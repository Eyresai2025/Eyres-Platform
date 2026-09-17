import unittest

from app_core.rbac import ADMIN, ROLES, can_access_index


class UserManagementAccessTests(unittest.TestCase):
    def test_only_administrator_can_open_user_management(self):
        for role in ROLES:
            self.assertEqual(can_access_index(role, 9), role == ADMIN)

    def test_unknown_role_is_denied(self):
        self.assertFalse(can_access_index("unknown", 9))


if __name__ == "__main__":
    unittest.main()
