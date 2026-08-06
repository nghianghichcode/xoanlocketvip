import os
import tempfile
import unittest

from app import database as db
from app.services.nextdns import build_install_url


class UsageLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.original_db_name = db.DB_NAME
        db.DB_NAME = self.temp_db.name
        db.init_db()

    def tearDown(self):
        db.DB_NAME = self.original_db_name
        if os.path.exists(self.temp_db.name):
            os.remove(self.temp_db.name)

    def test_default_daily_limit_is_two(self):
        self.assertTrue(db.check_can_request(1001))

        db.increment_usage(1001)
        self.assertTrue(db.check_can_request(1001))

        db.increment_usage(1001)
        self.assertFalse(db.check_can_request(1001))

    def test_referral_bonus_adds_one_extra_daily_use(self):
        db.increment_usage(1001)
        db.increment_usage(1001)
        self.assertFalse(db.check_can_request(1001))

        db.grant_referral_bonus(1001)
        self.assertTrue(db.check_can_request(1001))

    def test_build_install_url_uses_configured_external_link(self):
        link = build_install_url('abc123', 'https://tinyurl.com/45z362ae')
        self.assertEqual(link, 'https://tinyurl.com/45z362ae')


if __name__ == '__main__':
    unittest.main()
