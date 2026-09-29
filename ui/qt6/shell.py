"""Responsive PyQt6 main shell for the EYRES AI Inspection Platform."""
from __future__ import annotations

import time

from dataclasses import dataclass

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QLabel, QMainWindow, QPushButton, QScrollArea, QStackedWidget,
    QVBoxLayout, QHBoxLayout, QWidget, QSizePolicy,
)

from app_core.audit import record_audit_event
from app_core.rbac import ROLE_LABELS, SessionUser, can_access
from pages.dashboard.page_qt6 import DashboardPageQt6
from pages.machines.page_qt6 import MachinesPageQt6
from pages.projects.page_qt6 import ProjectsPageQt6
from pages.capture.page_qt6 import CapturePageQt6
from pages.annotation.page_qt6 import AnnotationPageQt6
from pages.augmentation.page_qt6 import AugmentationPageQt6
from pages.training.page_qt6 import TrainingPageQt6
from pages.live.page_qt6 import LivePageQt6
from pages.plc.page_qt6 import PLCPageQt6
from pages.users.page_qt6 import UserManagementPageQt6
from pages.maintenance.page_qt6 import SystemMaintenancePageQt6
from pages.diagnostics.page_qt6 import ApplicationDiagnosticsPageQt6
from .animations import fade_in
from .assets import asset_path
from .icons import icon, icon_pixmap
from .widgets import NavButton, PulseDot, SpinButton, ToastOverlay


@dataclass(frozen=True)
class PageSpec:
    key: str
    title: str
    subtitle: str
    icon_name: str
    permission: str
    section: str = "main"


PAGE_SPECS = (
    PageSpec("dashboard", "Dashboard", "Inspection operations and system readiness", "dashboard", "dashboard"),
    PageSpec("machines", "Machines", "Configure inspection cells, PLC connectivity and line endpoints", "machines", "machines"),
    PageSpec("projects", "Projects", "Organize inspection recipes, training pipelines and machine assignments", "projects", "projects"),
    PageSpec("capture", "Image Capturing", "Acquire and verify source images for inspection workflows", "capture", "capture"),
    PageSpec("annotation", "Annotation Tool", "Create, edit and verify inspection labels for the selected dataset.", "annotation", "annotation"),
    PageSpec("augmentation", "Augmentation Tool", "Prepare robust training data with controlled transformations", "augmentation", "augmentation"),
    PageSpec("training", "Model Training", "Configure and run production model training workflows", "training", "training"),
    PageSpec("live", "Live", "Run camera inference, review inspection results and monitor the active inspection session", "live", "live"),
    PageSpec("measurement", "Measurement Studio", "Calibrated dimensional inspection and measurement workflows", "measurement", "roi", "measurements"),
    PageSpec("plc", "PLC Live", "Guided PLC connection, tag selection and live monitoring", "plc", "plc", "admin"),
    PageSpec("users", "User Management", "Manage accounts, roles, access and account security", "users", "user_management", "admin"),
    PageSpec("maintenance", "System Maintenance", "Health checks, verified backups and dependency reporting", "maintenance", "system_maintenance", "admin"),
    PageSpec("diagnostics", "Application Diagnostics", "Review application events and create privacy-safe support reports", "diagnostics", "diagnostics", "admin"),
)


class CollapseButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle = 0.0
        self.setFixedSize(34, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Collapse / expand sidebar")
        self.setStyleSheet("""
        QPushButton {
            background:#FFFFFF; border:1px solid #CAD7E8; border-radius:11px;
        }
        QPushButton:hover { background:#EEF4FF; border-color:#AFC6EA; }
        QPushButton:pressed { background:#E5EEFF; }
        """)
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(22); shadow.setOffset(0, 7); shadow.setColor(QColor(38, 60, 96, 38))
        self.setGraphicsEffect(shadow)
        self._anim = QtCore.QPropertyAnimation(self, b"angle", self)
        self._anim.setDuration(280)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)

    def get_angle(self):
        return self._angle

    def set_angle(self, value):
        self._angle = float(value)
        self.update()

    angle = pyqtProperty(float, fget=get_angle, fset=set_angle)

    def set_collapsed(self, collapsed: bool, animate: bool = True):
        target = 180.0 if collapsed else 0.0
        if not animate:
            self.set_angle(target)
            return
        self._anim.stop()
        self._anim.setStartValue(self._angle)
        self._anim.setEndValue(target)
        self._anim.start()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.translate(self.width()/2, self.height()/2)
        painter.rotate(self._angle)
        pm = icon_pixmap("chevron", "#36506F", 17, prefer_legacy=False)
        painter.drawPixmap(-pm.width()//2, -pm.height()//2, pm)
        painter.end()


class SidebarWidget(QFrame):
    page_requested = pyqtSignal(str)
    logout_requested = pyqtSignal()

    def __init__(self, user: SessionUser, parent=None):
        super().__init__(parent)
        self.user = user
        self._compact = False
        self.buttons: dict[str, NavButton] = {}
        self.section_labels: list[QLabel] = []
        self.setObjectName("Qt6Sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build()
        self._apply_style()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.brand = QFrame(objectName="BrandHeader")
        self.brand.setFixedHeight(88)
        brand_layout = QHBoxLayout(self.brand)
        brand_layout.setContentsMargins(17, 12, 17, 12)
        brand_layout.setSpacing(0)

        self.logo = QLabel()
        self.logo.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.logo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._full_logo = QPixmap(str(asset_path("company_logo.png")))
        self._mark_logo = QPixmap(str(asset_path("app.png")))
        self._update_logo()
        brand_layout.addWidget(self.logo, 1)
        root.addWidget(self.brand)

        scroll = QScrollArea()
        scroll.setObjectName("SidebarScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.nav_host = QWidget()
        self.nav_layout = QVBoxLayout(self.nav_host)
        self.nav_layout.setContentsMargins(10, 14, 10, 10)
        self.nav_layout.setSpacing(3)
        scroll.setWidget(self.nav_host)
        root.addWidget(scroll, 1)

        current_section = "main"
        for spec in PAGE_SPECS:
            if not can_access(self.user.role, spec.permission):
                continue
            if spec.section != current_section:
                current_section = spec.section
                text = "MEASUREMENTS" if current_section == "measurements" else "PLC & ADMIN"
                label = QLabel(text, objectName="SidebarSection")
                self.section_labels.append(label)
                self.nav_layout.addSpacing(7)
                self.nav_layout.addWidget(label)
            button = NavButton(spec.title, spec.icon_name)
            button.clicked.connect(lambda _checked=False, key=spec.key: self.page_requested.emit(key))
            self.nav_layout.addWidget(button)
            self.buttons[spec.key] = button
        self.nav_layout.addStretch(1)

        footer = QFrame(objectName="SidebarFooter")
        fl = QVBoxLayout(footer)
        fl.setContentsMargins(10, 9, 10, 11)
        self.logout = QPushButton("  Logout")
        self.logout.setObjectName("LogoutButton")
        self.logout.setIcon(icon("power", "#C73750", 20, prefer_legacy=False))
        self.logout.setIconSize(QtCore.QSize(20,20))
        self.logout.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logout.setFixedHeight(43)
        self.logout.clicked.connect(self.logout_requested.emit)
        fl.addWidget(self.logout)
        root.addWidget(footer)

    def _apply_style(self):
        self.setStyleSheet("""
        QFrame#Qt6Sidebar { background:#FFFFFF; border:0; border-right:1px solid #C9D5E5; }
        QFrame#BrandHeader { background:#FFFFFF; border:0; border-bottom:1px solid #DDE5EF; }
        QScrollArea#SidebarScroll, QScrollArea#SidebarScroll > QWidget > QWidget { background:#FFFFFF; border:0; }
        QLabel#SidebarSection { color:#7B899E; font-size:10px; font-weight:800; letter-spacing:1px; padding:13px 12px 6px; }
        QFrame#SidebarFooter { background:#FFFFFF; border:0; }
        QPushButton#LogoutButton {
            background:#FFF4F6; color:#C73750; border:1px solid #FFD9E0; border-radius:11px;
            padding:0 12px; text-align:left; font-size:12px; font-weight:700;
        }
        QPushButton#LogoutButton:hover { background:#FFECEF; }
        QPushButton#LogoutButton:pressed { background:#FFE2E8; }
        QScrollBar:vertical { background:transparent; width:7px; margin:2px; }
        QScrollBar::handle:vertical { background:#D3DDEA; border-radius:3px; min-height:28px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
        """)

    def _update_logo(self):
        pm = self._mark_logo if self._compact else self._full_logo
        if pm.isNull():
            self.logo.clear()
            return
        target = QtCore.QSize(43,43) if self._compact else QtCore.QSize(180,62)
        self.logo.setPixmap(pm.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
        self.logo.setAlignment(
            Qt.AlignmentFlag.AlignCenter if self._compact
            else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

    def set_compact(self, compact: bool):
        self._compact = bool(compact)
        self.brand.setFixedHeight(74 if compact else 88)
        self._update_logo()
        for label in self.section_labels:
            label.setVisible(not compact)
        for button in self.buttons.values():
            button.set_compact(compact)
        self.logout.setText("" if compact else "  Logout")
        self.logout.setToolTip("Logout" if compact else "")
        self.logout.setStyleSheet(
            "QPushButton{background:#FFF4F6;color:#C73750;border:1px solid #FFD9E0;border-radius:11px;padding:0;}"
            "QPushButton:hover{background:#FFECEF;}" if compact else ""
        )

    def set_active(self, key: str):
        for page_key, button in self.buttons.items():
            button.setChecked(page_key == key)


class ProfileButton(QFrame):
    clicked = pyqtSignal()

    def __init__(self, user: SessionUser, parent=None):
        super().__init__(parent)
        self.user = user
        self.setObjectName("ProfileButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(45)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 4, 8, 4)
        layout.setSpacing(8)
        avatar = QLabel((user.username[:1] or "U").upper(), objectName="HeaderAvatar")
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFixedSize(34, 34)
        layout.addWidget(avatar)
        copy = QVBoxLayout(); copy.setSpacing(1)
        name = QLabel(user.username, objectName="HeaderUser")
        role = QLabel(ROLE_LABELS.get(user.role, user.role), objectName="HeaderRole")
        copy.addWidget(name); copy.addWidget(role)
        layout.addLayout(copy)
        chevron = QLabel("⌄", objectName="HeaderChevron")
        layout.addWidget(chevron)
        self.setStyleSheet("""
        QFrame#ProfileButton { background:#FFFFFF; border:1px solid #C5D2E3; border-radius:13px; }
        QLabel#HeaderAvatar { background:#2868E8; color:#FFFFFF; border-radius:10px; font-size:13px; font-weight:800; }
        QLabel#HeaderUser { color:#172033; font-size:11px; font-weight:750; }
        QLabel#HeaderRole { color:#7B899D; font-size:9px; }
        QLabel#HeaderChevron { color:#75839A; font-size:10px; }
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class AccountPopup(QFrame):
    logout_requested = pyqtSignal()
    page_requested = pyqtSignal(str)
    dismissed = pyqtSignal()

    def __init__(self, user: SessionUser, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.user = user
        self.setObjectName("Qt6AccountPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(236)
        self.setWindowOpacity(0.0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(3)
        head = QFrame(objectName="PopupHead")
        hl = QVBoxLayout(head); hl.setContentsMargins(8,7,8,7); hl.setSpacing(2)
        hl.addWidget(QLabel(user.username, objectName="PopupName"))
        hl.addWidget(QLabel(ROLE_LABELS.get(user.role, user.role), objectName="PopupRole"))
        layout.addWidget(head)
        account = QPushButton("Account information", objectName="PopupAction")
        settings = QPushButton("Application settings", objectName="PopupAction")
        account.clicked.connect(lambda: self._open("users" if can_access(user.role, "user_management") else "dashboard"))
        settings.clicked.connect(lambda: self._open("maintenance" if can_access(user.role, "system_maintenance") else "dashboard"))
        layout.addWidget(account); layout.addWidget(settings)
        signout = QPushButton("Sign out", objectName="PopupDanger")
        signout.clicked.connect(self._logout)
        layout.addWidget(signout)
        self.setStyleSheet("""
        QFrame#Qt6AccountPopup { background:#FFFFFF; border:1px solid #C9D5E5; border-radius:14px; }
        QFrame#PopupHead { background:#F7F9FD; border:0; border-radius:10px; }
        QLabel#PopupName { color:#172033; font-size:11px; font-weight:750; }
        QLabel#PopupRole { color:#7B899D; font-size:9px; }
        QPushButton#PopupAction, QPushButton#PopupDanger {
            min-height:35px; border:0; border-radius:9px; background:transparent; text-align:left;
            padding:0 10px; color:#43526A; font-size:10.5px; font-weight:600;
        }
        QPushButton#PopupAction:hover { background:#F3F6FC; color:#2868E8; }
        QPushButton#PopupDanger { color:#D83E59; }
        QPushButton#PopupDanger:hover { background:#FFF1F4; }
        """)
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(42); shadow.setOffset(0, 14); shadow.setColor(QColor(34, 58, 96, 42))
        self.setGraphicsEffect(shadow)
        self._fade = QtCore.QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(170)
        self._fade.setStartValue(0.0); self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

    def popup_at(self, global_pos: QtCore.QPoint):
        self.adjustSize()
        self.move(global_pos.x() - self.width(), global_pos.y())
        self.show(); self.raise_(); self._fade.start()

    def hideEvent(self, event):
        self.dismissed.emit()
        super().hideEvent(event)

    def _open(self, key: str):
        self.close(); self.page_requested.emit(key)

    def _logout(self):
        self.close(); self.logout_requested.emit()


class HeaderBar(QFrame):
    refresh_requested = pyqtSignal()
    logout_requested = pyqtSignal()
    page_requested = pyqtSignal(str)

    def __init__(self, user: SessionUser, parent=None):
        super().__init__(parent)
        self.user = user
        self.setObjectName("Qt6Header")
        self.setFixedHeight(82)
        root = QHBoxLayout(self)
        root.setContentsMargins(28, 0, 28, 0)
        root.setSpacing(10)

        copy = QVBoxLayout(); copy.setSpacing(2)
        self.title = QLabel("Dashboard", objectName="PageTitle")
        self.subtitle = QLabel("Inspection operations and system readiness", objectName="PageSubtitle")
        copy.addWidget(self.title); copy.addWidget(self.subtitle)
        root.addLayout(copy, 1)

        ready = QFrame(objectName="ReadyPill")
        ready.setFixedHeight(34)
        ready.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)
        rl = QHBoxLayout(ready); rl.setContentsMargins(8,0,10,0); rl.setSpacing(2)
        rl.addWidget(PulseDot())
        self.ready_text = QLabel("PLATFORM READY", objectName="ReadyText")
        rl.addWidget(self.ready_text)
        root.addWidget(ready)

        self.refresh = SpinButton()
        self.refresh.clicked.connect(self._refresh)
        root.addWidget(self.refresh)

        self.profile = ProfileButton(user)
        self.profile.clicked.connect(self._show_popup)
        root.addWidget(self.profile)

        self.setStyleSheet("""
        QFrame#Qt6Header { background:#FFFFFF; border:0; border-bottom:1px solid #C9D5E5; }
        QLabel#PageTitle { color:#101A2D; font-size:23px; font-weight:800; }
        QLabel#PageSubtitle { color:#65758E; font-size:11px; }
        QFrame#ReadyPill { background:#E7F8F0; border:1px solid #D4F1E3; border-radius:17px; }
        QLabel#ReadyText { color:#078955; font-size:9px; font-weight:800; }
        """)
        self._popup = None
        self._popup_closed_at = 0.0

    def set_page(self, title: str, subtitle: str):
        self.title.setText(title); self.subtitle.setText(subtitle)

    def set_ready_text(self, text: str):
        self.ready_text.setText(str(text or "PLATFORM READY"))

    def _refresh(self):
        self.refresh.spin(); self.refresh_requested.emit()

    def _popup_dismissed(self):
        self._popup_closed_at = time.monotonic()

    def _show_popup(self):
        now = time.monotonic()

        # Qt.Popup closes itself when the profile button is clicked outside it.
        # Without this small suppression window that same click immediately
        # re-opens a new popup, which makes the menu look impossible to close.
        if now - self._popup_closed_at < 0.30:
            return

        if self._popup is not None and self._popup.isVisible():
            self._popup.close()
            self._popup_closed_at = time.monotonic()
            return

        self._popup = AccountPopup(self.user, self)
        self._popup.dismissed.connect(self._popup_dismissed)
        self._popup.logout_requested.connect(self.logout_requested.emit)
        self._popup.page_requested.connect(self.page_requested.emit)
        anchor = self.profile.mapToGlobal(
            QtCore.QPoint(self.profile.width(), self.profile.height() + 7)
        )
        self._popup.popup_at(anchor)


class PlaceholderPage(QWidget):
    def __init__(self, spec: PageSpec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.setObjectName("Qt6Placeholder")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addStretch(1)
        card = QFrame(objectName="PlaceholderCard")
        card.setMaximumWidth(620)
        c = QVBoxLayout(card); c.setContentsMargins(34,32,34,32); c.setSpacing(11)
        badge = QLabel(); badge.setAlignment(Qt.AlignmentFlag.AlignCenter); badge.setFixedSize(58,58)
        badge.setPixmap(icon_pixmap(spec.icon_name, "#2868E8", 34, prefer_legacy=True))
        badge.setObjectName("PlaceholderIcon")
        title = QLabel(spec.title, objectName="PlaceholderTitle"); title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body = QLabel(
            "This shell is now running on PyQt6. This feature page is intentionally left as the next migration step so PyQt5 and PyQt6 widgets are never mixed in the same process.",
            objectName="PlaceholderBody",
        )
        body.setWordWrap(True); body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c.addWidget(badge,0,Qt.AlignmentFlag.AlignHCenter); c.addWidget(title); c.addWidget(body)
        layout.addWidget(card,0,Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(2)
        self.setStyleSheet("""
        QWidget#Qt6Placeholder { background:transparent; }
        QFrame#PlaceholderCard { background:#FFFFFF; border:1px solid #C9D5E5; border-radius:18px; }
        QLabel#PlaceholderIcon { background:#EEF4FF; border:1px solid #DCE8FF; border-radius:15px; }
        QLabel#PlaceholderTitle { color:#101A2D; font-size:21px; font-weight:800; }
        QLabel#PlaceholderBody { color:#65758E; font-size:11px; }
        """)


class MainShellWindow(QMainWindow):
    """PyQt6 shell + Dashboard + Machines + Projects + Image Capturing.

    Other pages are placeholders until each one is ported to PyQt6. This is
    deliberate: Qt5 and Qt6 widget objects must not be embedded in one process.
    """

    def __init__(self, user: dict | None = None, on_logout=None):
        super().__init__()
        self.current_user = user or {}
        self.session_user = SessionUser.from_record(self.current_user)
        self.on_logout = on_logout
        self._sidebar_open = 244
        self._sidebar_closed = 78
        self._sidebar_collapsed = False
        self._user_forced_sidebar = False
        self._sidebar_anim = None
        self.pages: dict[str, QWidget] = {}
        self.specs = {s.key: s for s in PAGE_SPECS}
        self._active_key = "dashboard"
        self.setWindowTitle(
            f"EYRES AI Inspection Platform · {self.session_user.username} · "
            f"{ROLE_LABELS.get(self.session_user.role, self.session_user.role)}"
        )
        app_icon = asset_path("app.ico")
        if app_icon.is_file():
            self.setWindowIcon(QIcon(str(app_icon)))
        self.setMinimumSize(1024, 680)
        self._build()
        self._restore_sidebar_state()
        self.switch_page("dashboard", animate=False)
        QtCore.QTimer.singleShot(450, lambda: self.toast.show_message(
            "Qt6 workspace ready", "Dashboard, Machines, Projects and Image Capturing are running on PyQt6."
        ))

    # sidebar property for QPropertyAnimation
    def get_sidebar_width(self) -> int:
        return self.sidebar.width()

    def set_sidebar_width(self, value: int):
        value = int(value)
        self.sidebar.setFixedWidth(value)
        self.collapse_button.move(value - self.collapse_button.width()//2, 99)

    sidebarWidth = pyqtProperty(int, fget=get_sidebar_width, fset=set_sidebar_width)

    def _build(self):
        central = QWidget()
        central.setObjectName("Qt6ShellRoot")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        self.sidebar = SidebarWidget(self.session_user)
        self.sidebar.setFixedWidth(self._sidebar_open)
        self.sidebar.page_requested.connect(self.switch_page)
        self.sidebar.logout_requested.connect(self._logout)
        root.addWidget(self.sidebar)

        self.main = QFrame(objectName="Qt6MainArea")
        main_l = QVBoxLayout(self.main)
        main_l.setContentsMargins(0,0,0,0); main_l.setSpacing(0)
        self.header = HeaderBar(self.session_user)
        self.header.refresh_requested.connect(self._refresh)
        self.header.logout_requested.connect(self._logout)
        self.header.page_requested.connect(self.switch_page)
        main_l.addWidget(self.header)

        content_host = QWidget(objectName="ContentHost")
        ch = QVBoxLayout(content_host)
        ch.setContentsMargins(22, 18, 22, 24); ch.setSpacing(0)
        self.stack = QStackedWidget()
        self.stack.setObjectName("Qt6PageStack")
        ch.addWidget(self.stack)
        main_l.addWidget(content_host, 1)
        root.addWidget(self.main, 1)

        self.dashboard = DashboardPageQt6()
        self.dashboard.navigate_requested.connect(self.switch_page)
        self.dashboard.toast_requested.connect(self.toast_message)
        self._add_page("dashboard", self.dashboard)

        self.machines_page = None
        machines_spec = self.specs["machines"]
        if can_access(self.session_user.role, machines_spec.permission):
            self.machines_page = MachinesPageQt6(user=self.current_user)
            self.machines_page.toast_requested.connect(self.toast_message)
            self._add_page("machines", self.machines_page)

        self.projects_page = None
        projects_spec = self.specs["projects"]
        if can_access(self.session_user.role, projects_spec.permission):
            self.projects_page = ProjectsPageQt6(user=self.current_user)
            self.projects_page.toast_requested.connect(self.toast_message)
            self._add_page("projects", self.projects_page)

        self.capture_page = None
        capture_spec = self.specs["capture"]
        if can_access(self.session_user.role, capture_spec.permission):
            self.capture_page = CapturePageQt6(user=self.current_user)
            self.capture_page.toast_requested.connect(self.toast_message)
            self._add_page("capture", self.capture_page)

        self.annotation_page = None
        annotation_spec = self.specs["annotation"]
        if can_access(self.session_user.role, annotation_spec.permission):
            self.annotation_page = AnnotationPageQt6(user=self.current_user)
            self.annotation_page.toast_requested.connect(self.toast_message)
            self._add_page("annotation", self.annotation_page)

        self.augmentation_page = None
        augmentation_spec = self.specs["augmentation"]
        if can_access(self.session_user.role, augmentation_spec.permission):
            self.augmentation_page = AugmentationPageQt6(user=self.current_user)
            self.augmentation_page.toast_requested.connect(self.toast_message)
            self._add_page("augmentation", self.augmentation_page)

        self.training_page = None
        training_spec = self.specs["training"]
        if can_access(self.session_user.role, training_spec.permission):
            self.training_page = TrainingPageQt6(user=self.current_user)
            self.training_page.toast_requested.connect(self.toast_message)
            self._add_page("training", self.training_page)

        self.live_page = None
        live_spec = self.specs["live"]
        if can_access(self.session_user.role, live_spec.permission):
            self.live_page = LivePageQt6(user=self.current_user)
            self.live_page.toast_requested.connect(self.toast_message)
            self._add_page("live", self.live_page)

        self.plc_page = None
        plc_spec = self.specs["plc"]
        if can_access(self.session_user.role, plc_spec.permission):
            self.plc_page = PLCPageQt6(user=self.current_user)
            self.plc_page.toast_requested.connect(self.toast_message)
            self._add_page("plc", self.plc_page)

        self.users_page = None
        users_spec = self.specs["users"]
        if can_access(self.session_user.role, users_spec.permission):
            self.users_page = UserManagementPageQt6(user=self.current_user)
            self.users_page.toast_requested.connect(self.toast_message)
            self._add_page("users", self.users_page)

        self.maintenance_page = None
        maintenance_spec = self.specs["maintenance"]
        if can_access(self.session_user.role, maintenance_spec.permission):
            self.maintenance_page = SystemMaintenancePageQt6(user=self.current_user)
            self.maintenance_page.toast_requested.connect(self.toast_message)
            self._add_page("maintenance", self.maintenance_page)

        self.diagnostics_page = None
        diagnostics_spec = self.specs["diagnostics"]
        if can_access(self.session_user.role, diagnostics_spec.permission):
            self.diagnostics_page = ApplicationDiagnosticsPageQt6(user=self.current_user)
            self.diagnostics_page.toast_requested.connect(self.toast_message)
            self._add_page("diagnostics", self.diagnostics_page)

        for spec in PAGE_SPECS:
            if spec.key in {"dashboard", "machines", "projects", "capture", "annotation", "augmentation", "training", "live", "plc", "users", "maintenance", "diagnostics"} or not can_access(self.session_user.role, spec.permission):
                continue
            self._add_page(spec.key, PlaceholderPage(spec))

        self.collapse_button = CollapseButton(central)
        self.collapse_button.clicked.connect(self.toggle_sidebar)
        self.collapse_button.move(self._sidebar_open - 17, 99)
        self.collapse_button.raise_()

        self.toast = ToastOverlay(central)
        self.toast.raise_()

        central.setStyleSheet("""
        QWidget#Qt6ShellRoot { background:#EEF3F9; }
        QFrame#Qt6MainArea, QWidget#ContentHost, QStackedWidget#Qt6PageStack { background:#EEF3F9; border:0; }
        QToolTip { background:#172033; color:#FFFFFF; border:0; padding:5px 7px; border-radius:5px; }
        """)

    def _add_page(self, key: str, widget: QWidget):
        self.pages[key] = widget
        self.stack.addWidget(widget)

    def _restore_sidebar_state(self):
        settings = QtCore.QSettings("EYRES AI", "Inspection Platform")
        collapsed = settings.value("qt6/sidebar_collapsed", False, type=bool)
        if self.width() < 980:
            collapsed = True
        self._set_sidebar_collapsed(collapsed, animate=False, persist=False)

    def toggle_sidebar(self):
        self._user_forced_sidebar = True
        self._set_sidebar_collapsed(not self._sidebar_collapsed, animate=True, persist=True)

    def _set_sidebar_collapsed(self, collapsed: bool, animate: bool = True, persist: bool = True):
        collapsed = bool(collapsed)
        if collapsed == self._sidebar_collapsed and animate:
            return
        self._sidebar_collapsed = collapsed
        target = self._sidebar_closed if collapsed else self._sidebar_open
        if persist:
            settings = QtCore.QSettings("EYRES AI", "Inspection Platform")
            settings.setValue("qt6/sidebar_collapsed", collapsed)

        if self._sidebar_anim is None:
            self._sidebar_anim = QtCore.QPropertyAnimation(self, b"sidebarWidth", self)
            self._sidebar_anim.setDuration(280)
            self._sidebar_anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        self._sidebar_anim.stop()
        self.collapse_button.set_collapsed(collapsed, animate=animate)

        if not animate:
            self.set_sidebar_width(target)
            self.sidebar.set_compact(collapsed)
            return

        if not collapsed:
            self.sidebar.set_compact(False)
        else:
            QtCore.QTimer.singleShot(135, lambda: self.sidebar.set_compact(True) if self._sidebar_collapsed else None)
        self._sidebar_anim.setStartValue(self.get_sidebar_width())
        self._sidebar_anim.setEndValue(target)
        self._sidebar_anim.start()

    def switch_page(self, key: str, animate: bool = True):
        spec = self.specs.get(key)
        if spec is None or not can_access(self.session_user.role, spec.permission):
            self.toast_message("Access denied", "Your role does not have access to this feature.")
            return
        page = self.pages.get(key)
        if page is None:
            self.toast_message("Migration pending", f"{spec.title} has not been migrated to PyQt6 yet.")
            return

        self._active_key = key
        self.sidebar.set_active(key)
        self.header.set_page(
            "Live Inspection" if key == "live" else spec.title,
            spec.subtitle,
        )
        self.header.set_ready_text(
            "AUTO-SAVE READY"
            if key == "annotation"
            else "TRAINING READY"
            if key == "training"
            else "LIVE READY"
            if key == "live"
            else "PLC READY"
            if key == "plc"
            else "ACCESS CONTROL READY"
            if key == "users"
            else "MAINTENANCE READY"
            if key == "maintenance"
            else "DIAGNOSTICS READY"
            if key == "diagnostics"
            else "PLATFORM READY"
        )
        self.stack.setCurrentWidget(page)
        if key == "dashboard":
            self.dashboard.refresh_all(animate=True)
        elif key == "machines" and self.machines_page is not None:
            self.machines_page.refresh_data(animate=True)
        elif key == "projects" and self.projects_page is not None:
            self.projects_page.refresh_data(animate=True)
        elif key == "capture" and self.capture_page is not None:
            self.capture_page.refresh_context()
        elif key == "annotation" and self.annotation_page is not None:
            self.annotation_page.refresh_context()
        elif key == "augmentation" and self.augmentation_page is not None:
            self.augmentation_page.refresh_context()
        elif key == "training" and self.training_page is not None:
            self.training_page.refresh_context()
        elif key == "live" and self.live_page is not None:
            self.live_page.refresh_context()
        elif key == "plc" and self.plc_page is not None:
            self.plc_page.refresh_context()
        elif key == "users" and self.users_page is not None:
            self.users_page.refresh_context()
        elif key == "maintenance" and self.maintenance_page is not None:
            self.maintenance_page.activate()
        elif key == "diagnostics" and self.diagnostics_page is not None:
            self.diagnostics_page.activate()
        if animate:
            fade_in(page, 220)
        try:
            record_audit_event(
                "navigation", actor=self.session_user.username,
                details={"page": spec.title, "ui_runtime": "PyQt6"},
            )
        except Exception:
            pass

    def toast_message(self, title: str, text: str):
        self.toast.show_message(title, text)

    def _refresh(self):
        if self._active_key == "dashboard":
            self.dashboard.refresh_all(animate=True)
            self.toast_message("System status refreshed", "Dashboard indicators have been refreshed.")
        elif self._active_key == "machines" and self.machines_page is not None:
            self.machines_page.refresh_data(animate=True)
            self.toast_message("Machines refreshed", "Machine records and status indicators were refreshed.")
        elif self._active_key == "projects" and self.projects_page is not None:
            self.projects_page.refresh_data(animate=True)
            self.toast_message("Projects refreshed", "Project and machine-assignment information was refreshed.")
        elif self._active_key == "capture" and self.capture_page is not None:
            self.capture_page.refresh_context()
            self.toast_message("Capture page refreshed", "Project and storage context were refreshed.")
        elif self._active_key == "annotation" and self.annotation_page is not None:
            self.annotation_page.refresh_context()
            self.toast_message("Annotation page refreshed", "Project and dataset context were refreshed.")
        elif self._active_key == "augmentation" and self.augmentation_page is not None:
            self.augmentation_page.refresh_context()
            self.toast_message("Augmentation page refreshed", "Project and dataset context were refreshed.")
        elif self._active_key == "training" and self.training_page is not None:
            self.training_page.refresh_context()
            self.toast_message("Training page refreshed", "Project, dataset and device context were refreshed.")
        elif self._active_key == "live" and self.live_page is not None:
            self.live_page.refresh_context()
            self.toast_message("Live page refreshed", "Project, camera and session context were refreshed.")
        elif self._active_key == "plc" and self.plc_page is not None:
            self.plc_page.refresh_context()
            self.toast_message("PLC page refreshed", "PLC monitoring context was refreshed.")
        elif self._active_key == "users" and self.users_page is not None:
            self.users_page.refresh_data(animate=True)
        elif self._active_key == "maintenance" and self.maintenance_page is not None:
            self.maintenance_page.refresh_context()
            self.maintenance_page.refresh_health()
        elif self._active_key == "diagnostics" and self.diagnostics_page is not None:
            self.diagnostics_page.refresh_all()
        else:
            self.toast_message("Page refreshed", f"{self.specs[self._active_key].title} is ready.")

    def _logout(self):
        try:
            if self.capture_page is not None:
                self.capture_page.shutdown()
            if self.annotation_page is not None:
                self.annotation_page.shutdown()
            if self.augmentation_page is not None:
                self.augmentation_page.shutdown()
            if self.training_page is not None:
                self.training_page.shutdown()
            if self.live_page is not None:
                self.live_page.shutdown()
            if self.plc_page is not None:
                self.plc_page.shutdown()
            if self.maintenance_page is not None:
                self.maintenance_page.shutdown()
            if self.diagnostics_page is not None:
                self.diagnostics_page.shutdown()
        except Exception:
            pass
        try:
            record_audit_event("logout", actor=self.session_user.username)
        except Exception:
            pass
        self.hide()
        if callable(self.on_logout):
            self.on_logout()
        self.deleteLater()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "collapse_button"):
            self.collapse_button.move(self.sidebar.width() - self.collapse_button.width()//2, 99)
        if hasattr(self, "toast"):
            self.toast.reposition()
        # Very narrow screens automatically use icon-only navigation.
        if self.width() < 930 and not self._sidebar_collapsed:
            self._set_sidebar_collapsed(True, animate=True, persist=False)

    def closeEvent(self, event):
        try:
            if self.capture_page is not None:
                self.capture_page.shutdown()
            if self.annotation_page is not None:
                self.annotation_page.shutdown()
            if self.augmentation_page is not None:
                self.augmentation_page.shutdown()
            if self.training_page is not None:
                self.training_page.shutdown()
            if self.live_page is not None:
                self.live_page.shutdown()
            if self.plc_page is not None:
                self.plc_page.shutdown()
            if self.maintenance_page is not None:
                self.maintenance_page.shutdown()
            if self.diagnostics_page is not None:
                self.diagnostics_page.shutdown()
        except Exception:
            pass
        try:
            record_audit_event("application_close", actor=self.session_user.username)
        except Exception:
            pass
        super().closeEvent(event)
