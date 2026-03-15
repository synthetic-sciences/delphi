"""
Supabase authentication for GitHub Context.

All authentication is done through Supabase:
- API keys are stored in the api_keys table
- User IDs are validated against Supabase
- Activity is logged to Supabase
"""

import hashlib
import os
import time
from typing import Optional
from datetime import datetime, timezone

import httpx
import structlog

logger = structlog.get_logger(__name__)

# In-memory TTL cache for validated tokens → user_id
# Avoids hitting Supabase on every request (API key validation = 2 HTTP calls)
_AUTH_CACHE: dict[str, tuple[str, float]] = {}  # key_hash → (user_id, expires_at)
_AUTH_CACHE_TTL = 300  # 5 minutes


def _hash_api_key(raw_key: str) -> str:
    """
    Hash an API key with SHA-256 for secure storage and comparison.

    The raw key is never stored — only this hash is persisted in the
    ``api_keys`` table. On every validation request the incoming key is
    hashed with the same function and compared against the stored digest.

    Args:
        raw_key: The plaintext API key (e.g. ``synsc_abc123…``)

    Returns:
        Hex-encoded SHA-256 digest (64 characters)
    """
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


# Supabase configuration from environment (REQUIRED)
# Support both new naming (secret/publishable) and legacy (service_role/anon)
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SECRET_KEY = (
    os.getenv("SUPABASE_SECRET_KEY") or 
    os.getenv("SUPABASE_SERVICE_ROLE_KEY") or  # Common variation
    os.getenv("SUPABASE_SERVICE_KEY", "")
)

SUPABASE_PUBLISHABLE_KEY = (
    os.getenv("SUPABASE_PUBLISHABLE_KEY") or
    os.getenv("SUPABASE_ANON_KEY", "")
)

# JWT secret for HS256 signature verification (Supabase Dashboard → Settings → API → JWT Secret)
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

# JWKS client for ES256 verification (newer Supabase projects use asymmetric keys)
_jwks_client = None


def _get_jwks_client():
    """Get or create a cached PyJWKClient for the Supabase JWKS endpoint."""
    global _jwks_client
    if _jwks_client is None and SUPABASE_URL:
        import jwt as _jwt
        _jwks_client = _jwt.PyJWKClient(
            f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json",
            cache_keys=True,
            lifespan=3600,  # Cache keys for 1 hour
        )
    return _jwks_client


# Backward compatibility alias
SUPABASE_SERVICE_KEY = SUPABASE_SECRET_KEY


def is_supabase_configured() -> bool:
    """Check if Supabase is configured."""
    return bool(SUPABASE_URL and SUPABASE_SECRET_KEY)


class SupabaseREST:
    """Direct REST API client for Supabase.

    Uses a **persistent** ``httpx.Client`` with keep-alive so that TCP
    connections are reused across requests instead of opening a new
    socket per call.
    """

    def __init__(self, url: str, api_key: str):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        # Persistent connection pool — reuses TCP connections
        self._client = httpx.Client(
            timeout=30,
            headers=self.headers,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Shut down the underlying connection pool."""
        self._client.close()

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------

    def select(self, table: str, columns: str = "*", filters: dict = None) -> list:
        """Select rows from a table."""
        url = f"{self.url}/rest/v1/{table}?select={columns}"
        if filters:
            for key, value in filters.items():
                url += f"&{key}=eq.{value}"

        try:
            response = self._client.get(url)
            if response.status_code == 200:
                return response.json()
            logger.warning("Supabase select failed", table=table, status=response.status_code)
        except Exception as e:
            logger.error("Supabase select error", error=str(e))
        return []

    def update(self, table: str, data: dict, filters: dict) -> bool:
        """Update rows in a table."""
        url = f"{self.url}/rest/v1/{table}"
        query_parts = [f"{key}=eq.{value}" for key, value in filters.items()]
        if query_parts:
            url += "?" + "&".join(query_parts)

        try:
            response = self._client.patch(url, json=data)
            return response.status_code in [200, 204]
        except Exception as e:
            logger.error("Supabase update failed", error=str(e))
        return False

    def insert(self, table: str, data: dict, timeout: float = 30) -> dict:
        """Insert a row into a table."""
        url = f"{self.url}/rest/v1/{table}"
        try:
            response = self._client.post(url, json=data, timeout=timeout)
            if response.status_code in [200, 201]:
                result = response.json()
                return result[0] if result else {}
            logger.error("Supabase insert failed", table=table, status=response.status_code)
        except Exception as e:
            logger.error("Supabase insert error", table=table, error=str(e))
        return {}

    def insert_batch(self, table: str, rows: list[dict], timeout: float = 60, return_rows: bool = True) -> list[dict]:
        """Insert multiple rows into a table in a single request."""
        if not rows:
            return []
        url = f"{self.url}/rest/v1/{table}"
        headers = {**self.headers}
        if not return_rows:
            headers["Prefer"] = "return=minimal"
        try:
            response = self._client.post(url, headers=headers, json=rows, timeout=timeout)
            if response.status_code in [200, 201]:
                if return_rows:
                    return response.json()
                return [{}] * len(rows)
            logger.error("Supabase batch insert failed", table=table, status=response.status_code, row_count=len(rows))
        except Exception as e:
            logger.error("Supabase batch insert error", table=table, error=str(e), row_count=len(rows))
        return []

    def delete(self, table: str, filters: dict) -> bool:
        """Delete rows from a table."""
        url = f"{self.url}/rest/v1/{table}"
        query_parts = [f"{key}=eq.{value}" for key, value in filters.items()]
        if query_parts:
            url += "?" + "&".join(query_parts)

        try:
            response = self._client.delete(url)
            return response.status_code in [200, 204]
        except Exception as e:
            logger.error("Supabase delete failed", error=str(e))
        return False

    def rpc(self, function_name: str, params: dict, timeout: float = 30) -> list:
        """Call a Supabase RPC (database function)."""
        url = f"{self.url}/rest/v1/rpc/{function_name}"
        try:
            response = self._client.post(url, json=params, timeout=timeout)
            if response.status_code == 200:
                return response.json()
            logger.warning("Supabase RPC failed", function=function_name, status=response.status_code)
        except Exception as e:
            logger.error("Supabase RPC error", function=function_name, error=str(e))
        return []

    def select_advanced(
        self,
        table: str,
        columns: str = "*",
        filters: dict = None,
        order_by: str = None,
        order_desc: bool = False,
        limit: int = None,
        gte: dict = None,
    ) -> list:
        """Select rows with advanced options."""
        url = f"{self.url}/rest/v1/{table}?select={columns}"

        if filters:
            for key, value in filters.items():
                url += f"&{key}=eq.{value}"
        if gte:
            for key, value in gte.items():
                url += f"&{key}=gte.{value}"
        if order_by:
            direction = ".desc" if order_desc else ".asc"
            url += f"&order={order_by}{direction}"
        if limit:
            url += f"&limit={limit}"

        try:
            response = self._client.get(url)
            if response.status_code == 200:
                return response.json()
            logger.warning("Supabase select_advanced failed", table=table, status=response.status_code)
        except Exception as e:
            logger.error("Supabase select_advanced error", error=str(e))
        return []


# Singleton REST client
_rest_client: Optional[SupabaseREST] = None


def get_supabase_client() -> SupabaseREST:
    """Get the Supabase REST client.
    
    Raises:
        RuntimeError: If Supabase is not configured
    """
    global _rest_client
    if _rest_client is None:
        if not is_supabase_configured():
            raise RuntimeError(
                "Supabase is not configured. "
                "Set SUPABASE_URL and SUPABASE_SECRET_KEY (or legacy SUPABASE_SERVICE_KEY) environment variables."
            )
        _rest_client = SupabaseREST(SUPABASE_URL, SUPABASE_SECRET_KEY)
    return _rest_client


class SupabaseAuth:
    """Authentication service using Supabase."""

    def __init__(self):
        self.client = get_supabase_client()

    def validate_api_key(self, api_key: str) -> Optional[str]:
        """
        Validate an API key against Supabase and return the user_id.

        The incoming key is SHA-256 hashed before querying the database so
        that plaintext keys are never stored or compared on the wire.

        Args:
            api_key: The plaintext API key to validate (format: synsc_xxxx / ghctx_xxxx)

        Returns:
            user_id if valid, None otherwise
        """
        if not api_key:
            return None

        # Check for our key prefix
        if not (api_key.startswith("ghctx_") or api_key.startswith("synsc_")):
            return None

        key_hash = _hash_api_key(api_key)

        try:
            # Query the api_keys table by hash
            results = self.client.select(
                "api_keys",
                "user_id,is_revoked",
                {"key_hash": key_hash}
            )

            if results and len(results) > 0:
                key_data = results[0]

                # Check if key is revoked
                if key_data.get("is_revoked", False):
                    logger.warning("API key is revoked", key_preview=api_key[:12] + "...")
                    return None

                user_id = key_data.get("user_id")

                # Update last_used_at (fire and forget)
                try:
                    self.client.update(
                        "api_keys",
                        {"last_used_at": datetime.now(timezone.utc).isoformat()},
                        {"key_hash": key_hash},
                    )
                except Exception:
                    pass  # Don't fail validation if update fails

                return user_id

            return None

        except Exception as e:
            logger.error("Error validating API key via Supabase", error=str(e))
            return None

    def validate_jwt(self, token: str) -> Optional[str]:
        """
        Validate a Supabase JWT access token and return the user_id.

        Supports **both** signing algorithms used by Supabase:

        * **ES256** (newer projects) — verified via the JWKS endpoint
          at ``{SUPABASE_URL}/auth/v1/.well-known/jwks.json``.  The public
          key is cached for 1 hour.
        * **HS256** (older projects) — verified using the shared
          ``SUPABASE_JWT_SECRET``.

        Also checks expiration, audience (``authenticated``), and issuer.

        Args:
            token: Supabase JWT access token (starts with ``eyJ…``)

        Returns:
            user_id (UUID string) if valid, ``None`` otherwise
        """
        if not token:
            return None

        import jwt as _jwt

        # --- helper to extract user_id from a verified payload ----------
        def _extract_user_id(payload: dict) -> Optional[str]:
            iss = payload.get("iss", "")
            if SUPABASE_URL and not iss.startswith(SUPABASE_URL):
                logger.warning("JWT issuer mismatch", iss=iss)
                return None
            user_id = payload.get("sub")
            if not user_id:
                logger.warning("JWT missing sub claim")
            return user_id

        # --- 1) Try ES256 via JWKS (newer Supabase projects) -----------
        jwks = _get_jwks_client()
        if jwks:
            try:
                signing_key = jwks.get_signing_key_from_jwt(token)
                payload = _jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["ES256"],
                    audience="authenticated",
                    options={
                        "verify_signature": True,
                        "verify_exp": True,
                        "verify_aud": True,
                    },
                )
                return _extract_user_id(payload)
            except _jwt.ExpiredSignatureError:
                logger.warning("JWT expired")
                return None
            except _jwt.InvalidAudienceError:
                logger.warning("JWT invalid audience")
                return None
            except _jwt.PyJWKClientError:
                # JWKS fetch/key-match failed — fall through to HS256
                pass
            except _jwt.PyJWTError:
                # Signature mismatch with JWKS — fall through to HS256
                pass
            except Exception:
                pass  # network error etc. — try HS256

        # --- 2) Fall back to HS256 with shared secret ------------------
        if SUPABASE_JWT_SECRET:
            try:
                payload = _jwt.decode(
                    token,
                    SUPABASE_JWT_SECRET,
                    algorithms=["HS256"],
                    audience="authenticated",
                    options={
                        "verify_signature": True,
                        "verify_exp": True,
                        "verify_aud": True,
                    },
                )
                return _extract_user_id(payload)
            except _jwt.ExpiredSignatureError:
                logger.warning("JWT expired")
                return None
            except _jwt.InvalidAudienceError:
                logger.warning("JWT invalid audience")
                return None
            except _jwt.PyJWTError as e:
                logger.warning("JWT validation failed (HS256)", error=str(e))
                return None

        logger.warning("JWT validation skipped: no JWKS or JWT_SECRET available")
        return None

    def log_activity(
        self,
        user_id: str,
        action: str,
        resource_type: str = None,
        resource_id: str = None,
        query: str = None,
        results_count: int = None,
        duration_ms: int = None,
        metadata: dict = None,
    ) -> bool:
        """Log an activity to Supabase activity_log table.
        
        Args:
            user_id: User UUID
            action: Action type (e.g. 'index_repository', 'search_code', 'index_paper')
            resource_type: Resource category ('repository', 'paper', 'search')
            resource_id: UUID of the related resource (repo or paper)
            query: Search query text (truncated to 500 chars)
            results_count: Number of results returned
            duration_ms: Request duration in milliseconds
            metadata: Additional JSONB metadata (repo_name, paper_title, error, etc.)
        """
        try:
            data = {
                "user_id": user_id,
                "action": action,
            }
            if resource_type:
                data["resource_type"] = resource_type
            if resource_id:
                data["resource_id"] = resource_id
            if query:
                data["query"] = query[:500]
            if results_count is not None:
                data["results_count"] = results_count
            if duration_ms is not None:
                data["duration_ms"] = duration_ms
            if metadata:
                data["metadata"] = metadata  # Supabase REST handles JSONB serialization

            self.client.insert("activity_log", data)
            return True
        except Exception as e:
            logger.error("Failed to log activity", error=str(e))
            return False


# Singleton auth instance
_supabase_auth: Optional[SupabaseAuth] = None


def get_supabase_auth() -> SupabaseAuth:
    """Get the Supabase auth service."""
    global _supabase_auth
    if _supabase_auth is None:
        _supabase_auth = SupabaseAuth()
    return _supabase_auth


def validate_api_key(api_key: str) -> tuple[bool, Optional[str]]:
    """
    Validate an API key **or** Supabase JWT token.

    Two token types are supported:

    1. **Custom API keys** (prefixed ``ghctx_`` or ``synsc_``) – looked up in
       the ``api_keys`` table via ``SupabaseAuth.validate_api_key``.
    2. **Supabase JWT access tokens** (from the frontend OAuth login) –
       validated via the Supabase Auth ``/auth/v1/user`` endpoint.

    The custom-key path is tried first; only if it returns ``None`` do we fall
    through to JWT validation.

    Results are cached in-memory for 5 minutes to avoid repeated Supabase
    round-trips on every request.

    Args:
        api_key: The API key or JWT token to validate

    Returns:
        Tuple of (is_valid, user_id)
    """
    if not api_key:
        return False, None

    # Check in-memory cache first
    cache_key = hashlib.sha256(api_key.encode()).hexdigest()[:32]
    cached = _AUTH_CACHE.get(cache_key)
    if cached:
        user_id, expires_at = cached
        if time.monotonic() < expires_at:
            return True, user_id
        else:
            del _AUTH_CACHE[cache_key]

    auth = get_supabase_auth()

    # 1) Try custom API key validation (ghctx_… / synsc_…)
    user_id = auth.validate_api_key(api_key)
    if user_id:
        _AUTH_CACHE[cache_key] = (user_id, time.monotonic() + _AUTH_CACHE_TTL)
        return True, user_id

    # 2) Fall back to Supabase JWT validation (frontend OAuth tokens)
    user_id = auth.validate_jwt(api_key)
    if user_id:
        _AUTH_CACHE[cache_key] = (user_id, time.monotonic() + _AUTH_CACHE_TTL)
        return True, user_id

    return False, None


# Alias for backward compatibility
validate_api_key_hybrid = validate_api_key
