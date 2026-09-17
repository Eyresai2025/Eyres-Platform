# hik_capture.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Tuple
import os, sys, glob, struct, ctypes, tempfile
from pathlib import Path
from datetime import datetime
import numpy as np
import cv2
# ───────── MVS bootstrap ─────────
if struct.calcsize("P")*8 != 64:
    raise EnvironmentError("Use 64-bit Python with 64-bit MVS.")

WRAPPER_FILES = ("MvCameraControl_class.py", "PixelType_header.py")

DLL_NAME = "MvCameraControl.dll"

def _ensure_mvs_dll_on_path(wrapper_dir: Optional[str]):
    """
    Make sure the folder that contains MvCameraControl.dll is in the DLL search path.
    """
    # 🔹 Put your known runtime folder FIRST
    candidates = [
        r"C:\Program Files (x86)\Common Files\MVS\Runtime\Win64_x64",
    ]

    # 1) same folder as wrappers
    if wrapper_dir:
        candidates.append(wrapper_dir)

    # 2) from env vars (if you set MVS_HOME / MVSDK_HOME / HIKROBOT_MVS)
    for env in ("MVS_HOME", "MVSDK_HOME", "HIKROBOT_MVS"):
        base = os.environ.get(env)
        if not base:
            continue
        candidates.extend([
            os.path.join(base, "Development", "Libraries", "Win64", "MvCamera"),
            os.path.join(base, "Runtime", "Win64_x64"),
            os.path.join(base, "Bin", "Win64"),
            base,
        ])

    # 3) common default install paths
    for base in (r"C:\Program Files\MVS", r"C:\Program Files (x86)\MVS"):
        candidates.extend([
            os.path.join(base, "Development", "Libraries", "Win64", "MvCamera"),
            os.path.join(base, "Runtime", "Win64_x64"),
            os.path.join(base, "Bin", "Win64"),
            base,
        ])

    # Add the first directory where the DLL exists
    for d in candidates:
        if not d:
            continue
        dll_path = os.path.join(d, DLL_NAME)
        if os.path.isfile(dll_path):
            if hasattr(os, "add_dll_directory"):      # Python 3.8+
                os.add_dll_directory(d)
            else:                                     # older Python
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            # print(f"[hik_capture] using DLL dir: {d}")
            return



def _dir_has_wrappers(d: str) -> bool:
    return all(os.path.isfile(os.path.join(d, f)) for f in WRAPPER_FILES)

def _find_wrapper_dir() -> Optional[str]:
    for env_var in ("MVS_HOME", "MVSDK_HOME", "HIKROBOT_MVS"):
        base = os.environ.get(env_var)
        if base:
            for sub in ("Development\\Samples\\Python\\MvImport",
                        "Samples\\Python\\MvImport",
                        "MvImport"):
                d = os.path.join(base, sub)
                if _dir_has_wrappers(d):
                    return d
    here = Path(__file__).resolve().parent
    if _dir_has_wrappers(str(here)):
        return str(here)
    bases = [
        r"C:\Program Files\MVS",
        r"C:\Program Files (x86)\MVS",
        r"C:\Program Files\Common Files\MVS",
        r"C:\Program Files (x86)\Common Files\MVS",
    ]
    for base in bases:
        if os.path.isdir(base):
            for d in glob.glob(os.path.join(base, "**", "MvImport"), recursive=True):
                if _dir_has_wrappers(d):
                    return d
    return None

wrap_dir = _find_wrapper_dir()
if not wrap_dir:
    raise FileNotFoundError(
        "MvImport wrappers not found. Install MVS or copy "
        "MvCameraControl_class.py & PixelType_header.py next to this file."
    )

_ensure_mvs_dll_on_path(wrap_dir)

if wrap_dir not in sys.path:
    sys.path.insert(0, wrap_dir)

from MvCameraControl_class import * # type: ignore
from PixelType_header      import * # type: ignore



MV_OK     = getattr(sys.modules['MvCameraControl_class'], "MV_OK", 0)
PIX_MONO8 = PixelType_Gvsp_Mono8 # type: ignore
PIX_BGR8  = PixelType_Gvsp_BGR8_Packed # type: ignore
# --- add this to hik_capture.py ---
def enumerate_cameras():
    """
    Returns: list of (index, serial, model, transport_layer, raw_info)
    transport_layer is "GigE" or "USB3".
    """
    try:
        from MvCameraControl_class import MvCamera, MV_CC_DEVICE_INFO_LIST, MV_CC_DEVICE_INFO, MV_GIGE_DEVICE, MV_USB_DEVICE # type: ignore
        import ctypes
    except Exception as e:
        raise RuntimeError(f"Hik MVS wrappers not available: {e}")

    devs = MV_CC_DEVICE_INFO_LIST()
    cam = MvCamera()
    code = cam.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, devs)
    if code != 0:
        raise RuntimeError(f"EnumDevices failed: 0x{code:X}")

    out = []
    for i in range(devs.nDeviceNum):
        pinfo = ctypes.cast(devs.pDeviceInfo[i], ctypes.POINTER(MV_CC_DEVICE_INFO)).contents
        if pinfo.nTLayerType == MV_GIGE_DEVICE:
            ser  = ''.join(chr(b) for b in pinfo.SpecialInfo.stGigEInfo.chSerialNumber if b)
            name = ''.join(chr(b) for b in pinfo.SpecialInfo.stGigEInfo.chModelName if b)
            tl   = "GigE"
        else:
            ser  = ''.join(chr(b) for b in pinfo.SpecialInfo.stUsb3VInfo.chSerialNumber if b)
            name = ''.join(chr(b) for b in pinfo.SpecialInfo.stUsb3VInfo.chModelName if b)
            tl   = "USB3"
        out.append((i, ser, name, tl, pinfo))
    return out

# optional alias in case other code imports list_devices()
list_devices = enumerate_cameras

def _sdk_ok(code: int, where: str = ""):
    if code != MV_OK:
        raise RuntimeError(f"{where} failed: 0x{code:X}")

@dataclass
class Device:
    index: int
    serial: str
    name: str
    transport: str
    pinfo: MV_CC_DEVICE_INFO # type: ignore

def list_devices() -> List[Device]:
    devs = MV_CC_DEVICE_INFO_LIST() # type: ignore
    _sdk_ok(MvCamera().MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, devs), "EnumDevices") # type: ignore
    out: List[Device] = []
    for i in range(devs.nDeviceNum):
        pinfo = ctypes.cast(devs.pDeviceInfo[i], ctypes.POINTER(MV_CC_DEVICE_INFO)).contents # type: ignore
        if pinfo.nTLayerType == MV_GIGE_DEVICE: # type: ignore
            ser  = ''.join(chr(b) for b in pinfo.SpecialInfo.stGigEInfo.chSerialNumber if b)
            name = ''.join(chr(b) for b in pinfo.SpecialInfo.stGigEInfo.chModelName if b)
            tl   = "GigE"
        else:
            ser  = ''.join(chr(b) for b in pinfo.SpecialInfo.stUsb3VInfo.chSerialNumber if b)
            name = ''.join(chr(b) for b in pinfo.SpecialInfo.stUsb3VInfo.chModelName if b)
            tl   = "USB3"
        out.append(Device(i, ser, name, tl, pinfo))
    return out

def _open_camera(pinfo: MV_CC_DEVICE_INFO) -> MvCamera: # type: ignore
    cam = MvCamera() # type: ignore
    _sdk_ok(cam.MV_CC_CreateHandle(pinfo), "CreateHandle")
    try:
        _sdk_ok(cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0), "OpenDevice") # type: ignore
    except Exception:
        cam.MV_CC_DestroyHandle()
        raise
    return cam

def _gige_set_optimal_packet_size(cam: MvCamera): # type: ignore
    try:
        size = cam.MV_CC_GetOptimalPacketSize()
        if size and size > 0:
            cam.MV_CC_SetIntValue("GevSCPSPacketSize", size)
    except Exception:
        pass

def _configure(cam: MvCamera, exposure_us: Optional[float], gain_db: Optional[float]): # type: ignore
    cam.MV_CC_SetEnumValue("AcquisitionMode", 2)  # Continuous
    cam.MV_CC_SetEnumValue("TriggerMode", 0)      # Off

    # Manual exposure/gain
    try:
        cam.MV_CC_SetEnumValue("ExposureAuto", 0)
    except Exception:
        pass
    try:
        cam.MV_CC_SetEnumValue("GainAuto", 0)
    except Exception:
        pass

    _sdk_ok(cam.MV_CC_SetEnumValue("PixelFormat", PIX_MONO8), "Set PixelFormat Mono8")

    # ✅ Clamp to camera limits before setting
    if exposure_us is not None:
        _set_float_clamped(cam, "ExposureTime", float(exposure_us), where="ExposureTime")

    if gain_db is not None:
        _set_float_clamped(cam, "Gain", float(gain_db), where="Gain")


def _grab_loop(cam: MvCamera, out_dir: str, frames: int, mirror: bool, # type: ignore
               progress_cb: Optional[Callable[[int, str], None]] = None):
    os.makedirs(out_dir, exist_ok=True)
    mirror_dir = os.path.join(out_dir, "MIRRORED") if mirror else None
    if mirror_dir: os.makedirs(mirror_dir, exist_ok=True)

    ival = MVCC_INTVALUE() # type: ignore
    _sdk_ok(cam.MV_CC_GetIntValue("PayloadSize", ival), "Get PayloadSize")
    buf  = (ctypes.c_ubyte * ival.nCurValue)()
    info = MV_FRAME_OUT_INFO_EX() # type: ignore
    params = [int(cv2.IMWRITE_JPEG_QUALITY), 95]

    _sdk_ok(cam.MV_CC_StartGrabbing(), "StartGrabbing")
    try:
        for n in range(frames):
            ret = cam.MV_CC_GetOneFrameTimeout(buf, ctypes.sizeof(buf), info, 1000)
            if ret != MV_OK:
                continue
            raw = memoryview(buf)[:info.nFrameLen]
            if info.enPixelType == PIX_MONO8:
                img = np.frombuffer(raw, dtype=np.uint8).reshape(info.nHeight, info.nWidth)
            elif info.enPixelType == PIX_BGR8:
                bgr = np.frombuffer(raw, dtype=np.uint8).reshape(info.nHeight, info.nWidth, 3)
                img = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            else:
                continue
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            path = os.path.join(out_dir, f"cam_{ts}_{n+1:03d}.jpg")
            cv2.imwrite(path, img, params)
            if progress_cb:
                try: progress_cb(n, path)
                except Exception: pass
            if mirror:
                cv2.imwrite(os.path.join(mirror_dir, os.path.basename(path)), cv2.flip(img, 1), params)
    finally:
        cam.MV_CC_StopGrabbing()
        cam.MV_CC_CloseDevice()
        cam.MV_CC_DestroyHandle()

def capture_multi(
    indices: Iterable[int],
    frames: int,
    base_out: str,
    mirror: bool = False,
    exposure_us: Optional[float] = None,
    gain_db: Optional[float] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,  # (cam_idx, frame_idx, path)
):
    """
    Capture from multiple cameras (sequentially, safe) and save into:
      base_out / cam_<index> / *.jpg

    progress_cb: called per frame with (cam_index, frame_idx, path)
    """
    os.makedirs(base_out, exist_ok=True)
    devs = list_devices()
    idx_set = set(indices)
    by_index = {d.index: d for d in devs if d.index in idx_set}
    for idx in indices:
        if idx not in by_index:
            raise RuntimeError(f"Camera index {idx} not found. Available: {[d.index for d in devs]}")

    for idx in indices:
        d = by_index[idx]
        cam = _open_camera(d.pinfo)
        try:
            _gige_set_optimal_packet_size(cam)
            _configure(cam, exposure_us, gain_db)
            out_dir = os.path.join(base_out, f"cam_{idx}")
            def _cb(frame_i: int, p: str):
                if progress_cb:
                    progress_cb(idx, frame_i, p)
            _grab_loop(cam, out_dir, frames, mirror, _cb)
        finally:
            # Safety handled inside _grab_loop, but keep a fallback
            try: cam.MV_CC_StopGrabbing()
            except Exception: pass
            try: cam.MV_CC_CloseDevice()
            except Exception: pass
            try: cam.MV_CC_DestroyHandle()
            except Exception: pass

def grab_live_frame(
    index: int,
    exposure_us: Optional[float] = None,
    gain_db: Optional[float] = None,
    mirror: bool = False,
) -> Optional[np.ndarray]:
    """
    Fast UI preview grab:
      - open camera
      - configure (with clamped Gain/ExposureTime)
      - start grabbing
      - read 1 frame
      - close camera
      - return Mono8 numpy array (H,W) or None
    """
    cam = None
    try:
        devs = list_devices()
        if index < 0 or index >= len(devs):
            return None

        d = devs[index]
        cam = _open_camera(d.pinfo)

        try:
            _gige_set_optimal_packet_size(cam)
        except Exception:
            pass

        # ✅ configure with clamping
        _configure(cam, exposure_us, gain_db)

        # Prepare buffer
        ival = MVCC_INTVALUE() # type: ignore
        _sdk_ok(cam.MV_CC_GetIntValue("PayloadSize", ival), "Get PayloadSize")
        buf = (ctypes.c_ubyte * ival.nCurValue)()
        info = MV_FRAME_OUT_INFO_EX() # type: ignore

        _sdk_ok(cam.MV_CC_StartGrabbing(), "StartGrabbing")
        try:
            ret = cam.MV_CC_GetOneFrameTimeout(buf, ctypes.sizeof(buf), info, 1000)
            if ret != MV_OK:
                return None

            raw = memoryview(buf)[:info.nFrameLen]

            if info.enPixelType == PIX_MONO8:
                img = np.frombuffer(raw, dtype=np.uint8).reshape(info.nHeight, info.nWidth).copy()
            elif info.enPixelType == PIX_BGR8:
                bgr = np.frombuffer(raw, dtype=np.uint8).reshape(info.nHeight, info.nWidth, 3)
                img = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            else:
                return None

            if mirror:
                img = cv2.flip(img, 1)
            return img

        finally:
            try:
                cam.MV_CC_StopGrabbing()
            except Exception:
                pass

    except Exception as e:
        print(f"[hik_capture] grab_live_frame error IDX {index}: {e}")
        return None

    finally:
        if cam is not None:
            try: cam.MV_CC_CloseDevice()
            except Exception: pass
            try: cam.MV_CC_DestroyHandle()
            except Exception: pass

def _floatvalue_to_tuple(fv) -> Optional[tuple]:
    """
    MVCC_FLOATVALUE typically has fMin, fMax, fCurValue.
    Some wrapper variants may name fields differently; we try safely.
    """
    try:
        fmin = float(getattr(fv, "fMin"))
        fmax = float(getattr(fv, "fMax"))
        fcur = float(getattr(fv, "fCurValue"))
        return (fmin, fmax, fcur)
    except Exception:
        return None


def _get_float_limits(cam: MvCamera, name: str) -> Optional[Tuple[float, float, float]]: # type: ignore
    """
    Returns (min, max, cur) for a float node, or None if not supported.
    """
    try:
        fv = MVCC_FLOATVALUE() # type: ignore
        code = cam.MV_CC_GetFloatValue(name, fv)
        if code != MV_OK:
            return None
        t = _floatvalue_to_tuple(fv)
        return t
    except Exception:
        return None


def _clamp(v: float, lo: float, hi: float) -> float:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def _set_float_clamped(cam: MvCamera, name: str, value: float, where: str = "") -> float: # type: ignore
    """
    Clamp value to node limits (if available) and set it.
    Returns the value actually applied.
    """
    v = float(value)
    lim = _get_float_limits(cam, name)
    if lim is not None:
        lo, hi, _cur = lim
        v = _clamp(v, lo, hi)

    code = cam.MV_CC_SetFloatValue(name, v)
    if code != MV_OK:
        raise RuntimeError(f"{where} SetFloat({name}={v}) failed: 0x{code:X}")
    return v

def read_gain_exposure_limits(index: int) -> dict:
    """
    Returns: {"ExposureTime": (min,max,cur), "Gain": (min,max,cur)} for a camera index.
    """
    cam = None
    try:
        devs = list_devices()
        d = devs[index]
        cam = _open_camera(d.pinfo)

        out = {}
        exp = _get_float_limits(cam, "ExposureTime")
        if exp: out["ExposureTime"] = exp

        gain = _get_float_limits(cam, "Gain")
        if gain: out["Gain"] = gain

        return out
    finally:
        if cam is not None:
            try: cam.MV_CC_CloseDevice()
            except Exception: pass
            try: cam.MV_CC_DestroyHandle()
            except Exception: pass
