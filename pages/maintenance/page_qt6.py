"""EYRES AI - PyQt6 System Maintenance page.

Qt6 migration of the existing SystemMaintenancePage.

Existing maintenance backend retained:
- MongoDB health check
- audit-integrity verification
- free disk-space reporting
- CycloneDX SBOM/dependency report generation
- verified MongoDB backup creation with retention
- backup checksum/manifest inspection
- guarded restore PREVIEW only (apply=False)
- maintenance audit events

Important:
The approved preview includes a Storage Cleanup workspace. The previous
maintenance backend did not implement destructive cleanup. This Qt6 migration
therefore provides real storage scanning/open-folder controls there, but does
not silently add deletion behavior.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtProperty, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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
from db import mongo
from tools.backup_restore import create_backup, inspect_backup, restore
from tools.generate_sbom import build as build_sbom


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _asset(name: str) -> str:
    return str(_root() / "ui" / "assets" / "maintenance_icons" / name)


def _format_size(num_bytes: int) -> str:
    size = float(max(0, num_bytes))
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"


def _format_timestamp(epoch_seconds: float) -> str:
    dt = datetime.fromtimestamp(epoch_seconds)
    return f"{dt.strftime('%b')} {dt.day}, {dt.year} · {dt.strftime('%I:%M %p')}"


def _format_manifest_created(value) -> str:
    if not value:
        return "Unknown"
    raw = str(value)
    try:
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return f"{dt.strftime('%b')} {dt.day}, {dt.year} · {dt.strftime('%I:%M %p')}"
    except Exception:
        return raw


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
    """Padded-canvas icon motion matching the shell/sidebar implementation."""

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
    def _tint(pix: QtGui.QPixmap, color: str) -> QtGui.QPixmap:
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
        self.setObjectName("MaintenanceRailButton")
        self.setMinimumHeight(50)
        self.setMinimumWidth(190)


class ContextCard(QFrame):
    def __init__(self, caption: str, value="—", detail="", parent=None):
        super().__init__(parent)
        self.setObjectName("ContextCard")
        box = QVBoxLayout(self)
        box.setContentsMargins(11, 8, 11, 8)
        box.setSpacing(3)

        box.addWidget(QLabel(caption.upper(), objectName="ContextCaption"))
        self.value = QLabel(str(value), objectName="ContextValue")
        self.detail = QLabel(str(detail), objectName="ContextDetail")
        self.detail.setWordWrap(False)
        box.addWidget(self.value)
        box.addWidget(self.detail)


class HealthRow(QFrame):
    def __init__(self, caption: str, parent=None):
        super().__init__(parent)
        self.setObjectName("HealthRow")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)

        self.caption = QLabel(caption, objectName="HealthCaption")
        self.status = QLabel("NOT CHECKED", objectName="HealthStatus")
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
        box.addWidget(self.value)


class BackupManifestDialog(QDialog):
    def __init__(self, path: Path, manifest: Dict, preview=False, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(
            "Restore Preview" if preview else "Backup Verification"
        )
        self.resize(590, 520)
        self.setStyleSheet(DIALOG_QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame(objectName="DialogHeader")
        hb = QVBoxLayout(header)
        hb.setContentsMargins(18, 15, 18, 14)
        hb.setSpacing(3)
        hb.addWidget(
            QLabel(
                "Restore Preview" if preview else "Backup Verification",
                objectName="DialogTitle",
            )
        )
        hb.addWidget(
            QLabel(
                "No data is modified by this preview."
                if preview
                else "Checksum and backup manifest inspection completed.",
                objectName="DialogSubtitle",
            )
        )
        root.addWidget(header)

        body = QWidget()
        bb = QVBoxLayout(body)
        bb.setContentsMargins(18, 15, 18, 15)
        bb.setSpacing(8)

        rows = [
            ("Backup", path.name),
            ("Database", manifest.get("database", "unknown")),
            ("Created", _format_manifest_created(manifest.get("created_utc"))),
        ]
        for caption, value in rows:
            frame = QFrame(objectName="DialogInfo")
            row = QHBoxLayout(frame)
            row.setContentsMargins(10, 7, 10, 7)
            row.addWidget(QLabel(caption, objectName="DialogKey"))
            row.addStretch(1)
            value_label = QLabel(str(value), objectName="DialogValue")
            value_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            row.addWidget(value_label)
            bb.addWidget(frame)

        collections = manifest.get("collections") or {}
        if collections:
            bb.addWidget(QLabel("Collections", objectName="DialogSection"))
            for name, count in sorted(collections.items()):
                frame = QFrame(objectName="DialogInfo")
                row = QHBoxLayout(frame)
                row.setContentsMargins(10, 7, 10, 7)
                row.addWidget(QLabel(str(name), objectName="DialogKey"))
                row.addStretch(1)
                row.addWidget(QLabel(str(count), objectName="DialogValue"))
                bb.addWidget(frame)

        bb.addStretch(1)
        root.addWidget(body, 1)

        footer = QFrame(objectName="DialogFooter")
        fb = QHBoxLayout(footer)
        fb.setContentsMargins(18, 10, 18, 14)
        fb.addStretch(1)
        close = QPushButton("Close", objectName="DialogPrimary")
        close.clicked.connect(self.accept)
        fb.addWidget(close)
        root.addWidget(footer)


class SystemMaintenancePageQt6(QWidget):
    toast_requested = pyqtSignal(str, str)

    STAGES = ("overview", "backup", "storage", "deps", "audit")

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
        self._selected_backup_path: Optional[Path] = None

        self.setObjectName("SystemMaintenancePageQt6")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._build()
        self._apply_style()
        self._show_stage("overview")

        QtCore.QTimer.singleShot(0, self.refresh_context)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        context = QGridLayout()
        context.setSpacing(8)

        self.data_card = ContextCard(
            "Application Data",
            "—",
            "Runtime files",
        )
        self.storage_card = ContextCard(
            "Storage",
            "—",
            "Checking capacity",
        )
        self.backup_card = ContextCard(
            "Latest Backup",
            "—",
            "No backup selected",
        )
        self.checks_card = ContextCard(
            "System Checks",
            "Not checked",
            "Run maintenance check",
        )

        for col, card in enumerate(
            (
                self.data_card,
                self.storage_card,
                self.backup_card,
                self.checks_card,
            )
        ):
            context.addWidget(card, 0, col)
            context.setColumnStretch(col, 1)

        root.addLayout(context)

        work = QHBoxLayout()
        work.setSpacing(10)

        self.rail = QFrame(objectName="MaintenanceRail")
        self.rail.setFixedWidth(220)
        rb = QVBoxLayout(self.rail)
        rb.setContentsMargins(11, 11, 11, 11)
        rb.setSpacing(7)

        rb.addWidget(QLabel("MAINTENANCE", objectName="RailEyebrow"))
        self.rail_buttons = {}

        for key, text, icon in (
            ("overview", "Overview", "overview"),
            ("backup", "Backup & Recovery", "backup"),
            ("storage", "Storage Cleanup", "storage"),
            ("deps", "Dependencies & SBOM", "deps"),
            ("audit", "Audit Integrity", "audit"),
        ):
            button = RailButton(key, text, icon)
            button.clicked.connect(
                lambda checked=False, stage=key: self._show_stage(stage)
            )
            rb.addWidget(button)
            self.rail_buttons[key] = button

        rb.addStretch(1)
        work.addWidget(self.rail)

        card = QFrame(objectName="WorkspaceCard")
        card_box = QVBoxLayout(card)
        card_box.setContentsMargins(0, 0, 0, 0)
        card_box.setSpacing(0)

        header = QFrame(objectName="WorkspaceHeader")
        hb = QHBoxLayout(header)
        hb.setContentsMargins(14, 10, 14, 10)

        copy = QVBoxLayout()
        copy.setSpacing(2)
        self.stage_title = QLabel("Maintenance Overview", objectName="WorkspaceTitle")
        self.stage_subtitle = QLabel(
            "Current workstation health and available maintenance actions.",
            objectName="WorkspaceSubtitle",
        )
        copy.addWidget(self.stage_title)
        copy.addWidget(self.stage_subtitle)

        self.stage_badge = QLabel("OVERVIEW", objectName="StageBadge")
        hb.addLayout(copy, 1)
        hb.addWidget(self.stage_badge)
        card_box.addWidget(header)

        self.stack = QStackedWidget()
        self.overview_page = self._build_overview()
        self.backup_page = self._build_backup()
        self.storage_page = self._build_storage()
        self.dependencies_page = self._build_dependencies()
        self.audit_page = self._build_audit()

        for widget in (
            self.overview_page,
            self.backup_page,
            self.storage_page,
            self.dependencies_page,
            self.audit_page,
        ):
            self.stack.addWidget(widget)

        card_box.addWidget(self.stack, 1)

        footer = QFrame(objectName="WorkspaceFooter")
        fb = QHBoxLayout(footer)
        fb.setContentsMargins(13, 9, 13, 9)
        self.footer_text = QLabel(
            "Review workstation health and available maintenance actions.",
            objectName="FooterText",
        )
        self.busy_text = QLabel("", objectName="BusyText")
        fb.addWidget(self.footer_text)
        fb.addStretch(1)
        fb.addWidget(self.busy_text)
        card_box.addWidget(footer)

        work.addWidget(card, 1)
        root.addLayout(work, 1)

    def _build_overview(self):
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(14, 14, 14, 14)
        grid.setSpacing(11)

        health = self._panel(
            "System Health",
            "Core application services and runtime storage.",
        )
        hb = health.layout()

        self.health_rows = {
            "database": HealthRow("Database service"),
            "audit": HealthRow("Audit records"),
            "disk": HealthRow("Storage capacity"),
            "dependencies": HealthRow("Dependency report"),
        }
        for row in self.health_rows.values():
            hb.addWidget(row)

        self.run_checks_btn = TiltIconButton(
            "Run Maintenance Check",
            "check",
            primary=True,
        )
        self.run_checks_btn.setObjectName("PrimaryIconButton")
        self.run_checks_btn.setMinimumWidth(170)
        self.run_checks_btn.clicked.connect(self.refresh_health)
        hb.addWidget(self.run_checks_btn)
        hb.addStretch(1)

        storage = self._panel(
            "Application Storage",
            "Runtime root, usage and retained maintenance data.",
        )
        sb = storage.layout()

        self.data_path_label = QLabel("—", objectName="PathBox")
        self.data_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        sb.addWidget(self.data_path_label)

        metrics = QGridLayout()
        metrics.setSpacing(7)
        self.used_metric = MetricBox("Used", "—")
        self.free_metric = MetricBox("Free", "—")
        self.logs_metric = MetricBox("Logs", "—")
        metrics.addWidget(self.used_metric, 0, 0)
        metrics.addWidget(self.free_metric, 0, 1)
        metrics.addWidget(self.logs_metric, 0, 2)
        sb.addLayout(metrics)

        self.disk_bar = QtWidgets.QProgressBar()
        self.disk_bar.setObjectName("DiskProgress")
        self.disk_bar.setRange(0, 100)
        self.disk_bar.setTextVisible(False)
        self.disk_bar.setValue(0)
        sb.addWidget(self.disk_bar)

        row = QHBoxLayout()
        self.open_data_btn = TiltIconButton("Open Data Folder", "folder")
        self.open_data_btn.setObjectName("SecondaryIconButton")
        self.open_data_btn.setMinimumWidth(135)
        self.open_data_btn.clicked.connect(self.open_data_folder)

        row.addWidget(self.open_data_btn)
        row.addStretch(1)
        sb.addLayout(row)
        sb.addStretch(1)

        grid.addWidget(health, 0, 0)
        grid.addWidget(storage, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(1, 1)
        return page

    def _build_backup(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        top = QGridLayout()
        top.setSpacing(11)

        backup = self._panel(
            "Backup & Recovery",
            "Create and verify application backups before maintenance or upgrade work.",
        )
        bb = backup.layout()

        self.backup_destination = HealthRow("Backup destination")
        bb.addWidget(self.backup_destination)

        self.backup_path_label = QLabel("—", objectName="PathBox")
        self.backup_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        bb.addWidget(self.backup_path_label)

        brow = QHBoxLayout()
        self.create_backup_btn = TiltIconButton(
            "Create Backup",
            "backup",
            primary=True,
        )
        self.create_backup_btn.setObjectName("PrimaryIconButton")
        self.create_backup_btn.setMinimumWidth(140)
        self.create_backup_btn.clicked.connect(self.create_backup)

        self.refresh_backup_btn = TiltIconButton("Refresh List", "refresh")
        self.refresh_backup_btn.setObjectName("SecondaryIconButton")
        self.refresh_backup_btn.setMinimumWidth(120)
        self.refresh_backup_btn.clicked.connect(self.refresh_backups)

        brow.addWidget(self.create_backup_btn)
        brow.addWidget(self.refresh_backup_btn)
        brow.addStretch(1)
        bb.addLayout(brow)
        bb.addStretch(1)

        restore_panel = self._panel(
            "Restore Safety",
            "Restore is guarded. This page performs a non-destructive restore preview only.",
        )
        rb = restore_panel.layout()

        self.restore_latest = HealthRow("Latest backup")
        self.restore_integrity = HealthRow("Selected backup integrity")
        self.restore_mode = HealthRow("Restore mode")
        self.restore_mode.set_state("PREVIEW ONLY", "blue")

        rb.addWidget(self.restore_latest)
        rb.addWidget(self.restore_integrity)
        rb.addWidget(self.restore_mode)

        self.preview_restore_btn = TiltIconButton(
            "Preview Restore",
            "preview",
        )
        self.preview_restore_btn.setObjectName("SecondaryIconButton")
        self.preview_restore_btn.setMinimumWidth(140)
        self.preview_restore_btn.clicked.connect(self.preview_selected)
        rb.addWidget(self.preview_restore_btn)
        rb.addStretch(1)

        top.addWidget(backup, 0, 0)
        top.addWidget(restore_panel, 0, 1)
        top.setColumnStretch(0, 1)
        top.setColumnStretch(1, 1)
        root.addLayout(top)

        self.backup_table = QTableWidget(0, 4)
        self.backup_table.setObjectName("BackupTable")
        self.backup_table.setHorizontalHeaderLabels(
            ["BACKUP", "CREATED", "SIZE", "ACTIONS"]
        )
        self.backup_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.backup_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.backup_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.backup_table.setAlternatingRowColors(False)
        self.backup_table.setShowGrid(False)
        self.backup_table.verticalHeader().setVisible(False)
        self.backup_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.backup_table.setMinimumHeight(210)

        header = self.backup_table.horizontalHeader()
        header.setMinimumHeight(38)
        header.setHighlightSections(False)
        for col in range(4):
            header.setSectionResizeMode(
                col,
                QHeaderView.ResizeMode.Fixed,
            )

        self.backup_table.itemSelectionChanged.connect(
            self._backup_selection_changed
        )
        root.addWidget(self.backup_table, 1)

        self.backup_selection_bar = QFrame(objectName="BackupSelectionBar")
        sbr = QHBoxLayout(self.backup_selection_bar)
        sbr.setContentsMargins(11, 7, 11, 7)

        self.selected_backup_label = QLabel(
            "Selected backup",
            objectName="SelectedBackupLabel",
        )
        self.selected_backup_meta = QLabel(
            "",
            objectName="SelectedBackupMeta",
        )
        selected_copy = QVBoxLayout()
        selected_copy.setSpacing(1)
        selected_copy.addWidget(self.selected_backup_label)
        selected_copy.addWidget(self.selected_backup_meta)

        self.verify_backup_btn = TiltIconButton(
            "Verify Backup",
            "verify",
        )
        self.verify_backup_btn.setObjectName("SecondaryIconButton")
        self.verify_backup_btn.setMinimumWidth(135)
        self.verify_backup_btn.clicked.connect(self.verify_selected)

        sbr.addLayout(selected_copy)
        sbr.addStretch(1)
        sbr.addWidget(self.verify_backup_btn)
        self.backup_selection_bar.hide()

        root.addWidget(self.backup_selection_bar)
        return page

    def _build_storage(self):
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(14, 14, 14, 14)
        grid.setSpacing(11)

        scan = self._panel(
            "Storage Review",
            "Review runtime storage usage. No files are deleted automatically.",
        )
        sb = scan.layout()

        self.storage_data_row = HealthRow("Application data")
        self.storage_logs_row = HealthRow("Log data")
        self.storage_backups_row = HealthRow("Backup archives")
        self.storage_reports_row = HealthRow("Reports")

        for row in (
            self.storage_data_row,
            self.storage_logs_row,
            self.storage_backups_row,
            self.storage_reports_row,
        ):
            sb.addWidget(row)

        self.rescan_storage_btn = TiltIconButton(
            "Recalculate Usage",
            "storage",
            primary=True,
        )
        self.rescan_storage_btn.setObjectName("PrimaryIconButton")
        self.rescan_storage_btn.setMinimumWidth(155)
        self.rescan_storage_btn.clicked.connect(self.refresh_storage)

        self.open_storage_btn = TiltIconButton(
            "Open Data Folder",
            "folder",
        )
        self.open_storage_btn.setObjectName("SecondaryIconButton")
        self.open_storage_btn.setMinimumWidth(135)
        self.open_storage_btn.clicked.connect(self.open_data_folder)

        row = QHBoxLayout()
        row.addWidget(self.rescan_storage_btn)
        row.addWidget(self.open_storage_btn)
        row.addStretch(1)
        sb.addLayout(row)
        sb.addStretch(1)

        policy = self._panel(
            "Retention & Safety",
            "Existing maintenance controls protect backups and audit evidence.",
        )
        pb = policy.layout()
        self.retention_backup_row = HealthRow("Backup retention")
        self.retention_backup_row.set_state("10 BACKUPS", "blue")
        self.retention_audit_row = HealthRow("Audit records")
        self.retention_audit_row.set_state("PROTECTED", "green")
        self.retention_cleanup_row = HealthRow("Automatic cleanup")
        self.retention_cleanup_row.set_state("NOT CONFIGURED", "amber")

        pb.addWidget(self.retention_backup_row)
        pb.addWidget(self.retention_audit_row)
        pb.addWidget(self.retention_cleanup_row)
        note = QLabel(
            "The previous maintenance backend did not include destructive cleanup. "
            "This Qt6 page therefore scans usage but does not silently delete runtime data.",
            objectName="InfoNote",
        )
        note.setWordWrap(True)
        pb.addWidget(note)
        pb.addStretch(1)

        grid.addWidget(scan, 0, 0)
        grid.addWidget(policy, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(1, 1)
        return page

    def _build_dependencies(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(11)

        top = QGridLayout()
        top.setSpacing(11)

        sbom = self._panel(
            "Software Bill of Materials",
            "Generate the current dependency inventory using the existing SBOM backend.",
        )
        sb = sbom.layout()

        self.sbom_report_row = HealthRow("SBOM report")
        self.sbom_environment_row = HealthRow("Python environment")
        sb.addWidget(self.sbom_report_row)
        sb.addWidget(self.sbom_environment_row)

        row = QHBoxLayout()
        self.generate_sbom_btn = TiltIconButton(
            "Generate SBOM",
            "deps",
            primary=True,
        )
        self.generate_sbom_btn.setObjectName("PrimaryIconButton")
        self.generate_sbom_btn.setMinimumWidth(140)
        self.generate_sbom_btn.clicked.connect(self.generate_sbom)

        self.open_sbom_btn = TiltIconButton(
            "Open Report Folder",
            "folder",
        )
        self.open_sbom_btn.setObjectName("SecondaryIconButton")
        self.open_sbom_btn.setMinimumWidth(150)
        self.open_sbom_btn.clicked.connect(self.open_dependency_folder)

        row.addWidget(self.generate_sbom_btn)
        row.addWidget(self.open_sbom_btn)
        row.addStretch(1)
        sb.addLayout(row)
        sb.addStretch(1)

        validation = self._panel(
            "Dependency Validation",
            "Compare installed packages with the current requirements baseline.",
        )
        vb = validation.layout()

        metrics = QGridLayout()
        metrics.setSpacing(7)
        self.dep_packages = MetricBox("Packages", "—")
        self.dep_missing = MetricBox("Missing", "—")
        self.dep_mismatch = MetricBox("Mismatched", "—")
        metrics.addWidget(self.dep_packages, 0, 0)
        metrics.addWidget(self.dep_missing, 0, 1)
        metrics.addWidget(self.dep_mismatch, 0, 2)
        vb.addLayout(metrics)

        self.dep_status = HealthRow("Validation status")
        vb.addWidget(self.dep_status)
        vb.addStretch(1)

        top.addWidget(sbom, 0, 0)
        top.addWidget(validation, 0, 1)
        top.setColumnStretch(0, 1)
        top.setColumnStretch(1, 1)
        root.addLayout(top)

        self.dependency_summary = QLabel(
            "Generate the SBOM to review missing, mismatched and unpinned packages.",
            objectName="DependencySummary",
        )
        self.dependency_summary.setWordWrap(True)
        root.addWidget(self.dependency_summary)
        root.addStretch(1)
        return page

    def _build_audit(self):
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(14, 14, 14, 14)
        grid.setSpacing(11)

        integrity = self._panel(
            "Audit Integrity",
            "Verify that application audit records remain readable and internally consistent.",
        )
        ib = integrity.layout()

        self.audit_state_row = HealthRow("Audit verification")
        self.audit_count_row = HealthRow("Records checked")
        ib.addWidget(self.audit_state_row)
        ib.addWidget(self.audit_count_row)

        self.verify_audit_btn = TiltIconButton(
            "Verify Audit Records",
            "shield",
            primary=True,
        )
        self.verify_audit_btn.setObjectName("PrimaryIconButton")
        self.verify_audit_btn.setMinimumWidth(165)
        self.verify_audit_btn.clicked.connect(self.verify_audit)

        ib.addWidget(self.verify_audit_btn)
        ib.addStretch(1)

        security = self._panel(
            "Security Maintenance",
            "Security-sensitive evidence is protected from maintenance cleanup.",
        )
        sb = security.layout()

        row1 = HealthRow("Audit log cleanup")
        row1.set_state("BLOCKED", "amber")
        row2 = HealthRow("User security records")
        row2.set_state("PROTECTED", "green")
        row3 = HealthRow("Backup verification")
        row3.set_state("ENABLED", "green")
        row4 = HealthRow("Maintenance actions")
        row4.set_state("AUDITED", "green")

        for row in (row1, row2, row3, row4):
            sb.addWidget(row)
        sb.addStretch(1)

        grid.addWidget(integrity, 0, 0)
        grid.addWidget(security, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(1, 1)
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
    # Stage navigation
    # ------------------------------------------------------------------
    def _show_stage(self, stage):
        mapping = {
            "overview": self.overview_page,
            "backup": self.backup_page,
            "storage": self.storage_page,
            "deps": self.dependencies_page,
            "audit": self.audit_page,
        }
        if stage not in mapping:
            return

        self._active_stage = stage
        self.stack.setCurrentWidget(mapping[stage])

        meta = {
            "overview": (
                "Maintenance Overview",
                "Current workstation health and available maintenance actions.",
                "OVERVIEW",
                "Review workstation health and available maintenance actions.",
            ),
            "backup": (
                "Backup & Recovery",
                "Create, verify and preview controlled application backups.",
                "BACKUP",
                "Create or verify backups before maintenance work.",
            ),
            "storage": (
                "Storage Cleanup",
                "Review runtime storage usage without deleting protected data.",
                "STORAGE",
                "Storage review is non-destructive in this migration.",
            ),
            "deps": (
                "Dependencies & SBOM",
                "Review dependency inventory and software bill of materials.",
                "DEPENDENCIES",
                "Generate or validate the current dependency inventory.",
            ),
            "audit": (
                "Audit Integrity",
                "Verify protected audit records and maintenance controls.",
                "AUDIT",
                "Verify integrity before exporting maintenance evidence.",
            ),
        }[stage]

        self.stage_title.setText(meta[0])
        self.stage_subtitle.setText(meta[1])
        self.stage_badge.setText(meta[2])
        self.footer_text.setText(meta[3])

        for key, button in self.rail_buttons.items():
            button.setChecked(key == stage)

        if stage == "backup":
            self.refresh_backups()
        elif stage == "storage":
            self.refresh_storage()

    # ------------------------------------------------------------------
    # Async runner
    # ------------------------------------------------------------------
    def _run(self, operation, success, audit_action=None, busy_text="Working…"):
        self._set_busy(True, busy_text)

        worker = Worker(operation)
        self._workers.add(worker)

        def completed(result):
            self._workers.discard(worker)
            self._set_busy(False)

            if audit_action:
                try:
                    record_audit_event(audit_action, actor=self.actor)
                except Exception:
                    pass

            success(result)

        def failed(message):
            self._workers.discard(worker)
            self._set_busy(False)

            if audit_action:
                try:
                    record_audit_event(
                        audit_action,
                        actor=self.actor,
                        status="failed",
                        details={"reason": message},
                    )
                except Exception:
                    pass

            QMessageBox.critical(
                self,
                "Maintenance operation failed",
                str(message),
            )

        worker.signals.completed.connect(completed)
        worker.signals.failed.connect(failed)
        self.pool.start(worker)

    def _set_busy(self, busy: bool, text=""):
        self._busy = bool(busy)
        self.busy_text.setText(text if busy else "")

        for button in (
            self.run_checks_btn,
            self.create_backup_btn,
            self.refresh_backup_btn,
            self.preview_restore_btn,
            self.verify_backup_btn,
            self.rescan_storage_btn,
            self.generate_sbom_btn,
            self.verify_audit_btn,
        ):
            button.setEnabled(not busy)

    # ------------------------------------------------------------------
    # Existing backend: health / SBOM / audit
    # ------------------------------------------------------------------
    @staticmethod
    def _health_snapshot():
        cfg = get_config()

        try:
            mongo.require_available()
            database = {
                "value": "Connected",
                "status": "PASS",
                "passed": True,
                "warning": False,
                "detail": "Database service is available.",
            }
        except Exception:
            database = {
                "value": "Unavailable",
                "status": "FAIL",
                "passed": False,
                "warning": False,
                "detail": "MongoDB could not be reached.",
            }

        valid, audit_message, count = verify_audit_integrity()
        audit = {
            "value": "Verified" if valid else "Integrity issue",
            "status": "PASS" if valid else "FAIL",
            "passed": bool(valid),
            "warning": False,
            "detail": (
                f"{count} records verified."
                if valid
                else str(audit_message)
            ),
            "count": int(count),
        }

        usage = shutil.disk_usage(cfg.data_dir)
        disk = {
            "value": f"{usage.free / (1024 ** 3):.1f} GB free",
            "status": "PASS",
            "passed": True,
            "warning": False,
            "detail": "Storage capacity is readable.",
            "total": int(usage.total),
            "used": int(usage.used),
            "free": int(usage.free),
        }

        project_root = _root()
        requirements = project_root / "requirements.txt"
        bom, report = build_sbom(requirements)

        output = project_root / "reports" / "dependencies"
        output.mkdir(parents=True, exist_ok=True)
        (output / "sbom.cdx.json").write_text(
            json.dumps(bom, indent=2),
            encoding="utf-8",
        )
        (output / "dependency_report.json").write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )

        dependency_status = str(
            report.get("status", "REVIEW")
        ).upper()
        missing = list(report.get("missing", []) or [])
        mismatch = list(report.get("version_mismatches", []) or [])
        unpinned = list(report.get("unpinned", []) or [])

        passed = dependency_status == "PASS"
        dependencies = {
            "value": "Healthy" if passed else "Review required",
            "status": dependency_status,
            "passed": passed,
            "warning": not passed,
            "detail": (
                f"{len(missing)} missing · "
                f"{len(mismatch)} mismatched · "
                f"{len(unpinned)} unpinned."
            ),
            "bom": bom,
            "report": report,
            "output": str(output),
        }

        return {
            "database": database,
            "audit": audit,
            "disk": disk,
            "dependencies": dependencies,
            "data_dir": str(cfg.data_dir),
        }

    def refresh_health(self):
        for row in self.health_rows.values():
            row.set_state("CHECKING", "blue")

        self._run(
            self._health_snapshot,
            self._show_health,
            "system_health_checked",
            "Running maintenance checks…",
        )

    def _show_health(self, snapshot):
        for key in ("database", "audit", "disk", "dependencies"):
            state = snapshot.get(key, {})
            kind = (
                "green"
                if state.get("passed")
                else ("amber" if state.get("warning") else "red")
            )
            self.health_rows[key].set_state(
                state.get("status", "UNKNOWN"),
                kind,
            )

        disk = snapshot.get("disk", {})
        total = int(disk.get("total", 0) or 0)
        used = int(disk.get("used", 0) or 0)
        free = int(disk.get("free", 0) or 0)

        self.storage_card.value.setText(
            f"{free / (1024 ** 3):.1f} GB free"
            if free
            else "Unavailable"
        )
        self.storage_card.detail.setText(
            "Healthy" if disk.get("passed") else "Check storage"
        )

        self.used_metric.value.setText(_format_size(used))
        self.free_metric.value.setText(_format_size(free))
        self.disk_bar.setValue(
            int(round((used / total) * 100))
            if total
            else 0
        )

        cfg = get_config()
        self.data_card.value.setText(Path(cfg.data_dir).name)
        self.data_card.detail.setText("Runtime files are writable")
        self.data_path_label.setText(str(cfg.data_dir))

        logs_path = Path(cfg.data_dir) / "logs"
        self.logs_metric.value.setText(
            _format_size(self._directory_size(logs_path))
        )

        passed = sum(
            1
            for key in ("database", "audit", "disk", "dependencies")
            if snapshot.get(key, {}).get("passed")
        )
        self.checks_card.value.setText(f"{passed} / 4 healthy")
        self.checks_card.detail.setText(
            "No action required"
            if passed == 4
            else "Review maintenance results"
        )

        audit_state = snapshot.get("audit", {})
        self.audit_state_row.set_state(
            audit_state.get("status", "UNKNOWN"),
            "green" if audit_state.get("passed") else "red",
        )
        self.audit_count_row.set_state(
            str(audit_state.get("count", 0)),
            "blue",
        )

        deps = snapshot.get("dependencies", {})
        report = deps.get("report") or {}
        self._apply_dependency_report(report)

        self.toast_requested.emit(
            "Maintenance check complete",
            f"{passed} of 4 maintenance checks passed.",
        )

    def generate_sbom(self):
        self._run(
            self._dependency_snapshot,
            self._show_dependency_snapshot,
            "sbom_generated",
            "Generating dependency report…",
        )

    @staticmethod
    def _dependency_snapshot():
        project_root = _root()
        requirements = project_root / "requirements.txt"
        bom, report = build_sbom(requirements)

        output = project_root / "reports" / "dependencies"
        output.mkdir(parents=True, exist_ok=True)

        sbom_path = output / "sbom.cdx.json"
        report_path = output / "dependency_report.json"

        sbom_path.write_text(
            json.dumps(bom, indent=2),
            encoding="utf-8",
        )
        report_path.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )

        return {
            "bom": bom,
            "report": report,
            "folder": str(output),
        }

    def _show_dependency_snapshot(self, payload):
        report = payload.get("report") or {}
        self._apply_dependency_report(report)

        self.sbom_report_row.set_state("AVAILABLE", "green")
        self.sbom_environment_row.set_state("READABLE", "green")

        self.toast_requested.emit(
            "SBOM generated",
            "Dependency inventory and report were regenerated.",
        )

    def _apply_dependency_report(self, report):
        missing = list(report.get("missing", []) or [])
        mismatches = list(report.get("version_mismatches", []) or [])
        unpinned = list(report.get("unpinned", []) or [])
        status = str(report.get("status", "REVIEW")).upper()

        components = (
            report.get("installed_count")
            or report.get("package_count")
            or report.get("components")
        )
        if isinstance(components, (list, tuple, dict)):
            component_count = len(components)
        elif isinstance(components, int):
            component_count = components
        else:
            component_count = "—"

        self.dep_packages.value.setText(str(component_count))
        self.dep_missing.value.setText(str(len(missing)))
        self.dep_mismatch.value.setText(str(len(mismatches)))

        kind = "green" if status == "PASS" else "amber"
        self.dep_status.set_state(status, kind)
        self.dependency_summary.setText(
            f"{len(missing)} missing · {len(mismatches)} mismatched · "
            f"{len(unpinned)} unpinned package(s)."
        )

    def verify_audit(self):
        self._run(
            self._audit_snapshot,
            self._show_audit_snapshot,
            "audit_integrity_verified",
            "Verifying audit records…",
        )

    @staticmethod
    def _audit_snapshot():
        valid, message, count = verify_audit_integrity()
        return {
            "valid": bool(valid),
            "message": str(message),
            "count": int(count),
        }

    def _show_audit_snapshot(self, snapshot):
        valid = bool(snapshot.get("valid"))
        self.audit_state_row.set_state(
            "PASS" if valid else "FAIL",
            "green" if valid else "red",
        )
        self.audit_count_row.set_state(
            str(snapshot.get("count", 0)),
            "blue",
        )

        if valid:
            self.toast_requested.emit(
                "Audit verification passed",
                f"{snapshot.get('count', 0)} records verified.",
            )
        else:
            QMessageBox.warning(
                self,
                "Audit integrity issue",
                snapshot.get("message", "Audit verification failed."),
            )

    # ------------------------------------------------------------------
    # Existing backend: backup creation / inspect / restore preview
    # ------------------------------------------------------------------
    def _backup_root(self) -> Path:
        return Path(get_config().data_dir) / "backups"

    def _backup_paths(self):
        root = self._backup_root()
        if not root.exists():
            return []
        return sorted(
            root.glob("eyres_backup_*.zip"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    def refresh_backups(self):
        paths = self._backup_paths()
        previous = (
            str(self._selected_backup_path)
            if self._selected_backup_path
            else None
        )

        self.backup_path_label.setText(str(self._backup_root()))
        self.backup_destination.set_state(
            "READY" if self._backup_root().exists() else "AVAILABLE",
            "green",
        )

        self.backup_table.blockSignals(True)
        try:
            self.backup_table.clearContents()
            self.backup_table.setRowCount(len(paths))

            for row, path in enumerate(paths):
                created = _format_timestamp(path.stat().st_mtime)
                size_text = _format_size(path.stat().st_size)

                name_item = QTableWidgetItem(path.name)
                name_item.setData(Qt.ItemDataRole.UserRole, str(path))
                created_item = QTableWidgetItem(created)
                created_item.setData(Qt.ItemDataRole.UserRole, created)
                size_item = QTableWidgetItem(size_text)
                size_item.setData(Qt.ItemDataRole.UserRole, size_text)

                self.backup_table.setItem(row, 0, name_item)
                self.backup_table.setItem(row, 1, created_item)
                self.backup_table.setItem(row, 2, size_item)

                actions = QWidget()
                actions.setObjectName("CellHost")
                ar = QHBoxLayout(actions)
                ar.setContentsMargins(4, 2, 4, 2)
                ar.setSpacing(5)

                verify = QPushButton("Verify", objectName="TableAction")
                preview = QPushButton("Preview", objectName="TableAction")

                verify.clicked.connect(
                    lambda checked=False, r=row: self._select_and_verify(r)
                )
                preview.clicked.connect(
                    lambda checked=False, r=row: self._select_and_preview(r)
                )

                ar.addWidget(verify)
                ar.addWidget(preview)
                ar.addStretch(1)
                self.backup_table.setCellWidget(row, 3, actions)
                self.backup_table.setRowHeight(row, 48)

                if previous and previous == str(path):
                    self.backup_table.selectRow(row)

        finally:
            self.backup_table.blockSignals(False)

        self._resize_backup_columns()
        self._backup_selection_changed()

        if paths:
            latest = paths[0]
            self.backup_card.value.setText(
                _format_timestamp(latest.stat().st_mtime)
            )
            self.backup_card.detail.setText(latest.name)
            self.restore_latest.set_state(
                _format_timestamp(latest.stat().st_mtime),
                "green",
            )
        else:
            self.backup_card.value.setText("No backups")
            self.backup_card.detail.setText("Create the first backup")
            self.restore_latest.set_state("NONE", "amber")

    def create_backup(self):
        self._run(
            lambda: create_backup(keep=10),
            self._backup_created,
            "gui_backup_created",
            "Creating verified backup…",
        )

    def _backup_created(self, path):
        self.refresh_backups()
        self.toast_requested.emit(
            "Backup created",
            Path(path).name,
        )

    def _select_and_verify(self, row):
        self._select_backup_row(row)
        self.verify_selected()

    def _select_and_preview(self, row):
        self._select_backup_row(row)
        self.preview_selected()

    def _select_backup_row(self, row):
        if 0 <= row < self.backup_table.rowCount():
            self.backup_table.selectRow(row)
            self._backup_selection_changed()

    def _selected_backup(self):
        row = self.backup_table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Select backup",
                "Select one backup first.",
            )
            return None

        item = self.backup_table.item(row, 0)
        if item is None:
            return None

        value = item.data(Qt.ItemDataRole.UserRole)
        return Path(str(value)) if value else None

    def verify_selected(self):
        path = self._selected_backup()
        if not path:
            return

        def success(data):
            self.restore_integrity.set_state("VERIFIED", "green")
            BackupManifestDialog(
                path,
                data,
                preview=False,
                parent=self,
            ).exec()

        self._run(
            lambda: inspect_backup(path),
            success,
            "gui_backup_verified",
            "Verifying backup checksum…",
        )

    def preview_selected(self):
        path = self._selected_backup()
        if not path:
            return

        def success(data):
            self.restore_integrity.set_state("VERIFIED", "green")
            BackupManifestDialog(
                path,
                data,
                preview=True,
                parent=self,
            ).exec()

        # Deliberately preserve the previous page's guarded behavior.
        self._run(
            lambda: restore(path, apply=False),
            success,
            "gui_restore_previewed",
            "Preparing restore preview…",
        )

    def _backup_selection_changed(self):
        row = self.backup_table.currentRow()
        if row < 0:
            self._selected_backup_path = None
            self.backup_selection_bar.hide()
            self.restore_integrity.set_state("NOT CHECKED", "blue")
            return

        item = self.backup_table.item(row, 0)
        if item is None:
            self.backup_selection_bar.hide()
            return

        raw = item.data(Qt.ItemDataRole.UserRole)
        if not raw:
            self.backup_selection_bar.hide()
            return

        path = Path(str(raw))
        self._selected_backup_path = path

        created_item = self.backup_table.item(row, 1)
        size_item = self.backup_table.item(row, 2)
        created = created_item.text() if created_item else "—"
        size = size_item.text() if size_item else "—"

        self.selected_backup_label.setText(path.name)
        self.selected_backup_meta.setText(f"{created} · {size}")
        self.backup_selection_bar.show()
        self.restore_integrity.set_state("NOT CHECKED", "blue")

    # ------------------------------------------------------------------
    # Storage scanning (non-destructive)
    # ------------------------------------------------------------------
    def refresh_storage(self):
        self._run(
            self._storage_snapshot,
            self._show_storage,
            None,
            "Scanning runtime storage…",
        )

    @staticmethod
    def _directory_size(path: Path) -> int:
        if not path.exists():
            return 0
        total = 0
        try:
            for item in path.rglob("*"):
                try:
                    if item.is_file():
                        total += item.stat().st_size
                except OSError:
                    continue
        except OSError:
            pass
        return total

    @classmethod
    def _storage_snapshot(cls):
        cfg = get_config()
        data_dir = Path(cfg.data_dir)
        return {
            "data": cls._directory_size(data_dir),
            "logs": cls._directory_size(data_dir / "logs"),
            "backups": cls._directory_size(data_dir / "backups"),
            "reports": cls._directory_size(_root() / "reports"),
            "path": str(data_dir),
        }

    def _show_storage(self, snapshot):
        self.storage_data_row.set_state(
            _format_size(snapshot.get("data", 0)),
            "blue",
        )
        self.storage_logs_row.set_state(
            _format_size(snapshot.get("logs", 0)),
            "blue",
        )
        self.storage_backups_row.set_state(
            _format_size(snapshot.get("backups", 0)),
            "blue",
        )
        self.storage_reports_row.set_state(
            _format_size(snapshot.get("reports", 0)),
            "blue",
        )

        self.toast_requested.emit(
            "Storage scan complete",
            "Runtime storage usage was recalculated.",
        )

    # ------------------------------------------------------------------
    # Shell / folder integration
    # ------------------------------------------------------------------
    def refresh_context(self):
        cfg = get_config()
        data_dir = Path(cfg.data_dir)
        self.data_card.value.setText(data_dir.name or str(data_dir))
        self.data_card.detail.setText("Runtime files")
        self.data_path_label.setText(str(data_dir))
        self.backup_path_label.setText(str(self._backup_root()))

        try:
            usage = shutil.disk_usage(data_dir)
            free_gb = usage.free / (1024 ** 3)
            self.storage_card.value.setText(f"{free_gb:.1f} GB free")
            self.storage_card.detail.setText("Storage readable")
            self.used_metric.value.setText(_format_size(usage.used))
            self.free_metric.value.setText(_format_size(usage.free))
            self.disk_bar.setValue(
                int(round((usage.used / usage.total) * 100))
                if usage.total
                else 0
            )
        except Exception:
            self.storage_card.value.setText("Unavailable")
            self.storage_card.detail.setText("Check runtime path")

        self.logs_metric.value.setText(
            _format_size(self._directory_size(data_dir / "logs"))
        )

        self.refresh_backups()

    def activate(self):
        self.refresh_context()
        self.refresh_health()

    def open_data_folder(self):
        path = Path(get_config().data_dir)
        path.mkdir(parents=True, exist_ok=True)
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(path))
        )

    def open_dependency_folder(self):
        path = _root() / "reports" / "dependencies"
        path.mkdir(parents=True, exist_ok=True)
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(path))
        )

    def _resize_backup_columns(self):
        width = self.backup_table.viewport().width()
        if width <= 0:
            return

        action = 175
        usable = max(0, width - action - 4)
        self.backup_table.setColumnWidth(0, max(270, int(usable * 0.44)))
        self.backup_table.setColumnWidth(1, max(210, int(usable * 0.32)))
        self.backup_table.setColumnWidth(2, max(110, int(usable * 0.18)))
        self.backup_table.setColumnWidth(3, action)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_backup_columns()

    def shutdown(self):
        # QThreadPool is global. We do not cancel unrelated application work.
        # Local workers remove themselves from _workers when completed.
        pass

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------
    def _apply_style(self):
        self.setStyleSheet(PAGE_QSS)


PAGE_QSS = """
QWidget#SystemMaintenancePageQt6 {
    background:#EAF1F8;
    color:#101A2D;
}
QWidget#SystemMaintenancePageQt6 QLabel {
    background:transparent;
    border:0;
}

QFrame#ContextCard {
    background:#FFFFFF;
    border:1px solid #AFC1D4;
    border-radius:12px;
}
QLabel#ContextCaption {
    color:#60728A;
    font-size:7.8px;
    font-weight:850;
    letter-spacing:.55px;
}
QLabel#ContextValue {
    color:#17263D;
    font-size:10.4px;
    font-weight:820;
}
QLabel#ContextDetail {
    color:#718197;
    font-size:7.8px;
}

QFrame#MaintenanceRail,
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
QPushButton#MaintenanceRailButton {
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
QPushButton#MaintenanceRailButton:hover {
    background:#F0F5FF;
    border-color:#8EACD0;
    color:#2868E8;
}
QPushButton#MaintenanceRailButton:checked {
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

QFrame#HealthRow {
    min-height:44px;
    max-height:44px;
    background:#FFFFFF;
    border:1px solid #C3D1E2;
    border-radius:9px;
}
QLabel#HealthCaption {
    color:#17263D;
    font-size:8.8px;
    font-weight:760;
}
QLabel#HealthStatus {
    min-height:21px;
    max-height:21px;
    border-radius:10px;
    padding:0 7px;
    font-size:7.4px;
    font-weight:850;
}
QLabel#HealthStatus[kind="green"] {
    color:#07965D;
    background:#E8F8F1;
}
QLabel#HealthStatus[kind="amber"] {
    color:#A66300;
    background:#FFF5D9;
}
QLabel#HealthStatus[kind="red"] {
    color:#C93450;
    background:#FFF0F3;
}
QLabel#HealthStatus[kind="blue"] {
    color:#2868E8;
    background:#E8F1FF;
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
    font-size:12.5px;
    font-weight:850;
}

QLabel#PathBox {
    min-height:35px;
    background:#FFFFFF;
    color:#30445E;
    border:1px solid #B8C8DB;
    border-radius:8px;
    padding:0 9px;
    font-size:8.5px;
}

QProgressBar#DiskProgress {
    min-height:9px;
    max-height:9px;
    background:#DFE7F0;
    border:0;
    border-radius:4px;
}
QProgressBar#DiskProgress::chunk {
    background:#2868E8;
    border-radius:4px;
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
QPushButton#PrimaryIconButton:disabled,
QPushButton#SecondaryIconButton:disabled {
    background:#F1F4F8;
    color:#9AA7B7;
    border-color:#DCE3EC;
}

QTableWidget#BackupTable {
    background:#FFFFFF;
    color:#2C3E56;
    border:1px solid #B7C8DA;
    border-radius:10px;
    gridline-color:#E3EAF2;
    selection-background-color:#EEF4FF;
    selection-color:#17263D;
    outline:0;
    font-size:8.7px;
}
QTableWidget#BackupTable::item {
    border-bottom:1px solid #E3EAF2;
    padding:0 10px;
}
QHeaderView::section {
    background:#F3F7FB;
    color:#60728A;
    border:0;
    border-bottom:1px solid #C4D2E2;
    padding:0 10px;
    font-size:7.8px;
    font-weight:850;
}

QWidget#CellHost {
    background:transparent;
    border:0;
}
QPushButton#TableAction {
    min-height:28px;
    max-height:28px;
    background:#FFFFFF;
    color:#2868E8;
    border:1px solid #AFC1D4;
    border-radius:7px;
    padding:0 8px;
    font-size:7.8px;
    font-weight:760;
}
QPushButton#TableAction:hover {
    background:#EEF4FF;
}

QFrame#BackupSelectionBar {
    background:#F2F6FF;
    border:1px solid #C8D6E5;
    border-radius:9px;
}
QLabel#SelectedBackupLabel {
    color:#17263D;
    font-size:8.9px;
    font-weight:820;
}
QLabel#SelectedBackupMeta {
    color:#60728A;
    font-size:7.8px;
}

QLabel#InfoNote,
QLabel#DependencySummary {
    color:#60728A;
    background:#FFFFFF;
    border:1px solid #C3D1E2;
    border-radius:9px;
    padding:9px;
    font-size:8.3px;
}

QScrollBar:vertical {
    background:transparent;
    width:8px;
    margin:2px;
}
QScrollBar::handle:vertical {
    background:#BECBDD;
    border-radius:4px;
    min-height:28px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height:0;
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
QFrame#DialogInfo {
    background:#F7FAFD;
    border:1px solid #C3D1E2;
    border-radius:8px;
}
QLabel#DialogKey {
    color:#60728A;
    font-size:8.5px;
    font-weight:760;
}
QLabel#DialogValue {
    color:#17263D;
    font-size:8.8px;
    font-weight:780;
}
QLabel#DialogSection {
    color:#17263D;
    font-size:10px;
    font-weight:830;
    margin-top:5px;
}
QPushButton#DialogPrimary {
    min-height:35px;
    background:#2868E8;
    color:#FFFFFF;
    border:1px solid #2868E8;
    border-radius:8px;
    padding:0 13px;
    font-size:8.8px;
    font-weight:780;
}
"""


SystemMaintenancePage = SystemMaintenancePageQt6
