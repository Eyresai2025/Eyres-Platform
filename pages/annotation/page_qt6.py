"""EYRES AI - Final PyQt6 Annotation Tool.

UI finalized from the approved Annotation Tool V3 preview.

Preserved current annotation capabilities:
- Rectangle / Polygon / Select
- Move / resize selections using the existing canvas interaction logic
- Edit / Delete / Copy / Paste
- Undo / Redo
- Ctrl+mouse-wheel zoom + fit
- Previous / Next + thumbnail navigation
- Existing LabelMe JSON auto-load/export
- Pascal VOC XML export for rectangle annotations
- Auto-save in session memory
- Save Current
- Final Save & Verify
- Overwrite Existing Files
- Existing label reuse
- Keyboard shortcuts

The old PyQt5 annotation_tool.py is intentionally not imported by the Qt6
runtime.  This page is self-contained so PyQt5 and PyQt6 widgets never mix.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from xml.dom import minidom

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from db import ProjectDB
except ImportError:  # pragma: no cover
    try:
        from src.db import ProjectDB
    except ImportError:
        from src.database.db import ProjectDB


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp")


def _annotation_asset(name: str) -> str:
    """Resolve an Annotation Tool asset from the installed EYRES project."""
    project_root = Path(__file__).resolve().parents[2]
    return str(project_root / "ui" / "assets" / "annotation_icons" / name)


def _project_id(project: dict) -> str:
    return str(project.get("_id") or project.get("id") or "")


def _safe_folder_name(value: str) -> str:
    value = "".join(c if c.isalnum() or c in "-_ " else "_" for c in str(value or "Project"))
    return value.strip().replace(" ", "_") or "Project"


class ProjectComboBox(QComboBox):
    """White project selector with a clear Qt-painted dropdown indicator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ProjectSelector")
        self.setMinimumHeight(34)
        self.setMaxVisibleItems(8)

        # A non-native list keeps the popup white on Windows even when the OS
        # or another Qt palette is using dark popup colors.
        view = QListView(self)
        view.setObjectName("ProjectSelectorView")
        view.setUniformItemSizes(True)
        view.setSpacing(1)
        view.setMinimumWidth(270)
        self.setView(view)

    def paintEvent(self, event):
        # Let Qt draw the field/text first, then paint a crisp down chevron.
        super().paintEvent(event)

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        color = QtGui.QColor("#2868E8" if self.hasFocus() else "#526A86")
        pen = QtGui.QPen(color)
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        cx = self.width() - 14.0
        cy = self.height() / 2.0 - 1.0
        painter.drawLine(
            QtCore.QPointF(cx - 4.0, cy - 2.0),
            QtCore.QPointF(cx, cy + 2.0),
        )
        painter.drawLine(
            QtCore.QPointF(cx, cy + 2.0),
            QtCore.QPointF(cx + 4.0, cy - 2.0),
        )
        painter.end()

    def showPopup(self):
        self.view().setMinimumWidth(max(270, self.width()))
        super().showPopup()
        QtCore.QTimer.singleShot(0, self._position_popup)

    def _position_popup(self):
        try:
            popup = self.view().window()
            pos = self.mapToGlobal(QtCore.QPoint(0, self.height() + 4))
            popup.move(pos)
            popup.resize(max(270, self.width()), popup.height())
        except Exception:
            pass


class AnnotationToolButton(QPushButton):
    """Crisp vector tool icon + the same subtle hover tilt used in the shell."""

    def __init__(
        self,
        icon_kind: str,
        text: str,
        *,
        checkable: bool = False,
        parent=None,
    ):
        super().__init__(text, parent)
        self.icon_kind = icon_kind
        self._motion = 0.0
        self._hovered = False

        self.setObjectName("ToolButton")
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(54, 54)

        self._motion_anim = QtCore.QPropertyAnimation(self, b"iconMotion", self)
        self._motion_anim.setDuration(190)
        self._motion_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)

        self._external_icons = {}
        if self.icon_kind in {"undo", "redo"}:
            self._external_icons["normal"] = QtGui.QIcon(
                _annotation_asset(f"{self.icon_kind}.svg")
            )
            self._external_icons["active"] = QtGui.QIcon(
                _annotation_asset(f"{self.icon_kind}_active.svg")
            )

    def get_icon_motion(self) -> float:
        return self._motion

    def set_icon_motion(self, value: float):
        self._motion = max(0.0, min(1.0, float(value)))
        self.update()

    iconMotion = QtCore.pyqtProperty(
        float,
        fget=get_icon_motion,
        fset=set_icon_motion,
    )

    def _animate_icon(self, target: float):
        self._motion_anim.stop()
        self._motion_anim.setStartValue(self._motion)
        self._motion_anim.setEndValue(float(target))
        self._motion_anim.start()

    def enterEvent(self, event):
        self._hovered = True
        self._animate_icon(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._animate_icon(0.0)
        super().leaveEvent(event)

    @staticmethod
    def _vector_pen(painter, color, width=1.75):
        pen = QtGui.QPen(QtGui.QColor(color))
        pen.setWidthF(width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_icon(self, painter: QtGui.QPainter, kind: str, color: str):
        self._vector_pen(painter, color)

        if kind == "select":
            path = QtGui.QPainterPath()
            path.moveTo(-7.0, -8.0)
            path.lineTo(7.5, -1.0)
            path.lineTo(1.5, 1.5)
            path.lineTo(4.8, 8.0)
            path.lineTo(1.0, 9.5)
            path.lineTo(-2.0, 3.0)
            path.lineTo(-6.5, 7.0)
            path.closeSubpath()
            painter.drawPath(path)

        elif kind == "rectangle":
            painter.drawRoundedRect(
                QtCore.QRectF(-8.0, -6.0, 16.0, 12.0),
                1.5, 1.5,
            )

        elif kind == "polygon":
            poly = QtGui.QPolygonF([
                QtCore.QPointF(0.0, -9.0),
                QtCore.QPointF(8.0, -3.0),
                QtCore.QPointF(5.0, 7.0),
                QtCore.QPointF(-5.0, 7.0),
                QtCore.QPointF(-8.0, -3.0),
            ])
            painter.drawPolygon(poly)

        elif kind == "keyboard":
            painter.drawRoundedRect(
                QtCore.QRectF(-9.0, -6.0, 18.0, 12.0),
                2.0, 2.0,
            )
            painter.setBrush(QtGui.QColor(color))
            painter.setPen(Qt.PenStyle.NoPen)
            for yy in (-2.8, 1.0):
                for xx in (-5.5, -1.8, 1.9, 5.6):
                    painter.drawRoundedRect(
                        QtCore.QRectF(xx - 1.1, yy - .8, 2.2, 1.6),
                        .5, .5,
                    )
            painter.drawRoundedRect(
                QtCore.QRectF(-4.0, 4.0, 8.0, 1.5),
                .5, .5,
            )

    def _draw_external_icon(self, painter: QtGui.QPainter, active: bool):
        icon = self._external_icons.get("active" if active else "normal")
        if icon is None or icon.isNull():
            return False

        # Render from the bundled SVG at high device-independent resolution.
        pixmap = icon.pixmap(QtCore.QSize(24, 24))
        if pixmap.isNull():
            return False

        painter.drawPixmap(
            QtCore.QRectF(-12.0, -12.0, 24.0, 24.0),
            pixmap,
            QtCore.QRectF(pixmap.rect()),
        )
        return True

    def paintEvent(self, event):
        # QStyle draws the QSS-driven background / border. We paint the icon and
        # text ourselves to guarantee the same spacing and clarity as the HTML.
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        option = QtWidgets.QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        option.icon = QtGui.QIcon()
        self.style().drawControl(
            QtWidgets.QStyle.ControlElement.CE_PushButton,
            option,
            painter,
            self,
        )

        active = self.isChecked()
        icon_color = "#1D5BD0" if (active or self._hovered) else "#405B78"

        # Hover animation: tilt, tiny lift and small scale.
        motion = self._motion
        painter.save()
        painter.translate(self.width() / 2.0, 18.5 - motion)
        painter.rotate(-6.0 * motion)
        painter.scale(1.0 + 0.075 * motion, 1.0 + 0.075 * motion)

        if self.icon_kind in {"undo", "redo"}:
            self._draw_external_icon(
                painter,
                active=(active or self._hovered),
            )
        else:
            self._draw_icon(painter, self.icon_kind, icon_color)

        painter.restore()

        font = self.font()
        font.setPointSizeF(8.0)
        font.setWeight(QtGui.QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QtGui.QColor("#1D5BD0" if active else "#405B78"))
        painter.drawText(
            QtCore.QRectF(2.0, 33.0, self.width() - 4.0, 17.0),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )
        painter.end()


class LabelSelectionDialog(QDialog):
    def __init__(self, labels: list[str], current: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Label")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.selected_label = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(9)

        layout.addWidget(QLabel("Select or enter a label", objectName="DialogTitle"))

        self.list_widget = QListWidget(objectName="LabelList")
        self.list_widget.addItems(labels)
        self.list_widget.itemDoubleClicked.connect(
            lambda item: self._accept_value(item.text())
        )
        self.list_widget.setMinimumHeight(155)
        layout.addWidget(self.list_widget)

        self.input = QLineEdit(current, objectName="DialogInput")
        self.input.setPlaceholderText("Enter label")
        self.input.returnPressed.connect(lambda: self._accept_value(self.input.text()))
        layout.addWidget(self.input)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel", objectName="DialogSecondary")
        save = QPushButton("Use Label", objectName="DialogPrimary")
        cancel.clicked.connect(self.reject)
        save.clicked.connect(lambda: self._accept_value(self.input.text()))
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self.setStyleSheet("""
        QDialog { background:#FFFFFF; color:#101A2D; }
        QLabel#DialogTitle { font-size:14px; font-weight:800; }
        QListWidget#LabelList, QLineEdit#DialogInput {
            background:#FFFFFF; color:#17263D; border:1px solid #BFCEDF;
            border-radius:9px; padding:7px; font-size:10px;
        }
        QListWidget#LabelList::item { min-height:29px; border-radius:6px; padding:3px 6px; }
        QListWidget#LabelList::item:selected { background:#E5EEFF; color:#1D5BD0; }
        QPushButton#DialogPrimary, QPushButton#DialogSecondary {
            min-height:35px; border-radius:8px; padding:0 13px;
            font-size:9.5px; font-weight:750;
        }
        QPushButton#DialogPrimary { background:#2868E8; color:white; border:1px solid #2868E8; }
        QPushButton#DialogSecondary { background:white; color:#405873; border:1px solid #BFCEDF; }
        """)

    def _accept_value(self, value: str):
        value = str(value or "").strip()
        if not value and self.list_widget.currentItem():
            value = self.list_widget.currentItem().text().strip()
        if value:
            self.selected_label = value
            self.accept()


class SaveFormatDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Save Format")
        self.setModal(True)
        self.setMinimumWidth(430)
        self.format_choice = "json"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(9)

        layout.addWidget(QLabel("Select Save Format", objectName="DialogTitle"))
        layout.addWidget(QLabel("Choose the annotation export format.", objectName="DialogSub"))

        self.json_btn = QPushButton("JSON · LabelMe\nImage metadata + rectangle/polygon geometry", objectName="FormatChoice")
        self.xml_btn = QPushButton("XML · Pascal VOC\nBounding-box object-detection format", objectName="FormatChoice")
        for button in (self.json_btn, self.xml_btn):
            button.setCheckable(True)
            button.setMinimumHeight(58)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            layout.addWidget(button)
        self.json_btn.setChecked(True)

        self.json_btn.clicked.connect(lambda: self._select("json"))
        self.xml_btn.clicked.connect(lambda: self._select("xml"))

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = QPushButton("Cancel", objectName="DialogSecondary")
        ok = QPushButton("Continue", objectName="DialogPrimary")
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        footer.addWidget(cancel)
        footer.addWidget(ok)
        layout.addLayout(footer)

        self.setStyleSheet("""
        QDialog { background:#FFFFFF; color:#101A2D; }
        QLabel#DialogTitle { font-size:14px; font-weight:800; }
        QLabel#DialogSub { color:#5F7087; font-size:9.5px; }
        QPushButton#FormatChoice {
            text-align:left; background:#FFFFFF; color:#30455F;
            border:1px solid #C6D3E4; border-radius:10px;
            padding:8px 11px; font-size:9.5px; font-weight:650;
        }
        QPushButton#FormatChoice:checked {
            background:#EAF1FF; color:#1D5BD0; border:2px solid #2868E8;
        }
        QPushButton#DialogPrimary, QPushButton#DialogSecondary {
            min-height:35px; border-radius:8px; padding:0 13px;
            font-size:9.5px; font-weight:750;
        }
        QPushButton#DialogPrimary { background:#2868E8; color:#FFFFFF; border:1px solid #2868E8; }
        QPushButton#DialogSecondary { background:#FFFFFF; color:#405873; border:1px solid #BFCEDF; }
        """)

    def _select(self, value: str):
        self.format_choice = value
        self.json_btn.setChecked(value == "json")
        self.xml_btn.setChecked(value == "xml")


class VerificationDialog(QDialog):
    def __init__(self, page, parent=None):
        super().__init__(parent or page)
        self.page = page
        self.setWindowTitle("Final Save & Verify")
        self.resize(760, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(9)

        layout.addWidget(QLabel("Final Annotation Review", objectName="DialogTitle"))
        annotated = sum(1 for p in page.images if page.annotations.get(p))
        layout.addWidget(
            QLabel(
                f"Annotated images: {annotated} / {len(page.images)}",
                objectName="DialogSub",
            )
        )

        self.list_widget = QListWidget(objectName="VerifyList")
        self.list_widget.setIconSize(QtCore.QSize(70, 55))
        self.list_widget.itemDoubleClicked.connect(self._open_item)

        for image_path in page.images:
            item = QListWidgetItem()
            pix = QtGui.QPixmap(image_path)
            if not pix.isNull():
                pix = pix.scaled(
                    70, 55,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                item.setIcon(QtGui.QIcon(pix))
            count = len(page.annotations.get(image_path, []))
            item.setText(f"{Path(image_path).name}    ·    {count} annotation(s)")
            item.setData(Qt.ItemDataRole.UserRole, image_path)
            item.setForeground(
                QtGui.QBrush(QtGui.QColor("#087D53" if count else "#9A3F4E"))
            )
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget, 1)

        footer = QHBoxLayout()
        cancel = QPushButton("Continue Annotating", objectName="DialogSecondary")
        export = QPushButton("Export Annotations", objectName="DialogPrimary")
        cancel.clicked.connect(self.reject)
        export.clicked.connect(self._export)
        footer.addStretch(1)
        footer.addWidget(cancel)
        footer.addWidget(export)
        layout.addLayout(footer)

        self.setStyleSheet("""
        QDialog { background:#FFFFFF; color:#101A2D; }
        QLabel#DialogTitle { font-size:15px; font-weight:800; }
        QLabel#DialogSub { color:#5F7087; font-size:10px; }
        QListWidget#VerifyList {
            background:#FBFCFE; color:#17263D; border:1px solid #C7D4E4;
            border-radius:10px; padding:6px; font-size:10px;
        }
        QListWidget#VerifyList::item { min-height:64px; border-bottom:1px solid #E5EAF1; padding:3px; }
        QListWidget#VerifyList::item:selected { background:#EAF1FF; color:#1D5BD0; }
        QPushButton#DialogPrimary, QPushButton#DialogSecondary {
            min-height:36px; border-radius:8px; padding:0 14px;
            font-size:9.5px; font-weight:750;
        }
        QPushButton#DialogPrimary { background:#2868E8; color:#FFFFFF; border:1px solid #2868E8; }
        QPushButton#DialogSecondary { background:#FFFFFF; color:#405873; border:1px solid #BFCEDF; }
        """)

    def _open_item(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        self.page.open_image_path(path)
        self.reject()

    def _export(self):
        if self.page.export_all_annotations():
            self.accept()




class AnnotationCanvas(QtWidgets.QScrollArea):
    annotation_changed = QtCore.pyqtSignal()
    selection_changed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = None
        self.image_label = QtWidgets.QLabel()
        self.image_label.setBackgroundRole(QtGui.QPalette.ColorRole.Base)
        # Keep the zoomed image at its real displayed size. Using
        # QSizePolicy.Ignored allowed QScrollArea to compress the label and
        # could prevent the horizontal scroll range from appearing.
        self.image_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.image_label.setScaledContents(False)
        self.image_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        
        self.setBackgroundRole(QtGui.QPalette.ColorRole.Base)
        self.setWidgetResizable(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Canvas-local scrollbar styling so zoom navigation stays visible even
        # when the application/global stylesheet is very light.
        self.setStyleSheet("""
        QScrollArea {
            background:#FFFFFF;
            border:0;
        }
        QLabel {
            background:#FFFFFF;
        }

        QScrollBar:horizontal {
            background:#E7EDF5;
            height:13px;
            margin:1px;
            border:1px solid #D2DDE9;
            border-radius:6px;
        }
        QScrollBar::handle:horizontal {
            background:#829AB7;
            min-width:42px;
            border-radius:5px;
        }
        QScrollBar::handle:horizontal:hover {
            background:#7F99B8;
        }
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {
            width:0px;
            border:0;
        }
        QScrollBar::add-page:horizontal,
        QScrollBar::sub-page:horizontal {
            background:transparent;
        }

        QScrollBar:vertical {
            background:#E7EDF5;
            width:13px;
            margin:1px;
            border:1px solid #D2DDE9;
            border-radius:6px;
        }
        QScrollBar::handle:vertical {
            background:#829AB7;
            min-height:42px;
            border-radius:5px;
        }
        QScrollBar::handle:vertical:hover {
            background:#7F99B8;
        }
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            height:0px;
            border:0;
        }
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {
            background:transparent;
        }
        """)
        self.viewport().setStyleSheet("background:#FFFFFF;")
        self.setWidget(self.image_label)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        
        self.scale_factor = 1.0
        self.pixmap = None
        self.original_pixmap = None
        self.shapes = []
        self.current_shape = []
        self.drawing = False
        self.mode = 'rect'
        self.current_label = "object"
        
        # Undo/Redo functionality
        self.undo_stack = []
        self.redo_stack = []
        
        # Selection and adjustment
        self.selected_shape_index = -1
        self.selected_point_index = -1
        self.dragging = False
        self.resize_handle_size = 8
        
        # Copy/paste functionality
        self.copied_shape = None
        self.annotation_items = []
        # Zoom settings
        self.zoom_in_factor = 1.25
        self.zoom_out_factor = 1 / self.zoom_in_factor
        
        # Enable mouse tracking for better interaction
        self.setMouseTracking(True)
        self.image_label.setMouseTracking(True)

    def load_image(self, path):
        self.original_pixmap = QtGui.QPixmap(path)
        self.pixmap = self.original_pixmap
        self.image_label.setPixmap(self.pixmap)
        if self.pixmap and not self.pixmap.isNull():
            self.image_label.setFixedSize(self.pixmap.size())
        self.scale_factor = 1.0
        self.fit_to_window()
        self.shapes.clear()
        self.current_shape.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.selected_shape_index = -1
        self.selected_point_index = -1
        self.clear_annotation_items()
        
    def fit_to_window(self):
        """Fit the original image inside the viewport and hide pan bars."""
        if not self.original_pixmap or self.original_pixmap.isNull():
            return

        viewport_w = max(1, self.viewport().width() - 34)
        viewport_h = max(1, self.viewport().height() - 34)

        fit_factor = min(
            viewport_w / self.original_pixmap.width(),
            viewport_h / self.original_pixmap.height(),
        )
        self.scale_factor = max(0.02, fit_factor * 0.90)

        width = max(1, int(self.original_pixmap.width() * self.scale_factor))
        height = max(1, int(self.original_pixmap.height() * self.scale_factor))

        self.pixmap = self.original_pixmap.scaled(
            width,
            height,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )

        self.image_label.setPixmap(self.pixmap)
        self.image_label.setFixedSize(self.pixmap.size())
        self.image_label.updateGeometry()

        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)
        self.update()

    def _sync_scrollbars(self):
        """Show left/right and up/down pan bars only when actually required."""
        if not self.pixmap:
            return

        viewport_w = max(1, self.viewport().width())
        viewport_h = max(1, self.viewport().height())

        image_w = max(1, self.image_label.width())
        image_h = max(1, self.image_label.height())

        need_h = image_w > viewport_w
        need_v = image_h > viewport_h

        # Force visibility instead of relying on a delayed QScrollArea update.
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
            if need_h
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
            if need_v
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        hbar = self.horizontalScrollBar()
        vbar = self.verticalScrollBar()

        hbar.setPageStep(viewport_w)
        vbar.setPageStep(viewport_h)

        # QScrollArea will normally calculate these ranges. Setting them
        # explicitly makes the horizontal pan immediately usable after zoom.
        hbar.setRange(0, max(0, image_w - viewport_w))
        vbar.setRange(0, max(0, image_h - viewport_h))

        hbar.setVisible(need_h)
        vbar.setVisible(need_v)

    def scale_image(self, factor):
        if not self.original_pixmap or self.original_pixmap.isNull():
            return

        hbar = self.horizontalScrollBar()
        vbar = self.verticalScrollBar()

        # Preserve the visual center of the viewport while zooming.
        old_h_value = hbar.value()
        old_v_value = vbar.value()
        old_h_page = max(1, hbar.pageStep() or self.viewport().width())
        old_v_page = max(1, vbar.pageStep() or self.viewport().height())

        self.scale_factor *= float(factor)
        self.scale_factor = max(0.05, min(self.scale_factor, 12.0))

        width = max(1, int(self.original_pixmap.width() * self.scale_factor))
        height = max(1, int(self.original_pixmap.height() * self.scale_factor))

        self.pixmap = self.original_pixmap.scaled(
            width,
            height,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )

        # IMPORTANT: fixed-size QLabel is what creates a real scrollable
        # content area when the image grows beyond the viewer.
        self.image_label.setPixmap(self.pixmap)
        self.image_label.setFixedSize(self.pixmap.size())
        self.image_label.updateGeometry()

        QtWidgets.QApplication.processEvents(
            QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
        )

        self._sync_scrollbars()

        if hbar.maximum() > 0:
            hbar.setValue(
                int(
                    float(factor) * old_h_value
                    + ((float(factor) - 1.0) * old_h_page / 2.0)
                )
            )

        if vbar.maximum() > 0:
            vbar.setValue(
                int(
                    float(factor) * old_v_value
                    + ((float(factor) - 1.0) * old_v_page / 2.0)
                )
            )

        # Run once more after the event loop commits the QScrollArea layout.
        QtCore.QTimer.singleShot(0, self._sync_scrollbars)
        self.update()

    def adjust_scrollbar(self, scrollbar, factor):
        # Kept for compatibility with the original canvas API.
        scrollbar.setValue(
            int(
                float(factor) * scrollbar.value()
                + ((float(factor) - 1.0) * scrollbar.pageStep() / 2.0)
            )
        )

    def zoom_in(self):
        self.scale_image(self.zoom_in_factor)

    def zoom_out(self):
        self.scale_image(self.zoom_out_factor)

    def normal_size(self):
        if not self.original_pixmap or self.original_pixmap.isNull():
            return

        self.scale_factor = 1.0
        self.pixmap = self.original_pixmap
        self.image_label.setPixmap(self.original_pixmap)
        self.image_label.setFixedSize(self.original_pixmap.size())
        self.image_label.updateGeometry()

        self._sync_scrollbars()
        QtCore.QTimer.singleShot(0, self._sync_scrollbars)

    def get_image_coordinates(self, event_pos):
        """Convert widget coordinates to original image coordinates"""
        if not self.pixmap or not self.original_pixmap:
            return QtCore.QPoint(0, 0)
            
        # Get the position relative to the image label
        label_pos = self.image_label.mapFrom(self, event_pos)
        
        # Calculate the scale factor between displayed image and original image
        display_width = self.pixmap.width()
        display_height = self.pixmap.height()
        original_width = self.original_pixmap.width()
        original_height = self.original_pixmap.height()
        
        # Calculate the offset if the image is centered
        x_offset = (self.image_label.width() - display_width) / 2
        y_offset = (self.image_label.height() - display_height) / 2
        
        # Adjust for centering
        adj_x = label_pos.x() - x_offset
        adj_y = label_pos.y() - y_offset
        
        # Convert to original image coordinates
        if display_width > 0 and display_height > 0:
            x = int(adj_x * original_width / display_width)
            y = int(adj_y * original_height / display_height)
            
            # Clamp to image boundaries
            x = max(0, min(x, original_width - 1))
            y = max(0, min(y, original_height - 1))
            
            return QtCore.QPoint(x, y)
            
        return QtCore.QPoint(0, 0)

    # ... [Include all other ZoomableCanvas methods from your original code] ...
    # For brevity, I'm including the essential methods. You should copy ALL methods from your original ZoomableCanvas class

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self.pixmap:
            pos = self.get_image_coordinates(event.position().toPoint())
            
            if self.mode == 'rect':
                # Check if clicking on existing shape
                shape_index, point_index = self.get_shape_at_position(pos)
                if shape_index != -1:
                    self.selected_shape_index = shape_index
                    self.selected_point_index = point_index
                    self.dragging = True
                    # Save state for undo
                    self.save_state()
                else:
                    self.drawing = True
                    self.current_shape = [pos, pos]
                    self.selected_shape_index = -1
            elif self.mode == 'polygon':
                shape_index, point_index = self.get_shape_at_position(pos)
                if shape_index != -1:
                    self.selected_shape_index = shape_index
                    self.selected_point_index = point_index
                    self.dragging = True
                    self.save_state()
                else:
                    self.current_shape.append(pos)
            elif self.mode == 'select':
                shape_index, point_index = self.get_shape_at_position(pos)
                self.selected_shape_index = shape_index
                self.selected_point_index = point_index
                if shape_index != -1:
                    self.dragging = True
                    self.save_state()
                
        elif event.button() == QtCore.Qt.MouseButton.RightButton and self.mode == 'polygon':
            self.finish_polygon()
                
        self.selection_changed.emit()
        self.update()
        
    def mouseMoveEvent(self, event):
        if self.drawing and self.mode == 'rect' and self.pixmap:
            pos = self.get_image_coordinates(event.position().toPoint())
            self.current_shape[1] = pos
        elif self.dragging and self.selected_shape_index != -1 and self.pixmap:
            pos = self.get_image_coordinates(event.position().toPoint())
            self.update_shape_position(pos)
        self.update()
            
    def mouseReleaseEvent(self, event):
        if self.drawing and self.mode == 'rect' and self.pixmap:
            self.drawing = False
            if self.current_shape and self.current_label:
                # Save state before adding new shape
                self.save_state()
                self.shapes.append(('rect', self.current_shape.copy(), self.current_label))
                # Trigger auto-save
                if hasattr(self.main_window, 'auto_save_annotations'):
                    self.main_window.auto_save_annotations()
                # AUTO-OPEN LABEL EDITOR - USE main_window INSTEAD OF parent()
                if hasattr(self.main_window, 'auto_open_label_editor'):
                    QtCore.QTimer.singleShot(100, self.main_window.auto_open_label_editor)
                else:
                    print("DEBUG: auto_open_label_editor not found in main_window")
            self.current_shape.clear()
        elif self.dragging:
            self.dragging = False
            # Trigger auto-save after moving/resizing
            if hasattr(self.main_window, 'auto_save_annotations'):
                self.main_window.auto_save_annotations()
        self.annotation_changed.emit()
        self.selection_changed.emit()
        self.update()

    def get_shape_at_position(self, pos, threshold=10):
        """Check if position is near any shape or control point"""
        for i, (shape_type, points, label) in enumerate(self.shapes):
            if shape_type == 'rect':
                rect = QtCore.QRect(points[0], points[1]).normalized()
                # Check if near edges or corners
                if rect.contains(pos):
                    return i, -1  # -1 means moving entire shape
                
                # Check corners for resizing
                corners = [
                    rect.topLeft(), rect.topRight(), 
                    rect.bottomLeft(), rect.bottomRight()
                ]
                for j, corner in enumerate(corners):
                    if (pos - corner).manhattanLength() < threshold:
                        return i, j
                        
            elif shape_type == 'polygon':
                # Check if near any point
                for j, point in enumerate(points):
                    if (pos - point).manhattanLength() < threshold:
                        return i, j
                # Check if inside polygon
                poly = QtGui.QPolygon(points)
                if poly.containsPoint(pos, QtCore.Qt.FillRule.OddEvenFill):
                    return i, -1
                    
        return -1, -1

    def update_shape_position(self, pos):
        """Update shape position based on drag operation"""
        if self.selected_shape_index < 0 or self.selected_shape_index >= len(self.shapes):
            return
            
        shape_type, points, label = self.shapes[self.selected_shape_index]
        
        if shape_type == 'rect':
            rect = QtCore.QRect(points[0], points[1]).normalized()
            
            if self.selected_point_index == -1:  # Moving entire rectangle
                delta = pos - rect.center()
                new_tl = points[0] + delta
                new_br = points[1] + delta
                self.shapes[self.selected_shape_index] = (shape_type, [new_tl, new_br], label)
            else:  # Resizing from corner
                corners = [rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()]
                corners[self.selected_point_index] = pos
                
                # Reconstruct rectangle from updated corners
                new_tl = QtCore.QPoint(min(corners[0].x(), corners[2].x()), min(corners[0].y(), corners[1].y()))
                new_br = QtCore.QPoint(max(corners[1].x(), corners[3].x()), max(corners[2].y(), corners[3].y()))
                self.shapes[self.selected_shape_index] = (shape_type, [new_tl, new_br], label)
                
        elif shape_type == 'polygon':
            if self.selected_point_index >= 0 and self.selected_point_index < len(points):
                # Move specific point
                new_points = points.copy()
                new_points[self.selected_point_index] = pos
                self.shapes[self.selected_shape_index] = (shape_type, new_points, label)
            elif self.selected_point_index == -1:  # Moving entire polygon
                # Calculate center and move all points
                center = self.get_polygon_center(points)
                delta = pos - center
                new_points = [p + delta for p in points]
                self.shapes[self.selected_shape_index] = (shape_type, new_points, label)

    def get_polygon_center(self, points):
        """Calculate center point of polygon"""
        if not points:
            return QtCore.QPoint(0, 0)
        x_sum = sum(p.x() for p in points)
        y_sum = sum(p.y() for p in points)
        return QtCore.QPoint(x_sum // len(points), y_sum // len(points))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.pixmap:
            QtCore.QTimer.singleShot(0, self._sync_scrollbars)

    def wheelEvent(self, event):
        """Handle zoom with Ctrl+Mouse Wheel"""
        if event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Delete and self.selected_shape_index != -1:
            self.delete_selected_shape()
        elif event.key() == QtCore.Qt.Key.Key_Escape:
            self.cancel_operation()
        elif event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
            if event.key() == QtCore.Qt.Key.Key_Z:
                self.undo()
            elif event.key() == QtCore.Qt.Key.Key_Y:
                self.redo()
            elif event.key() == QtCore.Qt.Key.Key_C:
                self.copy_selected_shape()
            elif event.key() == QtCore.Qt.Key.Key_V:
                self.paste_shape()
        else:
            super().keyPressEvent(event)

    def delete_selected_shape(self):
        if self.selected_shape_index != -1:
            self.save_state()
            del self.shapes[self.selected_shape_index]
            self.selected_shape_index = -1
            # Trigger auto-save - USE main_window
            if hasattr(self.main_window, 'auto_save_annotations'):
                self.main_window.auto_save_annotations()
            self.update()

    def copy_selected_shape(self):
        if self.selected_shape_index != -1:
            shape_type, points, label = self.shapes[self.selected_shape_index]
            self.copied_shape = (shape_type, [QtCore.QPoint(p) for p in points], label)

    def paste_shape(self):
        if self.copied_shape and self.pixmap:
            self.save_state()
            shape_type, points, label = self.copied_shape
            # Offset the copied shape slightly
            offset = QtCore.QPoint(20, 20)
            new_points = [p + offset for p in points]
            self.shapes.append((shape_type, new_points, label))
            self.selected_shape_index = len(self.shapes) - 1
            # Trigger auto-save
            if hasattr(self.main_window, 'auto_save_annotations'):
                self.main_window.auto_save_annotations()
            self.update()

    def edit_selected_label(self, new_label):
        if self.selected_shape_index != -1:
            self.save_state()
            shape_type, points, old_label = self.shapes[self.selected_shape_index]
            self.shapes[self.selected_shape_index] = (shape_type, points, new_label)
            # Trigger auto-save
            if hasattr(self.main_window, 'auto_save_annotations'):
                self.main_window.auto_save_annotations()
            self.update()

    def cancel_operation(self):
        if self.mode == 'polygon':
            self.current_shape.clear()
        self.selected_shape_index = -1
        self.drawing = False
        self.dragging = False
        self.update()

    def save_state(self):
        """Save current state to undo stack"""
        state = {
            'shapes': [(shape_type, [QtCore.QPoint(p) for p in points], label) 
                      for shape_type, points, label in self.shapes],
            'current_shape': [QtCore.QPoint(p) for p in self.current_shape],
            'selected_index': self.selected_shape_index
        }
        self.undo_stack.append(state)
        self.redo_stack.clear()  # Clear redo stack when new action is performed
        
        # Limit undo stack size
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)

    def undo(self):
        """Undo last action"""
        if self.undo_stack:
            # Save current state to redo stack
            current_state = {
                'shapes': [(shape_type, [QtCore.QPoint(p) for p in points], label) 
                          for shape_type, points, label in self.shapes],
                'current_shape': [QtCore.QPoint(p) for p in self.current_shape],
                'selected_index': self.selected_shape_index
            }
            self.redo_stack.append(current_state)
            
            # Restore previous state
            state = self.undo_stack.pop()
            self.shapes = [(shape_type, points, label) for shape_type, points, label in state['shapes']]
            self.current_shape = state['current_shape']
            self.selected_shape_index = state['selected_index']
            self.update()

    def redo(self):
        """Redo last undone action"""
        if self.redo_stack:
            # Save current state to undo stack
            current_state = {
                'shapes': [(shape_type, [QtCore.QPoint(p) for p in points], label) 
                          for shape_type, points, label in self.shapes],
                'current_shape': [QtCore.QPoint(p) for p in self.current_shape],
                'selected_index': self.selected_shape_index
            }
            self.undo_stack.append(current_state)
            
            # Restore redone state
            state = self.redo_stack.pop()
            self.shapes = [(shape_type, points, label) for shape_type, points, label in state['shapes']]
            self.current_shape = state['current_shape']
            self.selected_shape_index = state['selected_index']
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.pixmap or not self.original_pixmap:
            return
            
        # Create a new pixmap to draw on (use original for accurate coordinates)
        temp_pixmap = self.original_pixmap.copy()
        painter = QtGui.QPainter(temp_pixmap)
        
        if not painter.isActive():
            return
            
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        
        # Draw existing shapes
        for i, (shape_type, points, label) in enumerate(self.shapes):
            color = self.get_color_for_label(label)
            pen = QtGui.QPen(color, 3)
            painter.setPen(pen)
            
            if shape_type == 'rect':
                rect = QtCore.QRect(points[0], points[1])
                painter.drawRect(rect)
                
                # Draw selection handles if selected
                if i == self.selected_shape_index:
                    self.draw_selection_handles(painter, rect)
                
                # Draw label
                painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 2))
                painter.drawText(points[0].x() + 5, points[0].y() - 5, label)
                
            elif shape_type == 'polygon':
                poly = QtGui.QPolygon(points)
                painter.drawPolygon(poly)
                
                # Draw selection handles if selected
                if i == self.selected_shape_index:
                    for point in points:
                        painter.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 0)))
                        painter.drawEllipse(point, 4, 4)
                
                if points:
                    painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 2))
                    painter.drawText(points[0].x() + 5, points[0].y() - 5, label)
                    
        # Draw current shape
        if self.current_shape:
            color = QtGui.QColor(255, 0, 0)  # Red for current shape
            pen = QtGui.QPen(color, 2, QtCore.Qt.PenStyle.DashLine)
            painter.setPen(pen)
            
            if self.mode == 'rect' and len(self.current_shape) == 2:
                rect = QtCore.QRect(self.current_shape[0], self.current_shape[1])
                painter.drawRect(rect)
            elif self.mode == 'polygon' and self.current_shape:
                poly = QtGui.QPolygon(self.current_shape)
                painter.drawPolyline(poly)
                # Draw points
                for point in self.current_shape:
                    painter.drawEllipse(point, 3, 3)
        
        painter.end()
        
        # Scale the annotated pixmap to current display size
        scaled_pixmap = temp_pixmap.scaled(
            self.pixmap.size(),
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation
        )
        self.image_label.setPixmap(scaled_pixmap)

    def draw_selection_handles(self, painter, rect):
        """Draw selection handles around rectangle"""
        painter.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 0)))
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0), 1))
        
        handles = [
            rect.topLeft(), rect.topRight(), 
            rect.bottomLeft(), rect.bottomRight(),
            QtCore.QPoint(rect.center().x(), rect.top()),
            QtCore.QPoint(rect.center().x(), rect.bottom()),
            QtCore.QPoint(rect.left(), rect.center().y()),
            QtCore.QPoint(rect.right(), rect.center().y())
        ]
        
        for handle in handles:
            painter.drawRect(handle.x() - 4, handle.y() - 4, 8, 8)

    def get_color_for_label(self, label):
        # Generate consistent color based on label
        import hashlib
        hash_obj = hashlib.md5(label.encode())
        hash_int = int(hash_obj.hexdigest()[:8], 16)
        r = (hash_int >> 16) & 255
        g = (hash_int >> 8) & 255
        b = hash_int & 255
        return QtGui.QColor(r, g, b)

    def set_mode(self, mode):
        self.mode = mode
        self.current_shape.clear()
        self.selected_shape_index = -1
        self.update()

    def set_label(self, label):
        self.current_label = label

    def finish_polygon(self):
        if len(self.current_shape) > 2 and self.current_label:
            self.save_state()
            self.shapes.append(('polygon', self.current_shape.copy(), self.current_label))
            self.current_shape.clear()
            # Trigger auto-save
            if hasattr(self.main_window, 'auto_save_annotations'):
                self.main_window.auto_save_annotations()
            # AUTO-OPEN LABEL EDITOR FOR POLYGON - USE main_window
            if hasattr(self.main_window, 'auto_open_label_editor'):
                QtCore.QTimer.singleShot(100, self.main_window.auto_open_label_editor)
            self.update()

    def get_annotations(self):
        annotations = []
        for shape_type, points, label in self.shapes:
            if shape_type == 'rect':
                x1, y1 = points[0].x(), points[0].y()
                x2, y2 = points[1].x(), points[1].y()
                annotations.append({
                    'label': label,
                    'shape': 'rectangle',
                    'points': [[x1, y1], [x2, y2]],
                    'bbox': [min(x1, x2), min(y1, y2), abs(x2-x1), abs(y2-y1)]
                })
            elif shape_type == 'polygon':
                pts = [[p.x(), p.y()] for p in points]
                x_coords = [p[0] for p in pts]
                y_coords = [p[1] for p in pts]
                annotations.append({
                    'label': label,
                    'shape': 'polygon',
                    'points': pts,
                    'bbox': [min(x_coords), min(y_coords), 
                            max(x_coords)-min(x_coords), max(y_coords)-min(y_coords)]
                })
        return annotations

    def clear_annotations(self):
        self.save_state()
        self.shapes.clear()
        self.selected_shape_index = -1
        self.update()

    def clear_annotation_items(self):
        """Clear all annotation graphics items"""
        self.annotation_items.clear()

    def add_annotation_rect(self, rect, label):
        """Add rectangle annotation to display"""
        print(f"Adding rectangle: {rect}, label: {label}")

    def add_annotation_polygon(self, polygon, label):
        """Add polygon annotation to display"""
        print(f"Adding polygon: {polygon.size()} points, label: {label}")


class ThumbnailCard(QWidget):
    """Filmstrip card matching the finalized preview."""

    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.setObjectName("ThumbnailCard")
        self.setProperty("selected", False)
        self.setFixedSize(132, 90)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)

        self.image_host = QFrame(objectName="ThumbnailImageHost")
        self.image_host.setFixedHeight(62)
        host_layout = QVBoxLayout(self.image_host)
        host_layout.setContentsMargins(2, 2, 2, 2)

        self.preview = QLabel(objectName="ThumbnailPreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = QtGui.QPixmap(image_path)
        if not pix.isNull():
            self.preview.setPixmap(
                pix.scaled(
                    118, 58,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        host_layout.addWidget(self.preview)
        layout.addWidget(self.image_host)

        self.check = QLabel("✓", self.image_host, objectName="ThumbnailCheck")
        self.check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.check.setFixedSize(17, 17)
        self.check.hide()

        self.name = QLabel(Path(image_path).name, objectName="ThumbnailName")
        self.name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.name)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.check.move(max(2, self.image_host.width() - 21), 4)

    def set_state(self, annotated: bool, selected: bool):
        self.check.setVisible(bool(annotated))
        self.setProperty("selected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class AnnotationRowWidget(QWidget):
    """Inspector annotation row matching the approved card design."""

    def __init__(self, label: str, type_name: str, meta: str, selected: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("AnnotationRow")
        self.setProperty("selected", bool(selected))
        self.setMinimumHeight(50)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.label_text = QLabel(label, objectName="AnnotationRowLabel")
        self.type_text = QLabel(type_name, objectName="AnnotationTypePill")
        top.addWidget(self.label_text, 1)
        top.addWidget(self.type_text, 0)
        layout.addLayout(top)

        self.meta_text = QLabel(meta, objectName="AnnotationRowMeta")
        layout.addWidget(self.meta_text)



class AnnotationPageQt6(QWidget):
    toast_requested = pyqtSignal(str, str)

    def __init__(self, user: dict | None = None, parent=None):
        super().__init__(parent)
        self.user = user or {}

        self.folder = ""
        self.images: list[str] = []
        self.current_index = -1
        self.current_image: str | None = None
        self.annotations: dict[str, list[dict]] = {}
        self.pending_saves: set[str] = set()
        self.existing_labels: set[str] = set()
        self.auto_save_enabled = True

        self.projects: list[dict] = []
        self.project_map: dict[str, dict] = {}
        self.selected_project_id = ""

        self._last_shape_signature = None
        self._last_selection_index = -999

        self.setObjectName("AnnotationPageQt6")
        self._build()
        self._apply_style()
        self._setup_shortcuts()

        self.refresh_context()

        # Compatibility with the existing canvas callback contract.
        self.canvas.main_window = self
        self.canvas.annotation_changed.connect(self._canvas_changed)
        self.canvas.selection_changed.connect(self.refresh_inspector)

        # Some movement/resize paths in the original canvas update continuously;
        # a lightweight UI-only timer keeps the inspector synchronized.
        self.inspector_timer = QtCore.QTimer(self)
        self.inspector_timer.setInterval(180)
        self.inspector_timer.timeout.connect(self._poll_canvas_state)
        self.inspector_timer.start()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # Context row
        context = QGridLayout()
        context.setContentsMargins(0, 0, 0, 0)
        context.setHorizontalSpacing(9)
        context.setVerticalSpacing(9)

        project_card = self._context_card("CURRENT PROJECT")
        self.project_selector = ProjectComboBox()
        self.project_selector.currentIndexChanged.connect(self._project_changed)
        project_card.layout().addWidget(self.project_selector)
        context.addWidget(project_card, 0, 0)

        source_card = self._context_card("SOURCE DATASET")
        self.source_label = QLabel("No image folder loaded", objectName="ContextValue")
        self.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        source_card.layout().addWidget(self.source_label)
        context.addWidget(source_card, 0, 1)

        annotated_card = self._context_card("ANNOTATED")
        self.annotated_count_label = QLabel("0 / 0 images", objectName="ContextValue")
        annotated_card.layout().addWidget(self.annotated_count_label)
        context.addWidget(annotated_card, 0, 2)

        current_card = self._context_card("CURRENT IMAGE")
        self.image_counter_label = QLabel("0 / 0", objectName="ContextValue")
        current_card.layout().addWidget(self.image_counter_label)
        context.addWidget(current_card, 0, 3)

        actions = QWidget()
        action_row = QHBoxLayout(actions)
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(7)

        self.browse_btn = QPushButton("Open Image Folder", objectName="ContextButton")
        self.browse_with_annotations_btn = QPushButton(
            "Open Images + Annotations",
            objectName="ContextButton",
        )
        for btn in (self.browse_btn, self.browse_with_annotations_btn):
            btn.setFixedHeight(38)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_btn.clicked.connect(self.browse_folder)
        self.browse_with_annotations_btn.clicked.connect(self.load_folder_with_annotations)
        action_row.addWidget(self.browse_btn)
        action_row.addWidget(self.browse_with_annotations_btn)
        context.addWidget(actions, 0, 4)

        # Match the finalized reference: Current Project is intentionally
        # wider and Source Dataset is slightly less dominant.
        context.setColumnStretch(0, 18)
        context.setColumnStretch(1, 23)
        context.setColumnStretch(2, 10)
        context.setColumnStretch(3, 10)
        context.setColumnStretch(4, 14)
        root.addLayout(context)

        # Main workbench
        self.workbench = QHBoxLayout()
        self.workbench.setSpacing(10)

        self.tool_rail = self._build_tool_rail()
        self.workbench.addWidget(self.tool_rail)

        self.canvas_panel = self._build_canvas_panel()
        self.workbench.addWidget(self.canvas_panel, 1)

        self.inspector = self._build_inspector()
        self.workbench.addWidget(self.inspector)

        root.addLayout(self.workbench, 1)

    def _context_card(self, title: str) -> QFrame:
        card = QFrame(objectName="ContextCard")
        card.setMinimumHeight(62)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)
        layout.addWidget(QLabel(title, objectName="ContextKey"))
        return card

    def _build_tool_rail(self):
        rail = QFrame(objectName="ToolRail")
        rail.setFixedWidth(76)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(7)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        layout.addWidget(
            QLabel("TOOLS", objectName="RailSection"),
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )

        self.tool_buttons = {}
        for mode, icon_kind in (
            ("Select", "select"),
            ("Rectangle", "rectangle"),
            ("Polygon", "polygon"),
        ):
            button = AnnotationToolButton(
                icon_kind,
                mode,
                checkable=True,
            )
            button.clicked.connect(
                lambda checked=False, m=mode: self.change_mode(m)
            )
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
            self.tool_buttons[mode] = button

        self.tool_buttons["Select"].setChecked(True)

        layout.addSpacing(7)
        layout.addWidget(
            QLabel("EDIT", objectName="RailSection"),
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )

        self.undo_btn = AnnotationToolButton("undo", "Undo")
        self.redo_btn = AnnotationToolButton("redo", "Redo")
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn.clicked.connect(self.redo)
        layout.addWidget(self.undo_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.redo_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch(1)

        self.keys_btn = AnnotationToolButton("keyboard", "Keys")
        self.keys_btn.clicked.connect(self.show_help)
        layout.addWidget(self.keys_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        return rail

    def _build_canvas_panel(self):
        panel = QFrame(objectName="CanvasPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QFrame(objectName="CanvasToolbar")
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(9, 7, 9, 7)
        row.setSpacing(5)

        self.toolbar_mode_buttons = {}
        for mode in ("Select", "Rectangle", "Polygon"):
            button = QPushButton(mode, objectName="ToolbarButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, m=mode: self.change_mode(m))
            row.addWidget(button)
            self.toolbar_mode_buttons[mode] = button
        self.toolbar_mode_buttons["Select"].setChecked(True)

        row.addSpacing(5)

        self.zoom_out_btn = QPushButton("−", objectName="ToolbarButton")
        self.fit_btn = QPushButton("Fit", objectName="ToolbarButton")
        self.zoom_in_btn = QPushButton("+", objectName="ToolbarButton")
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        self.fit_btn.clicked.connect(self.fit_to_window)
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        row.addWidget(self.zoom_out_btn)
        row.addWidget(self.fit_btn)
        row.addWidget(self.zoom_in_btn)

        row.addSpacing(5)

        self.prev_btn = QPushButton("← Previous", objectName="ToolbarButton")
        self.next_btn = QPushButton("Next →", objectName="ToolbarButton")
        self.prev_btn.clicked.connect(self.prev_image)
        self.next_btn.clicked.connect(self.next_image)
        row.addWidget(self.prev_btn)
        row.addWidget(self.next_btn)

        row.addStretch(1)
        self.filename_label = QLabel("No image loaded", objectName="FilenameLabel")
        row.addWidget(self.filename_label)
        layout.addWidget(toolbar)

        self.canvas_wrap = QFrame(objectName="CanvasWrap")
        cw = QVBoxLayout(self.canvas_wrap)
        cw.setContentsMargins(8, 8, 8, 8)
        cw.setSpacing(0)

        self.canvas = AnnotationCanvas()
        self.canvas.setMinimumHeight(340)
        cw.addWidget(self.canvas, 1)
        layout.addWidget(self.canvas_wrap, 1)

        status = QFrame(objectName="CanvasStatus")
        sr = QHBoxLayout(status)
        sr.setContentsMargins(9, 0, 9, 0)
        self.canvas_mode_label = QLabel("SELECT · click annotation to edit", objectName="CanvasStatusText")
        self.canvas_info_label = QLabel("No image", objectName="CanvasStatusText")
        sr.addWidget(self.canvas_mode_label)
        sr.addStretch(1)
        sr.addWidget(self.canvas_info_label)
        layout.addWidget(status)

        self.thumbnail_list = QListWidget(objectName="ThumbnailList")
        self.thumbnail_list.setViewMode(QListView.ViewMode.IconMode)
        self.thumbnail_list.setFlow(QListView.Flow.LeftToRight)
        self.thumbnail_list.setWrapping(False)
        self.thumbnail_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.thumbnail_list.setMovement(QListView.Movement.Static)
        self.thumbnail_list.setIconSize(QtCore.QSize(118, 66))
        self.thumbnail_list.setFixedHeight(116)
        self.thumbnail_list.setHorizontalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.thumbnail_list.itemClicked.connect(self.thumbnail_clicked)
        layout.addWidget(self.thumbnail_list)

        return panel

    def _build_inspector(self):
        panel = QFrame(objectName="Inspector")
        panel.setMinimumWidth(275)
        panel.setMaximumWidth(315)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        head = QFrame(objectName="InspectorHead")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(12, 11, 12, 9)
        hl.setSpacing(2)
        hl.addWidget(QLabel("Annotation Inspector", objectName="InspectorTitle"))
        self.inspector_subtitle = QLabel("Current image · 0 annotations", objectName="InspectorSubtitle")
        hl.addWidget(self.inspector_subtitle)
        layout.addWidget(head)

        scroll = QScrollArea(objectName="InspectorScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(10, 10, 10, 10)
        cl.setSpacing(9)

        # Active label
        label_group = QFrame(objectName="InspectorGroup")
        lg = QVBoxLayout(label_group)
        lg.setContentsMargins(10, 9, 10, 9)
        lg.setSpacing(6)
        lg.addWidget(QLabel("ACTIVE LABEL", objectName="GroupTitle"))
        lg.addWidget(QLabel("Label", objectName="FieldLabel"))

        lr = QHBoxLayout()
        self.label_input = QLineEdit(objectName="LabelInput")
        self.label_input.setPlaceholderText("Enter object label")
        self.label_input.textChanged.connect(self.update_current_label)
        choose = QPushButton("∨", objectName="LabelPickButton")
        choose.setFixedWidth(36)
        choose.clicked.connect(self.show_label_selection)
        lr.addWidget(self.label_input, 1)
        lr.addWidget(choose)
        lg.addLayout(lr)

        self.label_chip_host = QWidget()
        self.label_chip_layout = QHBoxLayout(self.label_chip_host)
        self.label_chip_layout.setContentsMargins(0, 0, 0, 0)
        self.label_chip_layout.setSpacing(5)
        lg.addWidget(self.label_chip_host)
        cl.addWidget(label_group)

        # Current annotations
        ann_group = QFrame(objectName="InspectorGroup")
        ag = QVBoxLayout(ann_group)
        ag.setContentsMargins(10, 9, 10, 9)
        ag.setSpacing(6)
        ag.addWidget(QLabel("ANNOTATIONS · CURRENT IMAGE", objectName="GroupTitle"))
        self.annotation_list = QListWidget(objectName="AnnotationList")
        self.annotation_list.setMinimumHeight(118)
        self.annotation_list.itemClicked.connect(self._annotation_item_clicked)
        ag.addWidget(self.annotation_list)
        cl.addWidget(ann_group)

        # Actions
        actions_group = QFrame(objectName="InspectorGroup")
        ac = QGridLayout(actions_group)
        ac.setContentsMargins(10, 9, 10, 9)
        ac.setHorizontalSpacing(6)
        ac.setVerticalSpacing(6)
        title = QLabel("SELECTED ANNOTATION", objectName="GroupTitle")
        ac.addWidget(title, 0, 0, 1, 2)

        self.edit_label_btn = QPushButton("Edit Label", objectName="InspectorButton")
        self.delete_btn = QPushButton("Delete", objectName="DangerButton")
        self.copy_btn = QPushButton("Copy", objectName="InspectorButton")
        self.paste_btn = QPushButton("Paste", objectName="InspectorButton")
        self.finish_polygon_btn = QPushButton("Finish Polygon", objectName="InspectorButton")
        self.edit_label_btn.clicked.connect(self.edit_selected_label)
        self.delete_btn.clicked.connect(self.delete_selected)
        self.copy_btn.clicked.connect(self.copy_selected)
        self.paste_btn.clicked.connect(self.paste_shape)
        self.finish_polygon_btn.clicked.connect(self.finish_polygon)

        ac.addWidget(self.edit_label_btn, 1, 0)
        ac.addWidget(self.delete_btn, 1, 1)
        ac.addWidget(self.copy_btn, 2, 0)
        ac.addWidget(self.paste_btn, 2, 1)
        ac.addWidget(self.finish_polygon_btn, 3, 0, 1, 2)
        cl.addWidget(actions_group)
        cl.addStretch(1)

        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        save = QFrame(objectName="SavePanel")
        sl = QVBoxLayout(save)
        sl.setContentsMargins(10, 9, 10, 9)
        sl.setSpacing(6)

        status = QHBoxLayout()
        status.addWidget(QLabel("Auto-save", objectName="AutosaveText"))
        status.addStretch(1)
        self.autosave_state = QLabel("● Saved", objectName="AutosaveReady")
        status.addWidget(self.autosave_state)
        sl.addLayout(status)

        sr = QHBoxLayout()
        self.save_current_btn = QPushButton("Save Current", objectName="SaveSecondary")
        self.save_all_btn = QPushButton("Final Save & Verify", objectName="SavePrimary")
        self.save_current_btn.clicked.connect(self.save_current)
        self.save_all_btn.clicked.connect(self.save_all)
        sr.addWidget(self.save_current_btn)
        sr.addWidget(self.save_all_btn)
        sl.addLayout(sr)

        self.overwrite_btn = QPushButton("Overwrite Existing Files", objectName="OverwriteButton")
        self.overwrite_btn.clicked.connect(self.save_and_overwrite)
        sl.addWidget(self.overwrite_btn)

        layout.addWidget(save)
        return panel

    def _apply_style(self):
        self.setStyleSheet("""
        QWidget#AnnotationPageQt6 { background:transparent; color:#101A2D; }
        QWidget#AnnotationPageQt6 QLabel { background:transparent; border:0; }

        QFrame#ContextCard {
            background:#FFFFFF; border:1px solid #C4D1E1; border-radius:13px;
        }
        QLabel#ContextKey {
            color:#5B6E86; font-size:8px; font-weight:850; letter-spacing:0.6px;
        }
        QLabel#ContextValue {
            color:#14243B; font-size:10.5px; font-weight:780;
        }
        QComboBox#ProjectSelector {
            min-height:34px;
            background:#FFFFFF;
            color:#17263D;
            border:1px solid #AEBFD5;
            border-radius:9px;
            padding:0 34px 0 10px;
            font-size:10.5px;
            font-weight:780;
        }
        QComboBox#ProjectSelector:hover,
        QComboBox#ProjectSelector:focus,
        QComboBox#ProjectSelector:on {
            background:#FFFFFF;
            border:1px solid #2868E8;
        }
        QComboBox#ProjectSelector::drop-down {
            subcontrol-origin:padding;
            subcontrol-position:top right;
            width:29px;
            border:0;
            border-left:1px solid #D7E1ED;
        }
        QComboBox#ProjectSelector::down-arrow {
            image:none;
            width:0px;
            height:0px;
        }
        QListView#ProjectSelectorView {
            background:#FFFFFF;
            color:#17263D;
            border:1px solid #AEBFD5;
            border-radius:9px;
            padding:5px;
            outline:0;
            font-size:10.5px;
            font-weight:700;
        }
        QListView#ProjectSelectorView::item {
            background:#FFFFFF;
            color:#17263D;
            min-height:32px;
            padding:4px 8px;
            border-radius:6px;
        }
        QListView#ProjectSelectorView::item:hover {
            background:#F0F5FF;
            color:#1D5BD0;
        }
        QListView#ProjectSelectorView::item:selected {
            background:#E5EEFF;
            color:#1D5BD0;
            font-weight:800;
        }

        QPushButton#ContextButton {
            background:#FFFFFF; color:#2868E8; border:1px solid #B9C9DB;
            border-radius:9px; padding:0 11px; font-size:9px; font-weight:760;
        }
        QPushButton#ContextButton:hover { background:#EAF1FF; border-color:#8EB0E6; }

        QFrame#ToolRail, QFrame#CanvasPanel, QFrame#Inspector {
            background:#FFFFFF; border:1px solid #BFCEDF; border-radius:16px;
        }
        QLabel#RailSection {
            color:#60728A; font-size:8.7px; font-weight:850; letter-spacing:0.7px;
        }
        QPushButton#ToolButton {
            background:#FFFFFF;
            color:#405B78;
            border:1px solid #BFCFE2;
            border-radius:12px;
            padding:0;
        }
        QPushButton#ToolButton:hover {
            background:#F0F5FF;
            border:1px solid #93B1E2;
        }
        QPushButton#ToolButton:checked {
            background:#E5EEFF;
            border:2px solid #2868E8;
        }
        QPushButton#ToolButton:pressed {
            background:#DDE9FF;
        }

        QFrame#CanvasToolbar {
            background:#FCFDFE; border:0; border-bottom:1px solid #D6E0EB;
        }
        QPushButton#ToolbarButton {
            min-height:32px; background:#FFFFFF; color:#455E7B;
            border:1px solid #C4D2E3; border-radius:8px;
            padding:0 9px; font-size:9px; font-weight:780;
        }
        QPushButton#ToolbarButton:hover { background:#EEF4FF; color:#2868E8; }
        QPushButton#ToolbarButton:checked { background:#E5EEFF; color:#2868E8; border-color:#8FB0EA; }
        QLabel#FilenameLabel {
            color:#52667E; font-family:Consolas; font-size:8.8px;
        }

        QFrame#CanvasWrap { background:#FFFFFF; border:0; }
        QFrame#CanvasStatus {
            background:#FAFCFF; border:0; border-top:1px solid #D7E1ED;
            min-height:31px;
        }
        QLabel#CanvasStatusText {
            color:#526A86; font-family:Consolas; font-size:8.5px;
        }

        QListWidget#ThumbnailList {
            background:#F9FBFE; color:#425874; border:0;
            border-top:1px solid #D6E0EB; padding:7px;
            outline:0;
        }
        QListWidget#ThumbnailList::item {
            background:transparent; border:0; padding:0; margin:0;
        }
        QWidget#ThumbnailCard {
            background:#FFFFFF;
            border:1px solid #C6D3E3;
            border-radius:9px;
        }
        QWidget#ThumbnailCard[selected="true"] {
            background:#EAF1FF;
            border:2px solid #2868E8;
        }
        QFrame#ThumbnailImageHost {
            background:#F2F5F8;
            border:0;
            border-radius:6px;
        }
        QLabel#ThumbnailPreview { background:transparent; border:0; }
        QLabel#ThumbnailName {
            color:#425874; font-family:Consolas; font-size:7.8px;
            font-weight:650;
        }
        QLabel#ThumbnailCheck {
            background:#07965D; color:#FFFFFF;
            border:2px solid #FFFFFF; border-radius:8px;
            font-size:9px; font-weight:900;
        }

        QFrame#InspectorHead { background:#FFFFFF; border:0; border-bottom:1px solid #D6E0EB; }
        QLabel#InspectorTitle { color:#101A2D; font-size:13.5px; font-weight:850; }
        QLabel#InspectorSubtitle { color:#5B6F87; font-size:9.5px; font-weight:600; }

        QScrollArea#InspectorScroll,
        QScrollArea#InspectorScroll > QWidget > QWidget { background:#FFFFFF; border:0; }

        QFrame#InspectorGroup {
            background:#FBFCFE; border:1px solid #C9D6E5; border-radius:11px;
        }
        QLabel#GroupTitle {
            color:#52667F; font-size:9.2px; font-weight:850; letter-spacing:0.55px;
        }
        QLabel#FieldLabel { color:#3E536D; font-size:9.5px; font-weight:760; }

        QLineEdit#LabelInput {
            min-height:36px; background:#FFFFFF; color:#18283F;
            border:1px solid #BFCEDF; border-radius:8px;
            padding:0 9px; font-size:10.8px; font-weight:650;
        }
        QLineEdit#LabelInput:focus { border:1px solid #2868E8; }
        QPushButton#LabelPickButton {
            min-height:36px; background:#FFFFFF; color:#2868E8;
            border:1px solid #BFCEDF; border-radius:8px; font-weight:800;
        }

        QPushButton#LabelChip {
            min-height:27px; background:#FFFFFF; color:#405873;
            border:1px solid #C4D2E3; border-radius:13px;
            padding:0 8px; font-size:8.7px; font-weight:760;
        }
        QPushButton#LabelChip:hover { background:#EAF1FF; color:#2868E8; }

        QListWidget#AnnotationList {
            background:transparent; border:0; outline:0;
        }
        QListWidget#AnnotationList::item {
            background:transparent; border:0; padding:0; margin:0 0 5px 0;
        }
        QWidget#AnnotationRow {
            background:#FFFFFF;
            border:1px solid #C7D4E4;
            border-radius:8px;
        }
        QWidget#AnnotationRow[selected="true"] {
            background:#EAF1FF;
            border:1px solid #2868E8;
        }
        QLabel#AnnotationRowLabel {
            color:#17263D; font-size:10.4px; font-weight:820;
        }
        QLabel#AnnotationTypePill {
            background:#EEF2F7; color:#5E7189;
            border-radius:8px; padding:3px 6px;
            font-size:8px; font-weight:700;
        }
        QLabel#AnnotationRowMeta {
            color:#65778D; font-family:Consolas;
            font-size:8.2px; font-weight:600;
        }

        QPushButton#InspectorButton, QPushButton#DangerButton {
            min-height:34px; background:#FFFFFF; color:#3E5876;
            border:1px solid #B9C9DB; border-radius:8px;
            font-size:9.2px; font-weight:780;
        }
        QPushButton#InspectorButton:hover { background:#EEF4FF; color:#2868E8; }
        QPushButton#DangerButton { color:#C93450; border-color:#EABBC4; }
        QPushButton#DangerButton:hover { background:#FFF1F3; }

        QFrame#SavePanel { background:#FCFDFE; border:0; border-top:1px solid #D6E0EB; }
        QLabel#AutosaveText { color:#52677F; font-size:9.2px; font-weight:650; }
        QLabel#AutosaveReady { color:#07965D; font-size:9.2px; font-weight:800; }
        QPushButton#SaveSecondary, QPushButton#SavePrimary {
            min-height:38px; border-radius:9px; font-size:9.6px; font-weight:800;
        }
        QPushButton#SaveSecondary {
            background:#FFFFFF; color:#2868E8; border:1px solid #B7C7DB;
        }
        QPushButton#SavePrimary {
            background:#2868E8; color:#FFFFFF; border:1px solid #2868E8;
        }
        QPushButton#SaveSecondary:hover { background:#EEF4FF; }
        QPushButton#SavePrimary:hover { background:#1E58CB; }
        QPushButton#OverwriteButton {
            min-height:35px; background:#FFFFFF; color:#52677F;
            border:1px solid #C4D2E3; border-radius:8px;
            font-size:9px; font-weight:760;
        }
        QPushButton#OverwriteButton:hover { background:#F2F6FB; }

        QScrollBar:vertical {
            background:transparent; width:8px; margin:2px;
        }
        QScrollBar::handle:vertical {
            background:#C8D4E3; border-radius:4px; min-height:25px;
        }
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical { height:0; }

        QScrollBar:horizontal {
            background:transparent; height:8px; margin:2px;
        }
        QScrollBar::handle:horizontal {
            background:#C8D4E3; border-radius:4px; min-width:25px;
        }
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal { width:0; }
        """)

    # ------------------------------------------------------------------
    # Project + dataset context
    # ------------------------------------------------------------------
    def refresh_context(self):
        previous_id = self.selected_project_id
        try:
            self.projects = list(ProjectDB().get_all_projects() or [])
        except Exception as exc:
            self.projects = []
            self.toast_requested.emit("Projects unavailable", str(exc))

        self.project_map = {
            _project_id(project): project
            for project in self.projects
            if _project_id(project)
        }

        self.project_selector.blockSignals(True)
        self.project_selector.clear()
        for project in self.projects:
            self.project_selector.addItem(
                str(project.get("name") or "Unnamed Project"),
                _project_id(project),
            )

        if self.projects:
            idx = self.project_selector.findData(previous_id)
            self.project_selector.setCurrentIndex(idx if idx >= 0 else 0)
            self.project_selector.setEnabled(True)
        else:
            self.project_selector.addItem("No projects available", "")
            self.project_selector.setEnabled(False)
        self.project_selector.blockSignals(False)

        if self.projects:
            project = self.project_map.get(
                str(self.project_selector.currentData() or ""),
                self.projects[0],
            )
            self._apply_project(project, auto_load=not bool(self.images))

    def _project_changed(self, _index: int):
        project = self.project_map.get(str(self.project_selector.currentData() or ""))
        if project:
            self._apply_project(project, auto_load=True)

    def _apply_project(self, project: dict, *, auto_load: bool):
        self.selected_project_id = _project_id(project)
        project_name = str(project.get("name") or "Project")

        candidate = self._find_project_dataset(project)
        if candidate:
            self.source_label.setText(str(candidate))
            if auto_load:
                self.load_folder(str(candidate), quiet=True)
                self.toast_requested.emit(
                    "Project dataset loaded",
                    f"{project_name}: {candidate.name}",
                )
        else:
            self.source_label.setText("No captured image folder found")
            if auto_load:
                self.folder = ""
                self.images = []
                self.annotations = {}
                self.current_index = -1
                self.current_image = None
                self.thumbnail_list.clear()
                self.canvas.clear_annotations()
                self.update_annotated_count()
                self._update_current_labels()

    def _find_project_dataset(self, project: dict) -> Path | None:
        """Find the newest image-containing folder for the selected project."""
        roots: list[Path] = []

        folder_path = project.get("folder_path")
        if folder_path:
            roots.append(Path(folder_path))

        project_name = str(project.get("name") or "")
        cwd = Path.cwd()
        roots.extend([
            cwd / "media" / "Capture_Input" / project_name,
            cwd / "Media" / "Capture_Input" / project_name,
            cwd / "media" / "Capture_Input" / _safe_folder_name(project_name),
        ])

        candidates: list[Path] = []
        for root in roots:
            try:
                if not root.exists():
                    continue
                if any(p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS for p in root.iterdir()):
                    candidates.append(root)
                for child in root.rglob("*"):
                    if not child.is_dir():
                        continue
                    try:
                        if any(
                            p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
                            for p in child.iterdir()
                        ):
                            candidates.append(child)
                    except Exception:
                        pass
            except Exception:
                pass

        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)

    # ------------------------------------------------------------------
    # Folder loading / annotations
    # ------------------------------------------------------------------
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Image Folder",
            self.folder or str(Path.home()),
        )
        if folder:
            self.load_folder(folder)

    def load_folder(self, folder: str, quiet: bool = False):
        folder = str(folder)
        try:
            images = sorted(
                str(Path(folder) / name)
                for name in os.listdir(folder)
                if str(name).lower().endswith(IMAGE_EXTENSIONS)
            )
        except Exception as exc:
            self.toast_requested.emit("Folder error", str(exc))
            return

        if not images:
            if not quiet:
                self.toast_requested.emit("No images found", "The selected folder contains no supported images.")
            return

        self.save_current_annotations()
        self.folder = folder
        self.images = images
        self.annotations = {}
        self.pending_saves.clear()
        self.existing_labels.clear()

        self.auto_load_existing_annotations()
        self._load_thumbnails()
        self.current_index = 0
        self.load_current_image()
        self.update_annotated_count()

        if not quiet:
            self.toast_requested.emit("Images loaded", f"{len(self.images)} image(s) loaded.")

    def load_folder_with_annotations(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Folder with Images and Annotations",
            self.folder or str(Path.home()),
        )
        if not folder:
            return
        self.load_folder(folder, quiet=True)
        self.load_annotations_from_current_folder()
        self.load_current_image()
        self.update_annotated_count()
        self.toast_requested.emit(
            "Images + annotations loaded",
            f"{len(self.images)} images · {len(self.existing_labels)} label(s)",
        )

    def auto_load_existing_annotations(self):
        for image_path in self.images:
            base = Path(image_path).stem
            for name in (f"{base}.json", f"{base.lower()}.json", f"{base.upper()}.json"):
                path = Path(self.folder) / name
                if not path.exists():
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    annotations = self._annotations_from_json(data)
                    if annotations:
                        self.annotations[image_path] = annotations
                        self._collect_labels(annotations)
                        break
                except Exception as exc:
                    print(f"[Annotation] Could not load {path}: {exc}")

    def load_annotations_from_current_folder(self):
        if not self.folder:
            return

        for json_path in Path(self.folder).glob("*.json"):
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                annotations = self._annotations_from_json(data)
                if not annotations:
                    continue

                image_name = os.path.basename(
                    str(data.get("imagePath") or data.get("image_path") or "")
                )
                target = None
                if image_name:
                    target = next(
                        (p for p in self.images if Path(p).name.lower() == image_name.lower()),
                        None,
                    )
                if not target:
                    target = next(
                        (p for p in self.images if Path(p).stem.lower() == json_path.stem.lower()),
                        None,
                    )
                if target:
                    self.annotations[target] = annotations
                    self._collect_labels(annotations)
            except Exception as exc:
                print(f"[Annotation] Could not load {json_path}: {exc}")

    def _annotations_from_json(self, data: dict) -> list[dict]:
        if "shapes" in data:
            return [
                {
                    "label": shape.get("label", "unknown"),
                    "shape": shape.get("shape_type", "polygon"),
                    "points": shape.get("points", []),
                }
                for shape in data.get("shapes", [])
            ]
        return list(data.get("annotations", []) or [])

    def _collect_labels(self, annotations: list[dict]):
        for annotation in annotations:
            label = str(annotation.get("label") or "").strip()
            if label:
                self.existing_labels.add(label)
        self._rebuild_label_chips()

    def _load_thumbnails(self):
        self.thumbnail_list.clear()
        self.thumbnail_list.setGridSize(QtCore.QSize(138, 94))
        self.thumbnail_list.setSpacing(3)

        for image_path in self.images:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, image_path)
            item.setSizeHint(QtCore.QSize(136, 92))
            self.thumbnail_list.addItem(item)

            card = ThumbnailCard(image_path)
            self.thumbnail_list.setItemWidget(item, card)

        self.update_thumbnail_status()

    def load_current_image(self):
        if not (0 <= self.current_index < len(self.images)):
            self.current_image = None
            self.filename_label.setText("No image loaded")
            self.image_counter_label.setText("0 / 0")
            self.refresh_inspector()
            return

        image_path = self.images[self.current_index]
        self.current_image = image_path

        self.canvas.load_image(image_path)
        self.canvas.setEnabled(True)

        for annotation in self.annotations.get(image_path, []):
            label = str(annotation.get("label") or "object")
            points = annotation.get("points", [])
            if annotation.get("shape") in ("rectangle", "rect") and len(points) >= 2:
                self.canvas.shapes.append(
                    (
                        "rect",
                        [
                            QtCore.QPoint(int(points[0][0]), int(points[0][1])),
                            QtCore.QPoint(int(points[1][0]), int(points[1][1])),
                        ],
                        label,
                    )
                )
            elif annotation.get("shape") == "polygon" and len(points) >= 3:
                self.canvas.shapes.append(
                    (
                        "polygon",
                        [QtCore.QPoint(int(x), int(y)) for x, y in points],
                        label,
                    )
                )

        self.canvas.update()
        self.thumbnail_list.setCurrentRow(self.current_index)
        self.filename_label.setText(Path(image_path).name)
        self.image_counter_label.setText(f"{self.current_index + 1} / {len(self.images)}")
        self.source_label.setText(self.folder)

        pix = self.canvas.original_pixmap
        if pix and not pix.isNull():
            self.canvas_info_label.setText(
                f"{pix.width()} × {pix.height()} · "
                f"{len(self.canvas.shapes)} annotations · Auto-saved"
            )

        self.refresh_inspector()
        self.update_thumbnail_status()
        QtCore.QTimer.singleShot(50, self.canvas.fit_to_window)

    def open_image_path(self, image_path: str):
        if image_path in self.images:
            self.save_current_annotations()
            self.current_index = self.images.index(image_path)
            self.load_current_image()

    def thumbnail_clicked(self, item: QListWidgetItem):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path in self.images:
            self.save_current_annotations()
            self.current_index = self.images.index(path)
            self.load_current_image()

    def prev_image(self):
        if self.current_index > 0:
            self.save_current_annotations()
            self.current_index -= 1
            self.load_current_image()

    def next_image(self):
        if self.current_index < len(self.images) - 1:
            self.save_current_annotations()
            self.current_index += 1
            self.load_current_image()

    # ------------------------------------------------------------------
    # Canvas operations
    # ------------------------------------------------------------------
    def change_mode(self, mode: str):
        mapping = {"Rectangle": "rect", "Polygon": "polygon", "Select": "select"}
        self.canvas.set_mode(mapping.get(mode, "select"))

        for name, button in self.tool_buttons.items():
            button.setChecked(name == mode)
        for name, button in self.toolbar_mode_buttons.items():
            button.setChecked(name == mode)

        messages = {
            "Select": "SELECT · click annotation to edit",
            "Rectangle": "RECTANGLE · click and drag to draw",
            "Polygon": "POLYGON · click points · right-click to finish",
        }
        self.canvas_mode_label.setText(messages.get(mode, mode.upper()))

    def update_current_label(self, label: str):
        label = str(label or "").strip()
        self.canvas.set_label(label or "object")
        if label:
            self.existing_labels.add(label)
            self._rebuild_label_chips()

    def set_label(self, label: str):
        self.label_input.setText(label)
        self.update_current_label(label)

    def _rebuild_label_chips(self):
        while self.label_chip_layout.count():
            item = self.label_chip_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        labels = sorted(self.existing_labels)[:5]
        for label in labels:
            button = QPushButton(label, objectName="LabelChip")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, value=label: self.set_label(value))
            self.label_chip_layout.addWidget(button)
        self.label_chip_layout.addStretch(1)

    def show_label_selection(self):
        dialog = LabelSelectionDialog(
            sorted(self.existing_labels),
            self.label_input.text(),
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_label:
            self.set_label(dialog.selected_label)

    def auto_open_label_editor(self):
        if self.canvas.shapes and self.canvas.selected_shape_index == -1:
            self.canvas.selected_shape_index = len(self.canvas.shapes) - 1
            self.show_label_selection_after_annotation()

    def show_label_selection_after_annotation(self):
        index = self.canvas.selected_shape_index
        if not (0 <= index < len(self.canvas.shapes)):
            return
        current = self.canvas.shapes[index][2]
        dialog = LabelSelectionDialog(sorted(self.existing_labels), current, self)
        dialog.input.selectAll()
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_label:
            self.canvas.edit_selected_label(dialog.selected_label)
            self.existing_labels.add(dialog.selected_label)
            self.label_input.setText(dialog.selected_label)
            self.auto_save_annotations()
            self.refresh_inspector()

    def edit_selected_label(self):
        index = self.canvas.selected_shape_index
        if not (0 <= index < len(self.canvas.shapes)):
            self.toast_requested.emit("No annotation selected", "Select an annotation first.")
            return
        current = self.canvas.shapes[index][2]
        dialog = LabelSelectionDialog(sorted(self.existing_labels), current, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_label:
            self.canvas.edit_selected_label(dialog.selected_label)
            self.existing_labels.add(dialog.selected_label)
            self.label_input.setText(dialog.selected_label)
            self.auto_save_annotations()
            self.refresh_inspector()

    def finish_polygon(self):
        self.canvas.finish_polygon()
        self.auto_save_annotations()
        self.refresh_inspector()

    def clear_annotations(self):
        if not self.canvas.shapes:
            return
        reply = QMessageBox.question(
            self,
            "Clear Annotations",
            "Remove all annotations from the current image?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.canvas.clear_annotations()
            self.auto_save_annotations(force_empty=True)
            self.refresh_inspector()

    def delete_selected(self):
        before = len(self.canvas.shapes)
        self.canvas.delete_selected_shape()
        if len(self.canvas.shapes) < before:
            self.auto_save_annotations(force_empty=True)
            self.toast_requested.emit("Annotation deleted", "Selected annotation was removed.")
            self.refresh_inspector()

    def copy_selected(self):
        self.canvas.copy_selected_shape()
        self.toast_requested.emit("Annotation copied", "Paste it on the current image with Ctrl+V.")

    def paste_shape(self):
        self.canvas.paste_shape()
        self.auto_save_annotations()
        self.refresh_inspector()

    def undo(self):
        self.canvas.undo()
        self.auto_save_annotations(force_empty=True)
        self.refresh_inspector()

    def redo(self):
        self.canvas.redo()
        self.auto_save_annotations(force_empty=True)
        self.refresh_inspector()

    def zoom_in(self):
        self.canvas.zoom_in()

    def zoom_out(self):
        self.canvas.zoom_out()

    def fit_to_window(self):
        self.canvas.fit_to_window()

    def _canvas_changed(self):
        self.auto_save_annotations(force_empty=True)
        self.refresh_inspector()

    def _poll_canvas_state(self):
        signature = tuple(
            (
                shape_type,
                label,
                tuple((p.x(), p.y()) for p in points),
            )
            for shape_type, points, label in self.canvas.shapes
        )
        selected = self.canvas.selected_shape_index

        if signature != self._last_shape_signature:
            self._last_shape_signature = signature
            if self.current_image:
                self.auto_save_annotations(force_empty=True)
            self.refresh_inspector()

        if selected != self._last_selection_index:
            self._last_selection_index = selected
            self.refresh_inspector()

    def _annotation_item_clicked(self, item: QListWidgetItem):
        index = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(index, int) and 0 <= index < len(self.canvas.shapes):
            self.canvas.selected_shape_index = index
            self.canvas.update()
            self.refresh_inspector()

    def refresh_inspector(self):
        self.annotation_list.blockSignals(True)
        self.annotation_list.clear()

        for index, (shape_type, points, label) in enumerate(self.canvas.shapes):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setSizeHint(QtCore.QSize(0, 54))

            if shape_type == "rect" and len(points) >= 2:
                rect = QtCore.QRect(points[0], points[1]).normalized()
                meta = f"x {rect.x()}  ·  y {rect.y()}  ·  w {rect.width()}  ·  h {rect.height()}"
                type_name = "RECTANGLE"
            else:
                meta = f"{len(points)} points"
                type_name = "POLYGON"

            self.annotation_list.addItem(item)
            row = AnnotationRowWidget(
                label=label,
                type_name=type_name,
                meta=meta,
                selected=index == self.canvas.selected_shape_index,
            )
            self.annotation_list.setItemWidget(item, row)

            if index == self.canvas.selected_shape_index:
                self.annotation_list.setCurrentItem(item)

        self.annotation_list.blockSignals(False)

        count = len(self.canvas.shapes)
        self.inspector_subtitle.setText(f"Current image · {count} annotation{'s' if count != 1 else ''}")
        if self.canvas.original_pixmap:
            self.canvas_info_label.setText(
                f"{self.canvas.original_pixmap.width()} × {self.canvas.original_pixmap.height()} · "
                f"{count} annotation{'s' if count != 1 else ''} · Auto-saved"
            )

        index = self.canvas.selected_shape_index
        if 0 <= index < len(self.canvas.shapes):
            selected_label = self.canvas.shapes[index][2]
            if self.label_input.text() != selected_label:
                self.label_input.blockSignals(True)
                self.label_input.setText(selected_label)
                self.label_input.blockSignals(False)

    # ------------------------------------------------------------------
    # Auto-save + persistence
    # ------------------------------------------------------------------
    def auto_save_annotations(self, force_empty: bool = False):
        if not self.auto_save_enabled or not self.current_image:
            return

        annotations = self.canvas.get_annotations()
        if annotations or force_empty:
            self.annotations[self.current_image] = annotations
            self.pending_saves.add(self.current_image)
            self.autosave_state.setText("● Saved")
            self.update_annotated_count()
            self.update_thumbnail_status()

    def save_current_annotations(self):
        if self.current_image:
            self.auto_save_annotations(force_empty=True)

    def update_annotated_count(self):
        annotated = sum(1 for image in self.images if self.annotations.get(image))
        self.annotated_count_label.setText(f"{annotated} / {len(self.images)} images")

    def update_thumbnail_status(self):
        for row in range(self.thumbnail_list.count()):
            item = self.thumbnail_list.item(row)
            image_path = item.data(Qt.ItemDataRole.UserRole)
            count = len(self.annotations.get(image_path, []))
            item.setSelected(row == self.current_index)

            card = self.thumbnail_list.itemWidget(item)
            if isinstance(card, ThumbnailCard):
                card.set_state(
                    annotated=count > 0,
                    selected=row == self.current_index,
                )

    def ask_save_format(self) -> str | None:
        dialog = SaveFormatDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.format_choice
        return None

    def save_current(self):
        self.save_current_annotations()
        if not self.current_image:
            self.toast_requested.emit("No image loaded", "Open an image folder first.")
            return
        if not self.annotations.get(self.current_image):
            self.toast_requested.emit("Nothing to save", "The current image has no annotations.")
            return

        fmt = self.ask_save_format()
        if not fmt:
            return

        reply = QMessageBox.question(
            self,
            "Save Current",
            "Save in the current image folder?\n\n"
            "Yes: overwrite/create beside the image\n"
            "No: create a new annotations folder",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Cancel:
            return

        overwrite = reply == QMessageBox.StandardButton.Yes
        if self.save_annotations_to_file(self.current_image, overwrite=overwrite, format_choice=fmt):
            self.pending_saves.discard(self.current_image)
            self.toast_requested.emit(
                "Annotation saved",
                f"{Path(self.current_image).name} saved as {fmt.upper()}.",
            )

    def save_and_overwrite(self):
        self.save_current_annotations()
        if not self.folder:
            return

        fmt = self.ask_save_format()
        if not fmt:
            return

        reply = QMessageBox.question(
            self,
            "Overwrite Existing Files",
            f"Write all current annotations as {fmt.upper()} beside the source images?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        saved = 0
        errors = 0
        for image_path in self.images:
            if not self.annotations.get(image_path):
                continue
            try:
                if self.save_annotations_to_file(
                    image_path,
                    overwrite=True,
                    format_choice=fmt,
                ):
                    saved += 1
                else:
                    errors += 1
            except Exception:
                errors += 1

        self.pending_saves.clear()
        self.toast_requested.emit(
            "Overwrite complete",
            f"{saved} {fmt.upper()} file(s) written"
            + (f" · {errors} error(s)" if errors else ""),
        )

    def save_all(self):
        self.save_current_annotations()
        if not self.images:
            self.toast_requested.emit("No dataset loaded", "Open an image folder first.")
            return
        VerificationDialog(self, self).exec()

    def export_all_annotations(self) -> bool:
        fmt = self.ask_save_format()
        if not fmt:
            return False

        if not self.folder:
            return False

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_folder = Path(self.folder) / f"annotations_{fmt}_{timestamp}"
        output_folder.mkdir(parents=True, exist_ok=True)

        saved = 0
        errors = 0
        for image_path in self.images:
            if not self.annotations.get(image_path):
                continue
            try:
                ok = (
                    self.save_annotations_as_json(image_path, output_folder)
                    if fmt == "json"
                    else self.save_annotations_as_xml(image_path, output_folder)
                )
                if ok:
                    try:
                        shutil.copy2(image_path, output_folder / Path(image_path).name)
                    except Exception:
                        pass
                    saved += 1
                else:
                    errors += 1
            except Exception as exc:
                print(f"[Annotation export] {image_path}: {exc}")
                errors += 1

        self.pending_saves.clear()
        self.toast_requested.emit(
            "Annotation export complete",
            f"{saved} annotated image(s) exported to {output_folder.name}"
            + (f" · {errors} error(s)" if errors else ""),
        )
        return saved > 0

    def save_annotations_to_file(
        self,
        image_path: str,
        overwrite: bool = False,
        format_choice: str = "json",
    ) -> bool:
        if not self.annotations.get(image_path):
            return False

        if overwrite:
            output = Path(self.folder)
        else:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            output = Path(self.folder) / f"annotations_{format_choice}_{timestamp}"
            output.mkdir(parents=True, exist_ok=True)

        if format_choice == "json":
            return self.save_annotations_as_json(image_path, output, overwrite=overwrite)
        return self.save_annotations_as_xml(image_path, output, overwrite=overwrite)

    def save_annotations_as_json(
        self,
        image_path: str,
        output_folder: str | Path,
        overwrite: bool = False,
    ) -> bool:
        annotations = self.annotations.get(image_path, [])
        if not annotations:
            return False

        output_folder = Path(output_folder)
        output_folder.mkdir(parents=True, exist_ok=True)

        pix = QtGui.QPixmap(image_path)
        image_width = pix.width() if not pix.isNull() else 0
        image_height = pix.height() if not pix.isNull() else 0

        shapes = []
        for annotation in annotations:
            shape_type = annotation.get("shape", "polygon")
            labelme_type = "rectangle" if shape_type in ("rect", "rectangle") else "polygon"
            shapes.append(
                {
                    "label": annotation.get("label", "unknown"),
                    "points": annotation.get("points", []),
                    "group_id": None,
                    "description": "",
                    "shape_type": labelme_type,
                    "flags": {},
                    "mask": None,
                }
            )

        try:
            image_data = base64.b64encode(Path(image_path).read_bytes()).decode("utf-8")
        except Exception:
            image_data = None

        data = {
            "version": "5.5.0",
            "flags": {},
            "shapes": shapes,
            "imagePath": Path(image_path).name,
            "imageData": image_data,
            "imageHeight": image_height,
            "imageWidth": image_width,
        }

        path = output_folder / f"{Path(image_path).stem}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True

    def save_annotations_as_xml(
        self,
        image_path: str,
        output_folder: str | Path,
        overwrite: bool = False,
    ) -> bool:
        annotations = self.annotations.get(image_path, [])
        if not annotations:
            return False

        pix = QtGui.QPixmap(image_path)
        width = pix.width() if not pix.isNull() else 0
        height = pix.height() if not pix.isNull() else 0

        root = ET.Element("annotation")
        ET.SubElement(root, "folder").text = Path(image_path).parent.name
        ET.SubElement(root, "filename").text = Path(image_path).name
        ET.SubElement(root, "path").text = str(Path(image_path).resolve())

        source = ET.SubElement(root, "source")
        ET.SubElement(source, "database").text = "Unknown"

        size = ET.SubElement(root, "size")
        ET.SubElement(size, "width").text = str(width)
        ET.SubElement(size, "height").text = str(height)
        ET.SubElement(size, "depth").text = "3"
        ET.SubElement(root, "segmented").text = "0"

        object_count = 0
        for annotation in annotations:
            if annotation.get("shape") not in ("rect", "rectangle"):
                continue
            points = annotation.get("points", [])
            if len(points) < 2:
                continue
            xs = [int(point[0]) for point in points]
            ys = [int(point[1]) for point in points]

            obj = ET.SubElement(root, "object")
            ET.SubElement(obj, "name").text = str(annotation.get("label", "unknown"))
            ET.SubElement(obj, "pose").text = "Unspecified"
            ET.SubElement(obj, "truncated").text = "0"
            ET.SubElement(obj, "difficult").text = "0"

            box = ET.SubElement(obj, "bndbox")
            ET.SubElement(box, "xmin").text = str(min(xs))
            ET.SubElement(box, "ymin").text = str(min(ys))
            ET.SubElement(box, "xmax").text = str(max(xs))
            ET.SubElement(box, "ymax").text = str(max(ys))
            object_count += 1

        if object_count == 0:
            self.toast_requested.emit(
                "XML export",
                "Pascal VOC export supports rectangle annotations; no rectangles were found.",
            )
            return False

        rough = ET.tostring(root, "utf-8")
        pretty = minidom.parseString(rough).toprettyxml(indent="\t")

        output_folder = Path(output_folder)
        output_folder.mkdir(parents=True, exist_ok=True)
        (output_folder / f"{Path(image_path).stem}.xml").write_text(
            pretty,
            encoding="utf-8",
        )
        return True

    # ------------------------------------------------------------------
    # Help / shortcuts / responsive
    # ------------------------------------------------------------------
    def show_help(self):
        QMessageBox.information(
            self,
            "Annotation Tool Shortcuts",
            "R  Rectangle\\n"
            "P  Polygon\\n"
            "S  Select\\n"
            "E  Edit selected label\\n"
            "Delete  Delete selected annotation\\n"
            "Ctrl+C / Ctrl+V  Copy / Paste\\n"
            "Ctrl+Z / Ctrl+Y  Undo / Redo\\n"
            "A / Left  Previous image\\n"
            "D / Right  Next image\\n"
            "Ctrl + Mouse Wheel  Zoom",
        )

    def _setup_shortcuts(self):
        shortcuts = {
            "R": lambda: self.change_mode("Rectangle"),
            "P": lambda: self.change_mode("Polygon"),
            "S": lambda: self.change_mode("Select"),
            "E": self.edit_selected_label,
            "Delete": self.delete_selected,
            "Ctrl+D": self.delete_selected,
            "Ctrl+C": self.copy_selected,
            "Ctrl+V": self.paste_shape,
            "Ctrl+Z": self.undo,
            "Ctrl+Y": self.redo,
            "A": self.prev_image,
            "Left": self.prev_image,
            "D": self.next_image,
            "Right": self.next_image,
        }
        self._shortcuts = []
        for sequence, slot in shortcuts.items():
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(sequence), self)
            shortcut.activated.connect(slot)
            self._shortcuts.append(shortcut)

    def _update_current_labels(self):
        self.filename_label.setText("No image loaded")
        self.image_counter_label.setText("0 / 0")
        self.annotated_count_label.setText("0 / 0 images")
        self.inspector_subtitle.setText("Current image · 0 annotations")
        self.canvas_info_label.setText("No image")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.width()

        if width < 1040:
            self.inspector.setMaximumWidth(270)
            self.inspector.setMinimumWidth(245)
            self.tool_rail.setFixedWidth(72)
        else:
            self.inspector.setMinimumWidth(275)
            self.inspector.setMaximumWidth(315)
            self.tool_rail.setFixedWidth(76)

    def shutdown(self):
        try:
            self.save_current_annotations()
        except Exception:
            pass


AnnotationTool = AnnotationPageQt6
