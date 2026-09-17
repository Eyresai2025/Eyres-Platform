import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AugmentationUiContractTests(unittest.TestCase):
    """Source-level contract for the approved EYRES augmentation redesign."""

    def setUp(self):
        self.source = (ROOT / "augmentation_tool.py").read_text(encoding="utf-8")
        self.theme = (ROOT / "ui" / "theme" / "augmentation.py").read_text(encoding="utf-8")
        self.main_gui = (ROOT / "Main_GUI.py").read_text(encoding="utf-8")

    def test_all_approved_pages_exist(self):
        for name in (
            "ProfessionalDatasetPage",
            "ProfessionalAugmentationPage",
            "ProfessionalProgressPage",
            "ProfessionalPreprocessingPanel",
            "ProfessionalGammaPanel",
        ):
            self.assertIn(f"class {name}", self.source)

        for title in (
            "Dataset Setup",
            "Augmentation Settings",
            "Review & Run",
            "Image Preprocessing",
            "Gamma Correction",
        ):
            self.assertIn(title, self.source)

    def test_approved_workspace_and_left_navigation_are_present(self):
        self.assertIn('rail.setObjectName("workflowRail")', self.source)
        self.assertIn('shell.setObjectName("workspaceCard")', self.source)
        self.assertIn('QLabel("AUGMENTATION STEPS")', self.source)
        self.assertIn('QLabel("IMAGE PROCESSING")', self.source)
        self.assertIn('ProfessionalPreprocessingPanel(embedded=True)', self.source)
        self.assertIn('ProfessionalGammaPanel()', self.source)

    def test_dataset_setup_contract_is_preserved(self):
        for attr in (
            "input_dir_edit",
            "output_dir_edit",
            "train_ratio_spin",
            "seed_spin",
            "quality_spin",
            "float_precision_combo",
        ):
            self.assertIn(f"self.{attr}", self.source)

        for key in (
            "'input_dir'",
            "'output_dir'",
            "'train_ratio'",
            "'seed'",
            "'jpeg_quality'",
            "'float_precision'",
        ):
            self.assertIn(key, self.source)

        self.assertIn('setObjectName("readinessStrip")', self.source)

    def test_augmentation_setting_contract_is_preserved(self):
        self.assertIn("class ToggleSwitch", self.source)
        self.assertIn("QSlider", self.source)
        self.assertIn("Transformation Summary", self.source)
        for attr in (
            "flip_horizontal_cb",
            "flip_vertical_cb",
            "brightness_cb",
            "brightness_spin",
            "saturation_cb",
            "saturation_spin",
        ):
            self.assertIn(f"self.{attr}", self.source)
        for key in (
            "'flip_horizontal'",
            "'flip_vertical'",
            "'brightness_pct'",
            "'saturation_pct'",
        ):
            self.assertIn(key, self.source)

    def test_review_and_processing_pages_use_dark_activity_logs(self):
        self.assertIn('setObjectName("processingLog")', self.source)
        self.assertIn("Start Augmentation", self.source)
        self.assertIn("Process Images", self.source)
        self.assertIn("Run Gamma Correction", self.source)
        self.assertIn("Preview Area", self.source)

    def test_processing_back_navigation_is_connected(self):
        self.assertIn(
            "self.preprocessing_page.back_requested.connect(self.previous_page)",
            self.source,
        )
        self.assertIn(
            "self.gamma_page.back_requested.connect(self.previous_page)",
            self.source,
        )

    def test_existing_workers_and_processing_backend_remain_used(self):
        self.assertIn("class AugmentationWorker(QThread)", self.source)
        self.assertIn("class GammaWorker(QThread)", self.source)
        self.assertIn("process_folder_with_params", self.source)
        self.assertIn("self.worker=AugmentationWorker(self.config)", self.source.replace(" ", ""))

    def test_embedded_theme_restore_contract(self):
        self.assertIn("def _force_local_augmentation_theme(self):", self.source)
        self.assertIn("QEvent.ParentChange", self.source)
        self.assertIn("QEvent.Show", self.source)
        self.assertIn("_force_local_augmentation_theme", self.main_gui)
        self.assertIn("elif index == 5:", self.main_gui)
        self.assertNotIn("if index in (4, 5, 7):", self.main_gui)

    def test_approved_light_theme_contract(self):
        for token in ("#F6F9FD", "#255CED", "#DBE3F0", "#07101E"):
            self.assertIn(token, self.theme)
        for selector in (
            "QFrame#workspaceCard",
            "QFrame#transformCard",
            "QTextEdit#processingLog",
            "QSlider::handle:horizontal",
        ):
            self.assertIn(selector, self.theme)
        self.assertNotIn("background-color: #1e1e1e", self.theme.lower())


if __name__ == "__main__":
    unittest.main()
