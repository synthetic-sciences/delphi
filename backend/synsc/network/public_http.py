"""Public-network-only HTTP transport and URL validation."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

import httpcore
import httpx


def resolve_public_addresses(hostname: str, port: int) -> tuple[str, ...]:
    """Resolve once and return only globally routable addresses."""

    try:
        resolved = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("URL hostname could not be resolved") from exc

    addresses = tuple(dict.fromkeys(str(item[4][0]) for item in resolved))
    parsed_addresses = tuple(ipaddress.ip_address(address) for address in addresses)
    if not parsed_addresses or any(
        not address.is_global for address in parsed_addresses
    ):
        raise ValueError("URL must resolve only to public IP addresses")
    return addresses


def validate_public_http_url(url: str) -> None:
    """Reject non-HTTP, credential-bearing, and non-public targets."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must be a public HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL must not contain credentials")

    resolve_public_addresses(
        parsed.hostname,
        parsed.port or (443 if parsed.scheme == "https" else 80),
    )


class PublicNetworkBackend(httpcore.SyncBackend):
    """Pin connections to addresses validated during connect."""

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.NetworkStream:
        last_error: Exception | None = None
        for address in resolve_public_addresses(host, port):
            try:
                return super().connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        assert last_error is not None
        raise last_error


class PublicHTTPTransport(httpx.HTTPTransport):
    """HTTP transport whose sockets use the public-only pinned resolver."""

    def __init__(self) -> None:
        super().__init__(trust_env=False)
        self._pool.close()
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(trust_env=False),
            max_connections=20,
            max_keepalive_connections=10,
            network_backend=PublicNetworkBackend(),
        )
