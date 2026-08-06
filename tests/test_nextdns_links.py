import unittest

from app.services.nextdns import build_install_url


class NextDnsLinkTests(unittest.TestCase):
    def test_build_install_url_uses_profile_link_by_default(self):
        profile_id = 'abc123'
        link = build_install_url(profile_id)
        self.assertIn('profile=abc123', link)

    def test_build_install_url_supports_custom_domain(self):
        profile_id = 'abc123'
        link = build_install_url(profile_id, 'https://tinyurl.com/45z362ae?profile={profile_id}')
        self.assertTrue(link.startswith('https://tinyurl.com/45z362ae'))
        self.assertIn('profile=abc123', link)

    def test_build_install_url_returns_direct_external_link(self):
        profile_id = 'abc123'
        link = build_install_url(profile_id, 'https://tinyurl.com/45z362ae')
        self.assertEqual(link, 'https://tinyurl.com/45z362ae')


if __name__ == '__main__':
    unittest.main()