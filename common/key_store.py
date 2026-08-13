"""
common/key_store.py

Хранение Fernet-ключа для шифрования паролей серверов.

Бэкенды:
- macOS_keychain: ключ хранится в macOS Keychain (по умолчанию на macOS)
- file: ключ хранится в файле рядом с servers.json (только для тестов/не-macOS)

Выбор бэкенда:
- на macOS: только Keychain (файловый режим включается только через PARALLELS_SQL_ADMIN_TESTING=1)
- на других ОС: только файловый бэкенд (PARALLELS_SQL_ADMIN_KEY_BACKEND=file)

На macOS ключ извлекается через `security find-generic-password -s <service> -w`.
На других ОС используется файловый бэкенд автоматически.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet

from common.config import config


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _get_key_from_macos_keychain(service: str, account: str) -> bytes | None:
    """Извлекает ключ из macOS Keychain через security CLI."""
    if not _is_macos():
        return None

    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                service,
                "-a",
                account,
                "-w",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        key = result.stdout.strip().encode("utf-8")
        # Проверка валидности ключа Fernet (должен быть base64 длиной 32 байта)
        Fernet(key)
        return key
    except (subprocess.CalledProcessError, ValueError):
        return None


def _store_key_in_macos_keychain(key: bytes, service: str, account: str) -> None:
    """Сохраняет ключ в macOS Keychain через security CLI."""
    if not _is_macos():
        raise RuntimeError("macOS Keychain доступен только на macOS")

    try:
        # Удаляем старую запись, если есть
        subprocess.run(
            [
                "security",
                "delete-generic-password",
                "-s",
                service,
                "-a",
                account,
            ],
            capture_output=True,
            text=True,
        )
        # Добавляем новую запись
        subprocess.run(
            [
                "security",
                "add-generic-password",
                "-s",
                service,
                "-a",
                account,
                "-w",
                key.decode("utf-8"),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Не удалось сохранить ключ в Keychain: {e.stderr}") from e


def _get_key_from_file(key_file: Path) -> bytes | None:
    """Извлекает ключ из файла."""
    try:
        if key_file.exists():
            key = key_file.read_bytes()
            Fernet(key)  # Проверка валидности
            return key
    except Exception:
        pass
    return None


def _store_key_to_file(key: bytes, key_file: Path) -> None:
    """Сохраняет ключ в файл с правами 0600."""
    key_file.write_bytes(key)
    key_file.chmod(0o600)


def get_key() -> bytes:
    """Возвращает Fernet-ключ, загруженный из выбранного бэкенда."""
    service = "ParallelsSQLAdmins"
    account = "fernet-key"

    # Тестовый режим: разрешить файловый бэкенд через переменную окружения
    is_testing = os.environ.get("PARALLELS_SQL_ADMIN_TESTING") == "1"
    key_backend = os.environ.get(
        "PARALLELS_SQL_ADMIN_KEY_BACKEND", config.security.key_backend
    )

    if key_backend == "macos_keychain" and _is_macos():
        key = _get_key_from_macos_keychain(service, account)
        if key:
            return key
        # Если ключа нет в Keychain, пробуем файловый fallback (только для миграции)
        key = _get_key_from_file(Path("servers.key"))
        if key:
            # Миграция: сохраняем в Keychain и удаляем файл
            _store_key_in_macos_keychain(key, service, account)
            Path("servers.key").unlink(missing_ok=True)
            return key
        # Генерируем новый ключ
        new_key = Fernet.generate_key()
        _store_key_in_macos_keychain(new_key, service, account)
        return new_key

    # Файловый бэкенд (только для тестов/не-macOS)
    if is_testing or not _is_macos():
        key = _get_key_from_file(Path("servers.key"))
        if key:
            return key
        new_key = Fernet.generate_key()
        _store_key_to_file(new_key, Path("servers.key"))
        return new_key

    # На macOS без тестового режима и без ключа в Keychain — ошибка
    raise RuntimeError("Key not found in macOS Keychain and testing mode is disabled")


def store_key(key: bytes) -> None:
    """Сохраняет ключ в выбранный бэкенд."""
    service = "ParallelsSQLAdmins"
    account = "fernet-key"

    key_backend = os.environ.get(
        "PARALLELS_SQL_ADMIN_KEY_BACKEND", config.security.key_backend
    )

    if key_backend == "macos_keychain" and _is_macos():
        _store_key_in_macos_keychain(key, service, account)
    else:
        _store_key_to_file(key, Path("servers.key"))


def delete_key() -> None:
    """Удаляет ключ из всех бэкендов."""
    service = "ParallelsSQLAdmins"
    account = "fernet-key"

    # Удаляем из Keychain
    if _is_macos():
        subprocess.run(
            [
                "security",
                "delete-generic-password",
                "-s",
                service,
                "-a",
                account,
            ],
            capture_output=True,
            text=True,
        )

    # Удаляем файл
    Path("servers.key").unlink(missing_ok=True)


if __name__ == "__main__":
    # Тест
    key = get_key()
    print(f"Key loaded: {key[:16].hex()}... (len={len(key)})")
    print(f"macOS: {_is_macos()}")