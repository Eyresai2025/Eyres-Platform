from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "users" / "page_qt6.py"


def test_page_parses():
    ast.parse(PAGE.read_text(encoding="utf-8"))


def test_chevron_combo_accepts_object_name_keyword():
    source = PAGE.read_text(encoding="utf-8")
    assert "def __init__(self, parent=None, objectName=None):" in source
    assert "self.setObjectName(str(objectName))" in source
    assert 'ChevronComboBox(objectName="FilterCombo")' in source


def test_previous_failing_calls_are_supported():
    source = PAGE.read_text(encoding="utf-8")
    assert 'self.role_filter = ChevronComboBox(objectName="FilterCombo")' in source
    assert 'self.status_filter = ChevronComboBox(objectName="FilterCombo")' in source
