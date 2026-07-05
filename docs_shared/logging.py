"""Shared structlog configuration for server and ingest."""

from __future__ import annotations

import structlog


def configure_logging(level: str = "INFO") -> None:
    structlog.configure(
        cache_logger_on_first_use=True,
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
    )
