from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "maintenance" / "page_qt6.py"
SHELL = ROOT / "ui" / "qt6" / "shell.py"


def test_maintenance_page_parses():
    ast.parse(PAGE.read_text(encoding="utf-8"))


def test_maintenance_page_is_pyqt6_only():
    source = PAGE.read_text(encoding="utf-8")
    assert "from PyQt6" in source
    assert "from PyQt5" not in source


def test_existing_maintenance_backend_contract_is_preserved():
    source = PAGE.read_text(encoding="utf-8")
    for marker in (
        "mongo.require_available()",
        "verify_audit_integrity()",
        "build_sbom(requirements)",
        "create_backup(keep=10)",
        "inspect_backup(path)",
        "restore(path, apply=False)",
        "record_audit_event(",
    ):
        assert marker in source


def test_restore_remains_preview_only():
    source = PAGE.read_text(encoding="utf-8")
    assert "restore(path, apply=False)" in source
    assert "restore(path, apply=True)" not in source


def test_approved_maintenance_workspaces_exist():
    source = PAGE.read_text(encoding="utf-8")
    for marker in (
        "Overview",
        "Backup & Recovery",
        "Storage Cleanup",
        "Dependencies & SBOM",
        "Audit Integrity",
        "Run Maintenance Check",
        "Create Backup",
        "Preview Restore",
        "Generate SBOM",
        "Verify Audit Records",
    ):
        assert marker in source


def test_storage_cleanup_is_non_destructive():
    source = PAGE.read_text(encoding="utf-8")
    assert "No files are deleted automatically." in source
    assert "does not silently delete runtime data" in source
    assert ".unlink(" not in source
    assert "shutil.rmtree(" not in source


def test_shell_registers_real_maintenance_page():
    source = SHELL.read_text(encoding="utf-8")
    assert "SystemMaintenancePageQt6" in source
    assert '_add_page("maintenance"' in source
    assert '"MAINTENANCE READY"' in source


def test_local_maintenance_icons_exist():
    root = ROOT / "ui" / "assets" / "maintenance_icons"
    for name in (
        "overview.svg",
        "backup.svg",
        "storage.svg",
        "deps.svg",
        "audit.svg",
        "check.svg",
        "folder.svg",
        "shield.svg",
        "refresh.svg",
        "verify.svg",
        "preview.svg",
    ):
        assert (root / name).is_file()


def test_hover_icons_use_padded_canvas():
    source = PAGE.read_text(encoding="utf-8")
    assert "QtGui.QPixmap(36, 36)" in source
    assert "SmoothPixmapTransform" in source
