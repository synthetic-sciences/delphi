"""Tests for env-aware JSON/console logging configuration."""

import json
import logging
import os
from io import StringIO
from unittest.mock import patch

import structlog


def test_default_uses_console_renderer():
    """Without SYNSC_LOG_FORMAT, configure_logging() uses ConsoleRenderer."""
    os.environ.pop("SYNSC_LOG_FORMAT", None)

    from synsc.logging import configure_logging
    configure_logging(force=True)

    config = structlog.get_config()
    processors = config["processors"]
    renderer = processors[-1]
    assert isinstance(renderer, structlog.dev.ConsoleRenderer)


def test_json_format_uses_json_renderer():
    """SYNSC_LOG_FORMAT=json should use JSONRenderer."""
    os.environ["SYNSC_LOG_FORMAT"] = "json"
    try:
        from synsc.logging import configure_logging
        configure_logging(force=True)

        config = structlog.get_config()
        processors = config["processors"]
        renderer = processors[-1]
        assert isinstance(renderer, structlog.processors.JSONRenderer)
    finally:
        os.environ.pop("SYNSC_LOG_FORMAT", None)
        from synsc.logging import configure_logging as _cl
        _cl(force=True)


def test_console_format_explicit():
    """SYNSC_LOG_FORMAT=console should use ConsoleRenderer."""
    os.environ["SYNSC_LOG_FORMAT"] = "console"
    try:
        from synsc.logging import configure_logging
        configure_logging(force=True)

        config = structlog.get_config()
        renderer = config["processors"][-1]
        assert isinstance(renderer, structlog.dev.ConsoleRenderer)
    finally:
        os.environ.pop("SYNSC_LOG_FORMAT", None)


def test_json_output_is_valid_json():
    """In JSON mode, structlog output should be parseable JSON."""
    os.environ["SYNSC_LOG_FORMAT"] = "json"
    try:
        from synsc.logging import configure_logging
        configure_logging(force=True)

        logger = structlog.get_logger("test")
        # Capture log output
        handler = logging.StreamHandler(stream := StringIO())
        handler.setLevel(logging.INFO)
        logging.root.handlers = [handler]

        logger.info("test_message", key="value")

        output = stream.getvalue().strip()
        assert output, "Expected log output but got nothing"
        parsed = json.loads(output)
        assert parsed["event"] == "test_message"
        assert parsed["key"] == "value"
    finally:
        os.environ.pop("SYNSC_LOG_FORMAT", None)
        from synsc.logging import configure_logging as _cl
        _cl(force=True)


def test_log_level_from_env():
    """SYNSC_LOG_LEVEL should control the stdlib root logger level."""
    os.environ["SYNSC_LOG_LEVEL"] = "DEBUG"
    try:
        from synsc.logging import configure_logging
        configure_logging(force=True)
        assert logging.root.level == logging.DEBUG
    finally:
        os.environ["SYNSC_LOG_LEVEL"] = "INFO"
        from synsc.logging import configure_logging as _cl
        _cl(force=True)


def test_log_level_defaults_to_info():
    """Without SYNSC_LOG_LEVEL, root logger should be INFO."""
    os.environ.pop("SYNSC_LOG_LEVEL", None)
    from synsc.logging import configure_logging
    configure_logging(force=True)
    assert logging.root.level == logging.INFO


def test_structlog_wrapper_class():
    """configure_logging should set BoundLogger as the wrapper."""
    from synsc.logging import configure_logging
    configure_logging(force=True)
    config = structlog.get_config()
    assert config["wrapper_class"] is structlog.stdlib.BoundLogger


def test_processors_include_timestamper():
    """Timestamps should be present in the processor chain."""
    from synsc.logging import configure_logging
    configure_logging(force=True)
    config = structlog.get_config()
    processor_types = [type(p) for p in config["processors"]]
    assert structlog.processors.TimeStamper in processor_types
