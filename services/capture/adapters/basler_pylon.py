"""Basler pylon / pypylon camera adapter."""
from __future__ import annotations

from pathlib import Path

from .base import (
    AdapterCapabilities, CameraAdapter, CameraAdapterError, CameraDevice,
    CameraSdkUnavailable, CameraSettings, ensure_device_folder, save_frame,
    simulation_enabled,
)


class BaslerPylonAdapter(CameraAdapter):
    key = "basler"
    display_name = "Basler"
    vendor = "Basler"
    capabilities = AdapterCapabilities(
        scan_types=("area", "line"),
        sdk_name="Basler pylon / pypylon",
        install_hint="Install Basler pylon and the pypylon Python package.",
    )

    @classmethod
    def sdk_available(cls) -> bool:
        try:
            from pypylon import pylon  # noqa: F401
            return True
        except Exception:
            return False

    @staticmethod
    def _pylon():
        try:
            from pypylon import pylon
            return pylon
        except Exception as exc:
            raise CameraSdkUnavailable(
                "pypylon is not available. Install Basler pylon and pypylon."
            ) from exc

    def discover(self, scan_type: str) -> list[CameraDevice]:
        if simulation_enabled():
            return self._simulation_devices(scan_type)
        pylon = self._pylon()
        factory = pylon.TlFactory.GetInstance()
        result = []
        for index, info in enumerate(factory.EnumerateDevices()):
            serial = str(info.GetSerialNumber())
            model = str(info.GetModelName())
            device_class = str(info.GetDeviceClass())
            result.append(
                CameraDevice(
                    adapter_key=self.key,
                    backend_id=str(index),
                    serial=serial,
                    model=model,
                    vendor=self.vendor,
                    transport=device_class,
                    scan_type=scan_type,
                )
            )
        return result

    def _open(self, device: CameraDevice):
        pylon = self._pylon()
        factory = pylon.TlFactory.GetInstance()
        for info in factory.EnumerateDevices():
            if str(info.GetSerialNumber()) == str(device.serial):
                camera = pylon.InstantCamera(factory.CreateDevice(info))
                camera.Open()
                return pylon, camera
        raise CameraAdapterError(f"Basler camera {device.serial} was not found.")

    @staticmethod
    def _get(camera, name, default=None):
        try:
            return getattr(camera, name).Value
        except Exception:
            return default

    @staticmethod
    def _set(camera, name, value):
        if value is None:
            return
        try:
            node = getattr(camera, name)
            if hasattr(node, "SetValue"):
                node.SetValue(value)
            else:
                node.Value = value
        except Exception:
            pass

    def read_settings(self, device: CameraDevice) -> CameraSettings:
        if device.extra.get("simulation"):
            return CameraSettings(width=1280, height=720)
        _, cam = self._open(device)
        try:
            return CameraSettings(
                exposure_us=self._get(cam, "ExposureTime"),
                gain_db=self._get(cam, "Gain"),
                width=self._get(cam, "Width"),
                height=self._get(cam, "Height"),
                pixel_format=str(self._get(cam, "PixelFormat", "Mono8")),
                trigger_mode=str(self._get(cam, "TriggerMode", "")) or None,
                trigger_source=str(self._get(cam, "TriggerSource", "")) or None,
                acquisition_mode=str(self._get(cam, "AcquisitionMode", "")) or None,
            )
        finally:
            cam.Close()

    def _apply(self, cam, settings: CameraSettings):
        self._set(cam, "ExposureAuto", "Off")
        self._set(cam, "GainAuto", "Off")
        self._set(cam, "ExposureTime", settings.exposure_us)
        self._set(cam, "Gain", settings.gain_db)
        self._set(cam, "Width", settings.width)
        self._set(cam, "Height", settings.height)
        self._set(cam, "PixelFormat", settings.pixel_format)
        if settings.trigger_mode:
            self._set(cam, "TriggerMode", settings.trigger_mode)
        if settings.trigger_source:
            self._set(cam, "TriggerSource", settings.trigger_source)
        if settings.acquisition_mode:
            self._set(cam, "AcquisitionMode", settings.acquisition_mode)

    def apply_settings(self, device: CameraDevice, settings: CameraSettings) -> None:
        if device.extra.get("simulation"):
            return
        _, cam = self._open(device)
        try:
            self._apply(cam, settings)
        finally:
            cam.Close()

    def grab_preview(self, device: CameraDevice, settings: CameraSettings):
        if device.extra.get("simulation"):
            return self._simulation_preview(device)
        pylon, cam = self._open(device)
        try:
            preview = CameraSettings.from_dict(settings.to_dict())
            preview.trigger_mode = "Off"
            preview.acquisition_mode = "Continuous"
            self._apply(cam, preview)
            cam.StartGrabbingMax(1, pylon.GrabStrategy_LatestImageOnly)
            grab = cam.RetrieveResult(1500, pylon.TimeoutHandling_ThrowException)
            try:
                if not grab.GrabSucceeded():
                    return None
                return grab.Array.copy()
            finally:
                grab.Release()
        finally:
            try:
                cam.StopGrabbing()
            except Exception:
                pass
            cam.Close()

    def capture(
        self, device: CameraDevice, settings: CameraSettings, n_images: int,
        output_dir: str | Path, progress=None, should_stop=None,
    ) -> list[str]:
        if device.extra.get("simulation"):
            return self._simulation_capture(
                device, settings, n_images, output_dir, progress, should_stop
            )
        pylon, cam = self._open(device)
        folder = ensure_device_folder(output_dir, device)
        paths: list[str] = []
        try:
            capture_settings = CameraSettings.from_dict(settings.to_dict())
            if not capture_settings.trigger_mode:
                capture_settings.trigger_mode = "Off"
            if not capture_settings.acquisition_mode:
                capture_settings.acquisition_mode = "Continuous"
            self._apply(cam, capture_settings)
            cam.StartGrabbingMax(max(1, int(n_images)), pylon.GrabStrategy_OneByOne)

            i = 0
            while cam.IsGrabbing() and i < n_images:
                if should_stop and should_stop():
                    break
                grab = cam.RetrieveResult(2000, pylon.TimeoutHandling_ThrowException)
                try:
                    if not grab.GrabSucceeded():
                        continue
                    i += 1
                    path = save_frame(folder, device, grab.Array.copy(), i, ".png")
                    paths.append(path)
                    if progress:
                        progress(i, n_images, path)
                finally:
                    grab.Release()
            return paths
        finally:
            try:
                cam.StopGrabbing()
            except Exception:
                pass
            cam.Close()
