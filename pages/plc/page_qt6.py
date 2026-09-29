"""EYRES AI - PyQt6 PLC Live page."""

from __future__ import annotations

import csv
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtProperty, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .backend import DataStorage, PLCWorker, SPECIFIC_TAGS, TagMapper


def _app_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _asset(name: str) -> str:
    return str(_app_root() / "ui" / "assets" / "plc_icons" / name)


class TiltIconButton(QPushButton):
    """Local SVG button with sidebar-style padded hover animation.

    The icon is rotated/scaled on a larger transparent canvas first. This
    prevents the SVG edges from being clipped by the button while hovering.
    """

    def __init__(self, text: str, icon_name: str, parent=None, checkable=False):
        super().__init__(text, parent)
        self.icon_name = icon_name
        self._motion = 0.0
        self._hovered = False
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._normal_icon = QtGui.QIcon(_asset(f"{icon_name}.svg"))
        self._active_icon = QtGui.QIcon(_asset(f"{icon_name}_active.svg"))

        # Normal Qt layout handles text spacing more reliably than manually
        # painting the text. We only animate a padded icon canvas.
        self.setIconSize(QtCore.QSize(34, 34))
        self._refresh_icon()

        self._anim = QtCore.QPropertyAnimation(self, b"iconMotion", self)
        self._anim.setDuration(185)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)

        self.toggled.connect(lambda _checked: self._refresh_icon())

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
    def _tint_pixmap(pix: QtGui.QPixmap, color: str) -> QtGui.QPixmap:
        if pix.isNull():
            return pix
        out = QtGui.QPixmap(pix.size())
        out.fill(Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(out)
        painter.drawPixmap(0, 0, pix)
        painter.setCompositionMode(
            QtGui.QPainter.CompositionMode.CompositionMode_SourceIn
        )
        painter.fillRect(out.rect(), QtGui.QColor(color))
        painter.end()
        return out

    def _refresh_icon(self):
        active = self.isChecked() or self._hovered
        icon = self._active_icon if active else self._normal_icon

        # Render the original icon smaller than the animation canvas so a
        # rotated/scaled icon always has transparent breathing room.
        base = icon.pixmap(QtCore.QSize(21, 21))

        # Primary green/blue action buttons need a white icon.
        if self.property("primary") is True:
            base = self._tint_pixmap(base, "#FFFFFF")

        canvas_size = 36
        canvas = QtGui.QPixmap(canvas_size, canvas_size)
        canvas.fill(Qt.GlobalColor.transparent)

        painter = QtGui.QPainter(canvas)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(
            QtGui.QPainter.RenderHint.SmoothPixmapTransform, True
        )
        painter.translate(
            canvas_size / 2.0,
            canvas_size / 2.0 - (0.8 * self._motion),
        )
        painter.rotate(-4.5 * self._motion)
        scale = 1.0 + (0.055 * self._motion)
        painter.scale(scale, scale)
        painter.drawPixmap(
            QtCore.QRectF(-10.5, -10.5, 21.0, 21.0),
            base,
            QtCore.QRectF(base.rect()),
        )
        painter.end()

        self.setIcon(QtGui.QIcon(canvas))
        self.setIconSize(QtCore.QSize(34, 34))

    def set_primary(self, primary=True):
        self.setProperty("primary", bool(primary))
        self._refresh_icon()

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



class WorkflowButton(TiltIconButton):
    def __init__(self, text: str, icon_name: str, key: str, parent=None):
        super().__init__(text, icon_name, parent, checkable=True)
        self.stage_key = key
        self.setObjectName("WorkflowButton")
        self.setMinimumHeight(50)
        self.setMinimumWidth(190)


class ContextCard(QFrame):
    def __init__(self, title: str, value: str = "—", parent=None):
        super().__init__(parent)
        self.setObjectName("ContextCard")
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(4)
        box.addWidget(QLabel(title, objectName="ContextKey"))
        self.value = QLabel(value, objectName="ContextValue")
        box.addWidget(self.value)


class SwitchButton(QPushButton):
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggled.connect(self.update)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor("#2868E8" if self.isChecked() else "#CBD6E3"))
        p.drawRoundedRect(QtCore.QRectF(0.5, 0.5, 39, 21), 11, 11)
        p.setBrush(QtGui.QColor("#FFFFFF"))
        p.drawEllipse(QtCore.QPointF(29 if self.isChecked() else 11, 11), 8, 8)
        p.end()


class PLCPageQt6(QWidget):
    toast_requested = pyqtSignal(str, str)
    connection_finished = pyqtSignal(bool, bool, str)
    mapping_finished = pyqtSignal(object, object, object)

    def __init__(self, user: dict | None = None, parent=None):
        super().__init__(parent)
        self.user = user or {}
        self.setObjectName("PLCPageQt6")

        self.plc_worker = PLCWorker(self)
        self.data_storage = DataStorage()

        self.available_tags: List[str] = []
        self.cached_all_tags: List[str] = []
        self.display_tags: List[str] = []
        self.display_to_plc: Dict[str, Optional[str]] = {}
        self.read_tags: List[str] = []

        self.is_connected = False
        self.is_reading = False
        self.records_count = 0
        self._active_stage = "connect"
        self._manual_csv_path = ""

        self._build()
        self._apply_style()
        self._wire_backend()

        self.connection_finished.connect(self._on_connection_finished)
        self.mapping_finished.connect(self._on_mapping_finished)

        self.plc_worker.start()
        self._show_stage("connect")
        self._sync_controls()

    # -----------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        context = QGridLayout()
        context.setSpacing(8)

        self.connection_card = ContextCard("CONNECTION", "Disconnected")
        self.address_card = ContextCard("PLC ADDRESS", "192.168.1.1 · Slot 0")
        self.tags_card = ContextCard("MONITORING TAGS", "0 selected")
        self.collection_card = ContextCard("COLLECTION", "Idle · CSV enabled")

        context.addWidget(self.connection_card, 0, 0)
        context.addWidget(self.address_card, 0, 1)
        context.addWidget(self.tags_card, 0, 2)
        context.addWidget(self.collection_card, 0, 3)
        for col, stretch in enumerate((11, 12, 10, 10)):
            context.setColumnStretch(col, stretch)
        root.addLayout(context)

        workspace = QHBoxLayout()
        workspace.setSpacing(10)

        self.rail = QFrame(objectName="WorkflowRail")
        self.rail.setFixedWidth(220)
        rb = QVBoxLayout(self.rail)
        rb.setContentsMargins(11, 11, 11, 11)
        rb.setSpacing(7)

        rb.addWidget(QLabel("PLC WORKFLOW", objectName="RailEyebrow"))
        self.workflow_buttons = {}

        for key, text, icon in (
            ("connect", "Connect PLC", "connect"),
            ("tags", "Select Tags", "tags"),
            ("storage", "Storage & Collection", "storage"),
            ("monitor", "Live Monitor", "monitor"),
        ):
            button = WorkflowButton(text, icon, key)
            button.clicked.connect(lambda checked=False, stage=key: self._show_stage(stage))
            rb.addWidget(button)
            self.workflow_buttons[key] = button

        divider = QFrame(objectName="RailDivider")
        divider.setFixedHeight(1)
        rb.addWidget(divider)
        rb.addWidget(QLabel("TOOLS", objectName="RailEyebrow"))

        log_button = WorkflowButton("System Log", "log", "log")
        log_button.clicked.connect(lambda: self._show_stage("log"))
        rb.addWidget(log_button)
        self.workflow_buttons["log"] = log_button
        rb.addStretch(1)

        workspace.addWidget(self.rail)

        card = QFrame(objectName="WorkspaceCard")
        card_box = QVBoxLayout(card)
        card_box.setContentsMargins(0, 0, 0, 0)
        card_box.setSpacing(0)

        header = QFrame(objectName="WorkspaceHeader")
        hb = QHBoxLayout(header)
        hb.setContentsMargins(14, 10, 14, 10)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.stage_title = QLabel("Connect PLC", objectName="WorkspaceTitle")
        self.stage_subtitle = QLabel(
            "Configure the controller endpoint and establish the PLC session.",
            objectName="WorkspaceSubtitle",
        )
        title_box.addWidget(self.stage_title)
        title_box.addWidget(self.stage_subtitle)
        hb.addLayout(title_box, 1)

        self.step_badge = QLabel("STEP 1 OF 4", objectName="StepBadge")
        hb.addWidget(self.step_badge)
        card_box.addWidget(header)

        self.stack = QStackedWidget()
        self.connect_page = self._build_connect_page()
        self.tags_page = self._build_tags_page()
        self.storage_page = self._build_storage_page()
        self.monitor_page = self._build_monitor_page()
        self.log_page = self._build_log_page()

        for widget in (
            self.connect_page,
            self.tags_page,
            self.storage_page,
            self.monitor_page,
            self.log_page,
        ):
            self.stack.addWidget(widget)

        card_box.addWidget(self.stack, 1)

        footer = QFrame(objectName="WorkspaceFooter")
        fb = QHBoxLayout(footer)
        fb.setContentsMargins(13, 9, 13, 9)
        self.footer_text = QLabel("Connect to the PLC to begin.", objectName="FooterText")
        fb.addWidget(self.footer_text)
        fb.addStretch(1)

        self.back_btn = QPushButton("← Back", objectName="SecondaryButton")
        self.back_btn.clicked.connect(self._previous_stage)
        self.continue_btn = QPushButton("Continue →", objectName="PrimaryButton")
        self.continue_btn.clicked.connect(self._next_stage)

        fb.addWidget(self.back_btn)
        fb.addWidget(self.continue_btn)
        card_box.addWidget(footer)

        workspace.addWidget(card, 1)
        root.addLayout(workspace, 1)

    def _build_connect_page(self):
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(14, 14, 14, 14)
        grid.setSpacing(11)

        connection_panel = self._panel(
            "PLC Connection",
            "Connect using the existing Allen-Bradley EtherNet/IP backend.",
        )
        cp = connection_panel.layout()

        cp.addWidget(QLabel("IP Address", objectName="FieldLabel"))
        self.ip_edit = QLineEdit("192.168.1.1", objectName="FieldEdit")
        cp.addWidget(self.ip_edit)

        cp.addWidget(QLabel("Slot", objectName="FieldLabel"))
        self.slot_spin = QSpinBox(objectName="FieldSpin")
        self.slot_spin.setRange(0, 10)
        self.slot_spin.setValue(0)
        cp.addWidget(self.slot_spin)

        row = QHBoxLayout()
        self.connect_btn = TiltIconButton("Connect to PLC", "connect")
        self.connect_btn.set_primary(True)
        self.connect_btn.setObjectName("GreenButton")
        self.connect_btn.setMinimumHeight(37)
        self.connect_btn.setMinimumWidth(150)
        self.connect_btn.clicked.connect(self.connect_to_plc)

        self.disconnect_btn = QPushButton("Disconnect", objectName="DangerButton")
        self.disconnect_btn.clicked.connect(self.disconnect_from_plc)

        row.addWidget(self.connect_btn)
        row.addWidget(self.disconnect_btn)
        row.addStretch(1)
        cp.addLayout(row)
        cp.addStretch(1)

        health_panel = self._panel(
            "Connection Health",
            "Current PLC state and controller communication.",
        )
        hp = health_panel.layout()

        self.health_box = QFrame(objectName="HealthBox")
        hbr = QHBoxLayout(self.health_box)
        hbr.setContentsMargins(10, 9, 10, 9)
        self.health_icon = QLabel("✓", objectName="HealthIcon")
        self.health_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.health_icon.setFixedSize(34, 34)
        hbr.addWidget(self.health_icon)

        copy = QVBoxLayout()
        copy.setSpacing(2)
        self.health_title = QLabel("Ready to connect", objectName="HealthTitle")
        self.health_subtitle = QLabel(
            "Enter the PLC endpoint and connect.",
            objectName="HealthSubtitle",
        )
        copy.addWidget(self.health_title)
        copy.addWidget(self.health_subtitle)
        hbr.addLayout(copy, 1)
        hp.addWidget(self.health_box)

        metrics = QGridLayout()
        metrics.setSpacing(7)
        self.mode_metric = self._metric(metrics, 0, 0, "MODE", "—")
        self.tags_metric = self._metric(metrics, 0, 1, "TAGS", "—")
        self.read_metric = self._metric(metrics, 0, 2, "READ STATE", "Idle")
        hp.addLayout(metrics)
        hp.addStretch(1)

        grid.addWidget(connection_panel, 0, 0)
        grid.addWidget(health_panel, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(1, 1)
        return page

    def _build_tags_page(self):
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(14, 14, 14, 14)
        grid.setSpacing(10)

        left = QFrame(objectName="InnerPanel")
        lb = QVBoxLayout(left)
        lb.setContentsMargins(0, 0, 0, 0)
        lb.setSpacing(0)
        lb.addWidget(self._inner_header(
            "Available Tags",
            "Retrieve and choose tags exposed by the connected PLC.",
        ))

        search_host = QFrame(objectName="SearchHost")
        sr = QHBoxLayout(search_host)
        sr.setContentsMargins(8, 5, 8, 5)
        search_icon = QLabel()
        search_icon.setPixmap(QtGui.QIcon(_asset("search.svg")).pixmap(15, 15))
        self.tag_search = QLineEdit()
        self.tag_search.setPlaceholderText("Search available PLC tags")
        self.tag_search.setFrame(False)
        self.tag_search.textChanged.connect(self._filter_available_tags)
        sr.addWidget(search_icon)
        sr.addWidget(self.tag_search, 1)
        lb.addWidget(search_host)

        self.available_list = QListWidget(objectName="TagList")
        self.available_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.available_list.itemSelectionChanged.connect(self._sync_controls)
        lb.addWidget(self.available_list, 1)

        actions = QWidget()
        ag = QGridLayout(actions)
        ag.setContentsMargins(9, 8, 9, 9)
        ag.setSpacing(6)

        self.get_tags_btn = QPushButton("Get All Tags", objectName="SmallButton")
        self.get_tags_btn.clicked.connect(self.get_all_tags)

        self.select_all_btn = QPushButton("Select All", objectName="SmallButton")
        self.select_all_btn.clicked.connect(self.available_list.selectAll)

        self.clear_selection_btn = QPushButton("Clear Selection", objectName="SmallButton")
        self.clear_selection_btn.clicked.connect(self.available_list.clearSelection)

        self.add_selected_btn = QPushButton("Add Selected", objectName="SmallButton")
        self.add_selected_btn.clicked.connect(self.add_selected_tags)

        self.add_all_btn = QPushButton("Add All", objectName="SmallButton")
        self.add_all_btn.clicked.connect(self.add_all_tags)

        self.auto_map_btn = QPushButton("Add 300+ Specific Tags · Auto-map", objectName="PurpleButton")
        self.auto_map_btn.clicked.connect(self.add_specific_tags_automap)

        ag.addWidget(self.get_tags_btn, 0, 0)
        ag.addWidget(self.select_all_btn, 0, 1)
        ag.addWidget(self.clear_selection_btn, 0, 2)
        ag.addWidget(self.add_selected_btn, 1, 0)
        ag.addWidget(self.add_all_btn, 1, 1)
        ag.addWidget(self.auto_map_btn, 1, 2)
        lb.addWidget(actions)

        right = QFrame(objectName="InnerPanel")
        rb = QVBoxLayout(right)
        rb.setContentsMargins(0, 0, 0, 0)
        rb.setSpacing(0)
        rb.addWidget(self._inner_header(
            "Monitoring Tags",
            "Display labels mapped to readable PLC tag names.",
        ))

        self.selected_list = QListWidget(objectName="SelectedTagList")
        self.selected_list.itemSelectionChanged.connect(self._sync_controls)
        rb.addWidget(self.selected_list, 1)

        self.selected_count = QLabel("0 display tags selected", objectName="SelectedCount")
        rb.addWidget(self.selected_count)

        selected_actions = QWidget()
        sag = QGridLayout(selected_actions)
        sag.setContentsMargins(9, 8, 9, 9)
        sag.setSpacing(6)

        self.remove_btn = QPushButton("Remove Selected", objectName="SmallButton")
        self.remove_btn.clicked.connect(self.remove_selected_tag)

        self.clear_all_btn = QPushButton("Clear All", objectName="SmallButton")
        self.clear_all_btn.clicked.connect(self.clear_all_tags)

        self.save_taglist_btn = QPushButton("Save Tag List CSV", objectName="SmallButton")
        self.save_taglist_btn.clicked.connect(self.save_taglist_dialog)

        sag.addWidget(self.remove_btn, 0, 0)
        sag.addWidget(self.clear_all_btn, 0, 1)
        sag.addWidget(self.save_taglist_btn, 0, 2)
        rb.addWidget(selected_actions)

        grid.addWidget(left, 0, 0)
        grid.addWidget(right, 0, 1)
        grid.setColumnStretch(0, 11)
        grid.setColumnStretch(1, 9)
        return page

    def _build_storage_page(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(11)

        grid = QGridLayout()
        grid.setSpacing(11)

        collect = self._panel(
            "Collection Settings",
            "Control how often values are read from the PLC.",
        )
        cb = collect.layout()

        cb.addWidget(QLabel("Read Interval (ms)", objectName="FieldLabel"))
        self.interval_spin = QSpinBox(objectName="FieldSpin")
        self.interval_spin.setRange(100, 30000)
        self.interval_spin.setValue(1000)
        self.interval_spin.setSingleStep(100)
        cb.addWidget(self.interval_spin)

        cb.addWidget(QLabel("Batch Size", objectName="FieldLabel"))
        self.batch_spin = QSpinBox(objectName="FieldSpin")
        self.batch_spin.setRange(1, 100)
        self.batch_spin.setValue(50)
        cb.addWidget(self.batch_spin)

        action_row = QHBoxLayout()
        self.single_read_btn = TiltIconButton("Single Read", "read")
        self.single_read_btn.setObjectName("ToolbarButton")
        self.single_read_btn.setMinimumHeight(37)
        self.single_read_btn.setMinimumWidth(112)
        self.single_read_btn.clicked.connect(self.single_read)

        self.start_btn = TiltIconButton("Start Continuous Reading", "play")
        self.start_btn.set_primary(True)
        self.start_btn.setObjectName("GreenButton")
        self.start_btn.setMinimumHeight(37)
        self.start_btn.setMinimumWidth(190)
        self.start_btn.clicked.connect(self.start_reading)

        action_row.addWidget(self.single_read_btn)
        action_row.addWidget(self.start_btn)
        action_row.addStretch(1)
        cb.addLayout(action_row)
        cb.addStretch(1)

        storage = self._panel(
            "CSV Storage",
            "Save timestamped monitoring values for production review.",
        )
        sb = storage.layout()

        self.csv_switch = SwitchButton(True)
        self.csv_switch.toggled.connect(self._sync_context)
        sb.addLayout(self._switch_row("Save to CSV", self.csv_switch))

        self.auto_csv_switch = SwitchButton(True)
        sb.addLayout(self._switch_row("Auto-generate CSV filename", self.auto_csv_switch))

        sb.addWidget(QLabel("CSV destination", objectName="FieldLabel"))
        path_row = QHBoxLayout()
        self.csv_path_edit = QLineEdit(objectName="FieldEdit")
        self.csv_path_edit.setReadOnly(True)
        self.csv_path_edit.setText(self._default_csv_path())
        browse = QPushButton("Browse", objectName="SecondaryButton")
        browse.clicked.connect(self.browse_csv_file)
        path_row.addWidget(self.csv_path_edit, 1)
        path_row.addWidget(browse)
        sb.addLayout(path_row)
        sb.addStretch(1)

        grid.addWidget(collect, 0, 0)
        grid.addWidget(storage, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)

        summary = QFrame(objectName="SummaryStrip")
        sg = QGridLayout(summary)
        sg.setContentsMargins(0, 0, 0, 0)
        sg.setSpacing(0)

        self.summary_display = self._summary_cell(sg, 0, "DISPLAY TAGS", "0 selected")
        self.summary_readable = self._summary_cell(sg, 1, "READABLE TAGS", "0 resolved")
        self.summary_interval = self._summary_cell(sg, 2, "INTERVAL", "1000 ms")
        self.summary_storage = self._summary_cell(sg, 3, "STORAGE", "CSV enabled")
        root.addWidget(summary)
        root.addStretch(1)
        return page

    def _build_monitor_page(self):
        page = QWidget()
        root = QHBoxLayout(page)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        table_card = QFrame(objectName="InnerPanel")
        tb = QVBoxLayout(table_card)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(0)

        head = QFrame(objectName="MonitorHeader")
        hr = QHBoxLayout(head)
        hr.setContentsMargins(11, 8, 11, 8)
        hr.addWidget(QLabel("Real-time PLC Data", objectName="PanelTitle"))
        hr.addWidget(QLabel(
            "Display tag · current value · timestamp",
            objectName="PanelSubtitle",
        ))
        hr.addStretch(1)
        clear_btn = QPushButton("Clear Data", objectName="SmallButton")
        clear_btn.clicked.connect(self.clear_data)
        hr.addWidget(clear_btn)
        tb.addWidget(head)

        self.data_table = QTableWidget(0, 3)
        self.data_table.setObjectName("DataTable")
        self.data_table.setHorizontalHeaderLabels(
            ["DISPLAY TAG", "CURRENT VALUE", "TIMESTAMP"]
        )
        self.data_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.data_table.verticalHeader().setVisible(False)
        self.data_table.setAlternatingRowColors(True)
        self.data_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.data_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tb.addWidget(self.data_table, 1)
        root.addWidget(table_card, 1)

        status = self._panel(
            "Collection Status",
            "Live read statistics and recent system activity.",
        )
        status.setFixedWidth(300)
        sb = status.layout()

        self.records_metric = self._side_stat(sb, "RECORDS COLLECTED", "0")
        self.monitoring_metric = self._side_stat(sb, "TAGS MONITORING", "0")
        self.interval_metric = self._side_stat(sb, "READ INTERVAL", "1000 ms")

        self.mini_log = QTextEdit(objectName="MiniLog")
        self.mini_log.setReadOnly(True)
        sb.addWidget(self.mini_log, 1)

        self.stop_btn = TiltIconButton("Stop Reading", "stop")
        self.stop_btn.setObjectName("DangerIconButton")
        self.stop_btn.setMinimumHeight(36)
        self.stop_btn.setMinimumWidth(125)
        self.stop_btn.clicked.connect(self.stop_reading)
        sb.addWidget(self.stop_btn)

        root.addWidget(status)
        return page

    def _build_log_page(self):
        page = QWidget()
        root = QHBoxLayout(page)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self.log_text = QTextEdit(objectName="SystemLog")
        self.log_text.setReadOnly(True)
        root.addWidget(self.log_text, 1)

        tools = self._panel(
            "Log Controls",
            "Review or export PLC monitor events.",
        )
        tools.setFixedWidth(270)
        tb = tools.layout()

        clear_btn = QPushButton("Clear Log", objectName="SecondaryButton")
        clear_btn.clicked.connect(self.clear_log)
        save_btn = TiltIconButton("Save Log to File", "save")
        save_btn.setObjectName("ToolbarButton")
        save_btn.setMinimumHeight(36)
        save_btn.setMinimumWidth(145)
        save_btn.clicked.connect(self.save_log)

        tb.addWidget(clear_btn)
        tb.addWidget(save_btn)
        tb.addStretch(1)
        root.addWidget(tools)
        return page

    def _panel(self, title, subtitle):
        frame = QFrame(objectName="Panel")
        box = QVBoxLayout(frame)
        box.setContentsMargins(13, 12, 13, 12)
        box.setSpacing(8)
        box.addWidget(QLabel(title, objectName="PanelTitle"))
        sub = QLabel(subtitle, objectName="PanelSubtitle")
        sub.setWordWrap(True)
        box.addWidget(sub)
        return frame

    def _inner_header(self, title, subtitle):
        frame = QFrame(objectName="InnerHeader")
        box = QVBoxLayout(frame)
        box.setContentsMargins(11, 8, 11, 8)
        box.setSpacing(2)
        box.addWidget(QLabel(title, objectName="PanelTitle"))
        box.addWidget(QLabel(subtitle, objectName="PanelSubtitle"))
        return frame

    def _metric(self, layout, row, col, title, value):
        frame = QFrame(objectName="Metric")
        box = QVBoxLayout(frame)
        box.setContentsMargins(8, 7, 8, 7)
        box.setSpacing(2)
        box.addWidget(QLabel(title, objectName="MetricKey"))
        label = QLabel(value, objectName="MetricValue")
        box.addWidget(label)
        layout.addWidget(frame, row, col)
        return label

    def _side_stat(self, parent, title, value):
        frame = QFrame(objectName="SideStat")
        box = QVBoxLayout(frame)
        box.setContentsMargins(8, 7, 8, 7)
        box.setSpacing(2)
        box.addWidget(QLabel(title, objectName="MetricKey"))
        label = QLabel(value, objectName="SideStatValue")
        box.addWidget(label)
        parent.addWidget(frame)
        return label

    def _switch_row(self, text, switch):
        row = QHBoxLayout()
        row.addWidget(QLabel(text, objectName="SwitchLabel"))
        row.addStretch(1)
        row.addWidget(switch)
        return row

    def _summary_cell(self, layout, col, title, value):
        frame = QFrame(objectName="SummaryCell")
        box = QVBoxLayout(frame)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(2)
        box.addWidget(QLabel(title, objectName="MetricKey"))
        label = QLabel(value, objectName="SummaryValue")
        box.addWidget(label)
        layout.addWidget(frame, 0, col)
        return label

    # -----------------------------------------------------------------
    # Workflow navigation
    # -----------------------------------------------------------------
    def _show_stage(self, stage):
        mapping = {
            "connect": self.connect_page,
            "tags": self.tags_page,
            "storage": self.storage_page,
            "monitor": self.monitor_page,
            "log": self.log_page,
        }
        if stage not in mapping:
            return

        self._active_stage = stage
        self.stack.setCurrentWidget(mapping[stage])

        info = {
            "connect": (
                "Connect PLC",
                "Configure the controller endpoint and establish the PLC session.",
                "STEP 1 OF 4",
                "Connect to the PLC to begin.",
            ),
            "tags": (
                "Select Tags",
                "Retrieve PLC tags and choose the values required for live monitoring.",
                "STEP 2 OF 4",
                "Choose the tags required for monitoring.",
            ),
            "storage": (
                "Storage & Collection",
                "Configure polling, batching and CSV storage before collection.",
                "STEP 3 OF 4",
                "Configure collection and storage settings.",
            ),
            "monitor": (
                "Live Monitor",
                "Monitor selected PLC values and collection status in real time.",
                "STEP 4 OF 4",
                "Real-time PLC values are shown here.",
            ),
            "log": (
                "System Log",
                "Review connection, mapping, storage and collection events.",
                "TOOL",
                "Review PLC monitor events.",
            ),
        }[stage]

        self.stage_title.setText(info[0])
        self.stage_subtitle.setText(info[1])
        self.step_badge.setText(info[2])
        self.footer_text.setText(info[3])

        for key, button in self.workflow_buttons.items():
            button.setChecked(key == stage)

        self.back_btn.setVisible(stage not in {"connect", "log"})
        self.continue_btn.setVisible(stage != "log")
        self.continue_btn.setText("Reading Active" if stage == "monitor" and self.is_reading else "Continue →")
        self._sync_controls()

    def _previous_stage(self):
        stages = ["connect", "tags", "storage", "monitor"]
        if self._active_stage not in stages:
            return
        index = stages.index(self._active_stage)
        if index > 0:
            self._show_stage(stages[index - 1])

    def _next_stage(self):
        if self._active_stage == "connect":
            if not self.is_connected:
                QMessageBox.information(self, "Connect PLC", "Connect to the PLC before continuing.")
                return
            self._show_stage("tags")
            return

        if self._active_stage == "tags":
            if not self.display_tags:
                QMessageBox.information(self, "Select Tags", "Add at least one tag before continuing.")
                return
            self._show_stage("storage")
            return

        if self._active_stage == "storage":
            self._show_stage("monitor")
            return

    # -----------------------------------------------------------------
    # Backend
    # -----------------------------------------------------------------
    def _wire_backend(self):
        self.plc_worker.data_received.connect(self.on_data_received)
        self.plc_worker.status_signal.connect(self.on_status_update)
        self.plc_worker.error_signal.connect(self.on_error)
        self.plc_worker.tags_retrieved.connect(self.on_tags_retrieved)

    def connect_to_plc(self):
        ip = self.ip_edit.text().strip()
        slot = self.slot_spin.value()

        if not ip:
            QMessageBox.warning(self, "Input Error", "Please enter the PLC IP address.")
            return

        self.connect_btn.setEnabled(False)
        self.health_title.setText("Connecting…")
        self.health_subtitle.setText(f"Opening PLC session at {ip}.")
        self.address_card.value.setText(f"{ip} · Slot {slot}")
        self.log_message(f"Connecting to PLC at {ip}...")

        def job():
            success = self.plc_worker.connect_plc(ip, slot)
            simulation = bool(self.plc_worker.simulation)
            self.connection_finished.emit(success, simulation, ip)

        threading.Thread(target=job, daemon=True).start()

    @QtCore.pyqtSlot(bool, bool, str)
    def _on_connection_finished(self, success, simulation, ip):
        self.is_connected = bool(success or simulation)

        if success:
            self.connection_card.value.setText("Connected · Real PLC")
            self.health_title.setText("PLC connected")
            self.health_subtitle.setText("Controller communication is healthy.")
            self.mode_metric.setText("REAL")
            self.toast_requested.emit("PLC connected", f"Connected to {ip}.")
        elif simulation:
            self.connection_card.value.setText("Connected · Simulation")
            self.health_title.setText("Simulation mode active")
            self.health_subtitle.setText("Real PLC connection failed; dummy data is active.")
            self.mode_metric.setText("SIM")
            self.toast_requested.emit("Simulation mode", "PLC connection failed; dummy data is active.")
        else:
            self.connection_card.value.setText("Disconnected")
            self.health_title.setText("Connection failed")
            self.health_subtitle.setText("Check the controller address and network.")
            self.mode_metric.setText("—")

        self._sync_controls()
        if self.is_connected:
            QtCore.QTimer.singleShot(250, lambda: self._show_stage("tags"))

    def disconnect_from_plc(self):
        self.stop_reading(quiet=True)
        self.plc_worker.disconnect_plc()
        self.is_connected = False
        self.connection_card.value.setText("Disconnected")
        self.health_title.setText("Disconnected")
        self.health_subtitle.setText("PLC session closed.")
        self.mode_metric.setText("—")
        self.tags_metric.setText("—")
        self._sync_controls()
        self.toast_requested.emit("PLC disconnected", "Controller session closed.")

    def get_all_tags(self):
        if not self.is_connected:
            QMessageBox.information(self, "PLC Connection", "Connect to the PLC first.")
            return

        self.get_tags_btn.setEnabled(False)
        self.health_subtitle.setText("Retrieving tags from PLC…")
        self.log_message("Retrieving tags from PLC...")

        threading.Thread(target=self.plc_worker.get_all_tags, daemon=True).start()

    @QtCore.pyqtSlot(list)
    def on_tags_retrieved(self, tags):
        self.available_tags = sorted(tags or [])
        self.cached_all_tags = list(self.available_tags)
        self._populate_available_tags(self.available_tags)

        count = len(self.available_tags)
        self.tags_metric.setText(str(count) if count else "0")
        self.log_message(f"Successfully retrieved {count} tags from PLC")

        if self.cached_all_tags:
            path = self.save_taglist_csv(self.cached_all_tags)
            self.log_message(f"Auto-saved tag list to: {path}")

        self.get_tags_btn.setEnabled(True)
        self._sync_controls()

    def _populate_available_tags(self, tags):
        self.available_list.clear()
        for tag in tags:
            self.available_list.addItem(tag)

    def _filter_available_tags(self, text):
        text = text.strip().lower()
        filtered = self.available_tags if not text else [
            tag for tag in self.available_tags if text in tag.lower()
        ]
        self._populate_available_tags(filtered)

    def add_selected_tags(self):
        selected = [item.text() for item in self.available_list.selectedItems()]
        if not selected:
            QMessageBox.information(self, "Select Tags", "Select one or more PLC tags first.")
            return

        added = 0
        for tag in selected:
            if tag not in self.display_tags:
                self.display_tags.append(tag)
                self.display_to_plc[tag] = tag
                added += 1

        self._refresh_selected_list()
        self.log_message(f"Added {added} tags to monitoring list")

    def add_all_tags(self):
        if not self.available_tags:
            QMessageBox.information(self, "No Tags", "Retrieve PLC tags first.")
            return

        self.display_tags = list(self.available_tags)
        self.display_to_plc = {tag: tag for tag in self.display_tags}
        self._refresh_selected_list()
        self.log_message(f"Added all {len(self.display_tags)} tags to monitoring list")

    def add_specific_tags_automap(self):
        if not self.is_connected:
            QMessageBox.warning(self, "PLC Connection", "Connect to the PLC first.")
            return

        if self.is_reading:
            self.stop_reading(quiet=True)

        self.auto_map_btn.setEnabled(False)
        self.selected_count.setText("Mapping predefined production tags…")
        self.log_message(
            f"Loaded {len(SPECIFIC_TAGS)} predefined tags. Auto-mapping to real PLC names..."
        )

        available = list(self.available_tags)

        def job():
            mapper = TagMapper(self.plc_worker, available)
            mapping, fixes, unresolved = mapper.map_specific_tags(list(SPECIFIC_TAGS))
            self.mapping_finished.emit(mapping, fixes, unresolved)

        threading.Thread(target=job, daemon=True).start()

    @QtCore.pyqtSlot(object, object, object)
    def _on_mapping_finished(self, mapping, fixes, unresolved):
        self.display_tags = list(SPECIFIC_TAGS)
        self.display_to_plc = dict(mapping)

        seen = set()
        self.read_tags = []
        for plc_name in self.display_to_plc.values():
            if plc_name and plc_name not in seen:
                seen.add(plc_name)
                self.read_tags.append(plc_name)

        for old, new in fixes:
            self.log_message(f"Fixed tag: {old} -> {new}")
        for missing in unresolved:
            self.log_message(f"Could not resolve (skipped from read): {missing}")

        self._refresh_selected_list()
        self.auto_map_btn.setEnabled(True)
        self.selected_count.setText(
            f"{len(self.display_tags)} display tags selected · "
            f"{len(self.read_tags)} readable · {len(unresolved)} unresolved"
        )
        self.toast_requested.emit(
            "Auto-map complete",
            f"{len(self.read_tags)} readable tags · {len(unresolved)} unresolved.",
        )

    def remove_selected_tag(self):
        rows = sorted(
            {self.selected_list.row(item) for item in self.selected_list.selectedItems()},
            reverse=True,
        )
        if not rows:
            return

        for row in rows:
            display = self.selected_list.item(row).text()
            if "  →  " in display:
                display = display.split("  →  ", 1)[0]
            if display in self.display_tags:
                self.display_tags.remove(display)
            self.display_to_plc.pop(display, None)

        self._rebuild_read_tags()
        self._refresh_selected_list()

    def clear_all_tags(self):
        self.display_tags.clear()
        self.display_to_plc.clear()
        self.read_tags.clear()
        self._refresh_selected_list()

    def _refresh_selected_list(self):
        self.selected_list.clear()
        for display in self.display_tags:
            plc_name = self.display_to_plc.get(display)
            text = display if plc_name in {None, display} else f"{display}  →  {plc_name}"
            item = QListWidgetItem(text)
            if plc_name is None:
                item.setForeground(QtGui.QColor("#C93450"))
            self.selected_list.addItem(item)

        self._rebuild_read_tags()
        self._sync_context()
        self._sync_controls()

    def _rebuild_read_tags(self):
        seen = set()
        self.read_tags = []
        for display in self.display_tags:
            plc_name = self.display_to_plc.get(display)
            if plc_name and plc_name not in seen:
                seen.add(plc_name)
                self.read_tags.append(plc_name)

    def start_reading(self):
        if not self.display_tags:
            QMessageBox.warning(self, "No Tags", "Select monitoring tags first.")
            return

        self._rebuild_read_tags()
        if not self.read_tags:
            QMessageBox.warning(
                self,
                "No Readable Tags",
                "No resolvable PLC tags are available. Check the mapping in System Log.",
            )
            return

        if not self._setup_storage():
            return

        self.records_count = 0
        self.plc_worker.start_reading(
            self.read_tags,
            self.interval_spin.value(),
            self.batch_spin.value(),
        )

        self.is_reading = True
        self.read_metric.setText("Reading")
        self.collection_card.value.setText(
            "Reading · CSV enabled" if self.csv_switch.isChecked() else "Reading · Storage off"
        )
        self.log_message(
            f"Started continuous reading of {len(self.read_tags)} PLC tags "
            f"(display columns: {len(self.display_tags)})"
        )
        self.toast_requested.emit(
            "Collection started",
            f"{len(self.read_tags)} tags · {self.interval_spin.value()} ms.",
        )
        self._sync_controls()
        self._show_stage("monitor")

    def stop_reading(self, quiet=False):
        self.is_reading = False
        self.plc_worker.stop_reading()
        self.data_storage.close()
        self.read_metric.setText("Idle")
        self.collection_card.value.setText(
            "Idle · CSV enabled" if self.csv_switch.isChecked() else "Idle · Storage off"
        )
        self._sync_controls()
        if not quiet:
            self.toast_requested.emit("Reading stopped", "PLC data collection was stopped.")

    def single_read(self):
        if not self.display_tags:
            QMessageBox.warning(self, "No Tags", "Select monitoring tags first.")
            return

        self._rebuild_read_tags()
        if not self.read_tags:
            QMessageBox.warning(self, "No Readable Tags", "No readable PLC tags are available.")
            return

        if not self._setup_storage():
            return

        self.plc_worker.batch_size = self.batch_spin.value()
        threading.Thread(
            target=self.plc_worker.read_single_cycle,
            args=(list(self.read_tags),),
            daemon=True,
        ).start()
        self.log_message("Performed single read operation")

    def _setup_storage(self):
        self.data_storage.close()
        self.data_storage.use_csv = self.csv_switch.isChecked()

        if not self.data_storage.use_csv:
            return True

        filename = self._current_csv_path()
        if not self.data_storage.setup_csv(filename):
            QMessageBox.critical(self, "Storage Error", "Failed to create the CSV file.")
            return False

        self.data_storage.current_display_tags = list(self.display_tags)
        self.data_storage.display_to_plc = dict(self.display_to_plc)
        self.data_storage.write_headers()
        self.csv_path_edit.setText(filename)
        self.log_message(f"CSV storage setup: {filename}")
        return True

    def _default_csv_path(self):
        return str(
            _app_root()
            / f"plc_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )

    def _current_csv_path(self):
        if self.auto_csv_switch.isChecked():
            return self._default_csv_path()
        if self._manual_csv_path:
            return self._manual_csv_path
        value = self.csv_path_edit.text().strip()
        return value or self._default_csv_path()

    def browse_csv_file(self):
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save CSV File",
            self._current_csv_path(),
            "CSV Files (*.csv)",
        )
        if filename:
            self._manual_csv_path = filename
            self.csv_path_edit.setText(filename)
            self.auto_csv_switch.setChecked(False)

    @QtCore.pyqtSlot(dict)
    def on_data_received(self, data):
        try:
            timestamp = data["timestamp"]
            values = data["values"]
            self.data_storage.store_data(timestamp, values)
            self._update_table(timestamp, values)
            self.records_count += 1
            self.records_metric.setText(str(self.records_count))
        except Exception as exc:
            self.log_message(f"Error processing data: {exc}")

    def _update_table(self, timestamp, values):
        text_time = timestamp.strftime("%H:%M:%S.%f")[:-3]
        if self.data_table.rowCount() != len(self.display_tags):
            self.data_table.setRowCount(len(self.display_tags))

        for row, display in enumerate(self.display_tags):
            plc_name = self.display_to_plc.get(display)
            value = "N/A" if plc_name is None else values.get(plc_name, "N/A")

            for col, text in enumerate((display, str(value), text_time)):
                item = self.data_table.item(row, col)
                if item is None:
                    item = QTableWidgetItem(text)
                    self.data_table.setItem(row, col, item)
                else:
                    item.setText(text)

            value_item = self.data_table.item(row, 1)
            if "Error" in str(value):
                value_item.setForeground(QtGui.QColor("#C93450"))
            else:
                value_item.setForeground(QtGui.QColor("#17263D"))

    @QtCore.pyqtSlot(str)
    def on_status_update(self, message):
        self.log_message(f"INFO: {message}")
        if "Retrieved" in message:
            self.health_subtitle.setText(message)

    @QtCore.pyqtSlot(str)
    def on_error(self, message):
        lower = message.lower()
        if self.plc_worker.simulation and (
            "connection failed" in lower or
            "connection error" in lower or
            "timed out" in lower
        ):
            self.log_message(f"SIM INFO: {message}")
            return

        self.log_message(f"ERROR: {message}")
        QMessageBox.critical(self, "PLC Error", message)

    # -----------------------------------------------------------------
    # CSV / logs
    # -----------------------------------------------------------------
    def save_taglist_csv(self, tags, filename=None):
        if filename is None:
            filename = str(
                _app_root()
                / f"plc_taglist_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            )

        try:
            with open(filename, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["tag"])
                for tag in tags:
                    writer.writerow([tag])
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", f"Failed to save tag list:\n{exc}")
        return filename

    def save_taglist_dialog(self):
        if not self.cached_all_tags:
            QMessageBox.information(self, "No Tags", "Click Get All Tags first.")
            return

        default = str(
            _app_root()
            / f"plc_taglist_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Tag List CSV",
            default,
            "CSV Files (*.csv)",
        )
        if filename:
            self.save_taglist_csv(self.cached_all_tags, filename)
            self.log_message(f"Tag list saved to: {filename}")
            self.toast_requested.emit(
                "Tag list saved",
                f"{len(self.cached_all_tags)} tags exported.",
            )

    def log_message(self, message):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        self.log_text.append(line)
        self.mini_log.append(line)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )
        self.mini_log.verticalScrollBar().setValue(
            self.mini_log.verticalScrollBar().maximum()
        )

    def clear_log(self):
        self.log_text.clear()
        self.mini_log.clear()
        self.log_message("Log cleared")

    def save_log(self):
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Log File",
            str(_app_root() / f"plc_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"),
            "Text Files (*.txt)",
        )
        if not filename:
            return

        try:
            Path(filename).write_text(self.log_text.toPlainText(), encoding="utf-8")
            self.log_message(f"Log saved to {filename}")
            self.toast_requested.emit("Log saved", Path(filename).name)
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", f"Failed to save log:\n{exc}")

    def clear_data(self):
        self.data_table.setRowCount(0)
        self.records_count = 0
        self.records_metric.setText("0")
        self.log_message("Cleared data display")

    # -----------------------------------------------------------------
    # State / shell integration
    # -----------------------------------------------------------------
    def refresh_context(self):
        self._sync_context()
        self._sync_controls()

    def _sync_context(self):
        ip = self.ip_edit.text().strip() if hasattr(self, "ip_edit") else "192.168.1.1"
        slot = self.slot_spin.value() if hasattr(self, "slot_spin") else 0
        self.address_card.value.setText(f"{ip} · Slot {slot}")
        self.tags_card.value.setText(f"{len(self.display_tags)} selected")

        if self.is_reading:
            self.collection_card.value.setText(
                "Reading · CSV enabled" if self.csv_switch.isChecked() else "Reading · Storage off"
            )
        else:
            self.collection_card.value.setText(
                "Idle · CSV enabled" if self.csv_switch.isChecked() else "Idle · Storage off"
            )

        readable = len([value for value in self.display_to_plc.values() if value])
        self.selected_count.setText(
            f"{len(self.display_tags)} display tags selected · {readable} readable"
        )
        self.summary_display.setText(f"{len(self.display_tags)} selected")
        self.summary_readable.setText(f"{readable} resolved")
        self.summary_interval.setText(f"{self.interval_spin.value()} ms")
        self.summary_storage.setText(
            "CSV enabled" if self.csv_switch.isChecked() else "Disabled"
        )
        self.monitoring_metric.setText(str(len(self.display_tags)))
        self.interval_metric.setText(f"{self.interval_spin.value()} ms")

    def _sync_controls(self):
        connected = self.is_connected
        has_available = bool(self.available_tags)
        has_display = bool(self.display_tags)

        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)
        self.get_tags_btn.setEnabled(connected)
        self.select_all_btn.setEnabled(has_available)
        self.clear_selection_btn.setEnabled(has_available)
        self.add_selected_btn.setEnabled(
            connected and bool(self.available_list.selectedItems())
        )
        self.add_all_btn.setEnabled(connected and has_available)
        self.auto_map_btn.setEnabled(connected)
        self.save_taglist_btn.setEnabled(bool(self.cached_all_tags))
        self.remove_btn.setEnabled(bool(self.selected_list.selectedItems()))
        self.clear_all_btn.setEnabled(has_display)

        self.single_read_btn.setEnabled(
            connected and has_display and not self.is_reading
        )
        self.start_btn.setEnabled(
            connected and has_display and not self.is_reading
        )
        self.stop_btn.setEnabled(self.is_reading)

        self.continue_btn.setEnabled(
            self._active_stage != "monitor" or self.is_reading
        )
        self._sync_context()

    def shutdown(self):
        try:
            self.stop_reading(quiet=True)
        except Exception:
            pass

        try:
            self.plc_worker.shutdown()
            self.plc_worker.wait(1500)
        except Exception:
            pass

        self.data_storage.close()

    # -----------------------------------------------------------------
    # Styling
    # -----------------------------------------------------------------
    def _apply_style(self):
        self.setStyleSheet("""
        QWidget#PLCPageQt6 {
            background:#EAF1F8;
            color:#101A2D;
        }
        QWidget#PLCPageQt6 QLabel {
            background:transparent;
            border:0;
        }

        QFrame#ContextCard {
            background:#FFFFFF;
            border:1px solid #AFC1D4;
            border-radius:12px;
        }
        QLabel#ContextKey {
            color:#60738B;
            font-size:8px;
            font-weight:850;
            letter-spacing:.65px;
        }
        QLabel#ContextValue {
            color:#15263D;
            font-size:10.4px;
            font-weight:800;
        }

        QFrame#WorkflowRail, QFrame#WorkspaceCard {
            background:#FFFFFF;
            border:1px solid #A9BED3;
            border-radius:14px;
        }
        QLabel#RailEyebrow {
            color:#60728A;
            font-size:8px;
            font-weight:850;
            letter-spacing:.8px;
        }
        QFrame#RailDivider {
            background:#DCE4EE;
            border:0;
        }
        QPushButton#WorkflowButton {
            background:#FFFFFF;
            border:1px solid #AFC1D4;
            border-radius:10px;
            min-height:50px;
            text-align:left;
            padding:0 12px;
            color:#405873;
            font-size:9.3px;
            font-weight:760;
        }
        QPushButton#WorkflowButton:hover {
            background:#F0F5FF;
            border-color:#9DB7E2;
        }
        QPushButton#WorkflowButton:checked {
            background:#E8F1FF;
            border:1px solid #2868E8;
        }

        QFrame#WorkspaceHeader, QFrame#WorkspaceFooter {
            background:#FFFFFF;
            border:0;
        }
        QFrame#WorkspaceHeader {
            border-bottom:1px solid #DCE4EE;
        }
        QFrame#WorkspaceFooter {
            border-top:1px solid #DCE4EE;
        }
        QLabel#WorkspaceTitle {
            color:#17263D;
            font-size:14px;
            font-weight:850;
        }
        QLabel#WorkspaceSubtitle, QLabel#FooterText {
            color:#60728A;
            font-size:8.8px;
            font-weight:600;
        }
        QLabel#StepBadge {
            color:#566A82;
            background:#F1F5FA;
            border:1px solid #DCE4EE;
            border-radius:10px;
            padding:5px 9px;
            font-size:7.7px;
            font-weight:850;
        }

        QFrame#Panel, QFrame#InnerPanel {
            background:#F7FAFD;
            border:1px solid #B5C7DA;
            border-radius:11px;
        }
        QLabel#PanelTitle {
            color:#17263D;
            font-size:11px;
            font-weight:830;
        }
        QLabel#PanelSubtitle {
            color:#66788E;
            font-size:8.5px;
            font-weight:600;
        }
        QLabel#FieldLabel {
            color:#405873;
            font-size:8.7px;
            font-weight:760;
        }

        QLineEdit#FieldEdit, QSpinBox#FieldSpin {
            min-height:35px;
            background:#FFFFFF;
            color:#17263D;
            border:1px solid #A6BBD1;
            border-radius:8px;
            padding:0 9px;
            font-size:9.5px;
        }
        QLineEdit#FieldEdit:focus, QSpinBox#FieldSpin:focus {
            border:1px solid #2868E8;
        }

        QFrame#HealthBox {
            background:#EFF9F4;
            border:1px solid #CFE7DB;
            border-radius:10px;
        }
        QLabel#HealthIcon {
            color:#07965D;
            background:#DDF4E9;
            border-radius:9px;
            font-size:14px;
            font-weight:900;
        }
        QLabel#HealthTitle {
            color:#173A2E;
            font-size:9.6px;
            font-weight:820;
        }
        QLabel#HealthSubtitle {
            color:#60728A;
            font-size:8.1px;
        }

        QFrame#Metric, QFrame#SideStat {
            background:#FFFFFF;
            border:1px solid #BDCDE0;
            border-radius:9px;
        }
        QLabel#MetricKey {
            color:#718197;
            font-size:7.4px;
            font-weight:850;
            letter-spacing:.35px;
        }
        QLabel#MetricValue {
            color:#17263D;
            font-size:14px;
            font-weight:850;
        }
        QLabel#SideStatValue {
            color:#17263D;
            font-size:13px;
            font-weight:850;
        }

        QFrame#InnerHeader, QFrame#MonitorHeader {
            background:#FFFFFF;
            border:0;
            border-bottom:1px solid #DCE4EE;
        }
        QFrame#SearchHost {
            background:#FFFFFF;
            border:1px solid #A6BBD1;
            border-radius:8px;
            margin:8px 9px 5px 9px;
        }
        QFrame#SearchHost QLineEdit {
            background:#FFFFFF;
            color:#17263D;
            border:0;
            font-size:9px;
        }

        QListWidget#TagList, QListWidget#SelectedTagList {
            background:#FFFFFF;
            color:#253750;
            border:1px solid #BECEDF;
            border-radius:8px;
            margin:0 9px 0 9px;
            outline:0;
            font-size:8.8px;
        }
        QListWidget#TagList::item, QListWidget#SelectedTagList::item {
            min-height:30px;
            padding:2px 8px;
            border-bottom:1px solid #EEF2F6;
        }
        QListWidget#TagList::item:hover, QListWidget#SelectedTagList::item:hover {
            background:#F2F6FC;
        }
        QListWidget#TagList::item:selected, QListWidget#SelectedTagList::item:selected {
            background:#E8F1FF;
            color:#1D5BD0;
        }
        QLabel#SelectedCount {
            color:#078A57;
            background:#EEF8F4;
            border:1px solid #D0EBDD;
            border-radius:8px;
            margin:8px 9px 0 9px;
            padding:8px 9px;
            font-size:8.4px;
            font-weight:760;
        }

        QPushButton#SmallButton, QPushButton#PurpleButton,
        QPushButton#SecondaryButton, QPushButton#DangerButton,
        QPushButton#PrimaryButton {
            min-height:34px;
            border-radius:8px;
            padding:0 10px;
            font-size:8.6px;
            font-weight:780;
        }
        QPushButton#SmallButton, QPushButton#SecondaryButton {
            background:#FFFFFF;
            color:#2868E8;
            border:1px solid #A6BBD1;
        }
        QPushButton#SmallButton:hover, QPushButton#SecondaryButton:hover {
            background:#EEF4FF;
        }
        QPushButton#PurpleButton {
            background:#F8F5FF;
            color:#7047D7;
            border:1px solid #CBBDEB;
        }
        QPushButton#DangerButton {
            background:#FFFFFF;
            color:#C93450;
            border:1px solid #E3B6BE;
        }
        QPushButton#PrimaryButton {
            background:#2868E8;
            color:#FFFFFF;
            border:1px solid #2868E8;
        }
        QPushButton#PrimaryButton:disabled,
        QPushButton#SmallButton:disabled,
        QPushButton#SecondaryButton:disabled,
        QPushButton#DangerButton:disabled,
        QPushButton#PurpleButton:disabled {
            background:#F1F4F8;
            color:#9AA7B7;
            border-color:#DCE3EC;
        }

        QPushButton#GreenButton {
            background:#07965D;
            color:#FFFFFF;
            border:1px solid #07965D;
            border-radius:9px;
            padding:0 12px;
            text-align:left;
            font-size:9.2px;
            font-weight:800;
        }
        QPushButton#GreenButton:hover {
            background:#07814F;
            border-color:#07814F;
        }
        QPushButton#GreenButton:disabled {
            background:#BBD8CC;
            border-color:#BBD8CC;
        }
        QPushButton#ToolbarButton {
            background:#FFFFFF;
            color:#2868E8;
            border:1px solid #A6BBD1;
            border-radius:9px;
        }
        QPushButton#DangerIconButton {
            background:#FFFFFF;
            color:#C93450;
            border:1px solid #DDAAB4;
            border-radius:9px;
            padding:0 12px;
            text-align:left;
            font-size:9.1px;
            font-weight:760;
        }

        QLabel#SwitchLabel {
            color:#405873;
            font-size:8.8px;
            font-weight:720;
        }

        QFrame#SummaryStrip {
            background:#F7F9FC;
            border:1px solid #B7C8DA;
            border-radius:10px;
        }
        QFrame#SummaryCell {
            background:#F7F9FC;
            border:0;
            border-right:1px solid #DCE4EE;
        }
        QLabel#SummaryValue {
            color:#17263D;
            font-size:9px;
            font-weight:820;
        }

        QTableWidget#DataTable {
            background:#FFFFFF;
            alternate-background-color:#F9FBFE;
            color:#2C3E56;
            border:0;
            gridline-color:#EDF1F5;
            font-size:8.8px;
        }
        QTableWidget#DataTable::item {
            min-height:29px;
            padding:5px 8px;
            border-bottom:1px solid #EDF1F5;
        }
        QHeaderView::section {
            background:#F2F6FB;
            color:#60728A;
            border:0;
            border-bottom:1px solid #CFDAE7;
            padding:8px;
            font-size:7.8px;
            font-weight:850;
        }

        QTextEdit#MiniLog, QTextEdit#SystemLog {
            background:#0F1724;
            color:#D9E8FF;
            border:1px solid #26354A;
            border-radius:9px;
            font-family:Consolas;
            font-size:8.3px;
        }

        QScrollBar:vertical {
            background:transparent;
            width:8px;
            margin:2px;
        }
        QScrollBar::handle:vertical {
            background:#C5D2E2;
            border-radius:4px;
            min-height:28px;
        }
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            height:0;
        }
        """)


PLCPage = PLCPageQt6
