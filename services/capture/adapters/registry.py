"""Camera adapter registry used by the Qt6 Image Capturing page."""
from __future__ import annotations

from dataclasses import dataclass

from .base import CameraAdapter
from .basler_pylon import BaslerPylonAdapter
from .flir_spinnaker import FlirSpinnakerAdapter
from .genicam_harvesters import HarvesterGenicamAdapter
from .hikrobot_mvs import HikrobotMvsAdapter
from .lucid_arena import LucidArenaAdapter
from .teledyne_dalsa import TeledyneDalsaAdapter


@dataclass(frozen=True)
class AdapterInfo:
    key: str
    display_name: str
    short_name: str
    sdk_name: str
    scan_types: tuple[str, ...]
    available: bool
    status_text: str


_ADAPTERS: dict[str, type[CameraAdapter]] = {
    LucidArenaAdapter.key: LucidArenaAdapter,
    HikrobotMvsAdapter.key: HikrobotMvsAdapter,
    BaslerPylonAdapter.key: BaslerPylonAdapter,
    FlirSpinnakerAdapter.key: FlirSpinnakerAdapter,
    TeledyneDalsaAdapter.key: TeledyneDalsaAdapter,
    HarvesterGenicamAdapter.key: HarvesterGenicamAdapter,
}

_SHORT_NAMES = {
    "lucid": "LV",
    "hikrobot": "MVS",
    "basler": "BA",
    "flir": "FL",
    "teledyne_dalsa": "TD",
    "genicam": "GC",
}

# Keep the approved page flow: area and line expose different brand choices.
_SCAN_ORDER = {
    "area": ("lucid", "hikrobot", "basler", "flir", "genicam"),
    "line": ("lucid", "basler", "teledyne_dalsa", "genicam"),
}


def adapter_infos(scan_type: str) -> list[AdapterInfo]:
    result = []
    for key in _SCAN_ORDER.get(scan_type, ()):
        cls = _ADAPTERS[key]
        available, status = cls.sdk_status()
        result.append(
            AdapterInfo(
                key=key,
                display_name=cls.display_name,
                short_name=_SHORT_NAMES.get(key, key[:2].upper()),
                sdk_name=cls.capabilities.sdk_name,
                scan_types=cls.capabilities.scan_types,
                available=available,
                status_text=status,
            )
        )
    return result


def get_adapter(key: str) -> CameraAdapter:
    try:
        return _ADAPTERS[key]()
    except KeyError as exc:
        raise KeyError(f"Unknown camera adapter: {key}") from exc


def get_adapter_class(key: str) -> type[CameraAdapter]:
    return _ADAPTERS[key]


def all_adapter_keys() -> tuple[str, ...]:
    return tuple(_ADAPTERS)
