import unittest

from app_core.rbac import (
    ADMIN, AI_ENGINEER, MAINTENANCE, OPERATOR, QUALITY_ENGINEER,
    SessionUser, can_access, can_access_index, normalize_role,
)


class RBACTests(unittest.TestCase):
    def test_admin_has_every_page(self):
        self.assertTrue(all(can_access_index(ADMIN, i) for i in range(9)))

    def test_operator_cannot_open_training_or_configuration(self):
        self.assertFalse(can_access(OPERATOR, "training"))
        self.assertFalse(can_access(OPERATOR, "machines"))
        self.assertTrue(can_access(OPERATOR, "live"))

    def test_engineering_boundaries(self):
        self.assertTrue(can_access(AI_ENGINEER, "training"))
        self.assertFalse(can_access(AI_ENGINEER, "plc"))
        self.assertTrue(can_access(MAINTENANCE, "plc"))
        self.assertTrue(can_access(QUALITY_ENGINEER, "roi"))

    def test_unknown_role_fails_closed_to_operator(self):
        self.assertEqual(normalize_role("unexpected"), OPERATOR)
        self.assertFalse(can_access("unexpected", "training"))

    def test_legacy_user_defaults_safely(self):
        user = SessionUser.from_record({"username": "legacy"})
        self.assertEqual(user.role, OPERATOR)
        self.assertTrue(user.active)


if __name__ == "__main__":
    unittest.main()
