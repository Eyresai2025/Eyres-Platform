from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "augmentation" / "page_qt6.py"


def test_qt6_augmentation_page_exists_and_parses():
    assert PAGE.is_file()
    ast.parse(PAGE.read_text(encoding="utf-8"))


def test_no_pyqt5_import_in_new_page():
    source = PAGE.read_text(encoding="utf-8")
    assert "from PyQt5" not in source
    assert "import PyQt5" not in source


def test_final_workflow_markers():
    source = PAGE.read_text(encoding="utf-8")
    for marker in (
        "Dataset Setup",
        "Settings",
        "Review & Run",
        "Preprocessing",
        "Gamma Correction",
        "Augmentation Preview",
        "CURRENT PROJECT",
        "INPUT DATASET",
        "OUTPUT DATASET",
    ):
        assert marker in source


def test_backend_workers_preserved():
    source = PAGE.read_text(encoding="utf-8")
    assert "class AugmentationWorker" in source
    assert "class GammaWorker" in source
    assert "class PreprocessingThread" in source
    assert "write_yolo_txt" in source
    assert "write_yaml" in source
    assert "process_folder_with_params" in source


def test_rail_uses_icons_not_step_numbers():
    source = PAGE.read_text(encoding="utf-8")
    for icon in ("dataset", "settings", "review", "preprocess", "gamma"):
        assert f'"{icon}"' in source
    assert 'f"{number}' not in source


def test_shell_registers_augmentation_page():
    shell = (ROOT / "ui" / "qt6" / "shell.py").read_text(encoding="utf-8")
    assert "AugmentationPageQt6" in shell
    assert '_add_page("augmentation"' in shell
