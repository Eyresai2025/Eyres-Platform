"""EYRES AI Inspection Platform - PyQt6 application entry point.

Phase 2 migration:
- PyQt6 Login (local password + Google OAuth)
- PyQt6 responsive Main Shell / sidebar / header
- PyQt6 Dashboard with live backend counts and system readiness
- PyQt6 Machines page with existing MachineDB and PLC connectivity backend
- PyQt6 Projects page with existing ProjectDB/MachineDB backend
- PyQt6 Image Capturing page with multi-brand camera adapter backend
- Click-only sidebar collapse/expand with Qt6 property animations

Important migration rule:
PyQt5 feature pages are not imported into this process. Each remaining page is
ported to PyQt6 one-by-one and then replaces its temporary placeholder.
"""
from __future__ import annotations

import os
import sys

# Keep the proven Torch-before-Qt startup ordering on Windows.
_TORCH_PRELOAD_ERROR = None
if os.name == "nt":
    try:
        import torch as _torch  # noqa: F401
    except Exception as exc:  # dashboard will simply report CPU/not-loaded state
        _TORCH_PRELOAD_ERROR = str(exc)

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase, QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from app_core.audit import record_audit_event
from app_core.error_boundary import install_exception_hook
from app_core.logging_config import configure_logging
from pages.auth.login_qt6 import LoginWindow
from ui.qt6.assets import asset_path
from ui.qt6.shell import MainShellWindow


APP_BUILD = "2026.09.28-qt6-application-diagnostics-01"

_HIDDEN_CONSOLE_HWND = None


def _hide_windows_console():
    """Hide the Python console while the Qt GUI is running.

    Set EYRES_SHOW_CONSOLE=1 when a visible console is wanted for debugging.
    """
    global _HIDDEN_CONSOLE_HWND
    if os.name != "nt" or os.environ.get("EYRES_SHOW_CONSOLE", "").strip() == "1":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
            _HIDDEN_CONSOLE_HWND = hwnd
    except Exception:
        _HIDDEN_CONSOLE_HWND = None


def _restore_windows_console():
    """Restore a console hidden by _hide_windows_console()."""
    global _HIDDEN_CONSOLE_HWND
    if os.name != "nt" or not _HIDDEN_CONSOLE_HWND:
        return
    try:
        import ctypes
        ctypes.windll.user32.ShowWindow(_HIDDEN_CONSOLE_HWND, 5)  # SW_SHOW
    except Exception:
        pass
    finally:
        _HIDDEN_CONSOLE_HWND = None


class ApplicationController(QtCore.QObject):
    """Owns the login -> shell -> logout lifecycle."""

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.login_window: LoginWindow | None = None
        self.main_window: MainShellWindow | None = None

    def start(self):
        self.show_login()

    def show_login(self):
        self.login_window = LoginWindow(on_login_success=self.on_login_success)
        self.login_window.show()
        self.login_window.raise_()
        self.login_window.activateWindow()

    def on_login_success(self, user: dict):
        username = str((user or {}).get("username") or "unknown")
        try:
            record_audit_event(
                "login",
                actor=username,
                details={"ui_runtime": "PyQt6", "build": APP_BUILD},
            )
        except Exception:
            pass

        self.main_window = MainShellWindow(user=user, on_logout=self.on_logout)
        self.app.main_window = self.main_window  # strong reference for long sessions
        self.main_window.showMaximized()
        self.main_window.raise_()
        self.main_window.activateWindow()

        if self.login_window is not None:
            self.login_window.hide()
            self.login_window.deleteLater()
            self.login_window = None

    def on_logout(self):
        self.app.main_window = None
        self.main_window = None
        QtCore.QTimer.singleShot(0, self.show_login)


def _install_application_font(app: QApplication):
    families = set(QFontDatabase.families())
    for family in ("Segoe UI Variable Text", "Segoe UI", "Inter"):
        if family in families:
            app.setFont(QFont(family, 10))
            return
    app.setFont(QFont("Arial", 10))


def _install_light_palette(app: QApplication):
    """Keep popups/menus light even when Windows is using a dark app theme."""
    palette = app.palette()
    roles = QtGui.QPalette.ColorRole
    palette.setColor(roles.Window, QtGui.QColor("#EEF3F9"))
    palette.setColor(roles.WindowText, QtGui.QColor("#101A2D"))
    palette.setColor(roles.Base, QtGui.QColor("#FFFFFF"))
    palette.setColor(roles.AlternateBase, QtGui.QColor("#F7F9FC"))
    palette.setColor(roles.ToolTipBase, QtGui.QColor("#172033"))
    palette.setColor(roles.ToolTipText, QtGui.QColor("#FFFFFF"))
    palette.setColor(roles.Text, QtGui.QColor("#213047"))
    palette.setColor(roles.Button, QtGui.QColor("#FFFFFF"))
    palette.setColor(roles.ButtonText, QtGui.QColor("#213047"))
    palette.setColor(roles.Highlight, QtGui.QColor("#EAF1FF"))
    palette.setColor(roles.HighlightedText, QtGui.QColor("#1D59CF"))
    if hasattr(roles, "PlaceholderText"):
        palette.setColor(roles.PlaceholderText, QtGui.QColor("#78879B"))
    app.setPalette(palette)

    # QComboBox popup views are native top-level views on Windows.  Styling
    # them at QApplication level prevents a Windows dark-theme popup from
    # appearing black inside the otherwise light EYRES UI.
    app.setStyleSheet("""
    QComboBox QAbstractItemView {
        background-color:#FFFFFF;
        color:#213047;
        border:1px solid #BFCDE0;
        selection-background-color:#EAF1FF;
        selection-color:#1D59CF;
        outline:0;
        padding:3px;
    }
    QComboBox QAbstractItemView::item {
        min-height:28px;
        padding:4px 8px;
        background:#FFFFFF;
        color:#213047;
    }
    QComboBox QAbstractItemView::item:selected {
        background:#EAF1FF;
        color:#1D59CF;
    }
    QComboBox QAbstractItemView::item:hover {
        background:#F2F6FF;
        color:#1D59CF;
    }
    """)


def _show_fatal_error(message: str):
    app = QApplication.instance()
    if app is None:
        return
    QMessageBox.critical(None, "EYRES AI Inspection Platform", message)


def main() -> int:
    configure_logging()
    install_exception_hook(show_error=_show_fatal_error)

    # Use logical-pixel scaling consistently on 100/125/150/200% Windows DPI.
    QtGui.QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)

    # Production desktop behaviour: hide the black Python/console window.
    # To keep it visible for debugging:
    #     set EYRES_SHOW_CONSOLE=1
    #     python Main_GUI.py
    _hide_windows_console()
    app.aboutToQuit.connect(_restore_windows_console)

    app.setApplicationName("EYRES AI Inspection Platform")
    app.setOrganizationName("EYRES AI")
    app.setStyle("Fusion")
    _install_application_font(app)
    _install_light_palette(app)

    icon_path = asset_path("app.ico")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    print(f"[EYRES Qt6] build: {APP_BUILD}")
    if _TORCH_PRELOAD_ERROR:
        print(f"[EYRES Qt6] Torch preload warning: {_TORCH_PRELOAD_ERROR}")

    controller = ApplicationController(app)
    app.controller = controller  # keep controller alive for the full process
    controller.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
