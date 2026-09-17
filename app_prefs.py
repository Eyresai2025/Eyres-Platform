# app_prefs.py
from __future__ import annotations
import json, os, tempfile, base64
from typing import Any, Dict
from PyQt5.QtCore import QStandardPaths, QByteArray

APP_DIR_NAME = "AI-Model-Training-Suite"

# ---- defaults ----
DEFAULT_PREFS: Dict[str, Any] = {
    "last_tool_index": 0,
    "maximized": True,
    "window_geometry_b64": "",
    "window_state_b64": "",
    "theme": "Light",
}

def _app_data_dir() -> str:
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if not base:
        base = os.path.expanduser("~/.config")
    path = os.path.join(base, APP_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path

def _prefs_path() -> str:
    return os.path.join(_app_data_dir(), "session.json")

def _atomic_write(path: str, data: str) -> None:
    """Write data atomically to avoid corruption on crash."""
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

class AppPrefs:
    """Tiny JSON-backed preference store with typed helpers."""
    def __init__(self):
        self._path = _prefs_path()
        # start with defaults, then merge on load
        self._data: Dict[str, Any] = DEFAULT_PREFS.copy()
        self.load()

    # ---------- core load/save ----------
    def load(self) -> None:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    on_disk = json.load(f)
                # merge: keep defaults for any missing keys
                for k, v in DEFAULT_PREFS.items():
                    self._data[k] = on_disk.get(k, v)
            else:
                # ensure file created on first save
                self._data = DEFAULT_PREFS.copy()
        except Exception:
            # Corrupt or unreadable: start fresh (don’t crash the app)
            self._data = DEFAULT_PREFS.copy()

    def save(self) -> None:
        try:
            _atomic_write(self._path, json.dumps(self._data, indent=2))
        except Exception:
            pass

    # ---------- generic get/set ----------
    def get(self, key: str, default: Any=None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    # ---------- convenience: theme ----------
    @property
    def theme(self) -> str:
        return str(self._data.get("theme", DEFAULT_PREFS["theme"]))

    @theme.setter
    def theme(self, val: str):
        self._data["theme"] = str(val or DEFAULT_PREFS["theme"])
        self.save()

    # Optional explicit getters/setters if you prefer call-style
    def get_theme(self, default: str = DEFAULT_PREFS["theme"]) -> str:
        return str(self._data.get("theme", default))

    def set_theme(self, name: str) -> None:
        self.theme = name  # delegates to property and saves

    # ---------- window geometry/state (QByteArray <-> base64) ----------
    def set_geometry(self, ba: QByteArray) -> None:
        if isinstance(ba, QByteArray):
            self._data["window_geometry_b64"] = base64.b64encode(bytes(ba)).decode("ascii")
            self.save()

    def get_geometry(self) -> QByteArray:
        b64 = self._data.get("window_geometry_b64")
        if not b64:
            return QByteArray()
        try:
            return QByteArray(base64.b64decode(b64))
        except Exception:
            return QByteArray()

    def set_win_state(self, ba: QByteArray) -> None:
        if isinstance(ba, QByteArray):
            self._data["window_state_b64"] = base64.b64encode(bytes(ba)).decode("ascii")
            self.save()

    def get_win_state(self) -> QByteArray:
        b64 = self._data.get("window_state_b64")
        if not b64:
            return QByteArray()
        try:
            return QByteArray(base64.b64decode(b64))
        except Exception:
            return QByteArray()

    # ---------- last tool index ----------
    def set_last_tool_index(self, idx: int) -> None:
        self._data["last_tool_index"] = int(idx)
        self.save()

    def get_last_tool_index(self, default: int=0) -> int:
        try:
            return int(self._data.get("last_tool_index", default))
        except Exception:
            return default

    # ---------- maximized flag ----------
    def set_maximized(self, maximized: bool) -> None:
        self._data["maximized"] = bool(maximized)
        self.save()

    def get_maximized(self, default: bool=False) -> bool:
        v = self._data.get("maximized", default)
        return bool(v)
        
    def set_sidebar_width(self, w: int) -> None:
        self._data["sidebar_width"] = int(max(200, min(248, w)))

    def get_sidebar_width(self, default: int = 260) -> int:
        try:
            return int(self._data.get("sidebar_width", default))
        except Exception:
            return default

    def set_sidebar_collapsed(self, collapsed: bool) -> None:
        self._data["sidebar_collapsed"] = bool(collapsed)

    def get_sidebar_collapsed(self, default: bool = False) -> bool:
        v = self._data.get("sidebar_collapsed", default)
        return bool(v)
