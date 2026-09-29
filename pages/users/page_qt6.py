"""EYRES AI - PyQt6 User Management page.

This is the Qt6 migration of the existing administrator user-management flow.
The backend calls remain the same:
- Database.list_users()
- Database.create_managed_user()
- Database.set_user_role()
- Database.set_user_active()
- Database.admin_reset_password()
- Database.clear_user_lockout()
- record_audit_event()
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtProperty, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app_core.audit import record_audit_event
from app_core.rbac import ROLE_LABELS, ROLES
from db import Database


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


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _asset(name: str) -> str:
    return str(_root() / "ui" / "assets" / "user_icons" / name)


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
    return True


def _configure_combo_popup(combo: QComboBox) -> None:
    """Force a white, readable popup instead of inheriting Windows dark popup styling."""
    combo.setMaxVisibleItems(10)
    view = combo.view()
    view.setObjectName("UserComboPopup")
    view.setStyleSheet("""
        QAbstractItemView#UserComboPopup {
            background:#FFFFFF;
            color:#17263D;
            border:1px solid #AFC1D4;
            outline:0;
            padding:4px;
            selection-background-color:#E8F1FF;
            selection-color:#17263D;
            font-size:9.6px;
            font-weight:650;
        }
        QAbstractItemView#UserComboPopup::item {
            min-height:31px;
            padding:4px 9px;
            border-radius:5px;
        }
        QAbstractItemView#UserComboPopup::item:hover {
            background:#F0F5FF;
        }
    """)


class ChevronComboBox(QComboBox):
    """QComboBox with a permanently visible local SVG chevron.

    Windows/Qt native combo arrows can become very faint or disappear with
    custom QSS. This overlay keeps the dropdown affordance clear at all DPI
    scales while the popup remains a normal QComboBox popup.

    ``objectName`` is accepted explicitly because this is a Python subclass;
    unlike Qt's generated wrapper constructors, arbitrary Qt property keyword
    arguments are not automatically accepted by this custom __init__.
    """

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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        x = max(0, self.width() - self._arrow.width() - 3)
        y = max(0, (self.height() - self._arrow.height()) // 2)
        self._arrow.move(x, y)
        self._arrow.raise_()



class TiltIconButton(QPushButton):
    """Button icon motion matching the safe padded-canvas shell implementation."""

    def __init__(self, text: str, icon_name: str, parent=None, primary=False):
        super().__init__(text, parent)
        self._motion = 0.0
        self._hovered = False
        self._primary = bool(primary)
        self._normal = QtGui.QIcon(_asset(f"{icon_name}.svg"))
        self._active = QtGui.QIcon(_asset(f"{icon_name}_active.svg"))

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QtCore.QSize(33, 33))
        self.setMinimumHeight(38)

        self._anim = QtCore.QPropertyAnimation(self, b"iconMotion", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)
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
        icon = self._active if self._hovered else self._normal
        base = icon.pixmap(QtCore.QSize(19, 19))
        if self._primary:
            base = self._tint(base, "#FFFFFF")

        canvas = QtGui.QPixmap(34, 34)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(canvas)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.translate(17.0, 17.0 - (0.7 * self._motion))
        painter.rotate(-4.5 * self._motion)
        scale = 1.0 + (0.05 * self._motion)
        painter.scale(scale, scale)
        painter.drawPixmap(
            QtCore.QRectF(-9.5, -9.5, 19.0, 19.0),
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


class StatCard(QFrame):
    """Summary card with a subtle, non-clipping graphical-icon hover motion."""

    def __init__(self, caption: str, icon_name: str, kind: str, parent=None):
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setProperty("kind", kind)
        self.setMinimumHeight(82)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._motion = 0.0
        self._hovered = False
        self._normal = QtGui.QIcon(_asset(f"{icon_name}.svg"))
        self._active = QtGui.QIcon(_asset(f"{icon_name}_active.svg"))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 13, 11)
        layout.setSpacing(10)

        copy = QVBoxLayout()
        copy.setSpacing(3)
        caption_label = QLabel(caption.upper(), objectName="StatCaption")
        self.value_label = QLabel("0", objectName="StatValue")
        copy.addWidget(caption_label)
        copy.addWidget(self.value_label)
        copy.addStretch(1)
        layout.addLayout(copy, 1)

        self.icon_host = QLabel(objectName="StatIcon")
        self.icon_host.setProperty("kind", kind)
        self.icon_host.setFixedSize(42, 42)
        self.icon_host.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_host)

        self._anim = QtCore.QPropertyAnimation(self, b"iconMotion", self)
        self._anim.setDuration(185)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)
        self._refresh_icon()

    def set_value(self, value):
        self.value_label.setText(str(value))

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


class ChipLabel(QLabel):
    def __init__(self, text: str, kind: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("ChipLabel")
        self.setProperty("kind", kind)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)


class UserIdentityWidget(QFrame):
    def __init__(self, username: str, email: str, parent=None):
        super().__init__(parent)
        self.setObjectName("CellHost")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 3, 7, 3)
        layout.setSpacing(9)

        avatar = QLabel(_initials(username), objectName="UserAvatar")
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFixedSize(35, 35)

        copy = QVBoxLayout()
        copy.setSpacing(1)
        name = QLabel(str(username or "—"), objectName="UserName")
        email_label = QLabel(str(email or "—"), objectName="UserEmail")
        copy.addWidget(name)
        copy.addWidget(email_label)

        layout.addWidget(avatar)
        layout.addLayout(copy, 1)


class SecurityWidget(QFrame):
    def __init__(self, user: Dict, formatter, parent=None):
        super().__init__(parent)
        self.setObjectName("CellHost")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        box = QVBoxLayout(self)
        box.setContentsMargins(11, 3, 7, 3)
        box.setSpacing(1)

        failures = int(user.get("failed_login_count", 0) or 0)
        primary = QLabel(
            f"{failures} failed attempt{'s' if failures != 1 else ''}",
            objectName="SecurityPrimary",
        )
        box.addWidget(primary)

        locked_until = user.get("locked_until")
        if locked_until:
            secondary = QLabel(
                f"Locked until {formatter(locked_until)}",
                objectName="SecuritySecondary",
            )
            box.addWidget(secondary)


class BaseUserDialog(QDialog):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(title)
        self.setMinimumWidth(500)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame(objectName="DialogHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(20, 16, 16, 14)
        h.setSpacing(10)

        copy = QVBoxLayout()
        copy.setSpacing(3)
        copy.addWidget(QLabel(title, objectName="DialogTitle"))
        if subtitle:
            sub = QLabel(subtitle, objectName="DialogSubtitle")
            sub.setWordWrap(True)
            copy.addWidget(sub)

        close = QToolButton(objectName="DialogClose")
        close.setText("×")
        close.setFixedSize(32, 32)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.reject)

        h.addLayout(copy, 1)
        h.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        root.addWidget(header)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(20, 15, 20, 12)
        self.body_layout.setSpacing(10)
        root.addWidget(self.body, 1)

        footer = QFrame(objectName="DialogFooter")
        self.footer_layout = QHBoxLayout(footer)
        self.footer_layout.setContentsMargins(20, 11, 20, 15)
        self.footer_layout.setSpacing(8)
        self.footer_layout.addStretch(1)
        root.addWidget(footer)

        self.setStyleSheet(DIALOG_QSS)

    def add_field(self, title: str, widget: QWidget, helper: str = ""):
        group = QVBoxLayout()
        group.setSpacing(5)
        group.addWidget(QLabel(title, objectName="DialogFieldLabel"))
        group.addWidget(widget)
        if helper:
            label = QLabel(helper, objectName="DialogHelper")
            label.setWordWrap(True)
            group.addWidget(label)
        self.body_layout.addLayout(group)

    def add_user_summary(self, user: Dict):
        frame = QFrame(objectName="DialogUserSummary")
        row = QHBoxLayout(frame)
        row.setContentsMargins(10, 9, 10, 9)

        avatar = QLabel(_initials(user.get("username", "")), objectName="DialogAvatar")
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFixedSize(38, 38)

        copy = QVBoxLayout()
        copy.setSpacing(1)
        copy.addWidget(QLabel(str(user.get("username") or "—"), objectName="DialogUserName"))
        copy.addWidget(
            QLabel(
                str(
                    user.get("email")
                    or ROLE_LABELS.get(user.get("role"), user.get("role", ""))
                    or "—"
                ),
                objectName="DialogUserMeta",
            )
        )
        row.addWidget(avatar)
        row.addLayout(copy, 1)
        self.body_layout.addWidget(frame)


class CreateUserDialog(BaseUserDialog):
    def __init__(self, parent=None):
        super().__init__(
            "Create user",
            "Create an account and assign its initial access role.",
            parent,
        )
        self.resize(520, 535)

        self.username = QLineEdit()
        self.username.setPlaceholderText("Enter username")
        self.email = QLineEdit()
        self.email.setPlaceholderText("name@company.com")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Minimum 8 characters")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)

        password_host = QWidget()
        password_layout = QHBoxLayout(password_host)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.setSpacing(0)
        password_layout.addWidget(self.password, 1)

        self.eye_button = QToolButton(objectName="PasswordEye")
        self.eye_button.setText("SHOW")
        self.eye_button.setFixedWidth(50)
        self.eye_button.clicked.connect(self._toggle_password)
        password_layout.addWidget(self.eye_button)

        self.role = ChevronComboBox()
        for value in ROLES:
            self.role.addItem(ROLE_LABELS[value], value)
        _configure_combo_popup(self.role)

        operator = self.role.findData("operator")
        if operator >= 0:
            self.role.setCurrentIndex(operator)

        self.role_info = QFrame(objectName="RoleInfo")
        rib = QVBoxLayout(self.role_info)
        rib.setContentsMargins(10, 8, 10, 8)
        rib.setSpacing(2)
        self.role_title = QLabel(objectName="RoleInfoTitle")
        self.role_text = QLabel(objectName="RoleInfoText")
        self.role_text.setWordWrap(True)
        rib.addWidget(self.role_title)
        rib.addWidget(self.role_text)

        self.add_field("Username", self.username)
        self.add_field("Email", self.email)
        self.add_field(
            "Temporary password",
            password_host,
            "Minimum 8 characters. The administrator can reset this later.",
        )
        self.add_field("Role", self.role)
        self.body_layout.addWidget(self.role_info)
        self.body_layout.addStretch(1)

        cancel = QPushButton("Cancel", objectName="DialogSecondaryButton")
        cancel.clicked.connect(self.reject)
        self.create_button = QPushButton("Create User", objectName="DialogPrimaryButton")
        self.create_button.clicked.connect(self.accept)
        self.footer_layout.addWidget(cancel)
        self.footer_layout.addWidget(self.create_button)

        self.username.textChanged.connect(self._update_submit)
        self.password.textChanged.connect(self._update_submit)
        self.role.currentIndexChanged.connect(self._update_role_info)
        self._update_role_info()
        self._update_submit()

    def _toggle_password(self):
        hidden = self.password.echoMode() == QLineEdit.EchoMode.Password
        self.password.setEchoMode(
            QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password
        )
        self.eye_button.setText("HIDE" if hidden else "SHOW")

    def _update_submit(self):
        self.create_button.setEnabled(
            bool(self.username.text().strip()) and len(self.password.text()) >= 8
        )

    def _update_role_info(self):
        role = str(self.role.currentData() or "operator")
        self.role_title.setText(ROLE_LABELS.get(role, role))
        self.role_text.setText(ROLE_DESCRIPTIONS.get(role, "Platform access role."))

    def values(self):
        return (
            self.username.text().strip(),
            self.password.text(),
            self.email.text().strip(),
            self.role.currentData(),
        )


class ChangeRoleDialog(BaseUserDialog):
    def __init__(self, user: Dict, parent=None):
        super().__init__(
            "Change role",
            "Update the access level assigned to this user.",
            parent,
        )
        self.resize(500, 390)
        self.user = user
        self.add_user_summary(user)

        self.role = ChevronComboBox()
        if str(user.get("username")) == "admin":
            self.role.addItem(ROLE_LABELS.get("admin", "Administrator"), "admin")
        else:
            for value in ROLES:
                self.role.addItem(ROLE_LABELS[value], value)
        _configure_combo_popup(self.role)

        current = self.role.findData(user.get("role"))
        if current >= 0:
            self.role.setCurrentIndex(current)

        self.add_field("New role", self.role)

        self.role_info = QFrame(objectName="RoleInfo")
        rib = QVBoxLayout(self.role_info)
        rib.setContentsMargins(10, 8, 10, 8)
        rib.setSpacing(2)
        self.role_title = QLabel(objectName="RoleInfoTitle")
        self.role_text = QLabel(objectName="RoleInfoText")
        self.role_text.setWordWrap(True)
        rib.addWidget(self.role_title)
        rib.addWidget(self.role_text)
        self.body_layout.addWidget(self.role_info)
        self.body_layout.addStretch(1)

        cancel = QPushButton("Cancel", objectName="DialogSecondaryButton")
        cancel.clicked.connect(self.reject)
        update = QPushButton("Update Role", objectName="DialogPrimaryButton")
        update.clicked.connect(self.accept)
        self.footer_layout.addWidget(cancel)
        self.footer_layout.addWidget(update)

        self.role.currentIndexChanged.connect(self._update_role_info)
        self._update_role_info()

    def _update_role_info(self):
        role = str(self.role.currentData() or "operator")
        self.role_title.setText(ROLE_LABELS.get(role, role))
        self.role_text.setText(ROLE_DESCRIPTIONS.get(role, "Platform access role."))

    def selected_role(self):
        return self.role.currentData()


class ResetPasswordDialog(BaseUserDialog):
    def __init__(self, user: Dict, parent=None):
        super().__init__(
            "Reset password",
            "Set a new temporary password for the selected account.",
            parent,
        )
        self.resize(500, 355)
        self.add_user_summary(user)

        self.password = QLineEdit()
        self.password.setPlaceholderText("Minimum 8 characters")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)

        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.password, 1)

        eye = QToolButton(objectName="PasswordEye")
        eye.setText("SHOW")
        eye.setFixedWidth(50)
        row.addWidget(eye)

        def toggle():
            hidden = self.password.echoMode() == QLineEdit.EchoMode.Password
            self.password.setEchoMode(
                QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password
            )
            eye.setText("HIDE" if hidden else "SHOW")

        eye.clicked.connect(toggle)

        self.add_field(
            "New temporary password",
            host,
            "Use at least 8 characters. Failed-login count and lockout are cleared after reset.",
        )
        self.body_layout.addStretch(1)

        cancel = QPushButton("Cancel", objectName="DialogSecondaryButton")
        cancel.clicked.connect(self.reject)
        self.submit = QPushButton("Reset Password", objectName="DialogPrimaryButton")
        self.submit.clicked.connect(self.accept)
        self.submit.setEnabled(False)
        self.password.textChanged.connect(
            lambda value: self.submit.setEnabled(len(value) >= 8)
        )

        self.footer_layout.addWidget(cancel)
        self.footer_layout.addWidget(self.submit)

    def value(self):
        return self.password.text()


class ActionConfirmDialog(BaseUserDialog):
    def __init__(
        self,
        title: str,
        message: str,
        confirm_text: str,
        danger=False,
        parent=None,
    ):
        super().__init__(title, message, parent)
        self.resize(450, 220)
        self.body_layout.addStretch(1)

        cancel = QPushButton("Cancel", objectName="DialogSecondaryButton")
        cancel.clicked.connect(self.reject)
        confirm = QPushButton(
            confirm_text,
            objectName="DialogDangerButton" if danger else "DialogPrimaryButton",
        )
        confirm.clicked.connect(self.accept)
        self.footer_layout.addWidget(cancel)
        self.footer_layout.addWidget(confirm)


class UserManagementPageQt6(QWidget):
    toast_requested = pyqtSignal(str, str)

    def __init__(self, user: dict | None = None, parent=None):
        super().__init__(parent)
        self.user = user or {}
        self.actor = str(self.user.get("username") or "unknown")
        self.database = Database()

        self._users = []
        self._selected_username: Optional[str] = None
        self._first_refresh = True

        self.setObjectName("UserManagementPageQt6")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._build_ui()
        self._apply_style()

        QtCore.QTimer.singleShot(0, lambda: self.refresh_data(animate=False))

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addStretch(1)

        self.create_button = TiltIconButton(
            "Create User", "plus", primary=True
        )
        self.create_button.setObjectName("CreateButton")
        self.create_button.setMinimumWidth(132)
        self.create_button.clicked.connect(self.create_user)
        action_row.addWidget(self.create_button)
        root.addLayout(action_row)

        stats = QGridLayout()
        stats.setSpacing(9)

        self.total_card = StatCard("Total Users", "users", "blue")
        self.active_card = StatCard("Active", "active", "green")
        self.locked_card = StatCard("Locked", "locked", "amber")
        self.admin_card = StatCard("Administrators", "admin", "purple")

        stats.addWidget(self.total_card, 0, 0)
        stats.addWidget(self.active_card, 0, 1)
        stats.addWidget(self.locked_card, 0, 2)
        stats.addWidget(self.admin_card, 0, 3)

        for col in range(4):
            stats.setColumnStretch(col, 1)

        root.addLayout(stats)

        card = QFrame(objectName="UsersCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        head = QFrame(objectName="UsersHeader")
        head_row = QHBoxLayout(head)
        head_row.setContentsMargins(15, 11, 15, 11)
        head_row.setSpacing(9)

        copy = QVBoxLayout()
        copy.setSpacing(2)
        copy.addWidget(QLabel("Users", objectName="SectionTitle"))
        copy.addWidget(
            QLabel(
                "Manage people who can access the EYRES inspection platform.",
                objectName="SectionSubtitle",
            )
        )
        head_row.addLayout(copy, 1)

        search_host = QFrame(objectName="SearchHost")
        sh = QHBoxLayout(search_host)
        sh.setContentsMargins(8, 4, 8, 4)
        sh.setSpacing(6)

        search_icon = QLabel()
        search_icon.setPixmap(QtGui.QIcon(_asset("search.svg")).pixmap(15, 15))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search users...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setFrame(False)
        self.search_box.textChanged.connect(self._apply_filters)

        sh.addWidget(search_icon)
        sh.addWidget(self.search_box, 1)
        search_host.setFixedWidth(240)
        head_row.addWidget(search_host)

        self.role_filter = ChevronComboBox(objectName="FilterCombo")
        self.role_filter.setMinimumWidth(145)
        self.role_filter.addItem("All roles", None)
        for role in ROLES:
            self.role_filter.addItem(ROLE_LABELS[role], role)
        _configure_combo_popup(self.role_filter)
        self.role_filter.currentIndexChanged.connect(self._apply_filters)
        head_row.addWidget(self.role_filter)

        self.status_filter = ChevronComboBox(objectName="FilterCombo")
        self.status_filter.setMinimumWidth(130)
        self.status_filter.addItem("All status", None)
        self.status_filter.addItem("Active", "active")
        self.status_filter.addItem("Disabled", "disabled")
        self.status_filter.addItem("Locked", "locked")
        _configure_combo_popup(self.status_filter)
        self.status_filter.currentIndexChanged.connect(self._apply_filters)
        head_row.addWidget(self.status_filter)

        card_layout.addWidget(head)

        self.table = QTableWidget(0, 6)
        self.table.setObjectName("UsersTable")
        self.table.setHorizontalHeaderLabels(
            ["USER", "ROLE", "STATUS", "SECURITY", "LAST LOGIN", ""]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setMouseTracking(True)
        self.table.setMinimumHeight(260)

        header = self.table.horizontalHeader()
        header.setMinimumHeight(38)
        header.setHighlightSections(False)
        header.setStretchLastSection(False)
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        for col in range(6):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)

        self.table.itemSelectionChanged.connect(self._selection_changed)
        card_layout.addWidget(self.table, 1)

        self.empty_state = QFrame(objectName="EmptyState")
        empty_box = QVBoxLayout(self.empty_state)
        empty_box.setContentsMargins(16, 16, 16, 16)
        empty_box.setSpacing(2)
        title = QLabel("No users found", objectName="EmptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QLabel(
            "Try changing the search text or filters.",
            objectName="EmptyText",
        )
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_box.addWidget(title)
        empty_box.addWidget(text)
        self.empty_state.hide()
        card_layout.addWidget(self.empty_state)

        self.selection_bar = QFrame(objectName="SelectionBar")
        sb = QHBoxLayout(self.selection_bar)
        sb.setContentsMargins(14, 8, 14, 8)
        sb.setSpacing(7)

        self.selected_avatar = QLabel("US", objectName="SelectedAvatar")
        self.selected_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.selected_avatar.setFixedSize(34, 34)

        selected_copy = QVBoxLayout()
        selected_copy.setSpacing(1)
        self.selected_title = QLabel("Selected user", objectName="SelectedTitle")
        self.selected_meta = QLabel("", objectName="SelectedMeta")
        selected_copy.addWidget(self.selected_title)
        selected_copy.addWidget(self.selected_meta)

        sb.addWidget(self.selected_avatar)
        sb.addLayout(selected_copy)
        sb.addStretch(1)

        self.change_role_button = self._action_button("Change Role", "role")
        self.reset_password_button = self._action_button(
            "Reset Password", "password"
        )
        self.toggle_active_button = self._action_button(
            "Disable User", "disable"
        )
        self.clear_lockout_button = self._action_button(
            "Clear Lockout", "unlock"
        )

        self.change_role_button.clicked.connect(self.change_role)
        self.reset_password_button.clicked.connect(self.reset_password)
        self.toggle_active_button.clicked.connect(self.toggle_active)
        self.clear_lockout_button.clicked.connect(self.clear_lockout)

        sb.addWidget(self.change_role_button)
        sb.addWidget(self.reset_password_button)
        sb.addWidget(self.toggle_active_button)
        sb.addWidget(self.clear_lockout_button)

        self.selection_bar.hide()
        card_layout.addWidget(self.selection_bar)

        root.addWidget(card, 1)

    def _action_button(self, text, icon_name):
        button = QPushButton(text, objectName="SelectionButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setIcon(QtGui.QIcon(_asset(f"{icon_name}.svg")))
        button.setIconSize(QtCore.QSize(15, 15))
        return button

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def refresh_data(self, animate=True):
        try:
            previous = self._selected_username
            self._users = list(self.database.list_users())
            self._populate_table()
            self._update_stats()
            self._apply_filters()

            if previous:
                self._reselect_username(previous)
            else:
                self._selection_changed()

            if not self._first_refresh:
                self.toast_requested.emit(
                    "Users refreshed",
                    f"{len(self._users)} account record(s) loaded.",
                )
            self._first_refresh = False

        except Exception as exc:
            self._show_error("Users could not be loaded", exc)

    def refresh_context(self):
        self.refresh_data(animate=False)

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

                key_item = QTableWidgetItem("")
                key_item.setData(Qt.ItemDataRole.UserRole, username)
                self.table.setItem(row, 0, key_item)
                self.table.setCellWidget(
                    row, 0, UserIdentityWidget(username, email)
                )

                role_item = QTableWidgetItem("")
                role_item.setData(Qt.ItemDataRole.UserRole, role)
                self.table.setItem(row, 1, role_item)
                self.table.setCellWidget(
                    row,
                    1,
                    self._left_cell(
                        ChipLabel(
                            ROLE_LABELS.get(role, role),
                            ROLE_CHIP_KIND.get(role, "gray"),
                        )
                    ),
                )

                status_text = (
                    "Locked"
                    if locked
                    else ("Active" if active else "Disabled")
                )
                status_kind = (
                    "amber"
                    if locked
                    else ("green" if active else "gray")
                )
                self.table.setItem(row, 2, QTableWidgetItem(""))
                self.table.setCellWidget(
                    row,
                    2,
                    self._left_cell(
                        ChipLabel(status_text, status_kind)
                    ),
                )

                self.table.setItem(row, 3, QTableWidgetItem(""))
                self.table.setCellWidget(
                    row, 3, SecurityWidget(user, self._date)
                )

                self.table.setItem(row, 4, QTableWidgetItem(""))
                last = QLabel(
                    self._date(user.get("last_login_at")),
                    objectName="SecondaryCell",
                )
                self.table.setCellWidget(
                    row, 4, self._left_cell(last)
                )

                menu_button = QToolButton(objectName="RowMenuButton")
                menu_button.setText("⋯")
                menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
                menu_button.setPopupMode(
                    QToolButton.ToolButtonPopupMode.InstantPopup
                )
                menu_button.setMenu(self._build_row_menu(row))
                self.table.setItem(row, 5, QTableWidgetItem(""))
                self.table.setCellWidget(
                    row, 5, self._center_cell(menu_button, transparent=False)
                )
        finally:
            self.table.blockSignals(False)
            QtCore.QTimer.singleShot(0, self._resize_columns)

    def _build_row_menu(self, row):
        menu = QMenu(self)
        menu.setObjectName("UserRowMenu")

        def bind(callback):
            def run():
                self._select_row(row)
                callback()
            return run

        menu.addAction("Change Role", bind(self.change_role))
        menu.addAction("Reset Password", bind(self.reset_password))

        user = self._users[row] if 0 <= row < len(self._users) else {}
        menu.addAction(
            "Disable User" if user.get("active", True) else "Enable User",
            bind(self.toggle_active),
        )
        menu.addSeparator()
        menu.addAction("Clear Lockout", bind(self.clear_lockout))
        return menu

    def _update_stats(self):
        total = len(self._users)
        active = sum(
            1
            for user in self._users
            if bool(user.get("active", True)) and not _is_locked(user)
        )
        locked = sum(1 for user in self._users if _is_locked(user))
        admins = sum(
            1 for user in self._users
            if user.get("role") == "admin"
        )

        self.total_card.set_value(total)
        self.active_card.set_value(active)
        self.locked_card.set_value(locked)
        self.admin_card.set_value(admins)

    def _apply_filters(self):
        if not hasattr(self, "table"):
            return

        query = self.search_box.text().strip().lower()
        role_filter = self.role_filter.currentData()
        status_filter = self.status_filter.currentData()

        visible = 0
        for row, user in enumerate(self._users):
            username = str(user.get("username", ""))
            email = str(user.get("email", ""))
            role = str(user.get("role") or "operator")
            role_label = ROLE_LABELS.get(role, role)
            active = bool(user.get("active", True))
            locked = _is_locked(user)

            text_match = (
                not query
                or query in f"{username} {email} {role_label}".lower()
            )
            role_match = role_filter is None or role == role_filter

            if status_filter is None:
                status_match = True
            elif status_filter == "locked":
                status_match = locked
            elif status_filter == "active":
                status_match = active and not locked
            else:
                status_match = not active

            show = text_match and role_match and status_match
            self.table.setRowHidden(row, not show)
            if show:
                visible += 1

        self.empty_state.setVisible(visible == 0)

        row = self.table.currentRow()
        if row >= 0 and self.table.isRowHidden(row):
            self.table.clearSelection()
            self._selection_changed()

    def _resize_columns(self):
        if not hasattr(self, "table"):
            return

        width = self.table.viewport().width()
        if width <= 0:
            return

        menu_width = 52
        usable = max(0, width - menu_width - 4)
        ratios = (0.28, 0.18, 0.12, 0.19, 0.23)
        minimums = (260, 145, 110, 180, 190)

        widths = [
            max(minimums[i], int(usable * ratios[i]))
            for i in range(5)
        ]

        for col, value in enumerate(widths):
            self.table.setColumnWidth(col, value)
        self.table.setColumnWidth(5, menu_width)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def _select_row(self, row):
        if row < 0 or row >= self.table.rowCount():
            return
        self.table.setCurrentCell(row, 0)
        self.table.selectRow(row)
        self._selection_changed()

    def _selection_changed(self):
        row = self.table.currentRow()
        if row < 0 or self.table.isRowHidden(row):
            self._selected_username = None
            self.selection_bar.hide()
            return

        item = self.table.item(row, 0)
        username = (
            item.data(Qt.ItemDataRole.UserRole)
            if item is not None
            else None
        )
        user = self._user_by_username(str(username)) if username else None
        if not user:
            self._selected_username = None
            self.selection_bar.hide()
            return

        self._selected_username = str(user.get("username", ""))
        self.selected_avatar.setText(_initials(self._selected_username))
        self.selected_title.setText(self._selected_username)

        role_label = ROLE_LABELS.get(
            user.get("role"),
            user.get("role", "operator"),
        )
        status = (
            "Locked"
            if _is_locked(user)
            else ("Active" if bool(user.get("active", True)) else "Disabled")
        )
        self.selected_meta.setText(f"{role_label} · {status}")

        active = bool(user.get("active", True))
        self.toggle_active_button.setText(
            "Disable User" if active else "Enable User"
        )
        self.toggle_active_button.setIcon(
            QtGui.QIcon(
                _asset("disable.svg" if active else "enable.svg")
            )
        )
        self.toggle_active_button.setProperty("danger", active)

        failures = int(user.get("failed_login_count", 0) or 0)
        self.clear_lockout_button.setEnabled(
            bool(_is_locked(user) or failures)
        )

        for button in (
            self.change_role_button,
            self.reset_password_button,
            self.toggle_active_button,
        ):
            button.setEnabled(True)

        self.toggle_active_button.style().unpolish(
            self.toggle_active_button
        )
        self.toggle_active_button.style().polish(
            self.toggle_active_button
        )
        self.selection_bar.show()

    def _reselect_username(self, username):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if (
                item
                and str(item.data(Qt.ItemDataRole.UserRole))
                == str(username)
                and not self.table.isRowHidden(row)
            ):
                self._select_row(row)
                return

        self._selected_username = None
        self.selection_bar.hide()

    def _selected(self, notify=True):
        username = self._selected_username
        if not username:
            row = self.table.currentRow()
            if row >= 0:
                item = self.table.item(row, 0)
                if item is not None:
                    username = item.data(Qt.ItemDataRole.UserRole)

        user = (
            self._user_by_username(str(username))
            if username
            else None
        )
        if not user and notify:
            QMessageBox.information(
                self,
                "Select user",
                "Select one user first.",
            )
        return user

    def _user_by_username(self, username):
        for user in self._users:
            if str(user.get("username", "")) == str(username):
                return user
        return None

    # ------------------------------------------------------------------
    # Actions - same backend behavior as the existing page.
    # ------------------------------------------------------------------
    def create_user(self):
        dialog = CreateUserDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        username, password, email, role = dialog.values()
        try:
            self.database.create_managed_user(
                username, password, email, role
            )
            self._audit(
                "user_created",
                username,
                details={"role": role},
            )
            self.refresh_data(animate=False)
            self._reselect_username(username)
            self.toast_requested.emit(
                "User created",
                f"{username} was added successfully.",
            )
        except Exception as exc:
            self._audit(
                "user_created",
                username,
                "failed",
                {"reason": type(exc).__name__},
            )
            self._show_error("User was not created", exc)

    def change_role(self):
        user = self._selected()
        if not user:
            return

        dialog = ChangeRoleDialog(user, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        role = dialog.selected_role()
        if not role or role == user.get("role"):
            return

        try:
            self.database.set_user_role(user["username"], role)
            self._audit(
                "user_role_changed",
                user["username"],
                details={"role": role},
            )
            username = user["username"]
            self.refresh_data(animate=False)
            self._reselect_username(username)
            self.toast_requested.emit(
                "Role updated",
                f"{username} is now {ROLE_LABELS.get(role, role)}.",
            )
        except Exception as exc:
            self._show_error("Role was not changed", exc)

    def toggle_active(self):
        user = self._selected()
        if not user:
            return

        active = not bool(user.get("active", True))
        action = "Enable" if active else "Disable"

        dialog = ActionConfirmDialog(
            f"{action} user",
            (
                f"{action} {user['username']}? "
                + (
                    "The account will be allowed to sign in again."
                    if active
                    else "The account will no longer be able to sign in."
                )
            ),
            f"{action} User",
            danger=not active,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            self.database.set_user_active(
                user["username"], active
            )
            self._audit(
                "user_status_changed",
                user["username"],
                details={"active": active},
            )
            username = user["username"]
            self.refresh_data(animate=False)
            self._reselect_username(username)
            self.toast_requested.emit(
                f"User {'enabled' if active else 'disabled'}",
                username,
            )
        except Exception as exc:
            self._show_error("Status was not changed", exc)

    def reset_password(self):
        user = self._selected()
        if not user:
            return

        dialog = ResetPasswordDialog(user, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            self.database.admin_reset_password(
                user["username"],
                dialog.value(),
            )
            self._audit(
                "admin_password_reset",
                user["username"],
            )
            username = user["username"]
            self.refresh_data(animate=False)
            self._reselect_username(username)
            self.toast_requested.emit(
                "Password reset",
                f"Password updated for {username}.",
            )
        except Exception as exc:
            self._show_error("Password was not reset", exc)

    def clear_lockout(self):
        user = self._selected()
        if not user:
            return

        try:
            self.database.clear_user_lockout(
                user["username"]
            )
            self._audit(
                "user_lockout_cleared",
                user["username"],
            )
            username = user["username"]
            self.refresh_data(animate=False)
            self._reselect_username(username)
            self.toast_requested.emit(
                "Lockout cleared",
                f"{username} can retry sign-in.",
            )
        except Exception as exc:
            self._show_error("Lockout was not cleared", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _audit(
        self,
        action,
        target,
        status="success",
        details=None,
    ):
        payload = {"target_user": target}
        payload.update(details or {})
        try:
            record_audit_event(
                action,
                actor=self.actor,
                status=status,
                details=payload,
            )
        except Exception:
            pass

    @staticmethod
    def _date(value):
        if isinstance(value, datetime):
            return value.strftime("%b %d, %Y · %I:%M %p")
        return str(value or "—")

    def _show_error(self, title, exc):
        QMessageBox.critical(
            self,
            title,
            f"{title}\n\n{exc}",
        )

    def _left_cell(self, widget):
        host = QFrame(objectName="CellHost")
        host.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        row = QHBoxLayout(host)
        row.setContentsMargins(10, 0, 7, 0)
        row.addWidget(
            widget,
            0,
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignVCenter,
        )
        row.addStretch(1)
        return host

    def _center_cell(self, widget, transparent=True):
        host = QFrame(objectName="CellHost")
        if transparent:
            host.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                True,
            )
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(widget, 0, Qt.AlignmentFlag.AlignCenter)
        return host

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_columns()

    # ------------------------------------------------------------------
    # QSS
    # ------------------------------------------------------------------
    def _apply_style(self):
        self.setStyleSheet(PAGE_QSS)


PAGE_QSS = """
QWidget#UserManagementPageQt6 {
    background:#EAF1F8;
    color:#101A2D;
}
QWidget#UserManagementPageQt6 QLabel {
    background:transparent;
    border:0;
}

QPushButton#CreateButton {
    background:#2868E8;
    color:#FFFFFF;
    border:1px solid #2868E8;
    border-radius:9px;
    padding:0 13px 0 8px;
    text-align:left;
    font-size:9.8px;
    font-weight:800;
}
QPushButton#CreateButton:hover {
    background:#1F58CC;
    border-color:#1F58CC;
}

QFrame#StatCard {
    background:#FFFFFF;
    border:1px solid #AFC1D4;
    border-radius:12px;
}
QFrame#StatCard:hover {
    border-color:#8EACD0;
}
QLabel#StatCaption {
    color:#60728A;
    font-size:8.8px;
    font-weight:850;
    letter-spacing:.55px;
}
QLabel#StatValue {
    color:#101A2D;
    font-size:21px;
    font-weight:850;
}
QLabel#StatIcon {
    border-radius:10px;
}
QLabel#StatIcon[kind="blue"] {
    background:#E8F1FF;
}
QLabel#StatIcon[kind="green"] {
    background:#E8F8F1;
}
QLabel#StatIcon[kind="amber"] {
    background:#FFF5D9;
}
QLabel#StatIcon[kind="purple"] {
    background:#F2EDFF;
}

QFrame#UsersCard {
    background:#FFFFFF;
    border:1px solid #A9BED3;
    border-radius:14px;
}
QFrame#UsersHeader {
    background:#FFFFFF;
    border:0;
    border-bottom:1px solid #CED9E5;
}
QLabel#SectionTitle {
    color:#101A2D;
    font-size:12.6px;
    font-weight:840;
}
QLabel#SectionSubtitle {
    color:#66788E;
    font-size:9.0px;
    font-weight:650;
}

QFrame#SearchHost {
    background:#FFFFFF;
    border:1px solid #A6BBD1;
    border-radius:8px;
}
QFrame#SearchHost:focus-within {
    border-color:#2868E8;
}
QFrame#SearchHost QLineEdit {
    background:#FFFFFF;
    color:#17263D;
    border:0;
    font-size:9.8px;
}

QComboBox#FilterCombo,
QDialog QComboBox {
    min-height:35px;
    background:#FFFFFF;
    color:#17263D;
    border:1px solid #A6BBD1;
    border-radius:8px;
    padding:0 28px 0 9px;
    font-size:9.5px;
    font-weight:750;
}
QComboBox#FilterCombo:hover,
QDialog QComboBox:hover {
    border-color:#8DAAC8;
}
QComboBox#FilterCombo:focus,
QDialog QComboBox:focus {
    border-color:#2868E8;
}
QComboBox::drop-down {
    border:0;
    width:30px;
}
QComboBox::down-arrow {
    image:none;
    width:0;
    height:0;
}
QLabel#ComboChevron {
    background:transparent;
    border:0;
}

QTableWidget#UsersTable {
    background:#FFFFFF;
    color:#2C3E56;
    border:0;
    gridline-color:#E3EAF2;
    selection-background-color:#EEF4FF;
    selection-color:#17263D;
    outline:0;
}
QTableWidget#UsersTable::item {
    border-bottom:1px solid #E3EAF2;
    padding:0;
}
QTableWidget#UsersTable::item:selected {
    background:#EEF4FF;
}
QHeaderView::section {
    background:#F3F7FB;
    color:#60728A;
    border:0;
    border-bottom:1px solid #C4D2E2;
    padding:0 11px;
    font-size:8.8px;
    font-weight:850;
}

QFrame#CellHost {
    background:transparent;
    border:0;
}
QLabel#UserAvatar, QLabel#SelectedAvatar, QLabel#DialogAvatar {
    background:#E8F1FF;
    color:#2868E8;
    border-radius:9px;
    font-size:10px;
    font-weight:850;
}
QLabel#UserName {
    color:#17263D;
    font-size:10.2px;
    font-weight:820;
}
QLabel#UserEmail, QLabel#SecondaryCell {
    color:#66788E;
    font-size:8.8px;
}
QLabel#SecurityPrimary {
    color:#66788E;
    font-size:8.9px;
}
QLabel#SecuritySecondary {
    color:#B26B00;
    font-size:8.3px;
}

QLabel#ChipLabel {
    min-height:24px;
    max-height:24px;
    border-radius:12px;
    padding:0 9px;
    font-size:8.8px;
    font-weight:850;
}
QLabel#ChipLabel[kind="blue"] {
    background:#E8F1FF;
    color:#2868E8;
}
QLabel#ChipLabel[kind="green"] {
    background:#E8F8F1;
    color:#07965D;
}
QLabel#ChipLabel[kind="amber"] {
    background:#FFF5D9;
    color:#A66300;
}
QLabel#ChipLabel[kind="purple"] {
    background:#F2EDFF;
    color:#7047D7;
}
QLabel#ChipLabel[kind="gray"] {
    background:#F0F3F7;
    color:#65748C;
}

QToolButton#RowMenuButton {
    min-width:30px;
    max-width:30px;
    min-height:30px;
    max-height:30px;
    background:transparent;
    color:#65748C;
    border:0;
    border-radius:8px;
    font-size:18px;
    font-weight:700;
}
QToolButton#RowMenuButton:hover {
    background:#EFF4FA;
}

QFrame#EmptyState {
    background:#FFFFFF;
    border:0;
    border-top:1px solid #E3EAF2;
}
QLabel#EmptyTitle {
    color:#17263D;
    font-size:11px;
    font-weight:820;
}
QLabel#EmptyText {
    color:#66788E;
    font-size:8.5px;
}

QFrame#SelectionBar {
    background:#F2F6FF;
    border:0;
    border-top:1px solid #C8D6E5;
}
QLabel#SelectedTitle {
    color:#17263D;
    font-size:9.5px;
    font-weight:820;
}
QLabel#SelectedMeta {
    color:#60728A;
    font-size:8.3px;
}

QPushButton#SelectionButton {
    min-height:34px;
    background:#FFFFFF;
    color:#405873;
    border:1px solid #A6BBD1;
    border-radius:8px;
    padding:0 10px;
    font-size:8.9px;
    font-weight:760;
}
QPushButton#SelectionButton:hover {
    background:#EEF4FF;
}
QPushButton#SelectionButton[danger="true"] {
    color:#C93450;
    border-color:#DDAAB4;
    background:#FFF9FA;
}
QPushButton#SelectionButton:disabled {
    color:#98A6B7;
    background:#F2F5F8;
    border-color:#D7E0EA;
}

QMenu#UserRowMenu {
    background:#FFFFFF;
    color:#17263D;
    border:1px solid #AFC1D4;
    padding:5px;
}
QMenu#UserRowMenu::item {
    padding:7px 22px 7px 10px;
    border-radius:6px;
}
QMenu#UserRowMenu::item:selected {
    background:#E8F1FF;
    color:#17263D;
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
QScrollBar:horizontal {
    background:transparent;
    height:8px;
    margin:2px;
}
QScrollBar::handle:horizontal {
    background:#BECBDD;
    border-radius:4px;
    min-width:28px;
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width:0;
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
    border-bottom:1px solid #CED9E5;
}
QFrame#DialogFooter {
    background:#FFFFFF;
    border:0;
    border-top:1px solid #CED9E5;
}
QLabel#DialogTitle {
    color:#101A2D;
    font-size:14px;
    font-weight:850;
}
QLabel#DialogSubtitle {
    color:#60728A;
    font-size:9.1px;
}
QToolButton#DialogClose {
    background:#F0F3F7;
    color:#65748C;
    border:0;
    border-radius:8px;
    font-size:17px;
}
QToolButton#DialogClose:hover {
    background:#E3EAF2;
}
QLabel#DialogFieldLabel {
    color:#405873;
    font-size:9.0px;
    font-weight:760;
}
QLabel#DialogHelper {
    color:#718197;
    font-size:8.3px;
}

QDialog QLineEdit {
    min-height:37px;
    background:#FFFFFF;
    color:#17263D;
    border:1px solid #A6BBD1;
    border-radius:8px;
    padding:0 9px;
    font-size:9.8px;
}
QDialog QLineEdit:focus {
    border-color:#2868E8;
}
QToolButton#PasswordEye {
    min-height:37px;
    background:#FFFFFF;
    color:#2868E8;
    border:1px solid #A6BBD1;
    border-left:0;
    border-top-right-radius:8px;
    border-bottom-right-radius:8px;
    font-size:7.8px;
    font-weight:800;
}
QToolButton#PasswordEye:hover {
    background:#EEF4FF;
}

QFrame#RoleInfo, QFrame#DialogUserSummary {
    background:#F7FAFD;
    border:1px solid #C8D5E5;
    border-radius:9px;
}
QLabel#RoleInfoTitle, QLabel#DialogUserName {
    color:#17263D;
    font-size:9.4px;
    font-weight:820;
}
QLabel#RoleInfoText, QLabel#DialogUserMeta {
    color:#60728A;
    font-size:8.5px;
}

QPushButton#DialogSecondaryButton,
QPushButton#DialogPrimaryButton,
QPushButton#DialogDangerButton {
    min-height:36px;
    border-radius:8px;
    padding:0 12px;
    font-size:9.2px;
    font-weight:780;
}
QPushButton#DialogSecondaryButton {
    background:#FFFFFF;
    color:#405873;
    border:1px solid #A6BBD1;
}
QPushButton#DialogPrimaryButton {
    background:#2868E8;
    color:#FFFFFF;
    border:1px solid #2868E8;
}
QPushButton#DialogDangerButton {
    background:#FFF9FA;
    color:#C93450;
    border:1px solid #DDAAB4;
}
QPushButton#DialogPrimaryButton:disabled {
    background:#B8C9E8;
    border-color:#B8C9E8;
}
"""


UserManagementPage = UserManagementPageQt6
