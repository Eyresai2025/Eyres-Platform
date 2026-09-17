from __future__ import annotations
import sys, time, os, glob, random
import threading, subprocess, json, tempfile, shutil
from concurrent.futures import ThreadPoolExecutor
import threading
from typing import List
import hik_capture  
from pathlib import Path
from collections import deque
import cv2
from db import (
    ensure_mongo_connected,
    load_camera_overrides,
    insert_live_record,
    get_today_live_counts,
    get_recent_inspections,
)
from datetime import datetime  # FIXED: Added missing import
from gefs_template_offline import run_good_bad_template_matching
import numpy as np

# Qt Compatibility
PYQT6 = False
try:
    # Prefer PyQt5 first to match main_gui.py (avoid mixing)
    from PyQt5 import QtCore, QtGui, QtWidgets
    from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer
except Exception:
    from PyQt6 import QtCore, QtGui, QtWidgets # type: ignore
    from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer # type: ignore
    PYQT6 = True

try:
    from PyQt5.QtCore import pyqtSlot as _pyqtSlot
except Exception:
    from PyQt6.QtCore import pyqtSlot as _pyqtSlot # type: ignore


def _app_base_dir() -> Path:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _find_logo() -> Path | None:
    media = _app_base_dir() / "Media"
    if not media.exists():
        return None
    for name in ("LOGO-02.png", "logo.png", "Logo.png", "logo@2x.png"):
        p = media / name
        if p.is_file():
            return p
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.gif", "*.webp"):
        files = list(media.glob(ext))
        if files:
            return files[0]
    return None
def _find_camera_image() -> Path | None:
    """
    Look for camera_image.* inside Media folder.
    """
    media = _app_base_dir() / "Media"
    if not media.exists():
        return None

    for ext in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"):
        p = media / f"camera_image{ext}"
        if p.is_file():
            return p
    return None

DEFAULT_RUNS_DIR = r"C:\Users\DELL\Desktop\inf"
INFERENCE_SCRIPT = str((Path(__file__).resolve().parent / "Inference.py").as_posix())
# ---- Alignment & scaling aliases (PyQt5/6 safe) ----
if PYQT6:
    AlignCenter  = Qt.AlignmentFlag.AlignCenter
    AlignRight   = Qt.AlignmentFlag.AlignRight
    AlignLeft    = Qt.AlignmentFlag.AlignLeft
    AlignVCenter = Qt.AlignmentFlag.AlignVCenter
    KeepAspect   = Qt.AspectRatioMode.KeepAspectRatio
    Smooth       = Qt.TransformationMode.SmoothTransformation
else:
    AlignCenter  = Qt.AlignCenter
    AlignRight   = Qt.AlignRight
    AlignLeft    = Qt.AlignLeft
    AlignVCenter = Qt.AlignVCenter
    KeepAspect   = Qt.KeepAspectRatio
    Smooth       = Qt.SmoothTransformation
    

LIVE_QSS = """
QMainWindow {
  background-color: #020617;
}

/* LEFT SIDEBAR */
#Sidebar {
  background-color: #020617;
  border-right: 1px solid #111827;
}

/* MAIN GRID BACKDROP */
#GridHost {
  background-color: #020617;
}
/* Previous inspection blank page */
#PrevPage {
  background-color: #020617;
}
#PrevPlaceholder {
  background-color: #000000;
  border-radius: 18px;
  border: 1px solid #111827;
}

/* ===== TOP HEADER STRIP (Live / Previous) ===== */
#HeaderBar {
  background-color: #020617;
  border-bottom: 1px solid #111827;
}

/* Text-like tabs inside header (no button box) */
#TabButton {
  border: none;
  background: transparent;
  padding: 4px 0;
  margin-right: 24px;        /* spacing between the two labels */
  color: #64748b;            /* muted slate */
  font-size: 11px;
  font-weight: 600;
}

/* Active tab: highlight + underline/bar */
#TabButton[active="true"] {
  color: #e5e7eb;
  border-bottom: 2px solid #22c55e;
}

/* Hover state (only color change, still flat) */
#TabButton:hover {
  color: #e5e7eb;
}

/* ===== INSPECTION SUMMARY LABEL ===== */
#SummaryHeader {
  color: #9ca3af;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.20em;
  text-transform: uppercase;
  padding-top: 4px;
  padding-bottom: 4px;
}

/* ===== BIG STATUS PILL ===== */
#BigStatus {
  border-radius: 16px;
  padding: 6px 16px;
  font-size: 14px;
  font-weight: 900;
  letter-spacing: 2px;
  text-transform: uppercase;
  text-align: center;
  margin: 0px;
  min-height: 32px;
  min-width: 140px;
}

/* neutral (no result yet) */
#BigStatus[mode="neutral"] {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                            stop:0 #6b7280, stop:1 #4b5563);
  border: 2px solid #9ca3af;
  color: #e5e7eb;
}

/* GOOD pill */
#BigStatus[mode="good"] {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                            stop:0 #22c55e, stop:0.5 #16a34a, stop:1 #15803d);
  border: 2px solid #22c55e;
  color: #ffffff;
}

/* NG pill */
#BigStatus[mode="ng"] {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                            stop:0 #ef4444, stop:0.5 #dc2626, stop:1 #b91c1c);
  border: 2px solid #ef4444;
  color: #ffffff;
}

/* ===================== SUMMARY TILES (GOOD / BAD / RR / TOTAL) ===================== */

#SummaryContainer {
  background: transparent;
  border: none;
}

/* each tile frame */
QFrame#SummaryTile {
  background-color: #020617;
  border-radius: 12px;
  border: 1px solid #1e293b;
  padding: 4px 10px 8px 10px;
  margin-bottom: 6px;
}

/* colored top line per tile */
#SummaryLineGood {
  background-color: #16a34a;      /* green */
  border-radius: 2px;
}
#SummaryLineBad {
  background-color: #dc2626;      /* red */
  border-radius: 2px;
}
#SummaryLineRR {
  background-color: #eab308;      /* yellow */
  border-radius: 2px;
}
#SummaryLineTotal {
  background-color: #6b7280;      /* grey */
  border-radius: 2px;
}

/* label + value inside each tile */
#SummaryName {
  color: #e5e7eb;
  font-weight: 600;
  font-size: 11px;
}

#SummaryValue {
  color: #f9fafb;
  font-weight: 800;
  font-size: 15px;   /* bigger numbers */
  font-family: "Consolas","SF Mono","Roboto Mono",monospace;
}

/* ===== RESET + BYPASS AREA ===== */
#ResetButton {
  background-color: #fef2f2;
  border: 1px solid #ef4444;
  border-radius: 6px;
  color: #b91c1c;
  font-weight: 600;
  font-size: 11px;
  padding: 4px 6px;
}
#ResetButton:hover {
  background-color: #fee2e2;
}

/* ===== SMALL INFO CARDS (UPTIME / CYCLE / INSPECTION) ===== */
#InfoCard {
    background-color: #020617;
    border-radius: 8px;
    border: 1px solid #1f2937;
    padding: 4px 8px;
}
#InfoLabel {
  color: #9ca3af;
  font-size: 11px;
  font-weight: 600;
}
#InfoValue {
  color: #e5e7eb;
  font-size: 13px;
  font-weight: 700;
}

/* ==== CAMERA CARDS ==== */
#Card {
  background-color: #020617;
  border-radius: 18px;
  border: 1px solid #1e293b;  /* neutral border */
}
#Card > QFrame, #Card {
  border-radius: 18px;
}
/* GOOD card = green border */
#Card[good="true"] {
  border: 2px solid #22c55e;
}
/* NG card = red border */
#Card[ng="true"] {
  border: 2px solid #ef4444;
}

/* Camera title ONLY - REMOVED NG count styling */
#CardTitle {
  color: #e5e7eb;
  font-weight: 700;
  font-size: 15px;
}

/* Status chip */
#StatusLabel {
  padding: 4px 10px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 700;
}
#StatusLabel[ok="true"] {
  background-color: rgba(22, 163, 74, 0.18);
  border: 1px solid #22c55e;
  color: #bbf7d0;
}
#StatusLabel[ng="true"] {
  background-color: rgba(220, 38, 38, 0.18);
  border: 1px solid #ef4444;
  color: #fecaca;
}
#StatusLabel[na="true"] {
  background-color: rgba(30, 64, 175, 0.18);
  border: 1px solid #1d4ed8;
  color: #bfdbfe;
}

/* Image box */
#ImageBox {
  border-radius: 14px;
  border: 1px dashed #1e293b;
  background-color: #020617;
  color: #6b7280;
  font-size: 12px;
  font-weight: 500;
}

/* Bottom row text */
#BottomRow {
  color: #ffffff;
  font-size: 13px;
  font-weight: 700;
}
"""

# Remove the conflicting CardRight CSS section
LIVE_QSS += """
/* CARD CONTAINER */
#Card {
  background-color: #020617;
  border-radius: 18px;
  border: 1px solid #1e293b;  /* neutral border */
}

/* Glow can stay, but keep shadow subtle */
#Card > QFrame, #Card {
  border-radius: 18px;
}

/* GOOD card = green border */
#Card[good="true"] {
  border: 2px solid #22c55e;
}

/* NG card = red border */
#Card[ng="true"] {
  border: 2px solid #ef4444;
}

/* Camera title ONLY - no NG count */
#CardTitle {
  color: #e5e7eb;
  font-weight: 600;
  font-size: 12px;
}

/* Status chip */
#StatusLabel {
  padding: 4px 10px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 700;
}
#StatusLabel[ok="true"] {
  background-color: rgba(22, 163, 74, 0.18);
  border: 1px solid #22c55e;
  color: #bbf7d0;
}
#StatusLabel[ng="true"] {
  background-color: rgba(220, 38, 38, 0.18);
  border: 1px solid #ef4444;
  color: #fecaca;
}
#StatusLabel[na="true"] {
  background-color: rgba(30, 64, 175, 0.18);
  border: 1px solid #1d4ed8;
  color: #bfdbfe;
}

/* Image box */
#ImageBox {
  border-radius: 14px;
  border: 1px dashed #1e293b;
  background-color: #020617;
  color: #6b7280;
  font-size: 12px;
  font-weight: 500;
}
"""


LIVE_QSS += """
/* ===== METRIC CARDS (Good/Bad/RR/Total) ===== */
#MetricCard {
  background-color: #0b1120;
  border-radius: 10px;
  border: 1px solid #1f2933;
  padding: 4px 10px;
  margin-bottom: 4px;
}

/* coloured top border like your reference image */
#MetricCard[type="good"] {
  border-top: 3px solid #22c55e;
}
#MetricCard[type="bad"] {
  border-top: 3px solid #ef4444;
}
#MetricCard[type="rr"] {
  border-top: 3px solid #eab308;
}
#MetricCard[type="total"] {
  border-top: 3px solid #eab308;
}

/* re-tune summary labels for card style */
#SummaryKey {
  color: #9ca3af;
  font-weight: 600;
  font-size: 10px;
}
#SummaryVal {
  color: #f9fafb;
  font-weight: 800;
  font-size: 14px;
}
"""

LIVE_QSS += """
/* ===== PREVIOUS INSPECTION PAGE ===== */
#PrevPage {
  background-color: #020617;
  padding: 16px;
}

/* Grid container for previous inspections */
#PrevGridContainer {
  background-color: #020617;
  border-radius: 12px;
  border: 1px solid #1e293b;
}

/* Individual previous inspection item */
#PrevItem {
  background-color: #0f172a;
  border-radius: 8px;
  border: 1px solid #1e293b;
}
#PrevItem[good="true"] {
  border: 1px solid #22c55e;
}
#PrevItem[ng="true"] {
  border: 1px solid #ef4444;
}

/* Previous inspection image */
#PrevImage {
  background-color: #020617;
  border-radius: 6px;
  border: 1px solid #334155;
}

/* Stats container for previous page */
#PrevStatsContainer {
  background-color: #0f172a;
  border-radius: 12px;
  border: 1px solid #1e293b;
  padding: 12px;
}
"""
LIVE_QSS += """
#CaptureButton {
  background-color: #1e293b;
  border-radius: 6px;
  border: 1px solid #334155;
  color: #e5e7eb;
  font-size: 11px;
  font-weight: 600;
  padding: 6px 8px;
}
#CaptureButton:disabled {
  background-color: #111827;
  color: #4b5563;
  border-color: #1f2937;
}
#CaptureButton:hover:enabled {
  background-color: #334155;
}
"""

LIVE_QSS += """
/* ===== ANOMALY DETECTION PAGE ===== */
#AnomalyPage {
  background-color: #020617;
}

#AnomalyPreviewBox {
  background-color: #020617;
  border-radius: 12px;
  border: 2px solid #1e293b;
}

#AnomalyPreviewLabel {
  background-color: #020617;
  border-radius: 10px;
  border: 1px dashed #334155;
  color: #64748b;
  font-size: 13px;
  font-weight: 500;
}

#AnomalyButtonsBar {
  background-color: transparent;
}

#AnomalyButton {
  background-color: #1e293b;
  border-radius: 8px;
  border: 1px solid #334155;
  color: #e5e7eb;
  font-size: 12px;
  font-weight: 600;
  padding: 8px 14px;
  min-width: 140px;
}
#AnomalyButton:hover {
  background-color: #334155;
}
"""



# ----------------------------- Card Widget -----------------------------
class CardWidget(QtWidgets.QFrame):
    def __init__(self, cam_id: int, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setProperty("good", False)
        self.setProperty("ng", False)
        self.setMinimumWidth(260)
        self.setMaximumWidth(1100)   # tweak if you want a bit more/less
        self.setMaximumHeight(620) 
        if PYQT6:
            self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        else:
            self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setLineWidth(2)

        self.cam_id = cam_id
        self.ng_count = 0
        self._pixmap: QtGui.QPixmap | None = None

        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 10)
        shadow.setColor(QtGui.QColor(139, 92, 246, 60))
        self.setGraphicsEffect(shadow)

        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        # Top bar
        top = QtWidgets.QHBoxLayout()
        self.title = QtWidgets.QLabel(f"Camera {cam_id}")
        self.title.setObjectName("CardTitle")
        top.addWidget(self.title)
        top.addStretch(1)

        # Status chip
        self.status = QtWidgets.QLabel("N/A")
        self.status.setObjectName("StatusLabel")
        self.status.setAlignment(AlignCenter)
        self.status.setProperty("na", True)
        self.status.setProperty("ok", False)
        self.status.setProperty("ng", False)

        # Image box
        self.image = QtWidgets.QLabel()
        self.image.setObjectName("ImageBox")
        self.image.setAlignment(AlignCenter)

        # fixed drawing area
        self.image.setFixedSize(950, 520)
        self.image.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed,
            QtWidgets.QSizePolicy.Fixed
        )

        # Try to load camera_image.* from Media as initial placeholder
        cam_img_path = _find_camera_image()
        if cam_img_path is not None:
            pm = QtGui.QPixmap(str(cam_img_path))
            if not pm.isNull():
                # 🔹 smaller placeholder: 60% of box, keep aspect
                target_w = int(self.image.width() * 0.6)
                target_h = int(self.image.height() * 0.6)
                pm = pm.scaled(target_w, target_h, KeepAspect, Smooth)
                self.image.setPixmap(pm)
        else:
            self.image.setText("Placeholder")



        # Bottom row
        bottom = QtWidgets.QHBoxLayout()
        # margins: L, T, R, B  → tweak L/R to move whole row
        bottom.setContentsMargins(24, 0, 24, 4)
        bottom.setSpacing(4)

        self.b1 = QtWidgets.QLabel("Status: —")
        self.b2 = QtWidgets.QLabel("Class: —")
        self.score = QtWidgets.QLabel("Score: —")

        for w in (self.b1, self.b2, self.score):
            w.setObjectName("BottomRow")

        # left / center / right alignment INSIDE their slots
        self.b1.setAlignment(AlignLeft   | AlignVCenter)
        self.b2.setAlignment(AlignCenter | AlignVCenter)
        self.score.setAlignment(AlignRight | AlignVCenter)

        # layout: left label, space, middle, space, right label
        bottom.addWidget(self.b1)
        bottom.addStretch(1)      # space between Status and Class
        bottom.addWidget(self.b2)
        bottom.addStretch(1)      # space between Class and Score
        bottom.addWidget(self.score)
        root.addLayout(top)
        self.status.hide()  

        # --- center image vertically in the card ---
        root.addStretch(1)
        root.addWidget(self.image, 0, AlignCenter)
        root.addStretch(1)

        root.addLayout(bottom)

        self._pulse_anim = QPropertyAnimation(self, b"geometry")
        self._pulse_anim.setDuration(200)
        self._pulse_anim.setEasingCurve(QEasingCurve.Type.OutCubic if PYQT6 else QEasingCurve.OutCubic)

    def set_image(self, path: str):
        pm = QtGui.QPixmap(path)
        if pm.isNull():
            self.image.setText("⚠️ Could not load image")
            self.image.setPixmap(QtGui.QPixmap())
            return
        self._pixmap = pm
        self._rescale_pixmap()
        self._animate_success()

    def set_good(self):
        self.setProperty("good", True)
        self.setProperty("ng", False)
        self.style().unpolish(self); self.style().polish(self)
        self.status.setText("GOOD")
        self.status.setProperty("ok", True)
        self.status.setProperty("ng", False)
        self.status.setProperty("na", False)
        self.status.style().unpolish(self.status); self.status.style().polish(self.status)
        shadow = self.graphicsEffect()
        if shadow: shadow.setColor(QtGui.QColor(34, 197, 94, 100))

    def set_ng(self, from_db_count=False):
        self.setProperty("good", False)
        self.setProperty("ng", True)
        self.style().unpolish(self); self.style().polish(self)
        self.status.setText("NG")
        self.status.setProperty("ok", False)
        self.status.setProperty("ng", True)
        self.status.setProperty("na", False)
        self.status.style().unpolish(self.status); self.status.style().polish(self.status)
        shadow = self.graphicsEffect()
        if shadow: shadow.setColor(QtGui.QColor(239, 68, 68, 100))

    def clear(self):
        self._pixmap = None
        cam_img_path = _find_camera_image()
        if cam_img_path is not None:
            pm = QtGui.QPixmap(str(cam_img_path))
            if not pm.isNull():
                target_w = int(self.image.width() * 0.6)
                target_h = int(self.image.height() * 0.6)
                pm = pm.scaled(target_w, target_h, KeepAspect, Smooth)
                self.image.setPixmap(pm)
                self.image.setText("")
        else:
            self.image.setText("Placeholder")
            self.image.setPixmap(QtGui.QPixmap())


    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale_pixmap()

    def _rescale_pixmap(self):
        if not self._pixmap or self._pixmap.isNull():
            return

        # Keep aspect ratio → compressed, black area handled by QSS background
        pm = self._pixmap.scaled(
            self.image.size(),
            KeepAspect,          # <-- was Qt.IgnoreAspectRatio
            Smooth
        )
        self.image.setPixmap(pm)
        self.image.setText("")



    def _animate_success(self):
        start = self.geometry()
        scaled = QtCore.QRect(start)
        scaled.setWidth(int(start.width() * 1.02))
        scaled.setHeight(int(start.height() * 1.02))
        scaled.moveCenter(start.center())
        self._pulse_anim.setStartValue(start)
        self._pulse_anim.setKeyValueAt(0.5, scaled)
        self._pulse_anim.setEndValue(start)
        self._pulse_anim.start()

# ----------------------------- Zoomable Image Popup -----------------------------
class ImageZoomPopup(QtWidgets.QDialog):
    """Popup dialog for zoomable image view."""
    
    def __init__(self, pixmap: QtGui.QPixmap, inspection_data: dict, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Inspection Image - Detailed View")
        self.setModal(True)
        self.setMinimumSize(800, 600)
        
        # Store pixmap
        self.original_pixmap = pixmap
        self.current_scale = 1.0
        
        # Main layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # ----- HEADER: Inspection Info -----
        header_frame = QtWidgets.QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background-color: #0f172a;
                border-radius: 8px;
                border: 1px solid #1e293b;
            }
        """)
        header_layout = QtWidgets.QHBoxLayout(header_frame)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.setSpacing(20)
        
        # Left: Camera and time
        left_layout = QtWidgets.QVBoxLayout()
        left_layout.setSpacing(4)
        
        # Camera and time
        cam_index = inspection_data.get("cam_index", 0)
        dt = inspection_data.get("inspection_datetime", datetime.utcnow())
        if isinstance(dt, datetime):
            date_str = dt.strftime("%Y-%m-%d")
            time_str = dt.strftime("%H:%M:%S")
        else:
            date_str = str(dt)[:10] if len(str(dt)) > 10 else str(dt)
            time_str = str(dt)[11:19] if len(str(dt)) > 19 else str(dt)
        
        cam_label = QtWidgets.QLabel(f"Camera {cam_index + 1}")
        cam_label.setStyleSheet("color: #e5e7eb; font-size: 16px; font-weight: 700;")
        
        date_label = QtWidgets.QLabel(f"{date_str}")
        date_label.setStyleSheet("color: #9ca3af; font-size: 12px;")
        
        time_label = QtWidgets.QLabel(f"{time_str}")
        time_label.setStyleSheet("color: #9ca3af; font-size: 12px;")
        
        left_layout.addWidget(cam_label)
        left_layout.addWidget(date_label)
        left_layout.addWidget(time_label)
        
        # Center: Result with proper spacing
        center_layout = QtWidgets.QVBoxLayout()
        center_layout.setSpacing(4)
        
        is_ng = inspection_data.get("is_ng", False)
        result_text = "NG" if is_ng else "GOOD"
        result_label = QtWidgets.QLabel(result_text)
        result_label.setStyleSheet(f"""
            QLabel {{
                color: white;
                font-size: 18px;
                font-weight: 800;
                padding: 8px 16px;
                border-radius: 8px;
                background-color: {'#ef4444' if is_ng else '#22c55e'};
                min-width: 120px;
                max-width: 120px;
            }}
        """)
        result_label.setAlignment(AlignCenter)
        result_label.setFixedHeight(40)
        
        status_text = QtWidgets.QLabel("RESULT")
        status_text.setStyleSheet("color: #9ca3af; font-size: 11px; font-weight: 600;")
        status_text.setAlignment(AlignCenter)
        
        center_layout.addWidget(status_text)
        center_layout.addWidget(result_label)
        
        # Right: Score and details with proper wrapping
        right_layout = QtWidgets.QVBoxLayout()
        right_layout.setSpacing(4)
        
        score_text = inspection_data.get("score_text", "—")
        score_label = QtWidgets.QLabel(f"Score: {score_text}")
        score_label.setStyleSheet("color: #f9fafb; font-size: 14px; font-weight: 600;")
        score_label.setWordWrap(True)
        
        class_name = inspection_data.get("class_name", "—")
        class_label = QtWidgets.QLabel(f"Class: {class_name}")
        class_label.setStyleSheet("color: #9ca3af; font-size: 12px;")
        class_label.setWordWrap(True)
        
        inspection_type = inspection_data.get("inspection_type", "—")
        type_label = QtWidgets.QLabel(f"Type: {inspection_type}")
        type_label.setStyleSheet("color: #9ca3af; font-size: 12px;")
        type_label.setWordWrap(True)
        
        # Add stretch to push content to top
        right_layout.addWidget(score_label)
        right_layout.addWidget(class_label)
        right_layout.addWidget(type_label)
        right_layout.addStretch(1)
        
        # Add layouts to header
        header_layout.addLayout(left_layout, 1)  # 1 = stretch factor
        header_layout.addLayout(center_layout, 0)  # 0 = fixed size
        header_layout.addLayout(right_layout, 1)  # 1 = stretch factor
        
        layout.addWidget(header_frame)
        
        # ----- IMAGE VIEWER -----
        image_container = QtWidgets.QFrame()
        image_container.setStyleSheet("""
            QFrame {
                background-color: #020617;
                border-radius: 12px;
                border: 2px solid #1e293b;
            }
        """)
        image_layout = QtWidgets.QVBoxLayout(image_container)
        image_layout.setContentsMargins(0, 0, 0, 0)
        
        # Scroll area for zooming
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded if PYQT6 else Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded if PYQT6 else Qt.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #020617;
            }
            QScrollBar:vertical, QScrollBar:horizontal {
                background-color: #1e293b;
                width: 12px;
                height: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
                background-color: #475569;
                border-radius: 6px;
                min-height: 20px;
                min-width: 20px;
            }
            QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
                background-color: #64748b;
            }
        """)
        
        # Image label inside scroll area
        self.image_label = QtWidgets.QLabel()
        self.image_label.setAlignment(AlignCenter)
        self.image_label.setPixmap(self.original_pixmap)
        self.image_label.setScaledContents(False)
        
        self.scroll_area.setWidget(self.image_label)
        image_layout.addWidget(self.scroll_area)
        
        layout.addWidget(image_container, 1)  # Take remaining space
        
        # ----- ZOOM CONTROLS -----
        controls_frame = QtWidgets.QFrame()
        controls_layout = QtWidgets.QHBoxLayout(controls_frame)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(12)
        
        # Zoom buttons
        zoom_out_btn = QtWidgets.QPushButton("➖")
        zoom_out_btn.setToolTip("Zoom Out")
        zoom_out_btn.setFixedSize(40, 40)
        zoom_out_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #e5e7eb;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #334155;
            }
        """)
        zoom_out_btn.clicked.connect(self.zoom_out)
        
        reset_btn = QtWidgets.QPushButton("Reset")
        reset_btn.setToolTip("Reset to Original Size")
        reset_btn.setFixedSize(80, 40)
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #e5e7eb;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #334155;
            }
        """)
        reset_btn.clicked.connect(self.reset_zoom)
        
        zoom_in_btn = QtWidgets.QPushButton("➕")
        zoom_in_btn.setToolTip("Zoom In")
        zoom_in_btn.setFixedSize(40, 40)
        zoom_in_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #e5e7eb;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #334155;
            }
        """)
        zoom_in_btn.clicked.connect(self.zoom_in)
        
        # Zoom label
        self.zoom_label = QtWidgets.QLabel("100%")
        self.zoom_label.setStyleSheet("color: #9ca3af; font-size: 12px; font-weight: 600;")
        self.zoom_label.setAlignment(AlignCenter)
        self.zoom_label.setFixedWidth(60)
        
        # Fit to window button
        fit_btn = QtWidgets.QPushButton("Fit to Window")
        fit_btn.setToolTip("Fit Image to Window")
        fit_btn.setFixedSize(100, 40)
        fit_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #e5e7eb;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #334155;
            }
        """)
        fit_btn.clicked.connect(self.fit_to_window)
        
        controls_layout.addStretch(1)
        controls_layout.addWidget(zoom_out_btn)
        controls_layout.addWidget(reset_btn)
        controls_layout.addWidget(zoom_in_btn)
        controls_layout.addWidget(self.zoom_label)
        controls_layout.addWidget(fit_btn)
        controls_layout.addStretch(1)
        
        layout.addWidget(controls_frame)
        
        # ----- CLOSE BUTTON -----
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.setFixedHeight(40)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #e5e7eb;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #334155;
            }
        """)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        
        # Enable mouse wheel zoom
        self.image_label.setFocusPolicy(Qt.StrongFocus)
        self.image_label.wheelEvent = self.wheel_event
        
        # Adjust dialog size to fit content better
        self.resize(1000, 700)
        
    def wheel_event(self, event):
        """Handle mouse wheel for zooming."""
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()
        event.accept()
    
    def zoom_in(self):
        """Zoom in by 20%."""
        self.current_scale *= 1.2
        self.update_image()
    
    def zoom_out(self):
        """Zoom out by 20%."""
        self.current_scale /= 1.2
        if self.current_scale < 0.1:
            self.current_scale = 0.1
        self.update_image()
    
    def reset_zoom(self):
        """Reset to original size."""
        self.current_scale = 1.0
        self.update_image()
    
    def fit_to_window(self):
        """Fit image to window size."""
        if self.original_pixmap.isNull():
            return
        
        # Get available space in scroll area
        scroll_size = self.scroll_area.viewport().size()
        pixmap_size = self.original_pixmap.size()
        
        # Calculate scale to fit
        scale_w = scroll_size.width() / pixmap_size.width()
        scale_h = scroll_size.height() / pixmap_size.height()
        self.current_scale = min(scale_w, scale_h) * 0.95  # 95% to leave some margin
        
        self.update_image()
    
    def update_image(self):
        """Update the displayed image with current scale."""
        if self.original_pixmap.isNull():
            return
        
        # Scale the pixmap
        new_size = self.original_pixmap.size() * self.current_scale
        scaled_pixmap = self.original_pixmap.scaled(
            new_size,
            KeepAspect,
            Smooth
        )
        
        # Update label
        self.image_label.setPixmap(scaled_pixmap)
        
        # Update zoom label
        zoom_percent = int(self.current_scale * 100)
        self.zoom_label.setText(f"{zoom_percent}%")


# ----------------------------- Previous Inspection Grid Item -----------------------------
class PrevInspectionItem(QtWidgets.QFrame):
    """Widget for displaying a single previous inspection image with info."""
    
    def __init__(self, inspection_data: dict, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PrevItem")
        self.setProperty("good", not inspection_data.get("is_ng", True))
        self.setProperty("ng", inspection_data.get("is_ng", False))
        
        # Store inspection data
        self.inspection_data = inspection_data
        
        # Set fixed size for grid items
        self.setFixedSize(180, 220)
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel if PYQT6 else QtWidgets.QFrame.StyledPanel)
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        
        # Image label - make it clickable
        self.image_label = QtWidgets.QLabel()
        self.image_label.setObjectName("PrevImage")
        self.image_label.setAlignment(AlignCenter)
        self.image_label.setFixedSize(160, 120)
        
        # Make image label clickable
        self.image_label.setCursor(Qt.PointingHandCursor)
        self.image_label.mousePressEvent = self.on_image_clicked
        
        # Load image from binary data
        output_image = inspection_data.get("output_image")
        self.pixmap = None  # Store pixmap for zoom popup
        
        if output_image:
            try:
                # Convert binary data to QPixmap
                img_data = bytes(output_image)
                self.pixmap = QtGui.QPixmap()
                self.pixmap.loadFromData(img_data)
                
                if not self.pixmap.isNull():
                    # Scale image to fit in the thumbnail
                    scaled_pixmap = self.pixmap.scaled(
                        self.image_label.size(),
                        KeepAspect,
                        Smooth
                    )
                    self.image_label.setPixmap(scaled_pixmap)
                else:
                    self.image_label.setText("No Image")
                    self.image_label.setStyleSheet("color: #666; font-size: 10px;")
            except Exception as e:
                print(f"[prev] Error loading image: {e}")
                self.image_label.setText("Error")
                self.image_label.setStyleSheet("color: #f00; font-size: 10px;")
        else:
            self.image_label.setText("No Image")
            self.image_label.setStyleSheet("color: #666; font-size: 10px;")
        
        # Info labels
        info_layout = QtWidgets.QVBoxLayout()
        info_layout.setSpacing(2)
        
        # Camera and time
        cam_index = inspection_data.get("cam_index", 0)
        dt = inspection_data.get("inspection_datetime", datetime.utcnow())
        if isinstance(dt, datetime):
            time_str = dt.strftime("%H:%M:%S")
        else:
            time_str = str(dt)[11:19] if len(str(dt)) > 19 else "??:??:??"
        
        cam_label = QtWidgets.QLabel(f"Cam {cam_index+1} | {time_str}")
        cam_label.setStyleSheet("color: #e5e7eb; font-size: 10px; font-weight: 600;")
        cam_label.setAlignment(AlignCenter)
        
        # Status
        is_ng = inspection_data.get("is_ng", False)
        status_label = QtWidgets.QLabel("NG" if is_ng else "GOOD")
        status_label.setAlignment(AlignCenter)
        status_label.setStyleSheet("""
            font-size: 11px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 4px;
            background-color: %s;
            color: white;
        """ % ("#ef4444" if is_ng else "#22c55e"))
        
        # Score
        score_text = inspection_data.get("score_text", "—")
        score_label = QtWidgets.QLabel(f"Score: {score_text}")
        score_label.setStyleSheet("color: #9ca3af; font-size: 9px;")
        score_label.setAlignment(AlignCenter)
        
        info_layout.addWidget(cam_label)
        info_layout.addWidget(status_label)
        info_layout.addWidget(score_label)
        
        layout.addWidget(self.image_label)
        layout.addLayout(info_layout)
        
        # Apply styling based on result
        self.style().unpolish(self)
        self.style().polish(self)
    
    def on_image_clicked(self, event):
        """Handle image click event to open zoom popup."""
        if self.pixmap and not self.pixmap.isNull():
            # Open zoom popup
            popup = ImageZoomPopup(self.pixmap, self.inspection_data, self)
            popup.exec() if PYQT6 else popup.exec_()
        event.accept()
#-----------------------------------CAM-------------------------------------------------------
class CaptureWorker(QtCore.QObject):
    frameCaptured = QtCore.pyqtSignal(int, int, str)  # cam_index, frame_idx, path
    finished      = QtCore.pyqtSignal()
    error         = QtCore.pyqtSignal(str)
    cycleTick     = QtCore.pyqtSignal(int)            # <--- NEW

    def __init__(
        self,
        cam_indices: List[int],
        frames: int,
        out_dir: str,
        exposure_us=None,
        gain_db=None,
        mirror=False,
        exposure_map: dict[int, float] | None = None,
        gain_map: dict[int, float] | None = None,
    ):
        super().__init__()
        self.cam_indices = cam_indices
        self.frames      = frames            # >0 => finite, <=0 => continuous
        self.out_dir     = out_dir

        # 🔹 default values (if nothing specific in the map)
        self.exposure_us = exposure_us
        self.gain_db     = gain_db

        # 🔹 per-camera overrides (index -> value)
        self.exposure_map: dict[int, float] = exposure_map or {}
        self.gain_map: dict[int, float]     = gain_map or {}

        self.mirror      = mirror
        self._running    = True
        self._cycle      = 0                 # <--- NEW


    @QtCore.pyqtSlot()
    def stop(self):
        """Ask the worker loop to stop."""
        self._running = False

    @QtCore.pyqtSlot()
    def run(self):
        try:
            def _cb(cam_idx, frame_i, path):
                self.frameCaptured.emit(int(cam_idx), int(frame_i), str(path))

            def _exp_for(idx: int):
                # per-camera exposure; fall back to global exposure_us
                return self.exposure_map.get(idx, self.exposure_us)

            def _gain_for(idx: int):
                # per-camera gain; fall back to global gain_db
                return self.gain_map.get(idx, self.gain_db)

            # ----- FINITE MODE -----
            if self.frames and self.frames > 0:
                if not self._running:
                    return

                # capture 'frames' images per camera with its own exp/gain
                for cam_idx in self.cam_indices:
                    hik_capture.capture_multi(
                        indices=[cam_idx],
                        frames=self.frames,
                        base_out=self.out_dir,
                        mirror=self.mirror,
                        exposure_us=_exp_for(cam_idx),
                        gain_db=_gain_for(cam_idx),
                        progress_cb=_cb,
                    )

                self._cycle += 1
                self.cycleTick.emit(self._cycle)
                self.finished.emit()
                return

            # ----- CONTINUOUS MODE (frames <= 0) -----
            while self._running:
                self._cycle += 1
                # each loop = one "cycle": 1 frame per camera
                for cam_idx in self.cam_indices:
                    hik_capture.capture_multi(
                        indices=[cam_idx],
                        frames=1,              # 1 frame per cam per cycle
                        base_out=self.out_dir,
                        mirror=self.mirror,
                        exposure_us=_exp_for(cam_idx),
                        gain_db=_gain_for(cam_idx),
                        progress_cb=_cb,
                    )
                self.cycleTick.emit(self._cycle)

            # when stop() called, loop exits:
            self.finished.emit()

        except Exception as e:
            self.error.emit(str(e))


# ----------------------------- Simple Toggle Switch -----------------------------
class ToggleSwitch(QtWidgets.QCheckBox):
    """Small pill-style on/off switch used for Rejection Bypass."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setChecked(False)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(40, 22)  # pill size
        self.setText("")           # no checkbox text

    def paintEvent(self, event):
        radius = self.height() // 2
        center = self.rect().center()

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        # Background
        if self.isChecked():
            bg = QtGui.QColor("#22c55e")   # green
        else:
            bg = QtGui.QColor("#4b5563")   # grey

        painter.setPen(QtGui.QPen(bg))
        painter.setBrush(bg)
        painter.drawRoundedRect(2, 2, self.width() - 4, self.height() - 4, radius, radius)

        # Handle
        handle_r = radius - 3
        if self.isChecked():
            cx = self.width() - radius
        else:
            cx = radius
        cy = center.y()

        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor("#f9fafb"))
        painter.drawEllipse(QtCore.QPointF(cx, cy), handle_r, handle_r)
        painter.end()



# ----------------------------- Main Window -----------------------------
class LiveConfigDialog(QtWidgets.QDialog):
    def __init__(self, max_cams: int, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Live Capture Configuration")
        self.setModal(True)

        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(AlignRight | AlignVCenter)

        # --- Backend ---
        self.combo_backend = QtWidgets.QComboBox()
        self.combo_backend.addItems(["yolo", "detectron"])
        form.addRow("Inference backend:", self.combo_backend)

        # --- Weights path ---
        w_layout = QtWidgets.QHBoxLayout()
        self.ed_weights = QtWidgets.QLineEdit()
        self.ed_weights.setPlaceholderText("Select weights file (.pt / .pth)")
        btn_browse = QtWidgets.QPushButton("Browse…")
        w_layout.addWidget(self.ed_weights, 1)
        w_layout.addWidget(btn_browse)
        form.addRow("Weights file:", w_layout)

        # --- Num cameras (also how many cards) ---
        self.spin_cams = QtWidgets.QSpinBox()
        self.spin_cams.setRange(1, max_cams)
        self.spin_cams.setValue(min(4, max_cams))
        form.addRow("How many cameras:", self.spin_cams)

        # --- Detectron num_classes (only visible for Detectron) ---
        self.lbl_classes = QtWidgets.QLabel("Detectron num_classes:")
        self.spin_classes = QtWidgets.QSpinBox()
        self.spin_classes.setRange(1, 1000)
        self.spin_classes.setValue(5)
        form.addRow(self.lbl_classes, self.spin_classes)

        layout.addLayout(form)

        # Buttons
        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        layout.addWidget(btn_box)

        # Connections
        btn_browse.clicked.connect(self._on_browse)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        self.combo_backend.currentTextChanged.connect(self._on_backend_changed)

        # Initial state
        self._on_backend_changed(self.combo_backend.currentText())

    def _on_backend_changed(self, text: str):
        """Show num_classes only for Detectron."""
        is_detectron = (text.lower() == "detectron")
        self.lbl_classes.setVisible(is_detectron)
        self.spin_classes.setVisible(is_detectron)

    def _on_browse(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Weights File", "",
            "Model files (*.pt *.pth);;All files (*)"
        )
        if path:
            self.ed_weights.setText(path)

    def accept(self):
        # Basic validation
        if not self.ed_weights.text().strip():
            QtWidgets.QMessageBox.warning(self, "Missing Weights",
                                          "Please select a weights file.")
            return
        super().accept()

    def get_values(self) -> dict:
        backend = self.combo_backend.currentText().lower()
        return {
            "backend": backend,
            "weights": self.ed_weights.text().strip(),
            "num_cams": self.spin_cams.value(),
            "num_classes": self.spin_classes.value() if backend == "detectron" else None,
        }

# ----------------------------- Main Window -----------------------------
class MainWindow(QtWidgets.QMainWindow):
    # ==== signals (must be class attributes for PyQt) ====
    infer_result = QtCore.pyqtSignal(int, str, bool, str)

    def _make_info_card(self, title_text: str, value_text: str = "—"):
        """Small info row card: title on left, value on right."""
        card = QtWidgets.QFrame()
        card.setObjectName("InfoCard")
        lay = QtWidgets.QHBoxLayout(card)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(4)

        key = QtWidgets.QLabel(title_text)
        val = QtWidgets.QLabel(value_text)

        # bump font size a little
        key_font = key.font()
        key_font.setPointSize(key_font.pointSize() + 1)
        key.setFont(key_font)

        val_font = val.font()
        val_font.setPointSize(val_font.pointSize() + 1)
        val.setFont(val_font)

        key.setStyleSheet("color:#9ca3af; font-weight:600;")
        val.setStyleSheet("color:#f9fafb; font-weight:600;")

        val.setAlignment(AlignRight | AlignVCenter)

        lay.addWidget(key, 1)
        lay.addWidget(val, 0)
        return card, val

    def __init__(self, mvs_overrides: dict[int, dict] | None = None):
        super().__init__()
        self.setWindowTitle("LIVE UI ")

        screen = QtWidgets.QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            w = min(1300, avail.width())
            h = min(700,  avail.height())
        else:
            w, h = 1366, 768

        self.setMinimumSize(w, h)
        self.resize(w, h)
        self.cycle_count = 0
        self._mvs_overrides: dict[int, dict] = mvs_overrides or {}

        # ---- inference/session config ----
        self._infer_cfg = {
            "backend": None,       # "yolo" | "detectron"
            "weights": None,
            "num_classes": None,   # detectron only
            "device": None,        # optional
            "out_dir": None,       # temp per run (will change to results/..._op/...)
            "ip_dir": None,        # NEW: results/..._ip/... for input images
        }

        self._infer_pool = ThreadPoolExecutor(max_workers=2)

        # ---- state & maps ----
        self.good = 0
        self.bad = 0
        self.start_time = time.time()
        self.has_results = False
        self._last_is_ng: bool | None = None  # None = no result yet
        self.cards: list[CardWidget] = []
        self._dev_map: dict[int, int] = {}   # cam index -> card index
        self.num_cams = 0
        self.num_frames = 0
        self._pending = deque()   # holds tuples (cam_index, img_path)
        self._inflight = False    # True when one inference is running
        self._infer_pool = ThreadPoolExecutor(max_workers=2)
        self.infer_result.connect(self._apply_infer_result)
        self._current_input: dict[int, str] = {}
        # Last saved GOOD template (for anomaly stage later)
        self._last_good_template_path: str | None = None

        # ---- manual one-shot capture mode ----
        self._single_capture_mode = False
        self._single_cap_cam_indices: list[int] = []
        self._capture_running = False
        # --- Anomaly live preview timer & state ---
        self.anomaly_timer = QTimer(self)
        self.anomaly_timer.timeout.connect(self._update_anomaly_preview)
        self._anomaly_cam_index = None
        self._anomaly_last_frame = None
        # ---- root containers ----
        central = QtWidgets.QWidget()
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        # ---- sidebar ----
        self.sidebar = QtWidgets.QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(280)

        side = QtWidgets.QVBoxLayout(self.sidebar)
        side.setContentsMargins(16, 16, 16, 16)
        side.setSpacing(14)

        # ============ LOGO HEADER ============
        self.logoLabel = QtWidgets.QLabel()
        self.logoLabel.setObjectName("LiveLogo")
        self.logoLabel.setAlignment(AlignCenter)

        logo_path = _find_logo()
        if logo_path is not None:
            pm = QtGui.QPixmap(str(logo_path))
            if not pm.isNull():
                pm = pm.scaled(220, 80, KeepAspect, Smooth)
                self.logoLabel.setPixmap(pm)
            else:
                self.logoLabel.setText("EyRes.AI")
        else:
            self.logoLabel.setText("EyRes.AI")

        self.logoLabel.setStyleSheet("""
            QLabel#LiveLogo {
                color:#e5e7eb;
                font-size:18px;
                font-weight:800;
            }
        """)
        side.addWidget(self.logoLabel)
        side.addSpacing(8)

        # ===== NEW: "Inspection Summary" label =====
        self.summaryHeader = QtWidgets.QLabel("INSPECTION SUMMARY")
        self.summaryHeader.setObjectName("SummaryHeader")
        side.addWidget(self.summaryHeader)

        # ============ INSPECTION SUMMARY – 4 SMALL TILES (UNCHANGED STYLE) ============
        self.summaryBox = QtWidgets.QWidget(objectName="SummaryContainer")
        summary_layout = QtWidgets.QVBoxLayout(self.summaryBox)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(6)

        def make_tile(title: str, line_obj_name: str, value_label: QtWidgets.QLabel):
            tile = QtWidgets.QFrame()
            tile.setObjectName("SummaryTile")
            v = QtWidgets.QVBoxLayout(tile)
            v.setContentsMargins(6, 6, 6, 6)
            v.setSpacing(4)

            # colored line on top
            line = QtWidgets.QFrame()
            line.setObjectName(line_obj_name)
            if PYQT6:
                line.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            else:
                line.setFrameShape(QtWidgets.QFrame.NoFrame)
            line.setFixedHeight(3)
            v.addWidget(line)

            # name + value row
            row = QtWidgets.QHBoxLayout()
            name_lbl = QtWidgets.QLabel(title)
            name_lbl.setObjectName("SummaryName")

            value_label.setObjectName("SummaryValue")
            value_label.setAlignment(AlignRight | AlignVCenter)

            row.addWidget(name_lbl)
            row.addStretch(1)
            row.addWidget(value_label)
            v.addLayout(row)

            summary_layout.addWidget(tile)

        # value labels
        self.lblGoodVal  = QtWidgets.QLabel("0")
        self.lblBadVal   = QtWidgets.QLabel("0")
        self.lblRatioVal = QtWidgets.QLabel("0.00%")
        self.lblTotalVal = QtWidgets.QLabel("0")

        make_tile("Good (G)",        "SummaryLineGood",  self.lblGoodVal)
        make_tile("Bad (NG)",        "SummaryLineBad",   self.lblBadVal)
        make_tile("Rej. Ratio (RR)", "SummaryLineRR",    self.lblRatioVal)
        make_tile("Total",           "SummaryLineTotal", self.lblTotalVal)

        side.addWidget(self.summaryBox)
        side.addSpacing(6)


        # ============ Reset button ============
        self.btnReset = QtWidgets.QPushButton("Reset Counts / Images")
        self.btnReset.setObjectName("ResetButton")
        self.btnReset.clicked.connect(self._reset_all)
        side.addWidget(self.btnReset)

        # # ============ NEW: Manual Capture button ============
        # self.btnCapture = QtWidgets.QPushButton("Capture")
        # self.btnCapture.setObjectName("CaptureButton")
        # self.btnCapture.setEnabled(False)  # only enabled in manual mode
        # self.btnCapture.clicked.connect(self._manual_capture_trigger)
        # side.addWidget(self.btnCapture)

        # ============ Rejection Bypass (toggle switch) ============
        bypassRow = QtWidgets.QHBoxLayout()

        self.lblBypass = QtWidgets.QLabel("Rejection Bypass")
        self.lblBypass.setStyleSheet("color:#e5e7eb; font-size:11px; font-weight:600;")
        self.toggleBypass = ToggleSwitch()

        bypassRow.addWidget(self.lblBypass)
        bypassRow.addStretch(1)
        bypassRow.addWidget(self.toggleBypass)

        side.addLayout(bypassRow)
        side.addSpacing(6)

        side.addSpacing(8)

        # ============ Small info cards: Uptime / Cycle / Inspection ============
        self.uptimeCard, self.lblUptimeVal = self._make_info_card("Uptime", "00:00:00")
        self.cycleCard,  self.lblCycleVal  = self._make_info_card("Cycle", "0")
        self.inspCard,   self.lblInspVal   = self._make_info_card("Inspection", "idle")

        side.addWidget(self.uptimeCard)
        side.addWidget(self.cycleCard)
        side.addWidget(self.inspCard)

        side.addStretch(1)

        # ============ BIG GOOD/NG PILL (UPDATED PILL STYLE) ============
        self.bigStatus = QtWidgets.QLabel("—")
        self.bigStatus.setObjectName("BigStatus")
        self.bigStatus.setAlignment(AlignCenter)
        self.bigStatus.setProperty("mode", "neutral")

        # --- pill dimensions - make wider to fit "GOOD" text ---
        pill_h = 32  # Slightly taller for better appearance
        pill_w = 140  # Fixed width that fits both "GOOD" and "NG" comfortably

        self.bigStatus.setFixedSize(pill_w, pill_h)
        self.bigStatus.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed,
            QtWidgets.QSizePolicy.Fixed
        )

        # Enhanced pill styling - removed text-shadow
        self.bigStatus.setStyleSheet("""
            QLabel#BigStatus {
                border-radius: 16px;  /* Half of height for perfect pill shape */
                padding: 6px 16px;
                font-size: 14px;
                font-weight: 900;
                letter-spacing: 2px;
                text-transform: uppercase;
                text-align: center;
                margin: 0px;
            }
            
            /* neutral (no result yet) */
            QLabel#BigStatus[mode="neutral"] {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                          stop:0 #6b7280, stop:1 #4b5563);
                border: 2px solid #9ca3af;
                color: #e5e7eb;
            }

            /* GOOD pill - Enhanced green gradient */
            QLabel#BigStatus[mode="good"] {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                          stop:0 #22c55e, stop:0.5 #16a34a, stop:1 #15803d);
                border: 2px solid #22c55e;
                color: #ffffff;
            }

            /* NG pill - Enhanced red gradient */
            QLabel#BigStatus[mode="ng"] {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                          stop:0 #ef4444, stop:0.5 #dc2626, stop:1 #b91c1c);
                border: 2px solid #ef4444;
                color: #ffffff;
            }
        """)

        # add centered at bottom of sidebar
        side.addWidget(self.bigStatus, 0, AlignCenter)

        # ---- grid host = header bar (top) + camera grid (below) ----
        self.gridHost = QtWidgets.QWidget()
        self.gridHost.setObjectName("GridHost")

        # vertical layout on the right side
        self.gridHostLayout = QtWidgets.QVBoxLayout(self.gridHost)
        # top margin small so header hugs the top (under title bar)
        self.gridHostLayout.setContentsMargins(16, 4, 16, 16)
        self.gridHostLayout.setSpacing(8)

        # ===== HEADER BAR (where you marked red) =====
        headerFrame = QtWidgets.QFrame()
        headerFrame.setObjectName("HeaderBar")
        headerLayout = QtWidgets.QHBoxLayout(headerFrame)
        headerLayout.setContentsMargins(0, 4, 0, 4)
        headerLayout.setSpacing(8)

        # the three options
        self.btnLiveTab = QtWidgets.QPushButton("Live Inspection")
        self.btnLiveTab.setObjectName("TabButton")
        self.btnLiveTab.setProperty("active", True)
        self.btnLiveTab.setFlat(True)

        self.btnPrevTab = QtWidgets.QPushButton("Previous Inspection")
        self.btnPrevTab.setObjectName("TabButton")
        self.btnPrevTab.setProperty("active", False)
        self.btnPrevTab.setFlat(True)

        self.btnAnomalyTab = QtWidgets.QPushButton("Anomaly Detection")
        self.btnAnomalyTab.setObjectName("TabButton")
        self.btnAnomalyTab.setProperty("active", False)
        self.btnAnomalyTab.setFlat(True)

        # place them near the left; add stretch on the right
        headerLayout.addWidget(self.btnLiveTab)
        headerLayout.addWidget(self.btnPrevTab)
        headerLayout.addWidget(self.btnAnomalyTab)
        headerLayout.addStretch(1)


        self.gridHostLayout.addWidget(headerFrame)

        # Live page widget that will hold the camera card grid
        self.livePage = QtWidgets.QWidget()
        self.grid = QtWidgets.QGridLayout(self.livePage)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(16)
        self.grid.setContentsMargins(0, 8, 0, 0)

        # Previous page: show last 30 inspections in grid
        self.prevPage = QtWidgets.QWidget()  # FIXED: Only create prevPage once
        self.prevPage.setObjectName("PrevPage")
        prevMainLayout = QtWidgets.QVBoxLayout(self.prevPage)
        prevMainLayout.setContentsMargins(16, 8, 16, 16)
        prevMainLayout.setSpacing(16)

        # ----- STATS SECTION -----
        stats_container = QtWidgets.QFrame()
        stats_container.setObjectName("PrevStatsContainer")
        stats_layout = QtWidgets.QVBoxLayout(stats_container)
        stats_layout.setContentsMargins(12, 12, 12, 12)
        stats_layout.setSpacing(8)

        # Stats title
        stats_title = QtWidgets.QLabel("OVERALL STATISTICS")
        stats_title.setStyleSheet("""
            color: #22c55e;
            font-size: 14px;
            font-weight: 800;
            letter-spacing: 1px;
            text-transform: uppercase;
        """)
        stats_title.setAlignment(AlignCenter)
        stats_layout.addWidget(stats_title)

        # Stats grid
        stats_grid = QtWidgets.QGridLayout()
        stats_grid.setHorizontalSpacing(20)
        stats_grid.setVerticalSpacing(8)

        # Stat items
        self.prev_total_label = QtWidgets.QLabel("—")
        self.prev_good_label = QtWidgets.QLabel("—")
        self.prev_bad_label = QtWidgets.QLabel("—")
        self.prev_ratio_label = QtWidgets.QLabel("—")
        self.prev_last_time = QtWidgets.QLabel("—")
        self.prev_cam_count = QtWidgets.QLabel("—")

        stat_items = [
            ("Total Inspections:", self.prev_total_label),
            ("Good Results:", self.prev_good_label),
            ("Bad Results:", self.prev_bad_label),
            ("Rejection Ratio:", self.prev_ratio_label),
            ("Last Inspection:", self.prev_last_time),
            ("Cameras Used:", self.prev_cam_count),
        ]

        for i, (label_text, value_widget) in enumerate(stat_items):
            row = i // 2
            col = (i % 2) * 2
            
            # Label
            label = QtWidgets.QLabel(label_text)
            label.setStyleSheet("color: #9ca3af; font-size: 11px; font-weight: 600;")
            stats_grid.addWidget(label, row, col)
            
            # Value
            value_widget.setStyleSheet("color: #f9fafb; font-size: 13px; font-weight: 700;")
            value_widget.setAlignment(AlignRight | AlignVCenter)
            stats_grid.addWidget(value_widget, row, col + 1)

        stats_layout.addLayout(stats_grid)
        prevMainLayout.addWidget(stats_container)

        # ----- IMAGES GRID SECTION -----
        images_container = QtWidgets.QFrame()
        images_container.setObjectName("PrevGridContainer")
        images_layout = QtWidgets.QVBoxLayout(images_container)
        images_layout.setContentsMargins(12, 12, 12, 12)
        images_layout.setSpacing(12)

        # Grid title
        grid_title = QtWidgets.QLabel("LAST 30 INSPECTIONS")
        grid_title.setStyleSheet("""
            color: #e5e7eb;
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 1px;
        """)
        grid_title.setAlignment(AlignLeft | AlignVCenter)
        images_layout.addWidget(grid_title)

        # Scroll area for grid
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff if PYQT6 else Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded if PYQT6 else Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #1e293b;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background-color: #475569;
                border-radius: 5px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #64748b;
            }
        """)

        # Grid widget
        self.prev_grid_widget = QtWidgets.QWidget()
        self.prev_grid_layout = QtWidgets.QGridLayout(self.prev_grid_widget)
        self.prev_grid_layout.setHorizontalSpacing(12)
        self.prev_grid_layout.setVerticalSpacing(12)
        self.prev_grid_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area.setWidget(self.prev_grid_widget)
        images_layout.addWidget(scroll_area)

        prevMainLayout.addWidget(images_container, 1)  # Take remaining space

        # ----- ANOMALY DETECTION PAGE -----
        self.anomalyPage = QtWidgets.QWidget()
        self.anomalyPage.setObjectName("AnomalyPage")
        anomalyLayout = QtWidgets.QVBoxLayout(self.anomalyPage)
        # slightly smaller margins so the image can grow more
        anomalyLayout.setContentsMargins(16, 4, 16, 12)
        anomalyLayout.setSpacing(10)

        # Preview box (centered image)
        previewBox = QtWidgets.QFrame()
        previewBox.setObjectName("AnomalyPreviewBox")
        previewLayout = QtWidgets.QVBoxLayout(previewBox)
        # reduce inner padding so image uses almost all of the box
        previewLayout.setContentsMargins(8, 8, 8, 8)
        previewLayout.setSpacing(4)

        self.anomalyPreviewLabel = QtWidgets.QLabel("Live preview will appear here")
        self.anomalyPreviewLabel.setObjectName("AnomalyPreviewLabel")
        self.anomalyPreviewLabel.setAlignment(AlignCenter)

        # 🔹 BIGGER IMAGE AREA
        # increase the minimum size and let it expand with the window
        self.anomalyPreviewLabel.setMinimumSize(1100, 620)
        self.anomalyPreviewLabel.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding
        )

        # center label, let it take all vertical space in the preview box
        previewLayout.addWidget(self.anomalyPreviewLabel, 1, AlignCenter)

        anomalyLayout.addWidget(previewBox, 1)


        # Try to use same camera placeholder image
        cam_img_path = _find_camera_image()
        if cam_img_path is not None:
            pm = QtGui.QPixmap(str(cam_img_path))
            if not pm.isNull():
                pm = pm.scaled(800, 450, KeepAspect, Smooth)
                self.anomalyPreviewLabel.setPixmap(pm)
                self.anomalyPreviewLabel.setText("")



        previewLayout.addStretch(1)
        previewLayout.addWidget(self.anomalyPreviewLabel, 0, AlignCenter)
        previewLayout.addStretch(1)

        anomalyLayout.addWidget(previewBox, 1)

        # Buttons row under the preview
        buttonsBar = QtWidgets.QFrame()
        buttonsBar.setObjectName("AnomalyButtonsBar")
        buttonsLayout = QtWidgets.QHBoxLayout(buttonsBar)
        buttonsLayout.setContentsMargins(0, 0, 0, 0)
        buttonsLayout.setSpacing(12)

        # Left stretch to center the group
        buttonsLayout.addStretch(1)

        self.btnTemplateCreation = QtWidgets.QPushButton("Template Creation")
        self.btnTemplateCreation.setObjectName("AnomalyButton")
        self.btnTemplateCreation.setFixedHeight(40)

        self.btnAnomalyDetect = QtWidgets.QPushButton("Anomaly Detection")
        self.btnAnomalyDetect.setObjectName("AnomalyButton")
        self.btnAnomalyDetect.setFixedHeight(40)

        self.btnSyntheticDefect = QtWidgets.QPushButton("Synthetic Defect Creation")
        self.btnSyntheticDefect.setObjectName("AnomalyButton")
        self.btnSyntheticDefect.setFixedHeight(40)

        self.btnClassification = QtWidgets.QPushButton("Load")
        self.btnClassification.setObjectName("AnomalyButton")
        self.btnClassification.setFixedHeight(40)

        self.btnAnomalyClear = QtWidgets.QPushButton("Clear")
        self.btnAnomalyClear.setObjectName("AnomalyButton")
        self.btnAnomalyClear.setFixedHeight(40)
        self.btnTemplateCreation.clicked.connect(self._handle_template_creation)
        self.btnAnomalyDetect.clicked.connect(self._handle_anomaly_detection)
        self.btnAnomalyClear.clicked.connect(self._handle_anomaly_clear)
        self.btnSyntheticDefect.clicked.connect(self._handle_synthetic_defect)
        self.btnClassification.clicked.connect(self._handle_anomaly_load)

        for b in (
            self.btnTemplateCreation,
            self.btnAnomalyDetect,
            self.btnSyntheticDefect,
            self.btnClassification,
            self.btnAnomalyClear,
        ):
            buttonsLayout.addWidget(b)
        # Right stretch to keep them centered
        buttonsLayout.addStretch(1)

        anomalyLayout.addWidget(buttonsBar, 0)


        # Stack the pages and put the stack under the header
        self.stack = QtWidgets.QStackedLayout()
        self.stack.addWidget(self.livePage)     # index 0
        self.stack.addWidget(self.prevPage)     # index 1
        self.stack.addWidget(self.anomalyPage)  # index 2
        self.gridHostLayout.addLayout(self.stack, 1)
        self.stack.setCurrentWidget(self.livePage)


        # add sidebar + right side to root layout
        root.addWidget(self.sidebar)
        root.addWidget(self.gridHost, 1)

        # simple toggle for active style + page switch
        def _set_tab_mode(mode: str):
            live_active    = (mode == "live")
            prev_active    = (mode == "previous")
            anomaly_active = (mode == "anomaly")
            
            # header highlight
            self.btnLiveTab.setProperty("active", live_active)
            self.btnPrevTab.setProperty("active", prev_active)
            self.btnAnomalyTab.setProperty("active", anomaly_active)

            for btn in (self.btnLiveTab, self.btnPrevTab, self.btnAnomalyTab):
                btn.style().unpolish(btn)
                btn.style().polish(btn)
            if anomaly_active:
                self._start_anomaly_preview()
            else:
                self._stop_anomaly_preview()
            
            # switch stacked page
            if live_active:
                self.stack.setCurrentWidget(self.livePage)
            elif prev_active:
                self.stack.setCurrentWidget(self.prevPage)
                self.load_previous_inspections()
            else:  # anomaly
                self.stack.setCurrentWidget(self.anomalyPage)

        self.btnLiveTab.clicked.connect(lambda: _set_tab_mode("live"))
        self.btnPrevTab.clicked.connect(lambda: _set_tab_mode("previous"))
        self.btnAnomalyTab.clicked.connect(lambda: _set_tab_mode("anomaly"))


        self.cards: list[CardWidget] = []
        self.apply_theme()

        # Uptime timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self._build_cards(1)                                        
        self.has_results = False                                     
        self._refresh_summary()  
        self._init_counts_from_db()
    
    def _get_latest_image_in_folder(self, folder: Path) -> str | None:
        """
        Return path of latest image file in a folder, or None if nothing found.
        """
        exts = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
        if not folder.is_dir():
            return None

        candidates = [
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in exts
        ]
        if not candidates:
            return None

        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        return str(latest)

    
    def load_previous_inspections(self):
        """Load and display the last 30 inspections in the previous page."""
        try:
            # Clear existing grid items
            for i in reversed(range(self.prev_grid_layout.count())):
                item = self.prev_grid_layout.itemAt(i)
                if item.widget():
                    item.widget().setParent(None)
            
            # Get recent inspections from DB - FILTER for cam_index = 0 if you want only single camera
            inspections = get_recent_inspections(limit=30)
            
            # OPTIONAL: Filter to show only cam_index = 0 results
            # inspections = [item for item in inspections if item.get("cam_index", 0) == 0]
            
            if not inspections:
                # Show message if no inspections found
                no_data_label = QtWidgets.QLabel("No previous inspections found")
                no_data_label.setStyleSheet("color: #64748b; font-size: 14px; font-weight: 600;")
                no_data_label.setAlignment(AlignCenter)
                self.prev_grid_layout.addWidget(no_data_label, 0, 0)
                self._update_prev_stats({})
                return
            
            # Calculate statistics
            total = len(inspections)
            good = sum(1 for item in inspections if not item.get("is_ng", True))
            bad = total - good
            ratio = (bad / total * 100) if total > 0 else 0
            
            # Update statistics
            self._update_prev_stats({
                "total": total,
                "good": good,
                "bad": bad,
                "ratio": ratio,
                "last_time": inspections[0].get("inspection_datetime") if inspections else None,
                "cam_count": len(set(item.get("cam_index", 0) for item in inspections))
            })
            
            # Display images in grid (4 columns)
            cols = 4
            for i, inspection in enumerate(inspections):
                row = i // cols
                col = i % cols
                
                item_widget = PrevInspectionItem(inspection)
                self.prev_grid_layout.addWidget(item_widget, row, col)
            
            # Add empty cells if needed for proper grid alignment
            items_count = len(inspections)
            if items_count % cols != 0:
                for col in range(items_count % cols, cols):
                    self.prev_grid_layout.addWidget(QtWidgets.QWidget(), items_count // cols, col)
                    
        except Exception as e:
            print(f"[prev] Error loading previous inspections: {e}")
            error_label = QtWidgets.QLabel(f"Error loading data: {str(e)}")
            error_label.setStyleSheet("color: #ef4444; font-size: 12px;")
            error_label.setAlignment(AlignCenter)
            self.prev_grid_layout.addWidget(error_label, 0, 0)

    def start_manual_capture_mode(self):
        """
        NEW MANUAL FLOW (for Start Capture):

          1) Ask to capture GOOD image
          2) Ask to capture BAD image
          3) Ask for threshold value
          4) Run template matching(GOOD, BAD, threshold)
        """
        # Ensure window is visible and focused
        self.showMaximized()
        self.raise_()
        self.activateWindow()

        QtCore.QTimer.singleShot(50, self._start_manual_capture_mode_actual)

    def _start_manual_capture_mode_actual(self):
        # 1) Check cameras
        try:
            devs = hik_capture.list_devices()
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Camera Error", f"Failed to list Hikrobot devices:\n{e}"
            )
            return

        if not devs:
            QtWidgets.QMessageBox.critical(
                self, "No Cameras",
                "No Hikrobot cameras detected for manual capture."
            )
            return

        # For template matching we will use ONLY the first camera
        cam_index = devs[0].index

        # Prepare single card for display
        self._build_cards(1)
        self.has_results = False
        self.good = 0
        self.bad = 0
        self._last_is_ng = None
        self._refresh_summary()

        # ---------------- STEP 1: CAPTURE GOOD IMAGE ----------------
        reply_good = QtWidgets.QMessageBox.question(
            self,
            "Capture GOOD Image",
            "Step 1/3:\n\nPlace a GOOD tyre and focus the camera.\n\n"
            "Click 'Yes' to CAPTURE the GOOD image.\n"
            "Click 'No' to cancel.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if reply_good != QtWidgets.QMessageBox.Yes:
            return

        good_img_path = self._capture_one_image_for_template(cam_index, mode="good")
        if not good_img_path:
            QtWidgets.QMessageBox.warning(self, "Capture failed", "Could not capture GOOD image.")
            return

        # Show GOOD image in the card (optional)
        if self.cards:
            self.cards[0].set_image(good_img_path)

        # ---------------- STEP 2: CAPTURE BAD IMAGE ----------------
        reply_bad = QtWidgets.QMessageBox.question(
            self,
            "Capture BAD Image",
            "Step 2/3:\n\nNow place a BAD tyre and focus the camera.\n\n"
            "Click 'Yes' to CAPTURE the BAD image.\n"
            "Click 'No' to cancel.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if reply_bad != QtWidgets.QMessageBox.Yes:
            return

        bad_img_path = self._capture_one_image_for_template(cam_index, mode="bad")
        if not bad_img_path:
            QtWidgets.QMessageBox.warning(self, "Capture failed", "Could not capture BAD image.")
            return

        # ---------------- STEP 3: ASK THRESHOLD ----------------
        threshold, ok_thr = QtWidgets.QInputDialog.getDouble(
            self,
            "Template Threshold",
            "Step 3/3:\n\nEnter similarity threshold (0–1):\n"
            "Blocks with similarity <= threshold are treated as DEFECT.",
            0.9999996,   # default, you can change
            0.0,
            1.0,
            7            # decimals
        )
        if not ok_thr:
            return

        # ---------------- STEP 4: RUN TEMPLATE MATCHING ----------------
        try:
            overall_sim, overlay_path, decision = self._run_good_bad_template_matching_ui(
                good_img_path, bad_img_path, threshold
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Template Matching Error",
                f"Error during template matching:\n{e}"
            )
            return

        # Update UI with overlay + GOOD/NG decision
        if self.cards and overlay_path:
            self.cards[0].set_image(overlay_path)

        # Use the returned decision flag
        is_ng = (decision.upper() == "BAD")

        self.good = 0
        self.bad = 0
        if is_ng:
            self.bad = 1
            self.cards[0].set_ng()
        else:
            self.good = 1
            self.cards[0].set_good()

        self._last_is_ng = is_ng
        self.has_results = True
        self._refresh_summary()

        QtWidgets.QMessageBox.information(
            self,
            "Manual Template Matching",
            f"Done.\n\nOverall similarity: {overall_sim:.10f}\n"
            f"Threshold: {threshold:.10f}\n"
            f"Result: {'NG (Defect)' if is_ng else 'GOOD'}"
        )
    
    def _capture_one_image_for_template(self, cam_index: int, mode: str = "good") -> str:
        """
        Synchronous helper to capture exactly ONE image from a Hikrobot camera
        using hik_capture.capture_multi.

        mode: 'good' or 'bad' -> used for filename prefix.
        Returns saved image path, or "" on failure.
        """
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            out_dir = os.path.join(base_dir, "captures_template")
            os.makedirs(out_dir, exist_ok=True)

            saved_path = {"p": ""}

            def _cb(c_idx, frame_i, path):
                # callback from hik_capture.capture_multi
                saved_path["p"] = path

            # Get exposure/gain overrides
            ov = self._mvs_overrides.get(cam_index) if hasattr(self, "_mvs_overrides") else None
            exposure = float(ov["ExposureTime"]) if ov and "ExposureTime" in ov else None
            gain = float(ov["Gain"]) if ov and "Gain" in ov else None

            # Capture the image
            hik_capture.capture_multi(
                indices=[cam_index],
                frames=1,
                base_out=out_dir,
                mirror=False,
                exposure_us=exposure,
                gain_db=gain,
                progress_cb=_cb,
            )

            # Rename the captured file with mode prefix
            if saved_path["p"]:
                old_path = Path(saved_path["p"])
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_name = f"{mode}_{ts}.png"
                new_path = old_path.parent / new_name
                
                try:
                    old_path.rename(new_path)
                    saved_path["p"] = str(new_path)
                except Exception as rename_error:
                    print(f"[template-capture] rename error: {rename_error}")
                    # Keep original path if rename fails

            return saved_path["p"]
        except Exception as e:
            print(f"[template-capture] error: {e}")
            return ""



    # def start_manual_capture_mode(self):
    #     """
    #     Setup manual one-shot capture mode:
    #     - Ask YOLO/Detectron, weights, num_cams (like live mode)
    #     - Build cards and dev_map
    #     - Enable Capture button
    #     """
    #     # Ensure window is visible and focused
    #     self.showMaximized()
    #     self.raise_()
    #     self.activateWindow()

    #     QtCore.QTimer.singleShot(50, self._start_manual_capture_mode_actual)

    # def _start_manual_capture_mode_actual(self):
    #     # 1) List cameras
    #     try:
    #         devs = hik_capture.list_devices()
    #     except Exception as e:
    #         QtWidgets.QMessageBox.critical(
    #             self, "Camera Error", f"Failed to list Hikrobot devices:\n{e}"
    #         )
    #         return

    #     if not devs:
    #         QtWidgets.QMessageBox.critical(
    #             self, "No Cameras",
    #             "No Hikrobot cameras detected for manual capture."
    #         )
    #         return

    #     n_max = min(8, len(devs))

    #     # 2) Ask backend / weights / num_cams with same dialog as live mode
    #     dlg = LiveConfigDialog(max_cams=n_max, parent=self)
    #     dlg.setWindowModality(QtCore.Qt.ApplicationModal)
    #     result = dlg.exec() if PYQT6 else dlg.exec_()

    #     # refocus main window
    #     self.raise_()
    #     self.activateWindow()

    #     if result != QtWidgets.QDialog.Accepted:
    #         return

    #     cfg = dlg.get_values()
    #     backend     = cfg["backend"]
    #     weights     = cfg["weights"]
    #     num_cams    = cfg["num_cams"]
    #     num_classes = cfg["num_classes"]

    #     # 3) Save inference config (NO continuous capture)
    #     self._infer_cfg["backend"]     = backend
    #     self._infer_cfg["weights"]     = weights
    #     self._infer_cfg["num_classes"] = num_classes
    #     self._infer_cfg["device"]      = "cuda"  # Inference.py will fall back if needed

    #     # (If you also applied the results/ trial logic, you can call _prepare_run_dirs() here)
    #     # self._prepare_run_dirs()

    #     self.lblInspVal.setText(f"{backend.upper()} (MANUAL)")

    #     # 4) Choose first N devices
    #     cam_indices = [d.index for d in devs[:num_cams]]
    #     self._single_cap_cam_indices = cam_indices
    #     self._single_capture_mode = True

    #     # 5) Build cards and dev map ONCE
    #     self._build_cards(num_cams)
    #     self._dev_map = {cam_idx: i for i, cam_idx in enumerate(cam_indices)}
    #     self.has_results = True
    #     self._reset_counters(soft=False)

    #     # 6) Enable Capture button
    #     self.btnCapture.setEnabled(True)
    # def _manual_capture_trigger(self):
    #     """
    #     Called when the sidebar 'Capture' button is pressed.
    #     Capture exactly 1 frame per selected camera, run inference,
    #     and update UI. Then wait for next press.
    #     """
    #     if not self._single_capture_mode or not self._single_cap_cam_indices:
    #         QtWidgets.QMessageBox.warning(
    #             self, "Manual Capture",
    #             "Manual capture mode is not configured. Use 'Start Capture' in main UI."
    #         )
    #         return

    #     # Start one-shot CaptureWorker
    #     self._start_manual_capture_worker()

    # def _start_manual_capture_worker(self):
    #     cam_indices = self._single_cap_cam_indices
    #     if not cam_indices:
    #         return

    #     base_dir = os.path.dirname(os.path.abspath(__file__))
    #     out_dir  = os.path.join(base_dir, "captures")
    #     os.makedirs(out_dir, exist_ok=True)

    #     # Build per-camera exposure/gain maps from overrides, like _make_capture_bridge
    #     exp_map: dict[int, float] = {}
    #     gain_map: dict[int, float] = {}
    #     for cam_idx in cam_indices:
    #         ov = self._mvs_overrides.get(cam_idx) if hasattr(self, "_mvs_overrides") else None
    #         if not ov:
    #             continue
    #         if "ExposureTime" in ov:
    #             exp_map[cam_idx] = float(ov["ExposureTime"])
    #         if "Gain" in ov:
    #             gain_map[cam_idx] = float(ov["Gain"])

    #     # New thread & worker for ONE frame per camera
    #     self._cap_thread = QtCore.QThread(self)
    #     self._cap_worker = CaptureWorker(
    #         cam_indices,
    #         frames=1,          # <--- important: ONE frame per cam per click
    #         out_dir=out_dir,
    #         mirror=False,
    #         exposure_map=exp_map,
    #         gain_map=gain_map,
    #     )
    #     self._cap_worker.moveToThread(self._cap_thread)

    #     self._cap_thread.started.connect(self._cap_worker.run)
    #     self._cap_worker.frameCaptured.connect(self._on_frame_captured_and_enqueue)
    #     self._cap_worker.error.connect(self._on_capture_error)
    #     self._cap_worker.cycleTick.connect(self._on_cycle_tick)
    #     self._cap_worker.finished.connect(self._on_capture_finished)
    #     self._cap_worker.finished.connect(self._cap_thread.quit)
    #     self._cap_worker.finished.connect(self._cap_worker.deleteLater)
    #     self._cap_thread.finished.connect(self._cap_thread.deleteLater)

    #     self._cap_thread.start()

    def _run_good_bad_template_matching_ui(self, good_img_path: str, bad_img_path: str, threshold: float):
        """
        Thin wrapper around offline GEFS/SEFS template matching.

        Uses run_good_bad_template_matching(...) from gefs_template_offline.py.
        Returns:
            overall_similarity (float),
            overlay_path (str),
            decision (str: 'GOOD' or 'BAD')
        """
        overall_sim, overlay_path, decision = run_good_bad_template_matching(
            good_img_path=good_img_path,
            bad_img_path=bad_img_path,
            threshold=threshold,
        )
        return overall_sim, overlay_path, decision


    def _prepare_run_dirs(self):
        """
        Create results/<backend>_op/trial_xxx and results/<backend>_ip/trial_xxx
        and store them in self._infer_cfg["out_dir"] (op) and ["ip_dir"] (ip).
        """
        base_dir = _app_base_dir()  # respects PyInstaller / _MEIPASS
        results_root = base_dir / "results"

        backend = (self._infer_cfg.get("backend") or "yolo").lower()
        if backend == "detectron":
            prefix = "detec"
        else:
            prefix = "yolo"

        op_root = results_root / f"{prefix}_op"
        ip_root = results_root / f"{prefix}_ip"
        op_root.mkdir(parents=True, exist_ok=True)
        ip_root.mkdir(parents=True, exist_ok=True)

        # Find next trial number from op_root
        max_n = 0
        for d in op_root.iterdir():
            if not d.is_dir():
                continue
            name = d.name
            try:
                if name.startswith("trial_"):
                    n = int(name.split("_", 1)[1])
                else:
                    n = int(name)
                max_n = max(max_n, n)
            except ValueError:
                continue

        next_n = max_n + 1
        trial_name = f"trial_{next_n:03d}"

        op_trial = op_root / trial_name
        ip_trial = ip_root / trial_name
        op_trial.mkdir(parents=True, exist_ok=True)
        ip_trial.mkdir(parents=True, exist_ok=True)

        self._infer_cfg["out_dir"] = str(op_trial)
        self._infer_cfg["ip_dir"] = str(ip_trial)

    def _handle_template_creation(self):
        """
        When user clicks 'Template Creation' on Anomaly page:

        • Use the CURRENT anomaly preview frame (self._anomaly_last_frame)
        • Save that frame as GOOD template in templates/good
        • In parallel, save the SAME image into templates/Exist
        • Freeze the preview on that image (show the captured GOOD image)
        • DON'T show popup (silently save)
        """

        if self._anomaly_last_frame is None:
            QtWidgets.QMessageBox.warning(
                self,
                "No Preview Frame",
                "No live preview frame is available.\n\n"
                "Please ensure the anomaly live preview is visible, then click Template Creation again."
            )
            return

        base_dir = _app_base_dir()

        # 🔹 Folders: templates/good and templates/Exist
        tmpl_root = base_dir / "templates"
        tmpl_dir = tmpl_root / "good"
        exist_dir = tmpl_root / "Exist"

        tmpl_dir.mkdir(parents=True, exist_ok=True)
        exist_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        good_path = tmpl_dir / f"good_{ts}.png"
        exist_path = exist_dir / f"good_{ts}.png"

        img = self._anomaly_last_frame  # numpy array (grayscale)

        # Save to GOOD
        ok_good = cv2.imwrite(str(good_path), img)
        if not ok_good:
            QtWidgets.QMessageBox.critical(
                self,
                "Save Error",
                f"Failed to save GOOD template to:\n{good_path}"
            )
            return

        # Save to templates/Exist
        ok_exist = cv2.imwrite(str(exist_path), img)
        
        self._last_good_template_path = str(good_path)

        self._stop_anomaly_preview()

        # ----- Convert captured image to QPixmap and display it -----
        # Convert numpy array to QPixmap directly without saving/loading
        height, width = img.shape
        bytes_per_line = width
        qimg = QtGui.QImage(
            img.data,
            width,
            height,
            bytes_per_line,
            QtGui.QImage.Format_Grayscale8
        ).copy()  # Important: copy the data
        
        pm = QtGui.QPixmap.fromImage(qimg)
        
        if not pm.isNull():
            # Scale to fit the preview label
            pm = pm.scaled(
                self.anomalyPreviewLabel.size(),
                KeepAspect,
                Smooth
            )
            # Show the captured GOOD image
            self.anomalyPreviewLabel.setPixmap(pm)
            self.anomalyPreviewLabel.setText("")
            
            # ----- Show temporary success message as overlay -----
            # Create a semi-transparent overlay with success message
            overlay_pixmap = pm.copy()
            painter = QtGui.QPainter(overlay_pixmap)
            
            # Draw semi-transparent background for text
            painter.setBrush(QtGui.QColor(0, 0, 0, 180))  # Black with transparency
            painter.setPen(QtCore.Qt.NoPen)
            
            # Text rectangle (centered)
            text_rect = QtCore.QRect(0, 0, overlay_pixmap.width(), 50)
            text_rect.moveCenter(QtCore.QPoint(overlay_pixmap.width() // 2, 
                                            overlay_pixmap.height() // 2))
            painter.drawRect(text_rect)
            
            # Draw success text
            painter.setPen(QtGui.QColor(34, 197, 94))  # Green color
            font = painter.font()
            font.setPointSize(14)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(text_rect, QtCore.Qt.AlignCenter, "✓ Template Saved")
            
            painter.end()
            
            # Show the image with overlay
            self.anomalyPreviewLabel.setPixmap(overlay_pixmap)
            
            # Clear overlay after 1.5 seconds, keep showing the GOOD image
            QtCore.QTimer.singleShot(1500, lambda: self.anomalyPreviewLabel.setPixmap(pm))
            
        else:
            # Fallback if pixmap creation fails
            self.anomalyPreviewLabel.setText("Template saved ✓")
            # Clear text after 2 seconds
            QtCore.QTimer.singleShot(2000, lambda: self.anomalyPreviewLabel.setText(""))


    def _handle_anomaly_detection(self):
        """
        MODIFIED: Skip BAD image capture popup, directly capture and ask for threshold.
        Also removed final result popup.
        """

        # -------- 1) Check if camera is available --------
        try:
            devs = hik_capture.list_devices()
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Camera Error",
                f"Failed to list Hikrobot devices:\n{e}"
            )
            return

        if not devs:
            QtWidgets.QMessageBox.critical(
                self,
                "No Camera",
                "No Hikrobot camera detected for capturing BAD image."
            )
            return

        # Use first camera
        cam_index = devs[0].index

        # -------- 2) Stop live preview BEFORE capture --------
        self._stop_anomaly_preview()  # <--- ADD THIS LINE
        
        # -------- 3) Directly capture BAD image --------
        self.anomalyPreviewLabel.setText("Capturing BAD image...")
        QtWidgets.QApplication.processEvents()  # Update UI

        bad_img_path = self._capture_one_image_for_template(cam_index, mode="bad")
        if not bad_img_path:
            # Restart preview if capture failed
            self._start_anomaly_preview()  # <--- ADD THIS LINE
            QtWidgets.QMessageBox.warning(
                self, 
                "Capture failed", 
                "Could not capture BAD image."
            )
            return

        # Show captured BAD image temporarily
        try:
            pm = QtGui.QPixmap(bad_img_path)
            if not pm.isNull():
                pm = pm.scaled(
                    self.anomalyPreviewLabel.size(),
                    KeepAspect,
                    Smooth
                )
                self.anomalyPreviewLabel.setPixmap(pm)
        except Exception:
            pass

        # -------- 4) Save BAD image to templates/bad folder --------
        base_dir = _app_base_dir()
        bad_dir = Path(base_dir) / "templates" / "bad"
        bad_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bad_final_path = bad_dir / f"bad_{ts}.png"

        try:
            # Copy the captured image to templates/bad
            shutil.copy2(bad_img_path, bad_final_path)
            bad_img_path = str(bad_final_path)  # Use the new path
        except Exception as e:
            # Continue with original captured path even if save fails
            pass

        # -------- 5) Check for GOOD template --------
        good_dir = Path(base_dir) / "templates" / "good"
        good_path = self._get_latest_image_in_folder(good_dir)

        if not good_path:
            # Restart preview if no template
            self._start_anomaly_preview()  # <--- ADD THIS LINE
            QtWidgets.QMessageBox.warning(
                self,
                "No GOOD Template",
                "No GOOD template image found in:\n"
                f"{good_dir}\n\n"
                "Please create a GOOD template first using 'Template Creation'."
            )
            return

        # -------- 6) Ask for similarity threshold --------
        threshold, ok_thr = QtWidgets.QInputDialog.getDouble(
            self,
            "Template Threshold",
            "Enter similarity threshold (0–1):\n"
            "Blocks with similarity <= threshold are treated as DEFECT.",
            0.9999995,   # default
            0.0,
            1.0,
            7            # decimals
        )
        if not ok_thr:
            # Restart preview if cancelled
            self._start_anomaly_preview()  # <--- ADD THIS LINE
            return

        # -------- 7) Show processing message --------
        self.anomalyPreviewLabel.setText("Processing...")
        QtWidgets.QApplication.processEvents()  # Update UI

        # -------- 8) Run GEFS/SEFS template matching --------
        try:
            overall_sim, overlay_path, decision = self._run_good_bad_template_matching_ui(
                good_path,
                bad_img_path,  # Use the captured BAD image
                threshold
            )
        except Exception as e:
            # Restart preview if error
            self._start_anomaly_preview()  # <--- ADD THIS LINE
            QtWidgets.QMessageBox.critical(
                self,
                "Anomaly Detection Error",
                f"Error during anomaly detection:\n{e}"
            )
            return

        # -------- 9) Save result into templates/output --------
        out_dir = Path(base_dir) / "templates" / "output"
        out_dir.mkdir(parents=True, exist_ok=True)

        final_overlay_path = None
        try:
            if overlay_path and os.path.isfile(overlay_path):
                # Copy overlay to output folder with timestamped name
                dest_overlay = out_dir / f"overlay_{ts}.png"
                shutil.copy2(overlay_path, dest_overlay)
                final_overlay_path = str(dest_overlay)
            else:
                # Fallback: if no overlay, copy BAD image
                dest_overlay = out_dir / f"overlay_{ts}.png"
                shutil.copy2(bad_img_path, dest_overlay)
                final_overlay_path = str(dest_overlay)
        except Exception as e:
            print("[anomaly] failed to store overlay in output:", e)
            # Use whatever overlay we got
            if overlay_path and os.path.isfile(overlay_path):
                final_overlay_path = overlay_path
            else:
                final_overlay_path = bad_img_path

        # -------- 10) Show overlay in anomaly preview --------
        try:
            pm = QtGui.QPixmap(final_overlay_path)
            if not pm.isNull():
                pm = pm.scaled(
                    self.anomalyPreviewLabel.size(),
                    KeepAspect,
                    Smooth
                )
                self.anomalyPreviewLabel.setPixmap(pm)
                self.anomalyPreviewLabel.setText("")
                
                # ----- Show brief status message on the image -----
                # Create a copy to draw on
                status_pixmap = pm.copy()
                painter = QtGui.QPainter(status_pixmap)
                
                # Draw semi-transparent status bar at bottom
                status_height = 40
                status_rect = QtCore.QRect(0, pm.height() - status_height, pm.width(), status_height)
                painter.setBrush(QtGui.QColor(0, 0, 0, 180))
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawRect(status_rect)
                
                # Draw result text
                is_ng = decision.upper() == "BAD"
                color = QtGui.QColor(239, 68, 68) if is_ng else QtGui.QColor(34, 197, 94)  # Red for NG, Green for GOOD
                painter.setPen(color)
                font = painter.font()
                font.setPointSize(12)
                font.setBold(True)
                painter.setFont(font)
                
                result_text = f"{decision} | Similarity: {overall_sim:.6f}"
                painter.drawText(status_rect, QtCore.Qt.AlignCenter, result_text)
                painter.end()
                
                # Show image with status
                self.anomalyPreviewLabel.setPixmap(status_pixmap)
                
                # Remove status after 3 seconds, keep showing the overlay
                QtCore.QTimer.singleShot(3000, lambda: self.anomalyPreviewLabel.setPixmap(pm))
                
                # DO NOT restart live preview timer here - keep showing the result!
                # The result will stay until user clicks "Clear" or switches tabs
            else:
                self.anomalyPreviewLabel.setPixmap(QtGui.QPixmap())
                self.anomalyPreviewLabel.setText("Overlay image could not be loaded.")
        except Exception as e:
            print("[anomaly] failed to show overlay:", e)
            self.anomalyPreviewLabel.setPixmap(QtGui.QPixmap())
            self.anomalyPreviewLabel.setText("Error showing overlay.")
            # Restart preview on error
            self._start_anomaly_preview()

        # -------- REMOVED: Show result summary popup -----
        # OLD CODE (COMMENTED):
        # QtWidgets.QMessageBox.information(
        #     self,
        #     "Anomaly Detection Result",
        #     (
        #         f"GOOD template : {os.path.basename(good_path)}\n"
        #         f"BAD image     : {os.path.basename(bad_img_path)}\n"
        #         f"Output folder : {out_dir}\n\n"
        #         f"Overall similarity : {overall_sim:.10f}\n"
        #         f"Threshold           : {threshold:.10f}\n"
        #         f"Result              : {decision}"
        #     )
        # )
    
    def _handle_anomaly_load(self):
        """
        Load-mode anomaly detection:

        - Take the LATEST GOOD image from templates/good
        - Ask user to select a BAD / defect image (via file dialog)
        - Ask for threshold
        - Run GEFS/SEFS template matching
        - Show overlay in anomaly preview + save to templates/output
        """
        from pathlib import Path

        base_dir = _app_base_dir()
        good_dir = Path(base_dir) / "templates" / "good"

        # 1) Get latest GOOD template
        good_path = self._get_latest_image_in_folder(good_dir)
        if not good_path:
            QtWidgets.QMessageBox.warning(
                self,
                "No GOOD Template",
                "No GOOD template image found in:\n"
                f"{good_dir}\n\n"
                "Please create a GOOD template first using 'Template Creation'."
            )
            return

        # 2) Ask user to choose BAD / defect image
        start_dir = str(Path(base_dir) / "templates")
        bad_img_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select BAD / Defect Image",
            start_dir,
            "Image Files (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;All Files (*)"
        )

        # Bring main window back to front after dialog
        self.raise_()
        self.activateWindow()

        if not bad_img_path:
            # User cancelled
            return

        # 3) Ask for similarity threshold
        threshold, ok_thr = QtWidgets.QInputDialog.getDouble(
            self,
            "Template Threshold",
            "Enter similarity threshold (0–1):\n"
            "Blocks with similarity <= threshold are treated as DEFECT.",
            0.9999995,   # default
            0.0,
            1.0,
            7            # decimals
        )
        if not ok_thr:
            return

        # 4) Show 'Processing...' while running anomaly
        self.anomalyPreviewLabel.setText("Processing...")
        QtWidgets.QApplication.processEvents()

        # 5) Run template matching (using existing wrapper)
        try:
            overall_sim, overlay_path, decision = self._run_good_bad_template_matching_ui(
                good_img_path=good_path,
                bad_img_path=bad_img_path,
                threshold=threshold,
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Anomaly Detection Error",
                f"Error during anomaly detection:\n{e}"
            )
            return

        # 6) Save overlay into templates/output
        out_dir = Path(base_dir) / "templates" / "output"
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        final_overlay_path = None

        try:
            if overlay_path and os.path.isfile(overlay_path):
                dest_overlay = out_dir / f"overlay_{ts}.png"
                shutil.copy2(overlay_path, dest_overlay)
                final_overlay_path = str(dest_overlay)
            else:
                # Fallback: copy BAD image if no overlay produced
                dest_overlay = out_dir / f"overlay_{ts}.png"
                shutil.copy2(bad_img_path, dest_overlay)
                final_overlay_path = str(dest_overlay)
        except Exception as e:
            print("[anomaly load] failed to store overlay:", e)
            if overlay_path and os.path.isfile(overlay_path):
                final_overlay_path = overlay_path
            else:
                final_overlay_path = bad_img_path

        # 7) Show overlay + status bar text in the anomaly preview
        try:
            pm = QtGui.QPixmap(final_overlay_path)
            if not pm.isNull():
                pm = pm.scaled(
                    self.anomalyPreviewLabel.size(),
                    KeepAspect,
                    Smooth
                )
                # Base overlay
                self.anomalyPreviewLabel.setPixmap(pm)
                self.anomalyPreviewLabel.setText("")

                # Draw status strip on a copy
                status_pixmap = pm.copy()
                painter = QtGui.QPainter(status_pixmap)

                status_height = 40
                status_rect = QtCore.QRect(
                    0,
                    pm.height() - status_height,
                    pm.width(),
                    status_height
                )

                painter.setBrush(QtGui.QColor(0, 0, 0, 180))
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawRect(status_rect)

                is_ng = decision.upper() == "BAD"
                color = QtGui.QColor(239, 68, 68) if is_ng else QtGui.QColor(34, 197, 94)
                painter.setPen(color)
                font = painter.font()
                font.setPointSize(12)
                font.setBold(True)
                painter.setFont(font)

                result_text = f"{decision} | Similarity: {overall_sim:.6f}"
                painter.drawText(status_rect, QtCore.Qt.AlignCenter, result_text)
                painter.end()

                # Show image with status text
                self.anomalyPreviewLabel.setPixmap(status_pixmap)

                # After 3s, keep only the plain overlay (no bar)
                QtCore.QTimer.singleShot(
                    3000,
                    lambda: self.anomalyPreviewLabel.setPixmap(pm)
                )
            else:
                self.anomalyPreviewLabel.setPixmap(QtGui.QPixmap())
                self.anomalyPreviewLabel.setText("Overlay image could not be loaded.")
        except Exception as e:
            print("[anomaly load] failed to show overlay:", e)
            self.anomalyPreviewLabel.setPixmap(QtGui.QPixmap())
            self.anomalyPreviewLabel.setText("Error showing overlay.")


    def _handle_synthetic_defect(self):
        """
        Run synthetic defect creation process.
        """
        try:
            # Import the synthetic defect creation module
            try:
                # Adjust the path based on where generate_induce.py is located
                import sys
                import os
                current_dir = os.path.dirname(os.path.abspath(__file__))
                sys.path.append(current_dir)
                
                from generate_induce import run_synthetic_defect_creation
                
            except ImportError as e:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Import Error",
                    f"Cannot import synthetic defect module:\n{e}"
                )
                return
            
            # Run the synthetic defect creation
            success, message = run_synthetic_defect_creation(self)
            
            if not success:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Synthetic Defect Creation",
                    message
                )
                
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Error in synthetic defect creation:\n{e}"
            )

    def _handle_anomaly_clear(self):
        """
        Clear anomaly result and go back to LIVE PREVIEW
        inside the ANOMALY page only.
        - Does NOT switch to Live Inspection tab
        - Does NOT touch good/bad counts
        """
        # 1) Clear current image & text
        self.anomalyPreviewLabel.clear()
        self.anomalyPreviewLabel.setText("Live preview will appear here")

        # Reset last captured frame (template stays as-is)
        self._anomaly_last_frame = None

        # 2) Restart live preview timer ONLY for anomaly page
        self._start_anomaly_preview()


    def _update_prev_stats(self, stats: dict):
        """Update the statistics display in the previous inspection page."""
        total = stats.get("total", 0)
        good = stats.get("good", 0)
        bad = stats.get("bad", 0)
        ratio = stats.get("ratio", 0.0)
        last_time = stats.get("last_time")
        cam_count = stats.get("cam_count", 0)
        
        self.prev_total_label.setText(str(total))
        self.prev_good_label.setText(str(good))
        self.prev_bad_label.setText(str(bad))
        self.prev_ratio_label.setText(f"{ratio:.1f}%" if ratio > 0 else "0%")
        self.prev_cam_count.setText(str(cam_count))
        
        if last_time:
            if isinstance(last_time, datetime):
                time_str = last_time.strftime("%H:%M:%S")
            else:
                # Try to parse string datetime
                try:
                    dt = datetime.fromisoformat(str(last_time).replace('Z', '+00:00'))
                    time_str = dt.strftime("%H:%M:%S")
                except:
                    time_str = str(last_time)[11:19] if len(str(last_time)) > 19 else "??:??:??"
            self.prev_last_time.setText(time_str)
        else:
            self.prev_last_time.setText("—")
    def _start_anomaly_preview(self):
        """Start periodic camera preview updates on the anomaly page."""
        if self.anomaly_timer.isActive():
            return

        # If live capture is not running, pick a camera index for direct grab
        if not self._capture_running:
            try:
                devs = hik_capture.list_devices()
            except Exception as e:
                print(f"[anomaly] list_devices error: {e}")
                devs = []

            if devs:
                # use first camera for preview
                self._anomaly_cam_index = devs[0].index
            else:
                self._anomaly_cam_index = None

        # Do one immediate update and then start timer
        self._update_anomaly_preview()
        self.anomaly_timer.start(1000)  # 1 second refresh

    def _stop_anomaly_preview(self):
        """Stop anomaly preview timer."""
        if self.anomaly_timer.isActive():
            self.anomaly_timer.stop()

    def _update_anomaly_preview(self):
        """Update the anomaly preview label with the latest camera image and
        remember it for template creation.
        """
        # Case 1: live capture is running – reuse the first card's current pixmap
        if self._capture_running and self.cards:
            card = self.cards[0]
            pm = card.image.pixmap()
            if pm and not pm.isNull():
                # Scale for display
                scaled = pm.scaled(
                    self.anomalyPreviewLabel.size(),
                    KeepAspect,
                    Smooth
                )
                self.anomalyPreviewLabel.setPixmap(scaled)
                self.anomalyPreviewLabel.setText("")

                # Store as grayscale numpy for template saving
                qimg = pm.toImage().convertToFormat(QtGui.QImage.Format_Grayscale8)
                w = qimg.width()
                h = qimg.height()
                ptr = qimg.bits()
                ptr.setsize(h * qimg.bytesPerLine())
                arr = np.frombuffer(ptr, np.uint8).reshape((h, qimg.bytesPerLine()))
                self._anomaly_last_frame = arr[:, :w].copy()

                return

        # Case 2: standalone one-shot grab from camera using hik_capture
        cam_idx = self._anomaly_cam_index
        if cam_idx is None:
            # Try to discover a camera lazily
            try:
                devs = hik_capture.list_devices()
            except Exception as e:
                print(f"[anomaly] list_devices error (lazy): {e}")
                devs = []
            if not devs:
                self.anomalyPreviewLabel.setText("No camera detected")
                self.anomalyPreviewLabel.setPixmap(QtGui.QPixmap())
                self._anomaly_last_frame = None
                return
            cam_idx = devs[0].index
            self._anomaly_cam_index = cam_idx

        # Pull exposure/gain overrides if we have them
        exposure = gain = None
        try:
            ov = self._mvs_overrides.get(cam_idx) if hasattr(self, "_mvs_overrides") else None
            if ov:
                if "ExposureTime" in ov:
                    exposure = float(ov["ExposureTime"])
                if "Gain" in ov:
                    gain = float(ov["Gain"])
        except Exception as e:
            print(f"[anomaly] override read error: {e}")

        try:
            frame = hik_capture.grab_live_frame(
                index=cam_idx,
                exposure_us=exposure,
                gain_db=gain,
                mirror=False,
            )
        except Exception as e:
            print(f"[anomaly] grab_live_frame error: {e}")
            frame = None

        if frame is None:
            self.anomalyPreviewLabel.setText("Camera preview not available")
            self.anomalyPreviewLabel.setPixmap(QtGui.QPixmap())
            self._anomaly_last_frame = None
            return

        # frame is a numpy (H, W) grayscale array
        self._anomaly_last_frame = frame.copy()

        h, w = frame.shape[:2]
        qimg = QtGui.QImage(
            frame.data,
            w,
            h,
            w,  # bytes per line for 8-bit grayscale
            QtGui.QImage.Format_Grayscale8,
        ).copy()

        pm = QtGui.QPixmap.fromImage(qimg)
        pm = pm.scaled(
            self.anomalyPreviewLabel.size(),
            KeepAspect,
            Smooth
        )
        self.anomalyPreviewLabel.setPixmap(pm)
        self.anomalyPreviewLabel.setText("")


    def apply_theme(self):
        # Apply live UI theme
        self.setStyleSheet(LIVE_QSS)
        self._update_big_status()


    def _prompt_cameras(self, initial: bool = False):
        settings = QtCore.QSettings("Live_ui", "layout")
        prev = int(settings.value("num_cameras", 8))
        num, ok = QtWidgets.QInputDialog.getInt(
            self, "Camera Configuration",
            "How many camera cards to display?",
            prev, 1, 8, 1   # <-- up to 8
        )
        if not ok and initial:
            num = max(1, min(prev, 8))
        elif not ok:
            return
        settings.setValue("num_cameras", num)
        self._build_cards(num)

    def _build_cards(self, n: int):
        for i in reversed(range(self.grid.count())):
            item = self.grid.itemAt(i)
            w = item.widget()
            if w: w.setParent(None)
        self.cards.clear()

        # 4 columns when >4, else n columns
        cols = 4 if n > 4 else n
        row = col = 0
        for cam_id in range(1, n + 1):
            card = CardWidget(cam_id)
            self.grid.addWidget(card, row, col, 1, 1)
            self.cards.append(card)
            col += 1
            if col >= cols:
                col = 0
                row += 1

    def _reset_counters(self, soft: bool = False):
        # soft=True doesn't prompt; it just clears numbers and status
        self.good = 0
        self.bad = 0
        self._last_is_ng = None  
        if not soft:
            for c in self.cards: c.clear()
        self.has_results = False
        self._refresh_summary()

    # ---- summary & status ----
    def _refresh_summary(self):
        total = self.good + self.bad
        ratio = (self.bad / total * 100.0) if total else 0.0

        self.lblGoodVal.setText(str(self.good))
        self.lblBadVal.setText(str(self.bad))
        self.lblRatioVal.setText(f"{ratio:.2f}%")   # change to f"{int(ratio)}" if you want just "0"
        self.lblTotalVal.setText(str(total))

        self._update_big_status()

    def _init_counts_from_db(self):
        """
        On startup, pre-fill Good/Bad/Total from today's records in MongoDB.
        """
        try:
            agg = get_today_live_counts()
        except Exception as e:
            print(f"[live] could not fetch today's counts: {e}")
            return

        if not agg:
            return

        # ---- sidebar summary only ----
        self.good = int(agg.get("good", 0) or 0)
        self.bad  = int(agg.get("bad", 0) or 0)

        if self.good == 0 and self.bad == 0:
            self._last_is_ng = None
        else:
            self._last_is_ng = self.bad > 0

        self._refresh_summary()



    def _update_big_status(self):
        """
        Update the big GOOD / NG pill at the bottom-left.
        Only text + 'mode' property change; QSS handles colors.
        """
        if self._last_is_ng is None:
            self.bigStatus.setText("—")
            self.bigStatus.setProperty("mode", "neutral")
        elif self._last_is_ng:
            self.bigStatus.setText("NG")
            self.bigStatus.setProperty("mode", "ng")
        else:
            self.bigStatus.setText("GOOD")
            self.bigStatus.setProperty("mode", "good")

        self.bigStatus.style().unpolish(self.bigStatus)
        self.bigStatus.style().polish(self.bigStatus)
        self.bigStatus.update()




    # ---- actions ----
    def _reset_all(self):
        reply = QtWidgets.QMessageBox.question(
            self, "🔄 Reset Confirmation",
            "Reset all counts and clear images?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
            if PYQT6 else
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if reply == (QtWidgets.QMessageBox.StandardButton.Yes if PYQT6 else QtWidgets.QMessageBox.Yes):
            for c in self.cards: c.clear()
            self._reset_counters(soft=True)

    def _put_image(self):
        img_path = self._find_test_image()
        if not img_path:
            QtWidgets.QMessageBox.warning(
                self, "Image not found",
                "Place at least one image in a folder named 'test_image' next to this script."
            )
            return

        # 1) load same test image to all placeholders
        for c in self.cards:
            c.clear()            
            c.set_image(img_path)  

        # 2) testing purpose: assign some GOOD, some NG
        n = len(self.cards)
        idxs = list(range(n))
        random.shuffle(idxs)

        # split roughly half NG, half GOOD; ensure at least one of each if n>=2
        ng_count_target = max(1, n // 2) if n >= 2 else (1 if n == 1 else 0)
        ng_idxs = set(idxs[:ng_count_target])

        self.good = 0
        self.bad = 0
        for i, c in enumerate(self.cards):
            if i in ng_idxs:
                c.set_ng(); self.bad += 1
            else:
                c.set_good(); self.good += 1

        self.has_results = True
        self._refresh_summary()

    # ---- helpers ----
    def _ensure_yolo(self, weights: str):
        """
        Lazily create a UnifiedYOLOInferencer and cache it on self.
        Reuse the same model for all images to keep live latency low.
        """
        # If already loaded with same weights, reuse
        if getattr(self, "_yolo_infer", None) is not None and getattr(self, "_yolo_weights", None) == weights:
            return

        import Inference as infer

        # Prefer whatever device is in config; let Inference decide if None
        device = self._infer_cfg.get("device") or None

        # allow_cpu_fallback=True so it still works on machines without CUDA
        self._yolo_infer = infer.UnifiedYOLOInferencer(
            weights=weights,
            device=device,
            allow_cpu_fallback=True
        )
        self._yolo_weights = weights

    def _yolo_predict_and_save(self, image_path: str, out_dir: str):
        """
        Use cached YOLO model to run on a single image and save an overlay.
        Returns: (overlay_path, is_ng, score_text)
        """
        import os
        import cv2
        import Inference as infer  # to access draw_vis

        img = cv2.imread(image_path)
        if img is None:
            raise RuntimeError(f"Cannot read image: {image_path}")

        # Run YOLO (uses the cached self._yolo_infer)
        dets, _ = self._yolo_infer.predict_image(img)

        # Draw overlay
        vis = infer.draw_vis(img, dets)

        # Save under out_dir/images
        # Save directly under out_dir (which is results/<backend>_op/trial_xxx)
        os.makedirs(out_dir, exist_ok=True)
        save_p = os.path.join(out_dir, os.path.basename(image_path))
        cv2.imwrite(save_p, vis)

        # Simple NG logic: any detection => NG
        is_ng = len(dets) > 0

        # Build a human-readable score text for the UI
        if dets:
            top = max(dets, key=lambda d: d.get("conf", 0.0))
            cls_name = str(top.get("name", top.get("cls", "?")))
            conf = float(top.get("conf", 0.0))
            score_text = f"{cls_name} {conf:.2f}"
        else:
            score_text = "GOOD"

        return save_p, is_ng, score_text

    def _find_test_image(self) -> str | None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        test_dir = os.path.join(base_dir, "test_image")
        exts = ["*.png", "*.jpg", "*.jpeg", "*.bmp", "*.gif", "*.tif", "*.tiff", "*.webp"]
        candidates = []
        if os.path.isdir(test_dir):
            for ext in exts:
                candidates.extend(glob.glob(os.path.join(test_dir, ext)))
        # also allow a single file like test_image.png in base_dir
        for ext in [".png",".jpg",".jpeg",".bmp",".gif",".tif",".tiff",".webp"]:
            p = os.path.join(base_dir, f"test_image{ext}")
            if os.path.isfile(p): candidates.append(p)
        return candidates[0] if candidates else None
      
    def start_capture_flow(self):
        # 1) Ask for number of cameras
        devs = hik_capture.list_devices()
        if not devs:
            QtWidgets.QMessageBox.critical(self, "No Cameras", "No Hikrobot cameras detected.")
            return

        n_max = min(8, len(devs))
        num, ok = QtWidgets.QInputDialog.getInt(
            self, "Select Cameras", f"How many cameras? (Available: {len(devs)})",
            min(1, n_max), 1, n_max, 1
        )
        if not ok:
            return

        # auto-pick first N device indices
        cam_indices = [d.index for d in devs[:num]]

        # 2) Ask frames per camera
        frames, ok2 = QtWidgets.QInputDialog.getInt(
            self, "Frames", "Frames per camera:", 5, 1, 9999, 1
        )
        if not ok2:
            return

        # 3) Prepare UI grid for 'num' cameras
        self._build_cards(num)
        self.has_results = True
        self._refresh_summary()  # keeps counts neutral

        # 4) Choose output base dir (next to live.py: captures/)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        out_dir = os.path.join(base_dir, "captures")

        # 5) Launch worker thread
        self._cap_thread = QtCore.QThread(self)
        self._cap_worker = CaptureWorker(cam_indices, frames, out_dir, mirror=False)
        self._cap_worker.moveToThread(self._cap_thread)
        self._cap_thread.started.connect(self._cap_worker.run)
        self._cap_worker.frameCaptured.connect(self._on_frame_captured_and_enqueue)
        self._cap_worker.error.connect(self._on_capture_error)
        self._cap_worker.finished.connect(self._on_capture_finished)
        self._cap_worker.finished.connect(self._cap_thread.quit)
        self._cap_worker.finished.connect(self._cap_worker.deleteLater)
        self._cap_thread.finished.connect(self._cap_thread.deleteLater)
        self._cap_thread.start()
        QtWidgets.QMessageBox.information(self, "Capture", f"Capturing {frames} frame(s) from {num} camera(s).")

    @_pyqtSlot(int, int, str)  # cam_index, frame_index, img_path
    def _on_frame_captured_and_infer(self, cam_index: int, frame_index: int, img_path: str):
        if not img_path or not os.path.isfile(img_path):
            print("[infer] error: bad image path:", img_path)
            return
        if not self._infer_cfg.get("backend") or not self._infer_cfg.get("weights"):
            QtWidgets.QMessageBox.critical(self, "Inference Not Configured",
                "Backend/weights missing. Click Start Live again.")
            return
          
    @QtCore.pyqtSlot(int, int, str)  # cam_index, frame_idx, img_path
    def _on_frame_captured_and_enqueue(self, cam_index: int, frame_idx: int, img_path: str):
        if not img_path or not os.path.isfile(img_path):
            print("[capture] bad path:", img_path)
            return

        # DO NOT show raw image now – let inference decide what to show
        # Just queue for inference
        self._pending.append((cam_index, img_path))

        # Immediately try to start inference (if none currently running)
        self._kick_next_inference()



    def _on_capture_error(self, msg: str):
        QtWidgets.QMessageBox.critical(self, "Capture Error", msg)

    @QtCore.pyqtSlot()
    def _on_capture_finished(self):
        # start sequential inference over the queued images
        self._kick_next_inference()
        self._capture_running = False
    @QtCore.pyqtSlot(int, str, bool, str)
    def _apply_infer_result(self, cam_index: int, overlay_path: str, is_ng: bool, score_text: str):
        # ---------- UI update ----------
        card_idx = self._dev_map.get(cam_index, 0) if hasattr(self, "_dev_map") else cam_index
        card_idx = max(0, min(card_idx, len(self.cards) - 1))
        card = self.cards[card_idx] if self.cards else None
        
        if card:
            # show overlay image (final)
            card.set_image(overlay_path)
            
            # Update card status
            if is_ng:
                card.set_ng()
                self.bad += 1
            else:
                card.set_good()
                self.good += 1
            
            # ----- bottom labels -----
            try:
                # Status label: GOOD / BAD
                status_text = "BAD" if is_ng else "GOOD"
                card.b1.setText(f"Status: {status_text}")

                # Class label: fixed as Dimension
                card.b2.setText("Class: Dimension")

                # Score label: pretty numeric if possible
                try:
                    val = float(score_text)
                    card.score.setText(f"Score: {val:.2f}")
                except Exception:
                    card.score.setText(f"Score: {score_text}")
            except Exception:
                pass

        self._last_is_ng = bool(is_ng)
        self.has_results = True
        self._refresh_summary()

        # ---------- DB logging (live collection) ----------
        try:
            input_path = self._current_input.get(cam_index)

            # safely read full image bytes
            input_bytes = None
            output_bytes = None

            if input_path and os.path.isfile(input_path):
                with open(input_path, "rb") as f:
                    input_bytes = f.read()

            if overlay_path and os.path.isfile(overlay_path):
                with open(overlay_path, "rb") as f:
                    output_bytes = f.read()

            total = self.good + self.bad

            # parse classname + numeric score from score_text
            cls_name = None
            per_score = None
            if score_text:
                st = score_text.strip()

                # New format: just a number like "0.94"
                try:
                    val = float(st)
                    per_score = val
                    cls_name = "Dimension"
                except ValueError:
                    # Old formats: "GOOD" or "BAD 0.97"
                    if st.upper() == "GOOD":
                        cls_name = "GOOD"
                        per_score = 1.0
                    else:
                        parts = st.split()
                        if parts:
                            cls_name = parts[0]
                        if len(parts) >= 2:
                            try:
                                per_score = float(parts[1])
                            except ValueError:
                                per_score = None

            doc = {
                "cam_index": cam_index,
                "good_count": self.good,
                "bad_count": self.bad,
                "total_count": total,
                "cycle": self.cycle_count,
                "inspection_type": (self._infer_cfg.get("backend") or "").upper(),
                "score_text": score_text,
                "class_name": cls_name,
                "is_ng": bool(is_ng),
                "input_image": input_bytes,
                "output_image": output_bytes,
                "input_filename": os.path.basename(input_path) if input_path else None,
                "output_filename": os.path.basename(overlay_path) if overlay_path else None,
            }
            insert_live_record(doc)
        except Exception as e:
            print(f"[live] failed to insert live record: {e}")
        
        try:
            self._current_input.pop(cam_index, None)
        except Exception:
            pass

        # ---------- trigger next inference ----------
        self._inflight = False
        QtCore.QTimer.singleShot(0, self._kick_next_inference)
        
    def _prompt_infer_options(self) -> bool:
        # 1) backend choice
        backend, ok = QtWidgets.QInputDialog.getItem(
            self, "Select Backend", "Inference backend:",
            ["yolo", "detectron"], 0, False
        )
        
        # Ensure main window gets focus back
        self.raise_()
        self.activateWindow()
        
        if not ok:
            return False

        # 2) weights path
        weights, ok = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Weights File", "", "Model files (*.pt *.pth);;All files (*)"
        )
        
        # Ensure main window gets focus back
        self.raise_()
        self.activateWindow()
        
        if not ok or not weights:
            return False

        # 3) detectron num_classes (YOLO ignores)
        num_classes = None
        if backend == "detectron":
            num_classes, ok = QtWidgets.QInputDialog.getInt(
                self, "Detectron Classes", "Number of classes:", 5, 1, 999, 1
            )
            
            # Ensure main window gets focus back
            self.raise_()
            self.activateWindow()
            
            if not ok:
                return False

        # CUDA default (no UI). Inference.py already falls back if needed.
        self._infer_cfg["backend"] = backend
        self._infer_cfg["weights"] = weights
        self._infer_cfg["num_classes"] = num_classes
        self._infer_cfg["device"] = "cuda"  
        return True
        
    @QtCore.pyqtSlot(int)
    def _on_cycle_tick(self, n: int):
        self.cycle_count = n
        self.lblCycleVal.setText(str(n))
        
    def _stop_capture_thread(self):
        """Gracefully stop the capture worker when closing the window."""
        # Ask the worker to stop its loop
        if hasattr(self, "_cap_worker") and self._cap_worker is not None:
            try:
                self._cap_worker.stop()
            except Exception as e:
                print("[live] error while stopping worker:", e)

        # Stop the thread itself
        if hasattr(self, "_cap_thread") and self._cap_thread is not None:
            self._cap_thread.quit()
            self._cap_thread.wait(2000)
        self._capture_running = False

    def closeEvent(self, event):
        """Stop capture and join the worker thread when the window closes."""
        self._stop_capture_thread()
        super().closeEvent(event)

        
    def _infer_one_and_update(self, cam_index: int, image_path: str):
        try:
            backend = self._infer_cfg["backend"]
            weights = self._infer_cfg["weights"]
            out_dir = self._infer_cfg["out_dir"]
            num_classes = self._infer_cfg["num_classes"]

            overlay_path, is_ng, score_txt = self._run_inference_on_image(
                backend=backend, weights=weights, image_path=image_path,
                out_dir=out_dir, num_classes=num_classes
            )

            # update UI on main thread
            def _apply():
                pos = self._dev_map.get(cam_index, 0)
                if 0 <= pos < len(self.cards):
                    card = self.cards[pos]
                    if overlay_path and os.path.isfile(overlay_path):
                        card.set_image(overlay_path)
                    else:
                        card.set_image(image_path)  # fallback
                    # mark status
                    if is_ng:
                        self.bad += 1; card.set_ng()
                    else:
                        self.good += 1; card.set_good()
                    self._refresh_summary()
            QtCore.QTimer.singleShot(0, _apply)
        except Exception as e:
            print(f"[infer] error: {e}")
            
    def _run_inference_on_image(self, backend: str, weights: str, image_path: str,
                                out_dir: str, num_classes: int | None):
        overlay = None
        is_ng = False
        score_text = "—"

        try:
            if backend == "yolo":
                self._ensure_yolo(weights)
                overlay, is_ng, score_text = self._yolo_predict_and_save(image_path, out_dir)
            else:
                import Inference as infer
                overlay, is_ng, score_text = infer.detectron_predict_single(
                    weights=weights,
                    image_path=image_path,
                    out_dir=out_dir,
                    num_classes=(num_classes or 1),
                )
        except Exception as e:
            print("[live fast] inference error:", e)

        return overlay, is_ng, score_text



    def _ask_backend_and_weights(self) -> bool:
        # 1) backend choice
        backend, ok = QtWidgets.QInputDialog.getItem(
            self, "Select Backend", "Inference backend:",
            ["yolo", "detectron"], 0, False
        )
        if not ok:
            return False

        # 2) weights path
        weights, ok = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Weights File", "", "Model files (*.pt *.pth);;All files (*)"
        )
        if not ok or not weights:
            return False

        # 3) detectron num_classes (YOLO ignores)
        num_classes = None
        if backend == "detectron":
            num_classes, ok = QtWidgets.QInputDialog.getInt(
                self, "Detectron Classes", "Number of classes:", 5, 1, 999, 1
            )
            if not ok:
                return False

        # CUDA default (no UI). Inference.py already falls back if needed.
        self._infer_cfg["backend"] = backend
        self._infer_cfg["weights"] = weights
        self._infer_cfg["num_classes"] = num_classes
        self._infer_cfg["device"] = "cuda"  
        return True



    def _start_live_flow(self):
        # Ensure window is visible and focused FIRST
        self.showMaximized()
        self.raise_()
        self.activateWindow()
        
        # Small delay to ensure window is ready
        QtCore.QTimer.singleShot(50, self._start_live_flow_actual)

    def _start_live_flow_actual(self):
        """Actual live flow implementation with window focus management"""
        # Get connected cameras first
        try:
            devs = hik_capture.list_devices()
        except Exception as e:
            print("[live] list_devices error:", e)
            devs = []

        if not devs:
            # NEW: fall back to local folder mode
            QtWidgets.QMessageBox.information(
                self, "No Cameras Detected",
                "No Hikrobot cameras detected.\n\n"
                "Switching to local folder mode (select model + image folder)."
            )
            # Ensure window stays focused after dialog
            self.raise_()
            self.activateWindow()
            self._start_folder_mode()
            return

        # (existing camera logic stays same below here)
        n_max = min(8, len(devs))

        # --- SINGLE combined dialog ---
        dlg = LiveConfigDialog(max_cams=n_max, parent=self)
        
        # Ensure the dialog doesn't minimize the main window
        dlg.setWindowModality(QtCore.Qt.ApplicationModal)
        
        result = dlg.exec() if PYQT6 else dlg.exec_()
        
        # Ensure main window gets focus back after dialog closes
        self.raise_()
        self.activateWindow()
        
        if result != QtWidgets.QDialog.Accepted:
            return

        cfg = dlg.get_values()
        backend      = cfg["backend"]        # "yolo" or "detectron"
        weights      = cfg["weights"]
        num_cams     = cfg["num_cams"]
        num_classes  = cfg["num_classes"]    # None for YOLO

        # Save inference config
        self._infer_cfg["backend"]     = backend
        self._infer_cfg["weights"]     = weights
        self._infer_cfg["num_classes"] = num_classes
        self._infer_cfg["device"]      = "cuda"  # Inference.py will fallback if needed

        # NEW: prepare results/<backend>_op/ip/trial_xxx
        self._prepare_run_dirs()


        # Sidebar – don't leave inspection blank
        self.lblInspVal.setText(backend.upper())

        # Pick the first N camera indices
        cam_indices = [d.index for d in devs[:num_cams]]

        # Capture output dir
        base_dir = os.path.dirname(os.path.abspath(__file__))
        out_dir  = os.path.join(base_dir, "captures")
        os.makedirs(out_dir, exist_ok=True)

        # Continuous mode: frames=0  -> CaptureWorker loop forever
        self._make_capture_bridge(cam_indices, frames=0, out_dir=out_dir, mirror=False)

        # Show final message and ensure window stays focused
        QtWidgets.QMessageBox.information(
            self, "Capture",
            f"Starting continuous capture from {num_cams} camera(s) with {backend.upper()}.\n"
            f"Press Ctrl+C or close the window to stop."
        )
        self.raise_()
        self.activateWindow()

        
    def _make_capture_bridge(self, cam_indices, frames, out_dir, mirror=False):
        """
        Build cards, prepare cam->card map, and spin the CaptureWorker thread.
        If frames <= 0: continuous mode (infinite loop).
        """
        # UI grid & summary
        self._build_cards(len(cam_indices))
        self.has_results = True
        self._refresh_summary()

        # map each camera index to its card position
        self._dev_map = {cam_idx: i for i, cam_idx in enumerate(cam_indices)}
        self.num_cams = len(cam_indices)
        self.num_frames = frames if frames is not None else 0

        print("[live] _make_capture_bridge cam_indices:", cam_indices)
        print("[live] _make_capture_bridge dev_map:", self._dev_map)

        # REMOVED: per-camera NG count initialization logic
        
        # 🔹 build per-camera exp/gain maps from Mongo overrides (if available)
        exp_map: dict[int, float] = {}
        gain_map: dict[int, float] = {}
        for cam_idx in cam_indices:
            ov = self._mvs_overrides.get(cam_idx) if hasattr(self, "_mvs_overrides") else None
            if not ov:
                continue
            if "ExposureTime" in ov:
                exp_map[cam_idx] = float(ov["ExposureTime"])
            if "Gain" in ov:
                gain_map[cam_idx] = float(ov["Gain"])

        # thread + worker
        self._cap_thread = QtCore.QThread(self)
        self._cap_worker = CaptureWorker(
            cam_indices,
            frames,
            out_dir,
            mirror=mirror,
            exposure_map=exp_map,
            gain_map=gain_map,
        )
        self._cap_worker.moveToThread(self._cap_thread)

        self._cap_thread.started.connect(self._cap_worker.run)
        self._cap_worker.frameCaptured.connect(self._on_frame_captured_and_enqueue)
        self._cap_worker.error.connect(self._on_capture_error)
        self._cap_worker.cycleTick.connect(self._on_cycle_tick)

        self._cap_worker.finished.connect(self._on_capture_finished)
        self._cap_worker.finished.connect(self._cap_thread.quit)
        self._cap_worker.finished.connect(self._cap_worker.deleteLater)
        self._cap_thread.finished.connect(self._cap_thread.deleteLater)

        self._cap_thread.start()
        self._capture_running = True



    def _start_folder_mode(self):
        # Ensure window is visible and focused FIRST
        self.showMaximized()
        self.raise_()
        self.activateWindow()
        
        # Small delay to ensure window is ready
        QtCore.QTimer.singleShot(50, self._start_folder_mode_actual)

    def _start_folder_mode_actual(self):
        """Actual folder mode implementation with window focus management"""
        """
        Offline mode: ask for backend/weights and an image folder,
        then run inference on those images and show them in the cards.
        No cameras needed.
        """
        # 1) Ask backend + weights + (optional) num_classes
        if not self._prompt_infer_options():
            return
        self._prepare_run_dirs()

        # 2) Ask for folder containing images
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Image Folder", ""
        )
        
        # Ensure main window gets focus back after file dialog
        self.raise_()
        self.activateWindow()
        
        if not folder:
            return

        exts = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")
        image_paths = []
        for root, _, files in os.walk(folder):
            for f in files:
                if os.path.splitext(f)[1].lower() in exts:
                    image_paths.append(os.path.join(root, f))

        if not image_paths:
            QtWidgets.QMessageBox.warning(
                self, "No Images",
                "No image files were found in the selected folder."
            )
            # Ensure window stays focused after dialog
            self.raise_()
            self.activateWindow()
            return

        # 3) Build ONLY ONE card in folder mode
        num_cards = 1
        self._build_cards(num_cards)
        self.has_results = True
        self._refresh_summary()

        # FIXED: Always use cam_index = 0 for all images in folder mode
        # Map ALL images to camera index 0 (single camera)
        self._dev_map = {0: 0}  # cam_index 0 maps to card index 0

        # 4) Fill inference queue - ALL images use cam_index = 0
        self._pending.clear()
        self._inflight = False
        for path in image_paths:
            self._pending.append((0, path))  # Always use cam_index = 0

        # 5) Kick off sequential inference
        self.lblInspVal.setText("FOLDER MODE")
        self._kick_next_inference()

    def _kick_next_inference(self):
        """Start next pending image (if any) and nothing currently running."""
        # Ensure we have run dirs prepared
        if not self._infer_cfg.get("out_dir"):
            self._prepare_run_dirs()

        out_dir = self._infer_cfg["out_dir"]
        os.makedirs(out_dir, exist_ok=True)

        if self._inflight:
            return
        if not self._pending:
            # nothing left
            return


        cam_index, img_path = self._pending.popleft()
        self._current_input[cam_index] = img_path
        # NEW: copy input image into results/..._ip/trial_xxx
        ip_dir = self._infer_cfg.get("ip_dir")
        if ip_dir:
            try:
                os.makedirs(ip_dir, exist_ok=True)
                dest_path = os.path.join(ip_dir, os.path.basename(img_path))
                # avoid overwriting if already copied
                if not os.path.exists(dest_path):
                    shutil.copy2(img_path, dest_path)
            except Exception as e:
                print("[live] failed to copy input image:", e)

        # safety: inference config must be present
        if not self._infer_cfg.get("backend") or not self._infer_cfg.get("weights"):
            QtWidgets.QMessageBox.critical(self, "Inference Not Configured",
                "Backend/weights missing. Click Start Live again.")
            return

        backend     = self._infer_cfg["backend"]
        weights     = self._infer_cfg["weights"]
        out_dir     = self._infer_cfg["out_dir"]
        num_classes = self._infer_cfg.get("num_classes")

        self._inflight = True
        fut = self._infer_pool.submit(
            self._run_inference_on_image, backend, weights, img_path, out_dir, num_classes
        )

        def _done(f):
            try:
                overlay, is_ng, score_text = f.result()
            except Exception as e:
                print("[infer] worker error:", e)
                overlay, is_ng, score_text = None, False, "—"
            # emit back to UI thread
            self.infer_result.emit(cam_index, overlay or img_path, is_ng, score_text)

        fut.add_done_callback(_done)
        
    def start_from_config(self, devs, cfg: dict):
        """
        Start capture + inference using a pre-filled config dict:
        cfg = {
            'backend': 'yolo' or 'detectron',
            'weights': 'path/to/weights',
            'num_cams': int,
            'num_classes': int or None,
            # optional: 'frames_per_cam': int (if >0, finite; if missing/<=0, continuous)
        }
        """
        backend      = cfg["backend"]
        weights      = cfg["weights"]
        num_cams     = cfg["num_cams"]
        num_classes  = cfg.get("num_classes")
        frames       = cfg.get("frames_per_cam", 0)   # 0 => continuous

        # Save inference config
        self._infer_cfg["backend"]     = backend
        self._infer_cfg["weights"]     = weights
        self._infer_cfg["num_classes"] = num_classes  # None for YOLO
        self._infer_cfg["device"]      = "cuda"

        # NEW: prepare results/<backend>_op/ip/trial_xxx
        self._prepare_run_dirs()


        self.lblInspVal.setText(backend.upper())


        # Pick first N devices
        cam_indices = [d.index for d in devs[:num_cams]]

        base_dir = os.path.dirname(os.path.abspath(__file__))
        out_dir  = os.path.join(base_dir, "captures")
        os.makedirs(out_dir, exist_ok=True)

        # Build cards = num_cams and start CaptureWorker
        self._make_capture_bridge(cam_indices, frames, out_dir, mirror=False)

        QtWidgets.QMessageBox.information(
            self, "Capture",
            f"{'Continuous' if frames <= 0 else f'{frames} frame(s) per camera'} "
            f"from {num_cams} camera(s) with {backend.upper()}."
        )


    # ---- misc ----
    def _tick(self):
        sec = int(time.time() - self.start_time)
        hh = sec // 3600
        mm = (sec % 3600) // 60
        ss = sec % 60
        self.lblUptimeVal.setText(f"{hh:02d}:{mm:02d}:{ss:02d}")


    def showEvent(self, event):
        super().showEvent(event)
        self.setWindowOpacity(0)
        self._fade_in = QPropertyAnimation(self, b"windowOpacity")
        self._fade_in.setDuration(600)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic if PYQT6 else QEasingCurve.OutCubic)
        self._fade_in.start()

# ----------------------------- Entrypoint -----------------------------
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setOrganizationName("Live_ui")
    app.setApplicationName("Live Inspection UI")

    font = app.font()
    font.setPointSize(10)
    font.setFamily("SF Pro Display")
    app.setFont(font)

    # 🔹 1) Check MongoDB connection
    if not ensure_mongo_connected():
        QtWidgets.QMessageBox.critical(
            None,
            "MongoDB connection failed",
            "Could not connect to MongoDB at:\n"
            "  mongodb://localhost:27017/\n\n"
            "Database: SmartQC+P\n\n"
            "Please start MongoDB service and try again."
        )
        sys.exit(1)

    # 🔹 2) Load overrides from DB (arena ignored here; use mvs for Hik)
    try:
        arena_overrides, mvs_overrides = load_camera_overrides()
    except Exception as e:
        QtWidgets.QMessageBox.critical(
            None,
            "MongoDB error",
            f"Failed to load camera overrides from MongoDB:\n{e}"
        )
        sys.exit(1)

    w = MainWindow(mvs_overrides=mvs_overrides)
    w.show()
    sys.exit(app.exec() if PYQT6 else app.exec_())