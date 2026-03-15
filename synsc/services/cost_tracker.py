"""Gemini API cost tracking.

Records per-user token usage and computed USD cost for embedding operations.
Fire-and-forget pattern — never raises on failure.
"""

import os

import structlog

from synsc.config import get_config
from synsc.services.tier_service import (
    get_user_tier,
    get_credit_limit,
    usd_to_credits,
    get_user_billing_cycle_info,
    get_current_billing_cycle,
)

logger = structlog.get_logger(__name__)

# Pricing: gemini-embedding-001 = $0.15 per 1M input tokens
GEMINI_EMBEDDING_COST_PER_TOKEN = 0.15 / 1_000_000  # $0.00000015

# Per-user cost limit (default $5.00, override via env var)
DEFAULT_COST_LIMIT_USD = 5.00
GEMINI_COST_LIMIT_USD = float(os.environ.get("GEMINI_COST_LIMIT_USD", DEFAULT_COST_LIMIT_USD))


def compute_cost(token_count: int) -> float:
    """Compute USD cost for a given token count."""
    return token_count * GEMINI_EMBEDDING_COST_PER_TOKEN


class CostLimitExceeded(Exception):
    """Raised when a user's credit limit would be exceeded."""

    def __init__(self, current_credits: float, estimated_credits: float,
                 limit_credits: int, tier: str):
        self.current_credits = current_credits
        self.estimated_credits = estimated_credits
        self.limit_credits = limit_credits
        self.tier = tier
        super().__init__(
            f"Credit limit exceeded ({tier} tier): "
            f"current {current_credits:.2f} + estimated {estimated_credits:.2f} "
            f"> limit {limit_credits} credits"
        )


def check_cost_limit(user_id: str, estimated_tokens: int) -> None:
    """Check if a user can afford an embedding operation based on their tier.

    Credit system behavior:
    - Free tier: One-time 5 credits (cumulative all-time usage)
    - Paid tiers: Monthly recurring credits (usage resets each billing cycle)

    Args:
        user_id: User UUID
        estimated_tokens: Tokens about to be embedded

    Raises:
        CostLimitExceeded: If operation would exceed user's credit limit
    """
    # Get user tier and credit limit
    tier = get_user_tier(user_id)
    credit_limit = get_credit_limit(tier)

    if credit_limit <= 0:
        return  # shouldn't happen

    estimated_cost_usd = compute_cost(estimated_tokens)
    estimated_credits = usd_to_credits(estimated_cost_usd)

    try:
        from synsc.supabase_auth import get_supabase_client

        # Determine billing cycle based on tier
        billing_cycle = None
        if tier != "free":
            # Paid tiers: Get billing cycle for monthly credit reset
            anchor, _ = get_user_billing_cycle_info(user_id)
            billing_cycle = get_current_billing_cycle(anchor)
            logger.debug(
                "Checking paid tier usage for current cycle",
                user_id=user_id,
                tier=tier,
                billing_cycle=billing_cycle,
            )
        else:
            # Free tier: Check all-time cumulative usage
            logger.debug(
                "Checking free tier usage (all-time)",
                user_id=user_id,
            )

        # Query usage directly (filtered by cycle for paid tiers, all-time for free)
        filters = {"user_id": user_id}
        if billing_cycle:
            filters["billing_cycle"] = billing_cycle

        rows = get_supabase_client().select("gemini_costs", "cost_usd", filters)
        current_cost_usd = sum(float(r.get("cost_usd", 0)) for r in rows)

        current_credits = usd_to_credits(current_cost_usd)

        if current_credits + estimated_credits > credit_limit:
            raise CostLimitExceeded(
                current_credits, estimated_credits, credit_limit, tier
            )

        log_data = {
            "user_id": user_id,
            "tier": tier,
            "current_credits": f"{current_credits:.2f}",
            "estimated_credits": f"{estimated_credits:.2f}",
            "limit_credits": credit_limit,
        }
        if billing_cycle:
            log_data["billing_cycle"] = billing_cycle

        logger.debug("Credit limit check passed", **log_data)

    except CostLimitExceeded:
        raise
    except Exception as e:
        # Fail open — don't block indexing if the check itself fails
        logger.warning("Credit limit check failed, allowing request", error=str(e))


def record_gemini_cost(
    user_id: str,
    operation: str,
    token_count: int,
    resource_id: str | None = None,
    batch_count: int = 1,
    metadata: dict | None = None,
) -> None:
    """Record a Gemini API cost entry. Fire-and-forget — never raises.

    Args:
        user_id: User UUID
        operation: 'index_repository' or 'search_code'
        token_count: Total input tokens consumed
        resource_id: Related repo_id (for indexing) or None
        batch_count: Number of API calls made
        metadata: Optional context (repo_name, query, etc.)
    """
    if not user_id or token_count <= 0:
        return

    cost_usd = compute_cost(token_count)

    try:
        from synsc.supabase_auth import get_supabase_client

        # Calculate billing cycle for this cost entry
        tier = get_user_tier(user_id)
        anchor, _ = get_user_billing_cycle_info(user_id)
        billing_cycle = get_current_billing_cycle(anchor)

        data: dict = {
            "user_id": user_id,
            "operation": operation,
            "token_count": token_count,
            "cost_usd": cost_usd,
            "model": get_config().embeddings.gemini_model_name,
            "batch_count": batch_count,
            "billing_cycle": billing_cycle,  # Store billing cycle
        }
        if resource_id:
            data["resource_id"] = resource_id
        if metadata:
            data["metadata"] = metadata

        get_supabase_client().insert("gemini_costs", data)

        logger.debug(
            "Recorded Gemini cost",
            user_id=user_id,
            operation=operation,
            tokens=token_count,
            cost_usd=f"${cost_usd:.8f}",
            billing_cycle=billing_cycle,
            tier=tier,
        )
    except Exception as e:
        logger.warning("Failed to record Gemini cost", error=str(e))
