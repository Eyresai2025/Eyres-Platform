import unittest
from pathlib import Path


class UIArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]

    def test_new_page_packages_exist(self):
        expected = (
            "pages/auth/login.py", "pages/dashboard/page.py",
            "pages/machines/page.py", "pages/projects/page.py",
            "pages/administration/users.py", "pages/administration/maintenance.py",
            "pages/administration/diagnostics.py",
        )
        for relative in expected:
            self.assertTrue((self.root / relative).is_file(), relative)

    def test_theme_and_official_assets_exist(self):
        for relative in (
            "ui/theme/tokens.py", "ui/theme/stylesheet.py",
            "ui/theme/manager.py", "ui/assets/app.ico", "ui/assets/app.png",
        ):
            self.assertTrue((self.root / relative).is_file(), relative)

    def test_standard_launcher_uses_page_packages(self):
        source = (self.root / "Main_GUI.py").read_text(encoding="utf-8")
        self.assertIn("from pages.auth import LoginWindow", source)
        self.assertIn("from pages.dashboard import DashboardPage", source)


if __name__ == "__main__":
    unittest.main()
