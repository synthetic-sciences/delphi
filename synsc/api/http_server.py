"""HTTP API Server for Synsc Context - enables tool calling from coding agents.

Multi-user server with GitHub OAuth, JWT sessions, and DB-backed API keys.
"""

import asyncio
import hashlib
import hmac
import os
import json
import time
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, date
from typing import Annotated
from uuid import UUID


class _SafeEncoder(json.JSONEncoder):
    """JSON encoder that handles UUID, datetime, and other DB types."""
    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        return super().default(obj)


def SafeJSONResponse(content, **kwargs):
    """JSONResponse that auto-serializes UUIDs and datetimes."""
    from starlette.responses import Response
    body = json.dumps(content, cls=_SafeEncoder).encode("utf-8")
    return Response(content=body, media_type="application/json", **kwargs)

import requests
import structlog


def _log_activity(
    user_id: str,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    query: str | None = None,
    results_count: int | None = None,
    duration_ms: int | None = None,
    metadata: dict | None = None,
) -> None:
    """Log a user activity to the activity_log table (best-effort)."""
    try:
        from synsc.database.connection import get_session
        from sqlalchemy import text as sa_text
        with get_session() as session:
            session.execute(
                sa_text(
                    "INSERT INTO activity_log "
                    "(user_id, action, resource_type, resource_id, query, results_count, duration_ms, metadata) "
                    "VALUES (:uid, :action, :rtype, :rid, :query, :rcnt, :dur, :meta)"
                ),
                {
                    "uid": user_id,
                    "action": action,
                    "rid": resource_id,
                    "rtype": resource_type,
                    "query": query,
                    "rcnt": results_count,
                    "dur": duration_ms,
                    "meta": json.dumps(metadata) if metadata else None,
                },
            )
            session.commit()
    except Exception as e:
        structlog.get_logger().warning("Failed to log activity", error=str(e))
from fastapi import Depends, FastAPI, HTTPException, Header, Query, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from synsc import __version__
from synsc.config import get_config
from synsc.database.connection import init_db, get_session
from synsc.api.mcp_server import (
    create_server as create_mcp_server,
    set_current_api_key,
    set_current_user_id,
)
from synsc.auth.sessions import create_session_token, verify_session_token

logger = structlog.get_logger(__name__)


def _encrypt_if_configured(token: str) -> str:
    """Encrypt a token if TOKEN_ENCRYPTION_KEY is set, else return plaintext."""
    if not os.getenv("TOKEN_ENCRYPTION_KEY", ""):
        return token
    from synsc.services.token_encryption import encrypt_token
    return encrypt_token(token)

def _decrypt_if_configured(stored: str) -> str:
    """Decrypt a token if TOKEN_ENCRYPTION_KEY is set, else return as-is."""
    if not os.getenv("TOKEN_ENCRYPTION_KEY", ""):
        return stored
    from synsc.services.token_encryption import decrypt_token
    return decrypt_token(stored)


@dataclass
class AuthContext:
    """Authentication context containing user info."""
    api_key: str
    user_id: str


# =============================================================================
# Request/Response Models
# =============================================================================


class IndexRepositoryRequest(BaseModel):
    """Request to index a repository."""
    url: str = Field(..., description="GitHub repository URL or shorthand (owner/repo)")
    branch: str = Field(default="main", description="Branch to index")
    deep_index: bool = Field(
        default=False,
        description="Deep indexing: full AST chunking per function/class (slower, higher quality)",
    )


class SearchCodeRequest(BaseModel):
    """Request to search code."""
    query: str = Field(..., description="Natural language query or keywords")
    repo_ids: list[str] | None = Field(default=None, description="Repository IDs to search")
    language: str | None = Field(default=None, description="Filter by programming language")
    file_pattern: str | None = Field(default=None, description="Glob pattern for file paths")
    top_k: int = Field(default=10, ge=1, le=100, description="Number of results")


class GetFileRequest(BaseModel):
    """Request to get file content."""
    repo_id: str = Field(..., description="Repository ID")
    file_path: str = Field(..., description="Path to file within repository")
    start_line: int | None = Field(default=None, description="Starting line (1-indexed)")
    end_line: int | None = Field(default=None, description="Ending line")


class SearchPapersRequest(BaseModel):
    """Request to search papers."""
    query: str = Field(..., description="Natural language search query")
    top_k: int = Field(default=10, ge=1, le=100, description="Number of results")
    paper_ids: list[str] | None = Field(default=None, description="Optional paper IDs to search within")


class IndexDatasetRequest(BaseModel):
    """Request to index a HuggingFace dataset."""
    hf_id: str = Field(..., description="HuggingFace dataset ID or URL (e.g. 'imdb', 'openai/gsm8k')")


class SearchDatasetsRequest(BaseModel):
    """Request to search datasets."""
    query: str = Field(..., description="Natural language search query")
    top_k: int = Field(default=10, ge=1, le=100, description="Number of results")


class SearchSymbolsRequest(BaseModel):
    """Request to search symbols."""
    name: str | None = Field(default=None, description="Symbol name to search for")
    repo_ids: list[str] | None = Field(default=None, description="Repository IDs to search")
    symbol_type: str | None = Field(default=None, description="Filter by type: function, class, method")
    language: str | None = Field(default=None, description="Filter by programming language")
    top_k: int = Field(default=25, ge=1, le=100, description="Number of results per page")
    offset: int = Field(default=0, ge=0, description="Pagination offset")


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    server_name: str
    uptime_seconds: float
    database_backend: str
    vector_backend: str
    auth_backend: str


class StoreGitHubTokenRequest(BaseModel):
    """Request to store a GitHub Personal Access Token."""
    token: str = Field(..., description="GitHub PAT (fine-grained recommended, contents:read)")
    label: str | None = Field(default=None, description="User label for this token")


class StoreHuggingFaceTokenRequest(BaseModel):
    """Request to store a HuggingFace API token."""
    token: str = Field(..., description="HuggingFace token (hf_...)")
    label: str | None = Field(default=None, description="User label for this token")


class CreateJobRequest(BaseModel):
    """Request to create an indexing job."""
    job_type: str = Field(..., description="Job type: 'repository' or 'paper'")
    target: str = Field(..., description="Repository URL or paper ID/URL")


# =============================================================================
# Dependencies
# =============================================================================


_start_time: float = time.time()

# =============================================================================
# Auth: GitHub OAuth + JWT Sessions + DB API Keys + SYSTEM_PASSWORD fallback
# =============================================================================
#
# Credential types (checked in order):
#   1. JWT session token — issued after GitHub OAuth login or SYSTEM_PASSWORD
#      login. Contains user_id. Verified via SERVER_SECRET.
#   2. DB API keys — created via dashboard, SHA-256 hashed in DB.
#      Used by AI agents / MCP tools.
#   3. SYSTEM_PASSWORD — optional admin fallback. If set, resolves to the
#      first admin user or creates one.
# =============================================================================


def _hash_api_key(key: str) -> str:
    """SHA-256 hash of an API key for DB lookup."""
    return hashlib.sha256(key.encode()).hexdigest()


def _validate_api_key_db(api_key: str) -> str | None:
    """Validate an API key against the database. Returns user_id or None."""
    if not api_key:
        return None

    key_hash = _hash_api_key(api_key)
    try:
        with get_session() as session:
            row = session.execute(
                text(
                    "SELECT user_id, is_revoked FROM api_keys "
                    "WHERE key_hash = :hash LIMIT 1"
                ),
                {"hash": key_hash},
            ).mappings().first()

            if not row or row["is_revoked"]:
                return None

            # Update last_used_at (best-effort)
            try:
                session.execute(
                    text("UPDATE api_keys SET last_used_at = now() WHERE key_hash = :hash"),
                    {"hash": key_hash},
                )
                session.commit()
            except Exception:
                pass

            return row["user_id"]
    except Exception as e:
        logger.error("Error validating API key", error=str(e))
        return None


def _get_or_create_admin_user() -> str:
    """Get the first admin user, or create one for SYSTEM_PASSWORD login."""
    with get_session() as session:
        row = session.execute(
            text("SELECT id FROM users WHERE is_admin = true ORDER BY created_at LIMIT 1")
        ).mappings().first()
        if row:
            return row["id"]

        # Create an admin user for SYSTEM_PASSWORD access
        import uuid
        admin_id = str(uuid.uuid4())
        session.execute(
            text(
                "INSERT INTO users (id, email, name, is_admin) "
                "VALUES (:id, 'admin@localhost', 'Admin', true)"
            ),
            {"id": admin_id},
        )
        session.commit()
        logger.info("Created admin user for SYSTEM_PASSWORD", user_id=admin_id)
        return admin_id


async def verify_api_key(
    x_api_key: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthContext:
    """Verify credentials from request headers.

    Checks (in order):
      1. JWT session token (from OAuth login or password login)
      2. DB-stored API key (for AI agents / MCP tools)
      3. SYSTEM_PASSWORD (admin fallback)
    Via: Authorization: Bearer <token> or X-API-Key: <token>
    """
    token = x_api_key
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization[7:]

    if not token:
        raise HTTPException(status_code=401, detail="Missing credentials.")

    # 1. Check JWT session token
    user_id = verify_session_token(token)
    if user_id:
        return AuthContext(api_key="session", user_id=user_id)

    # 2. Check DB-stored API key
    user_id = _validate_api_key_db(token)
    if user_id:
        return AuthContext(api_key=token, user_id=user_id)

    # 3. Check SYSTEM_PASSWORD (admin fallback)
    system_pw = os.getenv("SYSTEM_PASSWORD", "")
    if system_pw and hmac.compare_digest(token, system_pw):
        admin_id = _get_or_create_admin_user()
        return AuthContext(api_key="system_password", user_id=admin_id)

    raise HTTPException(status_code=401, detail="Invalid credentials.")


# =============================================================================
# Response Cache (short TTL, per-user)
# =============================================================================

_RESPONSE_CACHE: dict[str, tuple[dict, float]] = {}
_RESPONSE_CACHE_TTL = 30  # 30 seconds


def _cache_get(user_id: str, key: str) -> dict | None:
    """Get a cached response, or None if expired/missing."""
    entry = _RESPONSE_CACHE.get(f"{user_id}:{key}")
    if entry and time.monotonic() < entry[1]:
        return entry[0]
    return None


def _cache_set(user_id: str, key: str, data: dict) -> None:
    """Cache a response with TTL."""
    _RESPONSE_CACHE[f"{user_id}:{key}"] = (data, time.monotonic() + _RESPONSE_CACHE_TTL)


def _cache_invalidate_user(user_id: str) -> None:
    """Invalidate all cached responses for a user (after mutation)."""
    keys_to_delete = [k for k in _RESPONSE_CACHE if k.startswith(f"{user_id}:")]
    for k in keys_to_delete:
        del _RESPONSE_CACHE[k]


# =============================================================================
# Application Factory
# =============================================================================


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    import logging as _logging

    if not isinstance(
        structlog.get_config().get("wrapper_class"),
        type,
    ) or not issubclass(
        structlog.get_config().get("wrapper_class", object),
        structlog.stdlib.BoundLogger,
    ):
        _logging.basicConfig(
            format="%(message)s",
            level=_logging.INFO,
        )

        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="%H:%M:%S"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.dev.ConsoleRenderer(
                    colors=False,
                    pad_event_to=40,
                ),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

    # Silence noisy loggers
    _logging.getLogger("httpx").setLevel(_logging.WARNING)
    _logging.getLogger("httpcore").setLevel(_logging.WARNING)
    _logging.getLogger("sentence_transformers").setLevel(_logging.WARNING)
    _logging.getLogger("mcp.server.streamable_http").setLevel(_logging.WARNING)
    _logging.getLogger("mcp.server.lowlevel.server").setLevel(_logging.WARNING)

    config = get_config()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Init DB connection for this worker.
        init_db()

        # Load the sentence-transformers model (~500 MB) in this worker
        # process.  Runs in a thread so the event loop stays alive during
        # the ~15 s load.
        from synsc.embeddings.generator import get_paper_embedding_generator
        try:
            gen = await asyncio.to_thread(get_paper_embedding_generator)
            await asyncio.to_thread(gen.generate_single, "warmup")
            logger.info("Paper embedding model loaded and warmed up")
        except Exception as exc:
            logger.warning("Paper model load/warm-up failed: %s", exc)

        # Start MCP Streamable HTTP session manager (if attached to app)
        if hasattr(app, "_mcp_session_mgr") and app._mcp_session_mgr:
            import anyio
            mgr = app._mcp_session_mgr
            mgr._has_started = True
            tg = anyio.create_task_group()
            await tg.__aenter__()
            mgr._task_group = tg
            logger.info("MCP session manager task group initialized")
            try:
                yield
            finally:
                tg.cancel_scope.cancel()
                mgr._task_group = None
                try:
                    with anyio.fail_after(3):
                        await tg.__aexit__(None, None, None)
                except TimeoutError:
                    logger.warning("MCP task group shutdown timed out")
                except BaseException:
                    pass
        else:
            yield

    app = FastAPI(
        title="Synsc Context API",
        description="Unified code and paper indexing API for AI agents",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.api.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ==========================================================================
    # Health & Info Endpoints
    # ==========================================================================

    @app.get("/", tags=["Info"])
    async def root() -> dict:
        """API root - basic info."""
        return {
            "name": "Synsc Context API",
            "version": __version__,
            "docs": "/docs",
            "health": "/health",
        }

    @app.get("/health", response_model=HealthResponse, tags=["Info"])
    def health() -> HealthResponse:
        """Health check endpoint."""
        return HealthResponse(
            status="healthy",
            version=__version__,
            server_name=config.server_name,
            uptime_seconds=time.time() - _start_time,
            database_backend="postgresql",
            vector_backend="pgvector",
            auth_backend="github_oauth+jwt",
        )

    @app.get("/config", tags=["Info"])
    async def get_public_config() -> dict:
        """Get public configuration for frontend."""
        github_client_id = os.getenv("GITHUB_CLIENT_ID", "")
        return {
            "api_url": f"http://{config.api.host}:{config.api.port}",
            "github_oauth_enabled": bool(github_client_id),
            "system_password_enabled": bool(os.getenv("SYSTEM_PASSWORD", "")),
        }

    # ==========================================================================
    # Auth Endpoints
    # ==========================================================================

    # In-memory CSRF state store for OAuth (short-lived)
    _oauth_states: dict[str, float] = {}
    _OAUTH_STATE_TTL = 600  # 10 minutes

    def _cleanup_oauth_states() -> None:
        """Remove expired OAuth states."""
        now = time.time()
        expired = [s for s, t in _oauth_states.items() if now - t > _OAUTH_STATE_TTL]
        for s in expired:
            _oauth_states.pop(s, None)

    @app.get("/auth/github", tags=["Auth"])
    async def auth_github(request: Request) -> RedirectResponse:
        """Start GitHub OAuth flow — redirects to GitHub."""
        from synsc.auth.oauth import build_authorize_url, generate_state

        state = generate_state()
        _cleanup_oauth_states()
        _oauth_states[state] = time.time()

        # Build callback URL from the incoming request
        callback_url = str(request.url_for("auth_github_callback"))
        authorize_url = build_authorize_url(redirect_uri=callback_url, state=state)
        return RedirectResponse(url=authorize_url)

    @app.get("/auth/github/callback", tags=["Auth"])
    async def auth_github_callback(
        request: Request,
        code: str = Query(...),
        state: str = Query(...),
    ) -> RedirectResponse:
        """GitHub OAuth callback — exchanges code for user, issues JWT session.

        Redirects to the frontend with the session token as a query parameter.
        The frontend stores it and uses it for subsequent API requests.
        """
        from synsc.auth.oauth import exchange_code

        # Verify CSRF state
        if state not in _oauth_states:
            raise HTTPException(status_code=400, detail="Invalid or expired OAuth state.")
        _oauth_states.pop(state, None)

        callback_url = str(request.url_for("auth_github_callback"))

        try:
            gh_user = await exchange_code(code=code, redirect_uri=callback_url)
        except Exception as e:
            logger.error("GitHub OAuth exchange failed", error=str(e))
            raise HTTPException(status_code=400, detail="GitHub authentication failed.")

        # Find or create user in DB
        with get_session() as session:
            row = session.execute(
                text("SELECT id FROM users WHERE github_id = :gid"),
                {"gid": gh_user.github_id},
            ).mappings().first()

            if row:
                user_id = row["id"]
                # Update profile fields
                session.execute(
                    text(
                        "UPDATE users SET email = :email, name = :name, "
                        "avatar_url = :avatar, github_username = :ghu, "
                        "updated_at = now() WHERE id = :uid"
                    ),
                    {
                        "email": gh_user.email,
                        "name": gh_user.name,
                        "avatar": gh_user.avatar_url,
                        "ghu": gh_user.username,
                        "uid": user_id,
                    },
                )
            else:
                import uuid
                user_id = str(uuid.uuid4())
                # First user is admin
                is_first = session.execute(
                    text("SELECT COUNT(*) AS cnt FROM users")
                ).mappings().first()
                is_admin = (is_first["cnt"] == 0) if is_first else True

                session.execute(
                    text(
                        "INSERT INTO users (id, email, name, avatar_url, github_id, github_username, is_admin) "
                        "VALUES (:id, :email, :name, :avatar, :gid, :ghu, :admin)"
                    ),
                    {
                        "id": user_id,
                        "email": gh_user.email,
                        "name": gh_user.name,
                        "avatar": gh_user.avatar_url,
                        "gid": gh_user.github_id,
                        "ghu": gh_user.username,
                        "admin": is_admin,
                    },
                )
                logger.info("New user created via GitHub OAuth", user_id=user_id, github=gh_user.username)
            session.commit()

        # Issue JWT session token
        token = create_session_token(user_id=str(user_id), email=gh_user.email)

        # Redirect to frontend with token
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
        return RedirectResponse(url=f"{frontend_url}/auth/callback?token={token}")

    class LoginRequest(BaseModel):
        password: str = Field(description="System password (SYSTEM_PASSWORD env var)")

    @app.post("/auth/login", tags=["Auth"])
    async def login(request: LoginRequest) -> dict:
        """Authenticate with the system password (admin fallback).

        Returns a JWT session token for the admin user.
        """
        system_pw = os.getenv("SYSTEM_PASSWORD", "")
        if not system_pw:
            raise HTTPException(status_code=501, detail="SYSTEM_PASSWORD not configured. Use GitHub OAuth.")

        if not hmac.compare_digest(request.password, system_pw):
            raise HTTPException(status_code=401, detail="Invalid password.")

        admin_id = _get_or_create_admin_user()
        token = create_session_token(user_id=str(admin_id), email="admin@localhost")

        return {
            "success": True,
            "token": token,
            "message": "Authenticated. Use this token in Authorization: Bearer <token> headers.",
        }

    @app.get("/auth/me", tags=["Auth"])
    async def auth_me(auth: AuthContext = Depends(verify_api_key)) -> dict:
        """Get the current authenticated user's profile."""
        with get_session() as session:
            row = session.execute(
                text(
                    "SELECT id, email, name, avatar_url, github_username, is_admin, created_at "
                    "FROM users WHERE id = :uid"
                ),
                {"uid": auth.user_id},
            ).mappings().first()

        if not row:
            return {"user_id": auth.user_id, "email": None, "name": None}

        return {
            "user_id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "avatar_url": row["avatar_url"],
            "github_username": row["github_username"],
            "is_admin": row["is_admin"],
            "created_at": str(row["created_at"]) if row["created_at"] else None,
        }

    # ==========================================================================
    # Repository Endpoints (Code Context)
    # ==========================================================================

    @app.post("/v1/repositories/index", tags=["Code"])
    async def index_repository(
        request: IndexRepositoryRequest,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Index a GitHub repository for semantic code search."""
        logger.info("API: Indexing repository", url=request.url, branch=request.branch, user_id=auth.user_id)
        try:
            from synsc.services.indexing_service import IndexingService
            service = IndexingService()
            result = await asyncio.to_thread(
                service.index_repository,
                request.url, request.branch, user_id=auth.user_id,
                deep_index=request.deep_index,
            )
            _cache_invalidate_user(auth.user_id)
            _log_activity(auth.user_id, "index_repository", "repository", metadata={"url": request.url, "branch": request.branch})
            return SafeJSONResponse(content=result)
        except Exception as e:
            logger.error("Indexing failed", error=str(e))
            return SafeJSONResponse(content={"success": False, "error": "Repository indexing failed. Check server logs for details."}, status_code=500)

    @app.post("/v1/repositories/index/stream", tags=["Code"])
    async def index_repository_stream(
        request: IndexRepositoryRequest,
        auth: AuthContext = Depends(verify_api_key),
    ):
        """Index a repository with Server-Sent Events for progress updates."""
        logger.info("API: Streaming index repository", url=request.url, branch=request.branch, user_id=auth.user_id)

        async def event_stream():
            """Generate SSE events during indexing."""
            import asyncio
            import json

            progress_queue = asyncio.Queue()

            # CRITICAL: capture the running event loop NOW (on the async thread).
            loop = asyncio.get_running_loop()

            def progress_callback(stage: str, message: str, progress: float = 0, **kwargs):
                """Callback to receive progress updates (called from worker thread)."""
                try:
                    loop.call_soon_threadsafe(
                        progress_queue.put_nowait,
                        {"stage": stage, "message": message, "progress": progress, **kwargs}
                    )
                except Exception:
                    pass

            async def run_indexing():
                """Run indexing in thread pool."""
                import concurrent.futures
                loop = asyncio.get_event_loop()
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    try:
                        from synsc.services.indexing_service import IndexingService
                        service = IndexingService()
                        result = await loop.run_in_executor(
                            pool,
                            lambda: service.index_repository(
                                request.url,
                                request.branch,
                                user_id=auth.user_id,
                                progress_callback=progress_callback,
                                deep_index=request.deep_index,
                            )
                        )
                        return result
                    except Exception as e:
                        logger.error("Stream indexing failed", error=str(e))
                        return {"success": False, "error": "Repository indexing failed."}

            # Start indexing task
            task = asyncio.create_task(run_indexing())

            # Send initial event
            yield f"data: {json.dumps({'stage': 'starting', 'message': 'Starting indexing...', 'progress': 0})}\n\n"

            # Stream progress events
            while not task.done():
                try:
                    event = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Send heartbeat
                    yield f"data: {json.dumps({'stage': 'heartbeat', 'message': 'Processing...', 'progress': -1})}\n\n"

            # Get final result
            try:
                result = await task
                _cache_invalidate_user(auth.user_id)
                yield f"data: {json.dumps({'stage': 'complete', 'message': 'Indexing complete!', 'progress': 100, 'result': result})}\n\n"
            except Exception as e:
                logger.error("Stream indexing failed", error=str(e))
                yield f"data: {json.dumps({'stage': 'error', 'message': 'Repository indexing failed.', 'progress': 0})}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )

    @app.get("/v1/repositories", tags=["Code"])
    def list_repositories(
        limit: int = 50,
        offset: int = 0,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """List all indexed repositories."""
        try:
            cache_key = f"repos:{limit}:{offset}"
            cached = _cache_get(auth.user_id, cache_key)
            if cached is not None:
                return SafeJSONResponse(content=cached)

            from synsc.services.indexing_service import IndexingService
            service = IndexingService()
            result = service.list_repositories(limit=limit, offset=offset, user_id=auth.user_id)

            if result.get("success"):
                _cache_set(auth.user_id, cache_key, result)

            _log_activity(auth.user_id, "list_repositories", "repository")
            return SafeJSONResponse(content=result)
        except Exception as e:
            logger.error("Failed to list repositories", error=str(e))
            return SafeJSONResponse(content={"success": False, "error": "Failed to list repositories.", "repositories": [], "total": 0}, status_code=500)

    @app.get("/v1/repositories/{repo_id}", tags=["Code"])
    def get_repository(
        repo_id: str,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Get repository details by ID."""
        try:
            _uuid.UUID(repo_id)
        except ValueError:
            return SafeJSONResponse(content={"success": False, "error": "Invalid repository ID format"}, status_code=400)
        try:
            from synsc.services.indexing_service import IndexingService
            service = IndexingService()
            result = service.get_repository(repo_id, user_id=auth.user_id)
            return SafeJSONResponse(content=result)
        except Exception as e:
            logger.error("Failed to get repository", error=str(e))
            return SafeJSONResponse(content={"success": False, "error": "Failed to retrieve repository."}, status_code=500)

    @app.delete("/v1/repositories/{repo_id}", tags=["Code"])
    def delete_repository(
        repo_id: str,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Delete a repository."""
        try:
            _uuid.UUID(repo_id)
        except ValueError:
            return SafeJSONResponse(content={"success": False, "error": "Invalid repository ID format"}, status_code=400)
        try:
            from synsc.services.indexing_service import IndexingService
            service = IndexingService()
            result = service.delete_repository(repo_id, user_id=auth.user_id)
            _cache_invalidate_user(auth.user_id)
            return SafeJSONResponse(content=result)
        except Exception as e:
            logger.error("Failed to delete repository", error=str(e))
            return SafeJSONResponse(content={"success": False, "error": "Failed to delete repository."}, status_code=500)

    @app.post("/v1/files/get", tags=["Code"])
    def get_file(
        request: GetFileRequest,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Get file content from a repository."""
        try:
            _uuid.UUID(request.repo_id)
        except ValueError:
            return SafeJSONResponse(
                content={"success": False, "error": "Invalid repository ID format"},
                status_code=400,
            )
        from synsc.services.search_service import SearchService
        service = SearchService(user_id=auth.user_id)
        result = service.get_file(
            repo_id=request.repo_id,
            file_path=request.file_path,
            start_line=request.start_line,
            end_line=request.end_line,
        )

        _log_activity(auth.user_id, "get_file", "repository", resource_id=request.repo_id, metadata={"file_path": request.file_path})
        return SafeJSONResponse(content=result)

    @app.post("/v1/search/code", tags=["Code"])
    def search_code(
        request: SearchCodeRequest,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Search code using natural language or keywords."""
        logger.info("API: Searching code", query=request.query, user_id=auth.user_id)
        try:
            from synsc.services.search_service import SearchService
            t0 = int(time.time() * 1000)
            service = SearchService(user_id=auth.user_id)
            result = service.search_code(
                query=request.query,
                repo_ids=request.repo_ids,
                language=request.language,
                file_pattern=request.file_pattern,
                top_k=request.top_k,
            )
            dur = int(time.time() * 1000) - t0
            rc = len(result.get("results", []))
            _log_activity(auth.user_id, "search_code", "search", query=request.query, results_count=rc, duration_ms=dur)
            return SafeJSONResponse(content=result)
        except Exception as e:
            logger.error("Code search failed", error=str(e))
            return SafeJSONResponse(
                content={"error": "Code search failed."},
                status_code=500,
            )

    @app.post("/v1/symbols/search", tags=["Code"])
    def search_symbols(
        request: SearchSymbolsRequest,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Search for code symbols (functions, classes, methods)."""
        logger.info("API: Searching symbols", name=request.name, user_id=auth.user_id)
        from synsc.services.symbol_service import SymbolService
        t0 = int(time.time() * 1000)
        service = SymbolService(user_id=auth.user_id)
        result = service.search_symbols(
            name=request.name,
            repo_ids=request.repo_ids,
            symbol_type=request.symbol_type,
            language=request.language,
            top_k=request.top_k,
            offset=request.offset,
        )
        dur = int(time.time() * 1000) - t0
        rc = len(result.get("results", []))
        _log_activity(auth.user_id, "search_symbols", "search", query=request.name, results_count=rc, duration_ms=dur)
        return SafeJSONResponse(content=result)

    # ==========================================================================
    # Paper Endpoints (Research Context)
    # ==========================================================================

    class IndexPaperRequest(BaseModel):
        url: str | None = Field(default=None, description="arXiv URL or paper URL")
        arxiv_id: str | None = Field(default=None, description="arXiv paper ID (e.g., 1706.03762)")
        source_type: str = Field(default="arxiv", description="Source type: arxiv or pdf")

    @app.post("/v1/papers/index", tags=["Papers"])
    async def index_paper(
        request: IndexPaperRequest,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Index a research paper from arXiv or URL."""
        import tempfile
        import os

        logger.info("API: Indexing paper", arxiv_id=request.arxiv_id, url=request.url, user_id=auth.user_id)

        from synsc.services.paper_service import get_paper_service
        from synsc.core.arxiv_client import parse_arxiv_id, download_arxiv_pdf, get_arxiv_metadata, ArxivError

        service = get_paper_service(user_id=auth.user_id)

        # Determine source arXiv ID
        source_arxiv_id = request.arxiv_id

        # Extract arXiv ID from URL if provided
        if request.url:
            try:
                source_arxiv_id = parse_arxiv_id(request.url)
            except ArxivError:
                pass

        if not source_arxiv_id:
            return SafeJSONResponse(content={"success": False, "error": "Please provide an arXiv ID or URL"}, status_code=400)

        try:
            # Fetch arXiv metadata
            arxiv_metadata = None
            try:
                arxiv_metadata = get_arxiv_metadata(source_arxiv_id)
                logger.info("Fetched arXiv metadata", arxiv_id=source_arxiv_id)
            except Exception as e:
                logger.warning("Failed to fetch arXiv metadata", arxiv_id=source_arxiv_id)

            # Download PDF to temp file
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
                pdf_path = tmp_file.name

            try:
                download_arxiv_pdf(source_arxiv_id, pdf_path)

                # Index the paper (run in thread pool to avoid blocking the event loop)
                import asyncio
                result = await asyncio.to_thread(
                    service.index_paper,
                    pdf_path=pdf_path,
                    source="arxiv",
                    arxiv_id=source_arxiv_id,
                    arxiv_metadata=arxiv_metadata,
                )
                _log_activity(auth.user_id, "index_paper", "paper", metadata={"source": "arxiv", "arxiv_id": source_arxiv_id})
                return SafeJSONResponse(content=result)
            finally:
                # Clean up temp file
                try:
                    os.unlink(pdf_path)
                except OSError:
                    pass

        except ArxivError as e:
            logger.error("ArXiv error", error=str(e))
            return SafeJSONResponse(content={"success": False, "error": f"ArXiv error: {e}"}, status_code=400)
        except Exception as e:
            logger.error("Paper indexing failed", error=str(e))
            return SafeJSONResponse(content={"success": False, "error": "Paper indexing failed. Check server logs for details."}, status_code=500)

    @app.post("/v1/papers/upload", tags=["Papers"])
    async def upload_paper(
        file: UploadFile = File(...),
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Upload and index a PDF paper."""
        import tempfile
        import os

        logger.info("API: Uploading paper", filename=file.filename, user_id=auth.user_id)

        # Validate file type
        if not file.filename or not file.filename.lower().endswith('.pdf'):
            return SafeJSONResponse(content={"success": False, "error": "Only PDF files are supported"}, status_code=400)

        # Validate file size (50MB max)
        contents = await file.read()
        if len(contents) > 50 * 1024 * 1024:
            return SafeJSONResponse(content={"success": False, "error": "File size exceeds 50MB limit"}, status_code=400)

        try:
            from synsc.services.paper_service import get_paper_service
            service = get_paper_service(user_id=auth.user_id)

            # Save to temp file for processing
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                tmp.write(contents)
                tmp_path = tmp.name

            try:
                # Index the paper (run in thread pool to avoid blocking event loop)
                import asyncio
                result = await asyncio.to_thread(
                    service.index_paper,
                    pdf_path=tmp_path,
                    source="upload",
                    title=file.filename.replace('.pdf', ''),
                )
                return SafeJSONResponse(content=result)
            finally:
                # Clean up temp file
                os.unlink(tmp_path)
        except Exception as e:
            logger.error("Paper upload failed", error=str(e))
            return SafeJSONResponse(content={"success": False, "error": "Paper upload failed. Check server logs for details."}, status_code=500)

    @app.get("/v1/papers", tags=["Papers"])
    def list_papers(
        limit: int = 50,
        offset: int = 0,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """List all indexed papers."""
        from synsc.services.paper_service import get_paper_service
        service = get_paper_service(user_id=auth.user_id)
        papers = service.list_papers(limit=limit)

        _log_activity(auth.user_id, "list_papers", "paper")
        return SafeJSONResponse(content={
            "success": True,
            "papers": papers,
            "total": len(papers),
        })

    @app.post("/v1/search/papers", tags=["Papers"])
    def search_papers(
        request: SearchPapersRequest,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Search papers using semantic search."""
        logger.info("API: Searching papers", query=request.query, user_id=auth.user_id)

        from synsc.services.paper_service import get_paper_service
        t0 = int(time.time() * 1000)
        service = get_paper_service(user_id=auth.user_id)
        result = service.search_papers(query=request.query, top_k=request.top_k)
        dur = int(time.time() * 1000) - t0
        rc = len(result.get("results", []))
        _log_activity(auth.user_id, "search_papers", "search", query=request.query, results_count=rc, duration_ms=dur)
        return SafeJSONResponse(content=result)

    @app.get("/v1/papers/{paper_id}/citations", tags=["Papers"])
    def get_citations(
        paper_id: str,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Get citations from a paper."""
        from synsc.services.paper_service import get_paper_service
        service = get_paper_service(user_id=auth.user_id)
        citations = service.get_citations(paper_id)

        return SafeJSONResponse(content={
            "success": True,
            "paper_id": paper_id,
            "citations": citations,
            "count": len(citations),
        })

    @app.get("/v1/papers/{paper_id}/equations", tags=["Papers"])
    def get_equations(
        paper_id: str,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Get equations from a paper."""
        from synsc.services.paper_service import get_paper_service
        service = get_paper_service(user_id=auth.user_id)
        equations = service.get_equations(paper_id)

        return SafeJSONResponse(content={
            "success": True,
            "paper_id": paper_id,
            "equations": equations,
            "count": len(equations),
        })

    @app.delete("/v1/papers/{paper_id}", tags=["Papers"])
    def delete_paper(
        paper_id: str,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Delete a paper from user's library."""
        from synsc.services.paper_service import get_paper_service
        service = get_paper_service(user_id=auth.user_id)
        result = service.delete_paper(paper_id)

        if not result.get("success"):
            return SafeJSONResponse(content=result, status_code=404)

        return SafeJSONResponse(content=result)

    # ==========================================================================
    # Dataset Endpoints (HuggingFace)
    # ==========================================================================

    @app.post("/v1/datasets/index", tags=["Datasets"])
    async def index_dataset(
        request: IndexDatasetRequest,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Index a HuggingFace dataset for semantic search."""
        logger.info("API: Indexing dataset", hf_id=request.hf_id, user_id=auth.user_id)

        hf_token = _get_user_hf_token(auth.user_id)
        if not hf_token:
            return SafeJSONResponse(
                content={"success": False, "error": "HuggingFace token required. Store one via PUT /v1/huggingface/token."},
                status_code=403,
            )

        from synsc.services.dataset_service import get_dataset_service
        service = get_dataset_service(user_id=auth.user_id)

        result = await asyncio.to_thread(service.index_dataset, request.hf_id, hf_token)
        _log_activity(auth.user_id, "index_dataset", "dataset", metadata={"hf_id": request.hf_id})
        return SafeJSONResponse(content=result)

    @app.get("/v1/datasets", tags=["Datasets"])
    def list_datasets(
        limit: int = 50,
        offset: int = 0,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """List all indexed datasets."""
        if not _user_has_hf_token(auth.user_id):
            return SafeJSONResponse(
                content={"success": False, "error": "HuggingFace token required.", "requires_hf_token": True},
                status_code=403,
            )

        from synsc.services.dataset_service import get_dataset_service
        service = get_dataset_service(user_id=auth.user_id)
        datasets = service.list_datasets(limit=limit)

        return SafeJSONResponse(content={
            "success": True,
            "datasets": datasets,
            "total": len(datasets),
        })

    @app.get("/v1/datasets/{dataset_id}", tags=["Datasets"])
    def get_dataset(
        dataset_id: str,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Get detailed information about an indexed dataset."""
        if not _user_has_hf_token(auth.user_id):
            return SafeJSONResponse(
                content={"success": False, "error": "HuggingFace token required.", "requires_hf_token": True},
                status_code=403,
            )

        from synsc.services.dataset_service import get_dataset_service
        service = get_dataset_service(user_id=auth.user_id)
        dataset = service.get_dataset(dataset_id)

        if not dataset:
            return SafeJSONResponse(content={"success": False, "error": "Dataset not found"}, status_code=404)

        return SafeJSONResponse(content={"success": True, "dataset": dataset})

    @app.delete("/v1/datasets/{dataset_id}", tags=["Datasets"])
    def delete_dataset(
        dataset_id: str,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Delete a dataset. Public datasets are unmapped; private ones are fully removed."""
        if not _user_has_hf_token(auth.user_id):
            return SafeJSONResponse(
                content={"success": False, "error": "HuggingFace token required.", "requires_hf_token": True},
                status_code=403,
            )

        from synsc.services.dataset_service import get_dataset_service
        service = get_dataset_service(user_id=auth.user_id)
        result = service.delete_dataset(dataset_id)

        if not result.get("success"):
            return SafeJSONResponse(content=result, status_code=404)

        return SafeJSONResponse(content=result)

    @app.post("/v1/search/datasets", tags=["Datasets"])
    def search_datasets(
        request: SearchDatasetsRequest,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Search datasets using semantic search."""
        logger.info("API: Searching datasets", query=request.query, user_id=auth.user_id)

        if not _user_has_hf_token(auth.user_id):
            return SafeJSONResponse(
                content={"success": False, "error": "HuggingFace token required.", "requires_hf_token": True},
                status_code=403,
            )

        from synsc.services.dataset_service import get_dataset_service
        t0 = int(time.time() * 1000)
        service = get_dataset_service(user_id=auth.user_id)
        result = service.search_datasets(query=request.query, top_k=request.top_k)
        dur = int(time.time() * 1000) - t0
        rc = len(result.get("results", []))
        _log_activity(auth.user_id, "search_datasets", "search", query=request.query, results_count=rc, duration_ms=dur)
        return SafeJSONResponse(content=result)

    # ==========================================================================
    # Job Queue Endpoints
    # ==========================================================================

    @app.post("/v1/jobs", tags=["Jobs"])
    def create_job(
        request: CreateJobRequest,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Create an async indexing job."""
        logger.info("API: Creating job", job_type=request.job_type, target=request.target, user_id=auth.user_id)

        from synsc.services.job_queue_service import get_job_queue_service
        service = get_job_queue_service()

        if request.job_type == "repository":
            result = service.create_job(
                user_id=auth.user_id,
                repo_url=request.target,
                branch="main",
            )
        else:
            # For papers, create job with paper_source
            result = {
                "success": True,
                "message": f"Paper indexing job queued for: {request.target}",
                "job_type": "paper",
            }

        return SafeJSONResponse(content=result)

    @app.get("/v1/jobs/{job_id}", tags=["Jobs"])
    def get_job_status(
        job_id: str,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Get job status."""
        try:
            _uuid.UUID(job_id)
        except ValueError:
            return SafeJSONResponse(content={"success": False, "error": "Invalid job ID format"}, status_code=400)
        from synsc.services.job_queue_service import get_job_queue_service
        service = get_job_queue_service()
        result = service.get_job(job_id, user_id=auth.user_id)
        return SafeJSONResponse(content=result)

    @app.get("/v1/jobs", tags=["Jobs"])
    def list_jobs(
        status: str | None = None,
        limit: int = 20,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """List jobs for the current user."""
        from synsc.services.job_queue_service import get_job_queue_service
        service = get_job_queue_service()
        result = service.list_jobs(user_id=auth.user_id, status=status, limit=limit)
        return SafeJSONResponse(content=result)

    # ==========================================================================
    # API Key Management Endpoints
    # ==========================================================================

    class CreateKeyRequest(BaseModel):
        name: str = Field(default="API Key", description="Name for the API key")

    @app.get("/v1/keys", tags=["API Keys"])
    def list_api_keys(
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """List all API keys for the current user."""
        try:
            with get_session() as session:
                rows = session.execute(
                    text(
                        "SELECT id, name, key_preview, is_revoked, last_used_at, created_at "
                        "FROM api_keys WHERE user_id = :uid ORDER BY created_at DESC"
                    ),
                    {"uid": auth.user_id},
                ).mappings().all()

            keys = [dict(r) for r in rows]
            # Convert non-serializable types to strings
            for k in keys:
                for col in ("id", "last_used_at", "created_at"):
                    if k.get(col) is not None:
                        k[col] = str(k[col])

            return SafeJSONResponse(content={
                "success": True,
                "keys": keys,
                "total": len(keys),
            })

        except Exception as e:
            logger.error("Failed to fetch API keys", error=str(e))
            return SafeJSONResponse(content={
                "success": False,
                "error": "Failed to retrieve API keys.",
                "keys": []
            }, status_code=500)

    @app.post("/v1/keys", tags=["API Keys"])
    def create_api_key(
        request: CreateKeyRequest,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Create a new API key for the current user."""
        import secrets
        import hashlib

        try:
            # Generate API key
            key = f"synsc_{secrets.token_hex(24)}"
            key_preview = key[:12]  # synsc_xxxx
            key_hash = hashlib.sha256(key.encode()).hexdigest()

            with get_session() as session:
                result = session.execute(
                    text(
                        "INSERT INTO api_keys (user_id, name, key_hash, key_preview, is_revoked) "
                        "VALUES (:uid, :name, :hash, :preview, false) RETURNING id"
                    ),
                    {"uid": auth.user_id, "name": request.name, "hash": key_hash, "preview": key_preview},
                ).mappings().first()
                session.commit()

            if result:
                return SafeJSONResponse(content={
                    "success": True,
                    "key": key,  # Only returned once!
                    "key_id": str(result["id"]),
                    "name": request.name,
                    "message": "API key created. Save it now - you won't see it again!"
                })
            else:
                return SafeJSONResponse(content={
                    "success": False,
                    "error": "Failed to create key"
                })

        except Exception as e:
            logger.error("Failed to create API key", error=str(e))
            return SafeJSONResponse(content={
                "success": False,
                "error": "Failed to create API key."
            }, status_code=500)

    @app.post("/v1/keys/{key_id}/revoke", tags=["API Keys"])
    def revoke_api_key(
        key_id: str,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Revoke an API key (it will no longer work)."""
        try:
            with get_session() as session:
                result = session.execute(
                    text("UPDATE api_keys SET is_revoked = true WHERE id = :kid AND user_id = :uid"),
                    {"kid": key_id, "uid": auth.user_id},
                )
                session.commit()
                success = result.rowcount > 0

            return SafeJSONResponse(content={
                "success": success,
                "message": "API key revoked" if success else "Failed to revoke key"
            })

        except Exception as e:
            logger.error("Failed to revoke API key", error=str(e))
            return SafeJSONResponse(content={
                "success": False,
                "error": "Failed to revoke API key."
            }, status_code=500)

    @app.delete("/v1/keys/{key_id}", tags=["API Keys"])
    def delete_api_key(
        key_id: str,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Permanently delete an API key."""
        try:
            with get_session() as session:
                result = session.execute(
                    text("DELETE FROM api_keys WHERE id = :kid AND user_id = :uid"),
                    {"kid": key_id, "uid": auth.user_id},
                )
                session.commit()
                success = result.rowcount > 0

            return SafeJSONResponse(content={
                "success": success,
                "message": "API key deleted" if success else "Failed to delete key"
            })

        except Exception as e:
            logger.error("Failed to delete API key", error=str(e))
            return SafeJSONResponse(content={
                "success": False,
                "error": "Failed to delete API key."
            }, status_code=500)

    # ==========================================================================
    # GitHub Token Endpoints
    # ==========================================================================

    @app.put("/v1/github/token", tags=["GitHub"])
    def store_github_token(
        request: StoreGitHubTokenRequest,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Store or update an encrypted GitHub Personal Access Token.

        Validates the token against the GitHub API before storing.
        The token is Fernet-encrypted at rest and never returned via any endpoint.
        """
        # Validate token against GitHub API
        try:
            resp = requests.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {request.token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=10,
            )
            if resp.status_code != 200:
                return SafeJSONResponse(
                    content={
                        "success": False,
                        "error": "Invalid GitHub token. Ensure the token is valid and not expired.",
                    },
                    status_code=400,
                )
            github_user = resp.json()
            github_username = github_user.get("login", "")
            github_id = github_user.get("id")
        except Exception as e:
            logger.error("GitHub token validation failed", error=str(e))
            return SafeJSONResponse(
                content={"success": False, "error": "Could not validate token with GitHub API."},
                status_code=502,
            )

        # Encrypt and store
        try:
            with get_session() as session:
                existing = session.execute(
                    text("SELECT id FROM github_tokens WHERE user_id = :uid"),
                    {"uid": auth.user_id},
                ).mappings().all()

                if existing:
                    session.execute(
                        text(
                            "UPDATE github_tokens SET encrypted_token = :tok, token_label = :label, "
                            "github_username = :ghu, github_id = :ghi, updated_at = now() "
                            "WHERE user_id = :uid"
                        ),
                        {"tok": _encrypt_if_configured(request.token), "label": request.label, "ghu": github_username, "ghi": github_id, "uid": auth.user_id},
                    )
                else:
                    session.execute(
                        text(
                            "INSERT INTO github_tokens (user_id, encrypted_token, token_label, github_username, github_id) "
                            "VALUES (:uid, :tok, :label, :ghu, :ghi)"
                        ),
                        {"uid": auth.user_id, "tok": _encrypt_if_configured(request.token), "label": request.label, "ghu": github_username, "ghi": github_id},
                    )
                session.commit()

            return SafeJSONResponse(content={
                "success": True,
                "github_username": github_username,
                "label": request.label,
            })
        except Exception as e:
            logger.error("Failed to store GitHub token", error=str(e))
            return SafeJSONResponse(
                content={"success": False, "error": "Failed to store token."},
                status_code=500,
            )

    @app.get("/v1/github/token", tags=["GitHub"])
    def get_github_token_status(
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Check if a GitHub token is stored for the current user.

        Returns token metadata only -- never the token value itself.
        """
        try:
            with get_session() as session:
                rows = session.execute(
                    text(
                        "SELECT token_label, github_username, last_used_at, created_at, updated_at "
                        "FROM github_tokens WHERE user_id = :uid"
                    ),
                    {"uid": auth.user_id},
                ).mappings().all()

            if not rows:
                return SafeJSONResponse(content={
                    "success": True,
                    "has_token": False,
                })

            token_info = dict(rows[0])
            for col in ("last_used_at", "created_at", "updated_at"):
                if token_info.get(col) is not None:
                    token_info[col] = str(token_info[col])

            return SafeJSONResponse(content={
                "success": True,
                "has_token": True,
                "label": token_info.get("token_label"),
                "github_username": token_info.get("github_username"),
                "last_used_at": token_info.get("last_used_at"),
                "created_at": token_info.get("created_at"),
                "updated_at": token_info.get("updated_at"),
            })

        except Exception as e:
            logger.error("Failed to check GitHub token", error=str(e))
            return SafeJSONResponse(
                content={"success": False, "error": "Failed to check token status."},
                status_code=500,
            )

    @app.delete("/v1/github/token", tags=["GitHub"])
    def delete_github_token(
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Delete the stored GitHub token for the current user."""
        try:
            with get_session() as session:
                result = session.execute(
                    text("DELETE FROM github_tokens WHERE user_id = :uid"),
                    {"uid": auth.user_id},
                )
                session.commit()
                deleted = result.rowcount > 0

            return SafeJSONResponse(content={
                "success": True,
                "deleted": deleted,
            })

        except Exception as e:
            logger.error("Failed to delete GitHub token", error=str(e))
            return SafeJSONResponse(
                content={"success": False, "error": "Failed to delete token."},
                status_code=500,
            )

    @app.get("/v1/github/repos", tags=["GitHub"])
    def list_github_repos(
        page: int = 1,
        per_page: int = 30,
        q: str | None = None,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """List GitHub repositories accessible to the user's stored PAT.

        Uses the stored (encrypted) GitHub token to query the GitHub API.
        Supports optional search filtering via the `q` parameter.
        """
        # Retrieve and decrypt token
        try:
            with get_session() as session:
                rows = session.execute(
                    text("SELECT encrypted_token FROM github_tokens WHERE user_id = :uid"),
                    {"uid": auth.user_id},
                ).mappings().all()

            if not rows:
                return SafeJSONResponse(
                    content={"success": False, "error": "No GitHub token stored. Add one in Settings."},
                    status_code=404,
                )

            github_token = _decrypt_if_configured(rows[0]["encrypted_token"])
        except Exception as e:
            logger.error("Failed to retrieve GitHub token for repo listing", error=str(e))
            return SafeJSONResponse(
                content={"success": False, "error": "Failed to retrieve token."},
                status_code=500,
            )

        # Query GitHub API
        try:
            headers = {
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }

            if q:
                # Use the search API to filter by name
                resp = requests.get(
                    "https://api.github.com/search/repositories",
                    headers=headers,
                    params={
                        "q": f"{q} in:name fork:true",
                        "per_page": per_page,
                        "page": page,
                        "sort": "updated",
                    },
                    timeout=15,
                )
                if resp.status_code != 200:
                    return SafeJSONResponse(
                        content={"success": False, "error": "GitHub API error", "detail": resp.text[:200]},
                        status_code=502,
                    )
                data = resp.json()
                repos = data.get("items", [])
                total = data.get("total_count", 0)
            else:
                # List all repos the user has access to
                resp = requests.get(
                    "https://api.github.com/user/repos",
                    headers=headers,
                    params={
                        "per_page": per_page,
                        "page": page,
                        "sort": "updated",
                        "direction": "desc",
                    },
                    timeout=15,
                )
                if resp.status_code != 200:
                    return SafeJSONResponse(
                        content={"success": False, "error": "GitHub API error", "detail": resp.text[:200]},
                        status_code=502,
                    )
                repos = resp.json()
                # GitHub returns total in Link header; approximate from page size
                total = None

            return SafeJSONResponse(content={
                "success": True,
                "repos": [
                    {
                        "full_name": r["full_name"],
                        "name": r["name"],
                        "owner": r["owner"]["login"],
                        "private": r["private"],
                        "default_branch": r["default_branch"],
                        "description": r.get("description") or "",
                        "updated_at": r.get("updated_at"),
                        "language": r.get("language"),
                        "stargazers_count": r.get("stargazers_count", 0),
                    }
                    for r in repos
                ],
                "total": total,
                "page": page,
                "per_page": per_page,
            })

        except Exception as e:
            logger.error("GitHub repo listing failed", error=str(e))
            return SafeJSONResponse(
                content={"success": False, "error": "Failed to fetch repos from GitHub."},
                status_code=502,
            )

    @app.get("/v1/github/branches", tags=["GitHub"])
    def list_github_branches(
        owner: str,
        name: str,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """List branches for a GitHub repository.

        Uses the user's stored PAT if available (required for private repos),
        falls back to unauthenticated access for public repos.
        """
        # Try to get stored GitHub token (optional -- public repos work without)
        github_token = None
        try:
            with get_session() as session:
                rows = session.execute(
                    text("SELECT encrypted_token FROM github_tokens WHERE user_id = :uid"),
                    {"uid": auth.user_id},
                ).mappings().all()
            if rows:
                github_token = _decrypt_if_configured(rows[0]["encrypted_token"])
        except Exception:
            pass  # proceed without token

        try:
            headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            if github_token:
                headers["Authorization"] = f"Bearer {github_token}"

            resp = requests.get(
                f"https://api.github.com/repos/{owner}/{name}/branches",
                headers=headers,
                params={"per_page": 100},
                timeout=10,
            )
            if resp.status_code != 200:
                return SafeJSONResponse(
                    content={"success": False, "error": "Could not fetch branches"},
                    status_code=resp.status_code if resp.status_code in (403, 404) else 502,
                )

            branches = [b["name"] for b in resp.json()]

            # Also get default branch from repo metadata
            repo_resp = requests.get(
                f"https://api.github.com/repos/{owner}/{name}",
                headers=headers,
                timeout=5,
            )
            default_branch = "main"
            if repo_resp.status_code == 200:
                default_branch = repo_resp.json().get("default_branch", "main")

            return SafeJSONResponse(content={
                "success": True,
                "branches": branches,
                "default_branch": default_branch,
            })

        except Exception as e:
            logger.error("GitHub branch listing failed", error=str(e))
            return SafeJSONResponse(
                content={"success": False, "error": "Failed to fetch branches."},
                status_code=502,
            )

    # ==========================================================================
    # HuggingFace Token Endpoints
    # ==========================================================================

    def _user_has_hf_token(user_id: str) -> bool:
        """Check if a user has a stored HuggingFace token."""
        try:
            with get_session() as session:
                rows = session.execute(
                    text("SELECT id FROM huggingface_tokens WHERE user_id = :uid"),
                    {"uid": user_id},
                ).mappings().all()
            return bool(rows)
        except Exception:
            return False

    def _get_user_hf_token(user_id: str) -> str | None:
        """Retrieve and decrypt the user's HuggingFace token. Returns None if not set."""
        try:
            with get_session() as session:
                rows = session.execute(
                    text("SELECT encrypted_token FROM huggingface_tokens WHERE user_id = :uid"),
                    {"uid": user_id},
                ).mappings().all()

            if not rows:
                return None

            # Update last_used_at
            try:
                with get_session() as session:
                    session.execute(
                        text("UPDATE huggingface_tokens SET last_used_at = now() WHERE user_id = :uid"),
                        {"uid": user_id},
                    )
                    session.commit()
            except Exception:
                pass

            return _decrypt_if_configured(rows[0]["encrypted_token"])
        except Exception as e:
            logger.error("Failed to retrieve HuggingFace token", error=str(e))
            return None

    @app.put("/v1/huggingface/token", tags=["HuggingFace"])
    def store_huggingface_token(
        request: StoreHuggingFaceTokenRequest,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Store or update an encrypted HuggingFace API token.

        Validates the token against the HuggingFace API before storing.
        The token is Fernet-encrypted at rest and never returned via any endpoint.
        """
        # Validate token against HuggingFace API
        try:
            resp = requests.get(
                "https://huggingface.co/api/whoami-v2",
                headers={"Authorization": f"Bearer {request.token}"},
                timeout=10,
            )
            if resp.status_code != 200:
                return SafeJSONResponse(
                    content={
                        "success": False,
                        "error": "Invalid HuggingFace token. Ensure the token is valid and not expired.",
                    },
                    status_code=400,
                )
            hf_user = resp.json()
            hf_username = hf_user.get("name", "")
        except Exception as e:
            logger.error("HuggingFace token validation failed", error=str(e))
            return SafeJSONResponse(
                content={"success": False, "error": "Could not validate token with HuggingFace API."},
                status_code=502,
            )

        # Store token
        try:
            with get_session() as session:
                existing = session.execute(
                    text("SELECT id FROM huggingface_tokens WHERE user_id = :uid"),
                    {"uid": auth.user_id},
                ).mappings().all()

                if existing:
                    session.execute(
                        text(
                            "UPDATE huggingface_tokens SET encrypted_token = :tok, token_label = :label, "
                            "hf_username = :hfu, updated_at = now() WHERE user_id = :uid"
                        ),
                        {"tok": _encrypt_if_configured(request.token), "label": request.label, "hfu": hf_username, "uid": auth.user_id},
                    )
                else:
                    session.execute(
                        text(
                            "INSERT INTO huggingface_tokens (user_id, encrypted_token, token_label, hf_username) "
                            "VALUES (:uid, :tok, :label, :hfu)"
                        ),
                        {"uid": auth.user_id, "tok": _encrypt_if_configured(request.token), "label": request.label, "hfu": hf_username},
                    )
                session.commit()

            return SafeJSONResponse(content={
                "success": True,
                "hf_username": hf_username,
                "label": request.label,
            })

        except RuntimeError as e:
            logger.error("Token encryption not configured", error=str(e))
            return SafeJSONResponse(
                content={"success": False, "error": "Token encryption is not configured on this server."},
                status_code=500,
            )
        except Exception as e:
            logger.error("Failed to store HuggingFace token", error=str(e))
            return SafeJSONResponse(
                content={"success": False, "error": "Failed to store token."},
                status_code=500,
            )

    @app.get("/v1/huggingface/token", tags=["HuggingFace"])
    def get_huggingface_token_status(
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Check if a HuggingFace token is stored for the current user.

        Returns token metadata only -- never the token value itself.
        """
        try:
            with get_session() as session:
                rows = session.execute(
                    text(
                        "SELECT token_label, hf_username, last_used_at, created_at, updated_at "
                        "FROM huggingface_tokens WHERE user_id = :uid"
                    ),
                    {"uid": auth.user_id},
                ).mappings().all()

            if not rows:
                return SafeJSONResponse(content={
                    "success": True,
                    "has_token": False,
                })

            token_info = dict(rows[0])
            for col in ("last_used_at", "created_at", "updated_at"):
                if token_info.get(col) is not None:
                    token_info[col] = str(token_info[col])

            return SafeJSONResponse(content={
                "success": True,
                "has_token": True,
                "label": token_info.get("token_label"),
                "hf_username": token_info.get("hf_username"),
                "last_used_at": token_info.get("last_used_at"),
                "created_at": token_info.get("created_at"),
                "updated_at": token_info.get("updated_at"),
            })

        except Exception as e:
            logger.error("Failed to check HuggingFace token", error=str(e))
            return SafeJSONResponse(
                content={"success": False, "error": "Failed to check token status."},
                status_code=500,
            )

    @app.delete("/v1/huggingface/token", tags=["HuggingFace"])
    def delete_huggingface_token(
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Delete the stored HuggingFace token for the current user."""
        try:
            with get_session() as session:
                result = session.execute(
                    text("DELETE FROM huggingface_tokens WHERE user_id = :uid"),
                    {"uid": auth.user_id},
                )
                session.commit()
                deleted = result.rowcount > 0

            return SafeJSONResponse(content={
                "success": True,
                "deleted": deleted,
            })

        except Exception as e:
            logger.error("Failed to delete HuggingFace token", error=str(e))
            return SafeJSONResponse(
                content={"success": False, "error": "Failed to delete token."},
                status_code=500,
            )

    # ==========================================================================
    # User Profile
    # ==========================================================================

    @app.get("/v1/user/profile", tags=["User"])
    async def get_user_profile(auth: AuthContext = Depends(verify_api_key)):
        """Get user profile. Tier/credits are always unlimited in Delphi."""
        with get_session() as session:
            row = session.execute(
                text(
                    "SELECT id, email, name, avatar_url, github_username, is_admin "
                    "FROM users WHERE id = :uid"
                ),
                {"uid": auth.user_id},
            ).mappings().first()

        profile = {
            "user_id": auth.user_id,
            "email": row["email"] if row else None,
            "name": row["name"] if row else None,
            "avatar_url": row["avatar_url"] if row else None,
            "github_username": row["github_username"] if row else None,
            "is_admin": row["is_admin"] if row else False,
            "tier": "unlimited",
            "credits_used": 0,
            "credits_limit": None,
        }
        return profile

    # ==========================================================================
    # Activity Endpoints
    # ==========================================================================

    @app.get("/v1/activity", tags=["Activity"])
    def get_activity(
        time_range: str = "7d",
        limit: int = 100,
        action: str | None = None,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Get user activity log."""
        # Parse time range
        hours = 24 * 7  # default 7d
        if time_range.endswith("h"):
            hours = int(time_range[:-1])
        elif time_range.endswith("d"):
            hours = int(time_range[:-1]) * 24

        try:
            with get_session() as session:
                query = (
                    "SELECT id, action, resource_type, resource_id, query, "
                    "results_count, duration_ms, metadata, created_at "
                    "FROM activity_log WHERE user_id = :uid "
                    "AND created_at > now() - interval ':hours hours' "
                )
                params: dict = {"uid": auth.user_id, "hours": hours}

                if action:
                    query += "AND action = :action "
                    params["action"] = action

                query += "ORDER BY created_at DESC LIMIT :lim"
                params["lim"] = limit

                # Can't use interval with param binding, use explicit timestamp
                from datetime import datetime, timezone, timedelta
                cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

                rows = session.execute(
                    text(
                        "SELECT id, action, resource_type, resource_id, query, "
                        "results_count, duration_ms, metadata, created_at "
                        "FROM activity_log WHERE user_id = :uid "
                        "AND created_at > :cutoff "
                        + ("AND action = :action " if action else "")
                        + "ORDER BY created_at DESC LIMIT :lim"
                    ),
                    {"uid": auth.user_id, "cutoff": cutoff, "lim": limit, **({"action": action} if action else {})},
                ).mappings().all()

                activities = []
                for r in rows:
                    item = dict(r)
                    item["id"] = str(item["id"])
                    if item.get("resource_id"):
                        item["resource_id"] = str(item["resource_id"])
                    if item.get("created_at"):
                        item["created_at"] = str(item["created_at"])
                    if item.get("metadata") and isinstance(item["metadata"], dict):
                        item["details"] = item.pop("metadata")
                    else:
                        item.pop("metadata", None)
                    activities.append(item)

            return SafeJSONResponse(content={
                "success": True,
                "activities": activities,
                "total": len(activities),
            })
        except Exception as e:
            logger.error("Failed to fetch activity", error=str(e))
            return SafeJSONResponse(content={"success": True, "activities": [], "total": 0})

    @app.get("/v1/activity/stats", tags=["Activity"])
    def get_activity_stats(
        time_range: str = "7d",
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Get aggregated activity stats for the user."""
        hours = 24 * 7
        if time_range.endswith("h"):
            hours = int(time_range[:-1])
        elif time_range.endswith("d"):
            hours = int(time_range[:-1]) * 24

        try:
            from datetime import datetime, timezone, timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

            with get_session() as session:
                rows = session.execute(
                    text(
                        "SELECT action, COUNT(*) as cnt "
                        "FROM activity_log WHERE user_id = :uid "
                        "AND created_at > :cutoff "
                        "GROUP BY action"
                    ),
                    {"uid": auth.user_id, "cutoff": cutoff},
                ).mappings().all()

            by_action = {r["action"]: r["cnt"] for r in rows}
            total = sum(by_action.values())

            return SafeJSONResponse(content={
                "success": True,
                "stats": {
                    "total": total,
                    "by_action": by_action,
                },
            })
        except Exception as e:
            logger.error("Failed to fetch activity stats", error=str(e))
            return SafeJSONResponse(content={"success": True, "stats": {"total": 0, "by_action": {}}})

    # Return empty 404 (not JSON) for OAuth discovery so clients skip OAuth gracefully
    @app.get("/.well-known/{path:path}", include_in_schema=False)
    async def well_known_fallback(path: str):
        return JSONResponse(
            {"error": "not_supported", "error_description": "OAuth not supported"},
            status_code=404,
        )

    @app.post("/register", include_in_schema=False)
    async def register_fallback():
        return JSONResponse(
            {"error": "not_supported", "error_description": "OAuth not supported"},
            status_code=404,
        )

    return app


class _MCPMiddleware:
    """ASGI middleware that intercepts /mcp and routes to MCP transport."""

    def __init__(self, app, session_mgr):
        self.app = app
        self.session_mgr = session_mgr

    async def __call__(self, scope, receive, send):
        # Pass lifespan events to the inner app (triggers startup/shutdown hooks)
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return

        if scope["type"] == "http" and scope["path"] == "/mcp":
            # Extract Bearer token from headers
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode()
            token = auth_header[7:] if auth_header.startswith("Bearer ") else None

            if not token:
                resp = JSONResponse({"error": "Missing credentials"}, status_code=401)
                await resp(scope, receive, send)
                return

            # Validate credentials
            user_id = verify_session_token(token)
            api_key = None
            if not user_id:
                user_id = _validate_api_key_db(token)
                api_key = token
            if not user_id:
                system_pw = os.getenv("SYSTEM_PASSWORD", "")
                if system_pw and hmac.compare_digest(token, system_pw):
                    user_id = _get_or_create_admin_user()
            if not user_id:
                resp = JSONResponse({"error": "Invalid credentials"}, status_code=401)
                await resp(scope, receive, send)
                return

            set_current_api_key(api_key)
            set_current_user_id(user_id)

            await self.session_mgr.handle_request(scope, receive, send)
            return

        await self.app(scope, receive, send)


# Production app
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager as _SHSM

_mcp_srv = create_mcp_server()
_mcp_session_mgr = _SHSM(app=_mcp_srv._mcp_server, stateless=True)

_fastapi_app = create_app()
_fastapi_app._mcp_session_mgr = _mcp_session_mgr  # type: ignore[attr-defined]
app = _MCPMiddleware(_fastapi_app, _mcp_session_mgr)


def run_http_server():
    import uvicorn
    config = get_config()
    uvicorn.run(app, host=config.api.host, port=config.api.port)


if __name__ == "__main__":
    run_http_server()
