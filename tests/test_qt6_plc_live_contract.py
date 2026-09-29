from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "plc" / "page_qt6.py"
BACKEND = ROOT / "pages" / "plc" / "backend.py"


def test_files_parse():
    ast.parse(PAGE.read_text(encoding="utf-8"))
    ast.parse(BACKEND.read_text(encoding="utf-8"))


def test_no_pyqt5_in_new_plc_files():
    combined = PAGE.read_text(encoding="utf-8") + BACKEND.read_text(encoding="utf-8")
    assert "from PyQt5" not in combined
    assert "import PyQt5" not in combined


def test_approved_workflow_exists():
    source = PAGE.read_text(encoding="utf-8")
    for marker in (
        "Connect PLC",
        "Select Tags",
        "Storage & Collection",
        "Live Monitor",
        "System Log",
        "Get All Tags",
        "Add 300+ Specific Tags · Auto-map",
        "Start Continuous Reading",
        "Real-time PLC Data",
    ):
        assert marker in source


def test_existing_plc_backend_features_preserved():
    source = BACKEND.read_text(encoding="utf-8")
    for marker in (
        "class PLCWorker",
        "from pylogix import PLC",
        "GetPLCTime",
        "GetTagList",
        "self.plc.Read",
        "simulation",
        "class DataStorage",
        "class TagMapper",
        "SPECIFIC_TAGS",
    ):
        assert marker in source


def test_large_predefined_tag_list_retained():
    tree = ast.parse(BACKEND.read_text(encoding="utf-8"))
    value = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SPECIFIC_TAGS":
                    value = ast.literal_eval(node.value)
                    break
    assert value is not None
    assert len(value) >= 300


def test_shell_registers_real_plc_page():
    source = (ROOT / "ui" / "qt6" / "shell.py").read_text(encoding="utf-8")
    assert "PLCPageQt6" in source
    assert '_add_page("plc"' in source
    assert '"PLC READY"' in source


def test_local_plc_icons_exist():
    root = ROOT / "ui" / "assets" / "plc_icons"
    for name in (
        "connect.svg",
        "tags.svg",
        "storage.svg",
        "monitor.svg",
        "log.svg",
        "search.svg",
        "csv.svg",
        "read.svg",
        "play.svg",
        "stop.svg",
        "save.svg",
    ):
        assert (root / name).is_file()
