import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class AnnotationUiContractTests(unittest.TestCase):
    def test_annotation_theme_is_isolated(self):
        page = (ROOT / "annotation_tool.py").read_text(encoding="utf-8")
        theme = (ROOT / "ui" / "theme" / "annotation.py").read_text(encoding="utf-8")
        self.assertIn("apply_annotation_theme", page)
        self.assertNotIn("def apply_dark_theme", page)
        self.assertIn("ANNOTATION_QSS", theme)

    def test_sidebar_is_replaced_by_two_row_command_bar(self):
        page = (ROOT / "annotation_tool.py").read_text(encoding="utf-8")
        self.assertIn("QtWidgets.QVBoxLayout(self)", page)
        self.assertIn('setObjectName("annotationCommandBar")', page)
        self.assertIn("command_bar.setFixedHeight(116)", page)
        self.assertIn("primary_row", page)
        self.assertIn("secondary_row", page)

    def test_active_layout_has_no_group_boxes_or_toolbar_scroll(self):
        page = (ROOT / "annotation_tool.py").read_text(encoding="utf-8")
        active = page.split("    def init_ui(self):", 1)[1].split("    def ask_save_format", 1)[0]
        self.assertNotIn("QGroupBox", active)
        self.assertNotIn("QScrollArea", active)

    def test_dialogs_are_light(self):
        theme = (ROOT / "ui" / "theme" / "annotation.py").read_text(encoding="utf-8")
        self.assertIn("DIALOG_QSS", theme)
        self.assertNotIn("#2D2D3C", theme)

    def test_thumbnails_use_one_row(self):
        page = (ROOT / "annotation_tool.py").read_text(encoding="utf-8")
        self.assertIn("self.setWrapping(False)", page)
        self.assertIn('setObjectName("annotationThumbnails")', page)

    def test_final_annotation_polish(self):
        page = (ROOT / "annotation_tool.py").read_text(encoding="utf-8")
        self.assertIn('"Final Save && Verify"', page)
        self.assertIn("current_file_label", page)
        self.assertIn('setObjectName("activeTool")', page)
        self.assertIn("self.undo_btn", page)
        self.assertIn("self.redo_btn", page)
        self.assertIn("_refresh_action_states", page)
        self.assertIn("Clear Current Image", page)
        self.assertIn("Confirm Overwrite", page)
        self.assertIn('status += "  •  Auto-saved"', page)
        self.assertNotIn("self.toast(f\"Overwrote {saved_count} {fmt}", page)

    def test_save_notifications_fade(self):
        toast_source = (ROOT / "toasts.py").read_text(encoding="utf-8")
        self.assertIn("_fade.setEndValue(0.0)", toast_source)
        self.assertIn("singleShot=True", toast_source)

if __name__ == "__main__":
    unittest.main()
