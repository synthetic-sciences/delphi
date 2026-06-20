"""Application server bootstrap."""

from api.routes import register_routes


class Application:
    """A minimal request-dispatching application."""

    def __init__(self) -> None:
        self.routes: dict[str, callable] = {}

    def add_route(self, path: str, handler: callable) -> None:
        self.routes[path] = handler

    def handle_request(self, path: str, request: dict) -> dict:
        """Dispatch an incoming request to its registered handler."""
        handler = self.routes.get(path)
        if handler is None:
            return {"status": 404, "body": "not found"}
        return handler(request)


def create_app() -> Application:
    """Construct the application and wire up all routes."""
    app = Application()
    register_routes(app)
    return app
