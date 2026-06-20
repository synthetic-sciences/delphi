"""Database connection pooling."""

import threading

_POOL = []
_LOCK = threading.Lock()
_MAX_POOL_SIZE = 10


class Connection:
    """A thin wrapper around a database handle."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.closed = False

    def execute(self, sql: str, params: tuple = ()) -> list:
        if self.closed:
            raise RuntimeError("connection is closed")
        return []


def get_connection(dsn: str) -> Connection:
    """Check out a pooled connection, creating one if the pool is empty."""
    with _LOCK:
        if _POOL:
            return _POOL.pop()
    return Connection(dsn)


def close_connection(conn: Connection) -> None:
    """Return a connection to the pool or discard it if the pool is full."""
    with _LOCK:
        if len(_POOL) < _MAX_POOL_SIZE and not conn.closed:
            _POOL.append(conn)
        else:
            conn.closed = True
