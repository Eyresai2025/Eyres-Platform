"""Pure-path asset resolution for the Qt6 migration layer."""
from pathlib import Path
import sys


def project_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def asset_path(name: str) -> Path:
    modern = project_root() / "ui" / "assets" / name
    if modern.is_file():
        return modern
    return project_root() / "Media" / name
