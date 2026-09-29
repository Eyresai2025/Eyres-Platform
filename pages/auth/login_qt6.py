"""Responsive PyQt6 login for the EYRES AI Inspection Platform.

Qt6 compatibility note: custom painting uses QPointF-safe gradients.

Phase 1 migration target:
- Implements the approved responsive HTML design.
- Keeps the existing Database, audit, password-reset and Google OAuth backend.
- Does NOT import any PyQt5 module.
- Intended to run standalone until Main_GUI and the application shell are
  migrated to PyQt6. Do not import this module from the current PyQt5 shell.
"""
from __future__ import annotations

from pathlib import Path
import threading

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, QEvent, QPoint, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app_core.audit import record_audit_event
from db import Database
from ui.qt6 import BREAKPOINTS, asset_path, crossfade_stack
from .google_auth import (
    GoogleAuthError,
    prepare_google_auth,
    complete_google_auth,
)

LOGIN_UI_BUILD = "2026.09.24-qt6-oauth-native-02"


class BrandPanel(QWidget):
    """Painted responsive brand surface from the approved login preview."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("brandPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect()
        gradient = QLinearGradient(
            QtCore.QPointF(rect.topLeft()),
            QtCore.QPointF(rect.bottomRight()),
        )
        gradient.setColorAt(0.0, QColor("#F8FAFE"))
        gradient.setColorAt(0.48, QColor("#EEF3F9"))
        gradient.setColorAt(1.0, QColor("#F8FAFE"))
        painter.fillRect(rect, gradient)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(124, 77, 255, 18))
        painter.drawEllipse(-170, rect.height() - 290, 460, 460)

        painter.setBrush(QColor(22, 188, 232, 18))
        painter.drawEllipse(rect.width() - 260, -170, 420, 420)

        super().paintEvent(event)



class PasswordField(QWidget):
    """QLineEdit with an integrated Show/Hide control."""

    returnPressed = pyqtSignal()

    def __init__(self, placeholder: str = "Enter your password", parent=None):
        super().__init__(parent)
        self.setObjectName("passwordFieldHost")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.edit = QLineEdit()
        self.edit.setObjectName("authInput")
        self.edit.setPlaceholderText(placeholder)
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.returnPressed.connect(self.returnPressed.emit)
        layout.addWidget(self.edit)

        self.toggle = QPushButton("Show")
        self.toggle.setObjectName("passwordToggle")
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.setFixedSize(48, 32)
        self.toggle.clicked.connect(self._toggle)
        self.toggle.setParent(self)
        self.toggle.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        x = self.width() - self.toggle.width() - 8
        y = max(0, (self.height() - self.toggle.height()) // 2)
        self.toggle.move(x, y)
        self.edit.setTextMargins(0, 0, self.toggle.width() + 12, 0)

    def _toggle(self):
        hidden = self.edit.echoMode() == QLineEdit.EchoMode.Password
        self.edit.setEchoMode(
            QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password
        )
        self.toggle.setText("Hide" if hidden else "Show")

    def text(self) -> str:
        return self.edit.text()

    def clear(self):
        self.edit.clear()

    def setFocus(self, reason=Qt.FocusReason.OtherFocusReason):
        self.edit.setFocus(reason)


class LoginWindow(QWidget):
    google_auth_result = pyqtSignal(object, object)

    def __init__(self, on_login_success=None):
        super().__init__()
        self.db = Database()
        self.on_login_success = on_login_success
        self.google_auth_result.connect(self._handle_google_auth_result)
        self._google_auth_running = False
        self._compact_mode = False
        self._short_mode = False

        self.setObjectName("authWindow")
        self.setWindowTitle("EYRES AI Inspection Platform - Login")
        self.setMinimumSize(900, 560)

        icon = asset_path("app.ico")
        if icon.is_file():
            self.setWindowIcon(QIcon(str(icon)))

        self._build_ui()
        self._apply_styles()
        self._update_responsive_state()
        self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

    # ------------------------------------------------------------------
    # UI BUILD
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.brand_panel = BrandPanel()
        brand_layout = QVBoxLayout(self.brand_panel)
        brand_layout.setContentsMargins(58, 44, 58, 42)
        brand_layout.setSpacing(0)

        self.brand_top = self._build_brand_header()
        brand_layout.addWidget(self.brand_top, 0, Qt.AlignmentFlag.AlignTop)

        brand_layout.addStretch(1)

        self.brand_content = self._build_brand_content()
        brand_layout.addWidget(self.brand_content)

        brand_layout.addStretch(1)

        # Approved clean layout: no lower-left footer text.
        self.brand_footer = QWidget()
        self.brand_footer.setVisible(False)

        root.addWidget(self.brand_panel, 11)

        self.login_side = QFrame()
        self.login_side.setObjectName("loginSide")
        side_layout = QVBoxLayout(self.login_side)
        side_layout.setContentsMargins(54, 40, 54, 40)
        side_layout.setSpacing(0)
        side_layout.addStretch(1)

        self.card = QFrame()
        self.card.setObjectName("loginCard")
        self.card.setMaximumWidth(470)
        self.card.setMinimumWidth(400)
        self.card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(55)
        shadow.setOffset(0, 18)
        shadow.setColor(QColor(38, 64, 110, 35))
        self.card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(38, 36, 38, 32)
        card_layout.setSpacing(0)

        self.card_stack = QStackedWidget()
        self.login_page = self._build_login_page()
        self.forgot_username_page = self._build_forgot_username_page()
        self.forgot_reset_page = self._build_forgot_reset_page()
        self.card_stack.addWidget(self.login_page)
        self.card_stack.addWidget(self.forgot_username_page)
        self.card_stack.addWidget(self.forgot_reset_page)
        card_layout.addWidget(self.card_stack)

        side_layout.addWidget(self.card, 0, Qt.AlignmentFlag.AlignHCenter)
        side_layout.addStretch(1)

        root.addWidget(self.login_side, 9)


    def _build_brand_header(self) -> QWidget:
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(13)

        logo = QLabel()
        logo.setObjectName("brandLogo")
        path = asset_path("app.png")
        if path.is_file():
            pm = QPixmap(str(path))
            logo.setPixmap(
                pm.scaled(
                    48, 48,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        logo.setFixedSize(48, 48)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)

        labels = QVBoxLayout()
        labels.setSpacing(1)
        name = QLabel("EyRes.AI")
        name.setObjectName("brandName")
        kicker = QLabel("INSPECTION PLATFORM")
        kicker.setObjectName("brandKicker")
        labels.addWidget(name)
        labels.addWidget(kicker)
        layout.addLayout(labels)
        layout.addStretch(1)
        return host

    def _build_brand_content(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        chip = QLabel("●   Secure industrial workstation")
        chip.setObjectName("heroChip")
        chip.setFixedHeight(30)
        chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        layout.addWidget(chip, 0, Qt.AlignmentFlag.AlignLeft)

        title = QLabel(
            'Quality inspection,\n'
            '<span style="color:#2868E8;">orchestrated intelligently.</span>'
        )
        title.setObjectName("heroTitle")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setWordWrap(True)
        layout.addSpacing(16)
        layout.addWidget(title)

        body = QLabel(
            "One workspace for image acquisition, annotation, augmentation, "
            "model training, PLC monitoring, diagnostics and controlled production access."
        )
        body.setObjectName("heroCopy")
        body.setWordWrap(True)
        layout.addSpacing(9)
        layout.addWidget(body)

        return host

    def _build_login_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        logo = QLabel()
        logo.setObjectName("loginLogo")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        path = asset_path("app.png")
        if path.is_file():
            pm = QPixmap(str(path))
            logo.setPixmap(
                pm.scaled(
                    72, 72,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        layout.addWidget(logo)

        title = QLabel("Welcome back")
        title.setObjectName("loginTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(15)
        layout.addWidget(title)

        subtitle = QLabel("Sign in to continue to your inspection workspace.")
        subtitle.setObjectName("loginSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        layout.addSpacing(5)
        layout.addWidget(subtitle)

        form = QWidget()
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(0)

        user_label = QLabel("Username")
        user_label.setObjectName("fieldLabel")
        form_layout.addWidget(user_label)
        self.username = QLineEdit()
        self.username.setObjectName("authInput")
        self.username.setPlaceholderText("Enter your username")
        self.username.setMinimumHeight(46)
        form_layout.addSpacing(7)
        form_layout.addWidget(self.username)

        password_label = QLabel("Password")
        password_label.setObjectName("fieldLabel")
        form_layout.addSpacing(14)
        form_layout.addWidget(password_label)
        self.password_field = PasswordField("Enter your password")
        self.password_field.setMinimumHeight(46)
        form_layout.addSpacing(7)
        form_layout.addWidget(self.password_field)

        forgot_row = QHBoxLayout()
        forgot_row.setContentsMargins(0, 0, 0, 0)
        forgot_row.addStretch(1)
        forgot = QPushButton("Forgot password?")
        forgot.setObjectName("linkButton")
        forgot.setCursor(Qt.CursorShape.PointingHandCursor)
        forgot.clicked.connect(self.open_forgot_password)
        forgot_row.addWidget(forgot)
        form_layout.addSpacing(4)
        form_layout.addLayout(forgot_row)

        self.login_btn = QPushButton("Log in securely")
        self.login_btn.setObjectName("primaryButton")
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.setMinimumHeight(46)
        self.login_btn.clicked.connect(self.try_login)
        form_layout.addSpacing(11)
        form_layout.addWidget(self.login_btn)

        divider = QHBoxLayout()
        divider.setSpacing(12)
        left = QFrame()
        right = QFrame()
        left.setFrameShape(QFrame.Shape.HLine)
        right.setFrameShape(QFrame.Shape.HLine)
        left.setObjectName("divider")
        right.setObjectName("divider")
        or_label = QLabel("or")
        or_label.setObjectName("orLabel")
        divider.addWidget(left, 1)
        divider.addWidget(or_label)
        divider.addWidget(right, 1)
        form_layout.addSpacing(19)
        form_layout.addLayout(divider)

        self.google_btn = QPushButton("Continue with Google")
        self.google_btn.setObjectName("googleButton")
        self.google_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.google_btn.setMinimumHeight(44)
        g_icon = asset_path("google_g.svg")
        if g_icon.is_file():
            self.google_btn.setIcon(QIcon(str(g_icon)))
            self.google_btn.setIconSize(QtCore.QSize(18, 18))
        self.google_btn.clicked.connect(self.start_google_login)
        form_layout.addSpacing(16)
        form_layout.addWidget(self.google_btn)

        layout.addSpacing(25)
        layout.addWidget(form)

        self.password_field.returnPressed.connect(self.try_login)
        self.username.returnPressed.connect(lambda: self.password_field.setFocus())
        self._register_nav(self.username, "login")
        self._register_nav(self.password_field.edit, "login")
        return page

    def _build_forgot_username_page(self) -> QWidget:
        page = QWidget()
        page.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        head = self._back_header(
            "Reset password",
            "Enter your username to retrieve the configured security question.",
            self.show_login_page,
        )
        head.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout.addWidget(head)

        form = QFrame()
        form.setObjectName("recoveryForm")
        form.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(0)

        label = QLabel("Username")
        label.setObjectName("fieldLabel")
        form_layout.addWidget(label)

        self.fg_username = QLineEdit()
        self.fg_username.setObjectName("authInput")
        self.fg_username.setPlaceholderText("Enter your username")
        self.fg_username.setFixedHeight(46)
        form_layout.addSpacing(7)
        form_layout.addWidget(self.fg_username)

        next_btn = QPushButton("Continue")
        next_btn.setObjectName("primaryButton")
        next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        next_btn.setFixedHeight(46)
        next_btn.clicked.connect(self.handle_forgot_next)
        form_layout.addSpacing(14)
        form_layout.addWidget(next_btn)

        layout.addSpacing(28)
        layout.addWidget(form)
        layout.addStretch(1)

        self._register_nav(self.fg_username, "forgot_username")
        self.fg_username.returnPressed.connect(self.handle_forgot_next)
        return page

    def _build_forgot_reset_page(self) -> QWidget:
        page = QWidget()
        page.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        head = self._back_header(
            "Verify & set new password",
            "Answer your security question, then enter a new password.",
            lambda: self._show_card(self.forgot_username_page),
        )
        head.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout.addWidget(head)

        question_box = QFrame()
        question_box.setObjectName("questionBox")
        question_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        q_layout = QVBoxLayout(question_box)
        q_layout.setContentsMargins(13, 11, 13, 11)
        q_layout.setSpacing(4)
        q_kicker = QLabel("SECURITY QUESTION")
        q_kicker.setObjectName("questionKicker")
        self.fg_question_label = QLabel("—")
        self.fg_question_label.setObjectName("questionText")
        self.fg_question_label.setWordWrap(True)
        q_layout.addWidget(q_kicker)
        q_layout.addWidget(self.fg_question_label)

        layout.addSpacing(22)
        layout.addWidget(question_box)

        ans_label = QLabel("Security answer")
        ans_label.setObjectName("fieldLabel")
        layout.addSpacing(14)
        layout.addWidget(ans_label)

        self.fg_answer = QLineEdit()
        self.fg_answer.setObjectName("authInput")
        self.fg_answer.setEchoMode(QLineEdit.EchoMode.Password)
        self.fg_answer.setPlaceholderText("Enter your answer")
        self.fg_answer.setFixedHeight(46)
        layout.addSpacing(7)
        layout.addWidget(self.fg_answer)

        pass_label = QLabel("New password")
        pass_label.setObjectName("fieldLabel")
        layout.addSpacing(14)
        layout.addWidget(pass_label)

        self.fg_newpass = PasswordField("Enter a new password")
        self.fg_newpass.setFixedHeight(46)
        layout.addSpacing(7)
        layout.addWidget(self.fg_newpass)

        reset_btn = QPushButton("Reset password")
        reset_btn.setObjectName("primaryButton")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setFixedHeight(46)
        reset_btn.clicked.connect(self.handle_forgot_reset)
        layout.addSpacing(15)
        layout.addWidget(reset_btn)

        layout.addStretch(1)

        self._register_nav(self.fg_answer, "forgot_reset")
        self._register_nav(self.fg_newpass.edit, "forgot_reset")
        self.fg_answer.returnPressed.connect(lambda: self.fg_newpass.setFocus())
        self.fg_newpass.returnPressed.connect(self.handle_forgot_reset)
        return page

    def _back_header(self, title_text: str, body_text: str, callback) -> QWidget:
        host = QWidget()
        host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(11)
        row.setAlignment(Qt.AlignmentFlag.AlignTop)

        back = QPushButton("←")
        back.setObjectName("backButton")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setFixedSize(36, 36)
        back.clicked.connect(callback)
        row.addWidget(back, 0, Qt.AlignmentFlag.AlignTop)

        text_host = QWidget()
        text_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        text_box = QVBoxLayout(text_host)
        text_box.setContentsMargins(0, 1, 0, 0)
        text_box.setSpacing(6)

        title = QLabel(title_text)
        title.setObjectName("forgotTitle")
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        body = QLabel(body_text)
        body.setObjectName("forgotCopy")
        body.setWordWrap(True)
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        body.setMaximumWidth(300)

        text_box.addWidget(title)
        text_box.addWidget(body)

        row.addWidget(text_host, 1, Qt.AlignmentFlag.AlignTop)
        return host


    # ------------------------------------------------------------------
    # RESPONSIVE BEHAVIOUR
    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_responsive_state()

    def _update_responsive_state(self):
        compact = self.width() < BREAKPOINTS["compact_width"]
        short = self.height() < BREAKPOINTS["short_height"]

        if compact != self._compact_mode:
            self._compact_mode = compact
            self.brand_content.setVisible(not compact)
            self.brand_footer.setVisible(not compact)

            root = self.layout()
            if compact:
                root.setStretch(0, 0)
                root.setStretch(1, 1)
                self.brand_panel.setMaximumWidth(0)
                self.brand_panel.setMinimumWidth(0)
                self.brand_panel.hide()
                self.login_side.layout().setContentsMargins(24, 80, 24, 24)
            else:
                self.brand_panel.show()
                self.brand_panel.setMaximumWidth(16777215)
                self.brand_panel.setMinimumWidth(0)
                root.setStretch(0, 11)
                root.setStretch(1, 9)
                self.login_side.layout().setContentsMargins(54, 40, 54, 40)

        if short != self._short_mode:
            self._short_mode = short
            card_layout = self.card.layout()
            if short:
                card_layout.setContentsMargins(34, 24, 34, 23)
                self.card.setMaximumWidth(445)
            else:
                card_layout.setContentsMargins(38, 36, 38, 32)
                self.card.setMaximumWidth(470)

    # ------------------------------------------------------------------
    # PAGE SWITCHING / KEYBOARD NAVIGATION
    # ------------------------------------------------------------------
    def _show_card(self, widget: QWidget):
        crossfade_stack(self.card_stack, widget, duration_ms=160)

        # Recovery screens should stay compact instead of inheriting the taller
        # login-page geometry.
        if widget is self.forgot_username_page:
            self.card.setMinimumHeight(0)
            self.card.setMaximumHeight(500)
        elif widget is self.forgot_reset_page:
            self.card.setMinimumHeight(0)
            self.card.setMaximumHeight(620)
        else:
            self.card.setMaximumHeight(16777215)

    def show_login_page(self):
        self.card.setMaximumHeight(16777215)
        self._show_card(self.login_page)
        QtCore.QTimer.singleShot(0, self.username.setFocus)

    def open_forgot_password(self):
        self.fg_username.clear()
        self.fg_answer.clear()
        self.fg_newpass.clear()
        self.fg_question_label.setText("—")
        self._show_card(self.forgot_username_page)
        QtCore.QTimer.singleShot(0, self.fg_username.setFocus)

    def _register_nav(self, edit: QLineEdit, group: str):
        if edit is None:
            return
        edit.setProperty("nav_group", group)
        edit.installEventFilter(self)

    def eventFilter(self, obj, event):
        if isinstance(obj, QLineEdit) and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                group = obj.property("nav_group")
                if not group:
                    return False
                edits = [
                    e for e in self.findChildren(QLineEdit)
                    if e.property("nav_group") == group and e.isVisible() and e.isEnabled()
                ]
                edits.sort(
                    key=lambda w: (
                        w.mapToGlobal(QPoint(0, 0)).y(),
                        w.mapToGlobal(QPoint(0, 0)).x(),
                    )
                )
                try:
                    idx = edits.index(obj)
                except ValueError:
                    return False
                if key == Qt.Key.Key_Down and idx < len(edits) - 1:
                    edits[idx + 1].setFocus()
                    return True
                if key == Qt.Key.Key_Up and idx > 0:
                    edits[idx - 1].setFocus()
                    return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # AUTH BACKEND (same behaviour as current PyQt5 implementation)
    # ------------------------------------------------------------------
    def start_google_login(self):
        if self._google_auth_running:
            return

        try:
            flow = prepare_google_auth()
        except Exception as exc:
            QMessageBox.warning(self, "Google Sign-In", str(exc))
            return

        # Important: open the browser from the Qt GUI thread using Qt's native
        # desktop-services API. This is more reliable than launching a browser
        # from the background OAuth worker on Windows.
        opened = QDesktopServices.openUrl(QUrl(flow.auth_url))
        if not opened:
            flow.close()
            QMessageBox.warning(
                self,
                "Google Sign-In",
                "Windows could not open the default browser for Google Sign-In.",
            )
            return

        self._google_auth_running = True
        self.google_btn.setEnabled(False)
        self.google_btn.setText("Waiting for Google…")
        self.google_btn.setToolTip(
            "Complete Google Sign-In in the browser. "
            "EYRES is waiting for the secure local callback."
        )

        # Useful non-secret diagnostics when validating the migration.
        print(f"[EYRES Google OAuth] callback: {flow.redirect_uri}")

        threading.Thread(
            target=self._google_login_worker,
            args=(flow,),
            daemon=True,
        ).start()

    def _google_login_worker(self, flow):
        try:
            identity = complete_google_auth(flow, timeout_seconds=180)
            self.google_auth_result.emit(identity, None)
        except Exception as exc:
            self.google_auth_result.emit(None, exc)

    def _handle_google_auth_result(self, identity, error):
        self._google_auth_running = False
        self.google_btn.setEnabled(True)
        self.google_btn.setText("Continue with Google")
        self.google_btn.setToolTip("")

        if error is not None:
            message = str(error).strip()
            if not message:
                message = "Google Sign-In was cancelled or could not be completed."
            QMessageBox.warning(self, "Google Sign-In", message)
            return

        try:
            user = self.db.get_user_by_provider_identity("google", identity.provider_user_id)

            if user is None:
                if not identity.verified_email:
                    raise GoogleAuthError("Google did not verify this email address.")
                user = self.db.get_user_by_email(identity.email)
                if user is not None:
                    self.db.link_provider_identity(
                        user.get("username", ""),
                        "google",
                        identity.provider_user_id,
                        identity.email,
                    )
                    user = self.db.get_user_by_provider_identity(
                        "google", identity.provider_user_id
                    )
                else:
                    user = self.db.create_google_user(
                        identity.email, identity.name, identity.provider_user_id
                    )

            if not user:
                raise GoogleAuthError("Unable to create or find the platform account.")
            if not user.get("active", True):
                raise GoogleAuthError(
                    "This platform account is disabled. Contact an administrator."
                )

            if self.on_login_success:
                self.on_login_success(user)
                self.close()
            else:
                QMessageBox.information(
                    self,
                    "Success",
                    f"Welcome, {user.get('username', identity.email)}!",
                )
        except Exception as exc:
            record_audit_event(
                "google_login_error",
                actor=identity.email,
                status="failed",
                details={"error_type": type(exc).__name__},
            )
            QMessageBox.critical(self, "Google Sign-In", str(exc))

    def try_login(self):
        username = self.username.text().strip()
        password = self.password_field.text().strip()

        if not username or not password:
            QMessageBox.warning(self, "Sign in", "Please enter username and password.")
            return

        try:
            user = self.db.find_user(username, password)
        except Exception as exc:
            record_audit_event(
                "login_error",
                actor=username,
                status="failed",
                details={"error_type": type(exc).__name__},
            )
            QMessageBox.critical(
                self,
                "Service unavailable",
                "Login service is unavailable. Please contact the administrator.",
            )
            return

        if not user:
            record_audit_event(
                "login_denied",
                actor=username,
                status="denied",
                details={"reason": "invalid_credentials_or_disabled"},
            )
            QMessageBox.warning(self, "Sign in", "Invalid username or password.")
            return

        if self.on_login_success:
            self.hide()
            self.on_login_success(user)
            self.close()
        else:
            QMessageBox.information(self, "Success", f"Welcome, {username}!")

    def handle_forgot_next(self):
        username = self.fg_username.text().strip()
        if not username:
            QMessageBox.warning(self, "Reset password", "Please enter username.")
            return

        try:
            question = self.db.get_security_question(username)
        except Exception:
            QMessageBox.critical(
                self,
                "Service unavailable",
                "Password recovery service is unavailable.",
            )
            return

        if not question:
            QMessageBox.warning(self, "Reset password", "Username not found.")
            return

        self.fg_question_label.setText(question)
        self._show_card(self.forgot_reset_page)
        QtCore.QTimer.singleShot(0, self.fg_answer.setFocus)

    def handle_forgot_reset(self):
        username = self.fg_username.text().strip()
        answer = self.fg_answer.text().strip()
        new_password = self.fg_newpass.text().strip()

        if not answer or not new_password:
            QMessageBox.warning(
                self,
                "Reset password",
                "Please enter your security answer and a new password.",
            )
            return

        if not self.db.verify_security_answer(username, answer):
            QMessageBox.warning(self, "Reset password", "Incorrect security answer.")
            return

        self.db.update_password(username, new_password)
        QMessageBox.information(self, "Reset password", "Password updated.")

        self.username.setText(username)
        self.password_field.clear()
        self.show_login_page()

    # ------------------------------------------------------------------
    # STYLES
    # ------------------------------------------------------------------
    def _apply_styles(self):
        self.setStyleSheet("""
        QWidget#authWindow {
            background:#F6F8FC;
            color:#172033;
            font-family:"Segoe UI Variable Text","Segoe UI",Arial,sans-serif;
            font-size:12px;
        }
        QWidget#brandPanel {
            background:transparent;
            border-right:1px solid rgba(203,214,228,180);
        }
        QFrame#loginSide {
            background:rgba(255,255,255,0.40);
        }
        QFrame#loginCard {
            background:#FFFFFF;
            border:1px solid #C9D5E5;
            border-radius:24px;
        }
        QLabel#brandName {
            color:#172033;
            font-size:20px;
            font-weight:800;
        }
        QLabel#brandKicker {
            color:#5F7087;
            font-size:9px;
            font-weight:700;
            letter-spacing:1.6px;
        }
        QLabel#heroChip {
            color:#315A9A;
            background:rgba(255,255,255,0.82);
            border:1px solid #D7E3F6;
            border-radius:15px;
            padding:0 11px;
            font-size:10px;
            font-weight:700;
        }
        QLabel#heroTitle {
            color:#172033;
            font-size:43px;
            line-height:1.04;
            font-weight:800;
        }
        QLabel#heroCopy {
            color:#5F7087;
            font-size:14px;
            line-height:1.55;
        }
        QFrame#capabilityCard {
            background:rgba(255,255,255,0.82);
            border:1px solid #C9D5E5;
            border-radius:16px;
        }
        QLabel#capabilityIcon {
            color:#2868E8;
            background:#EEF4FF;
            border-radius:10px;
            font-size:11px;
            font-weight:800;
        }
        QLabel#capabilityTitle {
            color:#172033;
            font-size:11px;
            font-weight:750;
        }
        QLabel#capabilityBody {
            color:#5F7087;
            font-size:9px;
        }
        QLabel#secureRing {
            color:#159A67;
            background:#EAF8F2;
            border-radius:12px;
            font-weight:800;
        }
        QLabel#brandFooter {
            color:#718099;
            font-size:9px;
        }
        QLabel#loginTitle {
            color:#172033;
            font-size:26px;
            font-weight:800;
        }
        QLabel#loginSubtitle {
            color:#5F7087;
            font-size:12px;
        }
        QLabel#fieldLabel {
            color:#344156;
            font-size:11px;
            font-weight:700;
        }
        QLineEdit#authInput {
            min-height:46px;
            padding:0 14px;
            background:#FFFFFF;
            color:#172033;
            border:1px solid #CBD6E4;
            border-radius:10px;
            selection-background-color:#2868E8;
            selection-color:white;
            font-size:12px;
        }
        QLineEdit#authInput:focus {
            border:1px solid #2868E8;
        }
        QPushButton#passwordToggle {
            background:transparent;
            color:#718099;
            border:0;
            border-radius:8px;
            font-size:9px;
            font-weight:650;
        }
        QPushButton#passwordToggle:hover {
            background:#F2F6FC;
            color:#2868E8;
        }
        QPushButton#linkButton {
            background:transparent;
            color:#2868E8;
            border:0;
            padding:4px 0;
            font-size:10px;
            font-weight:700;
        }
        QPushButton#linkButton:hover { color:#1E56C7; }
        QPushButton#primaryButton {
            min-height:46px;
            color:#FFFFFF;
            background:#2868E8;
            border:1px solid #2868E8;
            border-radius:10px;
            font-size:11px;
            font-weight:750;
        }
        QPushButton#primaryButton:hover {
            background:#1E56C7;
            border-color:#1E56C7;
        }
        QPushButton#primaryButton:pressed {
            background:#1949A9;
            border-color:#1949A9;
        }
        QPushButton#googleButton {
            min-height:44px;
            color:#2B3545;
            background:#FFFFFF;
            border:1px solid #CBD6E4;
            border-radius:10px;
            font-size:10px;
            font-weight:700;
        }
        QPushButton#googleButton:hover {
            background:#F9FBFE;
            border-color:#AFC2DE;
        }
        QPushButton#googleButton:disabled {
            color:#8C98A8;
            background:#F5F7FA;
        }
        QFrame#divider {
            color:#E4EAF2;
        }
        QLabel#orLabel {
            color:#6F8097;
            font-size:10px;
        }
        QFrame#loginMeta {
            border-top:1px solid #ECF0F5;
        }
        QLabel#metaReady {
            color:#159A67;
            font-size:9px;
        }
        QLabel#metaText {
            color:#64758D;
            font-size:9px;
        }
        QPushButton#backButton {
            background:#FFFFFF;
            color:#3C4A60;
            border:1px solid #C9D5E5;
            border-radius:10px;
            font-size:15px;
            font-weight:700;
        }
        QPushButton#backButton:hover {
            background:#EEF3F9;
            color:#2868E8;
        }
        QLabel#forgotTitle {
            color:#172033;
            font-size:20px;
            font-weight:780;
        }
        QLabel#forgotCopy {
            color:#5F7087;
            font-size:11px;
        }
        QFrame#recoveryForm {
            background:transparent;
            border:0;
        }
        QFrame#questionBox {
            background:#F7FAFE;
            border:1px solid #CFDAE7;
            border-radius:10px;
        }
        QLabel#questionKicker {
            color:#78869A;
            font-size:8px;
            font-weight:800;
        }
        QLabel#questionText {
            color:#172033;
            font-size:11px;
            font-weight:650;
        }
        QMessageBox {
            background:#FFFFFF;
            color:#172033;
        }
        QMessageBox QLabel {
            background:transparent;
            color:#172033;
            font-size:11px;
            min-width:260px;
        }
        QMessageBox QPushButton {
            min-width:72px;
            min-height:30px;
            padding:0 12px;
            background:#FFFFFF;
            color:#172033;
            border:1px solid #CBD6E4;
            border-radius:8px;
            font-size:10px;
            font-weight:650;
        }
        QMessageBox QPushButton:hover {
            background:#EEF4FF;
            color:#2868E8;
            border-color:#AFC2DE;
        }
        """)


__all__ = ["LoginWindow"]
