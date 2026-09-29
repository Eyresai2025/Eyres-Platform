"""PyQt6 background workers for camera discovery, settings, preview and capture."""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from PyQt6 import QtCore

from .base import CameraDevice, CameraSettings
from .registry import get_adapter


class DiscoveryWorker(QtCore.QThread):
    completed = QtCore.pyqtSignal(list)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, adapter_key: str, scan_type: str, parent=None):
        super().__init__(parent)
        self.adapter_key = adapter_key
        self.scan_type = scan_type

    def run(self):
        try:
            devices = get_adapter(self.adapter_key).discover(self.scan_type)
            self.completed.emit(devices)
        except Exception as exc:
            self.failed.emit(str(exc))


class SettingsWorker(QtCore.QThread):
    completed = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(
        self, adapter_key: str, device: CameraDevice,
        settings: CameraSettings | None = None, action: str = "read", parent=None,
    ):
        super().__init__(parent)
        self.adapter_key = adapter_key
        self.device = device
        self.settings = settings
        self.action = action

    def run(self):
        try:
            adapter = get_adapter(self.adapter_key)
            if self.action == "read":
                result = adapter.read_settings(self.device)
            elif self.action == "apply":
                adapter.apply_settings(self.device, self.settings or CameraSettings())
                result = self.settings or CameraSettings()
            else:
                raise RuntimeError(f"Unsupported settings action: {self.action}")
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class PreviewWorker(QtCore.QThread):
    completed = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(
        self, adapter_key: str, device: CameraDevice,
        settings: CameraSettings, parent=None,
    ):
        super().__init__(parent)
        self.adapter_key = adapter_key
        self.device = device
        self.settings = settings

    def run(self):
        try:
            frame = get_adapter(self.adapter_key).grab_preview(
                self.device, self.settings
            )
            self.completed.emit(frame)
        except Exception as exc:
            self.failed.emit(str(exc))


class CaptureSessionWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(int, int, str)
    status = QtCore.pyqtSignal(str)
    completed = QtCore.pyqtSignal(list, str)
    failed = QtCore.pyqtSignal(str)

    def __init__(
        self,
        adapter_key: str,
        scan_type: str,
        devices: list[CameraDevice],
        settings_by_uid: dict[str, CameraSettings],
        images_per_camera: int,
        base_dir: str,
        parent=None,
    ):
        super().__init__(parent)
        self.adapter_key = adapter_key
        self.scan_type = scan_type
        self.devices = list(devices)
        self.settings_by_uid = dict(settings_by_uid)
        self.images_per_camera = max(1, int(images_per_camera))
        self.base_dir = str(base_dir)
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        try:
            adapter = get_adapter(self.adapter_key)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            session_dir = (
                Path(self.base_dir)
                / f"capture_{self.scan_type}_{stamp}"
            )
            session_dir.mkdir(parents=True, exist_ok=True)

            total = self.images_per_camera * len(self.devices)
            completed_before = 0
            all_paths: list[str] = []

            self.status.emit(
                f"Starting {self.scan_type} capture: "
                f"{self.images_per_camera} image(s) × {len(self.devices)} camera(s)"
            )

            for device in self.devices:
                if self._stop_event.is_set():
                    break

                self.status.emit(
                    f"[{device.serial}] Configuring {device.model}"
                )
                settings = self.settings_by_uid.get(
                    device.uid,
                    CameraSettings(),
                )

                def local_progress(done, _device_total, path):
                    self.progress.emit(
                        min(total, completed_before + done),
                        total,
                        path,
                    )

                paths = adapter.capture(
                    device=device,
                    settings=settings,
                    n_images=self.images_per_camera,
                    output_dir=session_dir,
                    progress=local_progress,
                    should_stop=self._stop_event.is_set,
                )
                all_paths.extend(paths)
                completed_before += self.images_per_camera
                self.status.emit(
                    f"[{device.serial}] Saved {len(paths)} file(s)"
                )

            self.completed.emit(all_paths, str(session_dir))
        except Exception as exc:
            self.failed.emit(str(exc))
