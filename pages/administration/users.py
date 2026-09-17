"""Administrator-only user account management page.

Modern EYRES User Management UI matching the approved design preview.
Backend behaviour is intentionally preserved:
- create managed users
- change roles
- enable / disable accounts
- reset passwords
- clear lockouts
- refresh/list users
- existing audit events

This page owns its local theme so the host application's global stylesheet does
not flatten the approved design when navigating away and back.
"""

from datetime import datetime
from typing import Dict, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from app_core.audit import record_audit_event
from app_core.rbac import ROLE_LABELS, ROLES
from db import Database


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


ROLE_DESCRIPTIONS = {
    "admin": "Full platform access including users, maintenance and diagnostics.",
    "operator": "Run inspections and use production workflows without administration access.",
    "quality_engineer": "Review inspection results, quality records and reporting workflows.",
    "maintenance": "Access maintenance, diagnostics and machine-support functions.",
    "ai_engineer": "Access AI configuration, model training and advanced inspection tooling.",
}

ROLE_CHIP_KIND = {
    "admin": "purple",
    "operator": "blue",
    "quality_engineer": "green",
    "maintenance": "amber",
    "ai_engineer": "purple",
}


def _pick_font_family() -> str:
    """Prefer the Figma font but stay safe on normal Windows deployments."""
    try:
        families = set(QtGui.QFontDatabase().families())
        for candidate in ("Inter", "Segoe UI Variable Text", "Segoe UI"):
            if candidate in families:
                return candidate
    except Exception:
        pass
    return "Segoe UI"


def _initials(username: str) -> str:
    value = str(username or "U").strip()
    if not value:
        return "U"
    parts = [part for part in value.replace("_", " ").split() if part]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return value[:2].upper()


def _is_locked(user: Dict) -> bool:
    value = user.get("locked_until")
    if not value:
        return False
    if isinstance(value, datetime):
        return value > datetime.utcnow()
    # A non-empty unparsed lockout value should still be presented as locked.
    return True


def _button_cursor(widget: QtWidgets.QWidget) -> None:
    widget.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))


# ---------------------------------------------------------------------------
# Local styles
# ---------------------------------------------------------------------------

PAGE_QSS = f"""
QWidget#userManagementPage {{
    background: {BG};
    color: {TEXT};
}}

QWidget#userManagementPage QLabel {{
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

QFrame#statCard,
QFrame#usersCard {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QLabel#statCaption {{
    color: {MUTED};
    font-size: 10px;
    font-weight: 700;
}}
QLabel#statValue {{
    color: {TEXT};
    font-size: 24px;
    font-weight: 700;
}}
QLabel#statIcon {{
    border-radius: 10px;
    min-width: 38px;
    max-width: 38px;
    min-height: 38px;
    max-height: 38px;
    font-size: 13px;
    font-weight: 700;
}}
QLabel#statIcon[statKind="blue"] {{ background: {BLUE_SOFT}; color: {BLUE}; }}
QLabel#statIcon[statKind="green"] {{ background: {GREEN_SOFT}; color: {GREEN}; }}
QLabel#statIcon[statKind="amber"] {{ background: {AMBER_SOFT}; color: {AMBER}; }}
QLabel#statIcon[statKind="purple"] {{ background: {PURPLE_SOFT}; color: {PURPLE}; }}

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
    padding: 0px 14px;
    border-radius: 9px;
    border: 1px solid {FIELD_BORDER};
    background: {CARD};
    color: {TEXT};
    font-size: 11px;
    font-weight: 600;
}}
QPushButton:hover {{ background: #F8FAFD; border-color: #ADC0E4; }}
QPushButton:pressed {{ background: #EEF3FA; }}
QPushButton:disabled {{ color: #9BA8BC; background: #F4F6F9; border-color: #E2E7EF; }}

QPushButton#primaryButton {{
    background: {BLUE};
    border-color: {BLUE};
    color: white;
    font-weight: 700;
}}
QPushButton#primaryButton:hover {{ background: {BLUE_DARK}; border-color: {BLUE_DARK}; }}
QPushButton#primaryButton:pressed {{ background: #1245BD; border-color: #1245BD; }}

QPushButton#dangerButton {{
    color: {RED};
    background: #FFF9FA;
    border-color: #F1CDD2;
}}
QPushButton#dangerButton:hover {{ background: {RED_SOFT}; border-color: #E9B5BD; }}

QToolButton#rowMenuButton {{
    background: {CARD};
    color: {TEXT};
    border: 1px solid {FIELD_BORDER};
    border-radius: 9px;
    font-weight: 700;
}}
QToolButton#rowMenuButton:hover {{ background: #F2F6FC; border-color: #ADC0E4; }}
QToolButton#rowMenuButton {{
    min-width: 30px;
    max-width: 30px;
    min-height: 30px;
    max-height: 30px;
    border-color: transparent;
    background: transparent;
    color: #66758D;
    font-size: 18px;
}}

QLineEdit,
QComboBox {{
    min-height: 36px;
    border: 1px solid {FIELD_BORDER};
    border-radius: 8px;
    background: {CARD};
    color: {TEXT};
    padding-left: 10px;
    padding-right: 10px;
    font-size: 11px;
}}
QLineEdit:focus,
QComboBox:focus {{
    border: 1px solid #8EAAF8;
}}
QComboBox::drop-down {{
    width: 28px;
    border: 0px;
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

QTableWidget#usersTable {{
    background: {CARD};
    alternate-background-color: {CARD};
    border: 0px;
    border-top: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    gridline-color: #EDF1F6;
    color: {TEXT};
    selection-background-color: #F0F5FF;
    selection-color: {TEXT};
    outline: 0px;
}}
QTableWidget#usersTable::item {{
    border-bottom: 1px solid #EDF1F6;
    padding: 0px 10px;
}}
QTableWidget#usersTable::item:selected {{
    background: #F0F5FF;
    color: {TEXT};
}}
QHeaderView::section {{
    background: #F5F8FC;
    color: #65748C;
    border: 0px;
    border-bottom: 1px solid {BORDER};
    padding: 0px 12px;
    font-size: 10px;
    font-weight: 700;
}}
QHeaderView {{
    background: #F5F8FC;
}}

QFrame#cellHost {{
    background: transparent;
    border: 0px;
}}
QLabel#avatarLabel {{
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
    border-radius: 9px;
    background: {BLUE_SOFT};
    color: {BLUE};
    font-size: 11px;
    font-weight: 700;
}}
QLabel#userNameLabel {{
    color: {TEXT};
    font-size: 11px;
    font-weight: 700;
}}
QLabel#userEmailLabel,
QLabel#secondaryCellLabel {{
    color: {MUTED};
    font-size: 10px;
}}
QLabel#securityPrimary {{
    color: {MUTED};
    font-size: 10px;
}}
QLabel#securitySecondary {{
    color: {AMBER};
    font-size: 9px;
}}

QLabel#chipLabel {{
    min-height: 24px;
    max-height: 24px;
    border-radius: 12px;
    padding-left: 9px;
    padding-right: 9px;
    font-size: 9px;
    font-weight: 700;
}}
QLabel#chipLabel[chipKind="blue"] {{ background: {BLUE_SOFT}; color: {BLUE}; }}
QLabel#chipLabel[chipKind="purple"] {{ background: {PURPLE_SOFT}; color: {PURPLE}; }}
QLabel#chipLabel[chipKind="green"] {{ background: {GREEN_SOFT}; color: {GREEN}; }}
QLabel#chipLabel[chipKind="amber"] {{ background: {AMBER_SOFT}; color: {AMBER}; }}
QLabel#chipLabel[chipKind="red"] {{ background: {RED_SOFT}; color: {RED}; }}
QLabel#chipLabel[chipKind="gray"] {{ background: #F0F3F7; color: #65748C; }}

QFrame#selectionBar {{
    background: #F4F7FF;
    border: 0px;
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

QLabel#emptyTitle {{
    color: {TEXT};
    font-size: 13px;
    font-weight: 700;
}}
QLabel#emptyText {{
    color: {MUTED};
    font-size: 10px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #CAD5E5;
    min-height: 30px;
    border-radius: 4px;
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #CAD5E5;
    min-width: 30px;
    border-radius: 4px;
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{ width: 0px; }}

QMenu {{
    background: white;
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 5px;
}}
QMenu::item {{
    padding: 7px 22px 7px 10px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background: {BLUE_SOFT};
    color: {TEXT};
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
    font-size: 18px;
    font-weight: 700;
    color: {TEXT};
}}
QLabel#dialogSubtitle {{
    font-size: 10px;
    color: {MUTED};
}}
QLabel#fieldLabel {{
    font-size: 10px;
    font-weight: 600;
    color: #485773;
}}
QLabel#helperLabel {{
    font-size: 9px;
    color: #7A89A0;
}}
QLabel#dialogAvatar {{
    min-width: 38px;
    max-width: 38px;
    min-height: 38px;
    max-height: 38px;
    border-radius: 9px;
    background: {BLUE_SOFT};
    color: {BLUE};
    font-size: 11px;
    font-weight: 700;
}}
QLabel#summaryUser {{
    font-size: 11px;
    font-weight: 700;
}}
QLabel#summaryMeta {{
    font-size: 9px;
    color: {MUTED};
}}
QFrame#dialogHeader {{
    background: white;
    border: 0px;
    border-bottom: 1px solid {BORDER};
}}
QFrame#dialogFooter {{
    background: white;
    border: 0px;
    border-top: 1px solid {BORDER};
}}
QFrame#userSummary,
QFrame#roleDescription {{
    background: #F7F9FD;
    border: 1px solid {BORDER};
    border-radius: 9px;
}}
QLabel#roleDescriptionTitle {{
    color: {TEXT};
    font-size: 10px;
    font-weight: 700;
}}
QLabel#roleDescriptionText {{
    color: #53617A;
    font-size: 9px;
}}

QLineEdit,
QComboBox {{
    min-height: 40px;
    border: 1px solid {FIELD_BORDER};
    border-radius: 8px;
    background: white;
    color: {TEXT};
    padding-left: 10px;
    padding-right: 10px;
    font-size: 11px;
}}
QLineEdit:focus,
QComboBox:focus {{ border-color: #8EAAF8; }}
QComboBox::drop-down {{ width: 28px; border: 0px; }}
QComboBox QAbstractItemView {{
    background: white;
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {BLUE_SOFT};
    selection-color: {TEXT};
    padding: 4px;
    outline: 0px;
}}

QPushButton {{
    min-height: 38px;
    padding: 0px 15px;
    border-radius: 9px;
    border: 1px solid {FIELD_BORDER};
    background: white;
    color: {TEXT};
    font-size: 11px;
    font-weight: 600;
}}
QPushButton:hover {{ background: #F8FAFD; border-color: #ADC0E4; }}
QPushButton#primaryButton {{
    background: {BLUE};
    border-color: {BLUE};
    color: white;
    font-weight: 700;
}}
QPushButton#primaryButton:hover {{ background: {BLUE_DARK}; border-color: {BLUE_DARK}; }}
QPushButton#dangerButton {{
    color: {RED};
    background: #FFF9FA;
    border-color: #F1CDD2;
}}
QPushButton:disabled {{ color: #9BA8BC; background: #F4F6F9; border-color: #E2E7EF; }}

QToolButton#dialogCloseButton,
QToolButton#passwordEyeButton {{
    border: 0px;
    background: #F2F5F9;
    color: #60708A;
    border-radius: 8px;
}}
QToolButton#dialogCloseButton {{
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
    font-size: 17px;
}}
QToolButton#passwordEyeButton {{
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
    background: transparent;
    font-size: 12px;
}}
QToolButton#dialogCloseButton:hover,
QToolButton#passwordEyeButton:hover {{ background: #E8EDF5; }}
"""


# ---------------------------------------------------------------------------
# Reusable UI pieces
# ---------------------------------------------------------------------------

class _StatCard(QtWidgets.QFrame):
    def __init__(self, caption: str, icon_text: str, kind: str, parent=None):
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setMinimumHeight(84)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 16, 14)
        layout.setSpacing(10)

        text_col = QtWidgets.QVBoxLayout()
        text_col.setSpacing(3)
        caption_label = QtWidgets.QLabel(caption.upper())
        caption_label.setObjectName("statCaption")
        self.value_label = QtWidgets.QLabel("0")
        self.value_label.setObjectName("statValue")
        text_col.addWidget(caption_label)
        text_col.addWidget(self.value_label)
        text_col.addStretch(1)

        icon = QtWidgets.QLabel(icon_text)
        icon.setObjectName("statIcon")
        icon.setProperty("statKind", kind)
        icon.setAlignment(QtCore.Qt.AlignCenter)

        layout.addLayout(text_col, 1)
        layout.addWidget(icon, 0, QtCore.Qt.AlignVCenter)

    def set_value(self, value) -> None:
        self.value_label.setText(str(value))


class _ChipLabel(QtWidgets.QLabel):
    def __init__(self, text: str, kind: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("chipLabel")
        self.setProperty("chipKind", kind)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)


class _UserIdentityWidget(QtWidgets.QFrame):
    def __init__(self, username: str, email: str, parent=None):
        super().__init__(parent)
        self.setObjectName("cellHost")
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 8, 4)
        layout.setSpacing(10)

        avatar = QtWidgets.QLabel(_initials(username))
        avatar.setObjectName("avatarLabel")
        avatar.setAlignment(QtCore.Qt.AlignCenter)
        avatar.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)

        text_col = QtWidgets.QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        name_label = QtWidgets.QLabel(str(username or "—"))
        name_label.setObjectName("userNameLabel")
        email_label = QtWidgets.QLabel(str(email or "—"))
        email_label.setObjectName("userEmailLabel")
        name_label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        email_label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        text_col.addWidget(name_label)
        text_col.addWidget(email_label)

        layout.addWidget(avatar)
        layout.addLayout(text_col, 1)


class _SecurityWidget(QtWidgets.QFrame):
    def __init__(self, user: Dict, date_formatter, parent=None):
        super().__init__(parent)
        self.setObjectName("cellHost")
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 4, 8, 4)
        layout.setSpacing(1)

        failures = int(user.get("failed_login_count", 0) or 0)
        primary = QtWidgets.QLabel(f"{failures} failed attempt{'s' if failures != 1 else ''}")
        primary.setObjectName("securityPrimary")
        primary.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(primary)

        locked_until = user.get("locked_until")
        if locked_until:
            secondary = QtWidgets.QLabel(f"Locked until {date_formatter(locked_until)}")
            secondary.setObjectName("securitySecondary")
            secondary.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
            layout.addWidget(secondary)
        else:
            layout.addStretch(1)


# ---------------------------------------------------------------------------
# Modern dialogs
# ---------------------------------------------------------------------------

class _BaseEyresDialog(QtWidgets.QDialog):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(title)
        self.setWindowFlag(QtCore.Qt.WindowContextHelpButtonHint, False)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.setFont(QtGui.QFont(_pick_font_family(), 10))
        self.setStyleSheet(DIALOG_QSS)

        self.root_layout = QtWidgets.QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        header = QtWidgets.QFrame()
        header.setObjectName("dialogHeader")
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(24, 20, 20, 16)
        header_layout.setSpacing(10)

        title_col = QtWidgets.QVBoxLayout()
        title_col.setSpacing(4)
        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("dialogTitle")
        title_col.addWidget(title_label)
        if subtitle:
            subtitle_label = QtWidgets.QLabel(subtitle)
            subtitle_label.setObjectName("dialogSubtitle")
            subtitle_label.setWordWrap(True)
            title_col.addWidget(subtitle_label)

        close_btn = QtWidgets.QToolButton()
        close_btn.setObjectName("dialogCloseButton")
        close_btn.setText("×")
        close_btn.clicked.connect(self.reject)
        _button_cursor(close_btn)

        header_layout.addLayout(title_col, 1)
        header_layout.addWidget(close_btn, 0, QtCore.Qt.AlignTop)
        self.root_layout.addWidget(header)

        self.body = QtWidgets.QWidget()
        self.body_layout = QtWidgets.QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(24, 18, 24, 10)
        self.body_layout.setSpacing(12)
        self.root_layout.addWidget(self.body, 1)

        self.footer = QtWidgets.QFrame()
        self.footer.setObjectName("dialogFooter")
        self.footer_layout = QtWidgets.QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(24, 15, 24, 18)
        self.footer_layout.setSpacing(9)
        self.footer_layout.addStretch(1)
        self.root_layout.addWidget(self.footer)

    @staticmethod
    def _field_label(text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    @staticmethod
    def _helper(text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setObjectName("helperLabel")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _make_button(text: str, object_name: str = "") -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(text)
        if object_name:
            button.setObjectName(object_name)
        _button_cursor(button)
        return button

    def _add_field(self, label_text: str, widget: QtWidgets.QWidget, helper: str = ""):
        box = QtWidgets.QVBoxLayout()
        box.setSpacing(6)
        box.addWidget(self._field_label(label_text))
        box.addWidget(widget)
        if helper:
            box.addWidget(self._helper(helper))
        self.body_layout.addLayout(box)

    def _add_user_summary(self, user: Dict):
        frame = QtWidgets.QFrame()
        frame.setObjectName("userSummary")
        layout = QtWidgets.QHBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        avatar = QtWidgets.QLabel(_initials(user.get("username", "")))
        avatar.setObjectName("dialogAvatar")
        avatar.setAlignment(QtCore.Qt.AlignCenter)

        text_col = QtWidgets.QVBoxLayout()
        text_col.setSpacing(2)
        name = QtWidgets.QLabel(str(user.get("username") or "—"))
        name.setObjectName("summaryUser")
        meta = QtWidgets.QLabel(
            str(user.get("email") or ROLE_LABELS.get(user.get("role"), user.get("role", "")) or "—")
        )
        meta.setObjectName("summaryMeta")
        text_col.addWidget(name)
        text_col.addWidget(meta)

        layout.addWidget(avatar)
        layout.addLayout(text_col, 1)
        self.body_layout.addWidget(frame)


class CreateUserDialog(_BaseEyresDialog):
    def __init__(self, parent=None):
        super().__init__(
            "Create user",
            "Create an account and assign its initial access role.",
            parent,
        )
        self.setMinimumWidth(520)
        self.resize(520, 545)

        self.username = QtWidgets.QLineEdit()
        self.username.setPlaceholderText("Enter username")
        self.email = QtWidgets.QLineEdit()
        self.email.setPlaceholderText("name@company.com")
        self.password = QtWidgets.QLineEdit()
        self.password.setPlaceholderText("Minimum 8 characters")
        self.password.setEchoMode(QtWidgets.QLineEdit.Password)

        password_host = QtWidgets.QWidget()
        password_layout = QtWidgets.QHBoxLayout(password_host)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.setSpacing(0)
        password_layout.addWidget(self.password, 1)
        self.eye_button = QtWidgets.QToolButton()
        self.eye_button.setObjectName("passwordEyeButton")
        self.eye_button.setText("SHOW")
        self.eye_button.setFixedWidth(48)
        self.eye_button.clicked.connect(self._toggle_password)
        _button_cursor(self.eye_button)
        password_layout.addWidget(self.eye_button)

        self.role = QtWidgets.QComboBox()
        for value in ROLES:
            self.role.addItem(ROLE_LABELS[value], value)
        # Operator is the least surprising default for a new production account.
        operator_index = self.role.findData("operator")
        if operator_index >= 0:
            self.role.setCurrentIndex(operator_index)

        self.role_desc = self._make_role_description()
        self.role.currentIndexChanged.connect(self._update_role_description)

        self._add_field("Username", self.username)
        self._add_field("Email", self.email)
        self._add_field(
            "Temporary password",
            password_host,
            "Minimum 8 characters. The administrator can reset this later.",
        )
        self._add_field("Role", self.role)
        self.body_layout.addWidget(self.role_desc)
        self.body_layout.addStretch(1)

        cancel = self._make_button("Cancel")
        cancel.clicked.connect(self.reject)
        self.create_button = self._make_button("Create User", "primaryButton")
        self.create_button.clicked.connect(self.accept)
        self.footer_layout.addWidget(cancel)
        self.footer_layout.addWidget(self.create_button)

        self.username.textChanged.connect(self._update_submit_state)
        self.password.textChanged.connect(self._update_submit_state)
        self._update_role_description()
        self._update_submit_state()

    def _toggle_password(self):
        hidden = self.password.echoMode() == QtWidgets.QLineEdit.Password
        self.password.setEchoMode(
            QtWidgets.QLineEdit.Normal if hidden else QtWidgets.QLineEdit.Password
        )
        self.eye_button.setText("HIDE" if hidden else "SHOW")

    def _make_role_description(self) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setObjectName("roleDescription")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(3)
        self.role_desc_title = QtWidgets.QLabel()
        self.role_desc_title.setObjectName("roleDescriptionTitle")
        self.role_desc_text = QtWidgets.QLabel()
        self.role_desc_text.setObjectName("roleDescriptionText")
        self.role_desc_text.setWordWrap(True)
        layout.addWidget(self.role_desc_title)
        layout.addWidget(self.role_desc_text)
        return frame

    def _update_role_description(self):
        role = str(self.role.currentData() or "operator")
        self.role_desc_title.setText(ROLE_LABELS.get(role, role))
        self.role_desc_text.setText(ROLE_DESCRIPTIONS.get(role, "Platform access role."))

    def _update_submit_state(self):
        ready = bool(self.username.text().strip()) and len(self.password.text()) >= 8
        self.create_button.setEnabled(ready)

    def values(self):
        return (
            self.username.text().strip(),
            self.password.text(),
            self.email.text().strip(),
            self.role.currentData(),
        )


class ChangeRoleDialog(_BaseEyresDialog):
    def __init__(self, user: Dict, parent=None):
        super().__init__(
            "Change role",
            "Update the access level assigned to this user.",
            parent,
        )
        self.user = user
        self.setMinimumWidth(480)
        self.resize(480, 400)
        self._add_user_summary(user)

        self.role = QtWidgets.QComboBox()
        for value in ROLES:
            self.role.addItem(ROLE_LABELS[value], value)
        current = self.role.findData(user.get("role"))
        if current >= 0:
            self.role.setCurrentIndex(current)

        # The database already enforces this rule. Mirroring it in the UI avoids
        # presenting an option that can never succeed.
        if user.get("username") == "admin":
            for index in range(self.role.count()):
                if self.role.itemData(index) != "admin":
                    item = self.role.model().item(index)
                    if item is not None:
                        item.setEnabled(False)

        self._add_field("New role", self.role)

        self.role_desc = QtWidgets.QFrame()
        self.role_desc.setObjectName("roleDescription")
        desc_layout = QtWidgets.QVBoxLayout(self.role_desc)
        desc_layout.setContentsMargins(12, 10, 12, 10)
        desc_layout.setSpacing(3)
        self.desc_title = QtWidgets.QLabel()
        self.desc_title.setObjectName("roleDescriptionTitle")
        self.desc_text = QtWidgets.QLabel()
        self.desc_text.setObjectName("roleDescriptionText")
        self.desc_text.setWordWrap(True)
        desc_layout.addWidget(self.desc_title)
        desc_layout.addWidget(self.desc_text)
        self.body_layout.addWidget(self.role_desc)
        self.body_layout.addStretch(1)

        cancel = self._make_button("Cancel")
        cancel.clicked.connect(self.reject)
        update = self._make_button("Update Role", "primaryButton")
        update.clicked.connect(self.accept)
        self.footer_layout.addWidget(cancel)
        self.footer_layout.addWidget(update)

        self.role.currentIndexChanged.connect(self._update_description)
        self._update_description()

    def _update_description(self):
        role = str(self.role.currentData() or "operator")
        self.desc_title.setText(ROLE_LABELS.get(role, role))
        self.desc_text.setText(ROLE_DESCRIPTIONS.get(role, "Platform access role."))

    def selected_role(self):
        return self.role.currentData()


class ResetPasswordDialog(_BaseEyresDialog):
    def __init__(self, user: Dict, parent=None):
        super().__init__(
            "Reset password",
            "Set a new temporary password for the selected account.",
            parent,
        )
        self.setMinimumWidth(480)
        self.resize(480, 360)
        self._add_user_summary(user)

        self.password = QtWidgets.QLineEdit()
        self.password.setEchoMode(QtWidgets.QLineEdit.Password)
        self.password.setPlaceholderText("Minimum 8 characters")

        password_host = QtWidgets.QWidget()
        password_layout = QtWidgets.QHBoxLayout(password_host)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.setSpacing(0)
        password_layout.addWidget(self.password, 1)
        self.eye_button = QtWidgets.QToolButton()
        self.eye_button.setObjectName("passwordEyeButton")
        self.eye_button.setText("SHOW")
        self.eye_button.setFixedWidth(48)
        self.eye_button.clicked.connect(self._toggle_password)
        _button_cursor(self.eye_button)
        password_layout.addWidget(self.eye_button)

        self._add_field(
            "New temporary password",
            password_host,
            "Use at least 8 characters. The user's failed-login count and lockout are cleared after reset.",
        )
        self.body_layout.addStretch(1)

        cancel = self._make_button("Cancel")
        cancel.clicked.connect(self.reject)
        self.submit = self._make_button("Reset Password", "primaryButton")
        self.submit.clicked.connect(self.accept)
        self.submit.setEnabled(False)
        self.password.textChanged.connect(
            lambda text: self.submit.setEnabled(len(text) >= 8)
        )
        self.footer_layout.addWidget(cancel)
        self.footer_layout.addWidget(self.submit)

    def _toggle_password(self):
        hidden = self.password.echoMode() == QtWidgets.QLineEdit.Password
        self.password.setEchoMode(
            QtWidgets.QLineEdit.Normal if hidden else QtWidgets.QLineEdit.Password
        )
        self.eye_button.setText("HIDE" if hidden else "SHOW")

    def value(self) -> str:
        return self.password.text()


class ActionConfirmDialog(_BaseEyresDialog):
    def __init__(self, title: str, message: str, confirm_text: str, danger=False, parent=None):
        super().__init__(title, message, parent)
        self.setMinimumWidth(430)
        self.resize(430, 220)
        self.body_layout.addStretch(1)

        cancel = self._make_button("Cancel")
        cancel.clicked.connect(self.reject)
        confirm = self._make_button(confirm_text, "dangerButton" if danger else "primaryButton")
        confirm.clicked.connect(self.accept)
        self.footer_layout.addWidget(cancel)
        self.footer_layout.addWidget(confirm)


# ---------------------------------------------------------------------------
# User management page
# ---------------------------------------------------------------------------

class UserManagementPage(QtWidgets.QWidget):
    """Account administration UI. Navigation policy restricts this page to admins."""

    def __init__(self, actor="unknown", parent=None):
        super().__init__(parent)
        self.actor = str(actor or "unknown")
        self.database = Database()
        self._users = []
        self._font_family = _pick_font_family()
        self._selected_username: Optional[str] = None
        self._theme_restore_scheduled = False

        self.setObjectName("userManagementPage")
        self.setFont(QtGui.QFont(self._font_family, 10))
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.installEventFilter(self)

        self._build_ui()
        self._force_local_theme()

    # ------------------------------ UI build ------------------------------

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 28)
        root.setSpacing(17)

        # Header
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(14)

        title_col = QtWidgets.QVBoxLayout()
        title_col.setSpacing(4)
        title = QtWidgets.QLabel("User Management")
        title.setObjectName("pageTitle")
        subtitle = QtWidgets.QLabel("Manage accounts, roles, access and account security.")
        subtitle.setObjectName("pageSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)

        create_button = QtWidgets.QPushButton("+  Create User")
        create_button.setObjectName("primaryButton")
        create_button.clicked.connect(self.create_user)
        _button_cursor(create_button)

        header.addLayout(title_col, 1)
        header.addWidget(create_button, 0, QtCore.Qt.AlignTop)
        root.addLayout(header)

        # Summary cards
        stats = QtWidgets.QHBoxLayout()
        stats.setSpacing(13)
        self.total_card = _StatCard("Total Users", "US", "blue")
        self.active_card = _StatCard("Active", "●", "green")
        self.locked_card = _StatCard("Locked", "LK", "amber")
        self.admin_card = _StatCard("Administrators", "AD", "purple")
        stats.addWidget(self.total_card, 1)
        stats.addWidget(self.active_card, 1)
        stats.addWidget(self.locked_card, 1)
        stats.addWidget(self.admin_card, 1)
        root.addLayout(stats)

        # Main users card
        users_card = QtWidgets.QFrame()
        users_card.setObjectName("usersCard")
        users_card_layout = QtWidgets.QVBoxLayout(users_card)
        users_card_layout.setContentsMargins(0, 0, 0, 0)
        users_card_layout.setSpacing(0)

        card_head = QtWidgets.QWidget()
        card_head_layout = QtWidgets.QHBoxLayout(card_head)
        card_head_layout.setContentsMargins(18, 15, 18, 15)
        card_head_layout.setSpacing(12)

        section_col = QtWidgets.QVBoxLayout()
        section_col.setSpacing(3)
        section_title = QtWidgets.QLabel("Users")
        section_title.setObjectName("sectionTitle")
        section_subtitle = QtWidgets.QLabel(
            "Manage people who can access the EYRES inspection platform."
        )
        section_subtitle.setObjectName("sectionSubtitle")
        section_col.addWidget(section_title)
        section_col.addWidget(section_subtitle)

        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setPlaceholderText("Search users...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setFixedWidth(230)
        self.search_box.textChanged.connect(self._apply_filters)

        self.role_filter = QtWidgets.QComboBox()
        self.role_filter.setFixedWidth(140)
        self.role_filter.addItem("All roles", None)
        for role in ROLES:
            self.role_filter.addItem(ROLE_LABELS[role], role)
        self.role_filter.currentIndexChanged.connect(self._apply_filters)

        self.status_filter = QtWidgets.QComboBox()
        self.status_filter.setFixedWidth(130)
        self.status_filter.addItem("All status", None)
        self.status_filter.addItem("Active", "active")
        self.status_filter.addItem("Disabled", "disabled")
        self.status_filter.addItem("Locked", "locked")
        self.status_filter.currentIndexChanged.connect(self._apply_filters)

        card_head_layout.addLayout(section_col, 1)
        card_head_layout.addWidget(self.search_box)
        card_head_layout.addWidget(self.role_filter)
        card_head_layout.addWidget(self.status_filter)
        users_card_layout.addWidget(card_head)

        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setObjectName("usersTable")
        self.table.setHorizontalHeaderLabels([
            "USER", "ROLE", "STATUS", "SECURITY", "LAST LOGIN", ""
        ])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setFocusPolicy(QtCore.Qt.NoFocus)
        self.table.setMouseTracking(True)
        self.table.setMinimumHeight(250)

        header_view = self.table.horizontalHeader()
        header_view.setMinimumHeight(38)
        header_view.setHighlightSections(False)
        header_view.setStretchLastSection(False)
        header_view.setDefaultAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)

        # Custom cell widgets are used for every visible table value.  Do not use
        # ResizeToContents here because it only measures the blank backing
        # QTableWidgetItems and can collapse/truncate the role/status columns.
        for column in range(6):
            header_view.setSectionResizeMode(column, QtWidgets.QHeaderView.Fixed)

        # Keep every header aligned with the visible content below it.
        for column in range(self.table.columnCount()):
            item = self.table.horizontalHeaderItem(column)
            if item is not None:
                item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)

        self._resize_table_columns()

        self.table.itemSelectionChanged.connect(self._selection_changed)
        users_card_layout.addWidget(self.table, 1)

        # Empty-state overlay row is represented as a normal widget under the table;
        # it only appears when search/filtering yields no rows.
        self.empty_state = QtWidgets.QWidget()
        empty_layout = QtWidgets.QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(16, 18, 16, 18)
        empty_layout.setSpacing(3)
        empty_title = QtWidgets.QLabel("No users found")
        empty_title.setObjectName("emptyTitle")
        empty_title.setAlignment(QtCore.Qt.AlignCenter)
        empty_text = QtWidgets.QLabel("Try changing the search text or filters.")
        empty_text.setObjectName("emptyText")
        empty_text.setAlignment(QtCore.Qt.AlignCenter)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_text)
        self.empty_state.hide()
        users_card_layout.addWidget(self.empty_state)

        # Selected-user action bar
        self.selection_bar = QtWidgets.QFrame()
        self.selection_bar.setObjectName("selectionBar")
        selection_layout = QtWidgets.QHBoxLayout(self.selection_bar)
        selection_layout.setContentsMargins(17, 10, 17, 10)
        selection_layout.setSpacing(8)

        self.selected_avatar = QtWidgets.QLabel("US")
        self.selected_avatar.setObjectName("avatarLabel")
        self.selected_avatar.setAlignment(QtCore.Qt.AlignCenter)

        selected_text = QtWidgets.QVBoxLayout()
        selected_text.setSpacing(1)
        self.selected_title = QtWidgets.QLabel("Selected user")
        self.selected_title.setObjectName("selectedTitle")
        self.selected_meta = QtWidgets.QLabel("")
        self.selected_meta.setObjectName("selectedMeta")
        selected_text.addWidget(self.selected_title)
        selected_text.addWidget(self.selected_meta)

        self.change_role_button = QtWidgets.QPushButton("Change Role")
        self.reset_password_button = QtWidgets.QPushButton("Reset Password")
        self.toggle_active_button = QtWidgets.QPushButton("Disable User")
        self.toggle_active_button.setObjectName("dangerButton")
        self.clear_lockout_button = QtWidgets.QPushButton("Clear Lockout")

        self.change_role_button.clicked.connect(self.change_role)
        self.reset_password_button.clicked.connect(self.reset_password)
        self.toggle_active_button.clicked.connect(self.toggle_active)
        self.clear_lockout_button.clicked.connect(self.clear_lockout)

        for button in (
            self.change_role_button, self.reset_password_button,
            self.toggle_active_button, self.clear_lockout_button,
        ):
            button.setMinimumHeight(34)
            _button_cursor(button)

        selection_layout.addWidget(self.selected_avatar)
        selection_layout.addLayout(selected_text)
        selection_layout.addStretch(1)
        selection_layout.addWidget(self.change_role_button)
        selection_layout.addWidget(self.reset_password_button)
        selection_layout.addWidget(self.toggle_active_button)
        selection_layout.addWidget(self.clear_lockout_button)
        self.selection_bar.hide()
        users_card_layout.addWidget(self.selection_bar)

        root.addWidget(users_card, 1)

    # ------------------------------ styling -------------------------------

    def _force_local_theme(self):
        """Reassert the page-local QSS after embedding/reparenting/navigation."""
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
        if watched is self and event.type() in (QtCore.QEvent.ParentChange, QtCore.QEvent.Show):
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
        """Keep headers and custom cell widgets aligned at every window size."""
        if not hasattr(self, "table"):
            return

        viewport_width = self.table.viewport().width()
        if viewport_width <= 0:
            return

        menu_width = 52
        usable = max(0, viewport_width - menu_width - 2)

        # Matches the approved design proportions:
        # User 28%, Role 18%, Status 12%, Security 19%, Last login 23%.
        ratios = (0.28, 0.18, 0.12, 0.19, 0.23)
        minimums = (280, 150, 115, 200, 220)

        widths = [
            max(minimums[i], int(usable * ratios[i]))
            for i in range(5)
        ]

        for column, width in enumerate(widths):
            self.table.setColumnWidth(column, width)
        self.table.setColumnWidth(5, menu_width)

    def activate(self):
        """Optional host hook; safe to call on navigation."""
        self._schedule_theme_restore()
        self.refresh_users()

    # --------------------------- data formatting --------------------------

    @staticmethod
    def _date(value):
        if isinstance(value, datetime):
            return value.strftime("%b %d, %Y · %I:%M %p")
        return str(value or "—")

    def _user_by_username(self, username: str) -> Optional[Dict]:
        for user in self._users:
            if str(user.get("username", "")) == str(username):
                return user
        return None

    def _selected(self, notify=True):
        row = self.table.currentRow()
        username = None
        if row >= 0:
            item = self.table.item(row, 0)
            if item is not None:
                username = item.data(QtCore.Qt.UserRole)
        if not username:
            username = self._selected_username
        user = self._user_by_username(str(username)) if username else None
        if not user and notify:
            QtWidgets.QMessageBox.information(self, "Select user", "Select one user first.")
        return user

    # ---------------------------- population ------------------------------

    def refresh_users(self):
        try:
            previous_username = self._selected_username
            self._users = self.database.list_users()
            self._populate_table()
            self._update_stats()
            self._apply_filters()

            if previous_username:
                self._reselect_username(previous_username)
            else:
                self._selection_changed()

            self._schedule_theme_restore()
        except Exception as exc:
            self._show_error("Users could not be loaded", exc)

    def _populate_table(self):
        self.table.blockSignals(True)
        try:
            self.table.clearContents()
            self.table.setRowCount(len(self._users))

            for row, user in enumerate(self._users):
                username = str(user.get("username", ""))
                email = str(user.get("email", ""))
                role = str(user.get("role") or "operator")
                active = bool(user.get("active", True))
                locked = _is_locked(user)

                self.table.setRowHeight(row, 60)

                # IMPORTANT:
                # QTableWidget paints the text of a QTableWidgetItem even when a
                # custom cell widget is placed on top of the same cell.  In the
                # host application/DPI combination this caused the underlying
                # item text and the custom widget text to be drawn together,
                # producing the duplicated/overlapping labels seen in the UI.
                #
                # Keep blank items purely for row selection + metadata and render
                # all visible content only through the custom cell widgets.
                key_item = QtWidgets.QTableWidgetItem("")
                key_item.setData(QtCore.Qt.UserRole, username)
                key_item.setData(QtCore.Qt.UserRole + 1, role)
                key_item.setData(QtCore.Qt.UserRole + 2, active)
                key_item.setData(QtCore.Qt.UserRole + 3, locked)
                self.table.setItem(row, 0, key_item)
                self.table.setCellWidget(row, 0, _UserIdentityWidget(username, email))

                role_item = QtWidgets.QTableWidgetItem("")
                role_item.setData(QtCore.Qt.UserRole, role)
                self.table.setItem(row, 1, role_item)
                role_host = self._center_chip(
                    _ChipLabel(ROLE_LABELS.get(role, role), ROLE_CHIP_KIND.get(role, "gray"))
                )
                self.table.setCellWidget(row, 1, role_host)

                status_text = "Locked" if locked else ("Active" if active else "Disabled")
                status_kind = "amber" if locked else ("green" if active else "gray")
                status_item = QtWidgets.QTableWidgetItem("")
                status_item.setData(QtCore.Qt.UserRole, status_text)
                self.table.setItem(row, 2, status_item)
                self.table.setCellWidget(
                    row, 2, self._center_chip(_ChipLabel(status_text, status_kind))
                )

                security_item = QtWidgets.QTableWidgetItem("")
                security_item.setData(
                    QtCore.Qt.UserRole, int(user.get("failed_login_count", 0) or 0)
                )
                self.table.setItem(row, 3, security_item)
                self.table.setCellWidget(row, 3, _SecurityWidget(user, self._date))

                last_login = self._date(user.get("last_login_at"))
                last_item = QtWidgets.QTableWidgetItem("")
                last_item.setData(QtCore.Qt.UserRole, last_login)
                self.table.setItem(row, 4, last_item)
                last_label = QtWidgets.QLabel(last_login)
                last_label.setObjectName("secondaryCellLabel")
                last_label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
                self.table.setCellWidget(row, 4, self._simple_cell(last_label))

                menu_button = QtWidgets.QToolButton()
                menu_button.setObjectName("rowMenuButton")
                menu_button.setText("⋯")
                menu_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
                menu_button.setMenu(self._build_row_menu(row))
                menu_button.clicked.connect(lambda _checked=False, r=row: self._select_row(r))
                _button_cursor(menu_button)
                self.table.setItem(row, 5, QtWidgets.QTableWidgetItem(""))
                self.table.setCellWidget(row, 5, self._center_widget(menu_button))
        finally:
            self.table.blockSignals(False)
            QtCore.QTimer.singleShot(0, self._resize_table_columns)

    def _build_row_menu(self, row: int) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self)

        def select_and(callback):
            return lambda _checked=False: (self._select_row(row), callback())

        menu.addAction("Change Role", select_and(self.change_role))
        menu.addAction("Reset Password", select_and(self.reset_password))
        user = self._users[row] if 0 <= row < len(self._users) else {}
        menu.addAction(
            "Disable User" if user.get("active", True) else "Enable User",
            select_and(self.toggle_active),
        )
        menu.addSeparator()
        menu.addAction("Clear Lockout", select_and(self.clear_lockout))
        return menu

    def _simple_cell(self, widget: QtWidgets.QWidget) -> QtWidgets.QFrame:
        host = QtWidgets.QFrame()
        host.setObjectName("cellHost")
        host.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        layout = QtWidgets.QHBoxLayout(host)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.addWidget(widget, 0, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        layout.addStretch(1)
        return host

    def _center_chip(self, chip: QtWidgets.QWidget) -> QtWidgets.QFrame:
        host = QtWidgets.QFrame()
        host.setObjectName("cellHost")
        host.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        layout = QtWidgets.QHBoxLayout(host)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.addWidget(chip, 0, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        layout.addStretch(1)
        return host

    def _center_widget(self, widget: QtWidgets.QWidget) -> QtWidgets.QFrame:
        host = QtWidgets.QFrame()
        host.setObjectName("cellHost")
        layout = QtWidgets.QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widget, 0, QtCore.Qt.AlignCenter)
        return host

    def _update_stats(self):
        total = len(self._users)
        active = sum(1 for user in self._users if bool(user.get("active", True)))
        locked = sum(1 for user in self._users if _is_locked(user))
        admins = sum(1 for user in self._users if user.get("role") == "admin")
        self.total_card.set_value(total)
        self.active_card.set_value(active)
        self.locked_card.set_value(locked)
        self.admin_card.set_value(admins)

    def _apply_filters(self):
        query = self.search_box.text().strip().lower()
        role_filter = self.role_filter.currentData()
        status_filter = self.status_filter.currentData()
        visible_count = 0

        for row, user in enumerate(self._users):
            username = str(user.get("username", ""))
            email = str(user.get("email", ""))
            role = str(user.get("role") or "operator")
            label = ROLE_LABELS.get(role, role)
            active = bool(user.get("active", True))
            locked = _is_locked(user)

            text_match = not query or query in f"{username} {email} {label}".lower()
            role_match = role_filter is None or role == role_filter
            if status_filter is None:
                status_match = True
            elif status_filter == "locked":
                status_match = locked
            elif status_filter == "active":
                status_match = active and not locked
            else:  # disabled
                status_match = not active

            visible = text_match and role_match and status_match
            self.table.setRowHidden(row, not visible)
            if visible:
                visible_count += 1

        self.empty_state.setVisible(visible_count == 0)

        current = self.table.currentRow()
        if current >= 0 and self.table.isRowHidden(current):
            self.table.clearSelection()
            self._selection_changed()

    def _select_row(self, row: int):
        if row < 0 or row >= self.table.rowCount():
            return
        self.table.setCurrentCell(row, 0)
        self.table.selectRow(row)
        self._selection_changed()

    def _reselect_username(self, username: str):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and str(item.data(QtCore.Qt.UserRole)) == str(username):
                if not self.table.isRowHidden(row):
                    self._select_row(row)
                    return
        self._selected_username = None
        self.selection_bar.hide()

    def _selection_changed(self):
        row = self.table.currentRow()
        if row < 0 or self.table.isRowHidden(row):
            self._selected_username = None
            self.selection_bar.hide()
            return

        item = self.table.item(row, 0)
        username = item.data(QtCore.Qt.UserRole) if item else None
        user = self._user_by_username(str(username)) if username else None
        if not user:
            self._selected_username = None
            self.selection_bar.hide()
            return

        self._selected_username = str(user.get("username", ""))
        self.selected_avatar.setText(_initials(self._selected_username))
        self.selected_title.setText(f"Selected: {self._selected_username}")
        role_label = ROLE_LABELS.get(user.get("role"), user.get("role", "operator"))
        email = str(user.get("email") or "No email")
        self.selected_meta.setText(f"{role_label} · {email}")

        active = bool(user.get("active", True))
        self.toggle_active_button.setText("Disable User" if active else "Enable User")
        self.toggle_active_button.setObjectName("dangerButton" if active else "primaryButton")
        self.toggle_active_button.style().unpolish(self.toggle_active_button)
        self.toggle_active_button.style().polish(self.toggle_active_button)

        self.selection_bar.show()

    # ------------------------------ actions -------------------------------

    def _audit(self, action, target, status="success", details=None):
        payload = {"target_user": target}
        payload.update(details or {})
        record_audit_event(action, actor=self.actor, status=status, details=payload)

    def _show_error(self, title, exc):
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Critical)
        box.setWindowTitle(title)
        box.setText(title)
        box.setInformativeText(str(exc))
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        box.setStyleSheet(DIALOG_QSS)
        box.exec_()

    def _show_info(self, title, message):
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Information)
        box.setWindowTitle(title)
        box.setText(title)
        box.setInformativeText(message)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        box.setStyleSheet(DIALOG_QSS)
        box.exec_()

    def create_user(self):
        dialog = CreateUserDialog(self)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        username, password, email, role = dialog.values()
        try:
            self.database.create_managed_user(username, password, email, role)
            self._audit("user_created", username, details={"role": role})
            self.refresh_users()
            self._reselect_username(username)
        except Exception as exc:
            self._audit("user_created", username, "failed", {"reason": type(exc).__name__})
            self._show_error("User was not created", exc)

    def change_role(self):
        user = self._selected()
        if not user:
            return

        dialog = ChangeRoleDialog(user, self)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        role = dialog.selected_role()
        if not role or role == user.get("role"):
            return

        try:
            self.database.set_user_role(user["username"], role)
            self._audit("user_role_changed", user["username"], details={"role": role})
            username = user["username"]
            self.refresh_users()
            self._reselect_username(username)
        except Exception as exc:
            self._show_error("Role was not changed", exc)

    def toggle_active(self):
        user = self._selected()
        if not user:
            return

        active = not bool(user.get("active", True))
        action = "Enable" if active else "Disable"
        danger = not active
        dialog = ActionConfirmDialog(
            f"{action} user",
            f"{action} {user['username']}? " + (
                "The account will no longer be able to sign in."
                if not active else
                "The account will be allowed to sign in again."
            ),
            f"{action} User",
            danger=danger,
            parent=self,
        )
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return

        try:
            self.database.set_user_active(user["username"], active)
            self._audit("user_status_changed", user["username"], details={"active": active})
            username = user["username"]
            self.refresh_users()
            self._reselect_username(username)
        except Exception as exc:
            self._show_error("Status was not changed", exc)

    def reset_password(self):
        user = self._selected()
        if not user:
            return

        dialog = ResetPasswordDialog(user, self)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        password = dialog.value()

        try:
            self.database.admin_reset_password(user["username"], password)
            self._audit("admin_password_reset", user["username"])
            username = user["username"]
            self.refresh_users()
            self._reselect_username(username)
            self._show_info("Password reset", "Password updated successfully.")
        except Exception as exc:
            self._show_error("Password was not reset", exc)

    def clear_lockout(self):
        user = self._selected()
        if not user:
            return
        try:
            self.database.clear_user_lockout(user["username"])
            self._audit("user_lockout_cleared", user["username"])
            username = user["username"]
            self.refresh_users()
            self._reselect_username(username)
        except Exception as exc:
            self._show_error("Lockout was not cleared", exc)
