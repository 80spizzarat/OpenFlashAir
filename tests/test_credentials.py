import os
import unittest

from openflashair.credentials import protect_secret, unprotect_secret


class CredentialTests(unittest.TestCase):
    def test_windows_profile_secret_is_user_protected_or_unavailable(self):
        token=protect_secret('synthetic-profile-secret')
        if os.name == 'nt':
            self.assertIsNotNone(token)
            self.assertNotIn('synthetic-profile-secret',token)
            self.assertEqual(unprotect_secret(token),'synthetic-profile-secret')
        else:
            self.assertIsNone(token)

    def test_invalid_tokens_are_not_treated_as_passwords(self):
        self.assertIsNone(unprotect_secret('not-a-dpapi-token'))


if __name__ == '__main__': unittest.main()
