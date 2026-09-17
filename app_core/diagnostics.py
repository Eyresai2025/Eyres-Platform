"""Privacy-safe diagnostic collection and support-report generation."""
from __future__ import annotations
import csv
from datetime import datetime, timezone
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import sys
from typing import Iterable
from .config import get_config

_SECRET_PATTERN = re.compile(
    r"(?i)(password|passwd|pwd|token|secret|security_answer|api[_-]?key)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_URI_CREDENTIALS = re.compile(r"(?i)(mongodb(?:\+srv)?://)[^/@\s:]+(?::[^/@\s]*)?@")


def redact(value: str) -> str:
    text = str(value or "")
    text = _SECRET_PATTERN.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
    return _URI_CREDENTIALS.sub(r"\1[REDACTED]@", text)


def tail_lines(path: Path, limit: int = 500) -> list[str]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return [redact(line) for line in lines[-max(1, limit):]]


def recent_log_entries(level="ALL", query="", limit=500) -> list[str]:
    path = get_config().log_dir / "eyres-platform.log"
    result = tail_lines(path, limit)
    level = str(level).upper()
    if level != "ALL":
        marker = f" {level} "
        result = [line for line in result if marker in line.upper()]
    query = str(query or "").strip().lower()
    if query:
        result = [line for line in result if query in line.lower()]
    return result


def recent_timings(limit=100) -> list[dict]:
    path = get_config().log_dir / "page_timings.csv"
    if not path.is_file():
        return []
    with path.open("r", newline="", encoding="utf-8", errors="replace") as stream:
        rows = list(csv.DictReader(stream))[-max(1, limit):]
    return [{key: redact(value) for key, value in row.items()} for row in rows]


def system_snapshot() -> dict:
    packages = {}
    for name in ("PyQt5", "pymongo", "opencv-python", "numpy", "torch", "torchvision", "pylogix"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = "not installed"
    gpu = {"cuda_available": False, "cuda_version": None, "device": None}
    torch = sys.modules.get("torch")
    if torch is not None:
        try:
            available = bool(torch.cuda.is_available())
            gpu = {"cuda_available": available, "cuda_version": torch.version.cuda,
                   "device": torch.cuda.get_device_name(0) if available else None}
        except Exception as exc:
            gpu["error"] = type(exc).__name__
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "application": get_config().app_name,
        "environment": get_config().environment,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "executable": str(Path(sys.executable).name),
        "gpu": gpu,
        "packages": packages,
    }


def build_support_report() -> dict:
    return {
        "system": system_snapshot(),
        "recent_logs": recent_log_entries(limit=500),
        "recent_page_timings": recent_timings(limit=100),
    }


def export_support_report() -> Path:
    cfg = get_config()
    root = cfg.data_dir / "reports" / "support"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = root / f"eyres_support_report_{stamp}.json"
    path.write_text(json.dumps(build_support_report(), indent=2), encoding="utf-8")
    return path


def diagnostic_log_paths() -> Iterable[Path]:
    root = get_config().log_dir
    yield root / "eyres-platform.log"
    yield root / "page_timings.csv"
    yield from root.glob("eyres-platform.log.*")
    yield from root.glob("page_timings_pending_*.csv")


def clear_diagnostic_logs() -> int:
    """Clear operational diagnostics only. Security audit files are never targeted."""
    count = 0
    for path in diagnostic_log_paths():
        if not path.is_file():
            continue
        if path.name == "eyres-platform.log":
            path.write_text("", encoding="utf-8")
        else:
            path.unlink()
        count += 1
    return count
