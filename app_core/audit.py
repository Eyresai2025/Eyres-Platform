"""Hash-chained, access-restricted security and operational audit records."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, hmac, json, logging, os, secrets, stat, subprocess
from pathlib import Path
from threading import Lock
from typing import Any, Mapping
from .config import get_config

_lock = Lock()
_LOGGER = logging.getLogger("eyres.audit")
_SENSITIVE_KEYS = {"password", "secret", "token", "security_answer", "api_key"}
_GENESIS = "0" * 64

def _paths():
    root = get_config().data_dir / "security"
    return root, root / "audit.jsonl", root / "audit.key", root / "audit.anchor"

def _safe_details(details: Mapping[str, Any] | None) -> dict[str, Any]:
    result = {}
    for key, value in (details or {}).items():
        if key.lower() in _SENSITIVE_KEYS:
            continue
        try:
            json.dumps(value); result[key] = value
        except (TypeError, ValueError):
            result[key] = str(value)
    return result

def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()

def _protect(path: Path, directory: bool = False) -> None:
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if directory else 0))
    except OSError:
        _LOGGER.exception("Could not set owner permissions on %s", path)
    if os.name == "nt" and os.getenv("USERNAME"):
        try:
            grant = f"{os.getenv('USERNAME')}:(OI)(CI)F" if directory else f"{os.getenv('USERNAME')}:F"
            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", grant,
                            "/grant:r", "SYSTEM:F", "/grant:r", "Administrators:F"],
                           check=True, capture_output=True, creationflags=0x08000000)
        except (OSError, subprocess.CalledProcessError):
            _LOGGER.exception("Could not harden Windows ACL on %s", path)

def initialize_audit_store() -> Path:
    root, log_path, key_path, anchor_path = _paths()
    root.mkdir(parents=True, exist_ok=True); _protect(root, True)
    if not key_path.exists():
        key_path.write_bytes(secrets.token_bytes(32)); _protect(key_path)
    if not anchor_path.exists():
        anchor_path.write_text(_GENESIS, encoding="ascii"); _protect(anchor_path)
    return log_path

def _read_anchor(path: Path) -> str:
    try:
        value = path.read_text(encoding="ascii").strip()
        return value if len(value) == 64 else _GENESIS
    except OSError:
        return _GENESIS

def record_audit_event(action: str, *, actor: str = "system", status: str = "success",
                       details: Mapping[str, Any] | None = None) -> Path:
    with _lock:
        log_path = initialize_audit_store()
        _, _, key_path, anchor_path = _paths()
        previous = _read_anchor(anchor_path)
        payload = {"timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                   "action": action, "actor": actor or "unknown", "status": status,
                   "details": _safe_details(details), "previous_hash": previous}
        payload["record_hash"] = hmac.new(key_path.read_bytes(),
            previous.encode("ascii") + _canonical(payload), hashlib.sha256).hexdigest()
        try:
            with log_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
                stream.flush(); os.fsync(stream.fileno())
            _protect(log_path)
            temporary = anchor_path.with_suffix(".tmp")
            temporary.write_text(payload["record_hash"], encoding="ascii")
            os.replace(temporary, anchor_path); _protect(anchor_path)
        except OSError:
            _LOGGER.exception("Could not persist audit action %s", action)
        return log_path

def verify_audit_integrity() -> tuple[bool, str, int]:
    with _lock:
        log_path = initialize_audit_store()
        _, _, key_path, anchor_path = _paths()
        key, previous, count = key_path.read_bytes(), _GENESIS, 0
        if log_path.exists():
            for number, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip(): continue
                try:
                    record = json.loads(line); supplied = record.pop("record_hash")
                except (json.JSONDecodeError, KeyError):
                    return False, f"Invalid record at line {number}", count
                if record.get("previous_hash") != previous:
                    return False, f"Broken chain at line {number}", count
                expected = hmac.new(key, previous.encode("ascii") + _canonical(record), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(supplied, expected):
                    return False, f"Modified record at line {number}", count
                previous, count = supplied, count + 1
        if _read_anchor(anchor_path) != previous:
            return False, "Audit log truncation or anchor mismatch detected", count
        return True, "Audit integrity verified", count
