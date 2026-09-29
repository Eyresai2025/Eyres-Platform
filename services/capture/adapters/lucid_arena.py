"""Lucid Vision Labs Arena SDK adapter."""
from __future__ import annotations

import ctypes
from pathlib import Path

import cv2
import numpy as np

from .base import (
    AdapterCapabilities, CameraAdapter, CameraAdapterError, CameraDevice,
    CameraSdkUnavailable, CameraSettings, ensure_device_folder, save_frame,
    simulation_enabled,
)


class LucidArenaAdapter(CameraAdapter):
    key = "lucid"
    display_name = "Lucid Vision"
    vendor = "Lucid Vision Labs"
    capabilities = AdapterCapabilities(
        scan_types=("area", "line"),
        sdk_name="Arena SDK / arena_api",
        install_hint="Install Lucid Arena SDK with the Arena Python package.",
    )

    @classmethod
    def sdk_available(cls) -> bool:
        try:
            import arena_api.system  # noqa: F401
            import arena_api.buffer  # noqa: F401
            return True
        except Exception:
            return False

    @staticmethod
    def _sdk():
        try:
            from arena_api.system import system
            from arena_api.buffer import BufferFactory
            return system, BufferFactory
        except Exception as exc:
            raise CameraSdkUnavailable(
                "Lucid Arena Python API is not available. Install Arena SDK and arena_api."
            ) from exc

    @staticmethod
    def _node(nodemap, name):
        try:
            return nodemap.get_node(name)
        except Exception:
            return None

    @classmethod
    def _read(cls, nodemap, name, default=None):
        node = cls._node(nodemap, name)
        if node is None:
            return default
        try:
            return node.value
        except Exception:
            return default

    @classmethod
    def _set(cls, nodemap, name, value):
        if value is None:
            return
        node = cls._node(nodemap, name)
        if node is None or not getattr(node, "is_writable", True):
            return
        candidates = [value]
        if isinstance(value, bool):
            candidates += [1 if value else 0, "true" if value else "false"]
        if isinstance(value, (int, float)):
            candidates.append(str(value))
        last = None
        for candidate in candidates:
            try:
                node.value = candidate
                return
            except Exception as exc:
                last = exc
        if last:
            raise CameraAdapterError(f"Could not set Arena node {name}={value!r}: {last}")

    @staticmethod
    def _tl_set(tl, name, value):
        try:
            node = tl[name]
            node.value = value
        except Exception:
            pass

    @staticmethod
    def _destroy(system):
        try:
            system.destroy_device()
        except Exception:
            pass

    def discover(self, scan_type: str) -> list[CameraDevice]:
        if simulation_enabled():
            return self._simulation_devices(scan_type)
        if not self.supports_scan_type(scan_type):
            return []
        system, _ = self._sdk()
        devices = []
        try:
            arena_devices = system.create_device()
            for index, dev in enumerate(arena_devices):
                devices.append(
                    CameraDevice(
                        adapter_key=self.key,
                        backend_id=str(index),
                        serial=str(self._read(dev.nodemap, "DeviceSerialNumber", index)),
                        model=str(self._read(dev.nodemap, "DeviceModelName", "Lucid Camera")),
                        vendor=self.vendor,
                        transport="GigE Vision",
                        scan_type=scan_type,
                    )
                )
            return devices
        finally:
            self._destroy(system)

    def _with_device(self, device: CameraDevice):
        system, buffer_factory = self._sdk()
        devices = system.create_device()
        found = None
        for dev in devices:
            serial = str(self._read(dev.nodemap, "DeviceSerialNumber", ""))
            if serial == str(device.serial):
                found = dev
                break
        if found is None:
            self._destroy(system)
            raise CameraAdapterError(f"Lucid camera {device.serial} was not found.")
        return system, buffer_factory, found

    def read_settings(self, device: CameraDevice) -> CameraSettings:
        if device.extra.get("simulation"):
            return CameraSettings(
                exposure_us=1700.0, gain_db=24.0,
                width=1280 if device.scan_type == "area" else 400,
                height=720 if device.scan_type == "area" else 1460,
                pixel_format="Mono8",
            )
        system, _, dev = self._with_device(device)
        try:
            nm = dev.nodemap
            return CameraSettings(
                exposure_us=self._number(self._read(nm, "ExposureTime")),
                gain_db=self._number(self._read(nm, "Gain")),
                width=self._integer(self._read(nm, "Width")),
                height=self._integer(self._read(nm, "Height")),
                pixel_format=str(self._read(nm, "PixelFormat", "Mono8")),
                trigger_mode=str(self._read(nm, "TriggerMode", "")) or None,
                trigger_source=str(self._read(nm, "TriggerSource", "")) or None,
                acquisition_mode=str(self._read(nm, "AcquisitionMode", "")) or None,
            )
        finally:
            self._destroy(system)

    @staticmethod
    def _number(value):
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _integer(value):
        try:
            return int(value)
        except Exception:
            return None

    def _apply_to_device(self, dev, settings: CameraSettings, for_preview: bool = False):
        nm = dev.nodemap
        try:
            self._set(nm, "ExposureAuto", "Off")
        except Exception:
            pass
        self._set(nm, "ExposureTime", settings.exposure_us)
        self._set(nm, "Gain", settings.gain_db)
        self._set(nm, "Width", settings.width)
        self._set(nm, "Height", settings.height)
        self._set(nm, "PixelFormat", settings.pixel_format)

        if for_preview:
            try:
                self._set(nm, "TriggerMode", "Off")
            except Exception:
                pass
            try:
                self._set(nm, "AcquisitionMode", "Continuous")
            except Exception:
                pass
        else:
            if settings.trigger_mode:
                self._set(nm, "TriggerMode", settings.trigger_mode)
            if settings.trigger_source:
                self._set(nm, "TriggerSource", settings.trigger_source)
            if settings.acquisition_mode:
                self._set(nm, "AcquisitionMode", settings.acquisition_mode)

        tl = dev.tl_stream_nodemap
        self._tl_set(tl, "StreamAutoNegotiatePacketSize", True)
        self._tl_set(tl, "StreamPacketResendEnable", True)
        self._tl_set(tl, "StreamBufferHandlingMode", "NewestOnly")

    def apply_settings(self, device: CameraDevice, settings: CameraSettings) -> None:
        if device.extra.get("simulation"):
            return
        system, _, dev = self._with_device(device)
        try:
            try:
                dev.stop_stream()
            except Exception:
                pass
            self._apply_to_device(dev, settings, for_preview=False)
        finally:
            self._destroy(system)

    @staticmethod
    def _grab(dev, buffer_factory) -> np.ndarray | None:
        buf = None
        copied = None
        try:
            buf = dev.get_buffer()
            copied = buffer_factory.copy(buf)
            width = int(copied.width)
            height = int(copied.height)
            raw_type = ctypes.c_ubyte * (width * height)
            raw = raw_type.from_address(ctypes.addressof(copied.pbytes))
            return np.ctypeslib.as_array(raw).reshape((height, width)).copy()
        except Exception:
            return None
        finally:
            if buf is not None:
                try:
                    dev.requeue_buffer(buf)
                except Exception:
                    pass
            if copied is not None:
                try:
                    buffer_factory.destroy(copied)
                except Exception:
                    pass

    def grab_preview(self, device: CameraDevice, settings: CameraSettings) -> np.ndarray | None:
        if device.extra.get("simulation"):
            return self._simulation_preview(device)
        system, buffer_factory, dev = self._with_device(device)
        try:
            try:
                dev.stop_stream()
            except Exception:
                pass
            self._apply_to_device(dev, settings, for_preview=True)
            dev.start_stream()
            return self._grab(dev, buffer_factory)
        finally:
            try:
                dev.stop_stream()
            except Exception:
                pass
            self._destroy(system)

    def capture(
        self, device: CameraDevice, settings: CameraSettings, n_images: int,
        output_dir: str | Path, progress=None, should_stop=None,
    ) -> list[str]:
        if device.extra.get("simulation"):
            return self._simulation_capture(
                device, settings, n_images, output_dir, progress, should_stop
            )

        system, buffer_factory, dev = self._with_device(device)
        folder = ensure_device_folder(output_dir, device)
        paths: list[str] = []
        try:
            try:
                dev.stop_stream()
            except Exception:
                pass

            # Offline dataset capture is free-run by default.  Existing trigger
            # profiles can still be supplied through CameraSettings when needed.
            capture_settings = CameraSettings.from_dict(settings.to_dict())
            if not capture_settings.trigger_mode:
                capture_settings.trigger_mode = "Off"
            if not capture_settings.acquisition_mode:
                capture_settings.acquisition_mode = "Continuous"

            self._apply_to_device(dev, capture_settings, for_preview=False)
            dev.start_stream()

            for i in range(max(1, int(n_images))):
                if should_stop and should_stop():
                    break
                frame = self._grab(dev, buffer_factory)
                if frame is None:
                    continue
                path = save_frame(folder, device, frame, i + 1, ".png")
                paths.append(path)
                if progress:
                    progress(i + 1, n_images, path)
            return paths
        finally:
            try:
                dev.stop_stream()
            except Exception:
                pass
            self._destroy(system)
