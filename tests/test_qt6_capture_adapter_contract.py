import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_qt6_capture_page_and_adapters_exist():
    assert (ROOT / "pages" / "capture" / "page_qt6.py").is_file()
    assert (ROOT / "services" / "capture" / "adapters" / "base.py").is_file()
    assert (ROOT / "services" / "capture" / "adapters" / "registry.py").is_file()


def test_capture_package_is_qt6_safe():
    source = (ROOT / "pages" / "capture" / "__init__.py").read_text(encoding="utf-8")
    assert "page_qt6" in source
    assert "PyQt5" not in source

    service_init = (ROOT / "services" / "capture" / "__init__.py").read_text(encoding="utf-8")
    assert "from .backend import" not in service_init


def test_all_final_brand_adapters_are_registered():
    source = (ROOT / "services" / "capture" / "adapters" / "registry.py").read_text(encoding="utf-8")
    for key in ("lucid", "hikrobot", "basler", "flir", "teledyne_dalsa", "genicam"):
        assert key in source


def test_capture_ui_flow_markers():
    source = (ROOT / "pages" / "capture" / "page_qt6.py").read_text(encoding="utf-8")
    for marker in (
        "Capture Type", "Camera Brand", "Detect Devices", "Camera Settings",
        "Capture Plan", "Storage", "Capture", "Review", "Session Readiness",
    ):
        assert marker in source


def test_no_pyqt5_import_in_qt6_capture_tree():
    for path in [
        ROOT / "pages" / "capture" / "page_qt6.py",
        *list((ROOT / "services" / "capture" / "adapters").glob("*.py")),
    ]:
        source = path.read_text(encoding="utf-8")
        assert "PyQt5" not in source
        ast.parse(source)
