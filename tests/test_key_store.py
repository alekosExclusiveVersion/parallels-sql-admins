"""
tests/test_key_store.py

Тесты vault-модуля: вывод ключа из мастер-пароля (PBKDF2), верификатор,
файловый ключ (создание, переиспользование, отказ от перегенерации).
"""

import tempfile
import unittest
from pathlib import Path

from common.key_store import (
    BACKEND_FILE_KEY,
    BACKEND_MASTER_PASSWORD,
    VaultError,
    create_master_meta,
    derive_key,
    load_or_create_file_key,
    vault,
    verify_master_password,
)


class TestKeyDerivation(unittest.TestCase):

    def test_derive_key_is_deterministic(self):
        salt = b"0123456789abcdef"
        a = derive_key("пароль", salt, 1000)
        b = derive_key("пароль", salt, 1000)
        c = derive_key("пароль", salt, 2000)
        d = derive_key("другой", salt, 1000)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertNotEqual(a, d)
        self.assertEqual(len(a), 44)  # urlsafe_b64encode(32 байта)

    def test_different_salts_give_different_keys(self):
        a = derive_key("pw", b"0" * 16, 1000)
        b = derive_key("pw", b"1" * 16, 1000)
        self.assertNotEqual(a, b)


class TestMasterVault(unittest.TestCase):

    def setUp(self):
        vault.lock()

    def test_create_and_verify(self):
        meta = create_master_meta("secret", 1000)
        self.assertEqual(meta["kind"], BACKEND_MASTER_PASSWORD)
        self.assertNotIn("secret", repr(meta))
        self.assertTrue(verify_master_password("secret", meta))
        self.assertFalse(verify_master_password("wrong", meta))

    def test_unlock_master_sets_key(self):
        meta = create_master_meta("secret", 1000)
        vault.unlock_master("secret", meta)
        self.assertTrue(vault.unlocked)
        self.assertEqual(vault.kind, BACKEND_MASTER_PASSWORD)
        token = vault.encrypt("hello")
        self.assertEqual(vault.decrypt(token), "hello")

    def test_wrong_password_keeps_locked(self):
        meta = create_master_meta("secret", 1000)
        with self.assertRaises(Exception):
            vault.unlock_master("wrong", meta)
        self.assertFalse(vault.unlocked)

    def test_lock_clears_key(self):
        meta = create_master_meta("secret", 1000)
        vault.unlock_master("secret", meta)
        vault.lock()
        self.assertFalse(vault.unlocked)
        with self.assertRaises(VaultError):
            vault.encrypt("hello")

    def test_meta_round_trip(self):
        meta = create_master_meta("secret", 1000)
        vault.unlock_master("secret", meta)
        saved = vault.meta
        self.assertEqual(saved, meta)


class TestFileKey(unittest.TestCase):

    def setUp(self):
        vault.lock()
        self._tmp = Path(tempfile.mkdtemp())

    def test_creates_key_file_with_0600(self):
        path = self._tmp / "servers.key"
        key = load_or_create_file_key(path)
        self.assertEqual(path.read_bytes(), key)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_reuses_existing_key(self):
        path = self._tmp / "servers.key"
        key1 = load_or_create_file_key(path)
        key2 = load_or_create_file_key(path)
        self.assertEqual(key1, key2)

    def test_corrupt_key_raises_and_not_overwritten(self):
        path = self._tmp / "servers.key"
        path.write_bytes(b"garbage-not-a-valid-key")
        with self.assertRaises(VaultError):
            load_or_create_file_key(path)
        self.assertEqual(path.read_bytes(), b"garbage-not-a-valid-key")

    def test_setup_file_unlocks_vault(self):
        path = self._tmp / "servers.key"
        vault.setup_file(path)
        self.assertTrue(vault.unlocked)
        self.assertEqual(vault.kind, BACKEND_FILE_KEY)
        token = vault.encrypt("pw")
        self.assertEqual(vault.decrypt(token), "pw")


if __name__ == "__main__":
    unittest.main()
