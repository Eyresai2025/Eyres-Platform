from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "training" / "page_qt6.py"


def test_training_page_exists_and_parses():
    assert PAGE.is_file()
    ast.parse(PAGE.read_text(encoding="utf-8"))


def test_no_pyqt5_in_training_page():
    source = PAGE.read_text(encoding="utf-8")
    assert "from PyQt5" not in source
    assert "import PyQt5" not in source


def test_approved_workflow_is_present():
    source = PAGE.read_text(encoding="utf-8")
    for marker in (
        "Model Type",
        "Dataset",
        "Model Weights",
        "Hyperparameters",
        "Review & Run",
        "Run Dashboard",
        "YOLO Segmentation",
        "YOLO Detection",
        "Detectron Segmentation",
        "Detectron Detection",
    ):
        assert marker in source


def test_backend_command_generation_preserved():
    source = PAGE.read_text(encoding="utf-8")
    assert "def build_commands" in source
    assert "def _fix_and_stage_data_yaml" in source
    assert "ultralytics" in source
    assert "DefaultTrainer" in source
    assert "faster_rcnn_R_50_FPN_3x.yaml" in source
    assert "mask_rcnn_R_50_FPN_3x.yaml" in source


def test_controlled_dropdown_is_used():
    source = PAGE.read_text(encoding="utf-8")
    assert "class ControlledComboBox" in source
    assert "QListView#ControlledComboView" in source
    assert "self.ver_combo = ControlledComboBox()" in source
    assert "self.device_combo = ControlledComboBox()" in source


def test_shell_registers_real_training_page():
    shell = (ROOT / "ui" / "qt6" / "shell.py").read_text(encoding="utf-8")
    assert "TrainingPageQt6" in shell
    assert '_add_page("training"' in shell
    assert '"TRAINING READY"' in shell


def test_training_icons_exist():
    icon_dir = ROOT / "ui" / "assets" / "training_icons"
    for name in (
        "model.svg",
        "dataset.svg",
        "weights.svg",
        "hparams.svg",
        "review.svg",
        "dashboard.svg",
        "yolo.svg",
        "detectron.svg",
    ):
        assert (icon_dir / name).is_file()
