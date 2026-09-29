"""Generic GenICam / GenTL adapter using the Harvesters library."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from .base import (
    AdapterCapabilities, CameraAdapter, CameraAdapterError, CameraDevice,
    CameraSdkUnavailable, CameraSettings, ensure_device_folder, save_frame,
    simulation_enabled,
)


class HarvesterGenicamAdapter(CameraAdapter):
    key = "genicam"
    display_name = "Other GenICam"
    vendor = "GenICam"
    cti_env = "EYRES_GENTL_CTI"
    capabilities = AdapterCapabilities(
        scan_types=("area", "line"),
        sdk_name="GenTL / Harvesters",
        install_hint=(
            "Install harvesters and configure EYRES_GENTL_CTI with one or more "
            "GenTL .cti producer paths separated by ';'."
        ),
    )

    @classmethod
    def _cti_paths(cls) -> list[str]:
        raw = os.getenv(cls.cti_env, "").strip()
        return [p.strip() for p in raw.split(";") if p.strip()]

    @classmethod
    def sdk_available(cls) -> bool:
        try:
            import harvesters.core  # noqa: F401
        except Exception:
            return False
        return bool(cls._cti_paths())

    @classmethod
    def _new_harvester(cls):
        try:
            from harvesters.core import Harvester
        except Exception as exc:
            raise CameraSdkUnavailable(
                "Harvesters is not installed. Install the 'harvesters' package."
            ) from exc

        paths = cls._cti_paths()
        if not paths:
            raise CameraSdkUnavailable(
                f"No GenTL producer configured. Set {cls.cti_env} to the required .cti path."
            )

        h = Harvester()
        for path in paths:
            h.add_file(path)
        h.update()
        return h

    @staticmethod
    def _info_attr(info, *names, default=""):
        for name in names:
            try:
                value = getattr(info, name)
                if value not in (None, ""):
                    return str(value)
            except Exception:
                pass
        return default

    def discover(self, scan_type: str) -> list[CameraDevice]:
        if simulation_enabled():
            return self._simulation_devices(scan_type)
        h = self._new_harvester()
        try:
            result = []
            for index, info in enumerate(h.device_info_list):
                serial = self._info_attr(
                    info, "serial_number", "property_dict",
                    default=str(index),
                )
                if serial.startswith("{"):
                    serial = str(index)
                result.append(
                    CameraDevice(
                        adapter_key=self.key,
                        backend_id=str(index),
                        serial=self._info_attr(info, "serial_number", default=str(index)),
                        model=self._info_attr(info, "model", "model_name", default="GenICam Camera"),
                        vendor=self._info_attr(info, "vendor", "vendor_name", default=self.vendor),
                        transport=self._info_attr(info, "tl_type", "transport_layer_type", default="GenTL"),
                        scan_type=scan_type,
                        extra={"cti_env": self.cti_env},
                    )
                )
            return result
        finally:
            try:
                h.reset()
            except Exception:
                pass

    def _open(self, device: CameraDevice):
        h = self._new_harvester()
        try:
            ia = h.create(index=int(device.backend_id))
            return h, ia
        except Exception:
            try:
                h.reset()
            except Exception:
                pass
            raise

    @staticmethod
    def _finish(h, ia):
        try:
            ia.stop()
        except Exception:
            pass
        try:
            ia.destroy()
        except Exception:
            pass
        try:
            h.reset()
        except Exception:
            pass

    @staticmethod
    def _node_map(ia):
        return ia.remote_device.node_map

    @staticmethod
    def _get_node(nm, name):
        try:
            return getattr(nm, name)
        except Exception:
            return None

    @classmethod
    def _read(cls, nm, name, default=None):
        node = cls._get_node(nm, name)
        if node is None:
            return default
        try:
            return node.value
        except Exception:
            return default

    @classmethod
    def _set(cls, nm, name, value):
        if value is None:
            return
        node = cls._get_node(nm, name)
        if node is None:
            return
        try:
            node.value = value
        except Exception:
            pass

    def read_settings(self, device: CameraDevice) -> CameraSettings:
        if device.extra.get("simulation"):
            return CameraSettings(width=1280, height=720 if device.scan_type == "area" else 1200)
        h, ia = self._open(device)
        try:
            nm = self._node_map(ia)
            return CameraSettings(
                exposure_us=self._number(self._read(nm, "ExposureTime")),
                gain_db=self._number(self._read(nm, "Gain")),
                width=self._integer(self._read(nm, "Width")),
                height=self._integer(self._read(nm, "Height")),
                pixel_format=str(self._read(nm, "PixelFormat", "Mono8")),
                trigger_mode=self._text(self._read(nm, "TriggerMode")),
                trigger_source=self._text(self._read(nm, "TriggerSource")),
                acquisition_mode=self._text(self._read(nm, "AcquisitionMode")),
            )
        finally:
            self._finish(h, ia)

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

    @staticmethod
    def _text(value):
        value = str(value or "").strip()
        return value or None

    def _apply(self, ia, settings: CameraSettings, preview=False):
        nm = self._node_map(ia)
        self._set(nm, "ExposureAuto", "Off")
        self._set(nm, "GainAuto", "Off")
        self._set(nm, "ExposureTime", settings.exposure_us)
        self._set(nm, "Gain", settings.gain_db)
        self._set(nm, "Width", settings.width)
        self._set(nm, "Height", settings.height)
        self._set(nm, "PixelFormat", settings.pixel_format)
        if preview:
            self._set(nm, "TriggerMode", "Off")
            self._set(nm, "AcquisitionMode", "Continuous")
        else:
            self._set(nm, "TriggerMode", settings.trigger_mode)
            self._set(nm, "TriggerSource", settings.trigger_source)
            self._set(nm, "AcquisitionMode", settings.acquisition_mode)

    @staticmethod
    def _buffer_to_array(buffer):
        component = buffer.payload.components[0]
        data = np.asarray(component.data).copy()
        height = int(getattr(component, "height", 1) or 1)
        width = int(getattr(component, "width", data.size) or data.size)
        components = int(getattr(component, "num_components_per_pixel", 1) or 1)
        if components > 1:
            return data.reshape(height, width, components)
        return data.reshape(height, width)

    def apply_settings(self, device: CameraDevice, settings: CameraSettings) -> None:
        if device.extra.get("simulation"):
            return
        h, ia = self._open(device)
        try:
            self._apply(ia, settings, preview=False)
        finally:
            self._finish(h, ia)

    def grab_preview(self, device: CameraDevice, settings: CameraSettings):
        if device.extra.get("simulation"):
            return self._simulation_preview(device)
        h, ia = self._open(device)
        try:
            self._apply(ia, settings, preview=True)
            ia.start()
            with ia.fetch(timeout=2.0) as buffer:
                return self._buffer_to_array(buffer)
        finally:
            self._finish(h, ia)

    def capture(
        self, device: CameraDevice, settings: CameraSettings, n_images: int,
        output_dir: str | Path, progress=None, should_stop=None,
    ) -> list[str]:
        if device.extra.get("simulation"):
            return self._simulation_capture(
                device, settings, n_images, output_dir, progress, should_stop
            )
        h, ia = self._open(device)
        folder = ensure_device_folder(output_dir, device)
        paths = []
        try:
            capture_settings = CameraSettings.from_dict(settings.to_dict())
            if not capture_settings.trigger_mode:
                capture_settings.trigger_mode = "Off"
            if not capture_settings.acquisition_mode:
                capture_settings.acquisition_mode = "Continuous"
            self._apply(ia, capture_settings, preview=False)
            ia.start()
            for i in range(max(1, int(n_images))):
                if should_stop and should_stop():
                    break
                with ia.fetch(timeout=3.0) as buffer:
                    frame = self._buffer_to_array(buffer)
                path = save_frame(folder, device, frame, i + 1, ".png")
                paths.append(path)
                if progress:
                    progress(i + 1, n_images, path)
            return paths
        finally:
            self._finish(h, ia)
