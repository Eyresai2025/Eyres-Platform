from __future__ import annotations
import os, sys, time, ctypes, traceback
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from toasts import ToastManager
import numpy as np
import cv2
from PyQt5 import QtCore, QtGui, QtWidgets
from pathlib import Path
from typing import Optional, Iterable
from datetime import datetime

from services.capture.backend import (
    AREA_ICON_PATH, LINE_ICON_PATH, ARENA_OK, CAMERA_SIMULATION, CamInfo,
    CaptureWorker, HikCaptureWorker, _safe_stop, _set_nm_value,
    arena_grab_gray, list_cameras, list_mvs_cameras,
    setup_area_camera, setup_line_preview_live, simulation_frame, system,
)
from ui.theme.capture import CAPTURE_STYLESHEET, apply_light_application_palette



# ---------- Help ----------
HELP_HTML = """
<div id="helpRoot">
  <div class="hero">
    <div>
      <h1>Camera Capture — Quick Help</h1>
      <p class="subtitle">A simple, one-page flow to grab images from your Lucid cameras.</p>
    </div>
  </div>

  <div class="card">
    <h2>What this app does</h2>
    <ul class="bullets">
      <li>🔍 <b>Finds your cameras</b> and lets you pick one or many.</li>
      <li>⚙️ Uses <b>safe defaults</b> so you don’t have to tune settings every time.</li>
      <li>🧮 Captures a <b>fixed number of images</b> from each selected camera.</li>
      <li>💾 Saves everything in a <b>date-stamped folder</b>, one folder per camera.</li>
      <li>📈 Shows a <b>progress bar</b> and a clear <b>status log</b>.</li>
      <li>🖼️ Gives a quick <b>preview grid</b> so you can check results fast.</li>
    </ul>
  </div>

  <div class="card">
    <h2>How to use (60-second guide)</h2>
    <ol class="steps">
      <li>🧭 <b>Choose Mode</b> — <i>Area Scan</i> (normal photos) or <i>Line Scan</i> (moving belt/roller).</li>
      <li>🎛️ <b>Select Cameras</b> — Press <b>Refresh</b>, tick the ones you need, or use <b>Select all cameras</b>.</li>
      <li>🔢 <b>Images per camera</b> — Pick how many pictures to take from each camera (e.g., 10).</li>
      <li>📂 <b>Save Location</b> — Choose where to store the session.</li>
      <li>▶️ <b>Capture</b> — Start; watch the progress and read the short log lines below.</li>
      <li>👀 <b>Preview</b> — Check sample images from every camera, then press <b>Finish</b> to start fresh.</li>
    </ol>
  </div>

  <div class="card">
    <h2>Where are my images?</h2>
    <pre class="folder">
{your_folder}/capture_{mode}_{YYYYMMDD_HHMMSS}/
  ├─ {SERIAL_1}/  image_001.jpg, image_002.jpg, ...
  └─ {SERIAL_2}/  image_001.jpg, image_002.jpg, ...
    </pre>
  </div>

  <div class="card tips">
    <h2>Quick tips</h2>
    <ul class="bullets">
      <li>🧪 <b>Line Scan</b> needs a working trigger from your machine (wired to <i>Line0</i>).</li>
      <li>🌗 Too dark or too bright? Reduce/increase exposure in code later — for now, just confirm wiring and lighting.</li>
      <li>🛠️ No cameras listed? Check power/network, then press <b>Refresh Devices</b>.</li>
    </ul>
    <div class="shortcuts">⌨️ <b>Shortcuts:</b> F1 = Help • Alt+→ = Next • Alt+← = Back</div>
  </div>
</div>
"""

class SimpleHelpDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Help")
        self.resize(780, 560)

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)

        card = QtWidgets.QFrame()
        card.setObjectName("helpCard")
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(18, 18, 18, 18)

        txt = QtWidgets.QTextBrowser()
        txt.setObjectName("helpText")
        txt.setOpenExternalLinks(True)
        txt.setHtml(HELP_HTML)

        lay.addWidget(txt)
        v.addWidget(card, 1)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        v.addWidget(btns, 0, QtCore.Qt.AlignRight)

class FullImageDialog(QtWidgets.QDialog):
    """Scrollable original-resolution viewer for a captured image."""
    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Captured Image — {os.path.basename(image_path)}")
        self.setModal(True)
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        self.resize(min(1200, int(screen.width()*0.82)), min(850, int(screen.height()*0.82)))
        layout = QtWidgets.QVBoxLayout(self); layout.setContentsMargins(12,12,12,12)
        header = QtWidgets.QLabel(os.path.basename(image_path)); header.setObjectName("fullImageTitle")
        scroll = QtWidgets.QScrollArea(); scroll.setObjectName("fullImageScroll"); scroll.setWidgetResizable(False)
        image = QtWidgets.QLabel(); image.setAlignment(QtCore.Qt.AlignCenter)
        pixmap = QtGui.QPixmap(image_path)
        image.setPixmap(pixmap); image.resize(pixmap.size())
        scroll.setWidget(image)
        close = QtWidgets.QPushButton("Close"); close.setObjectName("primaryButton"); close.clicked.connect(self.accept)
        layout.addWidget(header); layout.addWidget(scroll,1); layout.addWidget(close,0,QtCore.Qt.AlignRight)

# ---------- Preview helpers ----------
def _group_by_camdir(paths: List[str]) -> Dict[str, List[str]]:
    g = defaultdict(list)
    for p in paths:
        g[os.path.dirname(p)].append(p)
    for k in g:
        g[k].sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return g

def _pick_previews_by_rule(paths: List[str]) -> List[Tuple[str, str]]:
    groups = _group_by_camdir(paths)
    cams = sorted(groups.keys())
    out: List[Tuple[str, str]] = []
    if not cams: return out
    if len(cams) == 1:
        out += [(p, os.path.basename(cams[0])) for p in groups[cams[0]][:4]]
    elif len(cams) == 2:
        for c in cams: out += [(p, os.path.basename(c)) for p in groups[c][:2]]
    else:
        for c in cams: out.append((groups[c][0], os.path.basename(c)))
    return out

# ---------- Small utilities for labels (prevents strips) ----------
def _make_title(text: str) -> QtWidgets.QLabel:
    lbl = QtWidgets.QLabel(text)
    lbl.setObjectName("pageTitle")
    lbl.setFrameShape(QtWidgets.QFrame.NoFrame)
    lbl.setAutoFillBackground(False)
    lbl.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
    return lbl

def _make_subtitle(text: str) -> QtWidgets.QLabel:
    lbl = QtWidgets.QLabel(text)
    lbl.setObjectName("pageSubtitle")
    lbl.setFrameShape(QtWidgets.QFrame.NoFrame)
    lbl.setAutoFillBackground(False)
    lbl.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
    return lbl

# ---------- Widgets ----------
class StepIndicator(QtWidgets.QWidget):
    def __init__(self, number:int, title:str, parent=None):
        super().__init__(parent)
        self.number=number; self.is_active=False; self.is_complete=False
        self.setFixedHeight(52)
        h=QtWidgets.QHBoxLayout(self); h.setContentsMargins(16,10,16,10)
        self.circle=QtWidgets.QLabel(str(number)); self.circle.setObjectName("stepCircle")
        self.circle.setFixedSize(30,30); self.circle.setAlignment(QtCore.Qt.AlignCenter)
        self.title_label=QtWidgets.QLabel(title); self.title_label.setObjectName("stepTitle")
        h.addWidget(self.circle); h.addWidget(self.title_label); h.addStretch()
        self._update()
    def set_active(self,a): self.is_active=a; self._update()
    def set_complete(self,c): self.is_complete=c; self._update()
    def _update(self):
        if self.is_active:
            self.circle.setStyleSheet("QLabel#stepCircle{background:#2868e8;color:#fff;border-radius:15px;font-weight:700;}")
            self.title_label.setStyleSheet("color:#1d4ed8;background:transparent;font-weight:700;")
        elif self.is_complete:
            self.circle.setStyleSheet("QLabel#stepCircle{background:#dcfce7;color:#087f5b;border-radius:15px;font-weight:700;}")
            self.title_label.setStyleSheet("color:#475569;background:transparent;")
        else:
            self.circle.setStyleSheet("QLabel#stepCircle{background:#f1f5f9;color:#64748b;border:1px solid #cbd5e1;border-radius:15px;}")
            self.title_label.setStyleSheet("color:#64748b;background:transparent;")
    def mousePressEvent(self, e): self.parent().parent().parent()._on_step_clicked(self.number-1)

class StepMode(QtWidgets.QWidget):
    changed = QtCore.pyqtSignal()
    def __init__(self, area_icon_path=None, line_icon_path=None, icon_size=64):
        super().__init__()
        self.area_icon_path=area_icon_path; self.line_icon_path=line_icon_path; self.icon_size=icon_size
        v=QtWidgets.QVBoxLayout(self); v.setContentsMargins(32,24,32,24); v.setSpacing(16)

        title=_make_title("Select Capture Mode")
        title.setObjectName("modeTitle")              
        title.setStyleSheet("font-size:22px;font-weight:800;color:#0f172a;background:transparent;")
        subtitle=_make_subtitle("Choose between area scan, line scan, or MVS area scan (Hikrobot)")

        row=QtWidgets.QWidget(); row.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        hl=QtWidgets.QHBoxLayout(row); hl.setContentsMargins(0,12,0,0); hl.setSpacing(24)

        # Hidden radio buttons still need one explicit exclusive group. Without
        # this, moving them out of the card layouts allows every mode to remain
        # checked at the same time.
        self.mode_group=QtWidgets.QButtonGroup(self)
        self.mode_group.setExclusive(True)

        # Arena Area
        self.area_card=self._card("Area Scan","Standard 2D imaging\nIdeal for static objects", self.area_icon_path)
        self.area=QtWidgets.QRadioButton(); self.area.setChecked(True)
        self.mode_group.addButton(self.area, 0)
        self.area.toggled.connect(self.changed.emit); self.area.toggled.connect(self._refresh_cards)
        self.area.hide(); self._make_card_clickable(self.area_card, self.area)

        # Arena Line
        self.line_card=self._card("Line Scan","Continuous scanning\nFor moving objects", self.line_icon_path)
        self.line=QtWidgets.QRadioButton(); self.line.toggled.connect(self.changed.emit); self.line.toggled.connect(self._refresh_cards)
        self.mode_group.addButton(self.line, 1)
        self.line.hide(); self._make_card_clickable(self.line_card, self.line)

        # MVS Area (Hikrobot)
        self.mvs_card=self._card("MVS Area Scan","Hikrobot MVS Mono8 capture\nUses hik_capture.py", self.line_icon_path)
        self.mvs=QtWidgets.QRadioButton(); self.mvs.toggled.connect(self.changed.emit); self.mvs.toggled.connect(self._refresh_cards)
        self.mode_group.addButton(self.mvs, 2)
        self.mvs.hide(); self._make_card_clickable(self.mvs_card, self.mvs)

        hl.addStretch(); hl.addWidget(self.area_card); hl.addWidget(self.line_card); hl.addWidget(self.mvs_card); hl.addStretch()
        v.addWidget(title); v.addWidget(subtitle); v.addWidget(row); v.addStretch(1)
        self._refresh_cards()

    def _icon(self, path):
        lbl=QtWidgets.QLabel(); lbl.setAlignment(QtCore.Qt.AlignCenter)
        if path and os.path.exists(path):
            pm=QtGui.QPixmap(path)
            if not pm.isNull():
                pm=pm.scaled(self.icon_size,self.icon_size,QtCore.Qt.KeepAspectRatio,QtCore.Qt.SmoothTransformation)
                lbl.setPixmap(pm); return lbl
        lbl.setFixedHeight(self.icon_size); return lbl

    def _card(self, title, desc, icon_path):
        w=QtWidgets.QWidget(); w.setObjectName("modeCard"); w.setFixedSize(260,200)
        w.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        l=QtWidgets.QVBoxLayout(w); l.setContentsMargins(18,18,18,18); l.setSpacing(10)
        t=QtWidgets.QLabel(title); t.setObjectName("cardTitle"); t.setAlignment(QtCore.Qt.AlignCenter)
        d=QtWidgets.QLabel(desc);  d.setObjectName("cardDesc");  d.setAlignment(QtCore.Qt.AlignCenter); d.setWordWrap(True)
        check=QtWidgets.QLabel("✓"); check.setObjectName("modeCheck"); check.setFixedSize(24,24); check.setAlignment(QtCore.Qt.AlignCenter)
        l.addWidget(check,0,QtCore.Qt.AlignRight); l.addWidget(self._icon(icon_path)); l.addWidget(t); l.addWidget(d); l.addStretch()
        return w

    def _make_card_clickable(self, card, radio):
        card.setCursor(QtCore.Qt.PointingHandCursor)
        card.mousePressEvent = lambda event, r=radio: r.setChecked(True)

    def _refresh_cards(self):
        sel = "QWidget#modeCard{background:#eef4ff;border:2px solid #2868e8;border-radius:12px;}"
        norm= "QWidget#modeCard{background:#ffffff;border:1px solid #d8e2f0;border-radius:12px;}"
        self.area_card.setStyleSheet(sel if self.area.isChecked() else norm)
        self.line_card.setStyleSheet(sel if self.line.isChecked() else norm)
        self.mvs_card.setStyleSheet(sel if self.mvs.isChecked() else norm)
        for card, checked in ((self.area_card,self.area.isChecked()),(self.line_card,self.line.isChecked()),(self.mvs_card,self.mvs.isChecked())):
            badge=card.findChild(QtWidgets.QLabel,"modeCheck")
            if badge: badge.setVisible(checked)

    def value(self)->str:
        if self.mvs.isChecked(): return "mvs_area"
        return "area" if self.area.isChecked() else "line"


class StepDevices(QtWidgets.QWidget):
    changed = QtCore.pyqtSignal()
    def __init__(self):
        super().__init__()
        self._mode = "area"  # or "line" or "mvs_area"
        v=QtWidgets.QVBoxLayout(self); v.setContentsMargins(32,24,32,24); v.setSpacing(14)
        title=_make_title("Select Cameras")
        subtitle=_make_subtitle("Choose one or more cameras")
        top=QtWidgets.QWidget(); ht=QtWidgets.QHBoxLayout(top); ht.setContentsMargins(0,0,0,0)
        self.count_lbl=QtWidgets.QLabel("0 devices found"); self.count_lbl.setObjectName("deviceCount")
        self.refresh=QtWidgets.QPushButton("Refresh Devices"); self.refresh.setObjectName("primaryButton"); self.refresh.clicked.connect(self.refresh_devices)
        ht.addWidget(self.count_lbl); ht.addStretch(); ht.addWidget(self.refresh)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("deviceList")
        # MultiSelection provides the expected industrial touch/click behavior:
        # one click selects a camera and a second click deselects it. Ctrl is
        # not required.
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.list.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.list.setUniformItemSizes(True)
        self.list.setMaximumHeight(260)
        self.list.itemSelectionChanged.connect(self._on_sel)
        self.list.itemSelectionChanged.connect(self.changed.emit)
        self.list.itemClicked.connect(lambda _: self.changed.emit())
        bottom=QtWidgets.QWidget(); hb=QtWidgets.QHBoxLayout(bottom); hb.setContentsMargins(0,0,0,0)
        self.select_all=QtWidgets.QCheckBox("Select all cameras"); self.select_all.setTristate(True)
        self.select_all.setObjectName("selectAll"); self.select_all.stateChanged.connect(self._toggle_all)
        hb.addWidget(self.select_all); hb.addStretch()
        v.addWidget(title); v.addWidget(subtitle); v.addSpacing(6); v.addWidget(top); v.addWidget(self.list); v.addWidget(bottom); v.addStretch(1)



        self.refresh_devices()

    def set_mode(self, mode:str):
        """Call when StepMode changes: 'area'|'line'|'mvs_area'"""
        if mode not in ("area","line","mvs_area"): return
        if self._mode != mode:
            self._mode = mode
            self.refresh_devices()

    def _counts(self):
        t=self.list.count(); s=len(self.list.selectedItems())
        self.count_lbl.setText(f"{t} device{'s' if t!=1 else ''} found • {s} selected")

    def _sync_all(self):
        t=self.list.count(); s=len(self.list.selectedItems())
        if t==0 or s==0: self.select_all.setCheckState(QtCore.Qt.Unchecked)
        elif s==t: self.select_all.setCheckState(QtCore.Qt.Checked)
        else: self.select_all.setCheckState(QtCore.Qt.PartiallyChecked)

    def _on_sel(self): self._counts(); self._sync_all()

    def _toggle_all(self, state:int):
        if state==QtCore.Qt.PartiallyChecked: return
        block=self.list.blockSignals(True)
        try:
            self.list.selectAll() if state==QtCore.Qt.Checked else self.list.clearSelection()
        finally:
            self.list.blockSignals(block)
        self.changed.emit(); self._counts(); self._sync_all()

    def refresh_devices(self):
        self.list.clear()
        try:
            if self._mode == "mvs_area":
                cams = list_mvs_cameras()  # CamInfo(index, model, serial) but we’ll use index for MVS
            else:
                cams = list_cameras()      # Arena
        except Exception as e:
            cams = []
            QtWidgets.QMessageBox.critical(self, "Device Error", str(e))

        for c in cams:
            if self._mode == "mvs_area":
                # Show model + (IDX), payload marks it as MVS with device index
                text = f"📹  {c.model}  •  IDX: {c.index}"
                payload = ("mvs", int(c.index))
            else:
                # Arena: model + serial, payload marks it as ARENA with serial
                text = f"📹  {c.model}  •  S/N: {c.serial}"
                payload = ("arena", str(c.serial))

            it = QtWidgets.QListWidgetItem(text)
            it.setData(QtCore.Qt.UserRole, payload)
            it.setIcon(QtGui.QIcon.fromTheme("camera"))
            it.setFlags(it.flags() | QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
            self.list.addItem(it)

        if self.select_all.checkState() == QtCore.Qt.Checked and self.list.count() > 0:
            self.list.selectAll()

        if self.list.count() == 1 and not self.list.selectedItems():
            self.list.setCurrentRow(0)
            self.list.item(0).setSelected(True)

        self._counts()
        self._sync_all()


    def selected_serials(self) -> List[str]:
        out = []
        for it in self.list.selectedItems():
            payload = it.data(QtCore.Qt.UserRole)
            if isinstance(payload, tuple) and payload and payload[0] == "arena":
                out.append(str(payload[1]))
            elif isinstance(payload, str) and self._mode != "mvs_area":
                # fallback if older items only stored serial string
                out.append(payload)
        return out

    def selected_mvs_indices(self) -> List[int]:
        out = []
        for it in self.list.selectedItems():
            payload = it.data(QtCore.Qt.UserRole)
            if isinstance(payload, tuple) and payload and payload[0] == "mvs":
                out.append(int(payload[1]))
            elif isinstance(payload, int) and self._mode == "mvs_area":
                # fallback if older items only stored index int
                out.append(int(payload))
        return out

    def has_selection(self) -> bool:
        if self._mode == "mvs_area":
            return len(self.selected_mvs_indices()) > 0
        return len(self.selected_serials()) > 0

class StepCamSettings(QtWidgets.QWidget):
    """
    Step 3: Camera Settings

    - Shows live preview from selected Arena camera(s) (area/line).
    - Lets user tweak ExposureTime and Gain.
    - Stores overrides in CameraWidget._arena_overrides per serial.
    """
    changed = QtCore.pyqtSignal()

    def __init__(self, owner: "CameraWidget"):
        super().__init__()
        self._owner = owner
        self._mode: str = "area"      # "area" | "line" | "mvs_area"
        self._serials: List[str] = [] # arena serials
        self._idx: int = 0            # current index into _serials
        self._dev = None              # current arena device
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._grab_and_show)
        self._is_mvs: bool = False
        self._mvs_indices: List[int] = []
        self._preview_started_at = 0.0
        self._preview_frame_count = 0
        self._settings_dirty = False


        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(32, 24, 32, 24)
        v.setSpacing(10)

        title = _make_title("Camera Settings")
        subtitle = _make_subtitle("Preview each camera and adjust exposure / gain before capture")

        # Top row: current camera + prev/next
        hdr = QtWidgets.QWidget()
        hl = QtWidgets.QHBoxLayout(hdr)
        hl.setContentsMargins(0, 0, 0, 0)

        self.lbl_cam = QtWidgets.QLabel("No camera selected")
        self.lbl_cam.setObjectName("pageSubtitle")

        self.btn_prev = QtWidgets.QPushButton("◀ Prev")
        self.btn_next = QtWidgets.QPushButton("Next ▶")
        for b in (self.btn_prev, self.btn_next):
            b.setObjectName("secondaryButton")
            b.setFixedHeight(32)

        self.btn_prev.clicked.connect(self._prev_camera)
        self.btn_next.clicked.connect(self._next_camera)

        hl.addWidget(self.lbl_cam)
        hl.addStretch()
        hl.addWidget(self.btn_prev)
        hl.addWidget(self.btn_next)

        # Middle row: preview + settings
        mid = QtWidgets.QWidget()
        mh = QtWidgets.QHBoxLayout(mid)
        mh.setContentsMargins(0, 0, 0, 0)
        mh.setSpacing(18)

        # Preview
        self.lbl_preview = QtWidgets.QLabel()
        self.lbl_preview.setMinimumSize(480, 320)
        self.lbl_preview.setAlignment(QtCore.Qt.AlignCenter)
        self.lbl_preview.setStyleSheet("background:#050505; border:1px solid #202020; border-radius:8px;")
        self.lbl_preview.setText("Preview\n(no camera)")
        self.preview_info = QtWidgets.QLabel("OFFLINE  •  — FPS  •  — × —  •  —")
        self.preview_info.setObjectName("previewInfo")

        # Settings card
        panel = QtWidgets.QWidget()
        panel.setObjectName("formContainer")
        panel.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        form = QtWidgets.QFormLayout(panel)
        form.setContentsMargins(18, 18, 18, 18)

        # --- Exposure spin + slider ---
        self.spin_exp = QtWidgets.QDoubleSpinBox()
        self.spin_exp.setObjectName("imageCountSpin")
        self.spin_exp.setDecimals(1)
        self.spin_exp.setRange(10.0, 1_000_000.0)
        self.spin_exp.setSingleStep(100.0)
        self.spin_exp.setValue(1700.0)
        self.spin_exp.setSuffix(" µs")

        self.slider_exp = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_exp.setMinimum(10)
        self.slider_exp.setMaximum(100000)   # practical UI range
        self.slider_exp.setSingleStep(100)
        self.slider_exp.setValue(int(self.spin_exp.value()))

        # keep spin <-> slider in sync
        self.spin_exp.valueChanged.connect(
            lambda v: self.slider_exp.setValue(int(v))
        )
        self.slider_exp.valueChanged.connect(
            lambda v: self.spin_exp.setValue(float(v))
        )

        # --- Gain spin + slider ---
        self.spin_gain = QtWidgets.QDoubleSpinBox()
        self.spin_gain.setObjectName("imageCountSpin")
        self.spin_gain.setDecimals(1)
        self.spin_gain.setRange(0.0, 36.0)
        self.spin_gain.setSingleStep(0.5)
        self.spin_gain.setValue(24.0)
        self.spin_gain.setSuffix(" dB")

        self.slider_gain = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_gain.setMinimum(0)
        self.slider_gain.setMaximum(36)
        self.slider_gain.setSingleStep(1)
        self.slider_gain.setValue(int(self.spin_gain.value()))

        self.spin_gain.valueChanged.connect(
            lambda v: self.slider_gain.setValue(int(v))
        )
        self.slider_gain.valueChanged.connect(
            lambda v: self.spin_gain.setValue(float(v))
        )

        # --- Resolution + editable ROI + PixelFormat ---
        self.lbl_wh = QtWidgets.QLabel("— x —")

        self.spin_width = QtWidgets.QSpinBox()
        self.spin_width.setRange(16, 65536)   # will be tightened after camera open
        self.spin_width.setEnabled(False)

        self.spin_height = QtWidgets.QSpinBox()
        self.spin_height.setRange(16, 65536)
        self.spin_height.setEnabled(False)

        self.edit_pixfmt = QtWidgets.QLineEdit()
        self.edit_pixfmt.setPlaceholderText("Mono8 / BayerRG8 / ...")
        self.edit_pixfmt.setEnabled(False)

        self.btn_preview_toggle = QtWidgets.QPushButton("Start Preview")
        self.btn_preview_toggle.setObjectName("primaryButton")
        self.btn_preview_toggle.setFixedHeight(32)
        self.btn_preview_toggle.clicked.connect(self._toggle_preview)

        self.btn_reset_settings = QtWidgets.QPushButton("Reset to Defaults")
        self.btn_reset_settings.setObjectName("secondaryButton")
        self.btn_reset_settings.clicked.connect(self._reset_defaults)
        self.btn_apply_settings = QtWidgets.QPushButton("Apply Settings")
        self.btn_apply_settings.setObjectName("primaryButton")
        self.btn_apply_settings.clicked.connect(self._apply_settings)
        self.btn_apply_settings.setEnabled(False)
        action_row = QtWidgets.QWidget(); actions = QtWidgets.QHBoxLayout(action_row); actions.setContentsMargins(0,6,0,0)
        actions.addWidget(self.btn_reset_settings); actions.addWidget(self.btn_apply_settings)

        # layout: sliders under spins, then H/W/PixelFormat
        form.addRow("Exposure Time:", self.spin_exp)
        form.addRow("",               self.slider_exp)
        form.addRow("Gain:",          self.spin_gain)
        form.addRow("",               self.slider_gain)
        form.addRow("Resolution:",    self.lbl_wh)
        form.addRow("Width:",         self.spin_width)
        form.addRow("Height:",        self.spin_height)
        form.addRow("Pixel Format:",  self.edit_pixfmt)
        form.addRow("",               self.btn_preview_toggle)
        form.addRow("",               action_row)

        # connect changes
        self.spin_exp.valueChanged.connect(self._mark_settings_dirty)
        self.spin_gain.valueChanged.connect(self._mark_settings_dirty)
        self.spin_width.valueChanged.connect(self._mark_settings_dirty)
        self.spin_height.valueChanged.connect(self._mark_settings_dirty)
        self.edit_pixfmt.textChanged.connect(self._mark_settings_dirty)




        preview_box=QtWidgets.QWidget(); preview_layout=QtWidgets.QVBoxLayout(preview_box); preview_layout.setContentsMargins(0,0,0,0); preview_layout.setSpacing(6)
        preview_layout.addWidget(self.lbl_preview,1); preview_layout.addWidget(self.preview_info)
        mh.addWidget(preview_box, 2)
        mh.addWidget(panel, 1)

        v.addWidget(title)
        v.addWidget(subtitle)
        v.addWidget(hdr)
        v.addWidget(mid, 1)

    # --------- public API used by CameraWidget ---------
    def refresh_from_selection(self):
        """
        Called whenever mode/camera selection changes or when
        we enter this step.

        IMPORTANT: just update UI & list, do NOT open camera
        or start preview until user presses Start Preview.
        """
        self._mode = self._owner.step_mode.value()
        self._stop_preview_internal()  # stop anything running
        self._set_clean()

        if self._mode == "mvs_area":
            # MVS mode: use indices instead of serials
            self._is_mvs = True
            self._mvs_indices = self._owner.step_devs.selected_mvs_indices()
            self._serials = []  # not used in this mode
            self._idx = 0

            has = bool(self._mvs_indices)
            self.btn_prev.setEnabled(len(self._mvs_indices) > 1)
            self.btn_next.setEnabled(len(self._mvs_indices) > 1)
            self.btn_preview_toggle.setEnabled(has)
            self.btn_reset_settings.setEnabled(has)

            if not has:
                self.lbl_cam.setText("No MVS camera selected")
                self.lbl_preview.setText("Preview\n(select MVS camera first)")
                self.lbl_wh.setText("— x —")
                return

            cam_idx = self._mvs_indices[self._idx]
            self.lbl_cam.setText(f"MVS IDX {cam_idx} — press Start Preview")
            self.lbl_preview.setText("Preview\n(press Start Preview)")
            self.lbl_wh.setText("— x —")
            return

        # Arena (area / line)
        self._is_mvs = False
        self._mvs_indices = []
        self._serials = self._owner.step_devs.selected_serials()
        self._idx = 0
        has = bool(self._serials)

        self.btn_prev.setEnabled(len(self._serials) > 1)
        self.btn_next.setEnabled(len(self._serials) > 1)
        self.btn_preview_toggle.setEnabled(has)
        self.btn_reset_settings.setEnabled(has)

        if not has:
            self.lbl_cam.setText("No Arena camera selected")
            self.lbl_preview.setText("Preview\n(select camera first)")
            self.lbl_wh.setText("— x —")
            self.spin_width.setValue(0)
            self.spin_height.setValue(0)
            self.spin_width.setEnabled(False)
            self.spin_height.setEnabled(False)
            self.edit_pixfmt.setText("")
            self.edit_pixfmt.setEnabled(False)
            return



        self._load_current_overrides()
        serial = self._current_serial()
        self.lbl_cam.setText(
            f"{self._mode.upper()} • S/N: {serial} — press Start Preview"
        )
        self.lbl_preview.setText("Preview\n(press Start Preview)")
        self.lbl_wh.setText("— x —")

    def _current_serial(self) -> Optional[str]:
        if self._is_mvs or not self._serials:
            return None
        return self._serials[self._idx]

    def _current_mvs_index(self) -> Optional[int]:
        if not self._is_mvs or not self._mvs_indices:
            return None
        return self._mvs_indices[self._idx]

    def _current_label(self) -> str:
        if self._is_mvs:
            idx = self._current_mvs_index()
            return f"MVS IDX {idx}" if idx is not None else "MVS"
        else:
            s = self._current_serial()
            return f"{self._mode.upper()} • S/N: {s}" if s else "ARENA"

    def _open_current_mvs_camera(self, start_preview: bool):
        """
        Prepare live preview for current MVS (Hikrobot) camera.

        - Uses MVS index (from StepDevices)
        - Stores exposure/gain overrides in self._owner._mvs_overrides[idx]
        - Reads camera limits for Exposure/Gain and clamps values
        - Grabs one test frame (to get resolution & show first preview)
        - Starts QTimer if start_preview=True
        """
        # Stop any Arena preview that might be running
        self._timer.stop()
        try:
            if self._dev is not None:
                _safe_stop(self._dev)
        except Exception:
            pass
        self._dev = None  # MVS path does not use self._dev

        # Get currently selected MVS indices
        try:
            self._mvs_indices = self._owner.step_devs.selected_mvs_indices()
        except Exception:
            self._mvs_indices = []

        if not self._mvs_indices:
            self.lbl_cam.setText("No MVS camera selected")
            self.lbl_preview.setText("Preview\n(select MVS camera first)")
            self.lbl_wh.setText("— x —")

            # reset / disable ROI & pixfmt for MVS when nothing selected
            self.spin_width.setValue(0)
            self.spin_height.setValue(0)
            self.spin_width.setEnabled(False)
            self.spin_height.setEnabled(False)
            self.edit_pixfmt.setText("")
            self.edit_pixfmt.setEnabled(False)

            self.btn_preview_toggle.setText("Start Preview")
            return

        # Use current index into list
        if not hasattr(self, "_idx"):
            self._idx = 0
        self._idx = max(0, min(self._idx, len(self._mvs_indices) - 1))
        idx = self._mvs_indices[self._idx]

        self.lbl_cam.setText(f"MVS IDX {idx}")

        if CAMERA_SIMULATION:
            self._show_simulation_settings("MVS AREA • SIM-MVS-001", "mvs_area", start_preview)
            return

        # -------------------------------
        # ✅ Read Exposure/Gain limits
        # -------------------------------
        exp_lo, exp_hi = 10.0, 1_000_000.0   # fallback UI range (µs)
        gain_lo, gain_hi = 0.0, 36.0         # fallback UI range (dB)

        try:
            import hik_capture as hkc
            lims = hkc.read_gain_exposure_limits(idx) or {}
            if "ExposureTime" in lims:
                exp_lo, exp_hi, _cur = lims["ExposureTime"]
                self.spin_exp.setRange(float(exp_lo), float(exp_hi))
            else:
                self.spin_exp.setRange(float(exp_lo), float(exp_hi))

            if "Gain" in lims:
                gain_lo, gain_hi, _cur = lims["Gain"]
                self.spin_gain.setRange(float(gain_lo), float(gain_hi))
            else:
                self.spin_gain.setRange(float(gain_lo), float(gain_hi))
        except Exception as e:
            print(f"[cam_settings] read limits failed IDX {idx}: {e}")
            self.spin_exp.setRange(float(exp_lo), float(exp_hi))
            self.spin_gain.setRange(float(gain_lo), float(gain_hi))

        # Load / init overrides for this MVS index (only Exp/Gain)
        if not hasattr(self._owner, "_mvs_overrides"):
            self._owner._mvs_overrides = {}
        ov = self._owner._mvs_overrides.setdefault(idx, {})

        # Read saved values (Mongo), then clamp to camera limits
        cur_exp = float(ov.get("ExposureTime", 20000.0))  # 20 ms default
        cur_gain = float(ov.get("Gain", 0.0))

        # ✅ clamp
        cur_exp = max(float(exp_lo), min(float(exp_hi), cur_exp))
        cur_gain = max(float(gain_lo), min(float(gain_hi), cur_gain))

        ov["ExposureTime"] = cur_exp
        ov["Gain"] = cur_gain

        # Reflect in spin boxes
        try:
            self.spin_exp.blockSignals(True)
            self.spin_gain.blockSignals(True)
            self.spin_exp.setValue(cur_exp)
            self.spin_gain.setValue(cur_gain)
        finally:
            self.spin_exp.blockSignals(False)
            self.spin_gain.blockSignals(False)

        # Try one test grab to find resolution and show a first preview frame
        test_img = None
        try:
            import hik_capture as hkc
            test_img = hkc.grab_live_frame(
                index=idx,
                exposure_us=cur_exp,
                gain_db=cur_gain,
                mirror=False,
            )
        except Exception as e:
            print(f"[cam_settings] MVS test grab error IDX {idx}:", e)

        if test_img is not None:
            h, w = test_img.shape
            self.lbl_wh.setText(f"{w} x {h}")

            # For now: show W/H as read-only (MVS ROI not controlled here)
            self.spin_width.blockSignals(True)
            self.spin_height.blockSignals(True)
            self.spin_width.setRange(1, 1000000)
            self.spin_height.setRange(1, 1000000)
            self.spin_width.setValue(w)
            self.spin_height.setValue(h)
            self.spin_width.blockSignals(False)
            self.spin_height.blockSignals(False)

            self.spin_width.setEnabled(False)
            self.spin_height.setEnabled(False)
            self.edit_pixfmt.setText("Mono8")
            self.edit_pixfmt.setEnabled(False)

            qimg = QtGui.QImage(test_img.data, w, h, w, QtGui.QImage.Format_Grayscale8)
            pix = QtGui.QPixmap.fromImage(qimg).scaled(
                self.lbl_preview.width(),
                self.lbl_preview.height(),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
            self.lbl_preview.setPixmap(pix)
        else:
            self.lbl_wh.setText("— x —")
            self.spin_width.setValue(0)
            self.spin_height.setValue(0)
            self.spin_width.setEnabled(False)
            self.spin_height.setEnabled(False)
            self.edit_pixfmt.setText("")
            self.edit_pixfmt.setEnabled(False)
            self.lbl_preview.setText("Preview\n(press Start Preview)")

        # Start periodic grabbing if requested
        if start_preview:
            self._timer.start(200)  # ~5 FPS
            self.btn_preview_toggle.setText("Stop Preview")
        else:
            self.btn_preview_toggle.setText("Start Preview")





    # --------- internals ---------
    def _current_serial(self) -> Optional[str]:
        if not self._serials:
            return None
        return self._serials[self._idx]

    def _prev_camera(self):
        if self._is_mvs:
            if not self._mvs_indices:
                return
            self._idx = (self._idx - 1) % len(self._mvs_indices)
        else:
            if not self._serials:
                return
            self._idx = (self._idx - 1) % len(self._serials)

        self._load_current_overrides()
        if self._is_mvs:
            self._open_current_mvs_camera(start_preview=self._timer.isActive())
        else:
            self._open_current_camera(start_preview=self._timer.isActive())

    def _next_camera(self):
        if self._is_mvs:
            if not self._mvs_indices:
                return
            self._idx = (self._idx + 1) % len(self._mvs_indices)
        else:
            if not self._serials:
                return
            self._idx = (self._idx + 1) % len(self._serials)

        self._load_current_overrides()
        if self._is_mvs:
            self._open_current_mvs_camera(start_preview=self._timer.isActive())
        else:
            self._open_current_camera(start_preview=self._timer.isActive())


    def _load_current_overrides(self):
        serial = self._current_serial()
        if not serial:
            return
        ov = self._owner._arena_overrides.get(serial, {})

        if "ExposureTime" in ov:
            self.spin_exp.blockSignals(True)
            self.spin_exp.setValue(float(ov["ExposureTime"]))
            self.spin_exp.blockSignals(False)

        if "Gain" in ov:
            self.spin_gain.blockSignals(True)
            self.spin_gain.setValue(float(ov["Gain"]))
            self.spin_gain.blockSignals(False)

        if "Width" in ov:
            self.spin_width.blockSignals(True)
            self.spin_width.setValue(int(ov["Width"]))
            self.spin_width.blockSignals(False)

        if "Height" in ov:
            self.spin_height.blockSignals(True)
            self.spin_height.setValue(int(ov["Height"]))
            self.spin_height.blockSignals(False)

        if "PixelFormat" in ov and ov["PixelFormat"]:
            self.edit_pixfmt.blockSignals(True)
            self.edit_pixfmt.setText(str(ov["PixelFormat"]))
            self.edit_pixfmt.blockSignals(False)


    def _mark_settings_dirty(self, *args):
        self._settings_dirty = True
        self.btn_apply_settings.setEnabled(True)
        self.btn_apply_settings.setText("Apply Settings •")

    def _set_clean(self):
        self._settings_dirty = False
        self.btn_apply_settings.setEnabled(False)
        self.btn_apply_settings.setText("Apply Settings")

    def _reset_defaults(self):
        is_mvs = self._is_mvs and not CAMERA_SIMULATION
        defaults = (20000.0, 0.0) if is_mvs else (1700.0, 0.0)
        self.spin_exp.setValue(defaults[0]); self.spin_gain.setValue(defaults[1])
        self._mark_settings_dirty()
        self._owner._toast("Default exposure and gain restored. Press Apply Settings to save.", "info", 3000)

    def _apply_settings(self):
        if self._is_mvs:
            # ---- MVS branch: only Exposure/Gain used for Hikrobot ----
            idx = self._current_mvs_index()
            if idx is None:
                return
            ov = self._owner._mvs_overrides.setdefault(idx, {})
            ov["ExposureTime"] = float(self.spin_exp.value())   # microseconds
            ov["Gain"] = float(self.spin_gain.value())          # dB

            # 🔹 Save to MongoDB
            self._owner._persist_overrides()
            self.changed.emit()
            self._set_clean()
            self._owner._toast("Camera settings applied.", "success", 2200)
            return

        # ---- Arena (Lucid) branch: full control ----
        serial = self._current_serial()
        if not serial:
            return

        ov = self._owner._arena_overrides.setdefault(serial, {})
        ov["ExposureTime"] = float(self.spin_exp.value())
        ov["Gain"]        = float(self.spin_gain.value())
        ov["Width"]       = int(self.spin_width.value())
        ov["Height"]      = int(self.spin_height.value())
        ov["PixelFormat"] = self.edit_pixfmt.text().strip() or None

        # 🔹 Save to MongoDB
        self._owner._persist_overrides()

        self.changed.emit()

        if self._dev is not None:
            nm = self._dev.nodemap
            for node_name, value in (
                ("ExposureTime", ov["ExposureTime"]),
                ("Gain", ov["Gain"]),
                ("Width", ov.get("Width")),
                ("Height", ov.get("Height")),
                ("PixelFormat", ov.get("PixelFormat")),
            ):
                if value in (None, ""):
                    continue
                try:
                    _set_nm_value(nm, node_name, value)
                except Exception:
                    pass

        self._set_clean()
        self._owner._toast("Camera settings applied.", "success", 2200)



    def _toggle_preview(self):
        if self._timer.isActive():
            self._stop_preview_internal()
        else:
            if self._is_mvs:
                self._open_current_mvs_camera(start_preview=True)
            else:
                self._open_current_camera(start_preview=True)



    def _open_current_camera(self, start_preview: bool):
        self._stop_preview_internal()

        serial = self._current_serial()
        if CAMERA_SIMULATION and serial:
            self._show_simulation_settings(f"{self._mode.upper()} • S/N: {serial}", self._mode, start_preview)
            return
        if not serial or not ARENA_OK:
            self.lbl_cam.setText("Arena SDK not available" if not ARENA_OK else "No camera selected")
            return

        # connect to current serial
        try:
            devices = system.create_device()
        except Exception as e:
            self.lbl_cam.setText(f"Device error: {e}")
            return

        dev = None
        for d in devices:
            s = d.nodemap.get_node("DeviceSerialNumber").value
            if s == serial:
                dev = d
                break

        if dev is None:
            self.lbl_cam.setText(f"Camera {serial} not found")
            return

        self._dev = dev
        self.lbl_cam.setText(f"{self._mode.upper()} • S/N: {serial}")

        # apply overrides via setup_* helpers
        ov = self._owner._arena_overrides.get(serial, {})

        try:
            if self._mode == "line":
                # LIVE PREVIEW for line-scan (ArenaView-style continuous)
                setup_line_preview_live(self._dev, ov)
            else:
                # Normal area preview: same as capture
                setup_area_camera(self._dev, ov)
        except Exception as e:
            self.lbl_cam.setText(f"Config error:\n{e}")

        # show resolution
        # show resolution + enable ROI / pixel format editing
        try:
            nm = self._dev.nodemap
            w_node = nm.get_node("Width")
            h_node = nm.get_node("Height")
            pf_node = nm.get_node("PixelFormat")

            w = int(w_node.value)
            h = int(h_node.value)

            self.lbl_wh.setText(f"{w} x {h}")

            # tighten ranges to camera limits
            self.spin_width.blockSignals(True)
            self.spin_height.blockSignals(True)

            self.spin_width.setRange(int(w_node.min), int(w_node.max))
            self.spin_height.setRange(int(h_node.min), int(h_node.max))

            self.spin_width.setValue(w)
            self.spin_height.setValue(h)

            self.spin_width.blockSignals(False)
            self.spin_height.blockSignals(False)

            pf_val = str(pf_node.value) if pf_node is not None else ""
            self.edit_pixfmt.blockSignals(True)
            self.edit_pixfmt.setText(pf_val)
            self.edit_pixfmt.blockSignals(False)

            self.spin_width.setEnabled(True)
            self.spin_height.setEnabled(True)
            self.edit_pixfmt.setEnabled(True)

            # also push into overrides so capture uses same ROI/PF
            serial = self._current_serial()
            if serial:
                ov = self._owner._arena_overrides.setdefault(serial, {})
                ov["Width"] = w
                ov["Height"] = h
                ov["PixelFormat"] = pf_val or None

        except Exception:
            self.lbl_wh.setText("— x —")
            self.spin_width.setEnabled(False)
            self.spin_height.setEnabled(False)
            self.edit_pixfmt.setEnabled(False)

        if start_preview:
            self._timer.start(200)  # ~5 FPS
            self.btn_preview_toggle.setText("Stop Preview")


    def _show_simulation_settings(self, label: str, mode: str, start_preview: bool):
        """Populate the real settings controls with safe virtual-camera values."""
        self.lbl_cam.setText(label + "  •  SIMULATION")
        width, height = ((640, 900) if mode == "line" else (1280, 720))
        for control, value in ((self.spin_width, width), (self.spin_height, height)):
            control.blockSignals(True); control.setRange(16, 65536); control.setValue(value)
            control.setEnabled(True); control.blockSignals(False)
        self.edit_pixfmt.blockSignals(True); self.edit_pixfmt.setEnabled(True); self.edit_pixfmt.setText("Mono8"); self.edit_pixfmt.blockSignals(False)
        self.lbl_wh.setText(f"{width} x {height}")
        # Do not allow an old persisted 10 µs test value to make the simulator
        # appear incorrectly configured.
        if self.spin_exp.value() <= 10.0:
            self.spin_exp.blockSignals(True); self.spin_exp.setValue(1700.0); self.spin_exp.blockSignals(False)
        self._simulation_tick = 0
        self._show_frame(simulation_frame(mode, 0))
        if start_preview:
            self._timer.start(200); self.btn_preview_toggle.setText("Stop Preview")

    def _show_frame(self, img):
        h, w = img.shape
        qimg = QtGui.QImage(img.data, w, h, w, QtGui.QImage.Format_Grayscale8)
        self.lbl_preview.setPixmap(QtGui.QPixmap.fromImage(qimg).scaled(
            self.lbl_preview.width(), self.lbl_preview.height(), QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation))
        self._update_preview_info(img)

    def _update_preview_info(self, img):
        now=time.monotonic()
        if not self._preview_started_at:
            self._preview_started_at=now; self._preview_frame_count=0
        self._preview_frame_count += 1
        elapsed=max(0.001, now-self._preview_started_at)
        fps=(self._preview_frame_count-1)/elapsed if self._preview_frame_count > 1 else 0.0
        h,w=img.shape[:2]
        pixfmt=self.edit_pixfmt.text().strip() or "Mono8"
        self.preview_info.setText(f"LIVE  •  {fps:.1f} FPS  •  {w} × {h}  •  {pixfmt}")


    def _stop_preview_internal(self):
        self._timer.stop()
        self._preview_started_at=0.0; self._preview_frame_count=0
        if self._dev is not None:
            try:
                _safe_stop(self._dev)  # calls dev.stop_stream()
            except Exception:
                pass
            self._dev = None
        self.btn_preview_toggle.setText("Start Preview")
        current=self.preview_info.text()
        if current.startswith("LIVE"):
            self.preview_info.setText("PAUSED" + current[4:])
        if self.lbl_preview.pixmap() is None:
            self.lbl_preview.setText("Preview\n(press Start Preview)")

    def _grab_and_show(self):
        """
        Timer-driven preview:
        - If mode == 'mvs_area': use hik_capture.grab_live_frame()
        - Else (area/line Arena): use arena_grab_gray(self._dev)
        """
        img = None

        if CAMERA_SIMULATION:
            self._simulation_tick = getattr(self, "_simulation_tick", 0) + 1
            img = simulation_frame(getattr(self, "_mode", "area"), self._simulation_tick)
            self._show_frame(img)
            return

        try:
            if getattr(self, "_mode", "") == "mvs_area":
                # MVS path
                # Ensure we have indices; fall back to current selection if needed
                try:
                    if not hasattr(self, "_mvs_indices") or not self._mvs_indices:
                        self._mvs_indices = self._owner.step_devs.selected_mvs_indices()
                except Exception:
                    self._mvs_indices = []

                if not self._mvs_indices:
                    return

                if not hasattr(self, "_idx"):
                    self._idx = 0
                self._idx = max(0, min(self._idx, len(self._mvs_indices) - 1))
                idx = self._mvs_indices[self._idx]

                # Read overrides if present
                ov = getattr(self._owner, "_mvs_overrides", {}).get(idx, {})
                exp_us = ov.get("ExposureTime", None)
                gain_db = ov.get("Gain", None)

                import hik_capture as hkc
                img = hkc.grab_live_frame(
                    index=idx,
                    exposure_us=exp_us,
                    gain_db=gain_db,
                    mirror=False,
                )

            else:
                # Arena path (area/line)
                if self._dev is None:
                    return
                img = arena_grab_gray(self._dev)

        except Exception as e:
            print("[cam_settings] grab error:", e)
            return

        if img is None:
            return

        h, w = img.shape
        qimg = QtGui.QImage(img.data, w, h, w, QtGui.QImage.Format_Grayscale8)
        pix = QtGui.QPixmap.fromImage(qimg).scaled(
            self.lbl_preview.width(),
            self.lbl_preview.height(),
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
        self.lbl_preview.setPixmap(pix)
        self._update_preview_info(img)





    def stop_preview(self):
        """Called by CameraWidget when leaving this step or restarting."""
        self._stop_preview_internal()



class StepCount(QtWidgets.QWidget):
    changed = QtCore.pyqtSignal()
    def __init__(self):
        super().__init__()
        v=QtWidgets.QVBoxLayout(self); v.setContentsMargins(32,24,32,24); v.setSpacing(14)
        title=_make_title("Images Per Camera")
        subtitle=_make_subtitle("Specify how many images to capture")
        form=QtWidgets.QWidget(); form.setObjectName("formContainer"); form.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        form.setMaximumWidth(900)
        f=QtWidgets.QFormLayout(form); f.setContentsMargins(18,18,18,18); f.setLabelAlignment(QtCore.Qt.AlignRight)
        self.spin=QtWidgets.QSpinBox(); self.spin.setObjectName("imageCountSpin"); self.spin.setRange(1,10000); self.spin.setValue(10); self.spin.setMinimumWidth(160)
        self.spin.valueChanged.connect(self.changed.emit)
        f.addRow("Image Count:", self.spin)
        self.camera_count=1
        self.info=QtWidgets.QLabel(); self.info.setObjectName("infoLabel")
        self.info.setMaximumWidth(900)
        self.spin.valueChanged.connect(self._refresh_summary)
        v.addWidget(title); v.addWidget(subtitle); v.addSpacing(8); v.addWidget(form); v.addWidget(self.info); v.addStretch(1)
        self._refresh_summary()
    def set_camera_count(self, count:int):
        self.camera_count=max(1,int(count)); self._refresh_summary()
    def _refresh_summary(self):
        total=self.spin.value()*self.camera_count
        self.info.setText(f"CAPTURE PLAN    {self.spin.value()} images/camera   •   {self.camera_count} camera(s)   •   {total} total images")
    def value(self)->int: return self.spin.value()

class StepFolder(QtWidgets.QWidget):
    changed = QtCore.pyqtSignal()
    def __init__(self):
        super().__init__()
        v=QtWidgets.QVBoxLayout(self); v.setContentsMargins(32,24,32,24); v.setSpacing(14)
        title=_make_title("Save Location")
        subtitle=_make_subtitle("Choose where to save captured images")
        box=QtWidgets.QWidget(); box.setObjectName("formContainer"); box.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        box.setMaximumWidth(1100)
        bx=QtWidgets.QVBoxLayout(box); bx.setContentsMargins(18,18,18,18)
        lbl=QtWidgets.QLabel("Output Directory:"); lbl.setObjectName("formLabel")
        row=QtWidgets.QHBoxLayout(); row.setSpacing(10)
        default_dir = os.path.abspath("captures")  # fallback
        self.edit = QtWidgets.QLineEdit(default_dir)
        self.edit.setObjectName("pathEdit")

        self.edit.setReadOnly(True)
        btn = QtWidgets.QPushButton("Browse…"); btn.setObjectName("secondaryButton"); btn.clicked.connect(self._choose)

        row.addWidget(self.edit, 1)
        row.addWidget(btn)
        self.status=QtWidgets.QLabel(); self.status.setObjectName("folderStatus")
        bx.addWidget(lbl); bx.addLayout(row); bx.addWidget(self.status)
        v.addWidget(title); v.addWidget(subtitle); v.addSpacing(8); v.addWidget(box); v.addStretch(1)
        self.edit.textChanged.connect(self.changed.emit)
        self.edit.textChanged.connect(self._refresh_status)
        self._refresh_status()
    def set_project_base(self, project_dir: str):
        if project_dir:
            self.edit.setText(project_dir)

    def _choose(self):
        d=QtWidgets.QFileDialog.getExistingDirectory(self,"Select Folder",self.edit.text())
        if d: self.edit.setText(d)
    def _refresh_status(self):
        path=self.edit.text().strip()
        parent=path if os.path.isdir(path) else os.path.dirname(path) or "."
        writable=os.access(parent,os.W_OK)
        self.status.setText(("● Ready to save" if writable else "● Folder is not writable")+f"   •   {path}")
        self.status.setProperty("ready",writable); self.status.style().unpolish(self.status); self.status.style().polish(self.status)
    def value(self)->str: return self.edit.text().strip()

class StepCapture(QtWidgets.QWidget):
    def __init__(self, start_cb, stop_cb):
        super().__init__()
        self._start_cb=start_cb; self._stop_cb=stop_cb
        v=QtWidgets.QVBoxLayout(self); v.setContentsMargins(32,24,32,24); v.setSpacing(12)
        title=_make_title("Capturing Images")
        subtitle=_make_subtitle("Acquisition in progress…")
        box=QtWidgets.QWidget(); box.setObjectName("progressContainer"); box.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        bx=QtWidgets.QVBoxLayout(box); bx.setContentsMargins(14,14,14,14)
        self.pbar=QtWidgets.QProgressBar(); self.pbar.setObjectName("modernProgress"); self.pbar.setMinimumHeight(24)
        self.summary=QtWidgets.QLabel("Preparing capture…"); self.summary.setObjectName("captureSummary")
        self.stop_btn=QtWidgets.QPushButton("Stop Capture"); self.stop_btn.setObjectName("dangerButton"); self.stop_btn.clicked.connect(self.stop)
        sr=QtWidgets.QHBoxLayout(); sr.addWidget(self.summary); sr.addStretch(); sr.addWidget(self.stop_btn)
        bx.addLayout(sr); bx.addWidget(self.pbar)
        loglbl=QtWidgets.QLabel("📋 Capture Log"); loglbl.setObjectName("sectionLabel")
        self.log=QtWidgets.QPlainTextEdit(); self.log.setObjectName("captureLog"); self.log.setReadOnly(True)
        v.addWidget(title); v.addWidget(subtitle); v.addWidget(box); v.addWidget(loglbl); v.addWidget(self.log,1)
    @QtCore.pyqtSlot(int,int)
    def on_progress(self, d:int, t:int):
        percent=int(100*d/max(1,t)); self.pbar.setValue(percent); self.summary.setText(f"{d} of {t} images saved   •   {percent}% complete")
    @QtCore.pyqtSlot(str)
    def on_status(self, msg:str): self.log.appendPlainText(msg)
    @QtCore.pyqtSlot(str)
    def on_failed(self, err:str): QtWidgets.QMessageBox.critical(self,"Capture Failed",err)
    def start(self): self.pbar.setValue(0); self.summary.setText("Preparing capture…"); self.stop_btn.setEnabled(True); self.log.clear(); self._start_cb()
    def stop(self): self._stop_cb()

class StepPreview(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        v=QtWidgets.QVBoxLayout(self); v.setContentsMargins(32,24,32,24); v.setSpacing(12)
        title=_make_title("Image Preview")
        subtitle=_make_subtitle("Review captured images")
        top=QtWidgets.QWidget(); th=QtWidgets.QHBoxLayout(top); th.setContentsMargins(0,0,0,0)
        self.summary=QtWidgets.QLabel("No images captured"); self.summary.setObjectName("previewSummary")
        self.open_btn=QtWidgets.QPushButton("Open Folder"); self.open_btn.setObjectName("secondaryButton"); self.open_btn.clicked.connect(self._open_folder); self.open_btn.setEnabled(False)
        th.addWidget(self.summary); th.addStretch(); th.addWidget(self.open_btn)
        self.scroll=QtWidgets.QScrollArea(); self.scroll.setObjectName("previewScroll"); self.scroll.setWidgetResizable(True)
        self.gallery=QtWidgets.QWidget(); self.grid=QtWidgets.QGridLayout(self.gallery); self.grid.setSpacing(12); self.grid.setContentsMargins(8,8,8,8)
        self.scroll.setWidget(self.gallery)
        v.addWidget(title); v.addWidget(subtitle); v.addWidget(top); v.addWidget(self.scroll,1)
        self._paths=[]
    def _clear(self):
        while self.grid.count():
            it=self.grid.takeAt(0); w=it.widget()
            if w: w.deleteLater()
    def set_paths(self, paths:List[str]):
        self._paths=list(paths); self._clear(); picks=_pick_previews_by_rule(paths); r=c=0
        cameras=len(_group_by_camdir(paths)); self.summary.setText(f"{len(paths)} images captured   •   {cameras} camera(s)   •   showing {len(picks)} previews")
        self.open_btn.setEnabled(bool(paths))
        for p, cam in picks:
            card=QtWidgets.QWidget(); card.setObjectName("previewCard"); card.setAttribute(QtCore.Qt.WA_StyledBackground, True)
            cl=QtWidgets.QVBoxLayout(card); cl.setContentsMargins(10,10,10,10)
            img=QtWidgets.QLabel(); img.setAlignment(QtCore.Qt.AlignCenter)
            img.setCursor(QtCore.Qt.PointingHandCursor)
            img.setToolTip("Click to view the original image at full size")
            img.mousePressEvent=lambda event, path=p: FullImageDialog(path, self).exec_()
            pm=QtGui.QPixmap(p)
            if not pm.isNull(): pm=pm.scaled(360,270,QtCore.Qt.KeepAspectRatio,QtCore.Qt.SmoothTransformation)
            img.setPixmap(pm)
            cap=QtWidgets.QLabel(f"📷 {cam}"); cap.setObjectName("previewCamera")
            name=QtWidgets.QLabel(os.path.basename(p)); name.setObjectName("previewFilename")
            cl.addWidget(img); cl.addWidget(cap); cl.addWidget(name)
            self.grid.addWidget(card, r, c); c+=1
            if c>=2: c=0; r+=1
    def _open_folder(self):
        if self._paths:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(os.path.dirname(os.path.dirname(self._paths[0]))))

# ---------- Main ----------
class CameraWidget(QtWidgets.QWidget):
    def __init__(self, parent=None, project_name: str=None, project_root: str=None):
        super().__init__(parent)

        self.project_name = project_name
        self.project_root = Path(project_root) if project_root else None
        self._toasts = ToastManager.install(self)

        # 🔹 Load last saved overrides from MongoDB
        try:
            from db import load_camera_overrides  # ✅ local import avoids circular init
            arena, mvs = load_camera_overrides()
        except Exception as e:
            print("[cam_app] failed to load overrides from MongoDB:", e)
            arena, mvs = {}, {}

        self._arena_overrides: Dict[str, Dict[str, float]] = arena  # S/N -> settings
        self._mvs_overrides: Dict[int, Dict[str, float]] = mvs      # IDX -> settings

        self._worker: Optional[CaptureWorker] = None
        self._saved_paths: List[str] = []
        self._yolo = None           # cached YOLO inferencer
        self._yolo_conf = 0.20
        self._yolo_iou  = 0.50
        self._yolo_imgsz = 1024


        root=QtWidgets.QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # Sidebar (slimmer + visible right divider)
        sidebar=QtWidgets.QWidget(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(230)
        sidebar.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)
        sidebar.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        sl=QtWidgets.QVBoxLayout(sidebar); sl.setContentsMargins(0,0,0,0); sl.setSpacing(0)
        steps=QtWidgets.QWidget(); col=QtWidgets.QVBoxLayout(steps); col.setContentsMargins(8,16,8,16)
        self.step_indicators=[]
        for i, t in enumerate(["Mode","Cameras","Camera Settings","Images","Location","Capture","Preview"]):
            ind=StepIndicator(i+1, t); self.step_indicators.append(ind); col.addWidget(ind)
        sl.addWidget(steps); sl.addStretch()
        root.addWidget(sidebar)
        sep = QtWidgets.QWidget()
        sep.setObjectName("sidebarSeparator")
        sep.setFixedWidth(1)
        root.addWidget(sep)

        # Main area
        main=QtWidgets.QWidget(); main.setObjectName("mainContainer")
        main.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        ml=QtWidgets.QVBoxLayout(main); ml.setContentsMargins(0,0,0,0); ml.setSpacing(0)

        top=QtWidgets.QWidget(); top.setObjectName("topBar"); top.setFixedHeight(44)
        top.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        tl=QtWidgets.QHBoxLayout(top); tl.setContentsMargins(12,6,12,6)
        if CAMERA_SIMULATION:
            simulation_badge = QtWidgets.QLabel("●  SIMULATION MODE")
            simulation_badge.setObjectName("simulationBadge")
            simulation_badge.setToolTip("Virtual cameras are active. No physical hardware will be accessed.")
            tl.addWidget(simulation_badge)
        tl.addStretch()
        self.btn_help=QtWidgets.QToolButton(); self.btn_help.setObjectName("helpButton"); self.btn_help.setAutoRaise(True)
        self.btn_help.setToolTip("Help (F1)")
        self.btn_help.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxQuestion))
        self.btn_help.setIconSize(QtCore.QSize(20,20)); self.btn_help.setFixedSize(34,34)
        self.btn_help.clicked.connect(self._show_help)
        QtWidgets.QShortcut(QtGui.QKeySequence.HelpContents, self, activated=self._show_help)
        tl.addWidget(self.btn_help, 0, QtCore.Qt.AlignRight)

        self.stack=QtWidgets.QStackedWidget(); self.stack.setObjectName("contentStack")
        self.stack.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.step_mode        = StepMode(AREA_ICON_PATH, LINE_ICON_PATH, icon_size=48)
        self.step_devs        = StepDevices()
        self.step_cam_settings= StepCamSettings(self)
        self.step_count       = StepCount()
        self.step_folder      = StepFolder()
        self.step_capture     = StepCapture(self._start_capture, self._stop_capture)
        self.step_preview     = StepPreview()
        # ---- AUTO set project capture base ----
        if self.project_root:
            proj_dir = self.project_root
        elif self.project_name:
            proj_dir = get_project_folder(self.project_name)
        else:
            proj_dir = Path(os.path.abspath("captures"))

        self._project_dir = proj_dir
        self.step_folder.set_project_base(str(proj_dir))


        for w in [
            self.step_mode,
            self.step_devs,
            self.step_cam_settings,
            self.step_count,
            self.step_folder,
            self.step_capture,
            self.step_preview,
        ]:
            self.stack.addWidget(w)

        ml.addWidget(top); ml.addWidget(self.stack,1)

        nav=QtWidgets.QWidget(); nav.setObjectName("navBar"); nav.setFixedHeight(64)
        nav.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        nl=QtWidgets.QHBoxLayout(nav); nl.setContentsMargins(16,10,16,10)
        self.btn_back=QtWidgets.QPushButton("← Back"); self.btn_back.setObjectName("navButton"); self.btn_back.setFixedHeight(40); self.btn_back.setFixedWidth(110)
        self.btn_next=QtWidgets.QPushButton("Next →"); self.btn_next.setObjectName("primaryNavButton"); self.btn_next.setFixedHeight(40); self.btn_next.setFixedWidth(110)
        self.btn_back.clicked.connect(self._go_back); self.btn_next.clicked.connect(self._go_next)
        nl.addStretch(); nl.addWidget(self.btn_back); nl.addWidget(self.btn_next)
        ml.addWidget(nav)

        root.addWidget(main,1)

        # Style
        self._apply_capture_qss()

        # validations
        self.step_mode.changed.connect(lambda: self.step_devs.set_mode(self.step_mode.value()))
        self.step_mode.changed.connect(lambda: self.step_cam_settings.refresh_from_selection())
        self.step_devs.changed.connect(lambda: self.step_cam_settings.refresh_from_selection())
        self.step_devs.changed.connect(self._sync_capture_plan)
        self.step_devs.changed.connect(self._update_nav)
        self.step_count.changed.connect(self._update_nav)
        self.step_folder.changed.connect(self._update_nav)
        self._update_nav()

    def _sync_capture_plan(self):
        count=len(self.step_devs.selected_mvs_indices()) if self.step_mode.value()=="mvs_area" else len(self.step_devs.selected_serials())
        self.step_count.set_camera_count(count or 1)

    def _toast(self, text: str, kind: str = "info", dur_ms: int = 2500):
        mgr = ToastManager.instance()
        if mgr:
            mgr.show(text, kind=kind, duration_ms=dur_ms)

    def _wire_milestone_toasts(self):
        """Show small toasts for notable status messages coming from the worker."""
        if not self._worker:
            return

        def maybe_toast(msg: str):
            m = msg.lower()
            if "=== applied camera settings" in m:
                self._toast("Camera settings applied.", "success", 1600)
            if "skipped (no frame)" in m:
                self._toast("A frame was skipped.", "warning", 1800)

        self._worker.status.connect(maybe_toast)

    # ---- flow helpers ----
    def _persist_overrides(self):
        """Save current Arena & MVS overrides into MongoDB."""
        try:
            from db import save_camera_overrides  # ✅ local import
            save_camera_overrides(self._arena_overrides, self._mvs_overrides)
        except Exception as e:
            print("[cam_app] failed to save overrides to MongoDB:", e)

    def current_step(self)->int: return self.stack.currentIndex()
    def _on_step_clicked(self, idx:int):
        cur=self.current_step()
        if idx==cur: return
        if idx>cur and not self._validate(cur): return
        if idx >= 6 and not self._saved_paths:
            self._toast("Complete a capture before viewing preview.", "warning", 2500)
            return
        self.stack.setCurrentIndex(idx); self._update_nav()
    def _go_back(self):
        i=self.current_step()
        if i>0: self.stack.setCurrentIndex(i-1); self._update_nav()
    def _restart_app_soft(self):
        try:
            self._stop_capture()
            if self._worker:
                try:
                    self._worker.progress.disconnect(self.step_capture.on_progress)
                    self._worker.status.disconnect(self.step_capture.on_status)
                    self._worker.failed.disconnect(self.step_capture.on_failed)
                    self._worker.finished_ok.disconnect(self._on_capture_done)
                except Exception: pass
                self._worker=None
        except Exception: pass
        self._saved_paths=[]
        try: self.step_preview._clear()
        except Exception: pass
        try: self.step_mode.area.setChecked(True); self.step_mode._refresh_cards()
        except Exception: pass
        try: self.step_devs.refresh_devices(); self.step_devs.list.clearSelection()
        except Exception: pass
        try: self.step_count.spin.setValue(10)
        except Exception: pass
        try: self.step_folder.edit.setText(str(self._project_dir))
        except Exception: pass
        try: self.step_capture.pbar.setValue(0); self.step_capture.log.clear()
        except Exception: pass
        try: self.step_cam_settings.stop_preview()
        except Exception: pass

        self.stack.setCurrentIndex(0); self._update_nav()
        self._toast("Ready for a new session.", "success", 2000)
    def _go_next(self):
        i = self.current_step()
        if not self._validate(i):
            return

        # Location -> Capture (start acquisition)
        if i == 4:
            self.stack.setCurrentIndex(5)
            self._update_nav()
            self.step_capture.start()  # no artificial delay
            return

        if i < 6:
            self.stack.setCurrentIndex(i + 1)
            self._update_nav()
            # when we land on Camera Settings, refresh list/preview
            if i + 1 == 2:
                self.step_cam_settings.refresh_from_selection()
        else:
            self._restart_app_soft()
    def _validate(self, idx:int)->bool:
        if idx == 1:
            ok = self.step_devs.has_selection()
            if not ok:
                self._toast("Please select at least one camera.", "warning", 2500)
            return ok
        if idx == 3:
            ok = self.step_count.value()>=1
            if not ok:
                self._toast("Image count must be ≥ 1.", "warning", 2500)
            return ok
        if idx == 4:
            ok = bool(self.step_folder.value())
            if not ok:
                self._toast("Choose a valid save folder.", "warning", 2500)
            return ok
        return True
    def _update_nav(self):
        i = self.current_step()
        for idx, ind in enumerate(self.step_indicators):
            ind.set_active(idx == i)
            ind.set_complete(idx < i or (idx == 6 and self._saved_paths))

        # Disable Back while capture is running (step 5)
        self.btn_back.setEnabled(i > 0 and i < 5)

        if i == 5:
            self.btn_next.setEnabled(False)
            self.btn_next.setText("Capturing...")
        elif i == 6:
            self.btn_next.setEnabled(True)
            self.btn_next.setText("Finish")
        else:
            self.btn_next.setEnabled(self._validate(i))
            self.btn_next.setText("Next →")
    def _start_capture(self):
        mode=self.step_mode.value()
        n=self.step_count.value()
        base = self.step_folder.value() or str(self._project_dir)
        os.makedirs(base, exist_ok=True)


        self._saved_paths=[]

        if mode == "mvs_area":
            indices = self.step_devs.selected_mvs_indices()
            if not indices:
                self._toast("Please select at least one MVS (Hikrobot) camera.", "warning", 2500)
                return
            self._worker = HikCaptureWorker(indices=indices, n_images=n, base_dir=base, exposure_us=None, gain_db=None, mirror=False)
            cams = len(indices)
        else:
            serials = self.step_devs.selected_serials()
            if not serials:
                self._toast("Please select at least one Arena camera.", "warning", 2500)
                return
            # Pass per-camera overrides (ExposureTime/Gain) into worker
            self._worker = CaptureWorker(
                mode,
                serials,
                n,
                base,
                overrides=self._arena_overrides,
            )
            cams = len(serials)

        self._worker.progress.connect(self.step_capture.on_progress)
        self._worker.status.connect(self.step_capture.on_status)
        self._worker.failed.connect(self.step_capture.on_failed)
        self._worker.finished_ok.connect(self._on_capture_done)

        self._toast(f"Starting capture: {n} image(s) × {cams} camera(s)…", "info", 2500)
        self._worker.failed.connect(lambda err: self._toast("Capture failed — see log.", "error", 4000))
        self._wire_milestone_toasts()
        self._worker.start()

    def _stop_capture(self):
        try:
            if self._worker and self._worker.isRunning():
                self._worker.stop(); self._worker.wait(2000)
        except Exception: pass
        
    def _on_capture_done(self, paths: List[str]):
        self._saved_paths = paths or []
        count = len(self._saved_paths)
        self._toast(f"Capture complete — saved {count} file(s).", "success", 3000)
        self.step_preview.set_paths(self._saved_paths)
        self.stack.setCurrentIndex(6)   # ✅ Preview step
        self._update_nav()


    def _show_help(self): SimpleHelpDialog(self).exec_()
    def _ensure_yolo(self, weights: str):
        if self._yolo is not None:
            return
        # Import your Inference.py *once* and keep the model alive on GPU
        import Inference as infer
        # Force CUDA + FP16 if available; Retina masks on for nicer viz
        self._yolo = infer.UnifiedYOLOInferencer(
            weights=weights,
            device="cuda",                 # will fall back to cpu internally if needed
            conf=self._yolo_conf,
            iou=self._yolo_iou,
            imgsz=self._yolo_imgsz,
            half="auto",
            agnostic_nms=False,
            retina_masks=True,
        )

    def _yolo_predict_and_save(self, image_path: str, out_dir: str):
        """
        Fast path for live: read -> predict -> draw -> save overlay.
        No CSV/JSON in live to avoid disk overhead.
        Returns: (overlay_path, is_ng, score_text)
        """
        import os, cv2
        from Inference import draw_vis  # reuse your visualizer
        os.makedirs(os.path.join(out_dir, "images"), exist_ok=True)

        img = cv2.imread(image_path)
        if img is None:
            return None, False, "—"

        dets, _ = self._yolo.predict_image(img)
        vis = draw_vis(img, dets)
        stem = os.path.splitext(os.path.basename(image_path))[0]
        overlay_path = os.path.join(out_dir, "images", f"{stem}.jpg")
        cv2.imwrite(overlay_path, vis, [cv2.IMWRITE_JPEG_QUALITY, 92])

        # quick GOOD/NG heuristic: max confidence >= 0.30
        max_conf = max((float(d.get("conf", 0.0)) for d in dets), default=0.0)
        is_ng = max_conf >= 0.30
        return overlay_path, is_ng, f"{max_conf:.2f}"

    # ---------- Style ----------
    def _apply_capture_qss(self):
        self.setStyleSheet(CAPTURE_STYLESHEET)

# ---------- Entrypoint ----------
def main():
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    app = QtWidgets.QApplication(sys.argv)
    apply_light_application_palette(app)
    win = CameraWidget()
    win.setWindowTitle("EyRes.AI Camera Acquisition")
    win.resize(1280, 800)
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
