from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "live" / "page_qt6.py"


def test_live_page_exists_and_parses():
    assert PAGE.is_file()
    ast.parse(PAGE.read_text(encoding="utf-8"))


def test_no_pyqt5_import():
    tree = ast.parse(PAGE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("PyQt5") for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("PyQt5")


def test_hardware_sdk_is_lazy_imported():
    source = PAGE.read_text(encoding="utf-8")
    assert "def _load_hik_capture" in source
    assert "\nimport hik_capture\n" not in source


def test_approved_live_ui_sections_exist():
    source = PAGE.read_text(encoding="utf-8")
    for marker in (
        "Live Inspection",
        "Inspection History",
        "Anomaly Detection",
        "Configure Session",
        "Folder Mode",
        "Start Live",
        "Inspection Summary",
        "Camera Inspection View",
        "Rejection Bypass",
    ):
        assert marker in source


def test_live_backend_capabilities_preserved():
    source = PAGE.read_text(encoding="utf-8")
    for marker in (
        "class CaptureWorker",
        "capture_multi",
        "grab_live_frame",
        "UnifiedYOLOInferencer",
        "detectron_predict_single",
        "insert_live_record",
        "get_today_live_counts",
        "get_recent_inspections",
        "run_good_bad_template_matching",
        "_prepare_run_dirs",
    ):
        assert marker in source


def test_controlled_dropdown_and_icons_exist():
    source = PAGE.read_text(encoding="utf-8")
    assert "class ControlledComboBox" in source
    assert "QListView#LiveComboView" in source
    icon_root = ROOT / "ui" / "assets" / "live_icons"
    for name in (
        "live.svg",
        "history.svg",
        "anomaly.svg",
        "config.svg",
        "folder.svg",
        "play.svg",
        "stop.svg",
        "camera.svg",
        "template.svg",
    ):
        assert (icon_root / name).is_file()


def test_shell_registers_live_page():
    shell = (ROOT / "ui" / "qt6" / "shell.py").read_text(encoding="utf-8")
    assert "LivePageQt6" in shell
    assert '_add_page("live"' in shell
    assert '"LIVE READY"' in shell
    assert '"Live Inspection" if key == "live"' in shell
