# login_window.py
# Login UI for EYRES QC project
from PyQt5.QtWidgets import (
    QWidget,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QMessageBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QStackedWidget,
    QFrame,
)
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtCore import Qt, QEvent, QPoint, QSize, pyqtSignal
from db import Database
from app_core.audit import record_audit_event
from ui.theme import apply_light_surface, asset_path
from pathlib import Path
import sys, os
import threading
from .google_auth import authenticate_google, GoogleAuthError


def _app_base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _find_logo() -> Path | None:
    media = _app_base_dir() / "Media"
    modern = asset_path("app.png")
    if modern.is_file():
        return modern
    if not media.exists():
        return None
    for name in ("EYRES QC.png", "EYRES QC Black.png", "EYRES QC LOGO MARK.png"):
        p = media / name
        if p.is_file():
            return p
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.gif", "*.webp"):
        files = list(media.glob(ext))
        if files:
            return files[0]
    return None


# ================== SIGNUP & FORGOT DIALOGS (OLD – LOGIC REUSED, UI NOT USED) ==================
class SignupDialog(QDialog):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db

        self.setWindowTitle("Create Account")
        self.setModal(True)
        self.resize(560, 620)

        # ---- Dark theme & card style ----
        self.setStyleSheet("""
        QDialog {
            background-color: #050608;
        }
        #SignupCard {
            background-color: #11141a;
            border-radius: 18px;
            border: 1px solid #1f2430;
        }
        QLabel#SignupTitle {
            color: #ffffff;
            font-size: 20px;
            font-weight: 800;
        }
        QLabel {
            color: #c7d0e0;
            font-size: 12px;
        }
        QLineEdit {
            padding: 8px 10px;
            border-radius: 6px;
            background-color: #050608;
            border: 1px solid #222733;
            color: #ffffff;
            font-size: 13px;
        }
        QLineEdit:focus {
            border: 1px solid #2E86FF;
        }
        QPushButton#SignupButton {
            background-color: #1B5FCC;
            color: #ffffff;
            padding: 10px 20px;
            border-radius: 22px;
            font-size: 14px;
            font-weight: bold;
        }
        QPushButton#SignupButton:hover {
            background-color: #2E86FF;
        }
        """)

        # ===== OUTER LAYOUT (centres the card) =====
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        wrapper = QWidget(self)
        wlay = QVBoxLayout(wrapper)
        wlay.setAlignment(Qt.AlignCenter)
        wlay.setContentsMargins(0, 0, 0, 0)
        wlay.setSpacing(0)
        outer.addWidget(wrapper)

        # ===== CARD =====
        card = QWidget(wrapper)
        card.setObjectName("SignupCard")
        card.setFixedWidth(460)

        cl = QVBoxLayout(card)
        cl.setContentsMargins(40, 32, 40, 32)
        cl.setSpacing(12)

        # Title + subtitle
        title = QLabel("Create New Account")
        title.setObjectName("SignupTitle")
        title.setAlignment(Qt.AlignCenter)
        cl.addWidget(title)

        subtitle = QLabel("Enter your details to get started.")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color:#9ca3af; font-size:12px;")
        cl.addWidget(subtitle)
        cl.addSpacing(10)

        # ===== FIELDS (labels above inputs like login page) =====
        def add_field(label_text: str) -> QLineEdit:
            lbl = QLabel(label_text)
            cl.addWidget(lbl)
            edit = QLineEdit()
            cl.addWidget(edit)
            return edit

        self.ed_username = add_field("Username")
        self.ed_email    = add_field("Email")
        self.ed_password = add_field("Password")
        self.ed_confirm  = add_field("Confirm Password")
        self.ed_question = add_field("Security Question")
        self.ed_answer   = add_field("Answer")

        self.ed_password.setEchoMode(QLineEdit.Password)
        self.ed_confirm.setEchoMode(QLineEdit.Password)
        self.ed_answer.setEchoMode(QLineEdit.Password)

        cl.addSpacing(10)

        # ===== CREATE ACCOUNT BUTTON =====
        btn = QPushButton("Create Account")
        btn.setObjectName("SignupButton")
        btn.clicked.connect(self.handle_signup)
        cl.addWidget(btn)

        wlay.addWidget(card, 0, Qt.AlignCenter)

        # centre dialog over parent (nice UX)
        if parent is not None:
            self._center_over_parent(parent)

    def _center_over_parent(self, parent: QWidget):
        parent_geo = parent.frameGeometry()
        my_geo = self.frameGeometry()
        my_geo.moveCenter(parent_geo.center())
        self.move(my_geo.topLeft())

    def handle_signup(self):
        username = self.ed_username.text().strip()
        email    = self.ed_email.text().strip()
        pwd      = self.ed_password.text().strip()
        cpwd     = self.ed_confirm.text().strip()
        q        = self.ed_question.text().strip()
        ans      = self.ed_answer.text().strip()

        if not username or not pwd or not q or not ans:
            QMessageBox.warning(self, "Error", "All fields except email are required.")
            return

        if pwd != cpwd:
            QMessageBox.warning(self, "Error", "Passwords do not match.")
            return

        try:
            self.db.create_user(username, pwd, email, q, ans)
            QMessageBox.information(self, "Success", "Account created successfully!")
            self.accept()
        except ValueError as e:
            QMessageBox.warning(self, "Error", str(e))


class ForgotPasswordDialog(QDialog):
    """Old dialog version – kept only for reference, not used by LoginWindow now."""
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db

        self.setWindowTitle("Reset Password")
        self.setFixedSize(420, 300)
        self.setStyleSheet("background:#111; color:white;")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.ed_username = QLineEdit()
        self.ed_username.setPlaceholderText("Enter username")

        btn_fetch = QPushButton("Next")
        btn_fetch.clicked.connect(self.fetch_question)

        layout.addWidget(self.ed_username)
        layout.addWidget(btn_fetch)

        self.stage2 = QWidget()
        layout2 = QFormLayout(self.stage2)

        self.lbl_question = QLabel("")
        self.ed_answer = QLineEdit()
        self.ed_newpass = QLineEdit()

        self.ed_answer.setEchoMode(QLineEdit.Password)
        self.ed_newpass.setEchoMode(QLineEdit.Password)

        layout2.addRow("Security Q:", self.lbl_question)
        layout2.addRow("Answer:", self.ed_answer)
        layout2.addRow("New Password:", self.ed_newpass)

        self.btn_reset = QPushButton("Reset Password")
        self.btn_reset.clicked.connect(self.reset_pass)

        layout2.addWidget(self.btn_reset)
        self.stage2.hide()
        layout.addWidget(self.stage2)

    def fetch_question(self):
        username = self.ed_username.text().strip()
        q = self.db.get_security_question(username)
        if not q:
            QMessageBox.warning(self, "Error", "Username not found.")
            return

        self.lbl_question.setText(q)
        self.stage2.show()

    def reset_pass(self):
        username = self.ed_username.text().strip()
        ans = self.ed_answer.text().strip()
        newpwd = self.ed_newpass.text().strip()

        if not self.db.verify_security_answer(username, ans):
            QMessageBox.warning(self, "Error", "Incorrect security answer.")
            return

        self.db.update_password(username, newpwd)
        QMessageBox.information(self, "Success", "Password updated!")
        self.accept()


# ================== LOGIN WINDOW ==================

class LoginWindow(QWidget):
    google_auth_result = pyqtSignal(object, object)

    def __init__(self, on_login_success=None):
        super().__init__()
        self.db = Database()
        self.on_login_success = on_login_success
        self.google_auth_result.connect(self._handle_google_auth_result)
        self._google_auth_running = False

        self.setWindowTitle("EYRES QC - Login")

        icon_path = asset_path("app.ico")
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setMinimumSize(960, 540)
        # open maximized
        self.setWindowState(self.windowState() | Qt.WindowMaximized)

        self.build_ui()
        apply_light_surface(self)

    # ---------- page switching helpers ----------

    def show_login_page(self):
        self.card_stack.setCurrentWidget(self.login_page)

    def show_signup_page(self):
        self.card_stack.setCurrentWidget(self.signup_page)

    def show_forgot_page(self):
        # reset forgot-page fields each time
        self.fg_username.clear()
        self.fg_answer.clear()
        self.fg_newpass.clear()
        self.fg_question_label.setText("—")
        self.fg_stage2.hide()
        self.card_stack.setCurrentWidget(self.forgot_page)

    # ---------- Handlers called from buttons ----------

    def open_signup(self):
        # inline page instead of dialog
        self.show_signup_page()

    def open_forgot_password(self):
        # inline page instead of dialog
        self.show_forgot_page()
    
    # ---------- KEYBOARD NAVIGATION HELPERS (Up/Down) ----------

    def _register_nav(self, edit: QLineEdit, group: str):
        """
        Attach our eventFilter to a line edit and tag it with a group name.
        Up/Down arrows will move inside the same group, in visual (top-to-bottom) order.
        """
        if edit is None:
            return
        edit.setProperty("nav_group", group)
        edit.installEventFilter(self)

    def eventFilter(self, obj, event):
        # Handle arrow keys on text fields
        if isinstance(obj, QLineEdit) and event.type() == QEvent.KeyPress:
            key = event.key()

            if key in (Qt.Key_Down, Qt.Key_Up):
                group = obj.property("nav_group")
                if not group:
                    return False

                # All visible, enabled fields in the same group (same page)
                edits = [
                    e for e in self.findChildren(QLineEdit)
                    if e.property("nav_group") == group
                    and e.isVisible()
                    and e.isEnabled()
                ]
                if not edits:
                    return False

                # Sort them by screen position → top-to-bottom, left-to-right
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

                if key == Qt.Key_Down and idx < len(edits) - 1:
                    edits[idx + 1].setFocus()
                    return True
                elif key == Qt.Key_Up and idx > 0:
                    edits[idx - 1].setFocus()
                    return True

        return super().eventFilter(obj, event)


    # ---------- UI BUILD ----------

    def build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        center_wrapper = QWidget(self)
        center_layout = QVBoxLayout(center_wrapper)
        center_layout.setAlignment(Qt.AlignCenter)
        center_layout.setContentsMargins(40, 40, 40, 40)
        center_layout.setSpacing(0)

        # stacked pages: login + signup + forgot
        self.card_stack = QStackedWidget(center_wrapper)
        center_layout.addWidget(self.card_stack, 0, Qt.AlignCenter)

        self.login_page  = self._build_login_page()
        self.forgot_page = self._build_forgot_page()

        self.card_stack.addWidget(self.login_page)
        self.card_stack.addWidget(self.forgot_page)
        self.show_login_page()

        main_layout.addWidget(center_wrapper)

    # ---------- LOGIN PAGE (present design) ----------

    def _build_login_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)

        # ---- Card ----
        card = QWidget(page)
        card.setObjectName("login_card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(18)
        card_layout.setContentsMargins(40, 36, 40, 32)
        card.setFixedWidth(460)

        card.setStyleSheet("""
            QWidget#login_card {
                background-color: #181a1f;
                border-radius: 18px;
            }
            QWidget#login_card * {
                background-color: #181a1f;
            }
        """)
        card.setAttribute(Qt.WA_StyledBackground, True)

        # ---------- header (logo + title + subtitle) ----------
        header_box = QWidget(card)
        header_box.setObjectName("header_box")
        header_box.setStyleSheet("#header_box { background-color:#181a1f; }")
        header_layout = QVBoxLayout(header_box)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        logo_widget = QLabel()
        logo_widget.setAlignment(Qt.AlignCenter)
        pm = None
        logo_path = _find_logo()
        if logo_path is not None:
            pm = QPixmap(str(logo_path))
        if pm is not None and not pm.isNull():
            pm = pm.scaled(110, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_widget.setPixmap(pm)
        else:
            logo_widget.setText("EYRES QC")
            logo_widget.setStyleSheet("""
                QLabel {
                    color: #2E86FF;
                    font-size: 30px;
                    font-weight: 900;
                }
            """)
        header_layout.addWidget(logo_widget)

        title = QLabel("Log in to your account")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 22px;
                font-weight: 800;
            }
        """)
        header_layout.addWidget(title)

        subtitle = QLabel("Welcome back! Please enter your details below.")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("""
            QLabel {
                color: #9ca3af;
                font-size: 13px;
            }
        """)
        header_layout.addWidget(subtitle)

        card_layout.addWidget(header_box)
        card_layout.addSpacing(6)

        # ---------- fields ----------
        fields_container = QWidget(card)
        fields_container.setObjectName("fields_container")
        fields_container.setStyleSheet("#fields_container { background-color:#181a1f; }")
        fields_layout = QVBoxLayout(fields_container)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        fields_layout.setSpacing(10)

        lbl_user = QLabel("Username")
        lbl_user.setStyleSheet("color:#e5e7eb; font-size:13px; font-weight:600;")
        fields_layout.addWidget(lbl_user)

        self.username = QLineEdit()
        self.username.setPlaceholderText("Enter your username")
        self.username.setMinimumHeight(40)
        self.username.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                border-radius: 8px;
                background-color: #111317;
                border: 1px solid #2d3138;
                color: white;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #1B5FCC;
            }
        """)
        fields_layout.addWidget(self.username)

        lbl_pass = QLabel("Password")
        lbl_pass.setStyleSheet("color:#e5e7eb; font-size:13px; font-weight:600; margin-top:4px;")
        fields_layout.addWidget(lbl_pass)

        self.password = QLineEdit()
        self.password.setPlaceholderText("••••••••")
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setMinimumHeight(40)
        self.password.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                border-radius: 8px;
                background-color: #111317;
                border: 1px solid #2d3138;
                color: white;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #1B5FCC;
            }
        """)
        fields_layout.addWidget(self.password)

        # Forgot password row
        forgot_row = QHBoxLayout()
        forgot_row.setContentsMargins(0, 0, 0, 0)
        forgot_row.addStretch(1)

        forgot_btn = QPushButton("Forgot password?")
        forgot_btn.setFlat(True)
        forgot_btn.setCursor(Qt.PointingHandCursor)
        forgot_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #2E86FF;
                border: none;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                text-decoration: underline;
            }
        """)
        forgot_btn.clicked.connect(self.open_forgot_password)
        forgot_row.addWidget(forgot_btn)
        fields_layout.addLayout(forgot_row)

        card_layout.addWidget(fields_container)

        # ---------- login button (rounded) ----------
        login_btn = QPushButton("Login")
        login_btn.setObjectName("LoginButton")
        login_btn.setMinimumHeight(44)
        login_btn.setStyleSheet("""
            QPushButton#LoginButton {
                background-color: #1B5FCC;
                color: white;
                padding: 10px 20px;
                border-radius: 22px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton#LoginButton:hover {
                background-color: #2E86FF;
            }
        """)
        login_btn.clicked.connect(self.try_login)
        card_layout.addWidget(login_btn)

        # ---------- Google Sign-In ----------
        divider_row = QHBoxLayout()
        divider_row.setContentsMargins(0, 2, 0, 2)
        divider_row.setSpacing(10)
        left_line = QFrame()
        right_line = QFrame()
        left_line.setFrameShape(QFrame.HLine)
        right_line.setFrameShape(QFrame.HLine)
        left_line.setStyleSheet("color:#d9dee7;")
        right_line.setStyleSheet("color:#d9dee7;")
        or_label = QLabel("or")
        or_label.setAlignment(Qt.AlignCenter)
        or_label.setStyleSheet("color:#8b95a5; font-size:12px;")
        divider_row.addWidget(left_line, 1)
        divider_row.addWidget(or_label)
        divider_row.addWidget(right_line, 1)
        card_layout.addLayout(divider_row)

        google_btn = QPushButton()
        google_btn.setObjectName("GoogleButton")
        google_btn.setMinimumHeight(44)
        google_btn.setCursor(Qt.PointingHandCursor)
        google_btn.setIcon(QIcon(str(asset_path("google_g.svg"))))
        google_btn.setIconSize(QSize(20, 20))
        google_btn.setText("Continue with Google")
        google_btn.setStyleSheet("""
            QPushButton#GoogleButton {
                background-color: #ffffff;
                color: #202124;
                border: 1px solid #dadce0;
                border-radius: 22px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton#GoogleButton:hover {
                background-color: #f8f9fa;
                border-color: #c7cbd1;
            }
            QPushButton#GoogleButton:disabled {
                color: #9aa0a6;
                background-color: #f5f6f7;
            }
        """)
        google_btn.clicked.connect(self.start_google_login)
        card_layout.addWidget(google_btn)
        self.google_btn = google_btn

        self.password.returnPressed.connect(self.try_login)
        # ----- Keyboard navigation: login page -----
        # Up/Down between username and password
        self._register_nav(self.username, "login")
        self._register_nav(self.password, "login")

        # Enter on username → go to password
        self.username.returnPressed.connect(lambda: self.password.setFocus())
        # (Enter on password already triggers try_login via returnPressed)


        card_layout.addSpacing(10)

        # Public account creation is disabled in production. Administrators
        # provision named accounts and roles from the managed-user workflow.
        '''# ---------- divider ----------
        divider_row = QHBoxLayout()
        divider_row.setContentsMargins(0, 0, 0, 0)
        divider_row.setSpacing(10)

        line_left = QWidget()
        line_left.setFixedHeight(1)
        line_left.setStyleSheet("background-color:#272b33;")
        line_right = QWidget()
        line_right.setFixedHeight(1)
        line_right.setStyleSheet("background-color:#272b33;")

        divider_label = QLabel("or")
        divider_label.setStyleSheet("color:#6b7280; font-size:12px;")

        divider_row.addWidget(line_left, 1)
        divider_row.addWidget(divider_label)
        divider_row.addWidget(line_right, 1)
        card_layout.addLayout(divider_row)
        card_layout.addSpacing(8)

        # ---------- bottom "create account" ----------
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(4)
        bottom_row.setAlignment(Qt.AlignCenter)

        lbl_no_acc = QLabel("Don’t have an account?")
        lbl_no_acc.setStyleSheet("color:#9ca3af; font-size:12px;")
        bottom_row.addWidget(lbl_no_acc)

        create_btn = QPushButton("Create account")
        create_btn.setFlat(True)
        create_btn.setCursor(Qt.PointingHandCursor)
        create_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #2E86FF;
                border: none;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                text-decoration: underline;
            }
        """)
        create_btn.clicked.connect(self.open_signup)
        bottom_row.addWidget(create_btn)

        card_layout.addLayout(bottom_row)'''

        layout.addWidget(card, 0, Qt.AlignCenter)
        return page

    # ---------- SIGNUP PAGE (inline) ----------

    def _build_signup_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)

        card = QWidget(page)
        card.setObjectName("login_card")  # reuse same style
        card.setStyleSheet("""
            QWidget#login_card {
                background-color: #181a1f;
                border-radius: 18px;
            }
            QWidget#login_card * {
                background-color: #181a1f;
            }
        """)
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setFixedWidth(460)

        cl = QVBoxLayout(card)
        cl.setContentsMargins(40, 36, 40, 32)
        cl.setSpacing(12)

        title = QLabel("Create New Account")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 20px;
                font-weight: 800;
            }
        """)
        cl.addWidget(title)

        subtitle = QLabel("Enter your details to get started.")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color:#9ca3af; font-size:13px;")
        cl.addWidget(subtitle)
        cl.addSpacing(8)

        def add_field(label_text: str, is_password: bool = False) -> QLineEdit:
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color:#e5e7eb; font-size:13px; font-weight:600;")
            cl.addWidget(lbl)
            edit = QLineEdit()
            edit.setMinimumHeight(38)
            if is_password:
                edit.setEchoMode(QLineEdit.Password)
            edit.setStyleSheet("""
                QLineEdit {
                    padding: 8px 10px;
                    border-radius: 8px;
                    background-color: #111317;
                    border: 1px solid #2d3138;
                    color: white;
                    font-size: 13px;
                }
                QLineEdit:focus {
                    border: 1px solid #1B5FCC;
                }
            """)
            cl.addWidget(edit)
            return edit

        self.ed_username = add_field("Username")
        self.ed_email    = add_field("Email")
        self.ed_password = add_field("Password", is_password=True)
        self.ed_confirm  = add_field("Confirm Password", is_password=True)
        self.ed_question = add_field("Security Question")
        self.ed_answer   = add_field("Answer", is_password=True)

        cl.addSpacing(10)

        signup_btn = QPushButton("Create Account")
        signup_btn.setMinimumHeight(44)
        signup_btn.setStyleSheet("""
            QPushButton {
                background-color: #1B5FCC;
                color: white;
                padding: 10px 20px;
                border-radius: 22px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2E86FF;
            }
        """)
        signup_btn.clicked.connect(self.handle_signup_inline)
        cl.addWidget(signup_btn)

        cl.addSpacing(8)
        # ----- Keyboard navigation: signup page -----
        # Up/Down between all signup fields
        for w in (
            self.ed_username,
            self.ed_email,
            self.ed_password,
            self.ed_confirm,
            self.ed_question,
            self.ed_answer,
        ):
            self._register_nav(w, "signup")

        # Enter chain through fields, last one = Create Account
        self.ed_username.returnPressed.connect(lambda: self.ed_email.setFocus())
        self.ed_email.returnPressed.connect(lambda: self.ed_password.setFocus())
        self.ed_password.returnPressed.connect(lambda: self.ed_confirm.setFocus())
        self.ed_confirm.returnPressed.connect(lambda: self.ed_question.setFocus())
        self.ed_question.returnPressed.connect(lambda: self.ed_answer.setFocus())
        self.ed_answer.returnPressed.connect(self.handle_signup_inline)


        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(4)
        bottom_row.setAlignment(Qt.AlignCenter)

        lbl_have = QLabel("Already have an account?")
        lbl_have.setStyleSheet("color:#9ca3af; font-size:12px;")
        bottom_row.addWidget(lbl_have)

        back_btn = QPushButton("Log in")
        back_btn.setFlat(True)
        back_btn.setCursor(Qt.PointingHandCursor)
        back_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #2E86FF;
                border: none;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                text-decoration: underline;
            }
        """)
        back_btn.clicked.connect(self.show_login_page)
        bottom_row.addWidget(back_btn)

        cl.addLayout(bottom_row)

        layout.addWidget(card, 0, Qt.AlignCenter)
        return page

    # ---------- FORGOT PASSWORD PAGE (inline) ----------

    def _build_forgot_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)

        card = QWidget(page)
        card.setObjectName("login_card")
        card.setStyleSheet("""
            QWidget#login_card {
                background-color: #181a1f;
                border-radius: 18px;
            }
            QWidget#login_card * {
                background-color: #181a1f;
            }
        """)
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setFixedWidth(460)

        cl = QVBoxLayout(card)
        cl.setContentsMargins(40, 36, 40, 32)
        cl.setSpacing(12)

        title = QLabel("Reset Password")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 20px;
                font-weight: 800;
            }
        """)
        cl.addWidget(title)

        subtitle = QLabel("Enter your username to find your account.")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color:#9ca3af; font-size:13px;")
        cl.addWidget(subtitle)
        cl.addSpacing(8)

        # Username field
        lbl_user = QLabel("Username")
        lbl_user.setStyleSheet("color:#e5e7eb; font-size:13px; font-weight:600;")
        cl.addWidget(lbl_user)

        self.fg_username = QLineEdit()
        self.fg_username.setMinimumHeight(38)
        self.fg_username.setPlaceholderText("Enter your username")
        self.fg_username.setStyleSheet("""
            QLineEdit {
                padding: 8px 10px;
                border-radius: 8px;
                background-color: #111317;
                border: 1px solid #2d3138;
                color: white;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #1B5FCC;
            }
        """)
        cl.addWidget(self.fg_username)
        # ----- Keyboard navigation: forgot-page (stage 1) -----
        self._register_nav(self.fg_username, "forgot")
        # Enter on username → same as clicking Next
        self.fg_username.returnPressed.connect(self.handle_forgot_next)


        # NEXT button
        next_btn = QPushButton("Next")
        next_btn.setMinimumHeight(40)
        next_btn.setStyleSheet("""
            QPushButton {
                background-color: #1B5FCC;
                color: white;
                padding: 8px 16px;
                border-radius: 20px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2E86FF;
            }
        """)
        next_btn.clicked.connect(self.handle_forgot_next)
        cl.addWidget(next_btn)

        cl.addSpacing(8)

        # Stage 2: security question + answer + new password
        self.fg_stage2 = QWidget(card)
        s2_layout = QVBoxLayout(self.fg_stage2)
        s2_layout.setContentsMargins(0, 0, 0, 0)
        s2_layout.setSpacing(8)

        lbl_q = QLabel("Security Question")
        lbl_q.setStyleSheet("color:#e5e7eb; font-size:13px; font-weight:600;")
        s2_layout.addWidget(lbl_q)

        self.fg_question_label = QLabel("—")
        self.fg_question_label.setStyleSheet("color:#9ca3af; font-size:13px;")
        s2_layout.addWidget(self.fg_question_label)

        lbl_ans = QLabel("Answer")
        lbl_ans.setStyleSheet("color:#e5e7eb; font-size:13px; font-weight:600; margin-top:4px;")
        s2_layout.addWidget(lbl_ans)

        self.fg_answer = QLineEdit()
        self.fg_answer.setMinimumHeight(38)
        self.fg_answer.setEchoMode(QLineEdit.Password)
        self.fg_answer.setStyleSheet("""
            QLineEdit {
                padding: 8px 10px;
                border-radius: 8px;
                background-color: #111317;
                border: 1px solid #2d3138;
                color: white;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #1B5FCC;
            }
        """)
        s2_layout.addWidget(self.fg_answer)

        lbl_np = QLabel("New Password")
        lbl_np.setStyleSheet("color:#e5e7eb; font-size:13px; font-weight:600; margin-top:4px;")
        s2_layout.addWidget(lbl_np)

        self.fg_newpass = QLineEdit()
        self.fg_newpass.setMinimumHeight(38)
        self.fg_newpass.setEchoMode(QLineEdit.Password)
        self.fg_newpass.setStyleSheet("""
            QLineEdit {
                padding: 8px 10px;
                border-radius: 8px;
                background-color: #111317;
                border: 1px solid #2d3138;
                color: white;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #1B5FCC;
            }
        """)
        s2_layout.addWidget(self.fg_newpass)

        # ----- Keyboard navigation: forgot-page (stage 2) -----
        self._register_nav(self.fg_answer, "forgot")
        self._register_nav(self.fg_newpass, "forgot")

        self.fg_answer.returnPressed.connect(lambda: self.fg_newpass.setFocus())
        # Enter on new password → Reset Password
        self.fg_newpass.returnPressed.connect(self.handle_forgot_reset)


        reset_btn = QPushButton("Reset Password")
        reset_btn.setMinimumHeight(40)
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #1B5FCC;
                color: white;
                padding: 8px 16px;
                border-radius: 20px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2E86FF;
            }
        """)
        reset_btn.clicked.connect(self.handle_forgot_reset)
        s2_layout.addWidget(reset_btn)

        self.fg_stage2.hide()
        cl.addWidget(self.fg_stage2)

        cl.addSpacing(8)

        # Back to login link
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(4)
        bottom_row.setAlignment(Qt.AlignCenter)

        lbl_back = QLabel("Remembered your password?")
        lbl_back.setStyleSheet("color:#9ca3af; font-size:12px;")
        bottom_row.addWidget(lbl_back)

        back_btn = QPushButton("Back to login")
        back_btn.setFlat(True)
        back_btn.setCursor(Qt.PointingHandCursor)
        back_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #2E86FF;
                border: none;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                text-decoration: underline;
            }
        """)
        back_btn.clicked.connect(self.show_login_page)
        bottom_row.addWidget(back_btn)

        cl.addLayout(bottom_row)

        layout.addWidget(card, 0, Qt.AlignCenter)
        return page

    # ---------- GOOGLE SIGN-IN ----------
    def start_google_login(self):
        if self._google_auth_running:
            return
        self._google_auth_running = True
        self.google_btn.setEnabled(False)
        self.google_btn.setText("Opening Google…")
        worker = threading.Thread(target=self._google_login_worker, daemon=True)
        worker.start()

    def _google_login_worker(self):
        try:
            identity = authenticate_google()
            self.google_auth_result.emit(identity, None)
        except Exception as exc:
            self.google_auth_result.emit(None, exc)

    def _handle_google_auth_result(self, identity, error):
        self._google_auth_running = False
        self.google_btn.setEnabled(True)
        self.google_btn.setText("Continue with Google")

        if error is not None:
            QMessageBox.warning(self, "Google Sign-In", str(error))
            return

        try:
            user = self.db.get_user_by_provider_identity("google", identity.provider_user_id)

            if user is None:
                # Only automatically link an existing account when Google confirms the email.
                if not identity.verified_email:
                    raise GoogleAuthError("Google did not verify this email address.")
                user = self.db.get_user_by_email(identity.email)
                if user is not None:
                    self.db.link_provider_identity(
                        user.get("username", ""), "google", identity.provider_user_id, identity.email
                    )
                    user = self.db.get_user_by_provider_identity("google", identity.provider_user_id)
                else:
                    user = self.db.create_google_user(
                        identity.email, identity.name, identity.provider_user_id
                    )

            if not user:
                raise GoogleAuthError("Unable to create or find the platform account.")
            if not user.get("active", True):
                raise GoogleAuthError("This platform account is disabled. Contact an administrator.")

            if self.on_login_success:
                self.on_login_success(user)
                self.close()
            else:
                QMessageBox.information(self, "Success", f"Welcome, {user.get('username', identity.email)}!")
        except Exception as exc:
            record_audit_event("google_login_error", actor=identity.email, status="failed",
                               details={"error_type": type(exc).__name__})
            QMessageBox.critical(self, "Google Sign-In", str(exc))

    # ---------- LOGIN & SIGNUP LOGIC ----------
    def try_login(self):
        username = self.username.text().strip()
        password = self.password.text().strip()

        if not username or not password:
            QMessageBox.warning(self, "Error", "Please enter username and password")
            return

        try:
            user = self.db.find_user(username, password)
        except Exception as exc:
            record_audit_event("login_error", actor=username, status="failed",
                               details={"error_type": type(exc).__name__})
            QMessageBox.critical(self, "Service unavailable",
                                 "Login service is unavailable. Please contact the administrator.")
            return
        if not user:
            record_audit_event("login_denied", actor=username, status="denied",
                               details={"reason": "invalid_credentials_or_disabled"})
            QMessageBox.warning(self, "Error", "Invalid username or password")
            return

        if self.on_login_success:
            # Hide the login immediately so the browser callback cannot leave
            # the login page visible while the dashboard is being created.
            self.hide()

            # Open the main window through Main_GUI.after_login().
            self.on_login_success(user)

            # Close the login window after the dashboard has been handed off.
            self.close()
        else:
            QMessageBox.information(self, "Success", f"Welcome, {username}!")


    def handle_signup_inline(self):
        username = self.ed_username.text().strip()
        email    = self.ed_email.text().strip()
        pwd      = self.ed_password.text().strip()
        cpwd     = self.ed_confirm.text().strip()
        q        = self.ed_question.text().strip()
        ans      = self.ed_answer.text().strip()

        if not username or not pwd or not q or not ans:
            QMessageBox.warning(self, "Error", "All fields except email are required.")
            return
        if pwd != cpwd:
            QMessageBox.warning(self, "Error", "Passwords do not match.")
            return

        try:
            self.db.create_user(username, pwd, email, q, ans)
            QMessageBox.information(self, "Success", "Account created successfully!")
            # go back to login and prefill username
            self.show_login_page()
            self.username.setText(username)
            self.password.setText("")
        except ValueError as e:
            QMessageBox.warning(self, "Error", str(e))

    # ---------- FORGOT PASSWORD LOGIC (inline page) ----------

    def handle_forgot_next(self):
        username = self.fg_username.text().strip()
        if not username:
            QMessageBox.warning(self, "Error", "Please enter username.")
            return

        q = self.db.get_security_question(username)
        if not q:
            QMessageBox.warning(self, "Error", "Username not found.")
            self.fg_stage2.hide()
            self.fg_question_label.setText("—")
            return

        self.fg_question_label.setText(q)
        self.fg_stage2.show()

    def handle_forgot_reset(self):
        username = self.fg_username.text().strip()
        ans      = self.fg_answer.text().strip()
        newpwd   = self.fg_newpass.text().strip()

        if not ans or not newpwd:
            QMessageBox.warning(self, "Error", "Please enter answer and new password.")
            return

        if not self.db.verify_security_answer(username, ans):
            QMessageBox.warning(self, "Error", "Incorrect security answer.")
            return

        self.db.update_password(username, newpwd)
        QMessageBox.information(self, "Success", "Password updated!")

        # Back to login with username prefilled
        # self.show_login_page()
        self.username.setText(username)
        self.password.setText("")
