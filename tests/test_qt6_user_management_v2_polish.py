from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "users" / "page_qt6.py"


def test_page_parses():
    ast.parse(PAGE.read_text(encoding="utf-8"))


def test_robust_chevron_combo_is_used():
    source = PAGE.read_text(encoding="utf-8")
    assert "class ChevronComboBox(QComboBox)" in source
    assert "chevron_down.svg" in source
    assert 'self.role = ChevronComboBox()' in source
    assert 'self.role_filter = ChevronComboBox(objectName="FilterCombo")' in source
    assert 'self.status_filter = ChevronComboBox(objectName="FilterCombo")' in source


def test_native_arrow_is_suppressed_to_avoid_double_arrow():
    source = PAGE.read_text(encoding="utf-8")
    assert "QComboBox::down-arrow" in source
    assert "image:none" in source


def test_readability_fonts_are_increased():
    source = PAGE.read_text(encoding="utf-8")
    assert "font-size:10.2px" in source
    assert "font-size:9.6px" in source


def test_chevron_asset_exists():
    assert (ROOT / "ui" / "assets" / "user_icons" / "chevron_down.svg").is_file()
