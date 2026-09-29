"""Vendor-neutral camera adapter contracts for the EYRES Qt6 capture page."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Iterable

import cv2
import numpy as np


class CameraAdapterError(RuntimeError):
    pass


class CameraSdkUnavailable(CameraAdapterError):
    pass


class CameraFeatureUnavailable(CameraAdapterError):
    pass


@dataclass
class CameraDevice:
    adapter_key: str
    backend_id: str
    serial: str
    model: str
    vendor: str
    transport: str = ""
    scan_type: str = "area"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def uid(self) -> str:
        value = self.serial or self.backend_id
        return f"{self.adapter_key}:{value}"


@dataclass
class CameraSettings:
    # None means: keep the camera's current/profile value unless the operator
    # explicitly applies an override in the Qt6 settings step.
    exposure_us: float | None = None
    gain_db: float | None = None
    width: int | None = None
    height: int | None = None
    pixel_format: str | None = None
    trigger_mode: str | None = None
    trigger_source: str | None = None
    acquisition_mode: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CameraSettings":
        data = dict(data or {})
        known = {
            "exposure_us", "gain_db", "width", "height", "pixel_format",
            "trigger_mode", "trigger_source", "acquisition_mode", "extras",
        }
        clean = {k: data.get(k) for k in known if k in data}
        return cls(**clean)


@dataclass(frozen=True)
class AdapterCapabilities:
    scan_types: tuple[str, ...]
    preview: bool = True
    capture: bool = True
    settings: bool = True
    sdk_name: str = ""
    install_hint: str = ""


ProgressCallback = Callable[[int, int, str], None]
StopCallback = Callable[[], bool]


def simulation_enabled() -> bool:
    return os.getenv("EYRES_CAMERA_SIMULATION", "0").strip().lower() in {
        "1", "true", "yes", "on"
    }


def simulation_frame(scan_type: str, frame_number: int = 0) -> np.ndarray:
    height, width = ((1100, 520) if scan_type == "line" else (720, 1280))
    y, x = np.indices((height, width))
    image = ((x * 0.10 + y * 0.06 + frame_number * 7) % 150 + 45).astype(np.uint8)
    cx = int(width * (0.50 + 0.08 * np.sin(frame_number / 3.0)))
    cy = int(height * 0.52)
    cv2.circle(image, (cx, cy), max(45, min(width, height) // 7), 205, -1)
    cv2.rectangle(image, (35, 35), (width - 35, height - 35), 225, 2)
    cv2.putText(
        image, "EYRES CAMERA SIMULATION", (50, 78),
        cv2.FONT_HERSHEY_SIMPLEX, 0.9 if width > 800 else 0.58,
        245, 2, cv2.LINE_AA,
    )
    return image


def ensure_device_folder(root: str | Path, device: CameraDevice) -> Path:
    safe = "".join(
        c if c.isalnum() or c in "-_." else "_"
        for c in (device.serial or device.backend_id or "camera")
    )
    folder = Path(root) / safe
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def save_frame(
    folder: str | Path,
    device: CameraDevice,
    frame: np.ndarray,
    sequence: int,
    extension: str = ".png",
) -> str:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stem = "".join(
        c if c.isalnum() or c in "-_." else "_"
        for c in (device.serial or device.backend_id or "camera")
    )
    path = folder / f"{stem}_{sequence:04d}{extension}"
    if not cv2.imwrite(str(path), frame):
        raise CameraAdapterError(f"Could not save image: {path}")
    return str(path)


class CameraAdapter(ABC):
    key = "base"
    display_name = "Camera"
    vendor = ""
    capabilities = AdapterCapabilities(scan_types=("area",))

    @classmethod
    def sdk_available(cls) -> bool:
        return True

    @classmethod
    def sdk_status(cls) -> tuple[bool, str]:
        try:
            ok = bool(cls.sdk_available())
        except Exception as exc:
            return False, str(exc)
        if ok:
            return True, "Ready"
        return False, cls.capabilities.install_hint or f"{cls.capabilities.sdk_name} not available."

    def supports_scan_type(self, scan_type: str) -> bool:
        return scan_type in self.capabilities.scan_types

    def _simulation_devices(self, scan_type: str, count: int = 2) -> list[CameraDevice]:
        return [
            CameraDevice(
                adapter_key=self.key,
                backend_id=str(i),
                serial=f"SIM-{self.key.upper()}-{i+1:03d}",
                model=f"EYRES Virtual {self.display_name}",
                vendor=self.vendor or self.display_name,
                transport="Simulation",
                scan_type=scan_type,
                extra={"simulation": True},
            )
            for i in range(count)
        ]

    def _simulation_preview(self, device: CameraDevice, frame_number: int = 0) -> np.ndarray:
        return simulation_frame(device.scan_type, frame_number)

    def _simulation_capture(
        self,
        device: CameraDevice,
        settings: CameraSettings,
        n_images: int,
        output_dir: str | Path,
        progress: ProgressCallback | None = None,
        should_stop: StopCallback | None = None,
    ) -> list[str]:
        folder = ensure_device_folder(output_dir, device)
        paths: list[str] = []
        for i in range(max(1, int(n_images))):
            if should_stop and should_stop():
                break
            path = save_frame(folder, device, simulation_frame(device.scan_type, i), i + 1)
            paths.append(path)
            if progress:
                progress(i + 1, n_images, path)
        return paths

    @abstractmethod
    def discover(self, scan_type: str) -> list[CameraDevice]:
        raise NotImplementedError

    @abstractmethod
    def read_settings(self, device: CameraDevice) -> CameraSettings:
        raise NotImplementedError

    @abstractmethod
    def apply_settings(self, device: CameraDevice, settings: CameraSettings) -> None:
        raise NotImplementedError

    @abstractmethod
    def grab_preview(self, device: CameraDevice, settings: CameraSettings) -> np.ndarray | None:
        raise NotImplementedError

    @abstractmethod
    def capture(
        self,
        device: CameraDevice,
        settings: CameraSettings,
        n_images: int,
        output_dir: str | Path,
        progress: ProgressCallback | None = None,
        should_stop: StopCallback | None = None,
    ) -> list[str]:
        raise NotImplementedError
