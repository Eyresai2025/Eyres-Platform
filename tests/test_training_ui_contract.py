import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TrainingUiContractTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "training_tool.py").read_text(encoding="utf-8")

    def test_professional_light_workspace(self):
        self.assertIn("background:#f5f7fb", self.source)
        self.assertIn('content.setObjectName("trainingWorkspace")', self.source)
        self.assertIn("content.setMaximumWidth(1120)", self.source)
        self.assertIn("self.nav = TrainingStageBar(self)", self.source)
        self.assertIn('button.setProperty("stageState", state)', self.source)
        self.assertIn("self.stack.setMaximumWidth(1056)", self.source)
        self.assertIn("background:#101827", self.source)

    def test_model_cards_are_compact_and_selectable(self):
        self.assertIn('grid_host.setMaximumWidth(952)', self.source)
        self.assertIn('background:#eef4ff; border:2px solid #2868e8', self.source)
        self.assertIn('self._model_group.setExclusive(True)', self.source)
        for label in ("YOLO Segmentation", "YOLO Detection", "Detectron Segmentation", "Detectron Detection"):
            self.assertIn(label, self.source)

    def test_completed_step_logic_is_correct(self):
        nav_method = self.source.split("def _update_nav(self):", 1)[1].split("def _restart_soft", 1)[0]
        self.assertIn("indicator.set_complete(idx < i)", nav_method)
        self.assertNotIn("indicator.set_complete(idx > i)", nav_method)
        self.assertIn("background:#f0fdf4", self.source)
        self.assertIn("border-left:3px solid #22c55e", self.source)

    def test_training_sections_remain_available(self):
        for label in ("Dataset", "Segmentation", "Detection", "Hyperparams", "Run"):
            self.assertIn(label, self.source)
        self.assertIn('QPushButton("Build Commands")', self.source)
        self.assertIn('QPushButton("Start Training")', self.source)

    def test_detectron_selection_does_not_reset_to_dataset(self):
        handler = self.source.split("def _on_model_card_selected", 1)[1].split("def current_step", 1)[0]
        self.assertIn("self.step_train.set_mode(mode)", handler)
        self.assertNotIn("self.step_train.nav.setCurrentIndex(0)", handler)
        self.assertIn('self.nav.set_steps([(1, "Configuration"), (4, "Review & run")])', self.source)


if __name__ == "__main__":
    unittest.main()
