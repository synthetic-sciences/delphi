#!/usr/bin/env python3
"""Backfill github_id for existing GitHub tokens.

This script queries all github_tokens where github_id IS NULL, calls the
GitHub API to get the numeric ID, and updates the row.

Usage:
    python scripts/backfill_github_ids.py

Environment Variables (required):
    SUPABASE_URL - Main Supabase project URL
    SUPABASE_SECRET_KEY - Main Supabase secret key
    TOKEN_ENCRYPTION_KEY - Encryption key for decrypting GitHub tokens
"""

import os
import sys
import time
import requests
import structlog

# Add parent directory to path to import synsc modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from synsc.supabase_auth import get_supabase_client
from synsc.services.token_encryption import decrypt_token

logger = structlog.get_logger(__name__)


def backfill_github_ids():
    """Backfill github_id for all users with GitHub tokens."""
    try:
        db = get_supabase_client()
    except Exception as e:
        logger.error("Failed to connect to Supabase", error=str(e))
        sys.exit(1)

    # Get all tokens
    try:
        rows = db.select(
            "github_tokens",
            columns="id,user_id,encrypted_token,github_username,github_id"
        )
    except Exception as e:
        logger.error("Failed to fetch github_tokens", error=str(e))
        sys.exit(1)

    # Filter for rows without github_id
    to_update = [r for r in rows if not r.get("github_id")]

    if not to_update:
        logger.info("No tokens need backfilling - all have github_id")
        return

    logger.info(f"Found {len(to_update)} tokens to backfill")
    success_count = 0
    error_count = 0

    for i, row in enumerate(to_update):
        user_id = row["user_id"]
        encrypted = row["encrypted_token"]
        github_username = row.get("github_username", "unknown")

        try:
            # Decrypt token
            token = decrypt_token(encrypted)

            # Call GitHub API
            resp = requests.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=10,
            )

            if resp.status_code != 200:
                logger.error(
                    "GitHub API failed",
                    user_id=user_id,
                    status=resp.status_code,
                    github_username=github_username
                )
                error_count += 1
                continue

            github_user = resp.json()
            github_id = github_user.get("id")
            github_login = github_user.get("login")

            if not github_id:
                logger.error(
                    "No github_id in response",
                    user_id=user_id,
                    github_username=github_username
                )
                error_count += 1
                continue

            # Update row
            db.update(
                "github_tokens",
                {"github_id": github_id, "github_username": github_login},
                {"user_id": user_id}
            )

            logger.info(
                f"[{i+1}/{len(to_update)}] Updated user",
                user_id=user_id,
                github_username=github_login,
                github_id=github_id
            )
            success_count += 1

            # Rate limit: 1 request/second to avoid GitHub API rate limits
            if i < len(to_update) - 1:  # Don't sleep after last iteration
                time.sleep(1)

        except Exception as e:
            logger.error(
                "Failed to backfill user",
                user_id=user_id,
                github_username=github_username,
                error=str(e)
            )
            error_count += 1

    logger.info(
        "Backfill complete",
        total=len(to_update),
        success=success_count,
        errors=error_count
    )


if __name__ == "__main__":
    # Configure structured logging
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )

    # Check required environment variables
    required_vars = ["SUPABASE_URL", "SUPABASE_SECRET_KEY", "TOKEN_ENCRYPTION_KEY"]
    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        logger.error("Missing required environment variables", missing=missing)
        sys.exit(1)

    backfill_github_ids()
