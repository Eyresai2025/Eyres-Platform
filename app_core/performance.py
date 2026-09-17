"""Persistent page-navigation performance telemetry."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import os
from pathlib import Path
from threading import Lock

from .config import get_config

_lock = Lock()
_FIELDS = ("timestamp_utc", "page", "elapsed_ms", "status", "slow_ui", "details")


def record_page_timing(
    page: str,
    elapsed_ms: float,
    status: str = "success",
    details: str = "",
) -> Path:
    """Append one navigation result and return the CSV path."""
    config = get_config()
    config.ensure_runtime_directories()
    path = config.log_dir / "page_timings.csv"
    row = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "page": page,
        "elapsed_ms": f"{elapsed_ms:.2f}",
        "status": status,
        "slow_ui": "yes" if elapsed_ms >= 500 else "no",
        "details": details.replace("\r", " ").replace("\n", " ")[:500],
    }
    with _lock:
        try:
            return _append_row(path, row)
        except PermissionError:
            # Excel commonly locks the primary CSV on Windows. Never lose a timing
            # sample: write to a per-process spool that can be reviewed or merged.
            fallback = config.log_dir / f"page_timings_pending_{os.getpid()}.csv"
            return _append_row(fallback, row)


def _append_row(path: Path, row: dict[str, str]) -> Path:
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)
    return path
