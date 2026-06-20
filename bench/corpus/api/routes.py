"""HTTP route registration."""


def health_check(request: dict) -> dict:
    """Liveness probe handler."""
    return {"status": 200, "body": "ok"}


def register_routes(app) -> None:
    """Attach all HTTP routes to the application instance."""
    app.add_route("/health", health_check)
    app.add_route("/login", _login_route)
    app.add_route("/users", _users_route)


def _login_route(request: dict) -> dict:
    return {"status": 200, "body": "login"}


def _users_route(request: dict) -> dict:
    return {"status": 200, "body": "users"}
