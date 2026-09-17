"""Typed, environment-driven application configuration.

Keep machine-specific values outside source code.  Every setting has a safe
default for a single-machine installation and can be overridden with an
``EYRES_*`` environment variable.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path


def _load_local_env() -> None:
    """Load simple KEY=VALUE entries from the project .env if present.

    Existing process environment variables always take precedence.
    This avoids adding python-dotenv as a dependency to the desktop app.
    """
    project_root = Path(__file__).resolve().parents[1]
    env_file = project_root / ".env"
    if not env_file.is_file():
        return

    try:
        for raw_line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            os.environ.setdefault(key, value)
    except OSError:
        # Environment variables can still be supplied normally.
        pass


_load_local_env()


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _default_data_dir() -> Path:
    """Choose a runtime directory even when HOME/USERPROFILE is unavailable."""
    explicit_root = os.getenv("LOCALAPPDATA") or os.getenv("PROGRAMDATA")
    if explicit_root:
        return Path(explicit_root) / "EyresAI_Data"
    try:
        return Path.home() / "EyresAI_Data"
    except RuntimeError:
        return Path.cwd() / "EyresAI_Data"


@dataclass(frozen=True)
class AppConfig:
    app_name: str
    environment: str
    data_dir: Path
    log_dir: Path
    mongodb_uri: str
    mongodb_database: str
    service_timeout_ms: int
    navigation_debounce_ms: int
    max_login_attempts: int
    lockout_minutes: int
    session_timeout_minutes: int

    @classmethod
    def from_environment(cls) -> "AppConfig":
        data_dir = Path(os.getenv("EYRES_DATA_DIR") or _default_data_dir())
        return cls(
            app_name=os.getenv("EYRES_APP_NAME", "EYRES AI Inspection Platform"),
            environment=os.getenv("EYRES_ENV", "production").strip().lower(),
            data_dir=data_dir,
            log_dir=Path(os.getenv("EYRES_LOG_DIR", str(data_dir / "logs"))).expanduser(),
            mongodb_uri=os.getenv("EYRES_MONGODB_URI", "mongodb://localhost:27017"),
            mongodb_database=os.getenv("EYRES_MONGODB_DATABASE", "eyres_qc"),
            service_timeout_ms=_positive_int("EYRES_SERVICE_TIMEOUT_MS", 2000),
            navigation_debounce_ms=_positive_int("EYRES_NAVIGATION_DEBOUNCE_MS", 75),
            max_login_attempts=_positive_int("EYRES_MAX_LOGIN_ATTEMPTS", 5),
            lockout_minutes=_positive_int("EYRES_LOCKOUT_MINUTES", 15),
            session_timeout_minutes=_positive_int("EYRES_SESSION_TIMEOUT_MINUTES", 15),
        )

    def ensure_runtime_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return AppConfig.from_environment()
