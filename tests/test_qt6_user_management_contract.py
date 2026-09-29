from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "users" / "page_qt6.py"
SHELL = ROOT / "ui" / "qt6" / "shell.py"


def test_user_page_parses():
    ast.parse(PAGE.read_text(encoding="utf-8"))


def test_user_page_is_pyqt6_only():
    source = PAGE.read_text(encoding="utf-8")
    assert "from PyQt6" in source
    assert "from PyQt5" not in source


def test_existing_backend_contract_is_preserved():
    source = PAGE.read_text(encoding="utf-8")
    for call in (
        "self.database.list_users()",
        "self.database.create_managed_user(",
        "self.database.set_user_role(",
        "self.database.set_user_active(",
        "self.database.admin_reset_password(",
        "self.database.clear_user_lockout(",
        "record_audit_event(",
    ):
        assert call in source


def test_approved_user_management_ui_exists():
    source = PAGE.read_text(encoding="utf-8")
    for label in (
        "Create User",
        "Total Users",
        "Administrators",
        "Search users...",
        "All roles",
        "All status",
        "Change Role",
        "Reset Password",
        "Disable User",
        "Clear Lockout",
    ):
        assert label in source


def test_combo_popups_are_forced_white():
    source = PAGE.read_text(encoding="utf-8")
    assert "def _configure_combo_popup" in source
    assert "background:#FFFFFF" in source
    assert "selection-background-color:#E8F1FF" in source


def test_user_icons_are_padded_for_hover():
    source = PAGE.read_text(encoding="utf-8")
    assert "QtGui.QPixmap(34, 34)" in source
    assert "QtGui.QPixmap(36, 36)" in source
    assert "SmoothPixmapTransform" in source


def test_shell_registers_real_users_page():
    source = SHELL.read_text(encoding="utf-8")
    assert "UserManagementPageQt6" in source
    assert '_add_page("users"' in source
    assert '"ACCESS CONTROL READY"' in source


def test_local_icons_exist():
    root = ROOT / "ui" / "assets" / "user_icons"
    for name in (
        "users.svg",
        "active.svg",
        "locked.svg",
        "admin.svg",
        "plus.svg",
        "search.svg",
        "role.svg",
        "password.svg",
        "unlock.svg",
        "disable.svg",
        "enable.svg",
    ):
        assert (root / name).is_file()
