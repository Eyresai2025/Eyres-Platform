"""Centralized rotating file and console logging."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from .config import AppConfig, get_config


def configure_logging(config: AppConfig | None = None) -> Path:
    config = config or get_config()
    config.ensure_runtime_directories()
    log_path = config.log_dir / "eyres-platform.log"
    root = logging.getLogger()
    if getattr(root, "_eyres_configured", False):
        return log_path

    root.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s [%(threadName)s] %(message)s"
    )
    file_handler = RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root._eyres_configured = True  # type: ignore[attr-defined]
    return log_path


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
