"""Administrator-only diagnostics and privacy-safe support reporting UI.

Modern EYRES Application Diagnostics page matching the approved design.

Backend behaviour is preserved:
- severity + text filtering of application diagnostics
- privacy-safe system snapshot
- redacted support report copy/export
- operational diagnostic log clearing only
- security audit records remain separate
- audit events for support-report and clear-log actions

The page owns a local stylesheet and restores it after reparent/show events so
the host application's global stylesheet cannot flatten the approved design.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from app_core.audit import record_audit_event
from app_core.diagnostics import (
    build_support_report,
    clear_diagnostic_logs,
    export_support_report,
    recent_log_entries,
    system_snapshot,
)


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

CONSOLE = "#07101E"
CONSOLE_HOVER = "#0D1728"
CONSOLE_TEXT = "#E7EDF7"
CONSOLE_MUTED = "#8798B4"
CONSOLE_MODULE = "#AAB7CC"


_LOG_PATTERN = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2}\s+"
    r"\d{2}:\d{2}:\d{2}(?:,\d{3})?)\s+"
    r"(?P<level>CRITICAL|ERROR|WARNING|INFO|DEBUG)\s+"
    r"(?P<module>\S+)\s*"
    r"(?P<message>.*)$",
    re.IGNORECASE,
)


def _pick_font_family() -> str:
    try:
        families = set(QtGui.QFontDatabase().families())
        for candidate in ("Inter", "Segoe UI Variable Text", "Segoe UI"):
            if candidate in families:
                return candidate
    except Exception:
        pass
    return "Segoe UI"


def _mono_font_family() -> str:
    try:
        families = set(QtGui.QFontDatabase().families())
        for candidate in ("Cascadia Mono", "Consolas", "Courier New"):
            if candidate in families:
                return candidate
    except Exception:
        pass
    return "Courier New"


def _pointer(widget: QtWidgets.QWidget) -> None:
    widget.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))


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

    # Fallback: preserve every character of an unrecognised log line instead
    # of dropping information.
    return ("", "INFO", "", text)


def _friendly_platform(raw: str) -> str:
    text = str(raw or "Unknown")
    match = re.match(r"Windows-(\d+)", text, re.IGNORECASE)
    if match:
        return f"Windows {match.group(1)}"

    if text.lower().startswith("windows"):
        return "Windows"

    # Keep the first useful platform family for Linux/macOS/other systems.
    head = text.split("-", 1)[0].strip()
    return head or text


# ---------------------------------------------------------------------------
# Page stylesheet
# ---------------------------------------------------------------------------

PAGE_QSS = f"""
QWidget#diagnosticsPage {{
    background: {BG};
    color: {TEXT};
}}

QWidget#diagnosticsPage QLabel {{
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

QFrame#runtimeCard,
QFrame#diagnosticCard {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}

QLabel#runtimeCaption {{
    color: {MUTED};
    font-size: 10px;
    font-weight: 700;
}}
QLabel#runtimeValue {{
    color: {TEXT};
    font-size: 15px;
    font-weight: 700;
}}
QLabel#runtimeMeta {{
    color: {MUTED};
    font-size: 9px;
}}
QLabel#runtimeIcon {{
    min-width: 38px;
    max-width: 38px;
    min-height: 38px;
    max-height: 38px;
    border-radius: 10px;
    font-size: 10px;
    font-weight: 700;
}}
QLabel#runtimeIcon[iconKind="blue"] {{
    background: {BLUE_SOFT};
    color: {BLUE};
}}
QLabel#runtimeIcon[iconKind="green"] {{
    background: {GREEN_SOFT};
    color: {GREEN};
}}
QLabel#runtimeIcon[iconKind="purple"] {{
    background: {PURPLE_SOFT};
    color: {PURPLE};
}}
QLabel#runtimeIcon[iconKind="amber"] {{
    background: {AMBER_SOFT};
    color: {AMBER};
}}

QLabel#miniChip {{
    min-height: 22px;
    max-height: 22px;
    padding-left: 8px;
    padding-right: 8px;
    border-radius: 11px;
    font-size: 9px;
    font-weight: 700;
}}
QLabel#miniChip[chipKind="green"] {{
    background: {GREEN_SOFT};
    color: {GREEN};
}}
QLabel#miniChip[chipKind="amber"] {{
    background: {AMBER_SOFT};
    color: {AMBER};
}}
QLabel#miniChip[chipKind="blue"] {{
    background: {BLUE_SOFT};
    color: {BLUE};
}}
QLabel#miniChip[chipKind="red"] {{
    background: {RED_SOFT};
    color: {RED};
}}

QFrame#privacyStrip {{
    background: #F1F5FF;
    border: 1px solid #D8E2FF;
    border-radius: 12px;
}}
QLabel#privacyIcon {{
    min-width: 31px;
    max-width: 31px;
    min-height: 31px;
    max-height: 31px;
    border-radius: 9px;
    background: #DDE7FF;
    color: {BLUE};
    font-size: 14px;
    font-weight: 700;
}}
QLabel#privacyTitle {{
    color: {TEXT};
    font-size: 11px;
    font-weight: 700;
}}
QLabel#privacySubtitle {{
    color: {MUTED};
    font-size: 9px;
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
QLabel#recordBadge {{
    min-height: 28px;
    max-height: 28px;
    padding-left: 10px;
    padding-right: 10px;
    border-radius: 14px;
    background: #F0F4FA;
    color: #5E6D84;
    font-size: 9px;
    font-weight: 700;
}}

QWidget#logToolbar,
QWidget#logFooter {{
    background: #FBFCFF;
    border: 0px;
}}
QWidget#logToolbar {{
    border-bottom: 1px solid {BORDER};
}}
QWidget#logFooter {{
    border-top: 1px solid {BORDER};
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
QPushButton#dangerButton {{
    background: #FFF9FA;
    border-color: #F0CBD1;
    color: {RED};
    font-weight: 700;
}}
QPushButton#dangerButton:hover {{
    background: {RED_SOFT};
    border-color: #E9ABB5;
}}

QLineEdit#logSearch,
QComboBox#severityCombo {{
    min-height: 38px;
    max-height: 38px;
    border: 1px solid {FIELD_BORDER};
    border-radius: 8px;
    background: white;
    color: {TEXT};
    padding-left: 10px;
    padding-right: 10px;
    font-size: 10px;
}}
QLineEdit#logSearch:focus,
QComboBox#severityCombo:focus {{
    border: 1px solid #8EAAF8;
}}
QLineEdit#logSearch {{
    padding-left: 12px;
}}
QComboBox#severityCombo {{
    min-width: 130px;
    max-width: 130px;
}}
QComboBox#severityCombo::drop-down {{
    border: 0px;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background: white;
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {BLUE_SOFT};
    selection-color: {TEXT};
    outline: 0px;
    padding: 4px;
}}

QTableWidget#logTable {{
    background: {CONSOLE};
    alternate-background-color: {CONSOLE};
    border: 0px;
    gridline-color: transparent;
    outline: 0px;
    color: {CONSOLE_TEXT};
    selection-background-color: {CONSOLE_HOVER};
    selection-color: {CONSOLE_TEXT};
}}
QTableWidget#logTable::item {{
    background: {CONSOLE};
    border: 0px;
    padding-left: 8px;
    padding-right: 8px;
}}
QTableWidget#logTable::item:hover {{
    background: {CONSOLE_HOVER};
}}
QTableWidget#logTable QTableCornerButton::section {{
    background: {CONSOLE};
    border: 0px;
}}
QHeaderView#logHeader {{
    background: {CONSOLE};
    border: 0px;
}}
QHeaderView#logHeader::section {{
    background: {CONSOLE};
    border: 0px;
}}

QLabel#footerStatus {{
    color: {MUTED};
    font-size: 9px;
}}
QLabel#footerHint {{
    color: {MUTED};
    font-size: 9px;
}}

QScrollBar:vertical {{
    background: {CONSOLE};
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #30405A;
    min-height: 32px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{
    background: #415675;
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: {CONSOLE};
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #30405A;
    min-width: 32px;
    border-radius: 5px;
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

QMenu {{
    background: white;
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
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
QFrame#warningBox {{
    background: {RED_SOFT};
    border: 1px solid #F2CDD3;
    border-radius: 10px;
}}
QFrame#safeBox {{
    background: #F7F9FD;
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QLabel#warningText {{
    color: #6A3940;
    font-size: 10px;
}}
QLabel#safeText {{
    color: #58677E;
    font-size: 10px;
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
QPushButton#dangerButton {{
    background: #FFF9FA;
    border-color: #F0CBD1;
    color: {RED};
    font-weight: 700;
}}
QPushButton#dangerButton:hover {{
    background: {RED_SOFT};
    border-color: #E9ABB5;
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
# Small widgets
# ---------------------------------------------------------------------------

class _MiniChip(QtWidgets.QLabel):
    def __init__(self, text="", kind="blue", parent=None):
        super().__init__(text, parent)
        self.setObjectName("miniChip")
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.set_kind(kind)

    def set_kind(self, kind: str):
        self.setProperty("chipKind", kind)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_state(self, text: str, kind: str):
        self.setText(text)
        self.set_kind(kind)


class _RuntimeCard(QtWidgets.QFrame):
    def __init__(self, caption: str, icon_text: str, icon_kind: str, parent=None):
        super().__init__(parent)
        self.setObjectName("runtimeCard")
        self.setMinimumHeight(112)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(17, 15, 17, 14)
        layout.setSpacing(7)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(10)

        text_col = QtWidgets.QVBoxLayout()
        text_col.setSpacing(5)

        caption_label = QtWidgets.QLabel(caption.upper())
        caption_label.setObjectName("runtimeCaption")

        self.value_label = QtWidgets.QLabel("—")
        self.value_label.setObjectName("runtimeValue")
        self.value_label.setWordWrap(True)

        text_col.addWidget(caption_label)
        text_col.addWidget(self.value_label)

        icon = QtWidgets.QLabel(icon_text)
        icon.setObjectName("runtimeIcon")
        icon.setAlignment(QtCore.Qt.AlignCenter)
        icon.setProperty("iconKind", icon_kind)

        top.addLayout(text_col, 1)
        top.addWidget(icon, 0, QtCore.Qt.AlignTop)
        layout.addLayout(top)

        bottom = QtWidgets.QHBoxLayout()
        bottom.setSpacing(8)

        self.chip = _MiniChip("", "green")
        self.chip.hide()

        self.meta_label = QtWidgets.QLabel("—")
        self.meta_label.setObjectName("runtimeMeta")
        self.meta_label.setWordWrap(True)

        bottom.addWidget(self.chip, 0, QtCore.Qt.AlignTop)
        bottom.addWidget(self.meta_label, 1)
        layout.addLayout(bottom)

    def set_data(
        self,
        value: str,
        meta: str,
        chip_text: str = "",
        chip_kind: str = "green",
        tooltip: str = "",
    ):
        self.value_label.setText(str(value))
        self.meta_label.setText(str(meta))

        if chip_text:
            self.chip.set_state(chip_text, chip_kind)
            self.chip.show()
        else:
            self.chip.hide()

        if tooltip:
            self.setToolTip(tooltip)


class _ClearLogsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("Clear diagnostic logs")
        self.setMinimumWidth(500)
        self.resize(500, 330)
        self.setStyleSheet(DIALOG_QSS)
        self.setFont(QtGui.QFont(_pick_font_family(), 10))

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QtWidgets.QWidget()
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(22, 18, 21, 14)
        header_layout.setSpacing(12)

        title_col = QtWidgets.QVBoxLayout()
        title_col.setSpacing(4)

        title = QtWidgets.QLabel("Clear diagnostic logs?")
        title.setObjectName("dialogTitle")

        subtitle = QtWidgets.QLabel(
            "This removes operational diagnostics from the application log area."
        )
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)

        title_col.addWidget(title)
        title_col.addWidget(subtitle)

        close = QtWidgets.QToolButton()
        close.setObjectName("dialogClose")
        close.setText("×")
        close.clicked.connect(self.reject)
        _pointer(close)

        header_layout.addLayout(title_col, 1)
        header_layout.addWidget(close, 0, QtCore.Qt.AlignTop)
        root.addWidget(header)

        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setStyleSheet(f"background:{BORDER}; border:0px; max-height:1px;")
        root.addWidget(separator)

        body = QtWidgets.QWidget()
        body_layout = QtWidgets.QVBoxLayout(body)
        body_layout.setContentsMargins(22, 17, 22, 10)
        body_layout.setSpacing(11)

        warning_box = QtWidgets.QFrame()
        warning_box.setObjectName("warningBox")
        warning_layout = QtWidgets.QVBoxLayout(warning_box)
        warning_layout.setContentsMargins(12, 11, 12, 11)

        warning = QtWidgets.QLabel(
            "<b>Application logs and page timings will be cleared.</b><br>"
            "This can make troubleshooting recent application behaviour more difficult."
        )
        warning.setObjectName("warningText")
        warning.setWordWrap(True)
        warning_layout.addWidget(warning)

        safe_box = QtWidgets.QFrame()
        safe_box.setObjectName("safeBox")
        safe_layout = QtWidgets.QVBoxLayout(safe_box)
        safe_layout.setContentsMargins(12, 11, 12, 11)

        safe = QtWidgets.QLabel(
            "<b>Security audit records are not affected.</b><br>"
            "Audit data is stored separately and is intentionally excluded from "
            "the diagnostic-log clear operation."
        )
        safe.setObjectName("safeText")
        safe.setWordWrap(True)
        safe_layout.addWidget(safe)

        body_layout.addWidget(warning_box)
        body_layout.addWidget(safe_box)
        root.addWidget(body, 1)

        footer = QtWidgets.QWidget()
        footer_layout = QtWidgets.QHBoxLayout(footer)
        footer_layout.setContentsMargins(22, 10, 22, 18)
        footer_layout.setSpacing(9)
        footer_layout.addStretch(1)

        cancel = QtWidgets.QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        _pointer(cancel)

        clear = QtWidgets.QPushButton("Clear Diagnostic Logs")
        clear.setObjectName("dangerButton")
        clear.clicked.connect(self.accept)
        _pointer(clear)

        footer_layout.addWidget(cancel)
        footer_layout.addWidget(clear)
        root.addWidget(footer)


# ---------------------------------------------------------------------------
# Diagnostics page
# ---------------------------------------------------------------------------

class DiagnosticsPage(QtWidgets.QWidget):
    def __init__(self, actor="unknown", parent=None):
        super().__init__(parent)

        self.actor = str(actor or "unknown")
        self._font_family = _pick_font_family()
        self._mono_family = _mono_font_family()
        self._theme_restore_scheduled = False

        self._filter_timer = QtCore.QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(140)
        self._filter_timer.timeout.connect(self._refresh_log_view_only)

        self.setObjectName("diagnosticsPage")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setFont(QtGui.QFont(self._font_family, 10))
        self.installEventFilter(self)

        self._build_ui()
        self._force_local_theme()

    # ------------------------------- UI ---------------------------------

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 28)
        root.setSpacing(16)

        # Header
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(14)

        title_col = QtWidgets.QVBoxLayout()
        title_col.setSpacing(4)

        title = QtWidgets.QLabel("Application Diagnostics")
        title.setObjectName("pageTitle")

        subtitle = QtWidgets.QLabel(
            "Review application events and create a privacy-safe support report."
        )
        subtitle.setObjectName("pageSubtitle")

        title_col.addWidget(title)
        title_col.addWidget(subtitle)

        copy_button = QtWidgets.QPushButton("Copy Support Report")
        copy_button.clicked.connect(self.copy_report)
        _pointer(copy_button)

        export_button = QtWidgets.QPushButton("Export Support Report")
        export_button.setObjectName("primaryButton")
        export_button.clicked.connect(self.export_report)
        _pointer(export_button)

        header.addLayout(title_col, 1)
        header.addWidget(copy_button, 0, QtCore.Qt.AlignTop)
        header.addWidget(export_button, 0, QtCore.Qt.AlignTop)
        root.addLayout(header)

        # Runtime snapshot cards
        cards = QtWidgets.QHBoxLayout()
        cards.setSpacing(13)

        self.platform_card = _RuntimeCard("Platform", "OS", "blue")
        self.python_card = _RuntimeCard("Python Runtime", "PY", "purple")
        self.gpu_card = _RuntimeCard("GPU / CUDA", "GPU", "green")
        self.packages_card = _RuntimeCard("Tracked Packages", "PKG", "amber")

        cards.addWidget(self.platform_card, 1)
        cards.addWidget(self.python_card, 1)
        cards.addWidget(self.gpu_card, 1)
        cards.addWidget(self.packages_card, 1)

        root.addLayout(cards)

        # Privacy strip
        privacy = QtWidgets.QFrame()
        privacy.setObjectName("privacyStrip")

        privacy_layout = QtWidgets.QHBoxLayout(privacy)
        privacy_layout.setContentsMargins(14, 10, 14, 10)
        privacy_layout.setSpacing(10)

        privacy_icon = QtWidgets.QLabel("i")
        privacy_icon.setObjectName("privacyIcon")
        privacy_icon.setAlignment(QtCore.Qt.AlignCenter)

        privacy_text = QtWidgets.QVBoxLayout()
        privacy_text.setSpacing(2)

        privacy_title = QtWidgets.QLabel("Privacy-safe diagnostics")
        privacy_title.setObjectName("privacyTitle")

        privacy_subtitle = QtWidgets.QLabel(
            "Support reports redact secrets and URI credentials. Security audit records "
            "are stored separately and are never cleared from this page."
        )
        privacy_subtitle.setObjectName("privacySubtitle")
        privacy_subtitle.setWordWrap(True)

        privacy_text.addWidget(privacy_title)
        privacy_text.addWidget(privacy_subtitle)

        privacy_badge = _MiniChip("REDACTED SUPPORT DATA", "blue")

        privacy_layout.addWidget(privacy_icon)
        privacy_layout.addLayout(privacy_text, 1)
        privacy_layout.addWidget(privacy_badge)

        root.addWidget(privacy)

        # Diagnostic log card
        card = QtWidgets.QFrame()
        card.setObjectName("diagnosticCard")

        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        card_head = QtWidgets.QWidget()
        card_head_layout = QtWidgets.QHBoxLayout(card_head)
        card_head_layout.setContentsMargins(18, 15, 18, 15)
        card_head_layout.setSpacing(12)

        section_text = QtWidgets.QVBoxLayout()
        section_text.setSpacing(3)

        section_title = QtWidgets.QLabel("Diagnostic Event Log")
        section_title.setObjectName("sectionTitle")

        section_subtitle = QtWidgets.QLabel(
            "Operational application logs only. Use severity and text filters to isolate relevant events."
        )
        section_subtitle.setObjectName("sectionSubtitle")

        section_text.addWidget(section_title)
        section_text.addWidget(section_subtitle)

        self.record_badge = QtWidgets.QLabel("0 records")
        self.record_badge.setObjectName("recordBadge")
        self.record_badge.setAlignment(QtCore.Qt.AlignCenter)

        card_head_layout.addLayout(section_text, 1)
        card_head_layout.addWidget(self.record_badge)
        card_layout.addWidget(card_head)

        # Toolbar
        toolbar = QtWidgets.QWidget()
        toolbar.setObjectName("logToolbar")

        toolbar_layout = QtWidgets.QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(18, 11, 18, 11)
        toolbar_layout.setSpacing(9)

        self.level = QtWidgets.QComboBox()
        self.level.setObjectName("severityCombo")
        self.level.addItems(["ALL", "CRITICAL", "ERROR", "WARNING", "INFO"])
        self.level.currentTextChanged.connect(self._schedule_filter_refresh)
        _pointer(self.level)

        self.search = QtWidgets.QLineEdit()
        self.search.setObjectName("logSearch")
        self.search.setPlaceholderText("Filter by module or text...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._schedule_filter_refresh)

        refresh = QtWidgets.QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_logs)
        _pointer(refresh)

        clear = QtWidgets.QPushButton("Clear Diagnostic Logs")
        clear.setObjectName("dangerButton")
        clear.clicked.connect(self.clear_logs)
        _pointer(clear)

        toolbar_layout.addWidget(self.level)
        toolbar_layout.addWidget(self.search, 1)
        toolbar_layout.addWidget(refresh)
        toolbar_layout.addWidget(clear)

        card_layout.addWidget(toolbar)

        # Structured dark log console
        self.log_table = QtWidgets.QTableWidget(0, 4)
        self.log_table.setObjectName("logTable")
        self.log_table.setHorizontalHeaderLabels(["", "", "", ""])
        self.log_table.horizontalHeader().setObjectName("logHeader")
        self.log_table.horizontalHeader().hide()
        self.log_table.verticalHeader().hide()

        self.log_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.log_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.log_table.setFocusPolicy(QtCore.Qt.NoFocus)
        self.log_table.setShowGrid(False)
        self.log_table.setAlternatingRowColors(False)
        self.log_table.setWordWrap(False)
        self.log_table.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.log_table.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.log_table.verticalHeader().setDefaultSectionSize(31)
        self.log_table.setMinimumHeight(315)

        log_header = self.log_table.horizontalHeader()
        log_header.setSectionResizeMode(0, QtWidgets.QHeaderView.Fixed)
        log_header.setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)
        log_header.setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)
        log_header.setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)

        self._resize_log_columns()
        card_layout.addWidget(self.log_table, 1)

        # Compatibility alias for code that previously referenced `logs`.
        self.logs = self.log_table

        # Footer
        footer = QtWidgets.QWidget()
        footer.setObjectName("logFooter")

        footer_layout = QtWidgets.QHBoxLayout(footer)
        footer_layout.setContentsMargins(18, 9, 18, 9)
        footer_layout.setSpacing(10)

        self.status = QtWidgets.QLabel("Ready")
        self.status.setObjectName("footerStatus")

        footer_hint = QtWidgets.QLabel(
            "Support report includes system snapshot, recent diagnostic logs and recent page timings."
        )
        footer_hint.setObjectName("footerHint")
        footer_hint.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        footer_layout.addWidget(self.status)
        footer_layout.addStretch(1)
        footer_layout.addWidget(footer_hint)

        card_layout.addWidget(footer)
        root.addWidget(card, 1)

        # Compatibility with the former page.  The old summary QPlainTextEdit
        # was replaced by the four runtime cards, so expose a harmless alias.
        self.summary = None

    # ------------------------------ styling -----------------------------

    def _force_local_theme(self):
        self.setStyleSheet(PAGE_QSS)
        self.setFont(QtGui.QFont(self._font_family, 10))
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)

        # Console font is intentionally monospace and should not inherit the
        # host application's proportional font.
        if hasattr(self, "log_table"):
            self.log_table.setFont(QtGui.QFont(self._mono_family, 9))

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
        self._resize_log_columns()
        self._schedule_theme_restore()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_log_columns()

    def _resize_log_columns(self):
        if not hasattr(self, "log_table"):
            return

        viewport_width = self.log_table.viewport().width()
        if viewport_width <= 0:
            return

        # Keep the same visual rhythm as the approved HTML design.
        time_width = max(155, min(185, int(viewport_width * 0.145)))
        level_width = 74
        module_width = max(145, min(190, int(viewport_width * 0.15)))

        self.log_table.setColumnWidth(0, time_width)
        self.log_table.setColumnWidth(1, level_width)
        self.log_table.setColumnWidth(2, module_width)

    # --------------------------- page lifecycle -------------------------

    def activate(self):
        self._schedule_theme_restore()
        self.refresh_logs()

    # -------------------------- runtime snapshot ------------------------

    def _update_runtime_cards(self, snapshot: Dict):
        platform_raw = str(snapshot.get("platform") or "Unknown")
        python_version = str(snapshot.get("python") or "Unknown")
        gpu = snapshot.get("gpu") or {}
        packages = snapshot.get("packages") or {}

        self.platform_card.set_data(
            _friendly_platform(platform_raw),
            platform_raw,
            tooltip=platform_raw,
        )

        self.python_card.set_data(
            f"Python {python_version}",
            "Application runtime environment detected",
        )

        cuda_available = bool(gpu.get("cuda_available"))
        gpu_name = gpu.get("device") or ("No CUDA device" if not cuda_available else "CUDA device")
        cuda_version = gpu.get("cuda_version")

        if cuda_available:
            gpu_meta = f"CUDA {cuda_version}" if cuda_version else "CUDA runtime available"
            self.gpu_card.set_data(
                str(gpu_name),
                gpu_meta,
                chip_text="● AVAILABLE",
                chip_kind="green",
                tooltip=str(gpu_name),
            )
        else:
            detail = "CUDA unavailable"
            if gpu.get("error"):
                detail += f" · {gpu.get('error')}"
            self.gpu_card.set_data(
                str(gpu_name),
                detail,
                chip_text="NOT AVAILABLE",
                chip_kind="amber",
                tooltip=str(gpu_name),
            )

        package_names = list(packages.keys())
        package_versions = ", ".join(
            f"{name} {version}" for name, version in packages.items()
        )

        self.packages_card.set_data(
            f"{len(package_names)} packages",
            " · ".join(package_names),
            tooltip=package_versions,
        )

    # ------------------------------ logs --------------------------------

    def _schedule_filter_refresh(self):
        self._filter_timer.start()

    def refresh_logs(self):
        try:
            snapshot = system_snapshot()
            self._update_runtime_cards(snapshot)
            self._refresh_log_view_only()
        except Exception as exc:
            self.status.setText("Diagnostics refresh failed")
            QtWidgets.QMessageBox.critical(
                self,
                "Diagnostics refresh failed",
                str(exc),
            )

    def _refresh_log_view_only(self):
        try:
            lines = recent_log_entries(
                self.level.currentText(),
                self.search.text(),
                1000,
            )
            self._populate_log_table(lines)
        except Exception as exc:
            self.status.setText("Log refresh failed")
            QtWidgets.QMessageBox.critical(
                self,
                "Log refresh failed",
                str(exc),
            )

    def _populate_log_table(self, lines: List[str]):
        self.log_table.setUpdatesEnabled(False)
        try:
            self.log_table.clearSpans()
            self.log_table.setRowCount(0)

            if not lines:
                self.log_table.setRowCount(1)
                self.log_table.setSpan(0, 0, 1, 4)

                empty_item = QtWidgets.QTableWidgetItem(
                    "No matching diagnostic records."
                )
                empty_item.setForeground(QtGui.QBrush(QtGui.QColor("#8090A7")))
                empty_item.setFont(QtGui.QFont(self._mono_family, 9))
                empty_item.setFlags(QtCore.Qt.ItemIsEnabled)

                self.log_table.setItem(0, 0, empty_item)
                self.log_table.setRowHeight(0, 42)

            else:
                self.log_table.setRowCount(len(lines))

                level_colors = {
                    "CRITICAL": "#FF7A88",
                    "ERROR": "#FF7A88",
                    "WARNING": "#F5BE68",
                    "INFO": "#73A1FF",
                    "DEBUG": "#9DABC0",
                }

                for row, raw in enumerate(lines):
                    timestamp, level, module, message = _parse_log_line(raw)

                    values = (timestamp, level, module, message)
                    colors = (
                        CONSOLE_MUTED,
                        level_colors.get(level, "#73A1FF"),
                        CONSOLE_MODULE,
                        CONSOLE_TEXT,
                    )

                    for column, (value, color) in enumerate(zip(values, colors)):
                        item = QtWidgets.QTableWidgetItem(str(value))
                        item.setForeground(QtGui.QBrush(QtGui.QColor(color)))
                        item.setFont(QtGui.QFont(self._mono_family, 9))

                        if column == 1:
                            font = item.font()
                            font.setBold(True)
                            item.setFont(font)

                        item.setFlags(QtCore.Qt.ItemIsEnabled)
                        item.setToolTip(str(raw))
                        self.log_table.setItem(row, column, item)

                    self.log_table.setRowHeight(row, 31)

            count = len(lines)
            suffix = "record" if count == 1 else "records"
            self.record_badge.setText(f"{count} {suffix}")
            self.status.setText(f"●  Showing {count} {suffix}")

        finally:
            self.log_table.setUpdatesEnabled(True)
            self.log_table.viewport().update()
            QtCore.QTimer.singleShot(0, self._resize_log_columns)

    # -------------------------- support report --------------------------

    def copy_report(self):
        try:
            text = json.dumps(build_support_report(), indent=2)
            QtWidgets.QApplication.clipboard().setText(text)

            record_audit_event(
                "support_report_copied",
                actor=self.actor,
            )

            self.status.setText("●  Redacted support report copied")

        except Exception as exc:
            self.status.setText("Support report copy failed")
            QtWidgets.QMessageBox.critical(
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

            self.status.setText(f"●  Support report exported: {path.name}")

            QtWidgets.QMessageBox.information(
                self,
                "Support report exported",
                f"Privacy-safe support report exported successfully.\n\n{path}",
            )

        except Exception as exc:
            self.status.setText("Support report export failed")
            QtWidgets.QMessageBox.critical(
                self,
                "Export failed",
                str(exc),
            )

    # ----------------------------- clearing -----------------------------

    def clear_logs(self):
        dialog = _ClearLogsDialog(self)

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return

        try:
            count = clear_diagnostic_logs()

            record_audit_event(
                "diagnostic_logs_cleared",
                actor=self.actor,
                details={"files": count},
            )

            self.refresh_logs()

            suffix = "file" if count == 1 else "files"
            self.status.setText(
                f"●  Cleared {count} diagnostic {suffix}; security audit records preserved"
            )

        except Exception as exc:
            self.status.setText("Diagnostic logs were not cleared")

            QtWidgets.QMessageBox.critical(
                self,
                "Logs were not cleared",
                str(exc),
            )
