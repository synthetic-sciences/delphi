"""GitHub OAuth flow — no auth libraries, just httpx.

Three-step flow:
  1. build_authorize_url()  → redirect user to GitHub
  2. GitHub redirects back with ?code=...&state=...
  3. exchange_code()        → swap code for access token, fetch user profile

The deployer creates a GitHub OAuth App at:
  https://github.com/settings/developers
and sets GITHUB_CLIENT_ID + GITHUB_CLIENT_SECRET env vars.
"""

import os
import secrets
from dataclasses import dataclass

import httpx
import structlog

logger = structlog.get_logger(__name__)

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


@dataclass
class GitHubUser:
    """User profile returned by GitHub after OAuth."""
    github_id: int
    username: str
    email: str | None
    name: str | None
    avatar_url: str | None


def get_client_id() -> str:
    val = os.getenv("GITHUB_CLIENT_ID", "")
    if not val:
        raise RuntimeError("GITHUB_CLIENT_ID environment variable is required for OAuth.")
    return val


def get_client_secret() -> str:
    val = os.getenv("GITHUB_CLIENT_SECRET", "")
    if not val:
        raise RuntimeError("GITHUB_CLIENT_SECRET environment variable is required for OAuth.")
    return val


def generate_state() -> str:
    """Generate a random state parameter for CSRF protection."""
    return secrets.token_urlsafe(32)


def build_authorize_url(redirect_uri: str, state: str) -> str:
    """Build the GitHub OAuth authorization URL."""
    params = (
        f"client_id={get_client_id()}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=read:user%20user:email"
        f"&state={state}"
    )
    return f"{GITHUB_AUTHORIZE_URL}?{params}"


async def exchange_code(code: str, redirect_uri: str) -> GitHubUser:
    """Exchange an OAuth authorization code for a user profile.

    1. POST to GitHub to get access token
    2. GET /user to fetch profile
    3. If no public email, GET /user/emails for the primary email

    Raises:
        httpx.HTTPStatusError: if GitHub API returns an error
        ValueError: if token exchange fails
    """
    async with httpx.AsyncClient() as client:
        # Step 1: exchange code for access token
        token_resp = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": get_client_id(),
                "client_secret": get_client_secret(),
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()

        access_token = token_data.get("access_token")
        if not access_token:
            error = token_data.get("error_description", token_data.get("error", "unknown"))
            raise ValueError(f"GitHub OAuth token exchange failed: {error}")

        auth_headers = {"Authorization": f"Bearer {access_token}"}

        # Step 2: fetch user profile
        user_resp = await client.get(GITHUB_USER_URL, headers=auth_headers, timeout=10)
        user_resp.raise_for_status()
        user_data = user_resp.json()

        email = user_data.get("email")

        # Step 3: if no public email, fetch from /user/emails
        if not email:
            try:
                emails_resp = await client.get(
                    "https://api.github.com/user/emails",
                    headers=auth_headers,
                    timeout=10,
                )
                emails_resp.raise_for_status()
                for entry in emails_resp.json():
                    if entry.get("primary") and entry.get("verified"):
                        email = entry["email"]
                        break
            except Exception as e:
                logger.warning("Could not fetch GitHub emails", error=str(e))

        return GitHubUser(
            github_id=user_data["id"],
            username=user_data["login"],
            email=email,
            name=user_data.get("name"),
            avatar_url=user_data.get("avatar_url"),
        )
