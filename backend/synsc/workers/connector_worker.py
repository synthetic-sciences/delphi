"""Background polling loop for durable connector synchronization."""

from __future__ import annotations

import time
from collections.abc import Callable

import structlog

from synsc.connectors.service import (
    ConnectorSyncService,
    get_connector_sync_service,
)

logger = structlog.get_logger(__name__)


class ConnectorSyncRunner:
    """Schedule due sources and process one leased sync page at a time."""

    def __init__(
        self,
        *,
        service: ConnectorSyncService | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        scheduler_interval: float = 60.0,
    ) -> None:
        if scheduler_interval <= 0:
            raise ValueError("scheduler_interval must be positive")
        self.service = service or get_connector_sync_service()
        self.sleeper = sleeper
        self.clock = clock
        self.scheduler_interval = scheduler_interval

    def run_forever(
        self,
        *,
        worker_id: str,
        should_continue: Callable[[], bool],
        poll_interval: float = 2.0,
    ) -> None:
        """Poll until shutdown while isolating transient queue failures."""

        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        next_schedule_at = 0.0
        while should_continue():
            try:
                now = self.clock()
                if now >= next_schedule_at:
                    self.service.schedule_due(limit=100)
                    next_schedule_at = now + self.scheduler_interval
                result = self.service.run_once(worker_id=worker_id)
                if result is None:
                    self.sleeper(poll_interval)
            except Exception as exc:
                logger.error(
                    "Connector worker poll failed",
                    worker_id=worker_id,
                    error=type(exc).__name__,
                )
                self.sleeper(poll_interval)
