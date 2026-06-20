"""User authentication entry point."""

from auth.password import verify_password
from auth.tokens import generate_token
from db.models import User


class LoginError(Exception):
    """Raised when authentication fails."""


def authenticate_user(username: str, password: str, store: dict) -> dict:
    """Authenticate a user by username/password and return a session token.

    Looks up the user, verifies the password hash, and issues a token. Raises
    LoginError on any failure so callers don't leak which step failed.
    """
    record = store.get(username)
    if record is None:
        raise LoginError("unknown user")
    user = User(user_id=record["id"], username=username, email=record.get("email"))
    if not verify_password(password, record["password_hash"]):
        raise LoginError("bad credentials")
    return generate_token(user.user_id)
