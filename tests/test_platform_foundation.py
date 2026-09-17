import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app_core.config import AppConfig, get_config


class ConfigTests(unittest.TestCase):
    def tearDown(self):
        get_config.cache_clear()

    def test_defaults_are_bounded(self):
        with patch.dict(os.environ, {}, clear=False):
            config = AppConfig.from_environment()
        self.assertGreater(config.service_timeout_ms, 0)
        self.assertLessEqual(config.service_timeout_ms, 10_000)
        self.assertGreater(config.navigation_debounce_ms, 0)

    def test_invalid_timeout_is_rejected(self):
        with patch.dict(os.environ, {"EYRES_SERVICE_TIMEOUT_MS": "never"}, clear=False):
            with self.assertRaisesRegex(ValueError, "must be an integer"):
                AppConfig.from_environment()


class PasswordContractTests(unittest.TestCase):
    """Load only the credential helpers without requiring a database server."""

    @classmethod
    def setUpClass(cls):
        try:
            from db import hash_secret, verify_secret
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest(f"optional database dependency missing: {exc}")
        cls.hash_secret = staticmethod(hash_secret)
        cls.verify_secret = staticmethod(verify_secret)

    def test_pbkdf2_hash_is_salted_and_verifiable(self):
        first = self.hash_secret("correct horse battery staple")
        second = self.hash_secret("correct horse battery staple")
        self.assertNotEqual(first, second)
        self.assertEqual(self.verify_secret("correct horse battery staple", first), (True, False))
        self.assertEqual(self.verify_secret("wrong", first), (False, False))

    def test_legacy_sha256_is_accepted_for_migration(self):
        legacy = hashlib.sha256(b"old-password").hexdigest()
        self.assertEqual(self.verify_secret("old-password", legacy), (True, True))


class AuditContractTests(unittest.TestCase):
    def tearDown(self):
        get_config.cache_clear()

    def test_audit_is_json_lines_and_redacts_secrets(self):
        from app_core.audit import record_audit_event

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"EYRES_DATA_DIR": directory}, clear=False
        ):
            get_config.cache_clear()
            path = record_audit_event(
                "test", actor="operator",
                details={"page": "Dashboard", "password": "do-not-store"},
            )
            event = json.loads(path.read_text(encoding="utf-8").strip())
        self.assertEqual(event["action"], "test")
        self.assertEqual(event["actor"], "operator")
        self.assertEqual(event["details"], {"page": "Dashboard"})


class PerformanceContractTests(unittest.TestCase):
    def tearDown(self):
        get_config.cache_clear()

    def test_timing_csv_is_created(self):
        from app_core.performance import record_page_timing

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"EYRES_DATA_DIR": directory}, clear=False
        ):
            get_config.cache_clear()
            path = record_page_timing("Dashboard", 12.25)
            contents = Path(path).read_text(encoding="utf-8")
        self.assertIn("timestamp_utc,page,elapsed_ms,status,slow_ui,details", contents)
        self.assertIn("Dashboard,12.25,success,no", contents)


class LifecycleContractTests(unittest.TestCase):
    def test_shutdown_continues_after_component_failure(self):
        from app_core.lifecycle import shutdown_components

        calls = []

        class Broken:
            def shutdown(self):
                calls.append("broken")
                raise RuntimeError("expected")

        class Healthy:
            def stop(self):
                calls.append("healthy")

        errors = shutdown_components([Broken(), Healthy()])
        self.assertEqual(calls, ["broken", "healthy"])
        self.assertEqual(len(errors), 1)
        self.assertIn("expected", errors[0])


if __name__ == "__main__":
    unittest.main()
