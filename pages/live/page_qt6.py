"""EYRES AI - PyQt6 Live Inspection page.

This is the Qt6 migration of the existing live.py workflow.

Preserved production capabilities:
- Hikrobot/MVS multi-camera capture through hik_capture
- per-camera ExposureTime/Gain overrides from database
- YOLO or Detectron inference
- continuous live capture
- folder inference
- result saving to results/<backend>_ip and results/<backend>_op
- Mongo live record logging
- today's GOOD/NG counters
- last 30 inspection history
- zoomable inspection history images
- template-based anomaly detection using gefs_template_offline
- anomaly GOOD template creation / capture / load / clear

The UI follows the approved light EYRES Qt6 design and uses native Qt6 widgets only.
"""
from __future__ import annotations

import glob
import os
import random
import shutil
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import List

import cv2
import numpy as np

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtProperty, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

# Database APIs are application-owned. Keep the page import-safe if one optional
# live helper is not present in an older db.py.
try:
    from db import ProjectDB
except Exception:
    ProjectDB = None

try:
    from db import (
        get_today_live_counts,
        get_recent_inspections,
        insert_live_record,
        load_camera_overrides,
    )
except Exception:
    get_today_live_counts = None
    get_recent_inspections = None
    insert_live_record = None
    load_camera_overrides = None


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def _app_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _asset(name: str) -> str:
    return str(_app_root() / "ui" / "assets" / "live_icons" / name)


def _project_id(project: dict) -> str:
    return str(project.get("_id") or project.get("id") or "")


def _safe_name(value: str) -> str:
    value = "".join(c if c.isalnum() or c in "-_ " else "_" for c in str(value or "Project"))
    return value.strip().replace(" ", "_") or "Project"


def _load_hik_capture():
    import hik_capture
    return hik_capture


def _load_template_matcher():
    from gefs_template_offline import run_good_bad_template_matching
    return run_good_bad_template_matching


def _load_inference_module():
    import Inference
    return Inference


class ControlledComboBox(QComboBox):
    """White compact popup used instead of the oversized Windows native popup."""

    def __init__(self, parent=None, object_name="FieldCombo"):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setMinimumHeight(34)
        self.setMaxVisibleItems(8)

        view = QListView(self)
        view.setObjectName("LiveComboView")
        view.setUniformItemSizes(True)
        view.setSpacing(1)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setView(view)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        pen = QtGui.QPen(QtGui.QColor("#2868E8" if self.hasFocus() else "#526A86"))
        pen.setWidthF(1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        cx = self.width() - 14.0
        cy = self.height() / 2.0 - 1.0
        painter.drawLine(QtCore.QPointF(cx - 4, cy - 2), QtCore.QPointF(cx, cy + 2))
        painter.drawLine(QtCore.QPointF(cx, cy + 2), QtCore.QPointF(cx + 4, cy - 2))
        painter.end()

    def showPopup(self):
        self.view().setMinimumWidth(self.width())
        self.view().setMaximumWidth(self.width())
        super().showPopup()
        QtCore.QTimer.singleShot(0, self._position_popup)

    def _position_popup(self):
        try:
            popup = self.view().window()
            rows = min(max(1, self.count()), self.maxVisibleItems())
            popup.move(self.mapToGlobal(QtCore.QPoint(0, self.height() + 4)))
            popup.resize(max(150, self.width()), rows * 31 + 12)
        except Exception:
            pass


class ProjectComboBox(ControlledComboBox):
    def __init__(self, parent=None):
        super().__init__(parent, object_name="ProjectSelector")


class TiltActionButton(QPushButton):
    """Live action/tab button with safe sizing and padded icon motion."""

    def __init__(self, text: str, icon_name: str, parent=None, checkable=False):
        super().__init__(text, parent)
        self.icon_name = icon_name
        self._motion = 0.0
        self._hovered = False

        button_font = QtGui.QFont(self.font())
        button_font.setPointSizeF(9.0)
        button_font.setWeight(QtGui.QFont.Weight.DemiBold)
        self.setFont(button_font)

        self._icon_normal = QtGui.QIcon(_asset(f"{icon_name}.svg"))
        self._icon_active = QtGui.QIcon(_asset(f"{icon_name}_active.svg"))

        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(38)
        self.setMaximumHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.setIconSize(QtCore.QSize(32, 32))

        fm = QtGui.QFontMetrics(button_font)
        self._safe_width = max(92, fm.horizontalAdvance(text) + 62)
        self.setMinimumWidth(self._safe_width)

        self._anim = QtCore.QPropertyAnimation(self, b"iconMotion", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)
        self.toggled.connect(lambda _checked: self._refresh_icon())
        self._refresh_icon()

    def sizeHint(self):
        return QtCore.QSize(self._safe_width, 39)

    def minimumSizeHint(self):
        return QtCore.QSize(self._safe_width, 38)

    def get_icon_motion(self):
        return self._motion

    def set_icon_motion(self, value):
        self._motion = max(0.0, min(1.0, float(value)))
        self._refresh_icon()

    iconMotion = pyqtProperty(float, fget=get_icon_motion, fset=set_icon_motion)

    def _animate(self, target):
        self._anim.stop()
        self._anim.setStartValue(self._motion)
        self._anim.setEndValue(float(target))
        self._anim.start()

    @staticmethod
    def _tint(pix: QtGui.QPixmap, color: str):
        if pix.isNull():
            return pix
        out = QtGui.QPixmap(pix.size())
        out.fill(Qt.GlobalColor.transparent)
        p = QtGui.QPainter(out)
        p.drawPixmap(0, 0, pix)
        p.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
        p.fillRect(out.rect(), QtGui.QColor(color))
        p.end()
        return out

    def _refresh_icon(self):
        active = self.isChecked() or self._hovered
        icon = self._icon_active if active else self._icon_normal
        base = icon.pixmap(QtCore.QSize(19, 19))

        if self.objectName() == "StartLiveButton":
            base = self._tint(base, "#FFFFFF")

        canvas = QtGui.QPixmap(34, 34)
        canvas.fill(Qt.GlobalColor.transparent)
        p = QtGui.QPainter(canvas)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        p.translate(17.0, 17.0 - (0.7 * self._motion))
        p.rotate(-4.0 * self._motion)
        scale = 1.0 + 0.045 * self._motion
        p.scale(scale, scale)
        p.drawPixmap(
            QtCore.QRectF(-9.5, -9.5, 19.0, 19.0),
            base,
            QtCore.QRectF(base.rect()),
        )
        p.end()
        self.setIcon(QtGui.QIcon(canvas))

    def enterEvent(self, event):
        self._hovered = True
        self._refresh_icon()
        self._animate(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._animate(0.0)
        self._refresh_icon()
        super().leaveEvent(event)



class ToggleSwitch(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggled.connect(self.update)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor("#2868E8" if self.isChecked() else "#CBD6E3"))
        painter.drawRoundedRect(QtCore.QRectF(0.5, 0.5, 39, 21), 11, 11)
        x = 29 if self.isChecked() else 11
        painter.setBrush(QtGui.QColor("#FFFFFF"))
        painter.drawEllipse(QtCore.QPointF(x, 11), 8, 8)
        painter.end()


class ContextCard(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("ContextCard")
        self.setMinimumHeight(62)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(10, 8, 10, 8)
        self.box.setSpacing(3)
        self.box.addWidget(QLabel(title, objectName="ContextKey"))

    def add_value(self, value="—"):
        label = QLabel(value, objectName="ContextValue")
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.box.addWidget(label)
        return label


class CameraCard(QFrame):
    """Responsive camera/result card used by the approved 2x2 live layout."""

    def __init__(self, card_index: int, parent=None):
        super().__init__(parent)
        self.card_index = card_index
        self.cam_index = card_index
        self._pixmap = QtGui.QPixmap()
        self.setObjectName("CameraCard")
        self.setProperty("result", "neutral")
        self.setMinimumSize(260, 190)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QFrame(objectName="CameraCardHeader")
        hr = QHBoxLayout(head)
        hr.setContentsMargins(9, 5, 9, 5)
        hr.setSpacing(7)

        self.icon = QLabel()
        self.icon.setFixedSize(18, 18)
        self.icon.setPixmap(QtGui.QIcon(_asset("camera.svg")).pixmap(18, 18))
        hr.addWidget(self.icon)

        copy = QVBoxLayout()
        copy.setSpacing(0)
        self.title = QLabel(f"Camera {card_index + 1:02d}", objectName="CameraName")
        self.serial = QLabel("Not assigned", objectName="CameraSerial")
        copy.addWidget(self.title)
        copy.addWidget(self.serial)
        hr.addLayout(copy, 1)

        self.status = QLabel("WAITING", objectName="CameraStatus")
        self.status.setProperty("mode", "neutral")
        hr.addWidget(self.status)
        root.addWidget(head)

        self.image = QLabel("Waiting for capture", objectName="CameraImage")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image.setMinimumHeight(120)
        self.image.setStyleSheet("""
            QLabel#CameraImage {
                background-color:#111827;
                color:#A6B2C3;
                border:0;
                font-size:9px;
                font-weight:650;
            }
        """)
        root.addWidget(self.image, 1)

        foot = QFrame(objectName="CameraCardFooter")
        fr = QHBoxLayout(foot)
        fr.setContentsMargins(9, 4, 9, 4)
        fr.setSpacing(5)
        self.b1 = QLabel("Status: —", objectName="CameraMeta")
        self.b2 = QLabel("Class: —", objectName="CameraMeta")
        self.score = QLabel("Score: —", objectName="CameraMeta")
        self.b2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.score.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        fr.addWidget(self.b1, 1)
        fr.addWidget(self.b2, 1)
        fr.addWidget(self.score, 1)
        root.addWidget(foot)

    def set_device(self, cam_index: int, label: str = ""):
        self.cam_index = int(cam_index)
        self.serial.setText(label or f"Device index {cam_index}")

    def set_image(self, path_or_pixmap):
        if isinstance(path_or_pixmap, QtGui.QPixmap):
            pixmap = path_or_pixmap
        else:
            pixmap = QtGui.QPixmap(str(path_or_pixmap))

        if pixmap.isNull():
            self._pixmap = QtGui.QPixmap()
            self.image.setPixmap(QtGui.QPixmap())
            self.image.setText("Image unavailable")
            return

        self._pixmap = pixmap
        self._rescale()

    def current_pixmap(self):
        return QtGui.QPixmap(self._pixmap) if not self._pixmap.isNull() else QtGui.QPixmap()

    def set_result(self, is_ng: bool | None, score_text: str = "—", class_name: str = "—"):
        if is_ng is None:
            mode = "neutral"
            status = "WAITING"
        elif is_ng:
            mode = "ng"
            status = "NG"
        else:
            mode = "good"
            status = "GOOD"

        self.setProperty("result", mode)
        self.status.setProperty("mode", mode)
        self.status.setText(status)

        self.b1.setText(f"Status: {status if is_ng is not None else '—'}")
        self.b2.setText(f"Class: {class_name or '—'}")
        self.score.setText(f"Score: {score_text or '—'}")

        for widget in (self, self.status):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def clear_result(self):
        self._pixmap = QtGui.QPixmap()
        self.image.setPixmap(QtGui.QPixmap())
        self.image.setText("Waiting for capture")
        self.set_result(None)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self):
        if self._pixmap.isNull():
            return
        target = self.image.size()
        if target.width() <= 2 or target.height() <= 2:
            return
        scaled = self._pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image.setPixmap(scaled)
        self.image.setText("")


class ImageZoomDialog(QDialog):
    def __init__(self, pixmap: QtGui.QPixmap, title: str = "Inspection Image", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1000, 700)
        self._original = QtGui.QPixmap(pixmap)
        self._scale = 1.0

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidget(self.image)
        root.addWidget(self.scroll, 1)

        controls = QHBoxLayout()
        controls.addStretch(1)

        minus = QPushButton("−", objectName="SecondaryButton")
        fit = QPushButton("Fit", objectName="SecondaryButton")
        reset = QPushButton("100%", objectName="SecondaryButton")
        plus = QPushButton("+", objectName="SecondaryButton")
        close = QPushButton("Close", objectName="PrimaryButton")

        minus.clicked.connect(lambda: self._zoom(1 / 1.2))
        plus.clicked.connect(lambda: self._zoom(1.2))
        reset.clicked.connect(self._reset)
        fit.clicked.connect(self._fit)
        close.clicked.connect(self.accept)

        for btn in (minus, fit, reset, plus, close):
            controls.addWidget(btn)
        controls.addStretch(1)
        root.addLayout(controls)

        self.setStyleSheet("""
        QDialog { background:#F2F6FB; color:#101A2D; }
        QScrollArea { background:#FFFFFF; border:1px solid #C4D2E2; border-radius:10px; }
        QLabel { background:#FFFFFF; }
        QPushButton#PrimaryButton, QPushButton#SecondaryButton {
            min-height:35px; border-radius:8px; padding:0 12px;
            font-size:9px; font-weight:780;
        }
        QPushButton#PrimaryButton { background:#2868E8; color:#FFFFFF; border:1px solid #2868E8; }
        QPushButton#SecondaryButton { background:#FFFFFF; color:#2868E8; border:1px solid #B8C8DB; }
        """)
        self._update()

    def _zoom(self, factor):
        self._scale = min(8.0, max(0.1, self._scale * factor))
        self._update()

    def _reset(self):
        self._scale = 1.0
        self._update()

    def _fit(self):
        if self._original.isNull():
            return
        viewport = self.scroll.viewport().size()
        if self._original.width() and self._original.height():
            self._scale = min(
                viewport.width() / self._original.width(),
                viewport.height() / self._original.height(),
            ) * 0.95
        self._update()

    def _update(self):
        if self._original.isNull():
            self.image.setText("Image unavailable")
            return
        size = self._original.size() * self._scale
        pix = self._original.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image.setPixmap(pix)
        self.image.resize(pix.size())


class HistoryItem(QFrame):
    def __init__(self, inspection: dict, parent=None):
        super().__init__(parent)
        self.inspection = inspection
        self.pixmap = QtGui.QPixmap()
        self.setObjectName("HistoryItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("ng", bool(inspection.get("is_ng", False)))

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        self.image = QLabel("No Image", objectName="HistoryImage")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(88)

        raw = inspection.get("output_image")
        if raw:
            try:
                data = bytes(raw)
                self.pixmap.loadFromData(data)
                if not self.pixmap.isNull():
                    self._render()
            except Exception:
                pass

        box.addWidget(self.image, 1)

        footer = QFrame(objectName="HistoryFooter")
        row = QHBoxLayout(footer)
        row.setContentsMargins(7, 5, 7, 5)

        dt = inspection.get("inspection_datetime")
        if isinstance(dt, datetime):
            time_text = dt.strftime("%H:%M:%S")
        else:
            text = str(dt or "")
            time_text = text[11:19] if len(text) >= 19 else "—"

        cam = int(inspection.get("cam_index", 0) or 0) + 1
        left = QLabel(f"Cam {cam} · {time_text}", objectName="HistoryText")
        status = QLabel("NG" if inspection.get("is_ng", False) else "GOOD", objectName="HistoryStatus")
        status.setProperty("mode", "ng" if inspection.get("is_ng", False) else "good")
        row.addWidget(left, 1)
        row.addWidget(status)
        box.addWidget(footer)

    def _render(self):
        if self.pixmap.isNull():
            return
        target = self.image.size()
        if target.width() > 2 and target.height() > 2:
            self.image.setPixmap(
                self.pixmap.scaled(
                    target,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.image.setText("")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.pixmap.isNull():
            ImageZoomDialog(self.pixmap, "Previous Inspection", self).exec()
        super().mouseReleaseEvent(event)


class LiveConfigDialog(QDialog):
    def __init__(self, max_cams: int = 8, initial: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Live Capture Configuration")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.max_cams = max(1, int(max_cams))
        initial = initial or {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QFrame(objectName="DialogHeader")
        hb = QVBoxLayout(head)
        hb.setContentsMargins(16, 14, 16, 13)
        hb.setSpacing(3)
        hb.addWidget(QLabel("Live Capture Configuration", objectName="DialogTitle"))
        hb.addWidget(QLabel(
            "Configure the inference backend, model and camera count before starting the session.",
            objectName="DialogSubtitle",
        ))
        root.addWidget(head)

        content = QWidget()
        form = QVBoxLayout(content)
        form.setContentsMargins(16, 14, 16, 14)
        form.setSpacing(10)

        self.backend = ControlledComboBox()
        self.backend.addItems(["yolo", "detectron"])
        self.backend.setCurrentText(str(initial.get("backend") or "yolo"))

        self.weights = QLineEdit(objectName="PathEdit")
        self.weights.setPlaceholderText("Select weights file (.pt / .pth)")
        self.weights.setText(str(initial.get("weights") or ""))

        wr = QHBoxLayout()
        wr.setSpacing(7)
        wr.addWidget(self.weights, 1)
        browse = QPushButton("Browse", objectName="SecondaryButton")
        browse.clicked.connect(self._browse)
        wr.addWidget(browse)

        self.camera_count = QSpinBox(objectName="FieldSpin")
        self.camera_count.setRange(1, self.max_cams)
        self.camera_count.setValue(min(int(initial.get("num_cams") or min(4, self.max_cams)), self.max_cams))

        self.classes = QSpinBox(objectName="FieldSpin")
        self.classes.setRange(1, 1000)
        self.classes.setValue(int(initial.get("num_classes") or 5))

        form.addWidget(QLabel("Inference backend", objectName="FieldLabel"))
        form.addWidget(self.backend)
        form.addWidget(QLabel("Weights file", objectName="FieldLabel"))
        form.addLayout(wr)
        form.addWidget(QLabel("How many cameras", objectName="FieldLabel"))
        form.addWidget(self.camera_count)

        self.classes_label = QLabel("Detectron num_classes", objectName="FieldLabel")
        form.addWidget(self.classes_label)
        form.addWidget(self.classes)

        root.addWidget(content)

        foot = QFrame(objectName="DialogFooter")
        fr = QHBoxLayout(foot)
        fr.setContentsMargins(16, 10, 16, 12)
        fr.addStretch(1)
        cancel = QPushButton("Cancel", objectName="SecondaryButton")
        apply_btn = QPushButton("Apply Configuration", objectName="PrimaryButton")
        cancel.clicked.connect(self.reject)
        apply_btn.clicked.connect(self._accept)
        fr.addWidget(cancel)
        fr.addWidget(apply_btn)
        root.addWidget(foot)

        self.backend.currentTextChanged.connect(self._backend_changed)
        self._backend_changed(self.backend.currentText())

        self.setStyleSheet("""
        QDialog { background:#FFFFFF; color:#101A2D; }
        QFrame#DialogHeader, QFrame#DialogFooter { background:#FCFDFE; }
        QFrame#DialogHeader { border-bottom:1px solid #DCE4EE; }
        QFrame#DialogFooter { border-top:1px solid #DCE4EE; }
        QLabel#DialogTitle { font-size:14px; font-weight:850; color:#101A2D; }
        QLabel#DialogSubtitle { font-size:8.8px; color:#687A90; }
        QLabel#FieldLabel { font-size:8.8px; color:#405873; font-weight:760; }
        QLineEdit#PathEdit, QSpinBox#FieldSpin, QComboBox#FieldCombo {
            min-height:35px; background:#FFFFFF; color:#17263D;
            border:1px solid #B8C8DB; border-radius:8px; padding:0 8px; font-size:9.5px;
        }
        QComboBox#FieldCombo { padding:0 32px 0 9px; }
        QComboBox#FieldCombo::drop-down { width:28px; border:0; border-left:1px solid #D8E1EC; }
        QComboBox#FieldCombo::down-arrow { image:none; width:0; height:0; }
        QListView#LiveComboView {
            background:#FFFFFF; color:#17263D; border:1px solid #AEBFD5;
            border-radius:8px; padding:5px; outline:0; font-size:9.6px; font-weight:700;
        }
        QListView#LiveComboView::item { min-height:30px; padding:3px 8px; border-radius:5px; }
        QListView#LiveComboView::item:hover { background:#F0F5FF; color:#1D5BD0; }
        QListView#LiveComboView::item:selected { background:#E5EEFF; color:#1D5BD0; }
        QPushButton#PrimaryButton, QPushButton#SecondaryButton {
            min-height:36px; border-radius:9px; padding:0 12px; font-size:9.3px; font-weight:780;
        }
        QPushButton#PrimaryButton { background:#2868E8; color:#FFFFFF; border:1px solid #2868E8; }
        QPushButton#SecondaryButton { background:#FFFFFF; color:#2868E8; border:1px solid #B8C8DB; }
        """)

    def _backend_changed(self, value):
        show = str(value).lower() == "detectron"
        self.classes_label.setVisible(show)
        self.classes.setVisible(show)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Weights File",
            self.weights.text().strip() or str(Path.home()),
            "Model files (*.pt *.pth);;All files (*.*)",
        )
        if path:
            self.weights.setText(path)

    def _accept(self):
        if not self.weights.text().strip():
            QMessageBox.warning(self, "Missing Weights", "Please select a weights file.")
            return
        self.accept()

    def values(self):
        backend = self.backend.currentText().lower()
        return {
            "backend": backend,
            "weights": self.weights.text().strip(),
            "num_cams": int(self.camera_count.value()),
            "num_classes": int(self.classes.value()) if backend == "detectron" else None,
        }


class DeviceScanThread(QtCore.QThread):
    scanned = pyqtSignal(object, str)

    def run(self):
        try:
            hik = _load_hik_capture()
            devices = list(hik.list_devices() or [])
            self.scanned.emit(devices, "")
        except Exception as exc:
            self.scanned.emit([], str(exc))


class CaptureWorker(QtCore.QObject):
    frameCaptured = pyqtSignal(int, int, str)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    cycleTick = pyqtSignal(int)

    def __init__(
        self,
        cam_indices: List[int],
        frames: int,
        out_dir: str,
        mirror=False,
        exposure_map: dict[int, float] | None = None,
        gain_map: dict[int, float] | None = None,
    ):
        super().__init__()
        self.cam_indices = list(cam_indices)
        self.frames = int(frames)
        self.out_dir = str(out_dir)
        self.mirror = bool(mirror)
        self.exposure_map = exposure_map or {}
        self.gain_map = gain_map or {}
        self._running = True
        self._cycle = 0

    @QtCore.pyqtSlot()
    def stop(self):
        self._running = False

    @QtCore.pyqtSlot()
    def run(self):
        try:
            hik = _load_hik_capture()

            def callback(cam_idx, frame_i, path):
                self.frameCaptured.emit(int(cam_idx), int(frame_i), str(path))

            def exp_for(index):
                return self.exposure_map.get(index)

            def gain_for(index):
                return self.gain_map.get(index)

            if self.frames > 0:
                if not self._running:
                    self.finished.emit()
                    return
                for cam_idx in self.cam_indices:
                    if not self._running:
                        break
                    hik.capture_multi(
                        indices=[cam_idx],
                        frames=self.frames,
                        base_out=self.out_dir,
                        mirror=self.mirror,
                        exposure_us=exp_for(cam_idx),
                        gain_db=gain_for(cam_idx),
                        progress_cb=callback,
                    )
                self._cycle += 1
                self.cycleTick.emit(self._cycle)
                self.finished.emit()
                return

            while self._running:
                self._cycle += 1
                for cam_idx in self.cam_indices:
                    if not self._running:
                        break
                    hik.capture_multi(
                        indices=[cam_idx],
                        frames=1,
                        base_out=self.out_dir,
                        mirror=self.mirror,
                        exposure_us=exp_for(cam_idx),
                        gain_db=gain_for(cam_idx),
                        progress_cb=callback,
                    )
                self.cycleTick.emit(self._cycle)

            self.finished.emit()

        except Exception as exc:
            self.error.emit(str(exc))
            self.finished.emit()


class LivePageQt6(QWidget):
    toast_requested = pyqtSignal(str, str)
    infer_result = pyqtSignal(int, str, bool, str)
    anomaly_match_result = pyqtSignal(float, str, str, str)

    def __init__(self, user: dict | None = None, parent=None):
        super().__init__(parent)
        self.user = user or {}
        self.setObjectName("LivePageQt6")

        # Session state
        self.projects: list[dict] = []
        self.project_map: dict[str, dict] = {}
        self.selected_project_id = ""
        self._session_cfg = {
            "backend": None,
            "weights": None,
            "num_cams": 1,
            "num_classes": None,
            "device": "cuda",
        }
        self._infer_cfg = {
            "backend": None,
            "weights": None,
            "num_classes": None,
            "device": "cuda",
            "out_dir": None,
            "ip_dir": None,
        }
        self._detected_devices = []
        self._mvs_overrides: dict[int, dict] = {}

        # Runtime
        self.good = 0
        self.bad = 0
        self.cycle_count = 0
        self._last_is_ng: bool | None = None
        self._capture_running = False
        self._cap_thread = None
        self._cap_worker = None
        self._scan_thread = None

        self.cards: list[CameraCard] = []
        self._dev_map: dict[int, int] = {}
        self._pending = deque()
        self._inflight = False
        self._current_input: dict[int, str] = {}
        self._infer_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="eyres-live-infer")
        self._anomaly_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="eyres-anomaly")

        self._yolo_infer = None
        self._yolo_weights = None

        # Anomaly state
        self._anomaly_cam_index = None
        self._anomaly_last_frame = None
        self._last_good_template_path = None
        self.anomaly_timer = QtCore.QTimer(self)
        self.anomaly_timer.setInterval(1000)
        self.anomaly_timer.timeout.connect(self._update_anomaly_preview)

        self.start_time = time.time()

        self._build()
        self._apply_style()

        self.infer_result.connect(self._apply_infer_result)
        self.anomaly_match_result.connect(self._apply_anomaly_match_result)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self._build_cards(1)
        self._init_counts_from_db()
        self.refresh_context()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # Context strip
        context = QGridLayout()
        context.setContentsMargins(0, 0, 0, 0)
        context.setHorizontalSpacing(8)

        project_card = ContextCard("CURRENT PROJECT")
        self.project_selector = ProjectComboBox()
        self.project_selector.currentIndexChanged.connect(self._project_changed)
        project_card.box.addWidget(self.project_selector)
        context.addWidget(project_card, 0, 0)

        mode_card = ContextCard("SESSION MODE")
        self.context_mode = mode_card.add_value("Live Camera")
        context.addWidget(mode_card, 0, 1)

        inference_card = ContextCard("INFERENCE")
        self.context_inference = inference_card.add_value("Not configured")
        context.addWidget(inference_card, 0, 2)

        cameras_card = ContextCard("CAMERAS")
        self.context_cameras = cameras_card.add_value("Checking…")
        context.addWidget(cameras_card, 0, 3)

        context.setColumnStretch(0, 11)
        context.setColumnStretch(1, 10)
        context.setColumnStretch(2, 18)
        context.setColumnStretch(3, 10)
        root.addLayout(context)

        # Toolbar / tabs
        toolbar = QHBoxLayout()
        toolbar.setSpacing(7)

        self.tab_buttons = {}
        for key, text, icon in (
            ("live", "Live Inspection", "live"),
            ("history", "Inspection History", "history"),
            ("anomaly", "Anomaly Detection", "anomaly"),
        ):
            button = TiltActionButton(text, icon, checkable=True)
            button.setObjectName("LiveTabButton")
            # Width comes from TiltActionButton's font metrics; these floor
            # values keep every label readable at Windows 125/150% DPI.
            button.setMinimumWidth(max(button.minimumWidth(), {
                "live": 132,
                "history": 150,
                "anomaly": 154,
            }[key]))
            button.clicked.connect(lambda checked=False, k=key: self._switch_view(k))
            toolbar.addWidget(button)
            self.tab_buttons[key] = button

        toolbar.addStretch(1)

        self.config_btn = TiltActionButton("Configure Session", "config")
        self.config_btn.setObjectName("ToolbarButton")
        self.config_btn.setMinimumWidth(max(self.config_btn.minimumWidth(), 158))
        self.config_btn.clicked.connect(self._configure_session)

        self.folder_btn = TiltActionButton("Folder Mode", "folder")
        self.folder_btn.setObjectName("ToolbarButton")
        self.folder_btn.setMinimumWidth(max(self.folder_btn.minimumWidth(), 118))
        self.folder_btn.clicked.connect(self._start_folder_mode)

        self.start_btn = TiltActionButton("Start Live", "play")
        self.start_btn.setObjectName("StartLiveButton")
        self.start_btn.setMinimumWidth(max(self.start_btn.minimumWidth(), 108))
        self.start_btn.clicked.connect(self._toggle_live)

        toolbar.addWidget(self.config_btn)
        toolbar.addWidget(self.folder_btn)
        toolbar.addWidget(self.start_btn)
        root.addLayout(toolbar)

        self.stack = QStackedWidget()
        self.live_view = self._build_live_view()
        self.history_view = self._build_history_view()
        self.anomaly_view = self._build_anomaly_view()
        self.stack.addWidget(self.live_view)
        self.stack.addWidget(self.history_view)
        self.stack.addWidget(self.anomaly_view)
        root.addWidget(self.stack, 1)

        self._switch_view("live")

    def _build_live_view(self):
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        viewer = QFrame(objectName="ViewerCard")
        viewer_box = QVBoxLayout(viewer)
        viewer_box.setContentsMargins(0, 0, 0, 0)
        viewer_box.setSpacing(0)

        head = QFrame(objectName="ViewerHeader")
        hb = QHBoxLayout(head)
        hb.setContentsMargins(13, 8, 13, 8)
        copy = QVBoxLayout()
        copy.setSpacing(2)
        copy.addWidget(QLabel("Camera Inspection View", objectName="SectionTitle"))
        self.viewer_meta = QLabel("Waiting for live session", objectName="SectionSubtitle")
        copy.addWidget(self.viewer_meta)
        hb.addLayout(copy, 1)
        self.live_badge = QLabel("IDLE", objectName="LiveBadge")
        self.live_badge.setProperty("mode", "idle")
        hb.addWidget(self.live_badge)
        viewer_box.addWidget(head)

        grid_host = QWidget(objectName="CameraGridHost")
        self.camera_grid = QGridLayout(grid_host)
        self.camera_grid.setContentsMargins(9, 9, 9, 9)
        self.camera_grid.setHorizontalSpacing(9)
        self.camera_grid.setVerticalSpacing(9)
        viewer_box.addWidget(grid_host, 1)
        row.addWidget(viewer, 1)

        summary = QFrame(objectName="SummaryPanel")
        summary.setFixedWidth(315)
        sb = QVBoxLayout(summary)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(0)

        shead = QFrame(objectName="SummaryHeader")
        shb = QVBoxLayout(shead)
        shb.setContentsMargins(12, 10, 12, 9)
        shb.setSpacing(2)
        shb.addWidget(QLabel("Inspection Summary", objectName="SectionTitle"))
        shb.addWidget(QLabel("Current session counters and runtime state.", objectName="SectionSubtitle"))
        sb.addWidget(shead)

        result = QFrame(objectName="CurrentResult")
        rb = QHBoxLayout(result)
        rb.setContentsMargins(10, 9, 10, 9)
        result_copy = QVBoxLayout()
        result_copy.setSpacing(2)
        result_copy.addWidget(QLabel("CURRENT RESULT", objectName="SummaryCaption"))
        self.current_result_meta = QLabel("No inspection yet", objectName="MiniText")
        result_copy.addWidget(self.current_result_meta)
        rb.addLayout(result_copy, 1)
        self.current_result = QLabel("—", objectName="CurrentResultPill")
        self.current_result.setProperty("mode", "neutral")
        rb.addWidget(self.current_result)
        sb.addWidget(result)

        kpi_host = QWidget()
        kg = QGridLayout(kpi_host)
        kg.setContentsMargins(10, 0, 10, 0)
        kg.setSpacing(7)

        self.good_value = self._kpi(kg, 0, 0, "GOOD (G)", "0", "good")
        self.bad_value = self._kpi(kg, 0, 1, "BAD (NG)", "0", "bad")
        self.ratio_value = self._kpi(kg, 1, 0, "REJECTION RATIO", "0.00%", "neutral")
        self.total_value = self._kpi(kg, 1, 1, "TOTAL", "0", "neutral")
        sb.addWidget(kpi_host)

        session = QFrame(objectName="SummarySection")
        ss = QVBoxLayout(session)
        ss.setContentsMargins(10, 9, 10, 8)
        ss.setSpacing(0)
        ss.addWidget(QLabel("SESSION", objectName="RailEyebrow"))
        self.uptime_value = self._info_row(ss, "Uptime", "00:00:00")
        self.cycle_value = self._info_row(ss, "Cycle", "0")
        self.inspection_value = self._info_row(ss, "Inspection", "Idle")
        self.pending_value = self._info_row(ss, "Pending inference", "0")

        bypass_row = QHBoxLayout()
        bypass_row.setContentsMargins(0, 5, 0, 0)
        bypass_row.addWidget(QLabel("Rejection Bypass", objectName="SwitchLabel"))
        bypass_row.addStretch(1)
        self.bypass_toggle = ToggleSwitch()
        bypass_row.addWidget(self.bypass_toggle)
        ss.addLayout(bypass_row)
        sb.addWidget(session)

        health = QFrame(objectName="SummarySection")
        hs = QVBoxLayout(health)
        hs.setContentsMargins(10, 9, 10, 8)
        hs.setSpacing(0)
        hs.addWidget(QLabel("CAMERA HEALTH", objectName="RailEyebrow"))
        self.health_connected = self._info_row(hs, "Connected", "Checking…")
        self.health_capture = self._info_row(hs, "Capture worker", "Idle")
        self.health_device = self._info_row(hs, "Inference device", "CUDA")
        sb.addWidget(health)
        sb.addStretch(1)

        actions = QFrame(objectName="SummaryActions")
        ar = QHBoxLayout(actions)
        ar.setContentsMargins(10, 9, 10, 10)
        ar.setSpacing(7)

        reset = QPushButton("Reset Counts", objectName="SecondaryButton")
        reset.clicked.connect(self._reset_all)
        stop = QPushButton("Stop Capture", objectName="DangerButton")
        stop.clicked.connect(lambda: self._stop_capture(clear_pending=True))

        ar.addWidget(reset, 1)
        ar.addWidget(stop, 1)
        sb.addWidget(actions)

        row.addWidget(summary)
        return page

    def _build_history_view(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        stats = QHBoxLayout()
        stats.setSpacing(8)
        self.prev_total_label = self._history_stat(stats, "TOTAL INSPECTIONS", "0")
        self.prev_good_label = self._history_stat(stats, "GOOD RESULTS", "0", "good")
        self.prev_bad_label = self._history_stat(stats, "BAD RESULTS", "0", "bad")
        self.prev_ratio_label = self._history_stat(stats, "REJECTION RATIO", "0.00%")
        self.prev_last_time = self._history_stat(stats, "LAST INSPECTION", "—")
        self.prev_cam_count = self._history_stat(stats, "CAMERAS USED", "0")
        root.addLayout(stats)

        card = QFrame(objectName="HistoryCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        head = QFrame(objectName="HistoryHeader")
        hr = QHBoxLayout(head)
        hr.setContentsMargins(12, 8, 12, 8)
        hr.addWidget(QLabel("Last 30 Inspections", objectName="SectionTitle"))
        hr.addWidget(QLabel("Click a tile to inspect its captured result.", objectName="SectionSubtitle"))
        hr.addStretch(1)
        box.addWidget(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        host = QWidget()
        self.history_grid = QGridLayout(host)
        self.history_grid.setContentsMargins(9, 9, 9, 9)
        self.history_grid.setHorizontalSpacing(9)
        self.history_grid.setVerticalSpacing(9)
        scroll.setWidget(host)

        box.addWidget(scroll, 1)
        root.addWidget(card, 1)
        return page

    def _build_anomaly_view(self):
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        main = QFrame(objectName="AnomalyMain")
        mb = QVBoxLayout(main)
        mb.setContentsMargins(0, 0, 0, 0)
        mb.setSpacing(0)

        head = QFrame(objectName="ViewerHeader")
        hb = QHBoxLayout(head)
        hb.setContentsMargins(12, 8, 12, 8)
        hb.addWidget(QLabel("Anomaly Detection Preview", objectName="SectionTitle"))
        hb.addWidget(QLabel("Live camera preview / captured frame", objectName="SectionSubtitle"))
        hb.addStretch(1)
        mb.addWidget(head)

        preview_host = QWidget()
        ph = QVBoxLayout(preview_host)
        ph.setContentsMargins(10, 10, 10, 10)
        self.anomalyPreviewLabel = QLabel("Live preview will appear here", objectName="AnomalyPreview")
        self.anomalyPreviewLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.anomalyPreviewLabel.setMinimumHeight(320)
        self.anomalyPreviewLabel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.anomalyPreviewLabel.setStyleSheet("""
            QLabel#AnomalyPreview {
                background-color:#111827;
                color:#A6B2C3;
                border:1px solid #C7D4E4;
                border-radius:10px;
                font-size:9px;
                font-weight:650;
            }
        """)
        ph.addWidget(self.anomalyPreviewLabel, 1)

        self.anomalyResultLabel = QLabel("—", objectName="AnomalyResult")
        self.anomalyResultLabel.setProperty("mode", "neutral")
        self.anomalyResultLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph.addWidget(self.anomalyResultLabel, 0, Qt.AlignmentFlag.AlignHCenter)
        mb.addWidget(preview_host, 1)

        tools = QFrame(objectName="AnomalyToolbar")
        tr = QHBoxLayout(tools)
        tr.setContentsMargins(10, 8, 10, 10)
        tr.setSpacing(7)
        tr.addStretch(1)

        template_btn = TiltActionButton("Template Creation", "template")
        template_btn.setObjectName("ToolbarButton")
        template_btn.setMinimumWidth(max(template_btn.minimumWidth(), 154))
        template_btn.clicked.connect(self._handle_template_creation)

        detect_btn = TiltActionButton("Run Detection", "anomaly")
        detect_btn.setObjectName("StartLiveButton")
        detect_btn.setMinimumWidth(max(detect_btn.minimumWidth(), 132))
        detect_btn.clicked.connect(self._handle_anomaly_detection)

        load_btn = TiltActionButton("Load", "load")
        load_btn.setObjectName("ToolbarButton")
        load_btn.setMinimumWidth(max(load_btn.minimumWidth(), 88))
        load_btn.clicked.connect(self._handle_anomaly_load)

        clear_btn = TiltActionButton("Clear", "clear")
        clear_btn.setObjectName("ToolbarButton")
        clear_btn.setMinimumWidth(max(clear_btn.minimumWidth(), 92))
        clear_btn.clicked.connect(self._handle_anomaly_clear)

        for btn in (template_btn, detect_btn, load_btn, clear_btn):
            tr.addWidget(btn)
        tr.addStretch(1)
        mb.addWidget(tools)
        row.addWidget(main, 1)

        side = QFrame(objectName="AnomalySide")
        side.setFixedWidth(320)
        sb = QVBoxLayout(side)
        sb.setContentsMargins(11, 11, 11, 11)
        sb.setSpacing(8)
        sb.addWidget(QLabel("Anomaly Session", objectName="SectionTitle"))
        note = QLabel(
            "Create a known-good template, compare the current frame and review the final GOOD / NG decision.",
            objectName="SectionSubtitle",
        )
        note.setWordWrap(True)
        sb.addWidget(note)

        for title, text in (
            ("1. Good template", "Capture the current preview as the known-good reference."),
            ("2. Current frame", "Use the live preview or capture the current camera frame."),
            ("3. Compare", "Run the existing template matching pipeline and display the decision."),
        ):
            box = QFrame(objectName="AnomalyStep")
            vb = QVBoxLayout(box)
            vb.setContentsMargins(9, 8, 9, 8)
            vb.setSpacing(3)
            vb.addWidget(QLabel(title, objectName="AnomalyStepTitle"))
            desc = QLabel(text, objectName="AnomalyStepText")
            desc.setWordWrap(True)
            vb.addWidget(desc)
            sb.addWidget(box)

        sb.addStretch(1)
        self.template_health = self._side_info(sb, "Template", "Not created")
        self.preview_camera_health = self._side_info(sb, "Preview camera", "Checking…")
        self.preview_refresh_health = self._side_info(sb, "Refresh", "1 s")

        row.addWidget(side)
        return page

    def _kpi(self, grid, row, col, title, value, mode):
        frame = QFrame(objectName="KpiCard")
        frame.setProperty("mode", mode)
        box = QVBoxLayout(frame)
        box.setContentsMargins(8, 7, 8, 7)
        box.setSpacing(2)
        box.addWidget(QLabel(title, objectName="SummaryCaption"))
        label = QLabel(value, objectName="KpiValue")
        label.setProperty("mode", mode)
        box.addWidget(label)
        grid.addWidget(frame, row, col)
        return label

    def _info_row(self, parent_layout, title, value):
        frame = QFrame(objectName="InfoRow")
        row = QHBoxLayout(frame)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel(title, objectName="InfoKey"))
        row.addStretch(1)
        label = QLabel(value, objectName="InfoValue")
        row.addWidget(label)
        parent_layout.addWidget(frame)
        return label

    def _history_stat(self, layout, title, value, mode="neutral"):
        frame = QFrame(objectName="HistoryStat")
        box = QVBoxLayout(frame)
        box.setContentsMargins(9, 8, 9, 8)
        box.setSpacing(2)
        box.addWidget(QLabel(title, objectName="SummaryCaption"))
        label = QLabel(value, objectName="HistoryStatValue")
        label.setProperty("mode", mode)
        box.addWidget(label)
        layout.addWidget(frame, 1)
        return label

    def _side_info(self, parent_layout, title, value):
        frame = QFrame(objectName="SideInfoRow")
        row = QHBoxLayout(frame)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel(title, objectName="InfoKey"))
        row.addStretch(1)
        label = QLabel(value, objectName="InfoValue")
        row.addWidget(label)
        parent_layout.addWidget(frame)
        return label

    # ------------------------------------------------------------------
    # Style
    # ------------------------------------------------------------------
    def _apply_style(self):
        self.setStyleSheet("""
        QWidget#LivePageQt6 { background:transparent; color:#101A2D; }
        QWidget#LivePageQt6 QLabel { background:transparent; border:0; }

        QFrame#ContextCard {
            background:#FFFFFF; border:1px solid #C3D1E2; border-radius:12px;
        }
        QLabel#ContextKey {
            color:#60738B; font-size:8px; font-weight:850; letter-spacing:.65px;
        }
        QLabel#ContextValue {
            color:#15263D; font-size:10.4px; font-weight:800;
        }

        QComboBox#ProjectSelector, QComboBox#FieldCombo {
            min-height:34px; background:#FFFFFF; color:#17263D;
            border:1px solid #AEBFD5; border-radius:8px;
            padding:0 32px 0 9px; font-size:9.6px; font-weight:740;
        }
        QComboBox#ProjectSelector:focus, QComboBox#FieldCombo:focus,
        QComboBox#ProjectSelector:on, QComboBox#FieldCombo:on {
            background:#FFFFFF; border:1px solid #2868E8;
        }
        QComboBox#ProjectSelector::drop-down, QComboBox#FieldCombo::drop-down {
            width:28px; border:0; border-left:1px solid #D8E1EC;
        }
        QComboBox#ProjectSelector::down-arrow, QComboBox#FieldCombo::down-arrow {
            image:none; width:0; height:0;
        }
        QListView#LiveComboView {
            background:#FFFFFF; color:#17263D; border:1px solid #AEBFD5;
            border-radius:8px; padding:5px; outline:0; font-size:9.6px; font-weight:700;
        }
        QListView#LiveComboView::item {
            background:#FFFFFF; color:#17263D; min-height:30px; padding:3px 8px; border-radius:5px;
        }
        QListView#LiveComboView::item:hover {
            background:#F0F5FF; color:#1D5BD0;
        }
        QListView#LiveComboView::item:selected {
            background:#E5EEFF; color:#1D5BD0; font-weight:800;
        }

        QPushButton#LiveTabButton, QPushButton#ToolbarButton, QPushButton#StartLiveButton {
            padding:0 11px; text-align:left;
            min-height:38px; border-radius:10px; text-align:left; padding-left:3px;
        }
        QPushButton#LiveTabButton {
            padding:0 11px; text-align:left;
            background:#FFFFFF; color:#405873; border:1px solid #C4D2E2;
        }
        QPushButton#LiveTabButton:hover {
            background:#F0F5FF; border-color:#9DB7E2;
        }
        QPushButton#LiveTabButton:checked {
            background:#E8F1FF; border:1px solid #2868E8;
        }
        QPushButton#ToolbarButton {
            padding:0 11px; text-align:left;
            background:#FFFFFF; color:#2868E8; border:1px solid #B8C8DB;
        }
        QPushButton#ToolbarButton:hover {
            background:#EEF4FF; border-color:#9DB7E2;
        }
        QPushButton#StartLiveButton {
            padding:0 11px; text-align:left;
            background:#2868E8; color:#FFFFFF; border:1px solid #2868E8;
            font-weight:800;
        }
        QPushButton#StartLiveButton:hover {
            background:#1F58CC; color:#FFFFFF; border-color:#1F58CC;
        }
        QPushButton#StartLiveButton:pressed {
            background:#184BAE; color:#FFFFFF; border-color:#184BAE;
        }

        QFrame#ViewerCard, QFrame#SummaryPanel, QFrame#HistoryCard,
        QFrame#AnomalyMain, QFrame#AnomalySide {
            background:#FFFFFF; border:1px solid #BFCEDF; border-radius:14px;
        }
        QFrame#ViewerHeader, QFrame#SummaryHeader, QFrame#HistoryHeader {
            background:#FFFFFF; border:0; border-bottom:1px solid #DCE4EE;
        }
        QLabel#SectionTitle {
            color:#17263D; font-size:11.8px; font-weight:840;
        }
        QLabel#SectionSubtitle {
            color:#60738B; font-size:9.0px; font-weight:620;
        }
        QLabel#LiveBadge {
            border-radius:9px; padding:4px 7px; font-size:7.4px; font-weight:850;
        }
        QLabel#LiveBadge[mode="idle"] {
            background:#F1F5FA; color:#66788E; border:1px solid #DCE4EE;
        }
        QLabel#LiveBadge[mode="live"] {
            background:#EEF4FF; color:#2868E8; border:1px solid #D2E1FB;
        }

        QWidget#CameraGridHost { background:#F7F9FC; }

        QFrame#CameraCard {
            background:#FFFFFF; border:1px solid #C8D5E5; border-radius:11px;
        }
        QFrame#CameraCard:hover {
            border:1px solid #9CB6DD;
        }
        QFrame#CameraCard[result="good"] {
            border:1px solid #9FD5BA;
        }
        QFrame#CameraCard[result="ng"] {
            border:1px solid #E7A9B2;
        }
        QFrame#CameraCardHeader, QFrame#CameraCardFooter {
            background:#FFFFFF; border:0;
        }
        QFrame#CameraCardHeader { border-bottom:1px solid #DDE5EF; }
        QFrame#CameraCardFooter { border-top:1px solid #DDE5EF; }
        QLabel#CameraName { color:#20324B; font-size:8.8px; font-weight:820; }
        QLabel#CameraSerial { color:#77879A; font-size:7.5px; font-family:Consolas; }
        QLabel#CameraStatus {
            border-radius:8px; padding:3px 6px; font-size:7.2px; font-weight:850;
        }
        QLabel#CameraStatus[mode="neutral"] {
            background:#F1F5FA; color:#65778D;
        }
        QLabel#CameraStatus[mode="good"] {
            background:#E7F8F0; color:#078A57;
        }
        QLabel#CameraStatus[mode="ng"] {
            background:#FFF0F3; color:#C93450;
        }
        QLabel#CameraImage {
            background:#111827; color:#8492A6; border:0;
            font-size:9px; font-weight:650;
        }
        QLabel#CameraMeta {
            color:#526A86; font-size:7.8px; font-weight:650;
        }

        QFrame#CurrentResult {
            background:#FBFCFE; border:1px solid #D0DBE8; border-radius:10px;
            margin:10px 10px 8px 10px;
        }
        QLabel#CurrentResultPill {
            border-radius:10px; padding:5px 10px; font-size:9.5px; font-weight:900;
        }
        QLabel#CurrentResultPill[mode="neutral"] {
            background:#F1F5FA; color:#65778D;
        }
        QLabel#CurrentResultPill[mode="good"] {
            background:#E7F8F0; color:#078A57;
        }
        QLabel#CurrentResultPill[mode="ng"] {
            background:#FFF0F3; color:#C93450;
        }

        QFrame#KpiCard {
            background:#FBFCFE; border:1px solid #D0DBE8; border-radius:9px;
        }
        QLabel#SummaryCaption {
            color:#718197; font-size:7.4px; font-weight:850; letter-spacing:.35px;
        }
        QLabel#KpiValue {
            color:#17263D; font-size:16px; font-weight:850;
        }
        QLabel#KpiValue[mode="good"] { color:#07965D; }
        QLabel#KpiValue[mode="bad"] { color:#C93450; }

        QFrame#SummarySection {
            background:#FFFFFF; border:0; border-top:1px solid #E1E7EF;
            margin-top:9px;
        }
        QLabel#RailEyebrow {
            color:#60728A; font-size:7.7px; font-weight:850; letter-spacing:.65px;
        }
        QFrame#InfoRow, QFrame#SideInfoRow {
            background:#FFFFFF; border:0; border-bottom:1px solid #EEF2F6;
            min-height:29px;
        }
        QLabel#InfoKey {
            color:#60728A; font-size:8.5px; font-weight:620;
        }
        QLabel#InfoValue {
            color:#17263D; font-size:8.5px; font-weight:800;
        }
        QLabel#MiniText {
            color:#718197; font-size:7.8px; font-weight:600;
        }
        QLabel#SwitchLabel {
            color:#405873; font-size:8.8px; font-weight:720;
        }

        QFrame#SummaryActions {
            background:#FCFDFE; border:0; border-top:1px solid #DCE4EE;
        }
        QPushButton#SecondaryButton, QPushButton#DangerButton {
            min-height:34px; border-radius:8px; padding:0 10px;
            font-size:8.7px; font-weight:780;
        }
        QPushButton#SecondaryButton {
            background:#FFFFFF; color:#2868E8; border:1px solid #B8C8DB;
        }
        QPushButton#SecondaryButton:hover { background:#EEF4FF; }
        QPushButton#DangerButton {
            background:#FFFFFF; color:#C93450; border:1px solid #E3B6BE;
        }
        QPushButton#DangerButton:hover { background:#FFF3F5; }

        QFrame#HistoryStat {
            background:#FFFFFF; border:1px solid #C4D2E2; border-radius:10px;
        }
        QLabel#HistoryStatValue {
            color:#17263D; font-size:14px; font-weight:850;
        }
        QLabel#HistoryStatValue[mode="good"] { color:#07965D; }
        QLabel#HistoryStatValue[mode="bad"] { color:#C93450; }

        QFrame#HistoryItem {
            background:#FFFFFF; border:1px solid #C8D5E5; border-radius:9px;
        }
        QFrame#HistoryItem:hover {
            border:1px solid #9AB5E0;
        }
        QLabel#HistoryImage {
            background:#111827; color:#7B8AA0; border:0;
        }
        QFrame#HistoryFooter {
            background:#FFFFFF; border:0; border-top:1px solid #DCE4EE;
        }
        QLabel#HistoryText {
            color:#405873; font-size:7.7px; font-weight:720;
        }
        QLabel#HistoryStatus {
            border-radius:7px; padding:3px 5px; font-size:6.9px; font-weight:850;
        }
        QLabel#HistoryStatus[mode="good"] {
            background:#E7F8F0; color:#078A57;
        }
        QLabel#HistoryStatus[mode="ng"] {
            background:#FFF0F3; color:#C93450;
        }

        QLabel#AnomalyPreview {
            background:#111827; color:#8291A5; border:1px solid #C7D4E4;
            border-radius:10px; font-size:9px; font-weight:650;
        }
        QLabel#AnomalyResult {
            min-width:150px; border-radius:11px; padding:6px 13px;
            font-size:9.7px; font-weight:900; margin-bottom:2px;
        }
        QLabel#AnomalyResult[mode="neutral"] {
            background:#F1F5FA; color:#65778D; border:1px solid #DCE4EE;
        }
        QLabel#AnomalyResult[mode="good"] {
            background:#E7F8F0; color:#078A57; border:1px solid #CDEBDE;
        }
        QLabel#AnomalyResult[mode="ng"] {
            background:#FFF0F3; color:#C93450; border:1px solid #F0CED5;
        }
        QFrame#AnomalyToolbar {
            background:#FCFDFE; border:0; border-top:1px solid #DCE4EE;
        }
        QFrame#AnomalyStep {
            background:#FBFCFE; border:1px solid #D0DBE8; border-radius:9px;
        }
        QLabel#AnomalyStepTitle {
            color:#20324B; font-size:9.2px; font-weight:820;
        }
        QLabel#AnomalyStepText {
            color:#60738B; font-size:8.6px; font-weight:610;
        }

        QScrollBar:vertical {
            background:transparent; width:8px; margin:2px;
        }
        QScrollBar::handle:vertical {
            background:#C5D2E2; border-radius:4px; min-height:28px;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
        """)

    # ------------------------------------------------------------------
    # Context / project / camera discovery
    # ------------------------------------------------------------------
    def refresh_context(self):
        self._load_projects()
        self._load_overrides()
        self._scan_devices_async()
        self._update_context()

    def _load_projects(self):
        previous = self.selected_project_id
        projects = []
        if ProjectDB is not None:
            try:
                projects = list(ProjectDB().get_all_projects() or [])
            except Exception:
                projects = []

        self.projects = projects
        self.project_map = {_project_id(p): p for p in projects if _project_id(p)}

        self.project_selector.blockSignals(True)
        self.project_selector.clear()

        for project in projects:
            self.project_selector.addItem(
                str(project.get("name") or "Unnamed Project"),
                _project_id(project),
            )

        if projects:
            index = self.project_selector.findData(previous)
            self.project_selector.setCurrentIndex(index if index >= 0 else 0)
            self.project_selector.setEnabled(True)
            self.selected_project_id = str(self.project_selector.currentData() or "")
        else:
            self.project_selector.addItem("No projects available", "")
            self.project_selector.setEnabled(False)
            self.selected_project_id = ""

        self.project_selector.blockSignals(False)

    def _project_changed(self, _index):
        self.selected_project_id = str(self.project_selector.currentData() or "")
        self._update_context()

    def _load_overrides(self):
        self._mvs_overrides = {}
        if load_camera_overrides is None:
            return
        try:
            _arena, mvs = load_camera_overrides()
            self._mvs_overrides = dict(mvs or {})
        except Exception:
            self._mvs_overrides = {}

    def _scan_devices_async(self):
        if self._scan_thread is not None and self._scan_thread.isRunning():
            return
        self.context_cameras.setText("Checking…")
        self.health_connected.setText("Checking…")
        self._scan_thread = DeviceScanThread(self)
        self._scan_thread.scanned.connect(self._device_scan_done)
        self._scan_thread.start()

    def _device_scan_done(self, devices, error):
        self._detected_devices = list(devices or [])
        count = len(self._detected_devices)

        configured = max(1, int(self._session_cfg.get("num_cams") or 1))
        if self._session_cfg.get("backend"):
            detected_count = min(count, configured)
            self.context_cameras.setText(
                f"{configured} configured · {detected_count} detected"
            )
            self.health_connected.setText(
                f"{detected_count} / {configured} configured"
            )
            if not self._capture_running:
                self._apply_configured_camera_slots()
        elif error and not count:
            self.context_cameras.setText("Not available")
            self.health_connected.setText("0 connected")
        else:
            self.context_cameras.setText(f"{count} connected · {self._device_text()}")
            self.health_connected.setText(f"{count} connected")

        if self._detected_devices:
            try:
                self._anomaly_cam_index = int(self._detected_devices[0].index)
                self.preview_camera_health.setText("Camera 01")
            except Exception:
                pass
        else:
            self.preview_camera_health.setText("No camera")

    def _device_text(self):
        device = str(self._session_cfg.get("device") or "cuda")
        if device.lower().startswith("cuda"):
            return "CUDA"
        return device.upper()

    def _update_context(self):
        backend = self._session_cfg.get("backend")
        weights = self._session_cfg.get("weights")
        if backend and weights:
            self.context_inference.setText(
                f"{str(backend).upper()} · {Path(str(weights)).name}"
            )
        else:
            self.context_inference.setText("Not configured")

        mode = self.context_mode.text()
        if self._session_cfg.get("backend"):
            configured = max(1, int(self._session_cfg.get("num_cams") or 1))
            detected = min(len(self._detected_devices), configured)
            self.context_cameras.setText(f"{configured} configured · {detected} detected")
            self.health_connected.setText(f"{detected} / {configured} configured")
        elif self._detected_devices:
            self.context_cameras.setText(
                f"{len(self._detected_devices)} connected · {self._device_text()}"
            )
        self.health_device.setText(self._device_text())

    # ------------------------------------------------------------------
    # View switching
    # ------------------------------------------------------------------
    def _switch_view(self, key: str):
        mapping = {
            "live": self.live_view,
            "history": self.history_view,
            "anomaly": self.anomaly_view,
        }

        for name, button in self.tab_buttons.items():
            button.setChecked(name == key)

        self.stack.setCurrentWidget(mapping[key])

        if key == "history":
            self._stop_anomaly_preview()
            self.load_previous_inspections()
        elif key == "anomaly":
            self._start_anomaly_preview()
        else:
            self._stop_anomaly_preview()

    # ------------------------------------------------------------------
    # Session configuration + live capture
    # ------------------------------------------------------------------
    def _configure_session(self) -> bool:
        max_cams = max(1, min(8, len(self._detected_devices) or 8))
        dialog = LiveConfigDialog(max_cams=max_cams, initial=self._session_cfg, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False

        self._session_cfg.update(dialog.values())
        self._infer_cfg.update({
            "backend": self._session_cfg["backend"],
            "weights": self._session_cfg["weights"],
            "num_classes": self._session_cfg["num_classes"],
            "device": self._session_cfg.get("device") or "cuda",
        })
        self.inspection_value.setText(str(self._session_cfg["backend"]).upper())

        # Build preview frames immediately after configuration. The operator
        # should see the requested camera layout before capture starts.
        self._apply_configured_camera_slots()

        self._update_context()

        self.toast_requested.emit(
            "Session configured",
            f"{str(self._session_cfg['backend']).upper()} · "
            f"{Path(self._session_cfg['weights']).name} · "
            f"{self._session_cfg['num_cams']} camera(s)",
        )
        return True

    def _apply_configured_camera_slots(self):
        """Create camera preview cards immediately from the configured count."""
        count = max(1, min(8, int(self._session_cfg.get("num_cams") or 1)))
        self._build_cards(count)
        self._dev_map = {}

        detected = list(self._detected_devices or [])
        for slot, card in enumerate(self.cards):
            if slot < len(detected):
                device = detected[slot]
                try:
                    cam_idx = int(device.index)
                except Exception:
                    cam_idx = slot

                self._dev_map[cam_idx] = slot
                card.set_device(cam_idx, self._device_label(cam_idx))
                card.status.setText("READY")
                card.serial.setToolTip(card.serial.text())
            else:
                card.cam_index = slot
                card.serial.setText("Not detected")
                card.serial.setToolTip("Camera slot configured; hardware not currently detected.")
                card.status.setText("WAITING")

            card.image.setText("Waiting for capture")

        detected_count = min(len(detected), count)
        self.viewer_meta.setText(
            f"{count} camera slot(s) configured · {detected_count} detected · ready to start"
        )
        self.context_cameras.setText(
            f"{count} configured · {detected_count} detected"
        )
        self.health_connected.setText(
            f"{detected_count} / {count} configured"
        )

        if count:
            self.preview_camera_health.setText(
                "Camera 01" if detected_count else "Camera 01 slot"
            )

    def _toggle_live(self):
        if self._capture_running:
            self._stop_capture(clear_pending=True)
            return
        self._start_live()

    def _start_live(self):
        if not self._session_cfg.get("backend") or not self._session_cfg.get("weights"):
            if not self._configure_session():
                return

        try:
            hik = _load_hik_capture()
            devices = list(hik.list_devices() or [])
        except Exception as exc:
            QMessageBox.critical(self, "Camera Error", f"Failed to list Hikrobot devices:\n{exc}")
            return

        self._detected_devices = devices
        if not devices:
            answer = QMessageBox.question(
                self,
                "No Cameras Detected",
                "No Hikrobot cameras were detected.\n\nOpen Folder Mode instead?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._start_folder_mode()
            return

        count = min(int(self._session_cfg.get("num_cams") or 1), len(devices))
        cam_indices = [int(device.index) for device in devices[:count]]

        self.context_mode.setText("Live Camera")
        self._prepare_run_dirs()
        self._make_capture_bridge(cam_indices, frames=0)
        self._set_live_running(True)

        self.toast_requested.emit(
            "Live inspection started",
            f"{count} camera(s) · {str(self._infer_cfg['backend']).upper()}",
        )

    def _make_capture_bridge(self, cam_indices, frames=0):
        self._stop_capture(clear_pending=False, quiet=True)

        self._build_cards(len(cam_indices))
        self._dev_map = {cam_idx: index for index, cam_idx in enumerate(cam_indices)}

        for cam_idx, card_index in self._dev_map.items():
            label = self._device_label(cam_idx)
            self.cards[card_index].set_device(cam_idx, label)

        exp_map = {}
        gain_map = {}
        for cam_idx in cam_indices:
            override = self._mvs_overrides.get(cam_idx) or self._mvs_overrides.get(str(cam_idx))
            if not override:
                continue
            if "ExposureTime" in override:
                exp_map[cam_idx] = float(override["ExposureTime"])
            if "Gain" in override:
                gain_map[cam_idx] = float(override["Gain"])

        out_dir = _app_root() / "captures"
        out_dir.mkdir(parents=True, exist_ok=True)

        self._cap_thread = QtCore.QThread(self)
        self._cap_worker = CaptureWorker(
            cam_indices=cam_indices,
            frames=frames,
            out_dir=str(out_dir),
            mirror=False,
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

        self._cap_thread.start()
        self._capture_running = True
        self._update_health()

    def _device_label(self, cam_idx: int):
        for device in self._detected_devices:
            try:
                if int(device.index) == int(cam_idx):
                    for attr in ("serial", "serial_number", "name", "model"):
                        value = getattr(device, attr, None)
                        if value:
                            return str(value)
            except Exception:
                continue
        return f"Device index {cam_idx}"

    def _set_live_running(self, running: bool):
        self._capture_running = bool(running)
        self.live_badge.setText("LIVE" if running else "IDLE")
        self.live_badge.setProperty("mode", "live" if running else "idle")
        self.live_badge.style().unpolish(self.live_badge)
        self.live_badge.style().polish(self.live_badge)

        self.start_btn.setText("Stop Live" if running else "Start Live")
        self.start_btn.setMinimumWidth(max(self.start_btn.minimumWidth(), 108))
        self.start_btn.icon_name = "stop" if running else "play"
        self.start_btn._icon_normal = QtGui.QIcon(_asset(f"{self.start_btn.icon_name}.svg"))
        self.start_btn._icon_active = QtGui.QIcon(_asset(f"{self.start_btn.icon_name}_active.svg"))
        self.start_btn.update()

        self.viewer_meta.setText(
            f"{len(self.cards)} active stream(s) · inference overlay shown after each frame"
            if running
            else "Waiting for live session"
        )
        self.health_capture.setText("Running" if running else "Idle")

    def _stop_capture(self, clear_pending=False, quiet=False):
        worker = self._cap_worker
        thread = self._cap_thread

        try:
            if worker is not None:
                worker.stop()
        except Exception:
            pass

        try:
            if thread is not None and thread.isRunning():
                thread.quit()
                thread.wait(2200)
        except Exception:
            pass

        self._capture_running = False
        self._cap_worker = None
        self._cap_thread = None

        if clear_pending:
            self._pending.clear()
            self._inflight = False

        self._set_live_running(False)
        self._update_health()

        if not quiet:
            self.toast_requested.emit("Capture stopped", "Live capture was stopped gracefully.")

    # ------------------------------------------------------------------
    # Capture -> inference queue
    # ------------------------------------------------------------------
    @QtCore.pyqtSlot(int, int, str)
    def _on_frame_captured_and_enqueue(self, cam_index: int, frame_idx: int, img_path: str):
        if not img_path or not Path(img_path).is_file():
            return
        self._pending.append((cam_index, img_path))
        self.pending_value.setText(str(len(self._pending)))
        self._kick_next_inference()

    def _on_capture_error(self, message: str):
        self._set_live_running(False)
        self.toast_requested.emit("Capture error", str(message))

    def _on_capture_finished(self):
        self._capture_running = False
        self._set_live_running(False)
        self._kick_next_inference()

    @QtCore.pyqtSlot(int)
    def _on_cycle_tick(self, number: int):
        self.cycle_count = int(number)
        self.cycle_value.setText(str(number))

    def _kick_next_inference(self):
        if self._inflight or not self._pending:
            self.pending_value.setText(str(len(self._pending)))
            return

        if not self._infer_cfg.get("backend") or not self._infer_cfg.get("weights"):
            self.toast_requested.emit(
                "Inference not configured",
                "Configure the inference backend and model weights first.",
            )
            return

        if not self._infer_cfg.get("out_dir"):
            self._prepare_run_dirs()

        cam_index, img_path = self._pending.popleft()
        self.pending_value.setText(str(len(self._pending)))
        self._current_input[cam_index] = img_path

        ip_dir = self._infer_cfg.get("ip_dir")
        if ip_dir:
            try:
                Path(ip_dir).mkdir(parents=True, exist_ok=True)
                target = Path(ip_dir) / Path(img_path).name
                if not target.exists():
                    shutil.copy2(img_path, target)
            except Exception:
                pass

        self._inflight = True
        future = self._infer_pool.submit(
            self._run_inference_on_image,
            self._infer_cfg["backend"],
            self._infer_cfg["weights"],
            img_path,
            self._infer_cfg["out_dir"],
            self._infer_cfg.get("num_classes"),
        )

        def done(fut):
            try:
                overlay, is_ng, score_text = fut.result()
            except Exception as exc:
                overlay, is_ng, score_text = img_path, False, f"ERROR: {exc}"
            self.infer_result.emit(cam_index, overlay or img_path, bool(is_ng), str(score_text))

        future.add_done_callback(done)

    def _run_inference_on_image(self, backend, weights, image_path, out_dir, num_classes):
        if str(backend).lower() == "yolo":
            return self._yolo_predict_and_save(weights, image_path, out_dir)

        infer = _load_inference_module()
        return infer.detectron_predict_single(
            weights=weights,
            image_path=image_path,
            out_dir=out_dir,
            num_classes=(num_classes or 1),
        )

    def _ensure_yolo(self, weights: str):
        if self._yolo_infer is not None and self._yolo_weights == weights:
            return
        infer = _load_inference_module()
        self._yolo_infer = infer.UnifiedYOLOInferencer(
            weights=weights,
            device=self._infer_cfg.get("device") or None,
            allow_cpu_fallback=True,
        )
        self._yolo_weights = weights

    def _yolo_predict_and_save(self, weights: str, image_path: str, out_dir: str):
        self._ensure_yolo(weights)
        infer = _load_inference_module()

        image = cv2.imread(image_path)
        if image is None:
            raise RuntimeError(f"Cannot read image: {image_path}")

        detections, _ = self._yolo_infer.predict_image(image)
        visual = infer.draw_vis(image, detections)

        Path(out_dir).mkdir(parents=True, exist_ok=True)
        output = str(Path(out_dir) / Path(image_path).name)
        cv2.imwrite(output, visual)

        is_ng = len(detections) > 0
        if detections:
            top = max(detections, key=lambda item: item.get("conf", 0.0))
            name = str(top.get("name", top.get("cls", "?")))
            confidence = float(top.get("conf", 0.0))
            score = f"{name} {confidence:.2f}"
        else:
            score = "GOOD"

        return output, is_ng, score

    @QtCore.pyqtSlot(int, str, bool, str)
    def _apply_infer_result(self, cam_index: int, overlay_path: str, is_ng: bool, score_text: str):
        position = self._dev_map.get(cam_index, 0)
        if self.cards:
            position = max(0, min(position, len(self.cards) - 1))
            card = self.cards[position]
            card.set_image(overlay_path)

            class_name, score_display, numeric_score = self._parse_score(score_text, is_ng)
            card.set_result(is_ng, score_display, class_name)

            if is_ng:
                self.bad += 1
            else:
                self.good += 1

            self.current_result_meta.setText(f"Cycle {self.cycle_count} · Camera {position + 1:02d}")
            self._set_current_result(is_ng)

        self._last_is_ng = bool(is_ng)
        self._refresh_summary()

        # Keep the original live database record structure and binary images.
        if insert_live_record is not None:
            try:
                input_path = self._current_input.get(cam_index)
                input_bytes = Path(input_path).read_bytes() if input_path and Path(input_path).is_file() else None
                output_bytes = Path(overlay_path).read_bytes() if overlay_path and Path(overlay_path).is_file() else None

                class_name, _score_display, numeric_score = self._parse_score(score_text, is_ng)
                doc = {
                    "cam_index": cam_index,
                    "good_count": self.good,
                    "bad_count": self.bad,
                    "total_count": self.good + self.bad,
                    "cycle": self.cycle_count,
                    "inspection_type": str(self._infer_cfg.get("backend") or "").upper(),
                    "score_text": score_text,
                    "class_name": class_name,
                    "score": numeric_score,
                    "is_ng": bool(is_ng),
                    "input_image": input_bytes,
                    "output_image": output_bytes,
                    "input_filename": Path(input_path).name if input_path else None,
                    "output_filename": Path(overlay_path).name if overlay_path else None,
                    "project_id": self.selected_project_id or None,
                    "project_name": self.project_selector.currentText() if self.selected_project_id else None,
                }
                insert_live_record(doc)
            except Exception as exc:
                print(f"[live] failed to insert live record: {exc}")

        self._current_input.pop(cam_index, None)
        self._inflight = False
        QtCore.QTimer.singleShot(0, self._kick_next_inference)

    def _parse_score(self, text: str, is_ng: bool):
        value = str(text or "").strip()
        if not value:
            return ("Dimension" if is_ng else "—", "—", None)

        try:
            number = float(value)
            return "Dimension", f"{number:.2f}", number
        except Exception:
            pass

        if value.upper() == "GOOD":
            return "—", "GOOD", 1.0

        parts = value.split()
        class_name = parts[0] if parts else ("Dimension" if is_ng else "—")
        numeric = None
        if len(parts) >= 2:
            try:
                numeric = float(parts[-1])
            except Exception:
                numeric = None
        score_display = f"{numeric:.2f}" if numeric is not None else value
        return class_name, score_display, numeric

    # ------------------------------------------------------------------
    # Folder mode
    # ------------------------------------------------------------------
    def _start_folder_mode(self):
        if not self._session_cfg.get("backend") or not self._session_cfg.get("weights"):
            if not self._configure_session():
                return

        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Image Folder",
            str(Path.home()),
        )
        if not folder:
            return

        image_paths = sorted(
            str(path)
            for path in Path(folder).rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        )
        if not image_paths:
            QMessageBox.warning(self, "No Images", "No supported images were found in the selected folder.")
            return

        self._stop_capture(clear_pending=True, quiet=True)
        self.context_mode.setText("Folder Mode")
        self._infer_cfg.update({
            "backend": self._session_cfg["backend"],
            "weights": self._session_cfg["weights"],
            "num_classes": self._session_cfg["num_classes"],
            "device": self._session_cfg.get("device") or "cuda",
        })
        self._prepare_run_dirs()

        self._build_cards(1)
        self._dev_map = {0: 0}
        self.cards[0].set_device(0, Path(folder).name or "Folder Input")

        self._pending.clear()
        self._inflight = False
        for path in image_paths:
            self._pending.append((0, path))

        self.inspection_value.setText("FOLDER MODE")
        self.viewer_meta.setText(f"{len(image_paths)} image(s) queued for inference")
        self._kick_next_inference()

        self.toast_requested.emit(
            "Folder inference started",
            f"{len(image_paths)} image(s) queued.",
        )

    # ------------------------------------------------------------------
    # Cards / counters / health
    # ------------------------------------------------------------------
    def _build_cards(self, count: int):
        while self.camera_grid.count():
            item = self.camera_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.cards.clear()
        count = max(1, min(8, int(count)))

        cols = 1 if count == 1 else 2 if count <= 4 else 4
        for index in range(count):
            card = CameraCard(index)
            row, col = divmod(index, cols)
            self.camera_grid.addWidget(card, row, col)
            self.cards.append(card)

        for col in range(cols):
            self.camera_grid.setColumnStretch(col, 1)
        rows = (count + cols - 1) // cols
        for row in range(rows):
            self.camera_grid.setRowStretch(row, 1)

    def _init_counts_from_db(self):
        if get_today_live_counts is None:
            self._refresh_summary()
            return
        try:
            counts = get_today_live_counts() or {}
            self.good = int(counts.get("good", 0) or 0)
            self.bad = int(counts.get("bad", 0) or 0)
        except Exception:
            self.good = 0
            self.bad = 0
        self._refresh_summary()

    def _refresh_summary(self):
        total = self.good + self.bad
        ratio = self.bad / total * 100.0 if total else 0.0
        self.good_value.setText(str(self.good))
        self.bad_value.setText(str(self.bad))
        self.ratio_value.setText(f"{ratio:.2f}%")
        self.total_value.setText(str(total))
        self.pending_value.setText(str(len(self._pending)))
        self._update_health()

    def _set_current_result(self, is_ng: bool | None):
        if is_ng is None:
            mode, text = "neutral", "—"
        elif is_ng:
            mode, text = "ng", "NG"
        else:
            mode, text = "good", "GOOD"
        self.current_result.setProperty("mode", mode)
        self.current_result.setText(text)
        self.current_result.style().unpolish(self.current_result)
        self.current_result.style().polish(self.current_result)
        self.current_result.update()

    def _update_health(self):
        self.health_capture.setText("Running" if self._capture_running else "Idle")
        self.health_connected.setText(f"{len(self._detected_devices)} connected")
        self.health_device.setText(self._device_text())

    def _reset_all(self):
        answer = QMessageBox.question(
            self,
            "Reset Inspection Counts",
            "Reset the displayed GOOD/NG counts and clear camera images?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.good = 0
        self.bad = 0
        self._last_is_ng = None
        self._set_current_result(None)
        self.current_result_meta.setText("No inspection yet")
        for card in self.cards:
            card.clear_result()
        self._refresh_summary()
        self.toast_requested.emit("Counts reset", "Displayed inspection counts and images were cleared.")

    def _tick(self):
        elapsed = int(time.time() - self.start_time)
        hh = elapsed // 3600
        mm = (elapsed % 3600) // 60
        ss = elapsed % 60
        self.uptime_value.setText(f"{hh:02d}:{mm:02d}:{ss:02d}")

    # ------------------------------------------------------------------
    # Results directories
    # ------------------------------------------------------------------
    def _prepare_run_dirs(self):
        root = _app_root() / "results"
        backend = str(self._infer_cfg.get("backend") or "yolo").lower()
        prefix = "detec" if backend == "detectron" else "yolo"

        op_root = root / f"{prefix}_op"
        ip_root = root / f"{prefix}_ip"
        op_root.mkdir(parents=True, exist_ok=True)
        ip_root.mkdir(parents=True, exist_ok=True)

        max_number = 0
        for folder in op_root.iterdir():
            if not folder.is_dir():
                continue
            name = folder.name
            try:
                number = int(name.split("_", 1)[1]) if name.startswith("trial_") else int(name)
                max_number = max(max_number, number)
            except Exception:
                continue

        trial = f"trial_{max_number + 1:03d}"
        out_dir = op_root / trial
        ip_dir = ip_root / trial
        out_dir.mkdir(parents=True, exist_ok=True)
        ip_dir.mkdir(parents=True, exist_ok=True)

        self._infer_cfg["out_dir"] = str(out_dir)
        self._infer_cfg["ip_dir"] = str(ip_dir)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------
    def load_previous_inspections(self):
        while self.history_grid.count():
            item = self.history_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if get_recent_inspections is None:
            self._update_prev_stats({})
            self._history_message("Inspection history is not available in this database version.")
            return

        try:
            inspections = list(get_recent_inspections(limit=30) or [])
        except Exception as exc:
            self._update_prev_stats({})
            self._history_message(f"Could not load inspection history: {exc}")
            return

        if not inspections:
            self._update_prev_stats({})
            self._history_message("No previous inspections found.")
            return

        total = len(inspections)
        good = sum(1 for item in inspections if not item.get("is_ng", True))
        bad = total - good
        ratio = bad / total * 100.0 if total else 0.0
        cameras = len({int(item.get("cam_index", 0) or 0) for item in inspections})

        self._update_prev_stats({
            "total": total,
            "good": good,
            "bad": bad,
            "ratio": ratio,
            "last_time": inspections[0].get("inspection_datetime"),
            "cam_count": cameras,
        })

        cols = 5
        for index, inspection in enumerate(inspections):
            widget = HistoryItem(inspection)
            row, col = divmod(index, cols)
            self.history_grid.addWidget(widget, row, col)

        for col in range(cols):
            self.history_grid.setColumnStretch(col, 1)

    def _history_message(self, text):
        label = QLabel(text, objectName="SectionSubtitle")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.history_grid.addWidget(label, 0, 0, 1, 5)

    def _update_prev_stats(self, stats: dict):
        total = int(stats.get("total", 0) or 0)
        good = int(stats.get("good", 0) or 0)
        bad = int(stats.get("bad", 0) or 0)
        ratio = float(stats.get("ratio", 0.0) or 0.0)

        self.prev_total_label.setText(str(total))
        self.prev_good_label.setText(str(good))
        self.prev_bad_label.setText(str(bad))
        self.prev_ratio_label.setText(f"{ratio:.2f}%")
        self.prev_cam_count.setText(str(int(stats.get("cam_count", 0) or 0)))

        last_time = stats.get("last_time")
        if isinstance(last_time, datetime):
            self.prev_last_time.setText(last_time.strftime("%H:%M:%S"))
        elif last_time:
            text = str(last_time)
            self.prev_last_time.setText(text[11:19] if len(text) >= 19 else text)
        else:
            self.prev_last_time.setText("—")

    # ------------------------------------------------------------------
    # Anomaly workflow
    # ------------------------------------------------------------------
    def _start_anomaly_preview(self):
        if self.anomaly_timer.isActive():
            return

        if not self._capture_running:
            if self._detected_devices:
                try:
                    self._anomaly_cam_index = int(self._detected_devices[0].index)
                except Exception:
                    self._anomaly_cam_index = None
            elif self._anomaly_cam_index is None:
                self._scan_devices_async()

        self._update_anomaly_preview()
        self.anomaly_timer.start()

    def _stop_anomaly_preview(self):
        if self.anomaly_timer.isActive():
            self.anomaly_timer.stop()

    def _update_anomaly_preview(self):
        if self._capture_running and self.cards:
            pixmap = self.cards[0].current_pixmap()
            if not pixmap.isNull():
                self._show_anomaly_pixmap(pixmap)
                qimg = pixmap.toImage().convertToFormat(QtGui.QImage.Format.Format_Grayscale8)
                width = qimg.width()
                height = qimg.height()
                ptr = qimg.bits()
                ptr.setsize(height * qimg.bytesPerLine())
                array = np.frombuffer(ptr, np.uint8).reshape((height, qimg.bytesPerLine()))
                self._anomaly_last_frame = array[:, :width].copy()
                return

        cam_idx = self._anomaly_cam_index
        if cam_idx is None:
            self.anomalyPreviewLabel.setPixmap(QtGui.QPixmap())
            self.anomalyPreviewLabel.setText("No camera detected")
            self._anomaly_last_frame = None
            return

        override = self._mvs_overrides.get(cam_idx) or self._mvs_overrides.get(str(cam_idx)) or {}
        exposure = float(override["ExposureTime"]) if "ExposureTime" in override else None
        gain = float(override["Gain"]) if "Gain" in override else None

        try:
            hik = _load_hik_capture()
            frame = hik.grab_live_frame(
                index=cam_idx,
                exposure_us=exposure,
                gain_db=gain,
                mirror=False,
            )
        except Exception:
            frame = None

        if frame is None:
            self.anomalyPreviewLabel.setPixmap(QtGui.QPixmap())
            self.anomalyPreviewLabel.setText("Camera preview not available")
            self._anomaly_last_frame = None
            return

        frame = np.asarray(frame)
        if frame.ndim == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        frame = np.ascontiguousarray(frame)
        self._anomaly_last_frame = frame.copy()

        qimg = QtGui.QImage(
            frame.data,
            frame.shape[1],
            frame.shape[0],
            int(frame.strides[0]),
            QtGui.QImage.Format.Format_Grayscale8,
        ).copy()
        self._show_anomaly_pixmap(QtGui.QPixmap.fromImage(qimg))

    def _show_anomaly_pixmap(self, pixmap: QtGui.QPixmap):
        if pixmap.isNull():
            return
        scaled = pixmap.scaled(
            self.anomalyPreviewLabel.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.anomalyPreviewLabel.setPixmap(scaled)
        self.anomalyPreviewLabel.setText("")

    def _set_anomaly_result(self, mode: str, text: str):
        self.anomalyResultLabel.setProperty("mode", mode)
        self.anomalyResultLabel.setText(text)
        self.anomalyResultLabel.style().unpolish(self.anomalyResultLabel)
        self.anomalyResultLabel.style().polish(self.anomalyResultLabel)
        self.anomalyResultLabel.update()

    def _handle_template_creation(self):
        if self._anomaly_last_frame is None:
            QMessageBox.warning(
                self,
                "No Preview Frame",
                "No live preview frame is available yet.",
            )
            return

        root = _app_root() / "templates"
        good_dir = root / "good"
        exist_dir = root / "Exist"
        good_dir.mkdir(parents=True, exist_ok=True)
        exist_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        good_path = good_dir / f"good_{stamp}.png"
        exist_path = exist_dir / f"good_{stamp}.png"

        frame = np.asarray(self._anomaly_last_frame)
        if not cv2.imwrite(str(good_path), frame):
            QMessageBox.critical(self, "Save Error", f"Failed to save:\n{good_path}")
            return
        cv2.imwrite(str(exist_path), frame)

        self._last_good_template_path = str(good_path)
        self.template_health.setText("Ready")
        self._stop_anomaly_preview()
        self._show_anomaly_pixmap(self._pixmap_from_gray(frame))
        self._set_anomaly_result("good", "TEMPLATE SAVED")
        self.toast_requested.emit("Template saved", good_path.name)

    def _capture_one_image_for_template(self, cam_index: int, mode: str):
        try:
            hik = _load_hik_capture()
            out_dir = _app_root() / "captures_template"
            out_dir.mkdir(parents=True, exist_ok=True)

            saved = {"path": ""}

            def callback(_index, _frame, path):
                saved["path"] = str(path)

            override = self._mvs_overrides.get(cam_index) or self._mvs_overrides.get(str(cam_index)) or {}
            exposure = float(override["ExposureTime"]) if "ExposureTime" in override else None
            gain = float(override["Gain"]) if "Gain" in override else None

            hik.capture_multi(
                indices=[cam_index],
                frames=1,
                base_out=str(out_dir),
                mirror=False,
                exposure_us=exposure,
                gain_db=gain,
                progress_cb=callback,
            )

            if not saved["path"]:
                return ""

            old = Path(saved["path"])
            new = old.parent / f"{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{old.suffix or '.png'}"
            try:
                old.replace(new)
                return str(new)
            except Exception:
                return str(old)

        except Exception as exc:
            print(f"[template-capture] {exc}")
            return ""

    def _handle_anomaly_detection(self):
        cam_idx = self._anomaly_cam_index
        if cam_idx is None and self._detected_devices:
            try:
                cam_idx = int(self._detected_devices[0].index)
            except Exception:
                cam_idx = None
        if cam_idx is None:
            QMessageBox.warning(self, "No Camera", "No camera is available for anomaly capture.")
            return

        good_path = self._latest_image(_app_root() / "templates" / "good")
        if not good_path:
            QMessageBox.warning(
                self,
                "No GOOD Template",
                "Create a GOOD template first using Template Creation.",
            )
            return

        threshold, ok = QtWidgets.QInputDialog.getDouble(
            self,
            "Template Threshold",
            "Similarity threshold (0–1):",
            0.9999997,
            0.0,
            1.0,
            7,
        )
        if not ok:
            return

        self._stop_anomaly_preview()
        self.anomalyPreviewLabel.setPixmap(QtGui.QPixmap())
        self.anomalyPreviewLabel.setText("Capturing current frame…")
        QtWidgets.QApplication.processEvents()

        bad_path = self._capture_one_image_for_template(cam_idx, "bad")
        if not bad_path:
            self._start_anomaly_preview()
            QMessageBox.warning(self, "Capture failed", "Could not capture the current image.")
            return

        bad_dir = _app_root() / "templates" / "bad"
        bad_dir.mkdir(parents=True, exist_ok=True)
        final_bad = bad_dir / Path(bad_path).name
        try:
            if Path(bad_path).resolve() != final_bad.resolve():
                shutil.copy2(bad_path, final_bad)
                bad_path = str(final_bad)
        except Exception:
            pass

        self._run_template_match_async(good_path, bad_path, threshold)

    def _handle_anomaly_load(self):
        good_path = self._latest_image(_app_root() / "templates" / "good")
        if not good_path:
            QMessageBox.warning(
                self,
                "No GOOD Template",
                "Create a GOOD template first using Template Creation.",
            )
            return

        bad_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select BAD / Defect Image",
            str(_app_root() / "templates"),
            "Image Files (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;All Files (*)",
        )
        if not bad_path:
            return

        threshold, ok = QtWidgets.QInputDialog.getDouble(
            self,
            "Template Threshold",
            "Similarity threshold (0–1):",
            0.9999995,
            0.0,
            1.0,
            7,
        )
        if not ok:
            return

        self._stop_anomaly_preview()
        self._run_template_match_async(good_path, bad_path, threshold)

    def _run_template_match_async(self, good_path: str, bad_path: str, threshold: float):
        self.anomalyPreviewLabel.setPixmap(QtGui.QPixmap())
        self.anomalyPreviewLabel.setText("Processing anomaly comparison…")
        self._set_anomaly_result("neutral", "PROCESSING")

        future = self._anomaly_pool.submit(
            self._template_match_job,
            str(good_path),
            str(bad_path),
            float(threshold),
        )

        def done(fut):
            try:
                similarity, overlay, decision, bad = fut.result()
                self.anomaly_match_result.emit(float(similarity), str(overlay), str(decision), str(bad))
            except Exception as exc:
                self.anomaly_match_result.emit(-1.0, "", f"ERROR:{exc}", str(bad_path))

        future.add_done_callback(done)

    def _template_match_job(self, good_path, bad_path, threshold):
        matcher = _load_template_matcher()
        similarity, overlay_path, decision = matcher(
            good_img_path=good_path,
            bad_img_path=bad_path,
            threshold=threshold,
        )
        return similarity, overlay_path, decision, bad_path

    @QtCore.pyqtSlot(float, str, str, str)
    def _apply_anomaly_match_result(self, similarity, overlay_path, decision, bad_path):
        if decision.startswith("ERROR:"):
            self._set_anomaly_result("ng", "ERROR")
            self.anomalyPreviewLabel.setText(decision[6:])
            return

        is_ng = decision.upper() == "BAD"
        self._set_anomaly_result("ng" if is_ng else "good", "ANOMALIES OBSERVED" if is_ng else "NO ANOMALIES")

        output_dir = _app_root() / "templates" / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        source = Path(overlay_path) if overlay_path and Path(overlay_path).is_file() else Path(bad_path)
        final = output_dir / f"overlay_{stamp}{source.suffix or '.png'}"
        try:
            shutil.copy2(source, final)
        except Exception:
            final = source

        pixmap = QtGui.QPixmap(str(final))
        if not pixmap.isNull():
            self._show_anomaly_pixmap(pixmap)
        else:
            self.anomalyPreviewLabel.setText("Overlay image could not be loaded.")

        self.toast_requested.emit(
            "Anomaly result",
            f"{decision.upper()} · similarity {similarity:.6f}",
        )

    def _handle_anomaly_clear(self):
        self.anomalyPreviewLabel.clear()
        self.anomalyPreviewLabel.setText("Live preview will appear here")
        self._anomaly_last_frame = None
        self._set_anomaly_result("neutral", "—")
        self._start_anomaly_preview()

    def _latest_image(self, folder: Path):
        if not folder.is_dir():
            return None
        images = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
        if not images:
            return None
        return str(max(images, key=lambda p: p.stat().st_mtime))

    def _pixmap_from_gray(self, frame):
        frame = np.ascontiguousarray(frame)
        image = QtGui.QImage(
            frame.data,
            frame.shape[1],
            frame.shape[0],
            int(frame.strides[0]),
            QtGui.QImage.Format.Format_Grayscale8,
        ).copy()
        return QtGui.QPixmap.fromImage(image)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def shutdown(self):
        self._stop_anomaly_preview()
        try:
            self.timer.stop()
        except Exception:
            pass

        self._stop_capture(clear_pending=True, quiet=True)

        try:
            if self._scan_thread is not None and self._scan_thread.isRunning():
                self._scan_thread.quit()
                self._scan_thread.wait(800)
        except Exception:
            pass

        try:
            self._infer_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

        try:
            self._anomaly_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


LivePage = LivePageQt6
