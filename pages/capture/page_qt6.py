"""Final PyQt6 Image Capturing page.

Approved flow:
    1. Capture Type (Area / Line)
    2. Camera Brand / SDK
    3. Detect & Select Cameras
    4. Camera Settings
    5. Capture Plan
    6. Storage
    7. Capture
    8. Review

The page uses the Qt-neutral multi-brand adapter layer in
services.capture.adapters.  Vendor SDK work is always executed in QThread
workers so hardware discovery/capture does not freeze the GUI.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QDoubleSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from services.capture.adapters import (
    CameraDevice,
    CameraSettings,
    CaptureSessionWorker,
    DiscoveryWorker,
    PreviewWorker,
    SettingsWorker,
    adapter_infos,
)
from ui.qt6.icons import icon, icon_pixmap
from ui.qt6.widgets import AnimatedCard, IconBadge


try:
    from db import ProjectDB
except ImportError:  # pragma: no cover
    try:
        from src.db import ProjectDB
    except ImportError:
        from src.database.db import ProjectDB


def _safe_name(value: str) -> str:
    value = re.sub(r"[^\w\- ]+", "", str(value or "Capture"))
    value = re.sub(r"\s+", "_", value).strip("_")
    return value or "Capture"


def _default_capture_root(project_name: str) -> Path:
    root = Path.home() / "Documents" / "EyresAiPlatform" / "Projects"
    root.mkdir(parents=True, exist_ok=True)
    folder = root / _safe_name(project_name)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _qimage_from_array(frame) -> QImage | None:
    if frame is None:
        return None
    try:
        import numpy as np

        array = np.asarray(frame)
        if array.ndim == 2:
            if array.dtype != np.uint8:
                lo = float(array.min())
                hi = float(array.max())
                if hi > lo:
                    array = ((array - lo) * (255.0 / (hi - lo))).astype(np.uint8)
                else:
                    array = np.zeros_like(array, dtype=np.uint8)
            array = np.ascontiguousarray(array)
            height, width = array.shape
            return QImage(
                array.data,
                width,
                height,
                int(array.strides[0]),
                QImage.Format.Format_Grayscale8,
            ).copy()

        if array.ndim == 3 and array.shape[2] >= 3:
            array = np.ascontiguousarray(array[..., :3])
            height, width, _ = array.shape
            # Most industrial SDKs expose BGR or RGB.  For preview, use BGR888
            # where available and fall back to RGB888.
            fmt = getattr(QImage.Format, "Format_BGR888", QImage.Format.Format_RGB888)
            return QImage(
                array.data,
                width,
                height,
                int(array.strides[0]),
                fmt,
            ).copy()
    except Exception:
        return None
    return None


class ProjectComboBox(QComboBox):
    """Non-native project selector with a predictable white popup."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ProjectSelector")
        self.setMinimumHeight(34)
        self.setMinimumWidth(235)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.setMaxVisibleItems(8)

        view = QListView(self)
        view.setObjectName("ProjectSelectorView")
        view.setUniformItemSizes(True)
        view.setSpacing(1)
        view.setMinimumWidth(260)
        self.setView(view)

    def showPopup(self):
        # Force the list view to be at least as wide as the field.
        self.view().setMinimumWidth(max(260, self.width()))
        super().showPopup()

        # Qt/Windows can place QComboBox popups over the field. Reposition it
        # just below the selector so CURRENT PROJECT remains visible.
        QtCore.QTimer.singleShot(0, self._position_popup)

    def _position_popup(self):
        try:
            popup = self.view().window()
            global_pos = self.mapToGlobal(QtCore.QPoint(0, self.height() + 4))
            popup.move(global_pos)
            popup.resize(max(260, self.width()), popup.height())
        except Exception:
            pass


class StepPill(QPushButton):
    def __init__(self, number: int, title: str, parent=None):
        super().__init__(f"{number}   {title}", parent)
        self.number = number
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(43)
        self.setMinimumWidth(112)
        self.setProperty("complete", False)
        self.setStyleSheet("""
        QPushButton {
            background:transparent; color:#697990; border:0; border-radius:10px;
            text-align:left; padding:0 10px; font-size:9.5px; font-weight:700;
        }
        QPushButton:hover { background:#F5F8FD; color:#34506F; }
        QPushButton:checked {
            background:#EEF4FF; color:#215BCB; font-weight:800;
        }
        QPushButton[complete="true"] { color:#078A57; }
        """)

    def set_complete(self, complete: bool):
        self.setProperty("complete", bool(complete))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class ChoiceCard(AnimatedCard):
    clicked = pyqtSignal(str)

    def __init__(
        self,
        key: str,
        title: str,
        subtitle: str,
        icon_name: str,
        tags: list[str] | None = None,
        *,
        min_height: int = 220,
        parent=None,
    ):
        super().__init__(parent)
        self.key = key
        self._selected = False
        self.setObjectName("ChoiceCard")
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(min_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 17, 18, 16)
        layout.setSpacing(7)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.badge = IconBadge(icon_name, "#2868E8", "#EEF4FF")
        self.badge.setFixedSize(72, 72)
        layout.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignHCenter)

        title_label = QLabel(title, objectName="ChoiceTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        subtitle_label = QLabel(subtitle, objectName="ChoiceSubtitle")
        subtitle_label.setWordWrap(True)
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle_label)

        if tags:
            tag_host = QWidget()
            row = QHBoxLayout(tag_host)
            row.setContentsMargins(0, 5, 0, 0)
            row.setSpacing(5)
            row.setAlignment(Qt.AlignmentFlag.AlignCenter)
            for text in tags:
                chip = QLabel(text, objectName="ChoiceTag")
                row.addWidget(chip)
            layout.addWidget(tag_host)

        layout.addStretch(1)

    def set_selected(self, selected: bool):
        self._selected = bool(selected)
        self.setProperty("selected", self._selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self.badge.animate_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.badge.animate_hover(False)
        super().leaveEvent(event)


class BrandCard(AnimatedCard):
    clicked = pyqtSignal(str)

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self.setObjectName("BrandCard")
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(142)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 13, 14, 13)
        layout.setSpacing(4)

        top = QHBoxLayout()
        self.badge = IconBadge("capture", "#2868E8", "#EEF4FF")
        self.badge.setFixedSize(43, 43)
        top.addWidget(self.badge)

        status = QLabel(
            "READY" if info.available else "SDK NEEDED",
            objectName="AdapterReady" if info.available else "AdapterMissing",
        )
        status.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        top.addStretch(1)
        top.addWidget(status, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        layout.addWidget(QLabel(info.display_name, objectName="BrandName"))
        layout.addWidget(QLabel(info.sdk_name, objectName="BrandSdk"))
        layout.addStretch(1)

    def set_selected(self, selected: bool):
        self.setProperty("selected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.info.key)
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self.badge.animate_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.badge.animate_hover(False)
        super().leaveEvent(event)


class DeviceCard(AnimatedCard):
    toggled = pyqtSignal(object, bool)

    def __init__(self, device: CameraDevice, selected: bool = True, parent=None):
        super().__init__(parent)
        self.device = device
        self._selected = bool(selected)
        self.setObjectName("DeviceCard")
        self.setProperty("selected", self._selected)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(92)

        row = QHBoxLayout(self)
        row.setContentsMargins(13, 12, 13, 12)
        row.setSpacing(11)

        self.badge = IconBadge("capture", "#2868E8", "#EEF4FF")
        self.badge.setFixedSize(43, 43)
        row.addWidget(self.badge)

        copy = QVBoxLayout()
        copy.setSpacing(3)
        copy.addWidget(QLabel(device.model, objectName="DeviceName"))
        meta = QLabel(
            f"ID: {device.serial or device.backend_id}\n"
            f"{device.transport or device.vendor}",
            objectName="DeviceMeta",
        )
        copy.addWidget(meta)
        row.addLayout(copy, 1)

        self.check = QLabel("✓" if self._selected else "", objectName="DeviceCheck")
        self.check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.check.setFixedSize(22, 22)
        row.addWidget(self.check)

    def set_selected(self, selected: bool, emit_signal: bool = True):
        selected = bool(selected)
        if selected == self._selected:
            return
        self._selected = selected
        self.setProperty("selected", selected)
        self.check.setText("✓" if selected else "")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
        if emit_signal:
            self.toggled.emit(self.device, selected)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.set_selected(not self._selected)
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self.badge.animate_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.badge.animate_hover(False)
        super().leaveEvent(event)


class ReadinessRail(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ReadinessRail")
        self.setMinimumWidth(235)
        self.setMaximumWidth(285)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Session Readiness", objectName="RailTitle"))
        layout.addWidget(QLabel("Live capture status.", objectName="RailSubtitle"))

        status = QFrame(objectName="ReadinessBox")
        status_row = QHBoxLayout(status)
        status_row.setContentsMargins(11, 10, 11, 10)
        status_row.setSpacing(9)

        self.percent = QLabel("40%", objectName="ReadinessPercent")
        self.percent.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.percent.setFixedSize(42, 42)
        status_row.addWidget(self.percent)

        status_copy = QVBoxLayout()
        status_copy.setSpacing(2)
        self.status_title = QLabel("Hardware setup", objectName="ReadinessTitle")
        self.status_subtitle = QLabel("Select the camera brand.", objectName="ReadinessSubtitle")
        status_copy.addWidget(self.status_title)
        status_copy.addWidget(self.status_subtitle)
        status_row.addLayout(status_copy, 1)
        layout.addWidget(status)

        self.summary_labels: dict[str, QLabel] = {}
        for key, title in (
            ("project", "Project"),
            ("type", "Capture type"),
            ("brand", "Brand"),
            ("devices", "Devices"),
            ("count", "Images / camera"),
            ("storage", "Storage"),
        ):
            row = QFrame(objectName="RailRow")
            hl = QHBoxLayout(row)
            hl.setContentsMargins(1, 7, 1, 7)
            hl.setSpacing(8)
            hl.addWidget(QLabel(title, objectName="RailKey"))
            value = QLabel("—", objectName="RailValue")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            hl.addWidget(value, 1)
            layout.addWidget(row)
            self.summary_labels[key] = value

        layout.addSpacing(3)
        layout.addWidget(QLabel("PREFLIGHT", objectName="PreflightTitle"))

        self.checks: dict[str, tuple[QLabel, QLabel]] = {}
        for key, text in (
            ("type", "Capture type selected"),
            ("brand", "Camera brand selected"),
            ("devices", "Device discovery complete"),
            ("settings", "Camera settings applied"),
            ("storage", "Storage path ready"),
        ):
            host = QWidget()
            hl = QHBoxLayout(host)
            hl.setContentsMargins(0, 2, 0, 2)
            hl.setSpacing(7)
            dot = QLabel("•", objectName="CheckPending")
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setFixedSize(18, 18)
            label = QLabel(text, objectName="CheckText")
            hl.addWidget(dot)
            hl.addWidget(label, 1)
            layout.addWidget(host)
            self.checks[key] = (dot, label)

        layout.addStretch(1)

    def set_summary(self, key: str, value: str):
        label = self.summary_labels.get(key)
        if label:
            label.setText(value)

    def set_check(self, key: str, ready: bool):
        pair = self.checks.get(key)
        if not pair:
            return
        dot, _ = pair
        dot.setObjectName("CheckReady" if ready else "CheckPending")
        dot.setText("✓" if ready else "•")
        dot.style().unpolish(dot)
        dot.style().polish(dot)

    def set_readiness(self, percent: int):
        percent = max(0, min(100, int(percent)))
        self.percent.setText(f"{percent}%")
        if percent >= 100:
            self.status_title.setText("Ready for capture")
            self.status_subtitle.setText("Preflight checks are complete.")
        elif percent >= 60:
            self.status_title.setText("Configure hardware")
            self.status_subtitle.setText("Complete the remaining checks.")
        else:
            self.status_title.setText("Hardware setup")
            self.status_subtitle.setText("Select the camera brand.")


class FullImageDialog(QtWidgets.QDialog):
    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(Path(image_path).name)
        self.resize(1000, 760)
        layout = QVBoxLayout(self)
        image = QLabel()
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = QPixmap(image_path)
        if not pix.isNull():
            image.setPixmap(
                pix.scaled(
                    960, 700,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        layout.addWidget(image)


class CapturePageQt6(QWidget):
    toast_requested = pyqtSignal(str, str)

    STEP_TITLES = (
        ("Choose Capture Type", "Choose the scan type for this session.", "STEP 1 OF 8 · HARDWARE"),
        ("Select Camera Brand", "Choose the camera brand.", "STEP 2 OF 8 · HARDWARE"),
        ("Detect & Select Cameras", "Detect and select the required cameras.", "STEP 3 OF 8 · HARDWARE"),
        ("Configure Cameras", "Apply the required camera settings.", "STEP 4 OF 8 · CONFIGURE"),
        ("Build Capture Plan", "Set images per camera.", "STEP 5 OF 8 · CONFIGURE"),
        ("Confirm Storage", "Verify the save location.", "STEP 6 OF 8 · CONFIGURE"),
        ("Run Capture", "Start and monitor the capture.", "STEP 7 OF 8 · RUN"),
        ("Review Images", "Review the captured images.", "STEP 8 OF 8 · RUN"),
    )

    def __init__(self, user: dict | None = None, parent=None):
        super().__init__(parent)
        self.user = user or {}

        self.scan_type = "area"
        self.adapter_key: str | None = None
        self.adapter_label = ""
        self.devices: list[CameraDevice] = []
        self.selected_devices: list[CameraDevice] = []
        self.settings_by_uid: dict[str, CameraSettings] = {}
        self.applied_uids: set[str] = set()
        self.current_camera_index = 0
        self.saved_paths: list[str] = []
        self.last_session_dir = ""

        self._discovery_worker = None
        self._settings_worker = None
        self._preview_worker = None
        self._capture_worker = None
        self._preview_busy = False
        self._preview_active = False

        self.project_name = "Capture Session"
        self.project_dir = _default_capture_root(self.project_name)
        self.projects: list[dict] = []
        self.project_map: dict[str, dict] = {}
        self.selected_project_id = ""
        self.project_machine_id = ""

        self.setObjectName("CapturePageQt6")
        self._build()
        self._apply_style()
        self.refresh_context()
        self._render_brands()
        self._update_state()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(13)

        # Compact session context row.
        self.context_grid = QGridLayout()
        self.context_grid.setContentsMargins(0, 0, 0, 0)
        self.context_grid.setHorizontalSpacing(9)
        self.context_grid.setVerticalSpacing(9)

        self.context_values = {}
        context_items = (
            ("project", "CURRENT PROJECT"),
            ("type", "CAPTURE TYPE"),
            ("brand", "CAMERA BRAND"),
            ("devices", "DEVICES"),
            ("status", "SESSION STATUS"),
        )
        for index, (key, title) in enumerate(context_items):
            card = AnimatedCard()
            card.setObjectName("ContextCard")
            card.setMinimumHeight(72)
            vl = QVBoxLayout(card)
            vl.setContentsMargins(12, 9, 12, 9)
            vl.setSpacing(3)
            vl.addWidget(QLabel(title, objectName="ContextKey"))

            if key == "project":
                self.project_selector = ProjectComboBox()
                self.project_selector.currentIndexChanged.connect(
                    self._project_selection_changed
                )
                vl.addWidget(self.project_selector)
            else:
                value = QLabel("—", objectName="ContextValue")
                vl.addWidget(value)
                self.context_values[key] = value

            self.context_grid.addWidget(card, 0, index)

        self.reset_button = QPushButton("⟲  Reset", objectName="ResetButton")
        self.reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_button.setFixedSize(116, 42)
        self.reset_button.clicked.connect(self.reset_session)
        self.context_grid.addWidget(
            self.reset_button, 0, len(context_items),
            alignment=Qt.AlignmentFlag.AlignVCenter,
        )
        for col in range(len(context_items)):
            self.context_grid.setColumnStretch(col, 1)
        # Project selector gets slightly more horizontal room.
        self.context_grid.setColumnStretch(0, 6)
        for col in range(1, len(context_items)):
            self.context_grid.setColumnStretch(col, 5)
        root.addLayout(self.context_grid)

        # Workflow stepper.
        stepper = QFrame(objectName="WorkflowBar")
        step_layout = QHBoxLayout(stepper)
        step_layout.setContentsMargins(10, 8, 10, 8)
        step_layout.setSpacing(3)
        self.step_buttons = []
        for index, title in enumerate(
            (
                "Capture Type", "Camera Brand", "Detect Devices", "Camera Settings",
                "Capture Plan", "Storage", "Capture", "Review",
            )
        ):
            button = StepPill(index + 1, title)
            button.clicked.connect(
                lambda _checked=False, i=index: self._step_clicked(i)
            )
            step_layout.addWidget(button, 1)
            self.step_buttons.append(button)
        root.addWidget(stepper)

        # Main capture cockpit.
        cockpit = QHBoxLayout()
        cockpit.setSpacing(13)

        self.stage = QFrame(objectName="CaptureStage")
        stage_layout = QVBoxLayout(self.stage)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.setSpacing(0)

        head = QFrame(objectName="StageHeader")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(18, 14, 16, 12)
        copy = QVBoxLayout()
        copy.setSpacing(3)
        self.stage_title = QLabel("", objectName="StageTitle")
        self.stage_subtitle = QLabel("", objectName="StageSubtitle")
        copy.addWidget(self.stage_title)
        copy.addWidget(self.stage_subtitle)
        hl.addLayout(copy, 1)

        self.stage_chip = QLabel("", objectName="StageChip")
        self.stage_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(self.stage_chip)
        stage_layout.addWidget(head)

        self.stack = QStackedWidget(objectName="CaptureStack")
        self.stack.addWidget(self._build_type_page())
        self.stack.addWidget(self._build_brand_page())
        self.stack.addWidget(self._build_device_page())
        self.stack.addWidget(self._build_settings_page())
        self.stack.addWidget(self._build_plan_page())
        self.stack.addWidget(self._build_storage_page())
        self.stack.addWidget(self._build_capture_page())
        self.stack.addWidget(self._build_review_page())
        stage_layout.addWidget(self.stack, 1)

        foot = QFrame(objectName="StageFooter")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(16, 10, 16, 10)
        self.footer_hint = QLabel("Select the capture type and continue.", objectName="FooterHint")
        fl.addWidget(self.footer_hint, 1)
        self.back_button = QPushButton("← Back", objectName="SecondaryButton")
        self.next_button = QPushButton("Next →", objectName="PrimaryButton")
        for button in (self.back_button, self.next_button):
            button.setFixedHeight(38)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(self.go_back)
        self.next_button.clicked.connect(self.go_next)
        fl.addWidget(self.back_button)
        fl.addWidget(self.next_button)
        stage_layout.addWidget(foot)

        cockpit.addWidget(self.stage, 1)

        self.rail = ReadinessRail()
        cockpit.addWidget(self.rail)
        root.addLayout(cockpit, 1)

        # Preview timer uses one background frame at a time.
        self.preview_timer = QtCore.QTimer(self)
        self.preview_timer.setInterval(500)
        self.preview_timer.timeout.connect(self._request_preview_frame)

    def _scroll_page(self, content: QWidget) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("CaptureScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _build_type_page(self):
        host = QWidget()
        layout = QGridLayout(host)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(16)

        self.type_cards = {}
        definitions = (
            (
                "area", "Area Scan Camera",
                "2D frame capture for indexed or stop-and-capture inspection.",
                "capture", ["2D Frames", "Mono / Color", "Trigger"],
            ),
            (
                "line", "Line Scan Camera",
                "Continuous image construction for moving or rotary surfaces.",
                "live", ["Continuous Scan", "Line Trigger", "Long Image"],
            ),
        )
        for col, (key, title, subtitle, icon_name, tags) in enumerate(definitions):
            card = ChoiceCard(key, title, subtitle, icon_name, tags)
            # Final UI: keep the two capture-type cards close to square instead
            # of stretching them across the full stage width.
            card.setFixedSize(340, 340)
            card.clicked.connect(self._select_scan_type)
            layout.addWidget(
                card,
                0,
                col,
                alignment=Qt.AlignmentFlag.AlignCenter,
            )
            layout.setColumnStretch(col, 1)
            self.type_cards[key] = card
        self.type_cards["area"].set_selected(True)
        return self._scroll_page(host)

    def _build_brand_page(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.addWidget(QLabel("Camera Brand", objectName="SectionTitle"))
        top.addStretch(1)
        self.adapter_status = QLabel("", objectName="CompactInfo")
        top.addWidget(self.adapter_status)
        layout.addLayout(top)

        self.brand_host = QWidget()
        self.brand_grid = QGridLayout(self.brand_host)
        self.brand_grid.setContentsMargins(0, 2, 0, 0)
        self.brand_grid.setHorizontalSpacing(10)
        self.brand_grid.setVerticalSpacing(10)
        layout.addWidget(self.brand_host)
        layout.addStretch(1)
        return self._scroll_page(host)

    def _build_device_page(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(11)

        top = QHBoxLayout()
        self.device_count_label = QLabel("No discovery run", objectName="CompactInfo")
        top.addWidget(self.device_count_label)
        top.addStretch(1)
        self.select_all_button = QPushButton("Select all", objectName="SecondaryButton")
        self.detect_button = QPushButton("Detect Cameras", objectName="PrimaryButton")
        for button in (self.select_all_button, self.detect_button):
            button.setFixedHeight(37)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.select_all_button.clicked.connect(self._select_all_devices)
        self.detect_button.clicked.connect(self.detect_devices)
        top.addWidget(self.select_all_button)
        top.addWidget(self.detect_button)
        layout.addLayout(top)

        self.device_message = QLabel("Choose a camera brand first.", objectName="EmptyMessage")
        self.device_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.device_message.setMinimumHeight(170)
        layout.addWidget(self.device_message)

        self.device_host = QWidget()
        self.device_grid = QGridLayout(self.device_host)
        self.device_grid.setContentsMargins(0, 0, 0, 0)
        self.device_grid.setHorizontalSpacing(10)
        self.device_grid.setVerticalSpacing(10)
        self.device_host.hide()
        layout.addWidget(self.device_host)
        layout.addStretch(1)
        return self._scroll_page(host)

    def _build_settings_page(self):
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(17, 16, 17, 17)
        layout.setSpacing(14)

        preview = QFrame(objectName="PreviewPanel")
        pl = QVBoxLayout(preview)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)

        preview_head = QFrame(objectName="PreviewHeader")
        phl = QHBoxLayout(preview_head)
        phl.setContentsMargins(11, 0, 11, 0)
        self.preview_camera_label = QLabel("No camera selected", objectName="PreviewHeaderText")
        phl.addWidget(self.preview_camera_label)
        phl.addStretch(1)
        phl.addWidget(QLabel("LIVE PREVIEW", objectName="PreviewHeaderText"))
        pl.addWidget(preview_head)

        self.preview_label = QLabel("Preview paused", objectName="PreviewCanvas")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(500, 330)
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        pl.addWidget(self.preview_label, 1)

        self.preview_info = QLabel("PAUSED", objectName="PreviewStatus")
        pl.addWidget(self.preview_info)
        layout.addWidget(preview, 1)

        controls = QFrame(objectName="SettingsCard")
        controls.setMinimumWidth(315)
        controls.setMaximumWidth(390)
        cl = QVBoxLayout(controls)
        cl.setContentsMargins(14, 13, 14, 13)
        cl.setSpacing(8)

        camera_nav = QHBoxLayout()
        self.settings_camera_label = QLabel("No camera", objectName="SettingsCameraTitle")
        camera_nav.addWidget(self.settings_camera_label, 1)
        self.prev_camera_button = QPushButton("◀", objectName="MiniButton")
        self.next_camera_button = QPushButton("▶", objectName="MiniButton")
        self.prev_camera_button.clicked.connect(lambda: self._move_camera(-1))
        self.next_camera_button.clicked.connect(lambda: self._move_camera(1))
        camera_nav.addWidget(self.prev_camera_button)
        camera_nav.addWidget(self.next_camera_button)
        cl.addLayout(camera_nav)

        self.exposure = QDoubleSpinBox(objectName="SettingSpin")
        self.exposure.setRange(1.0, 10_000_000.0)
        self.exposure.setDecimals(1)
        self.exposure.setSuffix(" µs")

        self.gain = QDoubleSpinBox(objectName="SettingSpin")
        self.gain.setRange(-100.0, 100.0)
        self.gain.setDecimals(2)
        self.gain.setSuffix(" dB")

        self.width_input = QSpinBox(objectName="SettingSpin")
        self.width_input.setRange(0, 100000)
        self.height_input = QSpinBox(objectName="SettingSpin")
        self.height_input.setRange(0, 100000)

        self.pixel_format = QComboBox(objectName="SettingCombo")
        self.pixel_format.addItems(["Mono8", "Mono16", "BayerRG8", "RGB8"])

        self.trigger_mode = QComboBox(objectName="SettingCombo")
        self.trigger_mode.addItems(["Profile / unchanged", "Off", "On"])

        for label, widget in (
            ("Exposure Time", self.exposure),
            ("Gain", self.gain),
            ("Width", self.width_input),
            ("Height / Scan Lines", self.height_input),
            ("Pixel Format", self.pixel_format),
            ("Trigger", self.trigger_mode),
        ):
            cl.addWidget(QLabel(label, objectName="FieldLabel"))
            cl.addWidget(widget)

        self.settings_status = QLabel("Select a detected camera.", objectName="SettingsStatus")
        self.settings_status.setWordWrap(True)
        cl.addWidget(self.settings_status)

        self.preview_button = QPushButton("Start Preview", objectName="PrimaryButton")
        self.reset_settings_button = QPushButton("Reset", objectName="SecondaryButton")
        self.apply_settings_button = QPushButton("Apply Settings", objectName="PrimaryButton")
        for button in (
            self.preview_button,
            self.reset_settings_button,
            self.apply_settings_button,
        ):
            button.setFixedHeight(37)
            button.setCursor(Qt.CursorShape.PointingHandCursor)

        self.preview_button.clicked.connect(self.toggle_preview)
        self.reset_settings_button.clicked.connect(self._reset_current_settings)
        self.apply_settings_button.clicked.connect(self.apply_current_settings)

        cl.addWidget(self.preview_button)
        action_row = QHBoxLayout()
        action_row.addWidget(self.reset_settings_button)
        action_row.addWidget(self.apply_settings_button)
        cl.addLayout(action_row)
        cl.addStretch(1)

        layout.addWidget(controls)
        return self._scroll_page(host)

    def _build_plan_page(self):
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(30, 35, 30, 35)
        layout.setSpacing(15)

        left = QFrame(objectName="InnerCard")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(18, 17, 18, 17)
        ll.setSpacing(8)
        ll.addWidget(QLabel("Images per camera", objectName="SectionTitle"))
        self.count_spin = QSpinBox(objectName="CountSpin")
        self.count_spin.setRange(1, 10000)
        self.count_spin.setValue(10)
        self.count_spin.valueChanged.connect(self._update_state)
        ll.addWidget(self.count_spin)
        ll.addStretch(1)
        layout.addWidget(left, 1)

        right = QFrame(objectName="PlanSummary")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 15, 16, 15)
        rl.addWidget(QLabel("SESSION CAPTURE PLAN", objectName="PlanKicker"))
        self.plan_main = QLabel("", objectName="PlanMain")
        self.plan_total = QLabel("", objectName="PlanSub")
        rl.addWidget(self.plan_main)
        rl.addWidget(self.plan_total)
        self.plan_type = QLabel("", objectName="PlanLine")
        self.plan_brand = QLabel("", objectName="PlanLine")
        self.plan_devices = QLabel("", objectName="PlanLine")
        for widget in (self.plan_type, self.plan_brand, self.plan_devices):
            rl.addWidget(widget)
        rl.addStretch(1)
        layout.addWidget(right)
        return self._scroll_page(host)

    def _build_storage_page(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(30, 35, 30, 35)
        layout.setSpacing(12)

        card = QFrame(objectName="InnerCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 17, 18, 17)
        cl.setSpacing(8)
        cl.addWidget(QLabel("Output Directory", objectName="FieldLabel"))

        row = QHBoxLayout()
        self.path_input = QLineEdit(objectName="PathInput")
        self.path_input.textChanged.connect(self._storage_changed)
        browse = QPushButton("Browse…", objectName="SecondaryButton")
        browse.setFixedHeight(38)
        browse.clicked.connect(self.browse_folder)
        row.addWidget(self.path_input, 1)
        row.addWidget(browse)
        cl.addLayout(row)

        self.storage_status = QLabel("● Ready to save", objectName="StorageReady")
        cl.addWidget(self.storage_status)
        layout.addWidget(card)

        naming = QFrame(objectName="NamingCard")
        nl = QVBoxLayout(naming)
        nl.setContentsMargins(15, 14, 15, 14)
        nl.addWidget(QLabel("Session naming preview", objectName="SectionTitle"))
        self.naming_preview = QLabel("", objectName="NamingPreview")
        self.naming_preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        nl.addWidget(self.naming_preview)
        layout.addWidget(naming)
        layout.addStretch(1)
        return self._scroll_page(host)

    def _build_capture_page(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(17, 16, 17, 17)
        layout.setSpacing(10)

        self.run_summary = QLabel("", objectName="RunSummary")
        layout.addWidget(self.run_summary)

        progress_card = QFrame(objectName="InnerCard")
        pcl = QHBoxLayout(progress_card)
        pcl.setContentsMargins(14, 12, 14, 12)
        pcl.setSpacing(10)
        progress_copy = QVBoxLayout()
        progress_copy.setSpacing(4)
        self.capture_summary = QLabel("Ready to start capture", objectName="CaptureSummary")
        self.capture_subtitle = QLabel("Start the acquisition when the station is ready.", objectName="CompactInfo")
        self.progress = QtWidgets.QProgressBar(objectName="CaptureProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        progress_copy.addWidget(self.capture_summary)
        progress_copy.addWidget(self.capture_subtitle)
        progress_copy.addWidget(self.progress)
        pcl.addLayout(progress_copy, 1)

        self.start_capture_button = QPushButton("Start Capture", objectName="PrimaryButton")
        self.start_capture_button.setFixedHeight(38)
        self.start_capture_button.clicked.connect(self.start_capture)
        pcl.addWidget(self.start_capture_button)
        layout.addWidget(progress_card)

        layout.addWidget(QLabel("CAPTURE LOG", objectName="PlanKicker"))
        self.capture_log = QtWidgets.QPlainTextEdit(objectName="CaptureLog")
        self.capture_log.setReadOnly(True)
        self.capture_log.setMinimumHeight(245)
        layout.addWidget(self.capture_log, 1)
        return host

    def _build_review_page(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(17, 16, 17, 17)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.review_summary = QLabel("No captured images", objectName="CompactInfo")
        top.addWidget(self.review_summary)
        top.addStretch(1)

        open_folder = QPushButton("Open Folder", objectName="SecondaryButton")
        open_folder.clicked.connect(self.open_output_folder)
        new_session = QPushButton("New Session", objectName="PrimaryButton")
        new_session.clicked.connect(self.reset_session)
        top.addWidget(open_folder)
        top.addWidget(new_session)
        layout.addLayout(top)

        self.gallery_scroll = QScrollArea()
        self.gallery_scroll.setWidgetResizable(True)
        self.gallery_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.gallery_host = QWidget()
        self.gallery_grid = QGridLayout(self.gallery_host)
        self.gallery_grid.setContentsMargins(0, 0, 0, 0)
        self.gallery_grid.setSpacing(10)
        self.gallery_scroll.setWidget(self.gallery_host)
        layout.addWidget(self.gallery_scroll, 1)
        return host

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------
    def _apply_style(self):
        self.setStyleSheet("""
        QWidget#CapturePageQt6 { background:transparent; color:#101A2D; }
        QWidget#CapturePageQt6 QLabel { background:transparent; border:0; }

        QFrame#ContextCard {
            background:#FFFFFF; border:1px solid #C9D5E5; border-radius:14px;
        }
        QLabel#ContextKey {
            color:#63748B; font-size:8px; font-weight:800; letter-spacing:0.7px;
        }
        QLabel#ContextValue {
            color:#213047; font-size:11.5px; font-weight:800;
        }
        QComboBox#ProjectSelector {
            min-height:34px;
            background:#FFFFFF;
            color:#14233A;
            border:1px solid #AEBFD5;
            border-radius:9px;
            padding:0 28px 0 10px;
            font-size:10.5px;
            font-weight:800;
        }
        QComboBox#ProjectSelector:hover,
        QComboBox#ProjectSelector:focus,
        QComboBox#ProjectSelector:on {
            background:#FFFFFF;
            border:1px solid #2868E8;
        }
        QComboBox#ProjectSelector:disabled {
            background:#F2F5F9;
            color:#8593A7;
            border-color:#D4DDE9;
        }
        QComboBox#ProjectSelector::drop-down {
            subcontrol-origin:padding;
            subcontrol-position:top right;
            width:26px;
            border:0;
            border-left:1px solid #D9E2EE;
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
        QPushButton#ResetButton {
            background:#FFFFFF; color:#52667F; border:1px solid #D7E1EE;
            border-radius:12px; font-size:9.5px; font-weight:750;
        }
        QPushButton#ResetButton:hover {
            background:#EEF4FF; color:#2868E8; border-color:#BDD0EE;
        }

        QFrame#WorkflowBar {
            background:#FFFFFF; border:1px solid #C9D5E5; border-radius:16px;
        }

        QFrame#CaptureStage, QFrame#ReadinessRail {
            background:#FFFFFF; border:1px solid #C9D5E5; border-radius:18px;
        }
        QFrame#StageHeader {
            background:#FFFFFF; border:0; border-bottom:1px solid #DDE5EF;
        }
        QFrame#StageFooter {
            background:#F8FAFD; border:0; border-top:1px solid #DDE5EF;
        }
        QLabel#StageTitle { color:#101A2D; font-size:18px; font-weight:800; }
        QLabel#StageSubtitle { color:#5F7087; font-size:10px; font-weight:550; }
        QLabel#StageChip {
            background:#F2F6FC; color:#56667D; border:1px solid #DFE7F2;
            border-radius:13px; padding:5px 9px; font-size:8.5px; font-weight:800;
        }
        QLabel#FooterHint { color:#718197; font-size:9px; }

        QScrollArea#CaptureScroll,
        QScrollArea#CaptureScroll > QWidget > QWidget {
            background:#FFFFFF; border:0;
        }

        QFrame#ChoiceCard {
            background:#FFFFFF;
            border:1px solid #AFC0D6;
            border-radius:20px;
        }
        QFrame#ChoiceCard[selected="true"] {
            background:#E7F0FF;
            border:2px solid #2167EA;
        }
        QFrame#BrandCard, QFrame#DeviceCard {
            background:#FFFFFF;
            border:1px solid #C3D0E1;
            border-radius:16px;
        }
        QFrame#BrandCard[selected="true"], QFrame#DeviceCard[selected="true"] {
            background:#EDF4FF;
            border:2px solid #2868E8;
        }
        QLabel#ChoiceTitle {
            color:#0F1D32;
            font-size:16px;
            font-weight:800;
        }
        QLabel#ChoiceSubtitle {
            color:#52677F;
            font-size:9.7px;
            font-weight:600;
        }
        QLabel#ChoiceTag {
            background:#EAF0F8;
            color:#405772;
            border:1px solid #D6E0ED;
            border-radius:8px;
            padding:4px 7px;
            font-size:8px;
            font-weight:750;
        }

        QLabel#BrandName { color:#101A2D; font-size:12px; font-weight:800; }
        QLabel#BrandSdk { color:#66778E; font-size:8.8px; }
        QLabel#AdapterReady {
            background:#E8F8F1; color:#078A57; border-radius:8px;
            padding:4px 7px; font-size:7.5px; font-weight:800;
        }
        QLabel#AdapterMissing {
            background:#FFF6E2; color:#A76205; border-radius:8px;
            padding:4px 7px; font-size:7.5px; font-weight:800;
        }

        QLabel#DeviceName { color:#101A2D; font-size:11px; font-weight:800; }
        QLabel#DeviceMeta { color:#65758D; font-size:8.8px; }
        QLabel#DeviceCheck {
            background:#FFFFFF; color:#FFFFFF; border:1px solid #AEBED3;
            border-radius:7px; font-size:10px; font-weight:800;
        }
        QFrame#DeviceCard[selected="true"] QLabel#DeviceCheck {
            background:#2868E8; color:#FFFFFF; border-color:#2868E8;
        }
        QLabel#EmptyMessage {
            background:#F7F9FC; color:#5F7087; border:1px dashed #C9D7E8;
            border-radius:14px; font-size:10px; font-weight:600;
        }

        QLabel#SectionTitle { color:#101A2D; font-size:12px; font-weight:800; }
        QLabel#CompactInfo { color:#5F7087; font-size:9px; font-weight:600; }

        QPushButton#PrimaryButton, QPushButton#SecondaryButton {
            border-radius:10px; padding:0 14px; font-size:10px; font-weight:750;
        }
        QPushButton#PrimaryButton {
            background:#2868E8; color:#FFFFFF; border:1px solid #2868E8;
        }
        QPushButton#PrimaryButton:hover { background:#1F57C8; border-color:#1F57C8; }
        QPushButton#PrimaryButton:disabled {
            background:#AFC6EF; color:#FFFFFF; border-color:#AFC6EF;
        }
        QPushButton#SecondaryButton {
            background:#FFFFFF; color:#2868E8; border:1px solid #C7D6EA;
        }
        QPushButton#SecondaryButton:hover { background:#F1F6FF; }

        QFrame#PreviewPanel {
            background:#0B0F17; border:1px solid #CDD9E7; border-radius:15px;
        }
        QFrame#PreviewHeader {
            background:#121824; border:0; border-bottom:1px solid #232D3C;
        }
        QFrame#PreviewHeader { min-height:42px; }
        QLabel#PreviewHeaderText { color:#DCE7F7; font-size:8.8px; }
        QLabel#PreviewCanvas {
            background:#090D14; color:#8492A7; border:0; font-size:11px;
        }
        QLabel#PreviewStatus {
            background:#101723; color:#9EC0FF; border:0;
            padding:8px 11px; font-family:Consolas; font-size:8.8px;
        }

        QFrame#SettingsCard, QFrame#InnerCard {
            background:#F7F9FC; border:1px solid #CDD9E7; border-radius:15px;
        }
        QLabel#SettingsCameraTitle {
            color:#101A2D; font-size:10.5px; font-weight:800;
        }
        QPushButton#MiniButton {
            background:#FFFFFF; color:#46607E; border:1px solid #CAD7E8;
            border-radius:8px; min-width:32px; min-height:29px;
        }
        QPushButton#MiniButton:hover { background:#EEF4FF; color:#2868E8; }
        QLabel#FieldLabel { color:#40516A; font-size:9px; font-weight:700; }

        QDoubleSpinBox#SettingSpin, QSpinBox#SettingSpin, QComboBox#SettingCombo,
        QSpinBox#CountSpin, QLineEdit#PathInput {
            min-height:35px; background:#FFFFFF; color:#213047;
            border:1px solid #CBD8E8; border-radius:8px; padding:0 9px;
            font-size:9.5px;
        }
        QDoubleSpinBox#SettingSpin:focus, QSpinBox#SettingSpin:focus,
        QComboBox#SettingCombo:focus, QSpinBox#CountSpin:focus,
        QLineEdit#PathInput:focus { border:1px solid #2868E8; }

        QComboBox#SettingCombo QAbstractItemView {
            background:#FFFFFF;
            color:#213047;
            border:1px solid #BFCDE0;
            selection-background-color:#EAF1FF;
            selection-color:#1D59CF;
            outline:0;
            padding:3px;
        }
        QComboBox#SettingCombo QAbstractItemView::item {
            min-height:28px;
            padding:4px 8px;
            background:#FFFFFF;
            color:#213047;
        }
        QComboBox#SettingCombo QAbstractItemView::item:selected {
            background:#EAF1FF;
            color:#1D59CF;
        }

        QLabel#SettingsStatus {
            background:#FFF7E8; color:#A76205; border:1px solid #F0DEB6;
            border-radius:8px; padding:7px 9px; font-size:8.5px;
        }

        QFrame#PlanSummary {
            background:#EEF4FF; border:1px solid #CADCFB; border-radius:15px;
            min-width:280px;
        }
        QLabel#PlanKicker {
            color:#2868E8; font-size:8px; font-weight:800; letter-spacing:0.7px;
        }
        QLabel#PlanMain { color:#101A2D; font-size:17px; font-weight:800; }
        QLabel#PlanSub { color:#5F7087; font-size:9px; }
        QLabel#PlanLine { color:#40516A; font-size:9px; padding-top:4px; }

        QFrame#NamingCard {
            background:#FFFFFF; border:1px solid #D2DCE9; border-radius:15px;
        }
        QLabel#StorageReady {
            background:#EAF9F2; color:#078A57; border:1px solid #CDEBDD;
            border-radius:10px; padding:9px 10px; font-size:9px; font-weight:700;
        }
        QLabel#NamingPreview {
            background:#111827; color:#CFE1FF; border-radius:9px;
            padding:10px; font-family:Consolas; font-size:8.7px;
        }

        QLabel#RunSummary {
            background:#F5F8FD; color:#40516A; border:1px solid #D2DCE9;
            border-radius:10px; padding:9px 11px; font-size:9px; font-weight:650;
        }
        QLabel#CaptureSummary { color:#101A2D; font-size:11.5px; font-weight:800; }
        QProgressBar#CaptureProgress {
            min-height:9px; max-height:9px; background:#E2E8F0;
            border:0; border-radius:4px;
        }
        QProgressBar#CaptureProgress::chunk {
            background:#2868E8; border-radius:4px;
        }
        QPlainTextEdit#CaptureLog {
            background:#0E1522; color:#D9E8FF; border:1px solid #253248;
            border-radius:12px; padding:8px; font-family:Consolas; font-size:9px;
        }

        QFrame#ReadinessRail { background:#FFFFFF; }
        QLabel#RailTitle { color:#101A2D; font-size:12px; font-weight:800; }
        QLabel#RailSubtitle { color:#5F7087; font-size:8.8px; font-weight:600; }
        QFrame#ReadinessBox {
            background:#F0FAF6; border:1px solid #D3EEDF; border-radius:12px;
        }
        QLabel#ReadinessPercent {
            background:#FFFFFF; color:#07965D; border:5px solid #BDE7D2;
            border-radius:21px; font-size:9px; font-weight:800;
        }
        QLabel#ReadinessTitle { color:#087D53; font-size:10px; font-weight:800; }
        QLabel#ReadinessSubtitle { color:#5F7087; font-size:8.5px; font-weight:600; }
        QFrame#RailRow { border:0; border-bottom:1px solid #EEF2F6; }
        QLabel#RailKey { color:#5F7087; font-size:8.7px; font-weight:650; }
        QLabel#RailValue { color:#1E2E45; font-size:9px; font-weight:750; }
        QLabel#PreflightTitle {
            color:#607189; font-size:8.2px; font-weight:800; letter-spacing:0.7px;
        }
        QLabel#CheckText { color:#495C74; font-size:9px; font-weight:600; }
        QLabel#CheckReady {
            background:#EAF9F2; color:#07965D; border-radius:6px;
            font-size:9px; font-weight:800;
        }
        QLabel#CheckPending {
            background:#F2F5F9; color:#9BA8B8; border-radius:6px;
            font-size:9px; font-weight:800;
        }

        QScrollBar:vertical { background:transparent; width:7px; margin:2px; }
        QScrollBar::handle:vertical {
            background:#D3DDEA; border-radius:3px; min-height:28px;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
        """)

    # ------------------------------------------------------------------
    # Context / state
    # ------------------------------------------------------------------
    @staticmethod
    def _project_id(project: dict) -> str:
        return str(project.get("_id") or project.get("id") or "")

    def refresh_context(self):
        """Reload projects and preserve the operator's current project selection."""
        previous_id = self.selected_project_id
        if hasattr(self, "project_selector") and self.project_selector.currentData():
            previous_id = str(self.project_selector.currentData())

        try:
            self.projects = list(ProjectDB().get_all_projects() or [])
        except Exception as exc:
            self.projects = []
            self.toast_requested.emit(
                "Projects unavailable",
                f"Project records could not be loaded: {exc}",
            )

        self.project_map = {
            self._project_id(project): project
            for project in self.projects
            if self._project_id(project)
        }

        if hasattr(self, "project_selector"):
            self.project_selector.blockSignals(True)
            self.project_selector.clear()

            for project in self.projects:
                project_id = self._project_id(project)
                self.project_selector.addItem(
                    str(project.get("name") or "Unnamed Project"),
                    project_id,
                )

            if self.projects:
                self.project_selector.setEnabled(True)
                target_index = self.project_selector.findData(previous_id)
                if target_index < 0:
                    target_index = 0
                self.project_selector.setCurrentIndex(target_index)
            else:
                self.project_selector.addItem("No projects available", "")
                self.project_selector.setCurrentIndex(0)
                self.project_selector.setEnabled(False)

            self.project_selector.blockSignals(False)

        if self.projects:
            current_id = (
                str(self.project_selector.currentData())
                if hasattr(self, "project_selector")
                else self._project_id(self.projects[0])
            )
            project = self.project_map.get(current_id, self.projects[0])
            self._apply_project(project, update_storage=True)
        else:
            self.selected_project_id = ""
            self.project_machine_id = ""
            self.project_name = "Capture Session"
            self.project_dir = _default_capture_root(self.project_name)
            if hasattr(self, "path_input"):
                self.path_input.setText(str(self.project_dir))
            self._update_state()

    def _project_selection_changed(self, _index: int):
        if not hasattr(self, "project_selector"):
            return
        project_id = str(self.project_selector.currentData() or "")
        project = self.project_map.get(project_id)
        if project is None:
            return

        # Do not allow switching the data destination in the middle of a run.
        if self._capture_worker and self._capture_worker.isRunning():
            self.project_selector.blockSignals(True)
            previous_index = self.project_selector.findData(self.selected_project_id)
            if previous_index >= 0:
                self.project_selector.setCurrentIndex(previous_index)
            self.project_selector.blockSignals(False)
            self.toast_requested.emit(
                "Capture in progress",
                "Project selection is locked until the capture finishes.",
            )
            return

        self._apply_project(project, update_storage=True)
        self.toast_requested.emit(
            "Project selected",
            f"Capture output is now linked to {self.project_name}.",
        )

    def _apply_project(self, project: dict, *, update_storage: bool):
        self.selected_project_id = self._project_id(project)
        self.project_machine_id = str(project.get("machine_id") or "")
        self.project_name = str(project.get("name") or "Capture Session")

        folder = project.get("folder_path")
        self.project_dir = (
            Path(folder)
            if folder
            else _default_capture_root(self.project_name)
        )

        if update_storage and hasattr(self, "path_input"):
            self.path_input.setText(str(self.project_dir))

        self._update_state()

    def set_project_context(self, name: str, folder: str | None = None):
        """Compatibility hook for external navigation into a known project."""
        name = str(name or "Capture Session")

        if hasattr(self, "project_selector"):
            for index in range(self.project_selector.count()):
                if self.project_selector.itemText(index) == name:
                    self.project_selector.setCurrentIndex(index)
                    return

        self.project_name = name
        self.project_dir = (
            Path(folder)
            if folder
            else _default_capture_root(self.project_name)
        )
        if hasattr(self, "path_input"):
            self.path_input.setText(str(self.project_dir))
        self._update_state()

    def _selected_count(self) -> int:
        return len(self.selected_devices)

    def _settings_ready(self) -> bool:
        if not self.selected_devices:
            return False
        return all(device.uid in self.applied_uids for device in self.selected_devices)

    def _storage_ready(self) -> bool:
        path = self.path_input.text().strip() if hasattr(self, "path_input") else str(self.project_dir)
        if not path:
            return False
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            return True
        except Exception:
            return False

    def _update_state(self):
        capture_label = "Area Scan" if self.scan_type == "area" else "Line Scan"
        selected = self._selected_count()
        count = self.count_spin.value() if hasattr(self, "count_spin") else 10
        total = count * max(1, selected)

        self.context_values["type"].setText(capture_label)
        self.context_values["brand"].setText(self.adapter_label or "Not selected")
        self.context_values["devices"].setText(
            f"{selected} selected" if selected else "Not detected"
        )
        status = "Capturing" if self._capture_worker and self._capture_worker.isRunning() else (
            "Ready" if self._readiness_percent() == 100 else "Setup"
        )
        self.context_values["status"].setText(status)

        if hasattr(self, "project_selector"):
            self.project_selector.setEnabled(
                bool(self.projects)
                and not (
                    self._capture_worker
                    and self._capture_worker.isRunning()
                )
            )

        self.rail.set_summary("project", self.project_name)
        self.rail.set_summary("type", capture_label)
        self.rail.set_summary("brand", self.adapter_label or "—")
        self.rail.set_summary(
            "devices",
            f"{selected} camera{'s' if selected != 1 else ''}" if selected else "—",
        )
        self.rail.set_summary("count", str(count))
        storage_text = self.path_input.text().strip() if hasattr(self, "path_input") else str(self.project_dir)
        self.rail.set_summary("storage", storage_text or "—")

        self.rail.set_check("type", True)
        self.rail.set_check("brand", bool(self.adapter_key))
        self.rail.set_check("devices", selected > 0)
        self.rail.set_check("settings", self._settings_ready())
        self.rail.set_check("storage", self._storage_ready())
        self.rail.set_readiness(self._readiness_percent())

        if hasattr(self, "plan_main"):
            self.plan_main.setText(
                f"{count} × {selected or 0} camera{'s' if selected != 1 else ''}"
            )
            self.plan_total.setText(f"{count * selected} total images")
            self.plan_type.setText(f"Capture type:  {capture_label}")
            self.plan_brand.setText(f"Camera brand:  {self.adapter_label or '—'}")
            self.plan_devices.setText(f"Selected devices:  {selected}")

        if hasattr(self, "run_summary"):
            self.run_summary.setText(
                f"{capture_label}  ·  {self.adapter_label or 'No brand'}  ·  "
                f"{selected} camera(s)  ·  {count * selected} image(s)"
            )

        if hasattr(self, "naming_preview"):
            ids = [d.serial or d.backend_id for d in self.selected_devices[:2]]
            lines = ["capture_session\\"]
            for ident in ids or ["camera"]:
                lines.extend([f"  {ident}\\", f"    {ident}_0001.png"])
            self.naming_preview.setText("\n".join(lines))

        if hasattr(self, "next_button"):
            self._update_navigation()

    def _readiness_percent(self) -> int:
        checks = (
            True,
            bool(self.adapter_key),
            bool(self.selected_devices),
            self._settings_ready(),
            self._storage_ready(),
        )
        return round(sum(bool(v) for v in checks) / len(checks) * 100)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def current_step(self) -> int:
        return self.stack.currentIndex()

    def _step_clicked(self, index: int):
        if self._capture_worker and self._capture_worker.isRunning():
            return
        current = self.current_step()
        if index > current and not self._validate_step(current):
            return
        if index == 7 and not self.saved_paths:
            self.toast_requested.emit("Review unavailable", "Complete a capture first.")
            return
        self._set_step(index)

    def _set_step(self, index: int):
        index = max(0, min(7, int(index)))
        if index != 3:
            self.stop_preview()
        self.stack.setCurrentIndex(index)
        title, subtitle, chip = self.STEP_TITLES[index]
        self.stage_title.setText(title)
        self.stage_subtitle.setText(subtitle)
        self.stage_chip.setText(chip)

        hints = (
            "Select the capture type and continue.",
            "Choose the camera brand.",
            "Detect and select at least one device.",
            "Apply the required settings.",
            "Set images per camera.",
            "Confirm the save location.",
            "Start capture when ready.",
            "Review the saved images.",
        )
        self.footer_hint.setText(hints[index])

        for i, button in enumerate(self.step_buttons):
            button.setChecked(i == index)
            button.set_complete(i < index or (i == 7 and bool(self.saved_paths)))

        if index == 3:
            self._load_current_camera()
        self._update_navigation()

    def _update_navigation(self):
        index = self.current_step()
        capture_running = bool(self._capture_worker and self._capture_worker.isRunning())
        self.back_button.setEnabled(index > 0 and not capture_running)
        self.next_button.setEnabled(not capture_running)

        if index == 6:
            # Capture is explicitly started with the button inside the page.
            self.next_button.setEnabled(bool(self.saved_paths) and not capture_running)
            self.next_button.setText("Review →")
        elif index == 7:
            self.next_button.setText("Finish")
        else:
            self.next_button.setText("Next →")

    def _validate_step(self, index: int) -> bool:
        if index == 1 and not self.adapter_key:
            self.toast_requested.emit("Camera brand required", "Select a camera brand.")
            return False
        if index == 2 and not self.selected_devices:
            self.toast_requested.emit("Camera required", "Detect and select at least one camera.")
            return False
        if index == 4 and self.count_spin.value() < 1:
            return False
        if index == 5 and not self._storage_ready():
            self.toast_requested.emit("Storage unavailable", "Choose a writable output folder.")
            return False
        return True

    def go_back(self):
        if self.current_step() > 0:
            self._set_step(self.current_step() - 1)

    def go_next(self):
        index = self.current_step()
        if not self._validate_step(index):
            return
        if index == 7:
            self.reset_session()
            return
        if index < 7:
            self._set_step(index + 1)

    # ------------------------------------------------------------------
    # Capture type / brand
    # ------------------------------------------------------------------
    def _select_scan_type(self, key: str):
        if key not in ("area", "line"):
            return
        if key == self.scan_type:
            return
        self.scan_type = key
        for card_key, card in self.type_cards.items():
            card.set_selected(card_key == key)

        # Changing acquisition geometry invalidates downstream hardware state.
        self.adapter_key = None
        self.adapter_label = ""
        self.devices = []
        self.selected_devices = []
        self.settings_by_uid.clear()
        self.applied_uids.clear()
        self._render_brands()
        self._clear_device_cards()
        self._update_state()
        self.toast_requested.emit(
            "Capture type selected",
            "Area Scan selected." if key == "area" else "Line Scan selected.",
        )

    def _render_brands(self):
        while self.brand_grid.count():
            item = self.brand_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        infos = adapter_infos(self.scan_type)
        self.brand_cards = {}
        columns = 3
        for index, info in enumerate(infos):
            card = BrandCard(info)
            card.set_selected(info.key == self.adapter_key)
            card.clicked.connect(self._select_brand)
            self.brand_grid.addWidget(card, index // columns, index % columns)
            self.brand_grid.setColumnStretch(index % columns, 1)
            self.brand_cards[info.key] = card

        ready = sum(1 for info in infos if info.available)
        self.adapter_status.setText(f"{ready}/{len(infos)} SDK adapters ready")

    def _select_brand(self, key: str):
        info = next(
            (x for x in adapter_infos(self.scan_type) if x.key == key),
            None,
        )
        if info is None:
            return
        self.adapter_key = key
        self.adapter_label = info.display_name
        for card_key, card in self.brand_cards.items():
            card.set_selected(card_key == key)

        self.devices = []
        self.selected_devices = []
        self.settings_by_uid.clear()
        self.applied_uids.clear()
        self._clear_device_cards()
        self._update_state()

        if info.available:
            self.toast_requested.emit("Camera brand selected", f"{info.display_name} is ready.")
        else:
            self.toast_requested.emit(
                "Camera SDK required",
                info.status_text,
            )

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------
    def _clear_device_cards(self):
        while self.device_grid.count():
            item = self.device_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.device_host.hide()
        self.device_message.show()
        self.device_message.setText(
            "Ready to detect cameras." if self.adapter_key
            else "Choose a camera brand first."
        )
        self.device_count_label.setText("No discovery run")

    def detect_devices(self):
        if not self.adapter_key:
            self.toast_requested.emit("Camera brand required", "Select a camera brand first.")
            return
        if self._discovery_worker and self._discovery_worker.isRunning():
            return

        self.detect_button.setEnabled(False)
        self.detect_button.setText("Detecting…")
        self.device_message.show()
        self.device_message.setText("Detecting cameras…")
        self.device_host.hide()

        self._discovery_worker = DiscoveryWorker(
            self.adapter_key,
            self.scan_type,
            self,
        )
        self._discovery_worker.completed.connect(self._devices_found)
        self._discovery_worker.failed.connect(self._device_discovery_failed)
        self._discovery_worker.finished.connect(self._discovery_finished)
        self._discovery_worker.start()

    def _discovery_finished(self):
        self.detect_button.setEnabled(True)
        self.detect_button.setText("Detect Cameras")

    def _device_discovery_failed(self, message: str):
        self.devices = []
        self.selected_devices = []
        self.device_host.hide()
        self.device_message.show()
        self.device_message.setText(message)
        self.device_count_label.setText("Discovery failed")
        self._update_state()
        self.toast_requested.emit("Camera discovery failed", message)

    def _devices_found(self, devices: list):
        self.devices = list(devices or [])
        self.selected_devices = list(self.devices)
        # Until a device's settings are read/applied, keep its existing camera
        # profile untouched.  This avoids forcing generic 1700 us / 24 dB values
        # onto every vendor or SKU.
        self.settings_by_uid = {
            device.uid: CameraSettings()
            for device in self.devices
        }
        self.applied_uids.clear()

        while self.device_grid.count():
            item = self.device_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not self.devices:
            self.device_host.hide()
            self.device_message.show()
            self.device_message.setText("No cameras detected.")
            self.device_count_label.setText("0 devices found")
            self._update_state()
            return

        self.device_message.hide()
        self.device_host.show()
        self.device_cards = {}
        columns = 2
        for index, device in enumerate(self.devices):
            card = DeviceCard(device, selected=True)
            card.toggled.connect(self._device_toggled)
            self.device_grid.addWidget(card, index // columns, index % columns)
            self.device_grid.setColumnStretch(index % columns, 1)
            self.device_cards[device.uid] = card

        self.device_count_label.setText(
            f"{len(self.devices)} device(s) found · {len(self.selected_devices)} selected"
        )
        self.current_camera_index = 0
        self._update_state()
        self.toast_requested.emit(
            "Camera discovery complete",
            f"{len(self.devices)} device(s) found.",
        )

    def _device_toggled(self, device: CameraDevice, selected: bool):
        if selected:
            if not any(d.uid == device.uid for d in self.selected_devices):
                self.selected_devices.append(device)
        else:
            self.selected_devices = [d for d in self.selected_devices if d.uid != device.uid]
            self.applied_uids.discard(device.uid)
        self.device_count_label.setText(
            f"{len(self.devices)} device(s) found · {len(self.selected_devices)} selected"
        )
        self.current_camera_index = min(
            self.current_camera_index,
            max(0, len(self.selected_devices) - 1),
        )
        self._update_state()

    def _select_all_devices(self):
        if not self.devices:
            return
        self.selected_devices = list(self.devices)
        for card in getattr(self, "device_cards", {}).values():
            card.set_selected(True, emit_signal=False)
        self.device_count_label.setText(
            f"{len(self.devices)} device(s) found · {len(self.selected_devices)} selected"
        )
        self._update_state()

    # ------------------------------------------------------------------
    # Camera settings / preview
    # ------------------------------------------------------------------
    def _current_device(self) -> CameraDevice | None:
        if not self.selected_devices:
            return None
        self.current_camera_index %= len(self.selected_devices)
        return self.selected_devices[self.current_camera_index]

    def _move_camera(self, delta: int):
        if not self.selected_devices:
            return
        self.stop_preview()
        self.current_camera_index = (
            self.current_camera_index + delta
        ) % len(self.selected_devices)
        self._load_current_camera()

    def _load_current_camera(self):
        device = self._current_device()
        if device is None:
            self.settings_camera_label.setText("No camera selected")
            self.preview_camera_label.setText("No camera selected")
            return

        total = len(self.selected_devices)
        self.settings_camera_label.setText(
            f"Camera {self.current_camera_index + 1} of {total} · {device.serial}"
        )
        self.preview_camera_label.setText(
            f"{self.scan_type.upper()} · {self.adapter_label.upper()} · {device.serial}"
        )
        self.settings_status.setText("Reading camera settings…")

        if self._settings_worker and self._settings_worker.isRunning():
            return
        self._settings_worker = SettingsWorker(
            self.adapter_key,
            device,
            action="read",
            parent=self,
        )
        self._settings_worker.completed.connect(
            lambda settings, uid=device.uid: self._settings_loaded(uid, settings)
        )
        self._settings_worker.failed.connect(self._settings_read_failed)
        self._settings_worker.start()

    def _settings_loaded(self, uid: str, settings):
        if not isinstance(settings, CameraSettings):
            settings = CameraSettings.from_dict(
                settings.to_dict() if hasattr(settings, "to_dict") else {}
            )
        self.settings_by_uid[uid] = settings
        device = self._current_device()
        if device and device.uid == uid:
            self._populate_controls(settings)
            self.settings_status.setText("Camera settings loaded.")
        self._update_state()

    def _settings_read_failed(self, message: str):
        device = self._current_device()
        if device:
            settings = self.settings_by_uid.get(device.uid, CameraSettings())
            self._populate_controls(settings)
        self.settings_status.setText(message)
        self.toast_requested.emit("Camera settings", message)

    def _populate_controls(self, settings: CameraSettings):
        self.exposure.setValue(float(settings.exposure_us or 1700.0))
        self.gain.setValue(float(settings.gain_db or 0.0))
        self.width_input.setValue(int(settings.width or 0))
        self.height_input.setValue(int(settings.height or 0))

        pf = str(settings.pixel_format or "Mono8")
        index = self.pixel_format.findText(pf)
        if index < 0:
            self.pixel_format.addItem(pf)
            index = self.pixel_format.findText(pf)
        self.pixel_format.setCurrentIndex(max(0, index))

        trigger = str(settings.trigger_mode or "")
        if trigger in ("Off", "On"):
            self.trigger_mode.setCurrentText(trigger)
        else:
            self.trigger_mode.setCurrentIndex(0)

    def _controls_to_settings(self) -> CameraSettings:
        device = self._current_device()
        existing = (
            self.settings_by_uid.get(device.uid, CameraSettings())
            if device else CameraSettings()
        )
        trigger = self.trigger_mode.currentText()
        return CameraSettings(
            exposure_us=self.exposure.value(),
            gain_db=self.gain.value(),
            width=self.width_input.value() or None,
            height=self.height_input.value() or None,
            pixel_format=self.pixel_format.currentText(),
            trigger_mode=None if trigger.startswith("Profile") else trigger,
            trigger_source=existing.trigger_source,
            acquisition_mode=existing.acquisition_mode,
            extras=dict(existing.extras or {}),
        )

    def _reset_current_settings(self):
        device = self._current_device()
        if not device:
            return
        self.settings_by_uid[device.uid] = CameraSettings(
            exposure_us=1700.0,
            gain_db=24.0,
            pixel_format="Mono8",
        )
        self.applied_uids.discard(device.uid)
        self._populate_controls(self.settings_by_uid[device.uid])
        self.settings_status.setText("Defaults restored. Apply to save.")
        self._update_state()

    def apply_current_settings(self):
        device = self._current_device()
        if device is None or not self.adapter_key:
            return
        settings = self._controls_to_settings()
        self.apply_settings_button.setEnabled(False)
        self.apply_settings_button.setText("Applying…")

        worker = SettingsWorker(
            self.adapter_key,
            device,
            settings=settings,
            action="apply",
            parent=self,
        )
        self._settings_worker = worker
        worker.completed.connect(
            lambda result, d=device: self._settings_applied(d, result)
        )
        worker.failed.connect(self._settings_apply_failed)
        worker.finished.connect(
            lambda: (
                self.apply_settings_button.setEnabled(True),
                self.apply_settings_button.setText("Apply Settings"),
            )
        )
        worker.start()

    def _settings_applied(self, device: CameraDevice, settings):
        self.settings_by_uid[device.uid] = (
            settings if isinstance(settings, CameraSettings)
            else CameraSettings.from_dict({})
        )
        self.applied_uids.add(device.uid)
        self.settings_status.setText("Camera settings applied.")
        self.toast_requested.emit(
            "Camera settings applied",
            f"{device.serial} is configured.",
        )
        self._update_state()

    def _settings_apply_failed(self, message: str):
        self.settings_status.setText(message)
        self.toast_requested.emit("Camera settings failed", message)

    def toggle_preview(self):
        if self._preview_active:
            self.stop_preview()
            return
        if not self._current_device() or not self.adapter_key:
            return
        self._preview_active = True
        self.preview_button.setText("Stop Preview")
        self.preview_info.setText("LIVE")
        self.preview_timer.start()
        self._request_preview_frame()

    def stop_preview(self):
        self._preview_active = False
        self.preview_timer.stop()
        self.preview_button.setText("Start Preview")
        self.preview_info.setText("PAUSED")

    def _request_preview_frame(self):
        if not self._preview_active or self._preview_busy:
            return
        device = self._current_device()
        if not device or not self.adapter_key:
            return

        settings = self._controls_to_settings()
        self._preview_busy = True
        worker = PreviewWorker(
            self.adapter_key,
            device,
            settings,
            parent=self,
        )
        self._preview_worker = worker
        worker.completed.connect(self._preview_frame_ready)
        worker.failed.connect(self._preview_frame_failed)
        worker.finished.connect(lambda: setattr(self, "_preview_busy", False))
        worker.start()

    def _preview_frame_ready(self, frame):
        image = _qimage_from_array(frame)
        if image is None:
            return
        pix = QPixmap.fromImage(image)
        self.preview_label.setPixmap(
            pix.scaled(
                self.preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.preview_info.setText(
            f"LIVE · {image.width()} × {image.height()} · "
            f"{self.pixel_format.currentText()}"
        )

    def _preview_frame_failed(self, message: str):
        self.stop_preview()
        self.preview_label.setText("Preview unavailable")
        self.preview_info.setText("PAUSED")
        self.toast_requested.emit("Preview failed", message)

    # ------------------------------------------------------------------
    # Storage / capture
    # ------------------------------------------------------------------
    def _storage_changed(self):
        self._update_state()

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Capture Output Directory",
            self.path_input.text().strip() or str(self.project_dir),
        )
        if folder:
            self.path_input.setText(folder)

    def start_capture(self):
        if not self.adapter_key or not self.selected_devices:
            self.toast_requested.emit(
                "Capture setup incomplete",
                "Select the camera brand and cameras first.",
            )
            return
        if not self._storage_ready():
            self.toast_requested.emit("Storage unavailable", "Choose a writable output folder.")
            return
        if self._capture_worker and self._capture_worker.isRunning():
            self._capture_worker.stop()
            self.capture_subtitle.setText("Stop requested…")
            return

        self.stop_preview()
        self.saved_paths = []
        self.last_session_dir = ""
        self.progress.setValue(0)
        self.capture_log.clear()
        self.capture_summary.setText("Preparing capture…")
        self.capture_subtitle.setText("Starting camera acquisition.")
        self.start_capture_button.setText("Stop Capture")
        self.start_capture_button.setObjectName("SecondaryButton")
        self.start_capture_button.style().unpolish(self.start_capture_button)
        self.start_capture_button.style().polish(self.start_capture_button)

        # Ensure every selected camera has settings, even if the operator kept
        # its current device profile without pressing Apply.
        settings_map = {}
        for device in self.selected_devices:
            settings_map[device.uid] = self.settings_by_uid.get(
                device.uid,
                CameraSettings(),
            )

        worker = CaptureSessionWorker(
            adapter_key=self.adapter_key,
            scan_type=self.scan_type,
            devices=self.selected_devices,
            settings_by_uid=settings_map,
            images_per_camera=self.count_spin.value(),
            base_dir=self.path_input.text().strip(),
            parent=self,
        )
        self._capture_worker = worker
        worker.progress.connect(self._capture_progress)
        worker.status.connect(self._capture_status)
        worker.failed.connect(self._capture_failed)
        worker.completed.connect(self._capture_complete)
        worker.finished.connect(self._capture_worker_finished)
        worker.start()
        self._update_state()
        self._update_navigation()

    def _capture_progress(self, done: int, total: int, path: str):
        percent = round(done / max(1, total) * 100)
        self.progress.setValue(percent)
        self.capture_summary.setText(
            f"{done} of {total} images saved · {percent}% complete"
        )
        self.capture_subtitle.setText(Path(path).name)
        self.capture_log.appendPlainText(f"[SAVE] {path}")

    def _capture_status(self, message: str):
        self.capture_log.appendPlainText(message)

    def _capture_failed(self, message: str):
        self.capture_summary.setText("Capture failed")
        self.capture_subtitle.setText(message)
        self.capture_log.appendPlainText(f"[ERROR] {message}")
        self.toast_requested.emit("Capture failed", message)

    def _capture_complete(self, paths: list, session_dir: str):
        self.saved_paths = list(paths or [])
        self.last_session_dir = session_dir
        self.progress.setValue(100 if self.saved_paths else 0)
        self.capture_summary.setText(
            f"Capture complete · {len(self.saved_paths)} file(s) saved"
        )
        self.capture_subtitle.setText(session_dir)
        self.toast_requested.emit(
            "Capture complete",
            f"{len(self.saved_paths)} image(s) saved.",
        )
        self._render_gallery()
        self._update_state()

    def _capture_worker_finished(self):
        self.start_capture_button.setText("Start Capture")
        self.start_capture_button.setObjectName("PrimaryButton")
        self.start_capture_button.style().unpolish(self.start_capture_button)
        self.start_capture_button.style().polish(self.start_capture_button)
        self._update_navigation()
        self._update_state()

    # ------------------------------------------------------------------
    # Review
    # ------------------------------------------------------------------
    def _clear_gallery(self):
        while self.gallery_grid.count():
            item = self.gallery_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _render_gallery(self):
        self._clear_gallery()
        self.review_summary.setText(
            f"{len(self.saved_paths)} image(s) captured · showing latest previews"
        )
        for index, path in enumerate(self.saved_paths[:12]):
            card = AnimatedCard()
            card.setObjectName("InnerCard")
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(5)

            image = QLabel()
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image.setMinimumHeight(150)
            pix = QPixmap(path)
            if not pix.isNull():
                image.setPixmap(
                    pix.scaled(
                        360, 185,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            layout.addWidget(image)
            layout.addWidget(QLabel(Path(path).parent.name, objectName="DeviceName"))
            layout.addWidget(QLabel(Path(path).name, objectName="DeviceMeta"))

            card.mouseDoubleClickEvent = (
                lambda event, p=path: FullImageDialog(p, self).exec()
            )
            self.gallery_grid.addWidget(card, index // 2, index % 2)
            self.gallery_grid.setColumnStretch(index % 2, 1)

    def open_output_folder(self):
        folder = self.last_session_dir or self.path_input.text().strip()
        if not folder:
            return
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(Path(folder)))
        )

    # ------------------------------------------------------------------
    # Reset / shutdown / responsive
    # ------------------------------------------------------------------
    def reset_session(self):
        self.stop_preview()
        if self._capture_worker and self._capture_worker.isRunning():
            self._capture_worker.stop()
            self._capture_worker.wait(1500)

        self.scan_type = "area"
        self.adapter_key = None
        self.adapter_label = ""
        self.devices = []
        self.selected_devices = []
        self.settings_by_uid.clear()
        self.applied_uids.clear()
        self.current_camera_index = 0
        self.saved_paths = []
        self.last_session_dir = ""

        for key, card in self.type_cards.items():
            card.set_selected(key == "area")
        self._render_brands()
        self._clear_device_cards()
        self.count_spin.setValue(10)
        self.progress.setValue(0)
        self.capture_log.clear()
        self.capture_summary.setText("Ready to start capture")
        self.capture_subtitle.setText("Start the acquisition when the station is ready.")
        self.preview_label.clear()
        self.preview_label.setText("Preview paused")
        self.path_input.setText(str(self.project_dir))
        self._clear_gallery()
        self.review_summary.setText("No captured images")
        self._set_step(0)
        self._update_state()
        self.toast_requested.emit("Session reset", "Ready for a new capture session.")

    def shutdown(self):
        self.stop_preview()
        try:
            if self._capture_worker and self._capture_worker.isRunning():
                self._capture_worker.stop()
                self._capture_worker.wait(1500)
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.width()

        # Keep the capture-type choices square at normal desktop sizes while
        # reducing them slightly on smaller workstations.
        square_size = 340 if width >= 1180 else 300
        for card in getattr(self, "type_cards", {}).values():
            card.setFixedSize(square_size, square_size)

        # Readiness rail moves below the stage automatically on compact widths
        # by constraining its width rather than creating a second sidebar.
        if width < 1120:
            self.rail.setMaximumWidth(245)
        else:
            self.rail.setMaximumWidth(285)

        # Compact context row: two rows when the page is narrow.
        columns = 6 if width >= 1180 else 3 if width >= 760 else 2
        items = []
        while self.context_grid.count():
            items.append(self.context_grid.takeAt(0).widget())
        for index, widget in enumerate([w for w in items if w is not None]):
            self.context_grid.addWidget(widget, index // columns, index % columns)

    def showEvent(self, event):
        super().showEvent(event)
        if self.stage_title.text() == "":
            self._set_step(0)
