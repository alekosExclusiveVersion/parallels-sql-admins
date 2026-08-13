"""
common/key_store.py

Защита ключа шифрования паролей серверов — два режима на выбор пользователя:

1. master_password — персональный мастер-пароль. Ключ нигде не хранится:
   выводится из пароля через PBKDF2-HMAC-SHA256. В servers.json лежат только
   соль и верификатор, которые позволяют проверить правильность пароля.
   Без пароля данные не расшифровать даже при наличии бинарника и файла.

2. file_key — случайный Fernet-ключ в файле servers.key рядом с servers.json
   (права 0600). Файл ключа переезжает вместе с данными. Существующий ключ
   никогда не пересоздаётся: повреждённый файл — это ошибка, а не новая
   генерация (иначе старые пароли молча превращаются в пустые).

Ключ живёт в памяти сессии (Vault). В режиме master_password он не пишется
на диск вовсе; в режиме file_key файл создаётся однократно.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

BACKEND_MASTER_PASSWORD = "master_password"
BACKEND_FILE_KEY = "file_key"

KDF_VERSION = 1
SALT_BYTES = 16
_VERIFIER_PLAINTEXT = b"Parallels SQL Admin vault verifier v1"


class VaultError(RuntimeError):
    """Базовая ошибка хранилища ключей."""


class VaultLockedError(VaultError):
    """Хранилище заблокировано — требуется разблокировка."""


class WrongMasterPasswordError(VaultError):
    """Неверный мастер-пароль."""


def derive_key(password: str, salt: bytes, iterations: int) -> bytes:
    """Выводит Fernet-ключ из мастер-пароля через PBKDF2-HMAC-SHA256."""
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        int(iterations),
        dklen=32,
    )
    return base64.urlsafe_b64encode(dk)


def create_master_meta(password: str, iterations: int) -> dict:
    """Создаёт метаданные vault для мастер-пароля (соль + верификатор)."""
    salt = secrets.token_bytes(SALT_BYTES)
    key = derive_key(password, salt, iterations)
    verifier = Fernet(key).encrypt(_VERIFIER_PLAINTEXT).decode("ascii")
    return {
        "version": KDF_VERSION,
        "kind": BACKEND_MASTER_PASSWORD,
        "salt": base64.b64encode(salt).decode("ascii"),
        "iterations": int(iterations),
        "verifier": verifier,
    }


def verify_master_password(password: str, meta: dict) -> bool:
    """Проверяет мастер-пароль по верификатору (пароль не сохраняется)."""
    try:
        salt = base64.b64decode(meta["salt"])
        key = derive_key(password, salt, int(meta["iterations"]))
        plain = Fernet(key).decrypt(meta["verifier"].encode("ascii"))
        return hmac.compare_digest(plain, _VERIFIER_PLAINTEXT)
    except Exception:
        return False


def load_or_create_file_key(key_file: Path) -> bytes:
    """Возвращает ключ из файла, создавая его при первом запуске.

    Существующий ключ НИКОГДА не пересоздаётся: повреждённый файл — это
    ошибка, а не новая генерация (иначе старые пароли молча становятся
    пустыми — см. диагностику потери паролей в 4.21).
    """
    if key_file.exists():
        try:
            key = key_file.read_bytes()
            Fernet(key)
        except (ValueError, TypeError, OSError):
            raise VaultError(
                f"Файл ключа повреждён: {key_file}. Восстановите ключ из "
                "резервной копии, иначе пароли не расшифровать."
            ) from None
        return key
    key = Fernet.generate_key()
    key_file.write_bytes(key)
    key_file.chmod(0o600)
    logger.info("Создан новый файл ключа: %s", key_file)
    return key


class Vault:
    """Состояние ключа сессии. После lock() ключ стирается из памяти."""

    def __init__(self) -> None:
        self._key: bytes | None = None
        self._meta: dict | None = None

    @property
    def unlocked(self) -> bool:
        return self._key is not None

    @property
    def kind(self) -> str | None:
        if not self._meta:
            return None
        return self._meta.get("kind")

    @property
    def meta(self) -> dict | None:
        if not self._meta:
            return None
        return dict(self._meta)

    def lock(self) -> None:
        self._key = None
        self._meta = None

    def unlock_master(self, password: str, meta: dict) -> None:
        if not verify_master_password(password, meta):
            raise WrongMasterPasswordError("Неверный мастер-пароль")
        salt = base64.b64decode(meta["salt"])
        self._key = derive_key(password, salt, int(meta["iterations"]))
        self._meta = dict(meta)

    def unlock_file(self, key_file: Path) -> None:
        self._key = load_or_create_file_key(key_file)
        self._meta = {
            "version": KDF_VERSION,
            "kind": BACKEND_FILE_KEY,
        }

    def setup_master(self, password: str, iterations: int) -> None:
        """Создаёт новый vault для мастер-пароля и разблокирует его."""
        meta = create_master_meta(password, iterations)
        self.unlock_master(password, meta)

    def setup_file(self, key_file: Path) -> None:
        """Создаёт/загружает файловый ключ и разблокирует vault."""
        self.unlock_file(key_file)

    def encrypt(self, value: str) -> str:
        if not value:
            return ""
        return self._fernet().encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        if not value:
            return ""
        return self._fernet().decrypt(value.encode("utf-8")).decode("utf-8")

    def _fernet(self) -> Fernet:
        if self._key is None:
            raise VaultLockedError(
                "Хранилище ключей заблокировано: сначала разблокируйте ключ"
            )
        return Fernet(self._key)


vault = Vault()
