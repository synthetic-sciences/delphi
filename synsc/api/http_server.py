"""HTTP API Server for Synsc Context - enables tool calling from coding agents.

This server supports multi-tenant operation where each user has isolated data.
User ID is extracted from the API key authentication and passed to all services.
"""

import asyncio
import hashlib
import os
import json
import secrets
import time
import uuid as _uuid
from dataclasses import dataclass
from typing import Annotated, Optional

import requests
import structlog
from fastapi import Depends, FastAPI, HTTPException, Header, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from synsc import __version__
from synsc.config import get_config
from synsc.database.connection import init_db
from synsc.api.mcp_server import create_server as create_mcp_server, set_current_api_key, _current_user_id

logger = structlog.get_logger(__name__)

# Rate limiting — database-backed via Supabase check_rate_limit() RPC
_RATE_LIMIT_WINDOW = 60  # seconds

# =============================================================================
# CLI AUTH SESSION STORAGE (database-backed via Supabase)
# =============================================================================


class CLIAuthSessions:
    """Database-backed CLI auth sessions using Supabase.

    Stores sessions in the ``cli_auth_sessions`` table so they are shared
    across all Gunicorn workers and survive deploys.
    """

    def __init__(self, ttl_seconds: int = 600):
        self._ttl = ttl_seconds

    def _get_db(self):
        from synsc.supabase_auth import get_supabase_client
        return get_supabase_client()

    def create_session(self) -> dict:
        """Create a new CLI auth session in the database."""
        user_code = f"{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
        device_code = secrets.token_urlsafe(32)
        now = time.time()

        row = {
            "device_code": device_code,
            "user_code": user_code,
            "status": "pending",
            "created_at": now,
            "expires_at": now + self._ttl,
        }

        try:
            self._get_db().insert("cli_auth_sessions", row)
        except Exception as e:
            logger.error("Failed to create CLI auth session in DB", error=str(e))

        return {**row, "user_id": None, "api_key": None, "user_name": None, "user_email": None}

    def get_session(self, device_code: str) -> Optional[dict]:
        """Get a session by device code."""
        try:
            rows = self._get_db().select("cli_auth_sessions", filters={"device_code": device_code})
            if not rows:
                return None
            session = rows[0]
            if time.time() > session["expires_at"] and session["status"] == "pending":
                self._get_db().update("cli_auth_sessions", {"status": "expired"}, {"device_code": device_code})
                session["status"] = "expired"
            return session
        except Exception as e:
            logger.error("Failed to get CLI auth session", error=str(e))
            return None

    def get_session_by_user_code(self, user_code: str) -> Optional[dict]:
        """Get a session by user code."""
        try:
            rows = self._get_db().select("cli_auth_sessions", filters={"user_code": user_code.upper()})
            if not rows:
                return None
            session = rows[0]
            if time.time() > session["expires_at"] and session["status"] == "pending":
                self._get_db().update("cli_auth_sessions", {"status": "expired"}, {"device_code": session["device_code"]})
                session["status"] = "expired"
            return session
        except Exception as e:
            logger.error("Failed to get CLI auth session by user_code", error=str(e))
            return None

    def complete_session(self, device_code: str, user_id: str, api_key: str,
                        user_name: str = None, user_email: str = None) -> bool:
        """Mark a session as completed with user info."""
        try:
            rows = self._get_db().select("cli_auth_sessions", filters={"device_code": device_code})
            if not rows or rows[0]["status"] != "pending":
                return False
            if time.time() > rows[0]["expires_at"]:
                self._get_db().update("cli_auth_sessions", {"status": "expired"}, {"device_code": device_code})
                return False

            return self._get_db().update("cli_auth_sessions", {
                "status": "completed",
                "user_id": user_id,
                "api_key": api_key,
                "user_name": user_name,
                "user_email": user_email,
            }, {"device_code": device_code})
        except Exception as e:
            logger.error("Failed to complete CLI auth session", error=str(e))
            return False


cli_auth_sessions = CLIAuthSessions()


@dataclass
class AuthContext:
    """Authentication context containing user info."""
    api_key: str
    user_id: str | None


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


async def verify_api_key(
    x_api_key: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthContext:
    """Verify API key from headers."""
    config = get_config()
    
    if not config.api.require_auth:
        # Use default dev user when auth is disabled
        # This matches the user created in setup_supabase.sql
        return AuthContext(api_key="dev-mode", user_id="00000000-0000-0000-0000-000000000001")
    
    api_key = x_api_key
    if not api_key and authorization:
        if authorization.startswith("Bearer "):
            api_key = authorization[7:]
    
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Provide via X-API-Key header or Authorization: Bearer header",
        )
    
    from synsc.supabase_auth import validate_api_key_hybrid
    
    is_valid, user_id = validate_api_key_hybrid(api_key)
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    return AuthContext(
        api_key=api_key,
        user_id=user_id if user_id != "local" else None,
    )


async def rate_limit(
    request: Request,
    auth: AuthContext = Depends(verify_api_key),
) -> None:
    """Apply rate limiting per API key via Supabase RPC."""
    config = get_config()
    key_hash = hashlib.sha256(auth.api_key.encode()).hexdigest()[:32]

    try:
        from synsc.supabase_auth import get_supabase_client
        result = get_supabase_client().rpc("check_rate_limit", {
            "p_key_hash": key_hash,
            "p_limit": config.api.rate_limit_per_minute,
            "p_window": _RATE_LIMIT_WINDOW,
        })
        # RPC returns a single boolean
        allowed = result if isinstance(result, bool) else True
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Max {config.api.rate_limit_per_minute} requests per minute.",
            )
    except HTTPException:
        raise
    except Exception as e:
        # Fail open: if Supabase is unreachable, allow the request through
        logger.warning("Rate limit check failed, allowing request", error=str(e))


# Admin user IDs (comma-separated env var)
_ADMIN_USER_IDS: set[str] = set(
    uid.strip()
    for uid in os.environ.get("ADMIN_USER_IDS", "").split(",")
    if uid.strip()
)


def _is_admin(user_id: str | None) -> bool:
    """Check if a user is an admin."""
    if not user_id:
        return False
    return user_id in _ADMIN_USER_IDS


# =============================================================================
# Response Cache (short TTL, per-user)
# =============================================================================

# Caches expensive query results to avoid repeated Supabase round-trips.
# Keyed by (user_id, endpoint_key). Invalidated on mutation (index/delete).
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


def _log_activity(
    user_id: str | None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    query: str | None = None,
    results_count: int | None = None,
    duration_ms: int | None = None,
    metadata: dict | None = None,
) -> None:
    """Fire-and-forget activity logging for HTTP endpoints. Never raises."""
    if not user_id:
        return
    try:
        from synsc.supabase_auth import get_supabase_auth
        auth_service = get_supabase_auth()
        auth_service.log_activity(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            query=query,
            results_count=results_count,
            duration_ms=duration_ms,
            metadata=metadata,
        )
    except Exception:
        logger.debug("Activity logging failed (non-critical)")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    import logging as _logging

    # Ensure structlog routes through stdlib logging (needed for Sentry
    # LoggingIntegration breadcrumbs).  When started via Gunicorn the
    # module-level configure() in main.py doesn't run, so we do it here.
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
        import sys as _sys

        # Use JSON in production (clean for Sentry/log drains),
        # colored console only in a real terminal
        if _sys.stderr.isatty():
            _renderer = structlog.dev.ConsoleRenderer()
        else:
            _renderer = structlog.processors.JSONRenderer()

        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                _renderer,
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

    config = get_config()

    # Initialize Sentry if DSN is configured
    sentry_dsn = os.environ.get("SENTRY_DSN")
    if sentry_dsn:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        def before_send(event, hint):
            """Filter out expected exceptions from Sentry reporting."""
            if "exc_info" in hint:
                exc_type, exc_value, tb = hint["exc_info"]
                # Ignore CancelledError - normal flow control when clients disconnect during SSE streams
                if exc_type.__name__ == "CancelledError":
                    return None
                # Ignore client disconnect errors during streaming
                if "ClientDisconnect" in exc_type.__name__:
                    return None
            return event

        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[
                FastApiIntegration(),
                StarletteIntegration(),
                # Breadcrumbs from INFO+ (context trail on errors),
                # only ERROR+ logs create standalone Sentry events
                LoggingIntegration(
                    level=_logging.INFO,          # breadcrumbs from INFO+
                    event_level=_logging.ERROR,   # Sentry events from ERROR+ only
                ),
            ],
            before_send=before_send,  # Filter expected exceptions
            traces_sample_rate=0.1,  # 10% of requests for performance monitoring
            environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
            release=f"synsc-context@{__version__}",
            send_default_pii=False,
        )
        logger.info("Sentry initialized", environment=os.environ.get("SENTRY_ENVIRONMENT", "production"))

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Init DB connection for this worker.
        init_db()

        # Load the sentence-transformers model (~500 MB) in this worker
        # process.  Runs in a thread so the event loop (and Gunicorn
        # heartbeat) stays alive during the ~15 s load.
        from synsc.embeddings.generator import get_paper_embedding_generator
        try:
            gen = await asyncio.to_thread(get_paper_embedding_generator)
            await asyncio.to_thread(gen.generate_single, "warmup")
            logger.info("Paper embedding model loaded and warmed up")
        except Exception as exc:
            logger.warning("Paper model load/warm-up failed: %s", exc)

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
        """Health check endpoint.  Must be fast — Render pings every ~15s."""
        return HealthResponse(
            status="healthy",
            version=__version__,
            server_name=config.server_name,
            uptime_seconds=time.time() - _start_time,
            database_backend="postgresql",
            vector_backend="pgvector",
            auth_backend="supabase",
        )
    
    @app.get("/config", tags=["Info"])
    async def get_public_config() -> dict:
        """Get public configuration for frontend."""
        return {
            "supabase_url": config.supabase.url,
            "supabase_publishable_key": config.supabase.publishable_key,
            "api_url": f"http://{config.api.host}:{config.api.port}",
        }
    
    # ==========================================================================
    # CLI Auth Endpoints (Device Flow for `npx synsc-context`)
    # ==========================================================================
    
    @app.post("/api/cli/auth/start", tags=["CLI Auth"])
    def cli_auth_start() -> JSONResponse:
        """Start a CLI authentication session (device flow).
        
        Returns a user_code for display and a device_code for polling.
        The user authenticates in the browser, then the CLI polls for completion.
        """
        session = cli_auth_sessions.create_session()
        
        logger.info("CLI auth session created", user_code=session["user_code"])
        
        return JSONResponse(content={
            "device_code": session["device_code"],
            "user_code": session["user_code"],
            "verification_url": f"{config.api.cors_origins[0].rstrip('/')}/cli-auth" if config.api.cors_origins else None,
            "expires_in": 600,   # 10 minutes
            "interval": 5,       # poll every 5 seconds
        })
    
    @app.get("/api/cli/auth/status/{device_code}", tags=["CLI Auth"])
    def cli_auth_status(device_code: str) -> JSONResponse:
        """Poll for CLI authentication completion.
        
        Returns 'pending', 'completed' (with api_key), or 'expired'.
        """
        session = cli_auth_sessions.get_session(device_code)
        
        if not session:
            return JSONResponse(
                content={"status": "expired", "error": "Session not found or expired"},
                status_code=404,
            )
        
        if session["status"] == "completed":
            return JSONResponse(content={
                "status": "completed",
                "api_key": session["api_key"],
                "user_name": session["user_name"],
                "user_email": session["user_email"],
            })
        
        if session["status"] == "expired":
            return JSONResponse(content={"status": "expired"})
        
        return JSONResponse(content={"status": "pending"})
    
    @app.post("/api/cli/auth/complete", tags=["CLI Auth"])
    async def cli_auth_complete(request: Request) -> JSONResponse:
        """Complete a CLI auth session (called by the web frontend after GitHub OAuth).

        Requires a valid Supabase access_token — the user_id is extracted from
        the verified JWT, never trusted from the request body.
        """
        body = await request.json()
        user_code = body.get("user_code", "").strip().upper()
        access_token = body.get("access_token", "").strip()

        if not user_code:
            return JSONResponse(
                content={"success": False, "error": "user_code is required"},
                status_code=400,
            )

        if not access_token:
            return JSONResponse(
                content={"success": False, "error": "access_token is required"},
                status_code=401,
            )

        # Verify the Supabase JWT and extract the real user_id
        from synsc.supabase_auth import get_supabase_auth
        auth_service = get_supabase_auth()
        user_id = auth_service.validate_jwt(access_token)

        if not user_id:
            return JSONResponse(
                content={"success": False, "error": "Invalid or expired access token"},
                status_code=401,
            )

        session = cli_auth_sessions.get_session_by_user_code(user_code)

        if not session:
            return JSONResponse(
                content={"success": False, "error": "Invalid or expired session code"},
                status_code=404,
            )

        if session["status"] != "pending":
            return JSONResponse(
                content={"success": False, "error": f"Session already {session['status']}"},
                status_code=409,
            )

        # User info from body is cosmetic only — user_id comes from the verified JWT
        user_name = body.get("user_name", "")
        user_email = body.get("user_email", "")
        
        # Generate API key for the user
        api_key = f"synsc_{secrets.token_hex(24)}"
        key_preview = api_key[:12]  # synsc_xxxx
        
        # Store the hashed key in the database if we have a user_id
        if user_id:
            try:
                from synsc.supabase_auth import get_supabase_client, _hash_api_key
                client = get_supabase_client()
                client.insert("api_keys", {
                    "user_id": user_id,
                    "name": "CLI Setup Key",
                    "key_hash": _hash_api_key(api_key),
                    "key_preview": key_preview,
                    "is_revoked": False,
                })
            except Exception as e:
                logger.warning("Failed to persist CLI auth key", error=str(e))
        
        # Mark session as completed
        success = cli_auth_sessions.complete_session(
            device_code=session["device_code"],
            user_id=user_id or "anonymous",
            api_key=api_key,
            user_name=user_name,
            user_email=user_email,
        )
        
        if not success:
            return JSONResponse(
                content={"success": False, "error": "Failed to complete session"},
                status_code=500,
            )
        
        logger.info("CLI auth completed", user_code=user_code, user_name=user_name)
        
        return JSONResponse(content={
            "success": True,
            "message": "Authentication completed. The CLI will pick up the key automatically.",
        })
    
    # ==========================================================================
    # Repository Endpoints (Code Context)
    # ==========================================================================
    
    @app.post("/v1/repositories/index", tags=["Code"])
    async def index_repository(
        request: IndexRepositoryRequest,
        auth: AuthContext = Depends(verify_api_key),
        _: None = Depends(rate_limit),
    ) -> JSONResponse:
        """Index a GitHub repository for semantic code search."""
        logger.info("API: Indexing repository", url=request.url, branch=request.branch, user_id=auth.user_id)
        start = time.time()
        try:
            from synsc.services.indexing_service import IndexingService
            service = IndexingService()
            result = await asyncio.to_thread(
                service.index_repository,
                request.url, request.branch, user_id=auth.user_id,
                deep_index=request.deep_index,
            )
            if auth.user_id:
                _cache_invalidate_user(auth.user_id)
            _log_activity(
                user_id=auth.user_id, action="index_repository", resource_type="repository",
                resource_id=result.get("repo_id"), duration_ms=int((time.time() - start) * 1000),
                metadata={"repo_url": request.url, "branch": request.branch, "source": "http"},
            )
            return JSONResponse(content=result)
        except Exception as e:
            logger.error("Indexing failed", error=str(e))
            return JSONResponse(content={"success": False, "error": "Repository indexing failed. Check server logs for details."}, status_code=500)
    
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
            
            start = time.time()
            progress_queue = asyncio.Queue()
            
            # CRITICAL: capture the running event loop NOW (on the async thread).
            # The progress_callback will be invoked from a ThreadPoolExecutor
            # worker where asyncio.get_event_loop() does NOT return this loop.
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
                if auth.user_id:
                    _cache_invalidate_user(auth.user_id)
                _log_activity(
                    user_id=auth.user_id, action="index_repository", resource_type="repository",
                    resource_id=result.get("repo_id") if isinstance(result, dict) else None,
                    duration_ms=int((time.time() - start) * 1000),
                    metadata={"repo_url": request.url, "branch": request.branch, "source": "http_stream"},
                )
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
            if auth.user_id:
                cached = _cache_get(auth.user_id, cache_key)
                if cached is not None:
                    return JSONResponse(content=cached)

            from synsc.services.indexing_service import IndexingService
            service = IndexingService()
            result = service.list_repositories(limit=limit, offset=offset, user_id=auth.user_id)

            if auth.user_id and result.get("success"):
                _cache_set(auth.user_id, cache_key, result)

            return JSONResponse(content=result)
        except Exception as e:
            logger.error("Failed to list repositories", error=str(e))
            return JSONResponse(content={"success": False, "error": "Failed to list repositories.", "repositories": [], "total": 0}, status_code=500)
    
    @app.get("/v1/repositories/{repo_id}", tags=["Code"])
    def get_repository(
        repo_id: str,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Get repository details by ID."""
        try:
            _uuid.UUID(repo_id)
        except ValueError:
            return JSONResponse(content={"success": False, "error": "Invalid repository ID format"}, status_code=400)
        try:
            from synsc.services.indexing_service import IndexingService
            service = IndexingService()
            result = service.get_repository(repo_id, user_id=auth.user_id)
            return JSONResponse(content=result)
        except Exception as e:
            logger.error("Failed to get repository", error=str(e))
            return JSONResponse(content={"success": False, "error": "Failed to retrieve repository."}, status_code=500)
    
    @app.delete("/v1/repositories/{repo_id}", tags=["Code"])
    def delete_repository(
        repo_id: str,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Delete a repository."""
        if not auth.user_id:
            return JSONResponse(content={"success": False, "error": "Authentication required"}, status_code=401)
        try:
            _uuid.UUID(repo_id)
        except ValueError:
            return JSONResponse(content={"success": False, "error": "Invalid repository ID format"}, status_code=400)
        try:
            from synsc.services.indexing_service import IndexingService
            service = IndexingService()
            result = service.delete_repository(repo_id, user_id=auth.user_id)
            _cache_invalidate_user(auth.user_id)
            _log_activity(
                user_id=auth.user_id, action="delete_repository", resource_type="repository",
                resource_id=repo_id, metadata={"source": "http"},
            )
            return JSONResponse(content=result)
        except Exception as e:
            logger.error("Failed to delete repository", error=str(e))
            return JSONResponse(content={"success": False, "error": "Failed to delete repository."}, status_code=500)
    
    @app.post("/v1/files/get", tags=["Code"])
    def get_file(
        request: GetFileRequest,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Get file content from a repository."""
        try:
            _uuid.UUID(request.repo_id)
        except ValueError:
            return JSONResponse(
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
        
        return JSONResponse(content=result)
    
    @app.post("/v1/search/code", tags=["Code"])
    def search_code(
        request: SearchCodeRequest,
        auth: AuthContext = Depends(verify_api_key),
        _: None = Depends(rate_limit),
    ) -> JSONResponse:
        """Search code using natural language or keywords."""
        logger.info("API: Searching code", query=request.query, user_id=auth.user_id)
        start = time.time()
        try:
            from synsc.services.search_service import SearchService
            service = SearchService(user_id=auth.user_id)
            result = service.search_code(
                query=request.query,
                repo_ids=request.repo_ids,
                language=request.language,
                file_pattern=request.file_pattern,
                top_k=request.top_k,
            )
            results_count = len(result.get("results", [])) if isinstance(result, dict) else 0
            _log_activity(
                user_id=auth.user_id, action="search_code", resource_type="search",
                query=request.query, results_count=results_count,
                duration_ms=int((time.time() - start) * 1000),
                metadata={"source": "http"},
            )
            return JSONResponse(content=result)
        except Exception as e:
            logger.error("Code search failed", error=str(e))
            return JSONResponse(
                content={"error": "Code search failed."},
                status_code=500,
            )
    
    @app.post("/v1/symbols/search", tags=["Code"])
    def search_symbols(
        request: SearchSymbolsRequest,
        auth: AuthContext = Depends(verify_api_key),
        _: None = Depends(rate_limit),
    ) -> JSONResponse:
        """Search for code symbols (functions, classes, methods)."""
        logger.info("API: Searching symbols", name=request.name, user_id=auth.user_id)
        start = time.time()
        from synsc.services.symbol_service import SymbolService
        service = SymbolService(user_id=auth.user_id)
        result = service.search_symbols(
            name=request.name,
            repo_ids=request.repo_ids,
            symbol_type=request.symbol_type,
            language=request.language,
            top_k=request.top_k,
            offset=request.offset,
        )
        results_count = len(result.get("symbols", [])) if isinstance(result, dict) else 0
        _log_activity(
            user_id=auth.user_id, action="search_symbols", resource_type="search",
            query=request.name, results_count=results_count,
            duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "http"},
        )
        return JSONResponse(content=result)
    
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
        _: None = Depends(rate_limit),
    ) -> JSONResponse:
        """Index a research paper from arXiv or URL."""
        import tempfile
        import os
        
        logger.info("API: Indexing paper", arxiv_id=request.arxiv_id, url=request.url, user_id=auth.user_id)
        if not auth.user_id:
            return JSONResponse(content={"success": False, "error": "Authentication required"}, status_code=401)
        
        from synsc.services.paper_service_supabase import get_paper_service
        from synsc.core.arxiv_client import parse_arxiv_id, download_arxiv_pdf, get_arxiv_metadata, ArxivError
        
        service = get_paper_service(user_id=auth.user_id)
        start = time.time()
        
        # Determine source arXiv ID
        source_arxiv_id = request.arxiv_id
        
        # Extract arXiv ID from URL if provided
        if request.url:
            try:
                source_arxiv_id = parse_arxiv_id(request.url)
            except ArxivError:
                pass
        
        if not source_arxiv_id:
            return JSONResponse(content={"success": False, "error": "Please provide an arXiv ID or URL"}, status_code=400)
        
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
                
                # Index the paper (run in thread pool to avoid blocking the event loop
                # during CPU-bound embedding generation — keeps Gunicorn heartbeats alive)
                import asyncio
                result = await asyncio.to_thread(
                    service.index_paper,
                    pdf_path=pdf_path,
                    source="arxiv",
                    arxiv_id=source_arxiv_id,
                    arxiv_metadata=arxiv_metadata,
                )
                _log_activity(
                    user_id=auth.user_id, action="index_paper", resource_type="paper",
                    resource_id=result.get("paper_id") if isinstance(result, dict) else None,
                    duration_ms=int((time.time() - start) * 1000),
                    metadata={"arxiv_id": source_arxiv_id, "source": "http"},
                )
                return JSONResponse(content=result)
            finally:
                # Clean up temp file
                try:
                    os.unlink(pdf_path)
                except OSError:
                    pass
                    
        except ArxivError as e:
            logger.error("ArXiv error", error=str(e))
            return JSONResponse(content={"success": False, "error": f"ArXiv error: {e}"}, status_code=400)
        except Exception as e:
            logger.error("Paper indexing failed", error=str(e))
            return JSONResponse(content={"success": False, "error": "Paper indexing failed. Check server logs for details."}, status_code=500)
    
    @app.post("/v1/papers/upload", tags=["Papers"])
    async def upload_paper(
        file: UploadFile = File(...),
        auth: AuthContext = Depends(verify_api_key),
        _: None = Depends(rate_limit),
    ) -> JSONResponse:
        """Upload and index a PDF paper."""
        import tempfile
        import os
        
        logger.info("API: Uploading paper", filename=file.filename, user_id=auth.user_id)
        if not auth.user_id:
            return JSONResponse(content={"success": False, "error": "Authentication required"}, status_code=401)
        
        # Validate file type
        if not file.filename or not file.filename.lower().endswith('.pdf'):
            return JSONResponse(content={"success": False, "error": "Only PDF files are supported"}, status_code=400)
        
        # Validate file size (50MB max)
        contents = await file.read()
        if len(contents) > 50 * 1024 * 1024:
            return JSONResponse(content={"success": False, "error": "File size exceeds 50MB limit"}, status_code=400)
        
        start = time.time()
        try:
            from synsc.services.paper_service_supabase import get_paper_service
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
                _log_activity(
                    user_id=auth.user_id, action="index_paper", resource_type="paper",
                    resource_id=result.get("paper_id") if isinstance(result, dict) else None,
                    duration_ms=int((time.time() - start) * 1000),
                    metadata={"filename": file.filename, "source": "http_upload"},
                )
                return JSONResponse(content=result)
            finally:
                # Clean up temp file
                os.unlink(tmp_path)
        except Exception as e:
            logger.error("Paper upload failed", error=str(e))
            return JSONResponse(content={"success": False, "error": "Paper upload failed. Check server logs for details."}, status_code=500)
    
    @app.get("/v1/papers", tags=["Papers"])
    def list_papers(
        limit: int = 50,
        offset: int = 0,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """List all indexed papers."""
        if not auth.user_id:
            return JSONResponse(content={"success": False, "error": "Authentication required"}, status_code=401)
        
        from synsc.services.paper_service_supabase import get_paper_service
        service = get_paper_service(user_id=auth.user_id)
        papers = service.list_papers(limit=limit)
        
        return JSONResponse(content={
            "success": True,
            "papers": papers,
            "total": len(papers),
        })
    
    @app.post("/v1/search/papers", tags=["Papers"])
    def search_papers(
        request: SearchPapersRequest,
        auth: AuthContext = Depends(verify_api_key),
        _: None = Depends(rate_limit),
    ) -> JSONResponse:
        """Search papers using semantic search."""
        logger.info("API: Searching papers", query=request.query, user_id=auth.user_id)
        if not auth.user_id:
            return JSONResponse(content={"success": False, "error": "Authentication required"}, status_code=401)
        
        start = time.time()
        from synsc.services.paper_service_supabase import get_paper_service
        service = get_paper_service(user_id=auth.user_id)
        result = service.search_papers(query=request.query, top_k=request.top_k)
        results_count = len(result.get("results", [])) if isinstance(result, dict) else 0
        _log_activity(
            user_id=auth.user_id, action="search_papers", resource_type="search",
            query=request.query, results_count=results_count,
            duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "http"},
        )
        return JSONResponse(content=result)
    
    @app.get("/v1/papers/{paper_id}/citations", tags=["Papers"])
    def get_citations(
        paper_id: str,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Get citations from a paper."""
        if not auth.user_id:
            return JSONResponse(content={"success": False, "error": "Authentication required"}, status_code=401)
        
        from synsc.services.paper_service_supabase import get_paper_service
        service = get_paper_service(user_id=auth.user_id)
        citations = service.get_citations(paper_id)
        
        return JSONResponse(content={
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
        if not auth.user_id:
            return JSONResponse(content={"success": False, "error": "Authentication required"}, status_code=401)
        
        from synsc.services.paper_service_supabase import get_paper_service
        service = get_paper_service(user_id=auth.user_id)
        equations = service.get_equations(paper_id)
        
        return JSONResponse(content={
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
        if not auth.user_id:
            return JSONResponse(content={"success": False, "error": "Authentication required"}, status_code=401)
        
        from synsc.services.paper_service_supabase import get_paper_service
        service = get_paper_service(user_id=auth.user_id)
        result = service.delete_paper(paper_id)
        
        if not result.get("success"):
            return JSONResponse(content=result, status_code=404)
        
        _log_activity(
            user_id=auth.user_id, action="delete_paper", resource_type="paper",
            resource_id=paper_id, metadata={"source": "http"},
        )
        return JSONResponse(content=result)
    
    # ==========================================================================
    # Dataset Endpoints (HuggingFace)
    # ==========================================================================

    @app.post("/v1/datasets/index", tags=["Datasets"])
    async def index_dataset(
        request: IndexDatasetRequest,
        auth: AuthContext = Depends(verify_api_key),
        _: None = Depends(rate_limit),
    ) -> JSONResponse:
        """Index a HuggingFace dataset for semantic search."""
        logger.info("API: Indexing dataset", hf_id=request.hf_id, user_id=auth.user_id)
        if not auth.user_id:
            return JSONResponse(content={"success": False, "error": "Authentication required"}, status_code=401)

        hf_token = _get_user_hf_token(auth.user_id)
        if not hf_token:
            return JSONResponse(
                content={"success": False, "error": "HuggingFace token required. Connect your HuggingFace account in Settings → API Keys."},
                status_code=403,
            )

        from synsc.services.dataset_service import get_dataset_service
        service = get_dataset_service(user_id=auth.user_id)

        start = time.time()
        result = await asyncio.to_thread(service.index_dataset, request.hf_id, hf_token)

        _log_activity(
            user_id=auth.user_id, action="index_dataset", resource_type="dataset",
            resource_id=result.get("dataset_id") if isinstance(result, dict) else None,
            duration_ms=int((time.time() - start) * 1000),
            metadata={"hf_id": request.hf_id, "source": "http"},
        )
        return JSONResponse(content=result)

    @app.get("/v1/datasets", tags=["Datasets"])
    def list_datasets(
        limit: int = 50,
        offset: int = 0,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """List all indexed datasets."""
        if not auth.user_id:
            return JSONResponse(content={"success": False, "error": "Authentication required"}, status_code=401)

        if not _user_has_hf_token(auth.user_id):
            return JSONResponse(
                content={"success": False, "error": "HuggingFace token required. Connect your HuggingFace account in Settings → API Keys.", "requires_hf_token": True},
                status_code=403,
            )

        from synsc.services.dataset_service import get_dataset_service
        service = get_dataset_service(user_id=auth.user_id)
        datasets = service.list_datasets(limit=limit)

        return JSONResponse(content={
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
        if not auth.user_id:
            return JSONResponse(content={"success": False, "error": "Authentication required"}, status_code=401)

        if not _user_has_hf_token(auth.user_id):
            return JSONResponse(
                content={"success": False, "error": "HuggingFace token required.", "requires_hf_token": True},
                status_code=403,
            )

        from synsc.services.dataset_service import get_dataset_service
        service = get_dataset_service(user_id=auth.user_id)
        dataset = service.get_dataset(dataset_id)

        if not dataset:
            return JSONResponse(content={"success": False, "error": "Dataset not found"}, status_code=404)

        return JSONResponse(content={"success": True, "dataset": dataset})

    @app.delete("/v1/datasets/{dataset_id}", tags=["Datasets"])
    def delete_dataset(
        dataset_id: str,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Delete a dataset. Public datasets are unmapped; private ones are fully removed."""
        if not auth.user_id:
            return JSONResponse(content={"success": False, "error": "Authentication required"}, status_code=401)

        if not _user_has_hf_token(auth.user_id):
            return JSONResponse(
                content={"success": False, "error": "HuggingFace token required.", "requires_hf_token": True},
                status_code=403,
            )

        from synsc.services.dataset_service import get_dataset_service
        service = get_dataset_service(user_id=auth.user_id)
        result = service.delete_dataset(dataset_id)

        if not result.get("success"):
            return JSONResponse(content=result, status_code=404)

        _log_activity(
            user_id=auth.user_id, action="delete_dataset", resource_type="dataset",
            resource_id=dataset_id, metadata={"source": "http"},
        )
        return JSONResponse(content=result)

    @app.post("/v1/search/datasets", tags=["Datasets"])
    def search_datasets(
        request: SearchDatasetsRequest,
        auth: AuthContext = Depends(verify_api_key),
        _: None = Depends(rate_limit),
    ) -> JSONResponse:
        """Search datasets using semantic search."""
        logger.info("API: Searching datasets", query=request.query, user_id=auth.user_id)
        if not auth.user_id:
            return JSONResponse(content={"success": False, "error": "Authentication required"}, status_code=401)

        if not _user_has_hf_token(auth.user_id):
            return JSONResponse(
                content={"success": False, "error": "HuggingFace token required.", "requires_hf_token": True},
                status_code=403,
            )

        start = time.time()
        from synsc.services.dataset_service import get_dataset_service
        service = get_dataset_service(user_id=auth.user_id)
        result = service.search_datasets(query=request.query, top_k=request.top_k)
        results_count = len(result.get("results", [])) if isinstance(result, dict) else 0
        _log_activity(
            user_id=auth.user_id, action="search_datasets", resource_type="search",
            query=request.query, results_count=results_count,
            duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "http"},
        )
        return JSONResponse(content=result)

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
        
        if not auth.user_id:
            return JSONResponse(content={"success": False, "error": "Authentication required"}, status_code=401)
        
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
        
        return JSONResponse(content=result)
    
    @app.get("/v1/jobs/{job_id}", tags=["Jobs"])
    def get_job_status(
        job_id: str,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Get job status."""
        try:
            _uuid.UUID(job_id)
        except ValueError:
            return JSONResponse(content={"success": False, "error": "Invalid job ID format"}, status_code=400)
        from synsc.services.job_queue_service import get_job_queue_service
        service = get_job_queue_service()
        result = service.get_job(job_id, user_id=auth.user_id)
        return JSONResponse(content=result)
    
    @app.get("/v1/jobs", tags=["Jobs"])
    def list_jobs(
        status: str | None = None,
        limit: int = 20,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """List jobs for the current user."""
        if not auth.user_id:
            return JSONResponse(content={"success": False, "error": "Authentication required"}, status_code=401)
        
        from synsc.services.job_queue_service import get_job_queue_service
        service = get_job_queue_service()
        result = service.list_jobs(user_id=auth.user_id, status=status, limit=limit)
        return JSONResponse(content=result)
    
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
        if not auth.user_id:
            return JSONResponse(
                content={"success": False, "error": "Authentication required", "keys": []}, 
                status_code=401
            )
        
        try:
            from synsc.supabase_auth import get_supabase_client
            client = get_supabase_client()
            
            # Fetch keys (don't return full key, just preview)
            keys = client.select_advanced(
                "api_keys",
                columns="id,name,key_preview,is_revoked,last_used_at,created_at",
                filters={"user_id": auth.user_id},
                order_by="created_at",
                order_desc=True,
            )
            
            return JSONResponse(content={
                "success": True,
                "keys": keys,
                "total": len(keys),
            })
            
        except Exception as e:
            logger.error("Failed to fetch API keys", error=str(e))
            return JSONResponse(content={
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
        if not auth.user_id:
            return JSONResponse(
                content={"success": False, "error": "Authentication required"}, 
                status_code=401
            )
        
        try:
            from synsc.supabase_auth import get_supabase_client, _hash_api_key
            client = get_supabase_client()
            
            # Generate API key
            key = f"synsc_{secrets.token_hex(24)}"
            key_preview = key[:12]  # synsc_xxxx
            key_hash = _hash_api_key(key)
            
            # Insert hash into database (plaintext key is NEVER stored)
            result = client.insert("api_keys", {
                "user_id": auth.user_id,
                "name": request.name,
                "key_hash": key_hash,
                "key_preview": key_preview,
                "is_revoked": False,
            })
            
            if result and result.get("id"):
                return JSONResponse(content={
                    "success": True,
                    "key": key,  # Only returned once!
                    "key_id": result["id"],
                    "name": request.name,
                    "message": "API key created. Save it now - you won't see it again!"
                })
            else:
                return JSONResponse(content={
                    "success": False,
                    "error": "Failed to create key"
                })
            
        except Exception as e:
            logger.error("Failed to create API key", error=str(e))
            return JSONResponse(content={
                "success": False,
                "error": "Failed to create API key."
            }, status_code=500)
    
    @app.post("/v1/keys/{key_id}/revoke", tags=["API Keys"])
    def revoke_api_key(
        key_id: str,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Revoke an API key (it will no longer work)."""
        if not auth.user_id:
            return JSONResponse(
                content={"success": False, "error": "Authentication required"}, 
                status_code=401
            )
        
        try:
            from synsc.supabase_auth import get_supabase_client
            client = get_supabase_client()
            
            # Update key to revoked (only if owned by user)
            success = client.update(
                "api_keys",
                {"is_revoked": True},
                {"id": key_id, "user_id": auth.user_id}
            )
            
            return JSONResponse(content={
                "success": success,
                "message": "API key revoked" if success else "Failed to revoke key"
            })
            
        except Exception as e:
            logger.error("Failed to revoke API key", error=str(e))
            return JSONResponse(content={
                "success": False,
                "error": "Failed to revoke API key."
            }, status_code=500)
    
    @app.delete("/v1/keys/{key_id}", tags=["API Keys"])
    def delete_api_key(
        key_id: str,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Permanently delete an API key."""
        if not auth.user_id:
            return JSONResponse(
                content={"success": False, "error": "Authentication required"}, 
                status_code=401
            )
        
        try:
            from synsc.supabase_auth import get_supabase_client
            client = get_supabase_client()
            
            # Delete key (only if owned by user)
            success = client.delete(
                "api_keys",
                {"id": key_id, "user_id": auth.user_id}
            )
            
            return JSONResponse(content={
                "success": success,
                "message": "API key deleted" if success else "Failed to delete key"
            })
            
        except Exception as e:
            logger.error("Failed to delete API key", error=str(e))
            return JSONResponse(content={
                "success": False,
                "error": "Failed to delete API key."
            }, status_code=500)
    
    # ==========================================================================
    # Security Audit Logging
    # ==========================================================================

    def _log_security_audit(
        user_id: str | None,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Fire-and-forget security audit logging. Never raises."""
        if not user_id:
            return
        try:
            from synsc.supabase_auth import get_supabase_client
            db = get_supabase_client()
            db.insert("security_audit_log", {
                "user_id": user_id,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "metadata": json.dumps(metadata) if metadata else "{}",
            })
        except Exception:
            logger.debug("Security audit logging failed (non-critical)")

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
        if not auth.user_id:
            return JSONResponse(
                content={"success": False, "error": "Authentication required"},
                status_code=401,
            )

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
                return JSONResponse(
                    content={
                        "success": False,
                        "error": "Invalid GitHub token. Ensure the token is valid and not expired.",
                    },
                    status_code=400,
                )
            github_user = resp.json()
            github_username = github_user.get("login", "")
            github_id = github_user.get("id")  # Capture numeric GitHub ID
        except Exception as e:
            logger.error("GitHub token validation failed", error=str(e))
            return JSONResponse(
                content={"success": False, "error": "Could not validate token with GitHub API."},
                status_code=502,
            )

        # Encrypt and store
        try:
            from synsc.services.token_encryption import encrypt_token
            from synsc.supabase_auth import get_supabase_client

            encrypted = encrypt_token(request.token)
            db = get_supabase_client()

            # Check if token already exists for this user
            existing = db.select("github_tokens", filters={"user_id": auth.user_id})

            if existing:
                # Update existing token
                db.update("github_tokens", {
                    "encrypted_token": encrypted,
                    "token_label": request.label,
                    "github_username": github_username,
                    "github_id": github_id,
                    "updated_at": "now()",
                }, {"user_id": auth.user_id})
            else:
                # Insert new token
                db.insert("github_tokens", {
                    "user_id": auth.user_id,
                    "encrypted_token": encrypted,
                    "token_label": request.label,
                    "github_username": github_username,
                    "github_id": github_id,
                })

            _log_security_audit(
                user_id=auth.user_id,
                action="token.store",
                resource_type="github_token",
                metadata={"github_username": github_username},
            )

            return JSONResponse(content={
                "success": True,
                "github_username": github_username,
                "label": request.label,
            })

        except RuntimeError as e:
            # TOKEN_ENCRYPTION_KEY not set
            logger.error("Token encryption not configured", error=str(e))
            return JSONResponse(
                content={"success": False, "error": "Token encryption is not configured on this server."},
                status_code=500,
            )
        except Exception as e:
            logger.error("Failed to store GitHub token", error=str(e))
            return JSONResponse(
                content={"success": False, "error": "Failed to store token."},
                status_code=500,
            )

    @app.get("/v1/github/token", tags=["GitHub"])
    def get_github_token_status(
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Check if a GitHub token is stored for the current user.

        Returns token metadata only — never the token value itself.
        """
        if not auth.user_id:
            return JSONResponse(
                content={"success": False, "error": "Authentication required"},
                status_code=401,
            )

        try:
            from synsc.supabase_auth import get_supabase_client
            db = get_supabase_client()
            rows = db.select(
                "github_tokens",
                columns="token_label,github_username,last_used_at,created_at,updated_at",
                filters={"user_id": auth.user_id},
            )

            if not rows:
                return JSONResponse(content={
                    "success": True,
                    "has_token": False,
                })

            token_info = rows[0]
            return JSONResponse(content={
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
            return JSONResponse(
                content={"success": False, "error": "Failed to check token status."},
                status_code=500,
            )

    @app.delete("/v1/github/token", tags=["GitHub"])
    def delete_github_token(
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Delete the stored GitHub token for the current user."""
        if not auth.user_id:
            return JSONResponse(
                content={"success": False, "error": "Authentication required"},
                status_code=401,
            )

        try:
            from synsc.supabase_auth import get_supabase_client
            db = get_supabase_client()
            deleted = db.delete("github_tokens", {"user_id": auth.user_id})

            _log_security_audit(
                user_id=auth.user_id,
                action="token.delete",
                resource_type="github_token",
            )

            return JSONResponse(content={
                "success": True,
                "deleted": deleted,
            })

        except Exception as e:
            logger.error("Failed to delete GitHub token", error=str(e))
            return JSONResponse(
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
        if not auth.user_id:
            return JSONResponse(
                content={"success": False, "error": "Authentication required"},
                status_code=401,
            )

        # Retrieve and decrypt token
        try:
            from synsc.supabase_auth import get_supabase_client
            from synsc.services.token_encryption import decrypt_token

            db = get_supabase_client()
            rows = db.select(
                "github_tokens", columns="encrypted_token",
                filters={"user_id": auth.user_id},
            )
            if not rows:
                return JSONResponse(
                    content={"success": False, "error": "No GitHub token stored. Add one in Settings."},
                    status_code=404,
                )

            github_token = decrypt_token(rows[0]["encrypted_token"])
        except Exception as e:
            logger.error("Failed to retrieve GitHub token for repo listing", error=str(e))
            return JSONResponse(
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
                    return JSONResponse(
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
                    return JSONResponse(
                        content={"success": False, "error": "GitHub API error", "detail": resp.text[:200]},
                        status_code=502,
                    )
                repos = resp.json()
                # GitHub returns total in Link header; approximate from page size
                total = None

            return JSONResponse(content={
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
            return JSONResponse(
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
        if not auth.user_id:
            return JSONResponse(
                content={"success": False, "error": "Authentication required"},
                status_code=401,
            )

        # Try to get stored GitHub token (optional — public repos work without)
        github_token = None
        try:
            from synsc.supabase_auth import get_supabase_client
            from synsc.services.token_encryption import decrypt_token

            db = get_supabase_client()
            rows = db.select(
                "github_tokens", columns="encrypted_token",
                filters={"user_id": auth.user_id},
            )
            if rows:
                github_token = decrypt_token(rows[0]["encrypted_token"])
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
                return JSONResponse(
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

            return JSONResponse(content={
                "success": True,
                "branches": branches,
                "default_branch": default_branch,
            })

        except Exception as e:
            logger.error("GitHub branch listing failed", error=str(e))
            return JSONResponse(
                content={"success": False, "error": "Failed to fetch branches."},
                status_code=502,
            )

    # ==========================================================================
    # HuggingFace Token Endpoints
    # ==========================================================================

    def _user_has_hf_token(user_id: str) -> bool:
        """Check if a user has a stored HuggingFace token."""
        try:
            from synsc.supabase_auth import get_supabase_client
            db = get_supabase_client()
            rows = db.select("huggingface_tokens", columns="id", filters={"user_id": user_id})
            return bool(rows)
        except Exception:
            return False

    def _get_user_hf_token(user_id: str) -> str | None:
        """Retrieve and decrypt the user's HuggingFace token. Returns None if not set."""
        try:
            from synsc.supabase_auth import get_supabase_client
            from synsc.services.token_encryption import decrypt_token

            db = get_supabase_client()
            rows = db.select(
                "huggingface_tokens", columns="encrypted_token",
                filters={"user_id": user_id},
            )
            if not rows:
                return None

            # Update last_used_at
            try:
                db.update("huggingface_tokens", {"last_used_at": "now()"}, {"user_id": user_id})
            except Exception:
                pass

            return decrypt_token(rows[0]["encrypted_token"])
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
        if not auth.user_id:
            return JSONResponse(
                content={"success": False, "error": "Authentication required"},
                status_code=401,
            )

        # Validate token against HuggingFace API
        try:
            resp = requests.get(
                "https://huggingface.co/api/whoami-v2",
                headers={"Authorization": f"Bearer {request.token}"},
                timeout=10,
            )
            if resp.status_code != 200:
                return JSONResponse(
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
            return JSONResponse(
                content={"success": False, "error": "Could not validate token with HuggingFace API."},
                status_code=502,
            )

        # Encrypt and store
        try:
            from synsc.services.token_encryption import encrypt_token
            from synsc.supabase_auth import get_supabase_client

            encrypted = encrypt_token(request.token)
            db = get_supabase_client()

            existing = db.select("huggingface_tokens", filters={"user_id": auth.user_id})

            if existing:
                db.update("huggingface_tokens", {
                    "encrypted_token": encrypted,
                    "token_label": request.label,
                    "hf_username": hf_username,
                    "updated_at": "now()",
                }, {"user_id": auth.user_id})
            else:
                db.insert("huggingface_tokens", {
                    "user_id": auth.user_id,
                    "encrypted_token": encrypted,
                    "token_label": request.label,
                    "hf_username": hf_username,
                })

            _log_security_audit(
                user_id=auth.user_id,
                action="token.store",
                resource_type="huggingface_token",
                metadata={"hf_username": hf_username},
            )

            return JSONResponse(content={
                "success": True,
                "hf_username": hf_username,
                "label": request.label,
            })

        except RuntimeError as e:
            logger.error("Token encryption not configured", error=str(e))
            return JSONResponse(
                content={"success": False, "error": "Token encryption is not configured on this server."},
                status_code=500,
            )
        except Exception as e:
            logger.error("Failed to store HuggingFace token", error=str(e))
            return JSONResponse(
                content={"success": False, "error": "Failed to store token."},
                status_code=500,
            )

    @app.get("/v1/huggingface/token", tags=["HuggingFace"])
    def get_huggingface_token_status(
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Check if a HuggingFace token is stored for the current user.

        Returns token metadata only — never the token value itself.
        """
        if not auth.user_id:
            return JSONResponse(
                content={"success": False, "error": "Authentication required"},
                status_code=401,
            )

        try:
            from synsc.supabase_auth import get_supabase_client
            db = get_supabase_client()
            rows = db.select(
                "huggingface_tokens",
                columns="token_label,hf_username,last_used_at,created_at,updated_at",
                filters={"user_id": auth.user_id},
            )

            if not rows:
                return JSONResponse(content={
                    "success": True,
                    "has_token": False,
                })

            token_info = rows[0]
            return JSONResponse(content={
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
            return JSONResponse(
                content={"success": False, "error": "Failed to check token status."},
                status_code=500,
            )

    @app.delete("/v1/huggingface/token", tags=["HuggingFace"])
    def delete_huggingface_token(
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Delete the stored HuggingFace token for the current user."""
        if not auth.user_id:
            return JSONResponse(
                content={"success": False, "error": "Authentication required"},
                status_code=401,
            )

        try:
            from synsc.supabase_auth import get_supabase_client
            db = get_supabase_client()
            deleted = db.delete("huggingface_tokens", {"user_id": auth.user_id})

            _log_security_audit(
                user_id=auth.user_id,
                action="token.delete",
                resource_type="huggingface_token",
            )

            return JSONResponse(content={
                "success": True,
                "deleted": deleted,
            })

        except Exception as e:
            logger.error("Failed to delete HuggingFace token", error=str(e))
            return JSONResponse(
                content={"success": False, "error": "Failed to delete token."},
                status_code=500,
            )

    # ==========================================================================
    # Activity Log Endpoints
    # ==========================================================================

    @app.get("/v1/activity", tags=["Activity"])
    def list_activity(
        action: str | None = None,
        time_range: str = "7d",
        limit: int = 50,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """List recent activity for the current user.
        
        Args:
            action: Filter by action type (e.g., 'search_code', 'index_repository')
            time_range: Time range filter ('24h', '7d', '30d')
            limit: Maximum number of activities to return
        """
        if not auth.user_id:
            return JSONResponse(
                content={"success": False, "error": "Authentication required", "activities": []}, 
                status_code=401
            )
        
        try:
            from synsc.supabase_auth import get_supabase_client
            from datetime import datetime, timedelta
            
            client = get_supabase_client()
            
            # Calculate time cutoff
            time_deltas = {
                "24h": timedelta(hours=24),
                "7d": timedelta(days=7),
                "30d": timedelta(days=30),
            }
            delta = time_deltas.get(time_range, timedelta(days=7))
            cutoff = (datetime.utcnow() - delta).isoformat()
            
            # Build filters
            filters = {"user_id": auth.user_id}
            if action and action != "all":
                filters["action"] = action
            
            # Fetch activities
            raw_activities = client.select_advanced(
                "activity_log",
                columns="*",
                filters=filters,
                gte={"created_at": cutoff},
                order_by="created_at",
                order_desc=True,
                limit=limit,
            )
            
            # Transform DB rows → frontend-expected format
            # DB has: id, user_id, action, resource_type, resource_id, query, 
            #         results_count, duration_ms, metadata (JSONB), created_at
            # Frontend expects: id, action, created_at, paper_id, paper_title,
            #                   repo_id, query, results_count, duration_ms, details
            activities = []
            for row in raw_activities:
                meta = row.get("metadata") or {}
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except (json.JSONDecodeError, TypeError):
                        meta = {}
                
                activity = {
                    "id": row.get("id"),
                    "action": row.get("action"),
                    "created_at": row.get("created_at"),
                    "query": row.get("query"),
                    "results_count": row.get("results_count"),
                    "duration_ms": row.get("duration_ms"),
                    # Flatten metadata into expected fields
                    "paper_id": meta.get("paper_id") or (row.get("resource_id") if row.get("resource_type") == "paper" else None),
                    "paper_title": meta.get("paper_title"),
                    "repo_id": meta.get("repo_id") or (row.get("resource_id") if row.get("resource_type") == "repository" else None),
                    # Pass metadata as 'details' for the frontend
                    "details": {
                        **meta,
                        "resource_type": row.get("resource_type"),
                        "response_time_ms": row.get("duration_ms"),
                    },
                }
                activities.append(activity)
            
            return JSONResponse(content={
                "success": True,
                "activities": activities,
                "total": len(activities),
            })
            
        except Exception as e:
            logger.error("Failed to fetch activity", error=str(e))
            return JSONResponse(content={
                "success": False,
                "error": "Failed to fetch activity.",
                "activities": []
            }, status_code=500)
    
    @app.get("/v1/activity/stats", tags=["Activity"])
    def get_activity_stats(
        time_range: str = "7d",
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Get activity statistics for the current user.
        
        Returns total queries, success rate, average response time.
        """
        if not auth.user_id:
            return JSONResponse(
                content={"success": False, "error": "Authentication required"}, 
                status_code=401
            )
        
        try:
            from synsc.supabase_auth import get_supabase_client
            from datetime import datetime, timedelta
            
            client = get_supabase_client()
            
            # Calculate time cutoff
            time_deltas = {
                "24h": timedelta(hours=24),
                "7d": timedelta(days=7),
                "30d": timedelta(days=30),
            }
            delta = time_deltas.get(time_range, timedelta(days=7))
            cutoff = (datetime.utcnow() - delta).isoformat()
            
            # Fetch activities
            activities = client.select_advanced(
                "activity_log",
                columns="action,metadata,duration_ms,created_at",
                filters={"user_id": auth.user_id},
                gte={"created_at": cutoff},
            )
            
            total = len(activities)
            
            # Calculate stats
            successful = sum(1 for a in activities if not (a.get("metadata") or {}).get("error"))
            success_rate = round((successful / total) * 100) if total > 0 else 100
            
            # Average response time
            response_times = []
            for a in activities:
                meta = a.get("metadata") or {}
                # duration_ms is a top-level column; also check metadata for legacy entries
                if a.get("duration_ms") is not None:
                    response_times.append(a["duration_ms"])
                elif "response_time_ms" in meta:
                    response_times.append(meta["response_time_ms"])
                elif "duration_ms" in meta:
                    response_times.append(meta["duration_ms"])
            
            avg_response_ms = sum(response_times) / len(response_times) if response_times else 0
            
            # Count by action
            action_counts: dict[str, int] = {}
            for a in activities:
                action_type = a.get("action", "unknown")
                action_counts[action_type] = action_counts.get(action_type, 0) + 1
            
            return JSONResponse(content={
                "success": True,
                "stats": {
                    "total": total,
                    "success_rate": success_rate,
                    "avg_response_ms": round(avg_response_ms, 2),
                    "by_action": action_counts,
                    "time_range": time_range,
                }
            })
            
        except Exception as e:
            logger.error("Failed to fetch activity stats", error=str(e))
            return JSONResponse(content={
                "success": False,
                "error": "Failed to fetch activity stats."
            }, status_code=500)
    
    # ==========================================================================
    # User Profile (Tier + Credits)
    # ==========================================================================

    @app.get("/v1/user/profile", tags=["User"])
    def get_user_profile(
        force_refresh: bool = False,
        auth: AuthContext = Depends(verify_api_key),
    ) -> JSONResponse:
        """Get user profile including tier, credits used, and credits available.

        Args:
            force_refresh: If True, bypasses cache and fetches fresh tier from external DB.
                          Frontend should use this on app load to ensure tier is current.
        """
        if not auth.user_id:
            return JSONResponse(
                content={"success": False, "error": "Authentication required"},
                status_code=401,
            )

        try:
            from synsc.supabase_auth import get_supabase_client
            from synsc.services.tier_service import (
                get_user_tier, get_credit_limit, usd_to_credits,
                get_github_id_for_user
            )

            # Get tier (force refresh on app load to ensure tier upgrades are immediate)
            tier = get_user_tier(auth.user_id, bypass_cache=force_refresh)
            credits_limit = get_credit_limit(tier)

            # Get cost summary (direct query, bypasses broken PostgREST RPC cache)
            client = get_supabase_client()
            rows = client.select("gemini_costs", "cost_usd", {"user_id": auth.user_id})
            cost_usd_used = sum(float(r.get("cost_usd", 0)) for r in rows)

            credits_used = usd_to_credits(cost_usd_used)
            credits_available = max(0, credits_limit - credits_used)
            credits_percent_used = (credits_used / credits_limit * 100) if credits_limit > 0 else 0

            # Get GitHub info
            github_id = get_github_id_for_user(auth.user_id)
            github_username = None
            if github_id:
                rows = client.select(
                    "github_tokens",
                    columns="github_username",
                    filters={"user_id": auth.user_id}
                )
                if rows:
                    github_username = rows[0].get("github_username")

            profile = {
                "user_id": auth.user_id,
                "tier": tier,
                "credits_limit": credits_limit,
                "credits_used": round(credits_used, 2),
                "credits_available": round(credits_available, 2),
                "credits_percent_used": round(credits_percent_used, 1),
                "cost_usd_used": round(cost_usd_used, 4),
                "github_id": github_id,
                "github_username": github_username,
            }

            return JSONResponse(content={
                "success": True,
                "profile": profile,
            })

        except Exception as e:
            logger.error("Failed to fetch user profile", error=str(e))
            return JSONResponse(
                content={"success": False, "error": "Failed to fetch user profile."},
                status_code=500,
            )

    # ==========================================================================
    # MCP JSON-RPC Bridge (enables remote streamable HTTP + uvx proxy)
    # ==========================================================================

    # Create MCP server instance once (tools have activity logging built in)
    _mcp_server = create_mcp_server()

    @app.post("/mcp", tags=["MCP"])
    async def mcp_endpoint(
        request: Request,
        auth: AuthContext = Depends(verify_api_key),
    ):
        """MCP JSON-RPC endpoint.

        Bridges HTTP to the MCP tool server. Used by:
        - Remote agents (streamable HTTP config)
        - Local uvx stdio proxy

        All tool calls go through mcp_server.py where activity is logged.
        """
        # Set auth context so MCP tools can resolve the user
        set_current_api_key(auth.api_key)
        _current_user_id.set(auth.user_id)

        body = await request.json()
        method = body.get("method")
        params = body.get("params", {})
        request_id = body.get("id")

        try:
            # --- initialize ---
            if method == "initialize":
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {
                            "name": "synsc-context",
                            "version": "0.1.0",
                        },
                    },
                }

            # --- tools/list ---
            elif method == "tools/list":
                tools_list = await _mcp_server.list_tools()
                tools = [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": tool.inputSchema,
                    }
                    for tool in tools_list
                ]
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"tools": tools},
                }

            # --- tools/call ---
            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})

                try:
                    result = await _mcp_server.call_tool(tool_name, arguments)

                    # Handle tuple (content, structured) or list (content only)
                    if isinstance(result, tuple) and len(result) == 2:
                        content_blocks, structured_content = result
                    else:
                        content_blocks = result
                        structured_content = None

                    content = []
                    for block in content_blocks:
                        if hasattr(block, "type") and hasattr(block, "text"):
                            content.append({"type": block.type, "text": block.text})
                        elif isinstance(block, dict):
                            content.append(block)
                        else:
                            content.append({"type": "text", "text": str(block)})

                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": content,
                            "structuredContent": structured_content,
                            "isError": False,
                        },
                    }

                except Exception as tool_error:
                    logger.exception("MCP tool execution error", tool=tool_name)
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [{"type": "text", "text": f"Tool error: {tool_error}"}],
                            "isError": True,
                        },
                    }

            # --- unknown method ---
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Unknown method: {method}"},
                }

        except Exception as e:
            logger.exception("MCP endpoint internal error")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": "Internal server error"},
            }

    return app


# Production app
app = create_app()


def run_http_server(host: str | None = None, port: int | None = None) -> None:
    """Run the HTTP API server."""
    import uvicorn
    
    config = get_config()
    
    host = host or config.api.host
    port = port or config.api.port
    
    logger.info(
        "Starting Synsc Context HTTP API",
        host=host, port=port,
        docs=f"http://{host}:{port}/docs",
        auth_required=config.api.require_auth,
    )
    
    uvicorn.run(
        "synsc.api.http_server:app",
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    run_http_server()
