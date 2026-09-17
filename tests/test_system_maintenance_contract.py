import unittest
from app_core.rbac import ADMIN, ROLES, can_access_index


class SystemMaintenanceAccessTests(unittest.TestCase):
    def test_only_administrator_can_open_maintenance(self):
        for role in ROLES:
            self.assertEqual(can_access_index(role, 10), role == ADMIN)

    def test_unknown_role_is_denied(self):
        self.assertFalse(can_access_index("unknown", 10))


if __name__ == "__main__":
    unittest.main()
