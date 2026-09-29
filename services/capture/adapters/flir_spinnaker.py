"""FLIR / Teledyne FLIR Spinnaker camera adapter."""
from __future__ import annotations

from pathlib import Path

from .base import (
    AdapterCapabilities, CameraAdapter, CameraAdapterError, CameraDevice,
    CameraSdkUnavailable, CameraSettings, ensure_device_folder, save_frame,
    simulation_enabled,
)


class FlirSpinnakerAdapter(CameraAdapter):
    key = "flir"
    display_name = "FLIR / Teledyne"
    vendor = "Teledyne FLIR"
    capabilities = AdapterCapabilities(
        scan_types=("area",),
        sdk_name="Spinnaker / PySpin",
        install_hint="Install FLIR Spinnaker SDK with the matching PySpin module.",
    )

    @classmethod
    def sdk_available(cls) -> bool:
        try:
            import PySpin  # noqa: F401
            return True
        except Exception:
            return False

    @staticmethod
    def _sdk():
        try:
            import PySpin
            return PySpin
        except Exception as exc:
            raise CameraSdkUnavailable(
                "PySpin is not available. Install the FLIR Spinnaker SDK Python package."
            ) from exc

    @staticmethod
    def _string(PySpin, nodemap, name, default=""):
        try:
            node = PySpin.CStringPtr(nodemap.GetNode(name))
            if PySpin.IsReadable(node):
                return str(node.GetValue())
        except Exception:
            pass
        return default

    def discover(self, scan_type: str) -> list[CameraDevice]:
        if simulation_enabled():
            return self._simulation_devices(scan_type)
        if scan_type != "area":
            return []
        PySpin = self._sdk()
        system = PySpin.System.GetInstance()
        cam_list = system.GetCameras()
        result = []
        try:
            for i in range(cam_list.GetSize()):
                cam = cam_list.GetByIndex(i)
                tl = cam.GetTLDeviceNodeMap()
                result.append(
                    CameraDevice(
                        adapter_key=self.key,
                        backend_id=str(i),
                        serial=self._string(PySpin, tl, "DeviceSerialNumber", str(i)),
                        model=self._string(PySpin, tl, "DeviceModelName", "FLIR Camera"),
                        vendor=self.vendor,
                        transport=self._string(PySpin, tl, "DeviceType", "GigE/USB3"),
                        scan_type=scan_type,
                    )
                )
            return result
        finally:
            cam_list.Clear()
            system.ReleaseInstance()

    def _open(self, device: CameraDevice):
        PySpin = self._sdk()
        system = PySpin.System.GetInstance()
        cam_list = system.GetCameras()
        found = None
        try:
            for i in range(cam_list.GetSize()):
                cam = cam_list.GetByIndex(i)
                serial = self._string(PySpin, cam.GetTLDeviceNodeMap(), "DeviceSerialNumber", "")
                if serial == str(device.serial):
                    found = cam
                    break
            if found is None:
                raise CameraAdapterError(f"FLIR camera {device.serial} was not found.")
            found.Init()
            return PySpin, system, cam_list, found
        except Exception:
            cam_list.Clear()
            system.ReleaseInstance()
            raise

    @staticmethod
    def _finish(system, cam_list, cam):
        try:
            cam.DeInit()
        except Exception:
            pass
        try:
            cam_list.Clear()
        except Exception:
            pass
        try:
            system.ReleaseInstance()
        except Exception:
            pass

    @staticmethod
    def _set_enum(PySpin, nodemap, name, value):
        if not value:
            return
        try:
            node = PySpin.CEnumerationPtr(nodemap.GetNode(name))
            if not PySpin.IsWritable(node):
                return
            entry = node.GetEntryByName(str(value))
            if PySpin.IsReadable(entry):
                node.SetIntValue(entry.GetValue())
        except Exception:
            pass

    @staticmethod
    def _set_float(PySpin, nodemap, name, value):
        if value is None:
            return
        try:
            node = PySpin.CFloatPtr(nodemap.GetNode(name))
            if PySpin.IsWritable(node):
                value = min(max(float(value), float(node.GetMin())), float(node.GetMax()))
                node.SetValue(value)
        except Exception:
            pass

    @staticmethod
    def _set_int(PySpin, nodemap, name, value):
        if value is None:
            return
        try:
            node = PySpin.CIntegerPtr(nodemap.GetNode(name))
            if PySpin.IsWritable(node):
                value = min(max(int(value), int(node.GetMin())), int(node.GetMax()))
                node.SetValue(value)
        except Exception:
            pass

    @staticmethod
    def _read_float(PySpin, nodemap, name):
        try:
            node = PySpin.CFloatPtr(nodemap.GetNode(name))
            return float(node.GetValue()) if PySpin.IsReadable(node) else None
        except Exception:
            return None

    @staticmethod
    def _read_int(PySpin, nodemap, name):
        try:
            node = PySpin.CIntegerPtr(nodemap.GetNode(name))
            return int(node.GetValue()) if PySpin.IsReadable(node) else None
        except Exception:
            return None

    @staticmethod
    def _read_enum(PySpin, nodemap, name, default=None):
        try:
            node = PySpin.CEnumerationPtr(nodemap.GetNode(name))
            entry = node.GetCurrentEntry()
            if PySpin.IsReadable(entry):
                return str(entry.GetSymbolic())
        except Exception:
            pass
        return default

    def read_settings(self, device: CameraDevice) -> CameraSettings:
        if device.extra.get("simulation"):
            return CameraSettings(width=1280, height=720)
        PySpin, system, cam_list, cam = self._open(device)
        try:
            nm = cam.GetNodeMap()
            return CameraSettings(
                exposure_us=self._read_float(PySpin, nm, "ExposureTime"),
                gain_db=self._read_float(PySpin, nm, "Gain"),
                width=self._read_int(PySpin, nm, "Width"),
                height=self._read_int(PySpin, nm, "Height"),
                pixel_format=self._read_enum(PySpin, nm, "PixelFormat", "Mono8"),
                trigger_mode=self._read_enum(PySpin, nm, "TriggerMode"),
                trigger_source=self._read_enum(PySpin, nm, "TriggerSource"),
                acquisition_mode=self._read_enum(PySpin, nm, "AcquisitionMode"),
            )
        finally:
            self._finish(system, cam_list, cam)

    def _apply(self, PySpin, cam, settings: CameraSettings):
        nm = cam.GetNodeMap()
        self._set_enum(PySpin, nm, "ExposureAuto", "Off")
        self._set_enum(PySpin, nm, "GainAuto", "Off")
        self._set_float(PySpin, nm, "ExposureTime", settings.exposure_us)
        self._set_float(PySpin, nm, "Gain", settings.gain_db)
        self._set_int(PySpin, nm, "Width", settings.width)
        self._set_int(PySpin, nm, "Height", settings.height)
        self._set_enum(PySpin, nm, "PixelFormat", settings.pixel_format)
        if settings.trigger_mode:
            self._set_enum(PySpin, nm, "TriggerMode", settings.trigger_mode)
        if settings.trigger_source:
            self._set_enum(PySpin, nm, "TriggerSource", settings.trigger_source)
        if settings.acquisition_mode:
            self._set_enum(PySpin, nm, "AcquisitionMode", settings.acquisition_mode)

    def apply_settings(self, device: CameraDevice, settings: CameraSettings) -> None:
        if device.extra.get("simulation"):
            return
        PySpin, system, cam_list, cam = self._open(device)
        try:
            self._apply(PySpin, cam, settings)
        finally:
            self._finish(system, cam_list, cam)

    def grab_preview(self, device: CameraDevice, settings: CameraSettings):
        if device.extra.get("simulation"):
            return self._simulation_preview(device)
        PySpin, system, cam_list, cam = self._open(device)
        try:
            preview = CameraSettings.from_dict(settings.to_dict())
            preview.trigger_mode = "Off"
            preview.acquisition_mode = "Continuous"
            self._apply(PySpin, cam, preview)
            cam.BeginAcquisition()
            image = cam.GetNextImage(1500)
            try:
                if image.IsIncomplete():
                    return None
                converted = image.Convert(PySpin.PixelFormat_Mono8, PySpin.HQ_LINEAR)
                return converted.GetNDArray().copy()
            finally:
                image.Release()
                try:
                    cam.EndAcquisition()
                except Exception:
                    pass
        finally:
            self._finish(system, cam_list, cam)

    def capture(
        self, device: CameraDevice, settings: CameraSettings, n_images: int,
        output_dir: str | Path, progress=None, should_stop=None,
    ) -> list[str]:
        if device.extra.get("simulation"):
            return self._simulation_capture(
                device, settings, n_images, output_dir, progress, should_stop
            )
        PySpin, system, cam_list, cam = self._open(device)
        folder = ensure_device_folder(output_dir, device)
        paths = []
        try:
            capture_settings = CameraSettings.from_dict(settings.to_dict())
            if not capture_settings.trigger_mode:
                capture_settings.trigger_mode = "Off"
            if not capture_settings.acquisition_mode:
                capture_settings.acquisition_mode = "Continuous"
            self._apply(PySpin, cam, capture_settings)
            cam.BeginAcquisition()
            for i in range(max(1, int(n_images))):
                if should_stop and should_stop():
                    break
                image = cam.GetNextImage(2000)
                try:
                    if image.IsIncomplete():
                        continue
                    converted = image.Convert(PySpin.PixelFormat_Mono8, PySpin.HQ_LINEAR)
                    path = save_frame(folder, device, converted.GetNDArray().copy(), i + 1, ".png")
                    paths.append(path)
                    if progress:
                        progress(i + 1, n_images, path)
                finally:
                    image.Release()
            return paths
        finally:
            try:
                cam.EndAcquisition()
            except Exception:
                pass
            self._finish(system, cam_list, cam)
