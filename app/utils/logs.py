"""Shared logging utilities."""

from __future__ import annotations

import logging
import os
from pathlib import Path


DEFAULT_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def _resolve_log_level() -> int:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level_name, logging.INFO)


def configure_logging() -> None:
    """Configure the root logger once for the entire application."""
    if logging.getLogger().handlers:
        return

    log_file = os.getenv("LOG_FILE")
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))

    logging.basicConfig(
        level=_resolve_log_level(),
        format=DEFAULT_LOG_FORMAT,
        handlers=handlers,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger instance."""
    configure_logging()
    return logging.getLogger(name)
