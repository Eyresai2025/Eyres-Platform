"""Standalone Phase-1 runner for the migrated PyQt6 login.

Important:
The current Main_GUI.py is still PyQt5. Do not import it in this process.
Once the main shell is migrated to PyQt6, this LoginWindow will be wired to
the normal after_login() handoff.
"""
import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from pages.auth.login_qt6 import LoginWindow, LOGIN_UI_BUILD


def on_login_success(user):
    # Phase-1 validation handoff only.
    # Main shell integration is intentionally deferred until Main_GUI is Qt6.
    username = str(user.get("username", "user"))
    QMessageBox.information(
        None,
        "Qt6 login validated",
        f"Authentication succeeded for {username}.\n\n"
        "Next migration step: Qt6 Main Shell + Dashboard.",
    )


def main():
    print(f"[EYRES Qt6 Login] build: {LOGIN_UI_BUILD}")
    app = QApplication(sys.argv)
    app.setApplicationName("EYRES AI Inspection Platform")
    app.setOrganizationName("EYRES AI")
    app.setStyle("Fusion")

    window = LoginWindow(on_login_success=on_login_success)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
