from __future__ import annotations
import os, sys, time, ctypes, traceback
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional
import numpy as np
import cv2
from PyQt5 import QtCore
from pathlib import Path
from datetime import datetime

CAMERA_SIMULATION = os.getenv("EYRES_CAMERA_SIMULATION", "0").strip().lower() in {"1", "true", "yes", "on"}


def simulation_frame(mode: str, frame_number: int = 0) -> np.ndarray:
    """Create a deterministic industrial test frame for UI-only validation."""
    height, width = ((900, 640) if mode == "line" else (720, 1280))
    y, x = np.indices((height, width))
    image = ((x * 0.10 + y * 0.06 + frame_number * 7) % 150 + 45).astype(np.uint8)
    cx = int(width * (0.50 + 0.08 * np.sin(frame_number / 3.0)))
    cy = int(height * 0.52)
    cv2.circle(image, (cx, cy), max(45, min(width, height) // 7), 205, -1)
    cv2.rectangle(image, (40, 42), (width - 40, height - 42), 225, 2)
    cv2.putText(image, "EYRES CAMERA SIMULATION", (58, 85), cv2.FONT_HERSHEY_SIMPLEX,
                1.0 if width > 800 else 0.65, 245, 2, cv2.LINE_AA)
    cv2.putText(image, f"{mode.upper()}  FRAME {frame_number + 1:03d}", (58, height - 70),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, 235, 2, cv2.LINE_AA)
    return image


def _app_base_dir() -> Path:
    """
    Root folder of the app (PyInstaller-safe).
    - From source: folder of the current .py
    - From PyInstaller EXE: the temporary _MEIPASS dir
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]

def _projects_root() -> Path:
    """
    Root Projects folder next to EXE or in user space (your earlier logic).
    Example:
      <exe_dir>/EyresAiPlatform/Projects
    """
    base = Path(os.getcwd())  # or AppData approach if you used before
    root = base / "EyresAiPlatform" / "Projects"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_name(name: str) -> str:
    name = (name or "Project").strip()
    name = "".join(ch if ch.isalnum() or ch in " _-" else "_" for ch in name)
    return name.replace(" ", "_")


def get_project_folder(project_name: str) -> Path:
    """
    Final folder:
      EyresAiPlatform/Projects/<ProjectName>
    """
    folder = _projects_root() / _safe_name(project_name)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _media_dirs() -> list[Path]:
    """
    Candidate media directories next to the app.
    Supports both 'Media' and 'media' names.
    """
    base = _app_base_dir()
    return [base / "Media", base / "media"]

def _find_first_in_media(patterns: Iterable[str]) -> Optional[Path]:
    """
    Return the first existing file in any media directory that matches
    one of the provided filenames/globs. Exact filename wins over glob.
    """
    for mdir in _media_dirs():
        if not mdir.exists():
            continue
        # exact name first
        for name in patterns:
            p = mdir / name
            if p.is_file():
                return p
        # then globs (e.g., 'camera*.png')
        for name in patterns:
            for g in (mdir.glob(name) if any(ch in name for ch in "*?[]") else []):
                if g.is_file():
                    return g
    return None

# ---------- Optional icons (dynamic) ----------
_area_path = _find_first_in_media([
    "capture_area.png",          # your current filename
    "*.png", "*.svg", "*.ico"  # last resorts
])
_line_path = _find_first_in_media([
    "capture_area.png",
    "*.png", "*.svg", "*.ico"
])

# Keep public names as strings (or empty) because StepMode checks with os.path.exists
AREA_ICON_PATH = str(_area_path) if _area_path else ""
LINE_ICON_PATH = str(_line_path) if _line_path else ""
# ---------- Optional line-capture helpers (Lucid line scan, SingleFrame) ----------
LC_HAS_HELPERS = False
try:
    # line_capture.py lives in the base folder; we reuse its logic
    from line_capture import ( # type: ignore
        setup_singleframe as lc_setup_singleframe,
        snap_one as lc_snap_one,
        save_image_robust as lc_save_image_robust,
        GAP_SECONDS as LC_GAP_SECONDS,   # 6s in your script
    )
    LC_HAS_HELPERS = True
except Exception:
    LC_HAS_HELPERS = False
    LC_GAP_SECONDS = 0  # no enforced gap if helpers missing
# ---------- Arena SDK guard ----------
ARENA_OK = True
try:
    from arena_api.system import system
    from arena_api.buffer import BufferFactory
except Exception as e:
    ARENA_OK = False
    ARENA_IMPORT_ERR = str(e)

# ---------- Arena helpers ----------
@dataclass
class CamInfo:
    index: int
    model: str
    serial: str

def list_cameras() -> List[CamInfo]:
    if CAMERA_SIMULATION:
        return [CamInfo(0, "EyRes Virtual Lucid Camera", "SIM-LUCID-001")]
    if not ARENA_OK:
        raise RuntimeError(f"arena_api not available: {ARENA_IMPORT_ERR}")
    devices = system.create_device()
    out = []
    for i, dev in enumerate(devices):
        model = dev.nodemap.get_node("DeviceModelName").value
        serial = dev.nodemap.get_node("DeviceSerialNumber").value
        out.append(CamInfo(i, model, serial))
    return out

def _set_nm_value(nm, name: str, value):
    node = nm.get_node(name)
    if not getattr(node, "is_writable", False):
        return
    last = None
    seq = [value]
    if isinstance(value, bool):
        seq += [1 if value else 0, "true" if value else "false"]
    if isinstance(value, (int, float)):
        seq += [str(value)]
    for c in seq:
        try:
            node.value = c
            return
        except Exception as e:
            last = e
    raise RuntimeError(f"Failed to set node '{name}' to {value!r}: {last}")

def _set_tl_value(tl, name: str, value):
    try:
        node = tl[name]
    except Exception:
        return
    last = None
    seq = [value]
    if isinstance(value, bool):
        seq += [1 if value else 0, "true" if value else "false"]
    if isinstance(value, (int, float)):
        seq += [str(value)]
    for c in seq:
        try:
            node.value = c
            return
        except Exception as e:
            last = e
    raise RuntimeError(f"Failed to set TL node '{name}' to {value!r}: {last}")

def _safe_stop(dev):
    try:
        dev.stop_stream()
    except Exception:
        pass

def setup_area_camera(dev, overrides: Optional[Dict[str, float]] = None):
    nm = dev.nodemap
    _safe_stop(dev)

    # Turn off trigger + auto exposure if possible, but DO NOT
    # override Width/Height/PixelFormat etc. (unless overrides say so)
    try:
        _set_nm_value(nm, "TriggerMode", "Off")
    except Exception:
        pass
    try:
        _set_nm_value(nm, "ExposureAuto", "Off")
    except Exception:
        pass

    # Transport layer: keep the safe defaults
    tl = dev.tl_stream_nodemap
    _set_tl_value(tl, "StreamAutoNegotiatePacketSize", True)
    _set_tl_value(tl, "StreamPacketResendEnable", True)

    # Apply optional overrides (ExposureTime / Gain / Width / Height / PixelFormat)
    if overrides:
        try:
            if "ExposureTime" in overrides:
                _set_nm_value(nm, "ExposureTime", float(overrides["ExposureTime"]))
        except Exception:
            pass
        try:
            if "Gain" in overrides:
                _set_nm_value(nm, "Gain", float(overrides["Gain"]))
        except Exception:
            pass
        try:
            if "Width" in overrides and overrides["Width"]:
                _set_nm_value(nm, "Width", int(overrides["Width"]))
        except Exception:
            pass
        try:
            if "Height" in overrides and overrides["Height"]:
                _set_nm_value(nm, "Height", int(overrides["Height"]))
        except Exception:
            pass
        try:
            pf = overrides.get("PixelFormat")
            if pf:
                _set_nm_value(nm, "PixelFormat", pf)
        except Exception:
            pass

    # Start streaming; we grab frames with arena_grab_gray()
    dev.start_stream()




def setup_line_camera(dev, overrides: Optional[Dict[str, float]] = None):
    nm = dev.nodemap
    _safe_stop(dev)

    if LC_HAS_HELPERS:
        lc_setup_singleframe(nm)
    else:
        try:
            h_node = nm.get_node("Height")
            w_node = nm.get_node("Width")
            h_node.value = h_node.max
            w_node.value = w_node.max
        except Exception:
            pass
        _set_nm_value(nm, "PixelFormat", "Mono8")
        _set_nm_value(nm, "ExposureTime", 1700.0)
        _set_nm_value(nm, "Gain", 24.0)
        _set_nm_value(nm, "TriggerMode", "Off")
        _set_nm_value(nm, "AcquisitionMode", "SingleFrame")

    tl = dev.tl_stream_nodemap
    _set_tl_value(tl, "StreamAutoNegotiatePacketSize", True)
    _set_tl_value(tl, "StreamPacketResendEnable", True)
    _set_tl_value(tl, "StreamBufferHandlingMode", "NewestOnly")

    # Apply overrides AFTER base config
    if overrides:
        try:
            if "ExposureTime" in overrides:
                _set_nm_value(nm, "ExposureTime", float(overrides["ExposureTime"]))
        except Exception:
            pass
        try:
            if "Gain" in overrides:
                _set_nm_value(nm, "Gain", float(overrides["Gain"]))
        except Exception:
            pass
        try:
            if "Width" in overrides and overrides["Width"]:
                _set_nm_value(nm, "Width", int(overrides["Width"]))
        except Exception:
            pass
        try:
            if "Height" in overrides and overrides["Height"]:
                _set_nm_value(nm, "Height", int(overrides["Height"]))
        except Exception:
            pass
        try:
            pf = overrides.get("PixelFormat")
            if pf:
                _set_nm_value(nm, "PixelFormat", pf)
        except Exception:
            pass

def setup_line_preview_live(dev, overrides: Optional[Dict[str, float]] = None):
    """
    Line-scan LIVE PREVIEW configuration (ArenaView-style):
    - Continuous acquisition
    - TriggerMode Off
    - Mono8
    - Uses Height/Width max
    - Starts the stream

    NOTE: This is *only* for Camera Settings preview.
          The capture step still uses setup_line_camera / lc_snap_one.
    """
    nm = dev.nodemap
    _safe_stop(dev)  # make sure nothing is running

    # Large ROI for preview
    try:
        h_node = nm.get_node("Height")
        w_node = nm.get_node("Width")
        h_node.value = h_node.max
        w_node.value = w_node.max
    except Exception:
        pass

    # Basic mono + continuous, no trigger
    _set_nm_value(nm, "PixelFormat", "Mono8")
    _set_nm_value(nm, "TriggerMode", "Off")
    _set_nm_value(nm, "AcquisitionMode", "Continuous")

    # Exposure / gain overrides (from UI)
    if overrides:
        try:
            if "ExposureTime" in overrides:
                _set_nm_value(nm, "ExposureTime", float(overrides["ExposureTime"]))
        except Exception:
            pass
        try:
            if "Gain" in overrides:
                _set_nm_value(nm, "Gain", float(overrides["Gain"]))
        except Exception:
            pass

    # Transport layer
    tl = dev.tl_stream_nodemap
    _set_tl_value(tl, "StreamAutoNegotiatePacketSize", True)
    _set_tl_value(tl, "StreamPacketResendEnable", True)
    _set_tl_value(tl, "StreamBufferHandlingMode", "NewestOnly")

    # NOW start live streaming (this is what ArenaView "Continuous" does)
    dev.start_stream()



def _read_nodes_safe(nm, names):
    out = {}
    for n in names:
        try:
            out[n] = str(nm.get_node(n).value)
        except Exception:
            out[n] = "<N/A>"
    return out

def _read_tl_nodes_safe(tl, names):
    out = {}
    for n in names:
        try:
            out[n] = str(tl[n].value)
        except Exception:
            out[n] = "<N/A>"
    return out

def arena_grab_gray(dev) -> Optional[np.ndarray]:
    try:
        buf = dev.get_buffer()
        item = BufferFactory.copy(buf)
        w, h = item.width, item.height
        raw_type = ctypes.c_ubyte * (w * h)
        raw = raw_type.from_address(ctypes.addressof(item.pbytes))
        img = np.ctypeslib.as_array(raw).reshape((h, w)).copy()
        dev.requeue_buffer(buf)
        return img
    except Exception:
        return None
    
# ---- HIK MVS listing via hik_capture.py ----
def list_mvs_cameras() -> List[CamInfo]:
    """
    Uses hik_capture.enumerate_cameras() to build CamInfo(index, model, serial)
    Expects enumerate_cameras() -> List[ (idx, serial, model, tl, raw_info) ] from hik_capture.py
    """
    if CAMERA_SIMULATION:
        return [CamInfo(0, "EyRes Virtual Hikrobot [SIM]", "SIM-MVS-001")]
    import hik_capture as hkc
    out=[]
    for idx, ser, model, tl, _info in hkc.enumerate_cameras():
        out.append(CamInfo(index=idx, model=f"{model} [{tl}]", serial=ser))
    return out


# ---------- Worker ----------
class CaptureWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(int, int)
    status = QtCore.pyqtSignal(str)
    finished_ok = QtCore.pyqtSignal(list)
    failed = QtCore.pyqtSignal(str)

    def __init__(
        self,
        mode: str,
        serials: List[str],
        n_images: int,
        base_dir: str,
        overrides: Optional[Dict[str, Dict[str, float]]] = None,
    ):
        super().__init__()
        self.mode = mode
        self.serials = serials
        self.n_images = max(1, int(n_images))
        self.base_dir = base_dir
        self.overrides = overrides or {}   # {serial: {"ExposureTime": .., "Gain": ..}}
        self._stop = False
        
    def stop(self): self._stop = True

    def run(self):
        if CAMERA_SIMULATION:
            self._run_simulation()
            return
        if not ARENA_OK:
            self.failed.emit(f"arena_api not available: {ARENA_IMPORT_ERR}")
            return
        try:
            devices = system.create_device()
            ser2dev = {}
            for dev in devices:
                s = dev.nodemap.get_node("DeviceSerialNumber").value
                if s in self.serials:
                    ser2dev[s] = dev
            if not ser2dev:
                self.failed.emit("No matching cameras found.")
                return

            for s, d in ser2dev.items():
                self.status.emit(f"Configuring {s} as {self.mode} scan ...")

                ov = None
                if isinstance(self.overrides, dict):
                    ov = self.overrides.get(s)

                if self.mode == "area":
                    setup_area_camera(d, ov)
                else:
                    setup_line_camera(d, ov)

                nm, tl = d.nodemap, d.tl_stream_nodemap
                core = ["Width", "Height", "PixelFormat", "ExposureTime", "TriggerMode", "ExposureAuto",
                        "TriggerSelector", "TriggerSource", "TriggerActivation"]
                tlk = ["StreamAutoNegotiatePacketSize", "StreamPacketResendEnable"]
                nmv = _read_nodes_safe(nm, core)
                tlv = _read_tl_nodes_safe(tl, tlk)
                self.status.emit(f"[{s}] === Applied Camera Settings ===")
                for k in core: self.status.emit(f"[{s}] {k}: {nmv.get(k, '<N/A>')}")
                for k in tlk:  self.status.emit(f"[{s}] {k}: {tlv.get(k, '<N/A>')}")
                self.status.emit(f"[{s}] ===============================")

            total = self.n_images * len(ser2dev)
            saved, done = [], 0
            ts = time.strftime("%Y%m%d_%H%M%S")
            root_out = os.path.join(self.base_dir, f"camera_images_{ts}")
            os.makedirs(root_out, exist_ok=True)

            for serial, dev in ser2dev.items():
                cam_dir = os.path.join(root_out, serial)
                os.makedirs(cam_dir, exist_ok=True)

                for i in range(self.n_images):
                    if self._stop:
                        break

                    self.status.emit(f"[{serial}] Capturing {i+1}/{self.n_images}…")

                    # ----- LINE SCAN (Lucid) uses line_capture.py -----
                    if self.mode == "line" and LC_HAS_HELPERS:
                        try:
                            # One-shot grab, TriggerMode=Off, start/stop per frame
                            img = lc_snap_one(dev)  # timeout_ms default from line_capture.py
                        except Exception as e:
                            self.status.emit(f"[{serial}] Grab failed: {e}")
                            done += 1
                            self.progress.emit(done, total)
                            continue

                        if img is None:
                            self.status.emit(f"[{serial}] Skipped (no frame)")
                            done += 1
                            self.progress.emit(done, total)
                            continue

                        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                        filename = f"{i+1:04d}__{serial}__{ts}.png"
                        fp = os.path.join(cam_dir, filename)

                        # Use the robust writer from line_capture.py
                        saved_path = lc_save_image_robust(fp, img) or fp
                        saved.append(saved_path)

                    # ----- AREA SCAN (Lucid) keeps the old arena_grab_gray logic -----
                    else:
                        img = arena_grab_gray(dev) or arena_grab_gray(dev)
                        if img is None:
                            self.status.emit(f"[{serial}] Skipped (no frame)")
                            done += 1
                            self.progress.emit(done, total)
                            continue

                        fp = os.path.join(cam_dir, f"{serial}_{int(time.time()*1000)}_{i+1:03d}.jpg")
                        cv2.imwrite(fp, img)
                        saved.append(fp)

                    done += 1
                    self.progress.emit(done, total)

                # (Optional) If you want the same GAP_SECONDS behaviour between shots,
                # you can uncomment this block:
                #
                # if self.mode == "line" and LC_HAS_HELPERS and LC_GAP_SECONDS > 0 and not self._stop and self.n_images > 1:
                #     self.status.emit(f"[{serial}] Waiting {LC_GAP_SECONDS} seconds before next shot…")
                #     time.sleep(LC_GAP_SECONDS)


            for _, dev in ser2dev.items():
                _safe_stop(dev)
            self.finished_ok.emit(saved)
        except Exception:
            self.failed.emit(traceback.format_exc())

    def _run_simulation(self):
        try:
            total = self.n_images * max(1, len(self.serials)); done = 0; saved = []
            root = os.path.join(self.base_dir, "simulation", f"camera_images_{time.strftime('%Y%m%d_%H%M%S')}")
            os.makedirs(root, exist_ok=True)
            self.status.emit("SIMULATION MODE — no camera hardware is being accessed")
            self.status.emit(f"Output folder: {root}")
            for serial in self.serials:
                folder = os.path.join(root, serial); os.makedirs(folder, exist_ok=True)
                for index in range(self.n_images):
                    if self._stop: break
                    frame = simulation_frame(self.mode, index)
                    path = os.path.join(folder, f"{serial}_SIM_{index + 1:03d}.png")
                    if not cv2.imwrite(path, frame): raise RuntimeError(f"Could not write {path}")
                    saved.append(path); done += 1
                    self.status.emit(f"[{serial}] simulated frame {index + 1}/{self.n_images}")
                    self.progress.emit(done, total); self.msleep(90)
            self.finished_ok.emit(saved)
        except Exception:
            self.failed.emit(traceback.format_exc())
            
class HikCaptureWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(int, int)
    status = QtCore.pyqtSignal(str)
    finished_ok = QtCore.pyqtSignal(list)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, indices: List[int], n_images: int, base_dir: str,
                 exposure_us: Optional[float]=None, gain_db: Optional[float]=None, mirror: bool=False):
        super().__init__()
        self.indices = list(indices)
        self.n_images = max(1, int(n_images))
        self.base_dir = base_dir
        self.exposure_us = exposure_us
        self.gain_db = gain_db
        self.mirror = mirror
        self._stop = False

    def stop(self): self._stop = True

    def run(self):
        if CAMERA_SIMULATION:
            self._run_simulation()
            return
        try:
            import hik_capture as hkc
        except Exception as e:
            self.failed.emit(f"Failed to import hik_capture.py: {e}")
            return
        try:
            total = self.n_images * max(1, len(self.indices))
            done = 0
            saved_paths: List[str] = []

            ts = time.strftime("%Y%m%d_%H%M%S")
            root_out = os.path.join(self.base_dir, f"camera_images_{ts}")
            os.makedirs(root_out, exist_ok=True)
            self.status.emit(f"Output folder: {root_out}")

            def _cb(cam_idx:int, frame_i:int, path:str):
                nonlocal done, saved_paths
                saved_paths.append(path)
                done += 1
                self.progress.emit(done, total)
                # small log
                self.status.emit(f"[IDX {cam_idx}] saved {os.path.basename(path)} ({done}/{total})")

            # run the provided multi-capture
            # Assumes: hkc.capture_multi(indices, frames, base_out, mirror=False, exposure_us=None, gain_db=None, progress_cb=None)
            hkc.capture_multi(
                indices=self.indices,
                frames=self.n_images,
                base_out=root_out,
                mirror=self.mirror,
                exposure_us=self.exposure_us,
                gain_db=self.gain_db,
                progress_cb=_cb
            )

            self.finished_ok.emit(saved_paths)
        except Exception as e:
            self.failed.emit(traceback.format_exc())

    def _run_simulation(self):
        try:
            total = self.n_images * max(1, len(self.indices)); done = 0; saved = []
            root = os.path.join(self.base_dir, "simulation", f"camera_images_{time.strftime('%Y%m%d_%H%M%S')}")
            os.makedirs(root, exist_ok=True)
            self.status.emit("SIMULATION MODE — virtual Hikrobot acquisition")
            for camera_index in self.indices:
                folder = os.path.join(root, f"MVS_{camera_index}"); os.makedirs(folder, exist_ok=True)
                for index in range(self.n_images):
                    if self._stop: break
                    path = os.path.join(folder, f"MVS_{camera_index}_SIM_{index + 1:03d}.png")
                    if not cv2.imwrite(path, simulation_frame("mvs_area", index)):
                        raise RuntimeError(f"Could not write {path}")
                    saved.append(path); done += 1
                    self.status.emit(f"[MVS {camera_index}] simulated frame {index + 1}/{self.n_images}")
                    self.progress.emit(done, total); self.msleep(90)
            self.finished_ok.emit(saved)
        except Exception:
            self.failed.emit(traceback.format_exc())
