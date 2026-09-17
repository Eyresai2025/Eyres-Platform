import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CaptureArchitectureTests(unittest.TestCase):
    def test_capture_layers_exist(self):
        self.assertTrue((ROOT / "pages" / "capture" / "page.py").is_file())
        self.assertTrue((ROOT / "services" / "capture" / "backend.py").is_file())
        self.assertTrue((ROOT / "ui" / "theme" / "capture.py").is_file())

    def test_launcher_uses_capture_package(self):
        source = (ROOT / "Main_GUI.py").read_text(encoding="utf-8")
        self.assertIn("from pages.capture import CameraWidget", source)

    def test_root_camera_module_is_compatibility_only(self):
        source = (ROOT / "camera_app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        self.assertEqual(classes, [])
        self.assertIn("from pages.capture.page import CameraWidget", source)

    def test_capture_page_does_not_define_workers(self):
        source = (ROOT / "pages" / "capture" / "page.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
        self.assertNotIn("CaptureWorker", names)
        self.assertNotIn("HikCaptureWorker", names)
        self.assertIn("CameraWidget", names)

    def test_capture_theme_is_light(self):
        source = (ROOT / "ui" / "theme" / "capture.py").read_text(encoding="utf-8")
        self.assertIn("#f5f7fb", source)
        self.assertIn("#fff", source)
        self.assertNotIn(
            "_apply_flat_black_qss",
            (ROOT / "pages" / "capture" / "page.py").read_text(encoding="utf-8"),
        )

    def test_simulation_is_isolated_from_hardware_path(self):
        backend = (ROOT / "services" / "capture" / "backend.py").read_text(encoding="utf-8")
        page = (ROOT / "pages" / "capture" / "page.py").read_text(encoding="utf-8")
        self.assertIn('EYRES_CAMERA_SIMULATION', backend)
        self.assertIn('SIM-LUCID-001', backend)
        self.assertIn('SIM-MVS-001', backend)
        self.assertIn('def simulation_frame', backend)
        self.assertIn('if CAMERA_SIMULATION:', page)
        self.assertIn('SIMULATION MODE', page)

    def test_capture_polish_contract(self):
        page = (ROOT / "pages" / "capture" / "page.py").read_text(encoding="utf-8")
        theme = (ROOT / "ui" / "theme" / "capture.py").read_text(encoding="utf-8")
        for marker in ("CAPTURE PLAN", "Open Folder", "Stop Capture", "_make_card_clickable", "Ready to save"):
            self.assertIn(marker, page)
        self.assertIn("QLabel#modeCheck", theme)
        self.assertIn("QPushButton#dangerButton", theme)

    def test_mode_exclusivity_and_click_to_toggle_camera(self):
        page = (ROOT / "pages" / "capture" / "page.py").read_text(encoding="utf-8")
        self.assertIn("QButtonGroup", page)
        self.assertIn("setExclusive(True)", page)
        self.assertIn("QAbstractItemView.MultiSelection", page)

    def test_final_camera_settings_and_preview_features(self):
        page = (ROOT / "pages" / "capture" / "page.py").read_text(encoding="utf-8")
        for marker in ("Apply Settings", "Reset to Defaults", "previewInfo", "FullImageDialog", "FPS"):
            self.assertIn(marker, page)


if __name__ == "__main__":
    unittest.main()
