from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "annotation" / "page_qt6.py"


def test_annotation_qt6_page_exists():
    assert PAGE.is_file()
    ast.parse(PAGE.read_text(encoding="utf-8"))


def test_no_pyqt5_in_annotation_qt6_page():
    source = PAGE.read_text(encoding="utf-8")
    assert "from PyQt5" not in source
    assert "import PyQt5" not in source


def test_final_ui_markers_present():
    source = PAGE.read_text(encoding="utf-8")
    for marker in (
        "Annotation Inspector",
        "CURRENT PROJECT",
        "SOURCE DATASET",
        "Rectangle",
        "Polygon",
        "Final Save & Verify",
        "Overwrite Existing Files",
        "ThumbnailList",
    ):
        assert marker in source


def test_preserved_annotation_export_formats():
    source = PAGE.read_text(encoding="utf-8")
    assert "LabelMe" in source
    assert "Pascal VOC" in source
    assert "save_annotations_as_json" in source
    assert "save_annotations_as_xml" in source


def test_shell_registers_annotation_page():
    shell = (ROOT / "ui" / "qt6" / "shell.py").read_text(encoding="utf-8")
    assert "AnnotationPageQt6" in shell
    assert '_add_page("annotation"' in shell
