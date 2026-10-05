"""Behavioral checks for password-protected static publication."""
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import tracker

PASSWORD = 'test-password-only-1234'
SALT = b'0123456789abcdef'


def decrypt(envelope, password=PASSWORD):
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), base64.b64decode(envelope['salt']),
                              envelope['iterations'], dklen=32)
    plain = AESGCM(key).decrypt(base64.b64decode(envelope['nonce']),
                                base64.b64decode(envelope['ciphertext']), b'citation-v1')
    return json.loads(plain)


class EncryptionTests(unittest.TestCase):
    def test_wrong_password_and_tampering_are_rejected(self):
        envelope = tracker.encrypt_payload({'private': 'citation'}, PASSWORD, SALT)
        self.assertEqual(decrypt(envelope), {'private': 'citation'})
        with self.assertRaises(InvalidTag):
            decrypt(envelope, 'wrong password')
        value = bytearray(base64.b64decode(envelope['ciphertext']))
        value[0] ^= 1
        envelope['ciphertext'] = base64.b64encode(value).decode()
        with self.assertRaises(InvalidTag):
            decrypt(envelope)

    def test_daily_builds_use_fresh_nonce_with_same_login_key(self):
        first = tracker.encrypt_payload({'day': 1}, PASSWORD, SALT)
        second = tracker.encrypt_payload({'day': 2}, PASSWORD, SALT)
        self.assertEqual(first['salt'], second['salt'])
        self.assertNotEqual(first['nonce'], second['nonce'])
        self.assertEqual(decrypt(second), {'day': 2})

    def test_password_rotation_invalidates_saved_key(self):
        changed = tracker.encrypt_payload({'day': 2}, 'new-test-password-1234', SALT)
        with self.assertRaises(InvalidTag):
            decrypt(changed)

    def test_missing_password_never_builds_public_data(self):
        with tempfile.TemporaryDirectory() as out, patch.dict(os.environ, {'DASHBOARD_PASSWORD': ''}):
            cfg = tracker.Config()
            with self.assertRaises(tracker.TrackerError):
                tracker.build_site(cfg, tracker.blank_state(cfg), Path(out))
            self.assertEqual(list(Path(out).iterdir()), [])

    def test_legacy_state_migrates_and_password_can_be_rotated(self):
        with tempfile.TemporaryDirectory() as out, patch.dict(os.environ, {'DATA_DIR': out, 'DASHBOARD_PASSWORD': PASSWORD}):
            cfg = tracker.Config()
            state = tracker.blank_state(cfg)
            legacy = Path(out) / 'state.json'
            legacy.write_text(json.dumps(state))
            store = tracker.Store(cfg)
            self.assertEqual(store.load(), state)
            store.save(state)
            self.assertFalse(legacy.exists())
            encrypted = store.local_file.read_text()
            self.assertNotIn('author_id', encrypted)
            with patch.dict(os.environ, {'DASHBOARD_PASSWORD': 'new-test-password-1234', 'PREVIOUS_DASHBOARD_PASSWORD': PASSWORD}):
                self.assertEqual(store.load(), state)
                store.save(state)
                envelope = json.loads(store.local_file.read_text())
                self.assertEqual(decrypt(envelope, 'new-test-password-1234'), state)
                with self.assertRaises(InvalidTag):
                    decrypt(envelope)
