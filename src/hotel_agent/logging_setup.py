"""Centralized logging configuration with rotating file handler.

Environment variables (set in .env or shell):
    LOG_DIR       — Directory for log files.  Default: ``outputs/``
    LOG_MAX_BYTES — Max size per log file.    Default: ``52428800`` (50 MB)
    LOG_BACKUP_COUNT — Number of rotated files to keep.  Default: ``5``
    LOG_LEVEL     — Root log level.           Default: ``INFO``
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False

# Defaults
_DEFAULT_LOG_DIR = "outputs"
_DEFAULT_MAX_BYTES = 50 * 1024 * 1024  # 50 MB
_DEFAULT_BACKUP_COUNT = 5
_DEFAULT_LOG_LEVEL = "INFO"

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(verbose: bool = False) -> None:
    """Configure root logger with console + rotating file handlers.

    Safe to call multiple times — only configures once.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    log_dir = os.environ.get("LOG_DIR", _DEFAULT_LOG_DIR)
    max_bytes = int(os.environ.get("LOG_MAX_BYTES", _DEFAULT_MAX_BYTES))
    backup_count = int(os.environ.get("LOG_BACKUP_COUNT", _DEFAULT_BACKUP_COUNT))
    env_level = os.environ.get("LOG_LEVEL", _DEFAULT_LOG_LEVEL).upper()

    level = logging.DEBUG if verbose else getattr(logging, env_level, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT)

    # Console handler
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(formatter)
        root.addHandler(console)

    # Rotating file handler
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "hotel_agent.log"

    file_handler = RotatingFileHandler(
        str(log_file),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)  # File always captures DEBUG
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Quiet noisy libraries
    for lib in ("httpx", "litellm", "openai", "httpcore", "uvicorn.access"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    _logger = logging.getLogger("hotel_agent")
    _logger.info("=" * 60)
    _logger.info("  HOTEL PRICE TRACKER — SERVER STARTING")
    _logger.info("  Log dir: %s | Level: %s", log_dir, logging.getLevelName(level))
    _logger.info("=" * 60)
