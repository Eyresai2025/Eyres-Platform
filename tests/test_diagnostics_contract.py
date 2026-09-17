import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app_core.diagnostics import diagnostic_log_paths, redact, tail_lines
from app_core.rbac import ADMIN, ROLES, can_access_index


class DiagnosticsTests(unittest.TestCase):
    def test_only_admin_can_open_diagnostics(self):
        for role in ROLES:
            self.assertEqual(can_access_index(role, 11), role == ADMIN)

    def test_redacts_secrets_and_uri_credentials(self):
        value = redact("password=hello token:abc mongodb://user:pass@localhost")
        self.assertNotIn("hello", value)
        self.assertNotIn("abc", value)
        self.assertNotIn("user:pass", value)

    def test_tail_is_bounded_and_redacted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "app.log"
            path.write_text("one\npassword=hidden\nthree\n", encoding="utf-8")
            result = tail_lines(path, 2)
            self.assertEqual(len(result), 2)
            self.assertNotIn("hidden", " ".join(result))

    def test_clear_targets_never_include_security_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            class Config:
                log_dir = Path(folder)
            with patch("app_core.diagnostics.get_config", return_value=Config()):
                self.assertTrue(all("audit" not in p.name for p in diagnostic_log_paths()))


if __name__ == "__main__":
    unittest.main()
