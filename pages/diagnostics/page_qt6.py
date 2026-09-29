"""EYRES AI - PyQt6 Application Diagnostics page.

Migrated from the existing PyQt5 DiagnosticsPage while preserving its backend:
- system_snapshot()
- recent_log_entries()
- build_support_report()
- export_support_report()
- clear_diagnostic_logs()
- diagnostic/audit event recording

The page keeps security-audit records separate from operational diagnostic logs.
"""

from __future__ import annotations

import json
import os
import platform
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtProperty, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app_core.audit import record_audit_event, verify_audit_integrity
from app_core.config import get_config
from app_core.diagnostics import (
    build_support_report,
    clear_diagnostic_logs,
    export_support_report,
    recent_log_entries,
    system_snapshot,
)
from db import mongo


_LOG_PATTERN = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2}\s+"
    r"\d{2}:\d{2}:\d{2}(?:,\d{3})?)\s+"
    r"(?P<level>CRITICAL|ERROR|WARNING|INFO|DEBUG)\s+"
    r"(?P<module>\S+)\s*"
    r"(?P<message>.*)$",
    re.IGNORECASE,
)


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _asset(name: str) -> str:
    return str(_root() / "ui" / "assets" / "diagnostics_icons" / name)


def _friendly_platform(raw: str) -> str:
    text = str(raw or "Unknown")
    if text.lower().startswith("windows"):
        match = re.match(r"Windows-(\d+)", text, re.IGNORECASE)
        return f"Windows {match.group(1)}" if match else "Windows"
    head = text.split("-", 1)[0].strip()
    return head or text


def _parse_log_line(raw: str) -> Tuple[str, str, str, str]:
    text = str(raw or "")
    match = _LOG_PATTERN.match(text)
    if match:
        return (
            match.group("time"),
            match.group("level").upper(),
            match.group("module"),
            match.group("message"),
        )
    return ("", "INFO", "", text)


def _mono_font() -> QtGui.QFont:
    font = QtGui.QFont("Cascadia Mono")
    if not QtGui.QFontInfo(font).exactMatch():
        font = QtGui.QFont("Consolas")
    font.setPointSizeF(8.4)
    return font


class WorkerSignals(QtCore.QObject):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)


class Worker(QtCore.QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = WorkerSignals()

    @QtCore.pyqtSlot()
    def run(self):
        try:
            self.signals.completed.emit(self.operation())
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class TiltIconButton(QPushButton):
    """Safe padded icon motion used across the migrated Qt6 pages."""

    def __init__(
        self,
        text: str,
        icon_name: str,
        parent=None,
        primary=False,
        danger=False,
        checkable=False,
    ):
        super().__init__(text, parent)
        self._motion = 0.0
        self._hovered = False
        self._primary = bool(primary)
        self._danger = bool(danger)
        self._normal = QtGui.QIcon(_asset(f"{icon_name}.svg"))
        self._active = QtGui.QIcon(_asset(f"{icon_name}_active.svg"))

        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QtCore.QSize(34, 34))
        self.setMinimumHeight(38)

        self._anim = QtCore.QPropertyAnimation(self, b"iconMotion", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)
        if checkable:
            self.toggled.connect(lambda _checked: self._refresh_icon())
        self._refresh_icon()

    def get_motion(self):
        return self._motion

    def set_motion(self, value):
        self._motion = max(0.0, min(1.0, float(value)))
        self._refresh_icon()

    iconMotion = pyqtProperty(float, fget=get_motion, fset=set_motion)

    @staticmethod
    def _tint(pix: QtGui.QPixmap, color: str):
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
        icon = self._active if (self._hovered or self.isChecked()) else self._normal
        base = icon.pixmap(QtCore.QSize(20, 20))
        if self._primary:
            base = self._tint(base, "#FFFFFF")
        elif self._danger:
            base = self._tint(base, "#C93450")

        canvas = QtGui.QPixmap(36, 36)
        canvas.fill(Qt.GlobalColor.transparent)

        painter = QtGui.QPainter(canvas)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.translate(18.0, 18.0 - (0.8 * self._motion))
        painter.rotate(-4.5 * self._motion)
        scale = 1.0 + (0.05 * self._motion)
        painter.scale(scale, scale)
        painter.drawPixmap(
            QtCore.QRectF(-10.0, -10.0, 20.0, 20.0),
            base,
            QtCore.QRectF(base.rect()),
        )
        painter.end()
        self.setIcon(QtGui.QIcon(canvas))

    def _animate(self, target):
        self._anim.stop()
        self._anim.setStartValue(self._motion)
        self._anim.setEndValue(float(target))
        self._anim.start()

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


class RailButton(TiltIconButton):
    def __init__(self, key: str, text: str, icon_name: str, parent=None):
        super().__init__(text, icon_name, parent, checkable=True)
        self.key = key
        self.setObjectName("DiagnosticsRailButton")
        self.setMinimumHeight(50)
        self.setMinimumWidth(190)


class ChevronComboBox(QComboBox):
    """White Qt popup with an explicit local SVG chevron."""

    def __init__(self, parent=None, objectName=None):
        super().__init__(parent)
        if objectName:
            self.setObjectName(str(objectName))

        self._arrow = QLabel(self)
        self._arrow.setObjectName("ComboChevron")
        self._arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._arrow.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        self._arrow.setPixmap(
            QtGui.QIcon(_asset("chevron_down.svg")).pixmap(13, 13)
        )
        self._arrow.setFixedSize(26, 30)
        self._arrow.raise_()

        self.setMaxVisibleItems(10)
        view = self.view()
        view.setObjectName("DiagnosticsComboPopup")
        view.setStyleSheet("""
            QAbstractItemView#DiagnosticsComboPopup {
                background:#FFFFFF;
                color:#17263D;
                border:1px solid #AFC1D4;
                outline:0;
                padding:4px;
                selection-background-color:#E8F1FF;
                selection-color:#17263D;
                font-size:9.4px;
                font-weight:650;
            }
            QAbstractItemView#DiagnosticsComboPopup::item {
                min-height:30px;
                padding:4px 8px;
            }
        """)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrow.move(
            max(0, self.width() - self._arrow.width() - 3),
            max(0, (self.height() - self._arrow.height()) // 2),
        )
        self._arrow.raise_()


class KpiCard(QFrame):
    def __init__(self, caption: str, icon_name: str, kind: str, parent=None):
        super().__init__(parent)
        self.setObjectName("KpiCard")
        self.setProperty("kind", kind)
        self.setMinimumHeight(80)

        self._motion = 0.0
        self._hovered = False
        self._normal = QtGui.QIcon(_asset(f"{icon_name}.svg"))
        self._active = QtGui.QIcon(_asset(f"{icon_name}_active.svg"))

        row = QHBoxLayout(self)
        row.setContentsMargins(13, 9, 12, 9)
        row.setSpacing(10)

        copy = QVBoxLayout()
        copy.setSpacing(2)
        copy.addWidget(QLabel(caption.upper(), objectName="KpiCaption"))
        self.value = QLabel("—", objectName="KpiValue")
        self.meta = QLabel("—", objectName="KpiMeta")
        self.meta.setWordWrap(False)
        copy.addWidget(self.value)
        copy.addWidget(self.meta)
        row.addLayout(copy, 1)

        self.icon_host = QLabel(objectName="KpiIcon")
        self.icon_host.setProperty("kind", kind)
        self.icon_host.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_host.setFixedSize(42, 42)
        row.addWidget(self.icon_host)

        self._anim = QtCore.QPropertyAnimation(self, b"iconMotion", self)
        self._anim.setDuration(185)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)
        self._refresh_icon()

    def set_data(self, value: str, meta: str = ""):
        self.value.setText(str(value))
        self.meta.setText(str(meta or ""))
        self.setToolTip(str(meta or value))

    def get_motion(self):
        return self._motion

    def set_motion(self, value):
        self._motion = max(0.0, min(1.0, float(value)))
        self._refresh_icon()

    iconMotion = pyqtProperty(float, fget=get_motion, fset=set_motion)

    def _refresh_icon(self):
        icon = self._active if self._hovered else self._normal
        base = icon.pixmap(QtCore.QSize(22, 22))

        canvas = QtGui.QPixmap(36, 36)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(canvas)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.translate(18.0, 18.0 - self._motion)
        painter.rotate(-5.0 * self._motion)
        scale = 1.0 + (0.055 * self._motion)
        painter.scale(scale, scale)
        painter.drawPixmap(
            QtCore.QRectF(-11.0, -11.0, 22.0, 22.0),
            base,
            QtCore.QRectF(base.rect()),
        )
        painter.end()
        self.icon_host.setPixmap(canvas)

    def enterEvent(self, event):
        self._hovered = True
        self._refresh_icon()
        self._anim.stop()
        self._anim.setStartValue(self._motion)
        self._anim.setEndValue(1.0)
        self._anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._anim.stop()
        self._anim.setStartValue(self._motion)
        self._anim.setEndValue(0.0)
        self._anim.start()
        super().leaveEvent(event)


class StatusRow(QFrame):
    def __init__(self, caption: str, parent=None):
        super().__init__(parent)
        self.setObjectName("StatusRow")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        self.caption = QLabel(caption, objectName="StatusCaption")
        self.status = QLabel("NOT CHECKED", objectName="StatusValue")
        self.status.setProperty("kind", "blue")
        row.addWidget(self.caption)
        row.addStretch(1)
        row.addWidget(self.status)

    def set_state(self, text: str, kind: str):
        self.status.setText(str(text))
        self.status.setProperty("kind", kind)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)


class MetricBox(QFrame):
    def __init__(self, caption: str, value="—", parent=None):
        super().__init__(parent)
        self.setObjectName("MetricBox")
        box = QVBoxLayout(self)
        box.setContentsMargins(9, 7, 9, 7)
        box.setSpacing(2)
        box.addWidget(QLabel(caption.upper(), objectName="MetricCaption"))
        self.value = QLabel(str(value), objectName="MetricValue")
        self.value.setWordWrap(True)
        box.addWidget(self.value)


class ClearLogsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("Clear diagnostic logs")
        self.resize(500, 330)
        self.setMinimumWidth(500)
        self.setStyleSheet(DIALOG_QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame(objectName="DialogHeader")
        hr = QHBoxLayout(header)
        hr.setContentsMargins(19, 15, 15, 13)

        copy = QVBoxLayout()
        copy.setSpacing(3)
        copy.addWidget(QLabel("Clear diagnostic logs?", objectName="DialogTitle"))
        subtitle = QLabel(
            "This removes operational diagnostics from the application log area.",
            objectName="DialogSubtitle",
        )
        subtitle.setWordWrap(True)
        copy.addWidget(subtitle)

        close = QToolButton(objectName="DialogClose")
        close.setText("×")
        close.setFixedSize(32, 32)
        close.clicked.connect(self.reject)

        hr.addLayout(copy, 1)
        hr.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        root.addWidget(header)

        body = QWidget()
        bb = QVBoxLayout(body)
        bb.setContentsMargins(19, 14, 19, 14)
        bb.setSpacing(9)

        warning = QFrame(objectName="WarningBox")
        wb = QVBoxLayout(warning)
        wb.setContentsMargins(11, 9, 11, 9)
        w = QLabel(
            "<b>Application logs and page timings will be cleared.</b><br>"
            "This can make troubleshooting recent application behaviour more difficult.",
            objectName="WarningText",
        )
        w.setWordWrap(True)
        wb.addWidget(w)

        safe = QFrame(objectName="SafeBox")
        sb = QVBoxLayout(safe)
        sb.setContentsMargins(11, 9, 11, 9)
        s = QLabel(
            "<b>Security audit records are not affected.</b><br>"
            "Audit data is stored separately and is intentionally excluded.",
            objectName="SafeText",
        )
        s.setWordWrap(True)
        sb.addWidget(s)

        bb.addWidget(warning)
        bb.addWidget(safe)
        bb.addStretch(1)
        root.addWidget(body, 1)

        footer = QFrame(objectName="DialogFooter")
        fr = QHBoxLayout(footer)
        fr.setContentsMargins(19, 10, 19, 14)
        fr.addStretch(1)

        cancel = QPushButton("Cancel", objectName="DialogSecondary")
        clear = QPushButton("Clear Diagnostic Logs", objectName="DialogDanger")
        cancel.clicked.connect(self.reject)
        clear.clicked.connect(self.accept)
        fr.addWidget(cancel)
        fr.addWidget(clear)
        root.addWidget(footer)


class ApplicationDiagnosticsPageQt6(QWidget):
    toast_requested = pyqtSignal(str, str)

    def __init__(self, user: dict | None = None, actor=None, parent=None):
        super().__init__(parent)
        self.user = user or {}
        self.actor = str(
            actor
            or self.user.get("username")
            or self.user.get("name")
            or "unknown"
        )

        self.pool = QtCore.QThreadPool.globalInstance()
        self._workers = set()
        self._busy = False
        self._active_stage = "overview"
        self._snapshot: Dict = {}
        self._last_log_lines: List[str] = []

        self.setObjectName("ApplicationDiagnosticsPageQt6")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.filter_timer = QtCore.QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(140)
        self.filter_timer.timeout.connect(self.refresh_logs_only)

        self._build()
        self._apply_style()
        self._show_stage("overview")

        QtCore.QTimer.singleShot(0, self.activate)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        kpis = QGridLayout()
        kpis.setSpacing(9)

        self.platform_card = KpiCard("Platform", "platform", "blue")
        self.python_card = KpiCard("Python Runtime", "python", "purple")
        self.gpu_card = KpiCard("GPU / CUDA", "gpu", "green")
        self.packages_card = KpiCard("Tracked Packages", "packages", "amber")

        for col, card in enumerate(
            (
                self.platform_card,
                self.python_card,
                self.gpu_card,
                self.packages_card,
            )
        ):
            kpis.addWidget(card, 0, col)
            kpis.setColumnStretch(col, 1)

        root.addLayout(kpis)

        work = QHBoxLayout()
        work.setSpacing(10)

        rail = QFrame(objectName="DiagnosticsRail")
        rail.setFixedWidth(220)
        rb = QVBoxLayout(rail)
        rb.setContentsMargins(11, 11, 11, 11)
        rb.setSpacing(7)
        rb.addWidget(QLabel("DIAGNOSTICS", objectName="RailEyebrow"))

        self.rail_buttons = {}
        for key, text, icon in (
            ("overview", "Overview", "overview"),
            ("logs", "Application Logs", "logs"),
            ("support", "Support Report", "support"),
            ("runtime", "Runtime Details", "runtime"),
        ):
            button = RailButton(key, text, icon)
            button.clicked.connect(
                lambda checked=False, stage=key: self._show_stage(stage)
            )
            rb.addWidget(button)
            self.rail_buttons[key] = button
        rb.addStretch(1)

        work.addWidget(rail)

        card = QFrame(objectName="WorkspaceCard")
        cb = QVBoxLayout(card)
        cb.setContentsMargins(0, 0, 0, 0)
        cb.setSpacing(0)

        header = QFrame(objectName="WorkspaceHeader")
        hb = QHBoxLayout(header)
        hb.setContentsMargins(14, 10, 14, 10)

        copy = QVBoxLayout()
        copy.setSpacing(2)
        self.stage_title = QLabel("Diagnostics Overview", objectName="WorkspaceTitle")
        self.stage_subtitle = QLabel(
            "Current application state and recent diagnostic indicators.",
            objectName="WorkspaceSubtitle",
        )
        copy.addWidget(self.stage_title)
        copy.addWidget(self.stage_subtitle)

        self.stage_badge = QLabel("OVERVIEW", objectName="StageBadge")
        hb.addLayout(copy, 1)
        hb.addWidget(self.stage_badge)
        cb.addWidget(header)

        self.stack = QStackedWidget()
        self.overview_page = self._build_overview()
        self.logs_page = self._build_logs()
        self.support_page = self._build_support()
        self.runtime_page = self._build_runtime()

        for page in (
            self.overview_page,
            self.logs_page,
            self.support_page,
            self.runtime_page,
        ):
            self.stack.addWidget(page)

        cb.addWidget(self.stack, 1)

        footer = QFrame(objectName="WorkspaceFooter")
        fb = QHBoxLayout(footer)
        fb.setContentsMargins(13, 9, 13, 9)

        self.footer_text = QLabel(
            "Review current application health and recent diagnostic indicators.",
            objectName="FooterText",
        )
        self.busy_text = QLabel("", objectName="BusyText")
        fb.addWidget(self.footer_text)
        fb.addStretch(1)
        fb.addWidget(self.busy_text)
        cb.addWidget(footer)

        work.addWidget(card, 1)
        root.addLayout(work, 1)

    def _build_overview(self):
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(14, 14, 14, 14)
        grid.setSpacing(11)

        health = self._panel(
            "Application Health",
            "Current runtime checks without starting camera, PLC or AI workloads.",
        )
        hb = health.layout()

        self.health_runtime = StatusRow("Application runtime")
        self.health_database = StatusRow("Database connectivity")
        self.health_logs = StatusRow("Log directory")
        self.health_audit = StatusRow("Audit integrity")
        self.health_crash = StatusRow("Crash handler")

        for row in (
            self.health_runtime,
            self.health_database,
            self.health_logs,
            self.health_audit,
            self.health_crash,
        ):
            hb.addWidget(row)

        self.refresh_diagnostics_btn = TiltIconButton(
            "Refresh Diagnostics",
            "refresh",
            primary=True,
        )
        self.refresh_diagnostics_btn.setObjectName("PrimaryIconButton")
        self.refresh_diagnostics_btn.setMinimumWidth(160)
        self.refresh_diagnostics_btn.clicked.connect(self.refresh_all)
        hb.addWidget(self.refresh_diagnostics_btn)
        hb.addStretch(1)

        events = self._panel(
            "Recent Events",
            "High-signal warnings and failures from the current application logs.",
        )
        eb = events.layout()

        self.event_cards = []
        for _ in range(3):
            frame = QFrame(objectName="EventCard")
            fb = QVBoxLayout(frame)
            fb.setContentsMargins(10, 8, 10, 8)
            fb.setSpacing(2)
            title = QLabel("No recent event", objectName="EventTitle")
            text = QLabel("No warning/error event loaded.", objectName="EventText")
            text.setWordWrap(True)
            fb.addWidget(title)
            fb.addWidget(text)
            eb.addWidget(frame)
            self.event_cards.append((title, text))

        open_logs = TiltIconButton("Open Application Logs", "logs")
        open_logs.setObjectName("SecondaryIconButton")
        open_logs.setMinimumWidth(160)
        open_logs.clicked.connect(lambda: self._show_stage("logs"))
        eb.addWidget(open_logs)
        eb.addStretch(1)

        grid.addWidget(health, 0, 0)
        grid.addWidget(events, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(1, 1)
        return page

    def _build_logs(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(14, 14, 14, 14)
        box.setSpacing(9)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(7)

        self.log_search = QLineEdit(objectName="SearchEdit")
        self.log_search.setPlaceholderText("Search log text...")
        self.log_search.setClearButtonEnabled(True)
        self.log_search.textChanged.connect(lambda _value: self.filter_timer.start())

        self.level_combo = ChevronComboBox(objectName="FilterCombo")
        self.level_combo.setMinimumWidth(135)
        self.level_combo.addItems(
            ["ALL", "CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]
        )
        self.level_combo.currentTextChanged.connect(
            lambda _value: self.filter_timer.start()
        )

        self.apply_log_filter_btn = TiltIconButton("Refresh", "refresh")
        self.apply_log_filter_btn.setObjectName("SecondaryIconButton")
        self.apply_log_filter_btn.setMinimumWidth(105)
        self.apply_log_filter_btn.clicked.connect(self.refresh_logs_only)

        toolbar.addWidget(self.log_search, 1)
        toolbar.addWidget(self.level_combo)
        toolbar.addWidget(self.apply_log_filter_btn)
        box.addLayout(toolbar)

        self.log_table = QTableWidget(0, 4)
        self.log_table.setObjectName("LogTable")
        self.log_table.setHorizontalHeaderLabels(
            ["TIME", "LEVEL", "MODULE", "MESSAGE"]
        )
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.log_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.log_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.log_table.setShowGrid(False)
        self.log_table.setAlternatingRowColors(False)
        self.log_table.setWordWrap(False)
        self.log_table.setFont(_mono_font())
        self.log_table.setMinimumHeight(280)

        header = self.log_table.horizontalHeader()
        header.setMinimumHeight(34)
        header.setHighlightSections(False)
        for col in range(4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)

        box.addWidget(self.log_table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(7)

        self.log_count = QLabel("0 records", objectName="LogCount")
        actions.addWidget(self.log_count)
        actions.addStretch(1)

        open_folder = TiltIconButton("Open Log Folder", "folder")
        open_folder.setObjectName("SecondaryIconButton")
        open_folder.setMinimumWidth(135)
        open_folder.clicked.connect(self.open_log_folder)

        export_log = TiltIconButton("Export Filtered Log", "export")
        export_log.setObjectName("SecondaryIconButton")
        export_log.setMinimumWidth(145)
        export_log.clicked.connect(self.export_filtered_log)

        clear_logs = TiltIconButton(
            "Clear Diagnostic Logs",
            "clear",
            danger=True,
        )
        clear_logs.setObjectName("DangerIconButton")
        clear_logs.setMinimumWidth(155)
        clear_logs.clicked.connect(self.clear_logs)

        actions.addWidget(open_folder)
        actions.addWidget(export_log)
        actions.addWidget(clear_logs)
        box.addLayout(actions)
        return page

    def _build_support(self):
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(14, 14, 14, 14)
        grid.setSpacing(11)

        report = self._panel(
            "Support Report",
            "Create a diagnostic package for troubleshooting and support review.",
        )
        rb = report.layout()

        for title, text in (
            ("Application logs", "Recent application logs and crash records."),
            (
                "Runtime details",
                "OS, Python, application runtime, GPU/CUDA availability and storage context.",
            ),
            (
                "Configuration summary",
                "Diagnostic configuration information with sensitive values excluded.",
            ),
        ):
            frame = QFrame(objectName="ReportCard")
            fb = QVBoxLayout(frame)
            fb.setContentsMargins(10, 8, 10, 8)
            fb.setSpacing(2)
            fb.addWidget(QLabel(title, objectName="ReportTitle"))
            body = QLabel(text, objectName="ReportText")
            body.setWordWrap(True)
            fb.addWidget(body)
            rb.addWidget(frame)

        buttons = QHBoxLayout()
        self.copy_report_btn = TiltIconButton(
            "Copy Support Report",
            "copy",
        )
        self.copy_report_btn.setObjectName("SecondaryIconButton")
        self.copy_report_btn.setMinimumWidth(160)
        self.copy_report_btn.clicked.connect(self.copy_report)

        self.export_report_btn = TiltIconButton(
            "Export Support Report",
            "support",
            primary=True,
        )
        self.export_report_btn.setObjectName("PrimaryIconButton")
        self.export_report_btn.setMinimumWidth(170)
        self.export_report_btn.clicked.connect(self.export_report)

        buttons.addWidget(self.copy_report_btn)
        buttons.addWidget(self.export_report_btn)
        buttons.addStretch(1)
        rb.addLayout(buttons)
        rb.addStretch(1)

        privacy = self._panel(
            "Privacy & Redaction",
            "Support output remains useful without exposing secret material.",
        )
        pb = privacy.layout()

        for caption, value, kind in (
            ("Passwords / secrets", "REDACTED", "green"),
            ("Authentication tokens", "REDACTED", "green"),
            ("Environment secrets", "REDACTED", "green"),
            ("Application paths", "REVIEWED", "amber"),
            ("Production images", "NOT INCLUDED", "green"),
            ("Security audit records", "SEPARATE", "blue"),
        ):
            row = StatusRow(caption)
            row.set_state(value, kind)
            pb.addWidget(row)

        note = QLabel(
            "The support-report backend performs the application's existing "
            "redaction. This page does not include production images and does "
            "not clear security audit records.",
            objectName="PrivacyNote",
        )
        note.setWordWrap(True)
        pb.addWidget(note)
        pb.addStretch(1)

        grid.addWidget(report, 0, 0)
        grid.addWidget(privacy, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(1, 1)
        return page

    def _build_runtime(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(14, 14, 14, 14)
        box.setSpacing(11)

        metrics = QGridLayout()
        metrics.setSpacing(9)

        self.runtime_os = MetricBox("OS")
        self.runtime_python = MetricBox("Python")
        self.runtime_qt = MetricBox("Qt")
        self.runtime_torch = MetricBox("Torch")
        self.runtime_cuda = MetricBox("CUDA")
        self.runtime_gpu = MetricBox("GPU")

        for idx, metric in enumerate(
            (
                self.runtime_os,
                self.runtime_python,
                self.runtime_qt,
                self.runtime_torch,
                self.runtime_cuda,
                self.runtime_gpu,
            )
        ):
            metrics.addWidget(metric, idx // 3, idx % 3)

        box.addLayout(metrics)

        paths = self._panel(
            "Runtime Paths",
            "Useful local paths for troubleshooting.",
        )
        pb = paths.layout()

        self.path_app = StatusRow("Application root")
        self.path_data = StatusRow("Runtime data")
        self.path_logs = StatusRow("Logs")
        self.path_reports = StatusRow("Reports")

        for row in (
            self.path_app,
            self.path_data,
            self.path_logs,
            self.path_reports,
        ):
            pb.addWidget(row)

        buttons = QHBoxLayout()
        open_data = TiltIconButton("Open Data Folder", "folder")
        open_data.setObjectName("SecondaryIconButton")
        open_data.setMinimumWidth(135)
        open_data.clicked.connect(self.open_data_folder)

        copy_summary = TiltIconButton("Copy Runtime Summary", "copy")
        copy_summary.setObjectName("SecondaryIconButton")
        copy_summary.setMinimumWidth(155)
        copy_summary.clicked.connect(self.copy_runtime_summary)

        buttons.addWidget(open_data)
        buttons.addWidget(copy_summary)
        buttons.addStretch(1)
        pb.addLayout(buttons)
        pb.addStretch(1)

        box.addWidget(paths)
        box.addStretch(1)
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

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def _show_stage(self, stage):
        mapping = {
            "overview": self.overview_page,
            "logs": self.logs_page,
            "support": self.support_page,
            "runtime": self.runtime_page,
        }
        if stage not in mapping:
            return

        self._active_stage = stage
        self.stack.setCurrentWidget(mapping[stage])

        meta = {
            "overview": (
                "Diagnostics Overview",
                "Current application state and recent diagnostic indicators.",
                "OVERVIEW",
                "Review current application health and recent diagnostic indicators.",
            ),
            "logs": (
                "Application Logs",
                "Search, filter and review application log output.",
                "LOGS",
                "Use the log view to isolate warnings, errors and recent failures.",
            ),
            "support": (
                "Support Report",
                "Create a redacted diagnostic package for support review.",
                "SUPPORT",
                "Generate support evidence without exposing secret material.",
            ),
            "runtime": (
                "Runtime Details",
                "Review application, Python, GPU and local runtime context.",
                "RUNTIME",
                "Use runtime information when reproducing environment-specific issues.",
            ),
        }[stage]

        self.stage_title.setText(meta[0])
        self.stage_subtitle.setText(meta[1])
        self.stage_badge.setText(meta[2])
        self.footer_text.setText(meta[3])

        for key, button in self.rail_buttons.items():
            button.setChecked(key == stage)

        if stage == "logs":
            self.refresh_logs_only()

    # ------------------------------------------------------------------
    # Worker helper
    # ------------------------------------------------------------------
    def _run(self, operation, success, busy_text="Working…"):
        self._set_busy(True, busy_text)
        worker = Worker(operation)
        self._workers.add(worker)

        def completed(result):
            self._workers.discard(worker)
            self._set_busy(False)
            success(result)

        def failed(message):
            self._workers.discard(worker)
            self._set_busy(False)
            QMessageBox.critical(
                self,
                "Diagnostics operation failed",
                str(message),
            )

        worker.signals.completed.connect(completed)
        worker.signals.failed.connect(failed)
        self.pool.start(worker)

    def _set_busy(self, busy: bool, text=""):
        self._busy = bool(busy)
        self.busy_text.setText(text if busy else "")
        for button in (
            self.refresh_diagnostics_btn,
            self.apply_log_filter_btn,
            self.copy_report_btn,
            self.export_report_btn,
        ):
            button.setEnabled(not busy)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------
    def activate(self):
        self.refresh_all()

    def refresh_context(self):
        self.refresh_all()

    def refresh_all(self):
        self._run(
            self._collect_snapshot,
            self._apply_snapshot,
            "Refreshing diagnostics…",
        )

    @staticmethod
    def _collect_snapshot():
        snapshot = system_snapshot()

        health = {
            "runtime": {
                "text": "HEALTHY",
                "kind": "green",
            },
            "database": {
                "text": "UNKNOWN",
                "kind": "amber",
            },
            "logs": {
                "text": "UNKNOWN",
                "kind": "amber",
            },
            "audit": {
                "text": "UNKNOWN",
                "kind": "amber",
            },
            "crash": {
                "text": "ACTIVE"
                if sys.excepthook is not sys.__excepthook__
                else "DEFAULT",
                "kind": "green"
                if sys.excepthook is not sys.__excepthook__
                else "amber",
            },
        }

        try:
            mongo.require_available()
            health["database"] = {"text": "ONLINE", "kind": "green"}
        except Exception:
            health["database"] = {"text": "OFFLINE", "kind": "red"}

        try:
            cfg = get_config()
            log_dir = Path(cfg.data_dir) / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            probe = log_dir / ".eyres_diag_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            health["logs"] = {"text": "WRITABLE", "kind": "green"}
        except Exception:
            health["logs"] = {"text": "NOT WRITABLE", "kind": "red"}

        try:
            valid, _message, _count = verify_audit_integrity()
            health["audit"] = {
                "text": "VERIFIED" if valid else "CHECK",
                "kind": "green" if valid else "red",
            }
        except Exception:
            health["audit"] = {"text": "UNAVAILABLE", "kind": "amber"}

        recent = recent_log_entries("ALL", "", 200)
        return {
            "snapshot": snapshot,
            "health": health,
            "recent": list(recent or []),
        }

    def _apply_snapshot(self, payload):
        self._snapshot = dict(payload.get("snapshot") or {})
        health = payload.get("health") or {}
        recent = list(payload.get("recent") or [])

        self._update_kpis(self._snapshot)
        self._update_runtime_details(self._snapshot)

        for key, row in (
            ("runtime", self.health_runtime),
            ("database", self.health_database),
            ("logs", self.health_logs),
            ("audit", self.health_audit),
            ("crash", self.health_crash),
        ):
            state = health.get(key, {})
            row.set_state(
                state.get("text", "UNKNOWN"),
                state.get("kind", "amber"),
            )

        self._update_recent_events(recent)
        self.refresh_logs_only()

        self.toast_requested.emit(
            "Diagnostics refreshed",
            "Runtime and diagnostic indicators were refreshed.",
        )

    def _update_kpis(self, snapshot: Dict):
        platform_raw = str(snapshot.get("platform") or platform.platform() or "Unknown")
        python_version = str(snapshot.get("python") or platform.python_version() or "Unknown")
        gpu = snapshot.get("gpu") or {}
        packages = snapshot.get("packages") or {}

        self.platform_card.set_data(
            _friendly_platform(platform_raw),
            platform_raw,
        )
        self.python_card.set_data(
            f"Python {python_version}",
            "Application runtime",
        )

        cuda_available = bool(gpu.get("cuda_available"))
        gpu_name = str(
            gpu.get("device")
            or ("CUDA device" if cuda_available else "No CUDA device")
        )
        cuda_version = gpu.get("cuda_version")
        self.gpu_card.set_data(
            gpu_name,
            (
                f"CUDA {cuda_version}"
                if cuda_available and cuda_version
                else ("CUDA available" if cuda_available else "CUDA unavailable")
            ),
        )

        package_names = list(packages.keys())
        self.packages_card.set_data(
            f"{len(package_names)} packages",
            " · ".join(package_names[:4]) or "Tracked runtime packages",
        )

    def _update_runtime_details(self, snapshot: Dict):
        gpu = snapshot.get("gpu") or {}
        packages = snapshot.get("packages") or {}

        self.runtime_os.value.setText(
            _friendly_platform(str(snapshot.get("platform") or platform.platform()))
        )
        self.runtime_python.value.setText(
            str(snapshot.get("python") or platform.python_version())
        )
        self.runtime_qt.value.setText(
            str(getattr(QtCore, "PYQT_VERSION_STR", "PyQt6"))
        )

        torch_version = (
            packages.get("torch")
            or packages.get("Torch")
            or snapshot.get("torch")
            or "—"
        )
        self.runtime_torch.value.setText(str(torch_version))
        self.runtime_cuda.value.setText(
            str(gpu.get("cuda_version") or ("Available" if gpu.get("cuda_available") else "Unavailable"))
        )
        self.runtime_gpu.value.setText(str(gpu.get("device") or "No CUDA device"))

        cfg = get_config()
        data_dir = Path(cfg.data_dir)
        log_dir = data_dir / "logs"
        reports_dir = _root() / "reports"

        self.path_app.set_state(str(_root()), "blue")
        self.path_data.set_state(str(data_dir), "blue")
        self.path_logs.set_state(str(log_dir), "blue")
        self.path_reports.set_state(str(reports_dir), "blue")

    def _update_recent_events(self, lines: List[str]):
        parsed = []
        for raw in reversed(lines):
            ts, level, module, message = _parse_log_line(raw)
            if level in {"CRITICAL", "ERROR", "WARNING"}:
                parsed.append((level, module or "application", message or raw))
            if len(parsed) >= 3:
                break

        while len(parsed) < 3:
            parsed.append(
                ("INFO", "application", "No additional warning/error event in the recent log window.")
            )

        for (title, text), (level, module, message) in zip(self.event_cards, parsed):
            title.setText(f"{level.title()} · {module}")
            text.setText(str(message))

    # ------------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------------
    def refresh_logs_only(self):
        try:
            lines = recent_log_entries(
                self.level_combo.currentText(),
                self.log_search.text(),
                1000,
            )
            self._last_log_lines = list(lines or [])
            self._populate_logs(self._last_log_lines)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Log refresh failed",
                str(exc),
            )

    def _populate_logs(self, lines: List[str]):
        self.log_table.setUpdatesEnabled(False)
        try:
            self.log_table.setRowCount(len(lines))

            level_colors = {
                "CRITICAL": QtGui.QColor("#FF7A88"),
                "ERROR": QtGui.QColor("#FF7A88"),
                "WARNING": QtGui.QColor("#F5BE68"),
                "INFO": QtGui.QColor("#73A1FF"),
                "DEBUG": QtGui.QColor("#9DABC0"),
            }

            for row, raw in enumerate(lines):
                timestamp, level, module, message = _parse_log_line(raw)
                values = (timestamp, level, module, message)
                colors = (
                    QtGui.QColor("#8798B4"),
                    level_colors.get(level, QtGui.QColor("#73A1FF")),
                    QtGui.QColor("#AAB7CC"),
                    QtGui.QColor("#E7EDF7"),
                )

                for col, (value, color) in enumerate(zip(values, colors)):
                    item = QTableWidgetItem(str(value))
                    item.setForeground(color)
                    item.setFont(_mono_font())
                    if col == 1:
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                    item.setToolTip(str(raw))
                    self.log_table.setItem(row, col, item)
                self.log_table.setRowHeight(row, 29)

            self.log_count.setText(
                f"{len(lines)} record{'s' if len(lines) != 1 else ''}"
            )
            self._resize_log_columns()
        finally:
            self.log_table.setUpdatesEnabled(True)
            self.log_table.viewport().update()

    def open_log_folder(self):
        path = Path(get_config().data_dir) / "logs"
        path.mkdir(parents=True, exist_ok=True)
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(path))
        )

    def export_filtered_log(self):
        if not self._last_log_lines:
            QMessageBox.information(
                self,
                "No diagnostic records",
                "There are no filtered diagnostic records to export.",
            )
            return

        default = _root() / (
            f"diagnostic_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Filtered Diagnostic Log",
            str(default),
            "Text Files (*.txt)",
        )
        if not filename:
            return

        try:
            Path(filename).write_text(
                "\n".join(self._last_log_lines) + "\n",
                encoding="utf-8",
            )
            self.toast_requested.emit(
                "Diagnostic log exported",
                Path(filename).name,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export failed",
                str(exc),
            )

    def clear_logs(self):
        dialog = ClearLogsDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            count = clear_diagnostic_logs()
            record_audit_event(
                "diagnostic_logs_cleared",
                actor=self.actor,
                details={"files": count},
            )
            self.refresh_logs_only()
            self.toast_requested.emit(
                "Diagnostic logs cleared",
                f"{count} operational log file(s) cleared; security audit records preserved.",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Logs were not cleared",
                str(exc),
            )

    # ------------------------------------------------------------------
    # Support report
    # ------------------------------------------------------------------
    def copy_report(self):
        try:
            text = json.dumps(build_support_report(), indent=2)
            QApplication.clipboard().setText(text)
            record_audit_event(
                "support_report_copied",
                actor=self.actor,
            )
            self.toast_requested.emit(
                "Support report copied",
                "Redacted support data was copied to the clipboard.",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Copy failed",
                str(exc),
            )

    def export_report(self):
        try:
            path = export_support_report()
            record_audit_event(
                "support_report_exported",
                actor=self.actor,
                details={"file": path.name},
            )
            self.toast_requested.emit(
                "Support report exported",
                path.name,
            )
            QMessageBox.information(
                self,
                "Support report exported",
                f"Privacy-safe support report exported successfully.\n\n{path}",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export failed",
                str(exc),
            )

    # ------------------------------------------------------------------
    # Runtime tools
    # ------------------------------------------------------------------
    def open_data_folder(self):
        path = Path(get_config().data_dir)
        path.mkdir(parents=True, exist_ok=True)
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(path))
        )

    def copy_runtime_summary(self):
        snapshot = self._snapshot or {}
        payload = {
            "platform": snapshot.get("platform"),
            "python": snapshot.get("python"),
            "gpu": snapshot.get("gpu"),
            "packages": snapshot.get("packages"),
            "application_root": str(_root()),
            "data_dir": str(get_config().data_dir),
        }
        QApplication.clipboard().setText(
            json.dumps(payload, indent=2, default=str)
        )
        self.toast_requested.emit(
            "Runtime summary copied",
            "Runtime details were copied to the clipboard.",
        )

    # ------------------------------------------------------------------
    # Layout / lifecycle
    # ------------------------------------------------------------------
    def _resize_log_columns(self):
        width = self.log_table.viewport().width()
        if width <= 0:
            return

        time_width = max(155, min(185, int(width * 0.17)))
        level_width = 86
        module_width = max(145, min(190, int(width * 0.18)))
        message_width = max(
            280,
            width - time_width - level_width - module_width - 8,
        )

        self.log_table.setColumnWidth(0, time_width)
        self.log_table.setColumnWidth(1, level_width)
        self.log_table.setColumnWidth(2, module_width)
        self.log_table.setColumnWidth(3, message_width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_log_columns()

    def shutdown(self):
        pass

    def _apply_style(self):
        self.setStyleSheet(PAGE_QSS)


PAGE_QSS = """
QWidget#ApplicationDiagnosticsPageQt6 {
    background:#EAF1F8;
    color:#101A2D;
}
QWidget#ApplicationDiagnosticsPageQt6 QLabel {
    background:transparent;
    border:0;
}

QFrame#KpiCard {
    background:#FFFFFF;
    border:1px solid #AFC1D4;
    border-radius:12px;
}
QFrame#KpiCard:hover {
    border-color:#8EACD0;
}
QLabel#KpiCaption {
    color:#60728A;
    font-size:7.8px;
    font-weight:850;
    letter-spacing:.55px;
}
QLabel#KpiValue {
    color:#101A2D;
    font-size:16px;
    font-weight:850;
}
QLabel#KpiMeta {
    color:#718197;
    font-size:7.8px;
}
QLabel#KpiIcon {
    border-radius:10px;
}
QLabel#KpiIcon[kind="blue"] {
    background:#E8F1FF;
}
QLabel#KpiIcon[kind="green"] {
    background:#E8F8F1;
}
QLabel#KpiIcon[kind="amber"] {
    background:#FFF5D9;
}
QLabel#KpiIcon[kind="purple"] {
    background:#F2EDFF;
}

QFrame#DiagnosticsRail,
QFrame#WorkspaceCard {
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
QPushButton#DiagnosticsRailButton {
    min-height:50px;
    background:#FFFFFF;
    color:#405873;
    border:1px solid #AFC1D4;
    border-radius:10px;
    padding:0 12px;
    text-align:left;
    font-size:9.3px;
    font-weight:760;
}
QPushButton#DiagnosticsRailButton:hover {
    background:#F0F5FF;
    border-color:#8EACD0;
    color:#2868E8;
}
QPushButton#DiagnosticsRailButton:checked {
    background:#E8F1FF;
    border-color:#2868E8;
    color:#1D5BD0;
}

QFrame#WorkspaceHeader {
    background:#FFFFFF;
    border:0;
    border-bottom:1px solid #CBD7E4;
}
QFrame#WorkspaceFooter {
    background:#FCFDFE;
    border:0;
    border-top:1px solid #CBD7E4;
}
QLabel#WorkspaceTitle {
    color:#17263D;
    font-size:14px;
    font-weight:850;
}
QLabel#WorkspaceSubtitle,
QLabel#FooterText {
    color:#60728A;
    font-size:8.8px;
    font-weight:600;
}
QLabel#BusyText {
    color:#2868E8;
    font-size:8.5px;
    font-weight:760;
}
QLabel#StageBadge {
    color:#566A82;
    background:#F1F5FA;
    border:1px solid #D5DFE9;
    border-radius:10px;
    padding:5px 9px;
    font-size:7.7px;
    font-weight:850;
}

QFrame#Panel {
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
    font-size:8.6px;
    font-weight:600;
}

QFrame#StatusRow {
    min-height:44px;
    max-height:44px;
    background:#FFFFFF;
    border:1px solid #C3D1E2;
    border-radius:9px;
}
QLabel#StatusCaption {
    color:#17263D;
    font-size:8.8px;
    font-weight:760;
}
QLabel#StatusValue {
    min-height:21px;
    max-height:21px;
    border-radius:10px;
    padding:0 7px;
    font-size:7.4px;
    font-weight:850;
}
QLabel#StatusValue[kind="green"] {
    color:#07965D;
    background:#E8F8F1;
}
QLabel#StatusValue[kind="amber"] {
    color:#A66300;
    background:#FFF5D9;
}
QLabel#StatusValue[kind="red"] {
    color:#C93450;
    background:#FFF0F3;
}
QLabel#StatusValue[kind="blue"] {
    color:#2868E8;
    background:#E8F1FF;
}

QFrame#EventCard,
QFrame#ReportCard {
    background:#FFFFFF;
    border:1px solid #C3D1E2;
    border-radius:9px;
}
QLabel#EventTitle,
QLabel#ReportTitle {
    color:#17263D;
    font-size:8.9px;
    font-weight:820;
}
QLabel#EventText,
QLabel#ReportText {
    color:#65778D;
    font-size:8px;
}

QPushButton#PrimaryIconButton {
    background:#2868E8;
    color:#FFFFFF;
    border:1px solid #2868E8;
    border-radius:9px;
    padding:0 12px;
    text-align:left;
    font-size:9px;
    font-weight:800;
}
QPushButton#PrimaryIconButton:hover {
    background:#1F58CC;
    border-color:#1F58CC;
}
QPushButton#SecondaryIconButton {
    background:#FFFFFF;
    color:#2868E8;
    border:1px solid #A6BBD1;
    border-radius:9px;
    padding:0 12px;
    text-align:left;
    font-size:8.9px;
    font-weight:760;
}
QPushButton#SecondaryIconButton:hover {
    background:#EEF4FF;
}
QPushButton#DangerIconButton {
    background:#FFF9FA;
    color:#C93450;
    border:1px solid #DDAAB4;
    border-radius:9px;
    padding:0 12px;
    text-align:left;
    font-size:8.9px;
    font-weight:760;
}
QPushButton#DangerIconButton:hover {
    background:#FFF0F3;
}
QPushButton#PrimaryIconButton:disabled,
QPushButton#SecondaryIconButton:disabled {
    background:#F1F4F8;
    color:#9AA7B7;
    border-color:#DCE3EC;
}

QLineEdit#SearchEdit,
QComboBox#FilterCombo {
    min-height:35px;
    max-height:35px;
    background:#FFFFFF;
    color:#17263D;
    border:1px solid #A6BBD1;
    border-radius:8px;
    padding:0 30px 0 9px;
    font-size:9.2px;
    font-weight:650;
}
QLineEdit#SearchEdit {
    padding-right:9px;
}
QLineEdit#SearchEdit:focus,
QComboBox#FilterCombo:focus {
    border-color:#2868E8;
}
QComboBox#FilterCombo::drop-down {
    border:0;
    width:30px;
}
QComboBox#FilterCombo::down-arrow {
    image:none;
    width:0;
    height:0;
}
QLabel#ComboChevron {
    background:transparent;
    border:0;
}

QTableWidget#LogTable {
    background:#07111E;
    color:#DDE8F5;
    border:1px solid #1D2B3C;
    border-radius:10px;
    gridline-color:#132033;
    selection-background-color:#0D1728;
    selection-color:#E7EDF7;
    outline:0;
}
QTableWidget#LogTable::item {
    border:0;
    padding:3px 7px;
}
QHeaderView::section {
    background:#0A1524;
    color:#8EA1BA;
    border:0;
    border-bottom:1px solid #1D2B3C;
    padding:0 7px;
    font-size:7.5px;
    font-weight:850;
}
QLabel#LogCount {
    color:#60728A;
    font-size:8.3px;
    font-weight:760;
}
QScrollBar:vertical {
    background:#07111E;
    width:9px;
    margin:2px;
}
QScrollBar::handle:vertical {
    background:#30405A;
    border-radius:4px;
    min-height:28px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height:0;
}
QScrollBar:horizontal {
    background:#07111E;
    height:9px;
    margin:2px;
}
QScrollBar::handle:horizontal {
    background:#30405A;
    border-radius:4px;
    min-width:28px;
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width:0;
}

QFrame#MetricBox {
    background:#FFFFFF;
    border:1px solid #C3D1E2;
    border-radius:9px;
}
QLabel#MetricCaption {
    color:#718197;
    font-size:7.3px;
    font-weight:850;
}
QLabel#MetricValue {
    color:#17263D;
    font-size:11.5px;
    font-weight:850;
}

QLabel#PrivacyNote {
    color:#60728A;
    background:#FFFFFF;
    border:1px solid #C3D1E2;
    border-radius:9px;
    padding:9px;
    font-size:8.2px;
}
"""


DIALOG_QSS = """
QDialog {
    background:#FFFFFF;
    color:#101A2D;
}
QDialog QLabel {
    background:transparent;
    border:0;
}
QFrame#DialogHeader {
    background:#FFFFFF;
    border:0;
    border-bottom:1px solid #CBD7E4;
}
QFrame#DialogFooter {
    background:#FFFFFF;
    border:0;
    border-top:1px solid #CBD7E4;
}
QLabel#DialogTitle {
    color:#101A2D;
    font-size:14px;
    font-weight:850;
}
QLabel#DialogSubtitle {
    color:#60728A;
    font-size:8.8px;
}
QFrame#WarningBox {
    background:#FFF0F3;
    border:1px solid #F2CDD3;
    border-radius:9px;
}
QFrame#SafeBox {
    background:#F7F9FD;
    border:1px solid #C3D1E2;
    border-radius:9px;
}
QLabel#WarningText {
    color:#6A3940;
    font-size:8.7px;
}
QLabel#SafeText {
    color:#58677E;
    font-size:8.7px;
}
QToolButton#DialogClose {
    background:#F0F3F7;
    color:#65748C;
    border:0;
    border-radius:8px;
    font-size:17px;
}
QPushButton#DialogSecondary,
QPushButton#DialogDanger {
    min-height:35px;
    border-radius:8px;
    padding:0 12px;
    font-size:8.8px;
    font-weight:780;
}
QPushButton#DialogSecondary {
    background:#FFFFFF;
    color:#405873;
    border:1px solid #A6BBD1;
}
QPushButton#DialogDanger {
    background:#FFF9FA;
    color:#C93450;
    border:1px solid #DDAAB4;
}
"""


DiagnosticsPageQt6 = ApplicationDiagnosticsPageQt6
DiagnosticsPage = ApplicationDiagnosticsPageQt6
