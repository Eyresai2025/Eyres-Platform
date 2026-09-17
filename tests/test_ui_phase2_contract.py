import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UIPhase2ContractTests(unittest.TestCase):
    def test_legacy_pages_are_adapted_and_animated(self):
        launcher = (ROOT / "Main_GUI.py").read_text(encoding="utf-8")
        self.assertIn("adapt_legacy_page(current)", launcher)
        self.assertIn("fade_in(current)", launcher)

    def test_sidebar_brand_is_compact_and_bounded(self):
        launcher = (ROOT / "Main_GUI.py").read_text(encoding="utf-8")
        self.assertIn("logo_label.setFixedSize(42, 42)", launcher)
        self.assertIn("self.side.setMaximumWidth(248)", launcher)

    def test_maintenance_resolves_project_requirements(self):
        source = (ROOT / "pages" / "administration" / "maintenance.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("Path(__file__).resolve().parents[2]", source)
        self.assertIn('project_root / "requirements.txt"', source)


if __name__ == "__main__":
    unittest.main()
