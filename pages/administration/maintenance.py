"""Administrator maintenance dashboard for health, backup, audit and SBOM.

Modern EYRES System Maintenance UI matching the approved design preview.

Existing backend behaviour is preserved:
- MongoDB connectivity health check
- audit integrity verification
- free disk space reporting
- CycloneDX SBOM/dependency report generation
- verified MongoDB backup creation with retention
- checksum verification
- guarded restore preview only (no data changed)
- audit events for maintenance operations

This page owns a local stylesheet so the host application's global stylesheet
does not flatten the approved design after navigation/reparenting.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from app_core.audit import record_audit_event, verify_audit_integrity
from app_core.config import get_config
from db import mongo
from tools.backup_restore import create_backup, inspect_backup, restore
from tools.generate_sbom import build as build_sbom


# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------

BG = "#F6F9FD"
CARD = "#FFFFFF"
TEXT = "#0E1729"
MUTED = "#61708A"
BORDER = "#DBE3F0"
FIELD_BORDER = "#C9D6EB"

BLUE = "#255CED"
BLUE_DARK = "#174FD2"
BLUE_SOFT = "#ECF2FF"

GREEN = "#089957"
GREEN_SOFT = "#E8FAF0"

AMBER = "#B26B00"
AMBER_SOFT = "#FFF5D9"

RED = "#C83A49"
RED_SOFT = "#FFF0F2"

PURPLE = "#6B40E5"
PURPLE_SOFT = "#F2EDFF"


def _pick_font_family() -> str:
    try:
        families = set(QtGui.QFontDatabase().families())
        for candidate in ("Inter", "Segoe UI Variable Text", "Segoe UI"):
            if candidate in families:
                return candidate
    except Exception:
        pass
    return "Segoe UI"


def _pointer(widget: QtWidgets.QWidget) -> None:
    widget.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))


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


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class WorkerSignals(QtCore.QObject):
    completed = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)


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


# ---------------------------------------------------------------------------
# Local stylesheet
# ---------------------------------------------------------------------------

PAGE_QSS = f"""
QWidget#systemMaintenancePage {{
    background: {BG};
    color: {TEXT};
}}

QWidget#systemMaintenancePage QLabel {{
    background: transparent;
    border: 0px;
    color: {TEXT};
}}

QLabel#pageTitle {{
    color: {TEXT};
    font-size: 24px;
    font-weight: 700;
}}
QLabel#pageSubtitle {{
    color: {MUTED};
    font-size: 12px;
}}

QFrame#healthCard,
QFrame#backupCard {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}

QLabel#healthCaption,
QLabel#summaryCaption {{
    color: {MUTED};
    font-size: 10px;
    font-weight: 700;
}}
QLabel#healthValue {{
    color: {TEXT};
    font-size: 15px;
    font-weight: 700;
}}
QLabel#healthDetail {{
    color: {MUTED};
    font-size: 10px;
}}
QLabel#healthIcon {{
    min-width: 38px;
    max-width: 38px;
    min-height: 38px;
    max-height: 38px;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 700;
}}
QLabel#healthIcon[healthKind="blue"] {{
    background: {BLUE_SOFT};
    color: {BLUE};
}}
QLabel#healthIcon[healthKind="green"] {{
    background: {GREEN_SOFT};
    color: {GREEN};
}}
QLabel#healthIcon[healthKind="amber"] {{
    background: {AMBER_SOFT};
    color: {AMBER};
}}
QLabel#healthIcon[healthKind="purple"] {{
    background: {PURPLE_SOFT};
    color: {PURPLE};
}}
QLabel#healthIcon[healthKind="red"] {{
    background: {RED_SOFT};
    color: {RED};
}}

QLabel#statusChip {{
    min-height: 22px;
    max-height: 22px;
    padding-left: 8px;
    padding-right: 8px;
    border-radius: 11px;
    font-size: 9px;
    font-weight: 700;
}}
QLabel#statusChip[chipKind="green"] {{
    background: {GREEN_SOFT};
    color: {GREEN};
}}
QLabel#statusChip[chipKind="amber"] {{
    background: {AMBER_SOFT};
    color: {AMBER};
}}
QLabel#statusChip[chipKind="red"] {{
    background: {RED_SOFT};
    color: {RED};
}}
QLabel#statusChip[chipKind="blue"] {{
    background: {BLUE_SOFT};
    color: {BLUE};
}}

QLabel#sectionTitle {{
    color: {TEXT};
    font-size: 14px;
    font-weight: 700;
}}
QLabel#sectionSubtitle {{
    color: {MUTED};
    font-size: 10px;
}}

QPushButton {{
    min-height: 38px;
    padding-left: 14px;
    padding-right: 14px;
    border-radius: 9px;
    border: 1px solid {FIELD_BORDER};
    background: {CARD};
    color: {TEXT};
    font-size: 11px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: #F8FAFD;
    border-color: #ADC0E4;
}}
QPushButton:pressed {{
    background: #EEF3FA;
}}
QPushButton:disabled {{
    color: #9BA8BC;
    background: #F4F6F9;
    border-color: #E2E7EF;
}}

QPushButton#primaryButton {{
    background: {BLUE};
    border-color: {BLUE};
    color: white;
    font-weight: 700;
}}
QPushButton#primaryButton:hover {{
    background: {BLUE_DARK};
    border-color: {BLUE_DARK};
}}
QPushButton#primaryButton:pressed {{
    background: #1245BD;
    border-color: #1245BD;
}}

QToolButton#rowMenuButton {{
    min-width: 30px;
    max-width: 30px;
    min-height: 30px;
    max-height: 30px;
    border: 1px solid transparent;
    border-radius: 8px;
    background: transparent;
    color: #66758D;
    font-size: 18px;
    font-weight: 700;
}}
QToolButton#rowMenuButton:hover {{
    background: #EDF2FA;
    border-color: #E1E7F0;
}}

QFrame#backupSummary {{
    background: #FBFCFF;
    border-top: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
}}
QWidget#summaryCell {{
    background: transparent;
    border-right: 1px solid {BORDER};
}}
QWidget#summaryCell[lastCell="true"] {{
    border-right: 0px;
}}
QLabel#summaryValue {{
    color: {TEXT};
    font-size: 13px;
    font-weight: 700;
}}

QTableWidget#backupTable {{
    background: {CARD};
    alternate-background-color: {CARD};
    border: 0px;
    gridline-color: #EDF1F6;
    color: {TEXT};
    selection-background-color: #F0F5FF;
    selection-color: {TEXT};
    outline: 0px;
}}
QTableWidget#backupTable::item {{
    border-bottom: 1px solid #EDF1F6;
    padding: 0px;
}}
QHeaderView#backupHeader {{
    background: #F5F8FC;
    border: 0px;
    border-bottom: 1px solid {BORDER};
}}
QHeaderView#backupHeader::section {{
    background: #F5F8FC;
    color: #66758D;
    border: 0px;
    padding-left: 15px;
    padding-right: 8px;
    font-size: 9px;
    font-weight: 700;
}}
QTableCornerButton::section {{
    background: #F5F8FC;
    border: 0px;
}}

QWidget#backupCellWidget {{
    background: transparent;
    border: 0px;
}}
QLabel#backupIcon {{
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
    border-radius: 9px;
    background: {BLUE_SOFT};
    color: {BLUE};
    font-size: 10px;
    font-weight: 700;
}}
QLabel#backupName {{
    color: {TEXT};
    font-size: 11px;
    font-weight: 700;
}}
QLabel#backupMeta,
QLabel#secondaryCell {{
    color: {MUTED};
    font-size: 10px;
}}

QFrame#selectionBar {{
    background: #F4F7FF;
    border-top: 1px solid #DDE6FB;
    border-bottom-left-radius: 14px;
    border-bottom-right-radius: 14px;
}}
QLabel#selectedTitle {{
    color: {TEXT};
    font-size: 11px;
    font-weight: 700;
}}
QLabel#selectedMeta {{
    color: {MUTED};
    font-size: 9px;
}}
QLabel#statusLine {{
    color: #7A89A0;
    font-size: 9px;
}}

QMenu {{
    background: white;
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 5px;
}}
QMenu::item {{
    min-height: 28px;
    padding-left: 12px;
    padding-right: 24px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background: {BLUE_SOFT};
    color: {TEXT};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #C7D2E4;
    min-height: 32px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{
    background: #AEBBD0;
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #C7D2E4;
    min-width: 32px;
    border-radius: 5px;
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
"""


DIALOG_QSS = f"""
QDialog {{
    background: {CARD};
    color: {TEXT};
}}
QDialog QLabel {{
    background: transparent;
    border: 0px;
    color: {TEXT};
}}
QLabel#dialogTitle {{
    color: {TEXT};
    font-size: 18px;
    font-weight: 700;
}}
QLabel#dialogSubtitle {{
    color: {MUTED};
    font-size: 10px;
}}
QLabel#dialogSectionCaption {{
    color: {MUTED};
    font-size: 9px;
    font-weight: 700;
}}
QLabel#dialogSectionValue {{
    color: {TEXT};
    font-size: 11px;
    font-weight: 600;
}}
QFrame#dialogInfoBox,
QFrame#manifestFrame {{
    background: #F7F9FD;
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QWidget#manifestRow {{
    background: transparent;
    border-bottom: 1px solid #EDF1F6;
}}
QWidget#manifestRow[lastRow="true"] {{
    border-bottom: 0px;
}}
QLabel#manifestKey {{
    color: {MUTED};
    font-size: 10px;
}}
QLabel#manifestValue {{
    color: {TEXT};
    font-size: 10px;
    font-weight: 700;
}}
QLabel#manifestValue[state="success"] {{
    color: {GREEN};
}}
QLabel#manifestValue[state="blue"] {{
    color: {BLUE};
}}
QPushButton {{
    min-height: 38px;
    padding-left: 14px;
    padding-right: 14px;
    border-radius: 9px;
    border: 1px solid {FIELD_BORDER};
    background: white;
    color: {TEXT};
    font-size: 11px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: #F8FAFD;
    border-color: #ADC0E4;
}}
QPushButton#primaryButton {{
    background: {BLUE};
    border-color: {BLUE};
    color: white;
    font-weight: 700;
}}
QPushButton#primaryButton:hover {{
    background: {BLUE_DARK};
    border-color: {BLUE_DARK};
}}
QToolButton#dialogClose {{
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
    border: 0px;
    border-radius: 8px;
    background: #F2F5F9;
    color: #60708A;
    font-size: 18px;
}}
QToolButton#dialogClose:hover {{
    background: #E8EDF5;
}}
"""


# ---------------------------------------------------------------------------
# Small UI helpers
# ---------------------------------------------------------------------------

class _StatusChip(QtWidgets.QLabel):
    def __init__(self, text="NOT CHECKED", kind="blue", parent=None):
        super().__init__(text, parent)
        self.setObjectName("statusChip")
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.set_kind(kind)

    def set_kind(self, kind: str):
        self.setProperty("chipKind", kind)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_state(self, text: str, kind: str):
        self.setText(text)
        self.set_kind(kind)


class _HealthCard(QtWidgets.QFrame):
    def __init__(self, caption: str, icon_text: str, icon_kind: str, parent=None):
        super().__init__(parent)
        self.setObjectName("healthCard")
        self.setMinimumHeight(112)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(17, 16, 17, 15)
        outer.setSpacing(7)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(10)

        text_col = QtWidgets.QVBoxLayout()
        text_col.setSpacing(5)

        caption_label = QtWidgets.QLabel(caption.upper())
        caption_label.setObjectName("healthCaption")

        self.value_label = QtWidgets.QLabel("Not checked")
        self.value_label.setObjectName("healthValue")
        self.value_label.setWordWrap(True)

        text_col.addWidget(caption_label)
        text_col.addWidget(self.value_label)

        self.icon_label = QtWidgets.QLabel(icon_text)
        self.icon_label.setObjectName("healthIcon")
        self.icon_label.setAlignment(QtCore.Qt.AlignCenter)
        self.icon_label.setProperty("healthKind", icon_kind)

        top.addLayout(text_col, 1)
        top.addWidget(self.icon_label, 0, QtCore.Qt.AlignTop)
        outer.addLayout(top)

        status_row = QtWidgets.QHBoxLayout()
        status_row.setSpacing(8)

        self.status_chip = _StatusChip("NOT CHECKED", "blue")
        self.detail_label = QtWidgets.QLabel("Run health checks to update this status.")
        self.detail_label.setObjectName("healthDetail")
        self.detail_label.setWordWrap(True)

        status_row.addWidget(self.status_chip, 0, QtCore.Qt.AlignTop)
        status_row.addWidget(self.detail_label, 1)
        outer.addLayout(status_row)

    def set_checking(self):
        self.value_label.setText("Checking…")
        self.status_chip.set_state("CHECKING", "blue")
        self.detail_label.setText("Health check is currently running.")

    def set_state(
        self,
        value: str,
        passed: bool,
        detail: str,
        warning: bool = False,
    ):
        if passed:
            chip_text, chip_kind = "PASS", "green"
        elif warning:
            chip_text, chip_kind = "REVIEW", "amber"
        else:
            chip_text, chip_kind = "FAIL", "red"

        self.value_label.setText(value)
        self.status_chip.set_state(chip_text, chip_kind)
        self.detail_label.setText(detail)

        icon_kind = self.icon_label.property("baseHealthKind") or self.icon_label.property("healthKind")
        if not passed and not warning:
            self.icon_label.setProperty("healthKind", "red")
        else:
            self.icon_label.setProperty("healthKind", icon_kind)
        self.icon_label.style().unpolish(self.icon_label)
        self.icon_label.style().polish(self.icon_label)


class _SummaryCell(QtWidgets.QWidget):
    def __init__(self, caption: str, value: str = "—", last=False, parent=None):
        super().__init__(parent)
        self.setObjectName("summaryCell")
        self.setProperty("lastCell", "true" if last else "false")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(19, 11, 19, 11)
        layout.setSpacing(4)

        caption_label = QtWidgets.QLabel(caption.upper())
        caption_label.setObjectName("summaryCaption")

        self.value_label = QtWidgets.QLabel(value)
        self.value_label.setObjectName("summaryValue")
        self.value_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        layout.addWidget(caption_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str):
        self.value_label.setText(str(value))


class _BackupIdentityWidget(QtWidgets.QWidget):
    def __init__(self, filename: str, parent=None):
        super().__init__(parent)
        self.setObjectName("backupCellWidget")
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 8, 4)
        layout.setSpacing(10)

        icon = QtWidgets.QLabel("BK")
        icon.setObjectName("backupIcon")
        icon.setAlignment(QtCore.Qt.AlignCenter)

        text_col = QtWidgets.QVBoxLayout()
        text_col.setSpacing(1)

        name = QtWidgets.QLabel(filename)
        name.setObjectName("backupName")
        name.setToolTip(filename)
        name.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        meta = QtWidgets.QLabel("MongoDB backup archive")
        meta.setObjectName("backupMeta")

        text_col.addWidget(name)
        text_col.addWidget(meta)

        layout.addWidget(icon)
        layout.addLayout(text_col, 1)


class _SimpleCell(QtWidgets.QWidget):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("backupCellWidget")
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)

        label = QtWidgets.QLabel(text)
        label.setObjectName("secondaryCell")
        label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        layout.addWidget(label, 0, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        layout.addStretch(1)


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------

class _EyresDialog(QtWidgets.QDialog):
    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        self.resize(520, 420)
        self.setStyleSheet(DIALOG_QSS)
        self.setFont(QtGui.QFont(_pick_font_family(), 10))

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QtWidgets.QWidget()
        head_layout = QtWidgets.QHBoxLayout(head)
        head_layout.setContentsMargins(23, 19, 22, 15)
        head_layout.setSpacing(12)

        title_col = QtWidgets.QVBoxLayout()
        title_col.setSpacing(4)

        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("dialogTitle")

        subtitle_label = QtWidgets.QLabel(subtitle)
        subtitle_label.setObjectName("dialogSubtitle")
        subtitle_label.setWordWrap(True)

        title_col.addWidget(title_label)
        title_col.addWidget(subtitle_label)

        close = QtWidgets.QToolButton()
        close.setObjectName("dialogClose")
        close.setText("×")
        close.clicked.connect(self.reject)
        _pointer(close)

        head_layout.addLayout(title_col, 1)
        head_layout.addWidget(close, 0, QtCore.Qt.AlignTop)
        root.addWidget(head)

        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setStyleSheet(f"background:{BORDER}; border:0px; max-height:1px;")
        root.addWidget(line)

        self.body = QtWidgets.QWidget()
        self.body_layout = QtWidgets.QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(23, 18, 23, 8)
        self.body_layout.setSpacing(12)
        root.addWidget(self.body, 1)

        self.footer = QtWidgets.QWidget()
        self.footer_layout = QtWidgets.QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(23, 12, 23, 19)
        self.footer_layout.setSpacing(9)
        self.footer_layout.addStretch(1)
        root.addWidget(self.footer)

    def add_info_box(self, caption: str, value: str):
        box = QtWidgets.QFrame()
        box.setObjectName("dialogInfoBox")
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        caption_label = QtWidgets.QLabel(caption.upper())
        caption_label.setObjectName("dialogSectionCaption")

        value_label = QtWidgets.QLabel(value)
        value_label.setObjectName("dialogSectionValue")
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        layout.addWidget(caption_label)
        layout.addWidget(value_label)
        self.body_layout.addWidget(box)

    def add_manifest_rows(self, rows):
        frame = QtWidgets.QFrame()
        frame.setObjectName("manifestFrame")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        for index, row in enumerate(rows):
            if len(row) == 2:
                key, value = row
                state = ""
            else:
                key, value, state = row

            widget = QtWidgets.QWidget()
            widget.setObjectName("manifestRow")
            widget.setProperty("lastRow", "true" if index == len(rows) - 1 else "false")

            row_layout = QtWidgets.QHBoxLayout(widget)
            row_layout.setContentsMargins(11, 9, 11, 9)
            row_layout.setSpacing(10)

            key_label = QtWidgets.QLabel(str(key))
            key_label.setObjectName("manifestKey")

            value_label = QtWidgets.QLabel(str(value))
            value_label.setObjectName("manifestValue")
            value_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            if state:
                value_label.setProperty("state", state)

            row_layout.addWidget(key_label, 1)
            row_layout.addWidget(value_label, 1)
            layout.addWidget(widget)

        self.body_layout.addWidget(frame)

    def add_footer_button(self, text: str, primary=False):
        button = QtWidgets.QPushButton(text)
        if primary:
            button.setObjectName("primaryButton")
        button.clicked.connect(self.accept)
        _pointer(button)
        self.footer_layout.addWidget(button)
        return button


class _BackupManifestDialog(_EyresDialog):
    def __init__(self, path: Path, manifest: Dict, preview=False, parent=None):
        title = "Restore preview" if preview else "Backup verified"
        subtitle = (
            "Preview only — no database data will be changed."
            if preview
            else "Checksum validation completed successfully for the selected archive."
        )
        super().__init__(title, subtitle, parent)

        self.add_info_box("Selected backup", path.name)

        collections = manifest.get("collections", {}) or {}
        rows = [
            ("Database", manifest.get("database", "unknown")),
            ("Created", _format_manifest_created(manifest.get("created_utc"))),
        ]

        if preview:
            for name, count in sorted(collections.items()):
                rows.append((str(name), f"{count} records"))
            rows.append(("Mode", "Preview only", "blue"))
        else:
            rows.append(("Integrity", "Checksum passed", "success"))
            rows.append(("Collections", str(len(collections))))

        self.add_manifest_rows(rows)
        self.body_layout.addStretch(1)
        self.add_footer_button("Close" if preview else "Done", primary=not preview)


# ---------------------------------------------------------------------------
# System maintenance page
# ---------------------------------------------------------------------------

class SystemMaintenancePage(QtWidgets.QWidget):
    def __init__(self, actor="unknown", parent=None):
        super().__init__(parent)

        self.actor = str(actor or "unknown")
        self.pool = QtCore.QThreadPool.globalInstance()
        self._workers = set()
        self._font_family = _pick_font_family()
        self._selected_backup_path: Optional[Path] = None
        self._theme_restore_scheduled = False

        self.setObjectName("systemMaintenancePage")
        self.setFont(QtGui.QFont(self._font_family, 10))
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.installEventFilter(self)

        self._build_ui()
        self._force_local_theme()

    # ------------------------------- UI ---------------------------------

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 28)
        root.setSpacing(17)

        # Header
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(14)

        title_col = QtWidgets.QVBoxLayout()
        title_col.setSpacing(4)

        title = QtWidgets.QLabel("System Maintenance")
        title.setObjectName("pageTitle")

        subtitle = QtWidgets.QLabel(
            "Health checks, verified backups, audit integrity and dependency reporting."
        )
        subtitle.setObjectName("pageSubtitle")

        title_col.addWidget(title)
        title_col.addWidget(subtitle)

        self.health_button = QtWidgets.QPushButton("Run Health Checks")
        self.health_button.setObjectName("primaryButton")
        self.health_button.clicked.connect(self.refresh_health)
        _pointer(self.health_button)

        header.addLayout(title_col, 1)
        header.addWidget(self.health_button, 0, QtCore.Qt.AlignTop)
        root.addLayout(header)

        # Health cards
        health_row = QtWidgets.QHBoxLayout()
        health_row.setSpacing(13)

        self.health_cards = {
            "database": _HealthCard("MongoDB", "DB", "green"),
            "audit": _HealthCard("Audit Integrity", "AU", "purple"),
            "disk": _HealthCard("Free Disk Space", "DS", "amber"),
            "dependencies": _HealthCard("Dependencies", "DP", "blue"),
        }

        # Preserve base icon colors when a temporary fail state is shown.
        for key, kind in (
            ("database", "green"),
            ("audit", "purple"),
            ("disk", "amber"),
            ("dependencies", "blue"),
        ):
            self.health_cards[key].icon_label.setProperty("baseHealthKind", kind)

        # Compatibility with the old page's public attribute.
        self.health_labels = {
            key: card.value_label for key, card in self.health_cards.items()
        }

        for card in self.health_cards.values():
            health_row.addWidget(card, 1)

        root.addLayout(health_row)

        # Backup card
        backup_card = QtWidgets.QFrame()
        backup_card.setObjectName("backupCard")
        backup_layout = QtWidgets.QVBoxLayout(backup_card)
        backup_layout.setContentsMargins(0, 0, 0, 0)
        backup_layout.setSpacing(0)

        backup_head = QtWidgets.QWidget()
        backup_head_layout = QtWidgets.QHBoxLayout(backup_head)
        backup_head_layout.setContentsMargins(19, 15, 19, 15)
        backup_head_layout.setSpacing(10)

        section_col = QtWidgets.QVBoxLayout()
        section_col.setSpacing(3)

        section_title = QtWidgets.QLabel("Database Backups")
        section_title.setObjectName("sectionTitle")

        section_subtitle = QtWidgets.QLabel(
            "Verified MongoDB snapshots with checksum validation and guarded restore preview."
        )
        section_subtitle.setObjectName("sectionSubtitle")

        section_col.addWidget(section_title)
        section_col.addWidget(section_subtitle)

        self.refresh_button = QtWidgets.QPushButton("Refresh List")
        self.refresh_button.clicked.connect(self.refresh_backups)
        _pointer(self.refresh_button)

        self.create_backup_button = QtWidgets.QPushButton("+  Create Backup")
        self.create_backup_button.setObjectName("primaryButton")
        self.create_backup_button.clicked.connect(self.create_backup)
        _pointer(self.create_backup_button)

        backup_head_layout.addLayout(section_col, 1)
        backup_head_layout.addWidget(self.refresh_button)
        backup_head_layout.addWidget(self.create_backup_button)
        backup_layout.addWidget(backup_head)

        # Summary strip
        summary_frame = QtWidgets.QFrame()
        summary_frame.setObjectName("backupSummary")
        summary_layout = QtWidgets.QHBoxLayout(summary_frame)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(0)

        self.summary_stored = _SummaryCell("Stored Backups", "0")
        self.summary_retention = _SummaryCell("Retention", "10 backups")
        self.summary_latest = _SummaryCell("Latest Backup", "—")
        self.summary_storage = _SummaryCell("Storage Used", "0.00 MB", last=True)

        summary_layout.addWidget(self.summary_stored, 1)
        summary_layout.addWidget(self.summary_retention, 1)
        summary_layout.addWidget(self.summary_latest, 1)
        summary_layout.addWidget(self.summary_storage, 1)

        backup_layout.addWidget(summary_frame)

        # Backups table
        self.backups = QtWidgets.QTableWidget(0, 4)
        self.backups.setObjectName("backupTable")
        self.backups.setHorizontalHeaderLabels(["BACKUP", "CREATED", "SIZE", ""])
        self.backups.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.backups.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.backups.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.backups.setAlternatingRowColors(False)
        self.backups.setShowGrid(False)
        self.backups.setFocusPolicy(QtCore.Qt.NoFocus)
        self.backups.verticalHeader().setVisible(False)
        self.backups.verticalHeader().setDefaultSectionSize(62)
        self.backups.setMinimumHeight(290)

        header_view = self.backups.horizontalHeader()
        header_view.setObjectName("backupHeader")
        header_view.setMinimumHeight(38)
        header_view.setHighlightSections(False)
        header_view.setStretchLastSection(False)
        header_view.setDefaultAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)

        for column in range(4):
            header_view.setSectionResizeMode(column, QtWidgets.QHeaderView.Fixed)
            item = self.backups.horizontalHeaderItem(column)
            if item is not None:
                item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)

        self.backups.itemSelectionChanged.connect(self._selection_changed)
        self._resize_table_columns()

        backup_layout.addWidget(self.backups, 1)

        # Selected backup action bar
        self.selection_bar = QtWidgets.QFrame()
        self.selection_bar.setObjectName("selectionBar")

        selection_layout = QtWidgets.QHBoxLayout(self.selection_bar)
        selection_layout.setContentsMargins(17, 10, 17, 10)
        selection_layout.setSpacing(9)

        selected_text = QtWidgets.QVBoxLayout()
        selected_text.setSpacing(1)

        self.selected_title = QtWidgets.QLabel("Selected backup")
        self.selected_title.setObjectName("selectedTitle")

        self.selected_meta = QtWidgets.QLabel("")
        self.selected_meta.setObjectName("selectedMeta")

        selected_text.addWidget(self.selected_title)
        selected_text.addWidget(self.selected_meta)

        self.verify_button = QtWidgets.QPushButton("Verify Backup")
        self.verify_button.clicked.connect(self.verify_selected)
        _pointer(self.verify_button)

        self.preview_button = QtWidgets.QPushButton("Preview Restore")
        self.preview_button.setObjectName("primaryButton")
        self.preview_button.clicked.connect(self.preview_selected)
        _pointer(self.preview_button)

        selection_layout.addLayout(selected_text)
        selection_layout.addStretch(1)
        selection_layout.addWidget(self.verify_button)
        selection_layout.addWidget(self.preview_button)

        self.selection_bar.hide()
        backup_layout.addWidget(self.selection_bar)

        root.addWidget(backup_card, 1)

        self.status = QtWidgets.QLabel("Ready")
        self.status.setObjectName("statusLine")
        root.addWidget(self.status)

    # ------------------------------ styling -----------------------------

    def _force_local_theme(self):
        self.setStyleSheet(PAGE_QSS)
        self.setFont(QtGui.QFont(self._font_family, 10))
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)

        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _schedule_theme_restore(self):
        if self._theme_restore_scheduled:
            return
        self._theme_restore_scheduled = True

        def restore():
            self._theme_restore_scheduled = False
            self._force_local_theme()

        QtCore.QTimer.singleShot(0, restore)
        QtCore.QTimer.singleShot(80, self._force_local_theme)
        QtCore.QTimer.singleShot(220, self._force_local_theme)

    def eventFilter(self, watched, event):
        if watched is self and event.type() in (
            QtCore.QEvent.ParentChange,
            QtCore.QEvent.Show,
        ):
            self._schedule_theme_restore()
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        self._resize_table_columns()
        self._schedule_theme_restore()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_table_columns()

    def _resize_table_columns(self):
        if not hasattr(self, "backups"):
            return

        viewport_width = self.backups.viewport().width()
        if viewport_width <= 0:
            return

        menu_width = 52
        usable = max(0, viewport_width - menu_width - 2)

        # Approved design proportions:
        # Backup 47%, Created 26%, Size 27%, fixed menu column.
        ratios = (0.47, 0.26, 0.27)
        minimums = (430, 230, 150)

        widths = [
            max(minimums[i], int(usable * ratios[i]))
            for i in range(3)
        ]

        for column, width in enumerate(widths):
            self.backups.setColumnWidth(column, width)

        self.backups.setColumnWidth(3, menu_width)

    # --------------------------- page lifecycle -------------------------

    def activate(self):
        self._schedule_theme_restore()
        self.refresh_backups()
        self.refresh_health()

    # --------------------------- backup listing -------------------------

    def _backup_root(self) -> Path:
        return get_config().data_dir / "backups"

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

        selected_path = str(self._selected_backup_path) if self._selected_backup_path else None

        self.backups.blockSignals(True)
        try:
            self.backups.setRowCount(0)

            for row, path in enumerate(paths):
                self.backups.insertRow(row)

                # Blank backing items avoid QTableWidget painting duplicate text
                # underneath the custom cell widgets.
                path_item = QtWidgets.QTableWidgetItem("")
                path_item.setData(QtCore.Qt.UserRole, str(path))
                self.backups.setItem(row, 0, path_item)
                self.backups.setCellWidget(row, 0, _BackupIdentityWidget(path.name))

                created = _format_timestamp(path.stat().st_mtime)
                created_item = QtWidgets.QTableWidgetItem("")
                created_item.setData(QtCore.Qt.UserRole, created)
                self.backups.setItem(row, 1, created_item)
                self.backups.setCellWidget(row, 1, _SimpleCell(created))

                size_mb = path.stat().st_size / (1024 * 1024)
                size_text = f"{size_mb:.2f} MB"
                size_item = QtWidgets.QTableWidgetItem("")
                size_item.setData(QtCore.Qt.UserRole, size_text)
                self.backups.setItem(row, 2, size_item)
                self.backups.setCellWidget(row, 2, _SimpleCell(size_text))

                menu_item = QtWidgets.QTableWidgetItem("")
                self.backups.setItem(row, 3, menu_item)

                menu_button = QtWidgets.QToolButton()
                menu_button.setObjectName("rowMenuButton")
                menu_button.setText("⋯")
                menu_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
                menu_button.setMenu(self._build_row_menu(row))
                _pointer(menu_button)

                menu_host = QtWidgets.QWidget()
                menu_host.setObjectName("backupCellWidget")
                menu_layout = QtWidgets.QHBoxLayout(menu_host)
                menu_layout.setContentsMargins(2, 0, 2, 0)
                menu_layout.addStretch(1)
                menu_layout.addWidget(menu_button, 0, QtCore.Qt.AlignCenter)
                menu_layout.addStretch(1)
                self.backups.setCellWidget(row, 3, menu_host)

                if selected_path and str(path) == selected_path:
                    self.backups.selectRow(row)

            self._update_backup_summary(paths)

            if not paths:
                self._selected_backup_path = None
                self.selection_bar.hide()
                self.selected_title.setText("Selected backup")
                self.selected_meta.setText("")

        finally:
            self.backups.blockSignals(False)
            QtCore.QTimer.singleShot(0, self._resize_table_columns)

        # If the previously selected row still exists, refresh its bar.
        self._selection_changed()

    def _update_backup_summary(self, paths):
        self.summary_stored.set_value(str(len(paths)))
        self.summary_retention.set_value("10 backups")

        if paths:
            latest = paths[0]
            self.summary_latest.set_value(_format_timestamp(latest.stat().st_mtime))
            total_bytes = sum(path.stat().st_size for path in paths)
            self.summary_storage.set_value(f"{total_bytes / (1024 * 1024):.2f} MB")
        else:
            self.summary_latest.set_value("—")
            self.summary_storage.set_value("0.00 MB")

    def _build_row_menu(self, row: int):
        menu = QtWidgets.QMenu(self)

        verify_action = menu.addAction("Verify Backup")
        preview_action = menu.addAction("Preview Restore")

        def select_row_and(callback):
            if 0 <= row < self.backups.rowCount():
                self.backups.selectRow(row)
                callback()

        verify_action.triggered.connect(
            lambda checked=False: select_row_and(self.verify_selected)
        )
        preview_action.triggered.connect(
            lambda checked=False: select_row_and(self.preview_selected)
        )
        return menu

    def _selection_changed(self):
        row = self.backups.currentRow()
        if row < 0 or row >= self.backups.rowCount():
            self._selected_backup_path = None
            self.selection_bar.hide()
            return

        item = self.backups.item(row, 0)
        if item is None:
            self._selected_backup_path = None
            self.selection_bar.hide()
            return

        path_value = item.data(QtCore.Qt.UserRole)
        if not path_value:
            self._selected_backup_path = None
            self.selection_bar.hide()
            return

        path = Path(str(path_value))
        self._selected_backup_path = path

        created = self.backups.item(row, 1).data(QtCore.Qt.UserRole)
        size = self.backups.item(row, 2).data(QtCore.Qt.UserRole)

        self.selected_title.setText(f"Selected: {path.name}")
        self.selected_meta.setText(f"{created} · {size}")
        self.selection_bar.show()

    def _selected_backup(self):
        row = self.backups.currentRow()
        if row < 0:
            QtWidgets.QMessageBox.information(
                self,
                "Select backup",
                "Select one backup first.",
            )
            return None

        item = self.backups.item(row, 0)
        if item is None:
            return None

        value = item.data(QtCore.Qt.UserRole)
        if not value:
            return None

        return Path(str(value))

    # ---------------------------- async work -----------------------------

    def _run(self, operation, success, audit_action=None):
        self.status.setText("Working…")

        worker = Worker(operation)
        self._workers.add(worker)

        def completed(result):
            self._workers.discard(worker)
            self.status.setText("Completed")

            if audit_action:
                record_audit_event(audit_action, actor=self.actor)

            success(result)

        def failed(message):
            self._workers.discard(worker)
            self.status.setText("Failed")

            if audit_action:
                record_audit_event(
                    audit_action,
                    actor=self.actor,
                    status="failed",
                    details={"reason": message},
                )

            self._set_busy(False)

            QtWidgets.QMessageBox.critical(
                self,
                "Maintenance operation failed",
                message,
            )

        worker.signals.completed.connect(completed)
        worker.signals.failed.connect(failed)
        self.pool.start(worker)

    def _set_busy(self, busy: bool):
        self.health_button.setEnabled(not busy)
        self.create_backup_button.setEnabled(not busy)
        self.verify_button.setEnabled(not busy)
        self.preview_button.setEnabled(not busy)

    # --------------------------- backup actions -------------------------

    def create_backup(self):
        self.create_backup_button.setEnabled(False)
        self.create_backup_button.setText("Creating…")

        self._run(
            lambda: create_backup(keep=10),
            self._backup_created,
            "gui_backup_created",
        )

    def _backup_created(self, path):
        self.create_backup_button.setEnabled(True)
        self.create_backup_button.setText("+  Create Backup")
        self.refresh_backups()

        QtWidgets.QMessageBox.information(
            self,
            "Backup created",
            f"Backup created successfully.\n\n{path}",
        )

    def verify_selected(self):
        path = self._selected_backup()
        if not path:
            return

        self.verify_button.setEnabled(False)
        self.verify_button.setText("Verifying…")

        def success(data):
            self.verify_button.setEnabled(True)
            self.verify_button.setText("Verify Backup")
            dialog = _BackupManifestDialog(path, data, preview=False, parent=self)
            dialog.exec_()

        self._run(
            lambda: inspect_backup(path),
            success,
            "gui_backup_verified",
        )

    def preview_selected(self):
        path = self._selected_backup()
        if not path:
            return

        self.preview_button.setEnabled(False)
        self.preview_button.setText("Preparing…")

        def success(data):
            self.preview_button.setEnabled(True)
            self.preview_button.setText("Preview Restore")
            dialog = _BackupManifestDialog(path, data, preview=True, parent=self)
            dialog.exec_()

        self._run(
            lambda: restore(path, apply=False),
            success,
            "gui_restore_previewed",
        )

    @staticmethod
    def _manifest_summary(manifest):
        # Retained for compatibility with existing callers/tests.
        collections = manifest.get("collections", {})
        lines = [
            f"Database: {manifest.get('database', 'unknown')}",
            f"Created: {manifest.get('created_utc', 'unknown')}",
            "",
            "Collections:",
        ]
        lines.extend(
            f"  {name}: {count}"
            for name, count in sorted(collections.items())
        )
        return "\n".join(lines)

    # ---------------------------- health checks -------------------------

    def refresh_health(self):
        for card in self.health_cards.values():
            card.set_checking()

        self.health_button.setEnabled(False)
        self.health_button.setText("Checking…")

        self._run(
            self._health_snapshot,
            self._show_health,
            "system_health_checked",
        )

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
            "detail": f"{count} records verified." if valid else str(audit_message),
        }

        usage = shutil.disk_usage(cfg.data_dir)
        free_gb = usage.free / (1024 ** 3)
        disk = {
            "value": f"{free_gb:.1f} GB free",
            "status": "PASS",
            "passed": True,
            "warning": False,
            "detail": "Storage capacity is healthy.",
        }

        project_root = Path(__file__).resolve().parents[2]
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

        dependency_status = str(report.get("status", "REVIEW")).upper()
        missing_count = len(report.get("missing", []))
        mismatch_count = len(report.get("version_mismatches", []))
        unpinned_count = len(report.get("unpinned", []))

        dependency_passed = dependency_status == "PASS"
        dependencies = {
            "value": "Healthy" if dependency_passed else "Review required",
            "status": dependency_status,
            "passed": dependency_passed,
            "warning": not dependency_passed,
            "detail": (
                f"{missing_count} missing · {mismatch_count} mismatched."
                if dependency_passed
                else (
                    f"{missing_count} missing · {mismatch_count} mismatched · "
                    f"{unpinned_count} unpinned."
                )
            ),
        }

        return {
            "database": database,
            "audit": audit,
            "disk": disk,
            "dependencies": dependencies,
        }

    def _show_health(self, snapshot):
        self.health_button.setEnabled(True)
        self.health_button.setText("Run Health Checks")

        # New structured snapshot used by this page.
        if snapshot and isinstance(next(iter(snapshot.values()), None), dict):
            for key, state in snapshot.items():
                card = self.health_cards.get(key)
                if card is None:
                    continue

                card.set_state(
                    state.get("value", "Unknown"),
                    bool(state.get("passed")),
                    state.get("detail", ""),
                    bool(state.get("warning")),
                )
            return

        # Compatibility fallback for an old string snapshot.
        for key, value in snapshot.items():
            card = self.health_cards.get(key)
            if card is None:
                continue

            text = str(value)
            upper = text.upper()
            passed = upper.startswith("PASS")
            warning = upper.startswith("REVIEW")
            display = text.split("—", 1)[1].strip() if "—" in text else text

            card.set_state(
                display,
                passed,
                text,
                warning,
            )
