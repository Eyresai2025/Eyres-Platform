import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from app_core.audit import record_audit_event, verify_audit_integrity

class AuditIntegrityTests(unittest.TestCase):
    def test_valid_chain_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); config = type("Config", (), {"data_dir": root})()
            with patch("app_core.audit.get_config", return_value=config):
                record_audit_event("login", actor="operator1")
                record_audit_event("navigation", actor="operator1")
                ok, _, count = verify_audit_integrity()
                self.assertTrue(ok); self.assertEqual(count, 2)
                path = root / "security" / "audit.jsonl"
                rows = path.read_text(encoding="utf-8").splitlines()
                item = json.loads(rows[0]); item["actor"] = "changed"
                rows[0] = json.dumps(item, sort_keys=True)
                path.chmod(0o600); path.write_text("\n".join(rows) + "\n", encoding="utf-8")
                ok, message, _ = verify_audit_integrity()
                self.assertFalse(ok); self.assertIn("Modified record", message)

    def test_secrets_are_never_written(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); config = type("Config", (), {"data_dir": root})()
            with patch("app_core.audit.get_config", return_value=config):
                path = record_audit_event("test", details={"password": "no", "safe": "yes"})
                text = path.read_text(encoding="utf-8")
                self.assertNotIn('"password"', text); self.assertNotIn('"no"', text)

if __name__ == "__main__": unittest.main()
