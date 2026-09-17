import os, unittest
from unittest.mock import patch
from app_core.config import AppConfig

class LoginSecurityTests(unittest.TestCase):
    def test_secure_defaults(self):
        c=AppConfig.from_environment()
        self.assertEqual(c.max_login_attempts,5)
        self.assertEqual(c.lockout_minutes,15)
        self.assertEqual(c.session_timeout_minutes,15)
    def test_values_are_configurable_and_positive(self):
        with patch.dict(os.environ,{"EYRES_MAX_LOGIN_ATTEMPTS":"3","EYRES_LOCKOUT_MINUTES":"10","EYRES_SESSION_TIMEOUT_MINUTES":"20"}):
            c=AppConfig.from_environment()
        self.assertEqual((c.max_login_attempts,c.lockout_minutes,c.session_timeout_minutes),(3,10,20))
        with patch.dict(os.environ,{"EYRES_MAX_LOGIN_ATTEMPTS":"0"}):
            with self.assertRaises(ValueError): AppConfig.from_environment()
if __name__=="__main__": unittest.main()
