"""User tier management with external Supabase integration.

Tier System:
- Free: 5 credits ($0.50)
- Researcher: 50 credits ($5.00)
- Lab: 200 credits ($20.00)

Conversion: 1 credit = $0.10 USD

This module provides centralized tier lookup with caching and graceful degradation.
All errors default to Free tier (availability > strict enforcement).
"""

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import structlog

logger = structlog.get_logger(__name__)

# Tier definitions (1 credit = $0.10 USD)
TIER_CREDITS = {
    "free": 5,        # $0.50
    "researcher": 50, # $5.00
    "lab": 200,       # $20.00
    "benchmark": 500, # $50.00
}

TierName = Literal["free", "researcher", "lab", "benchmark"]

# In-memory cache with TTL (5 minutes)
# Format: {user_id: (tier, cached_at)}
_tier_cache: dict[str, tuple[TierName, datetime]] = {}
_CACHE_TTL = timedelta(minutes=5)


def get_tier_supabase_client():
    """Get external tier Supabase client (separate from main DB).

    Returns None if not configured (graceful degradation to Free tier).
    """
    from synsc.config import get_config
    from synsc.supabase_auth import SupabaseREST

    tier_config = get_config().tier_supabase
    if not tier_config.is_configured:
        logger.debug("Tier Supabase not configured, all users default to Free tier")
        return None

    try:
        return SupabaseREST(tier_config.url, tier_config.secret_key)
    except Exception as e:
        logger.error("Failed to create tier Supabase client", error=str(e))
        return None


def _get_github_id_from_auth(user_id: str) -> Optional[int]:
    """Get GitHub ID from Supabase auth identity data via get_github_id RPC.

    When a user logs in via GitHub OAuth, Supabase stores the GitHub numeric ID
    in auth.identities. The get_github_id RPC (migration 012) resolves this
    with SECURITY DEFINER access to the auth schema.

    Args:
        user_id: User UUID

    Returns:
        GitHub ID (numeric) or None
    """
    try:
        from synsc.supabase_auth import get_supabase_client

        db = get_supabase_client()
        result = db.rpc("get_github_id", {"p_user_id": user_id})

        if result is not None and result != []:
            # RPC returning a scalar comes back as the value directly
            github_id = result if not isinstance(result, list) else result[0] if result else None
            if github_id:
                return int(github_id)
        return None
    except Exception as e:
        logger.debug("Failed to get github_id from auth RPC", user_id=user_id, error=str(e))
        return None


def get_github_id_for_user(user_id: str) -> Optional[int]:
    """Get GitHub ID for a user.

    Lookup strategy:
    1. Check github_tokens table (explicit PAT connection)
    2. Fall back to Supabase auth metadata (GitHub OAuth login)

    Args:
        user_id: User UUID

    Returns:
        GitHub ID (numeric) or None
    """
    try:
        from synsc.supabase_auth import get_supabase_client

        db = get_supabase_client()
        rows = db.select(
            "github_tokens",
            columns="github_id",
            filters={"user_id": user_id}
        )

        if rows and rows[0].get("github_id"):
            return int(rows[0]["github_id"])
    except Exception as e:
        logger.warning("Failed to get github_id from github_tokens", user_id=user_id, error=str(e))

    # Fallback: get from Supabase auth metadata (GitHub OAuth)
    return _get_github_id_from_auth(user_id)


def _fetch_tier_from_external_db(github_id: int) -> TierName:
    """Fetch tier from external Supabase by github_id.

    Returns 'free' if:
    - External DB not configured
    - User not found
    - Query fails
    - Invalid tier value

    Args:
        github_id: GitHub numeric ID

    Returns:
        TierName ("free", "researcher", or "lab")
    """
    tier_client = get_tier_supabase_client()
    if not tier_client:
        return "free"

    try:
        # Query external tier DB for user by github_id
        rows = tier_client.select(
            "user_profiles",
            columns="subscription_tier,credits",
            filters={"github_id": str(github_id)}  # Convert to string for JSON
        )

        if not rows:
            logger.info("User not found in tier DB, defaulting to free", github_id=github_id)
            return "free"

        tier_str = rows[0].get("subscription_tier", "free").lower()

        # Validate tier value
        if tier_str in TIER_CREDITS:
            return tier_str  # type: ignore

        logger.warning(
            "Invalid tier in external DB, defaulting to free",
            github_id=github_id,
            tier=tier_str
        )
        return "free"

    except Exception as e:
        logger.error(
            "Failed to fetch tier from external DB, failing open to free",
            github_id=github_id,
            error=str(e)
        )
        return "free"


def get_user_tier(user_id: str, bypass_cache: bool = False) -> TierName:
    """Get tier for a user with caching.

    Lookup strategy:
    1. Check in-memory cache (5-min TTL) unless bypass_cache=True
    2. Get github_id from github_tokens table (main DB)
    3. Query external Supabase tier DB by github_id
    4. Default to 'free' if any step fails

    Args:
        user_id: User UUID
        bypass_cache: Force fresh lookup (used by /v1/user/profile?force_refresh=true)

    Returns:
        TierName ("free", "researcher", or "lab")
    """
    global _tier_cache

    # Environment override (e.g. TIER_OVERRIDE=benchmark for local testing)
    import os
    tier_override = os.environ.get("TIER_OVERRIDE", "").lower()
    if tier_override and tier_override in TIER_CREDITS:
        return tier_override  # type: ignore

    # Check cache unless bypassed
    if not bypass_cache and user_id in _tier_cache:
        tier, cached_at = _tier_cache[user_id]
        if datetime.utcnow() - cached_at < _CACHE_TTL:
            logger.debug("Tier cache hit", user_id=user_id, tier=tier)
            return tier

    # Get github_id from main DB
    github_id = get_github_id_for_user(user_id)
    if not github_id:
        logger.info("User has no GitHub ID, defaulting to free tier", user_id=user_id)
        tier = "free"
    else:
        # Fetch from external DB
        tier = _fetch_tier_from_external_db(github_id)

    # Cache result
    _tier_cache[user_id] = (tier, datetime.utcnow())

    logger.info(
        "Fetched user tier",
        user_id=user_id,
        github_id=github_id,
        tier=tier,
        from_cache=False
    )
    return tier


def get_credit_limit(tier: TierName) -> int:
    """Get credit limit for a tier.

    Args:
        tier: Tier name ("free", "researcher", or "lab")

    Returns:
        Credit limit (5 for free, 50 for researcher, 200 for lab)
    """
    return TIER_CREDITS.get(tier, TIER_CREDITS["free"])


def usd_to_credits(usd: float) -> float:
    """Convert USD to credits (1 credit = $0.10).

    Args:
        usd: Amount in USD

    Returns:
        Amount in credits
    """
    return usd / 0.10


def credits_to_usd(credits: float) -> float:
    """Convert credits to USD (1 credit = $0.10).

    Args:
        credits: Amount in credits

    Returns:
        Amount in USD
    """
    return credits * 0.10


def clear_tier_cache(user_id: str | None = None) -> None:
    """Clear tier cache (for testing or manual refresh).

    Args:
        user_id: Clear specific user, or None to clear all
    """
    global _tier_cache
    if user_id:
        _tier_cache.pop(user_id, None)
        logger.debug("Cleared tier cache for user", user_id=user_id)
    else:
        _tier_cache.clear()
        logger.debug("Cleared entire tier cache")


# =============================================================================
# Billing Cycle Functions (for monthly credit resets on paid tiers)
# =============================================================================


def get_user_billing_cycle_info(user_id: str) -> tuple[datetime | None, datetime | None]:
    """Get user's credit_cycle_anchor and last_credit_grant_at from external DB.

    These fields are managed by the InkVell app's Stripe billing system.
    We read them to determine the current billing cycle for paid tier users.

    Args:
        user_id: User ID from main Supabase (synsc-context DB)

    Returns:
        (credit_cycle_anchor, last_credit_grant_at) or (None, None) if not found
    """
    github_id = get_github_id_for_user(user_id)
    if not github_id:
        logger.debug("User has no GitHub ID, cannot fetch billing cycle info", user_id=user_id)
        return None, None

    tier_client = get_tier_supabase_client()
    if not tier_client:
        logger.warning("Tier Supabase not configured, cannot fetch billing cycle info")
        return None, None

    try:
        rows = tier_client.select(
            "user_profiles",
            columns="credit_cycle_anchor,last_credit_grant_at",
            filters={"github_id": str(github_id)}
        )

        if not rows:
            logger.info("User not found in external DB, no billing cycle info", github_id=github_id)
            return None, None

        anchor_str = rows[0].get("credit_cycle_anchor")
        last_grant_str = rows[0].get("last_credit_grant_at")

        # Parse ISO timestamp strings to datetime objects
        anchor = None
        last_grant = None

        if anchor_str:
            anchor = datetime.fromisoformat(anchor_str.replace('Z', '+00:00'))
        if last_grant_str:
            last_grant = datetime.fromisoformat(last_grant_str.replace('Z', '+00:00'))

        logger.debug(
            "Fetched billing cycle info",
            user_id=user_id,
            github_id=github_id,
            anchor=anchor.isoformat() if anchor else None,
            last_grant=last_grant.isoformat() if last_grant else None,
        )

        return anchor, last_grant

    except Exception as e:
        logger.error("Failed to fetch billing cycle info", user_id=user_id, error=str(e))
        return None, None


def get_current_billing_cycle(credit_cycle_anchor: datetime | None) -> str:
    """Calculate current billing cycle string (YYYY-MM format).

    For free users (no anchor): Returns current calendar month.
    For paid users: Calculates based on anchor day-of-month.

    The billing cycle runs from anchor_day of one month to anchor_day of next month.
    Example:
        anchor = Feb 15, 2026
        today = March 10, 2026
        → Returns "2026-02" (still in Feb 15 - Mar 15 cycle)

        today = March 20, 2026
        → Returns "2026-03" (in Mar 15 - Apr 15 cycle)

    Args:
        credit_cycle_anchor: User's cycle anchor date, or None for free users

    Returns:
        Billing cycle string in YYYY-MM format (e.g., "2026-02")
    """
    import calendar

    now = datetime.now(timezone.utc)

    # Free users: Use calendar month (no anchor)
    if not credit_cycle_anchor:
        return now.strftime("%Y-%m")

    # Paid users: Calculate based on anchor day
    anchor_day = credit_cycle_anchor.day
    year, month = now.year, now.month

    # If we haven't reached the anchor day this month, we're still in previous cycle
    if now.day < anchor_day:
        # Move back one month
        if month == 1:
            year -= 1
            month = 12
        else:
            month -= 1

    return f"{year:04d}-{month:02d}"
