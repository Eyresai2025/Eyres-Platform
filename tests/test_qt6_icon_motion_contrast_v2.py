from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]

FILES = [
    ROOT / "pages" / "plc" / "page_qt6.py",
    ROOT / "pages" / "training" / "page_qt6.py",
    ROOT / "pages" / "augmentation" / "page_qt6.py",
    ROOT / "pages" / "live" / "page_qt6.py",
]


def test_patched_files_parse():
    for path in FILES:
        ast.parse(path.read_text(encoding="utf-8"))


def test_plc_uses_padded_icon_canvas():
    source = FILES[0].read_text(encoding="utf-8")
    assert "canvas_size = 36" in source
    assert "setIcon(QtGui.QIcon(canvas))" in source
    assert "SmoothPixmapTransform" in source


def test_training_and_augmentation_use_padded_canvas():
    for path in FILES[1:3]:
        source = path.read_text(encoding="utf-8")
        assert "QtGui.QPixmap(36, 36)" in source
        assert "setIcon(QtGui.QIcon(canvas))" in source


def test_live_uses_padded_canvas():
    source = FILES[3].read_text(encoding="utf-8")
    assert "QtGui.QPixmap(34, 34)" in source
    assert "setIcon(QtGui.QIcon(canvas))" in source


def test_plc_contrast_is_stronger():
    source = FILES[0].read_text(encoding="utf-8")
    assert "background:#EAF1F8" in source
    assert "#AFC1D4" in source
    assert "#A9BED3" in source


def test_dashboard_sidebar_code_was_not_replaced():
    source = (ROOT / "ui" / "qt6" / "widgets.py").read_text(encoding="utf-8")
    assert "class NavButton" in source
    assert "canvas_size = 34" in source
