"""Hikrobot MVS SDK adapter built on the project's existing hik_capture.py."""
from __future__ import annotations

from pathlib import Path

import cv2

from .base import (
    AdapterCapabilities, CameraAdapter, CameraAdapterError, CameraDevice,
    CameraSdkUnavailable, CameraSettings, ensure_device_folder, save_frame,
    simulation_enabled,
)


class HikrobotMvsAdapter(CameraAdapter):
    key = "hikrobot"
    display_name = "Hikrobot MVS"
    vendor = "Hikrobot"
    capabilities = AdapterCapabilities(
        scan_types=("area",),
        sdk_name="Hikrobot MVS SDK",
        install_hint="Install Hikrobot MVS and its Python MvImport wrappers.",
    )

    @classmethod
    def sdk_available(cls) -> bool:
        try:
            import hik_capture  # noqa: F401
            return True
        except Exception:
            return False

    @staticmethod
    def _hkc():
        try:
            import hik_capture as hkc
            return hkc
        except Exception as exc:
            raise CameraSdkUnavailable(
                "Hikrobot MVS wrappers are not available. Install MVS / MvImport."
            ) from exc

    def discover(self, scan_type: str) -> list[CameraDevice]:
        if simulation_enabled():
            return self._simulation_devices(scan_type)
        if scan_type != "area":
            return []
        hkc = self._hkc()
        result = []
        for idx, serial, model, transport, _info in hkc.enumerate_cameras():
            result.append(
                CameraDevice(
                    adapter_key=self.key,
                    backend_id=str(idx),
                    serial=str(serial or idx),
                    model=str(model or "Hikrobot Camera"),
                    vendor=self.vendor,
                    transport=str(transport),
                    scan_type=scan_type,
                    extra={"index": int(idx)},
                )
            )
        return result

    def read_settings(self, device: CameraDevice) -> CameraSettings:
        if device.extra.get("simulation"):
            return CameraSettings(exposure_us=1700, gain_db=0, width=1280, height=720)
        hkc = self._hkc()
        index = int(device.extra.get("index", device.backend_id))
        limits = hkc.read_gain_exposure_limits(index) or {}
        exp = limits.get("ExposureTime")
        gain = limits.get("Gain")
        return CameraSettings(
            exposure_us=float(exp[2]) if exp else None,
            gain_db=float(gain[2]) if gain else None,
            pixel_format="Mono8",
        )

    def apply_settings(self, device: CameraDevice, settings: CameraSettings) -> None:
        if device.extra.get("simulation"):
            return
        hkc = self._hkc()
        index = int(device.extra.get("index", device.backend_id))
        devs = hkc.list_devices()
        target = next((d for d in devs if int(d.index) == index), None)
        if target is None:
            raise CameraAdapterError(f"Hikrobot camera index {index} was not found.")
        cam = hkc._open_camera(target.pinfo)
        try:
            try:
                hkc._gige_set_optimal_packet_size(cam)
            except Exception:
                pass
            hkc._configure(cam, settings.exposure_us, settings.gain_db)
            if settings.width:
                try:
                    cam.MV_CC_SetIntValue("Width", int(settings.width))
                except Exception:
                    pass
            if settings.height:
                try:
                    cam.MV_CC_SetIntValue("Height", int(settings.height))
                except Exception:
                    pass
        finally:
            try:
                cam.MV_CC_CloseDevice()
            except Exception:
                pass
            try:
                cam.MV_CC_DestroyHandle()
            except Exception:
                pass

    def grab_preview(self, device: CameraDevice, settings: CameraSettings):
        if device.extra.get("simulation"):
            return self._simulation_preview(device)
        hkc = self._hkc()
        index = int(device.extra.get("index", device.backend_id))
        return hkc.grab_live_frame(
            index=index,
            exposure_us=settings.exposure_us,
            gain_db=settings.gain_db,
            mirror=False,
        )

    def capture(
        self, device: CameraDevice, settings: CameraSettings, n_images: int,
        output_dir: str | Path, progress=None, should_stop=None,
    ) -> list[str]:
        if device.extra.get("simulation"):
            return self._simulation_capture(
                device, settings, n_images, output_dir, progress, should_stop
            )
        folder = ensure_device_folder(output_dir, device)
        paths: list[str] = []
        for i in range(max(1, int(n_images))):
            if should_stop and should_stop():
                break
            frame = self.grab_preview(device, settings)
            if frame is None:
                continue
            path = save_frame(folder, device, frame, i + 1, ".png")
            paths.append(path)
            if progress:
                progress(i + 1, n_images, path)
        return paths
