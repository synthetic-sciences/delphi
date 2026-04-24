"""Centralized logging configuration for Delphi (synsc-context).

Switches between ConsoleRenderer (dev) and JSONRenderer (production)
based on the SYNSC_LOG_FORMAT environment variable.
"""

import logging
import os

import structlog


def configure_logging(*, force: bool = False) -> None:
    """Configure structlog with environment-aware rendering.

    Args:
        force: If True, reconfigure even if structlog is already configured.
               Useful when libraries have installed their own handlers.
    """
    log_format = os.getenv("SYNSC_LOG_FORMAT", "console").lower()
    log_level = os.getenv("SYNSC_LOG_LEVEL", "INFO").upper()

    if log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    shared_processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        renderer,
    ]

    # Reset stdlib logging so our config takes effect
    if force:
        logging.root.handlers.clear()

    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level, logging.INFO),
        force=force,
    )

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
