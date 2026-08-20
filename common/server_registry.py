"""
common/server_registry.py

Реестр серверов (MySQL/MSSQL) с персональными реквизитами подключения.

Каждый сервер хранится как ServerSpec (host, port, engine, user, password)
в JSON-файле servers.json. Пароли шифруются Fernet (cryptography). Ключ
защищается одним из двух режимов (см. common/key_store.py):

- master_password — персональный мастер-пароль: ключ выводится из пароля
  (PBKDF2), нигде не хранится, в файле только соль+верификатор;
- file_key — случайный ключ в файле servers.key рядом с servers.json.

Формат файла: {"meta": {...}, "servers": [...]}. Мета нужна, чтобы файл был
самодостаточным: перенос на другую машину не требует внешних настроек.
Старый плоский формат (список без меты) читается как legacy-миграция.

Защита от потери данных (диагноз 4.21): save() запрещён, пока vault
заблокирован, — запись «пустых» паролей поверх нерасшифрованных исключена
на уровне API. Повреждённый файл ключа не пересоздаётся.

Миграция: если servers.json ещё нет, а рядом есть servers.txt (старый
формат — просто хосты), серверы импортируются как MySQL с реквизитами
из [mysql] config.ini.

Резервное копирование: при каждом сохранении создаётся timestamp-копия
в подпапке backups/ с автоматической подчисткой старых (backup_count).

Потокобезопасность: доступ к кэшу — под RLock; credentials_for()
вызывается из рабочих потоков (GUI/worker), поэтому чтение безопасно.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from common.config import config
from common.key_store import (
    BACKEND_FILE_KEY,
    BACKEND_MASTER_PASSWORD,
    VaultError,
    VaultLockedError,
    vault,
)
from common.logger import logger

ENGINE_MYSQL = "mysql"
ENGINE_MSSQL = "mssql"
ENGINE_PGSQL = "pgsql"

_SYSTEM_DBS = frozenset(
    ("information_schema", "performance_schema", "mysql", "sys",
     "master", "tempdb", "model", "msdb"),
)


@dataclass
class ServerSpec:
    host: str
    port: int = 0
    engine: str = ENGINE_MYSQL
    user: str = ""
    password: str = ""
    name: str = ""
    ref: bool = False  # хост пришёл из эталона servers.reference.json

    def __post_init__(self):
        if not self.port:
            self.port = default_port(self.engine)

    def display_name(self) -> str:
        if self.name and self.name != self.host:
            return f"{self.name} ({self.host})"
        return self.host

    def ui_label(self) -> str:
        """Имя для списков серверов: только Name (host скрыт),
        при отсутствии имени — host."""
        return self.name or self.host


def default_port(engine: str) -> int:
    if engine == ENGINE_MSSQL:
        return config.mssql.port
    if engine == ENGINE_PGSQL:
        return config.pgsql.port
    return config.mysql.port


class ServerRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._specs: list[ServerSpec] = []
        self._loaded = False

        base = Path(config.advanced.servers_file)
        self.servers_file = base if base.is_absolute() else base
        self.key_file = self.servers_file.with_suffix(".key")
        self.vault = vault

        # Путь к папке резервных копий
        self.backups_dir = self.servers_file.parent / "backups"

    # ----------------------------------------------------------
    # Ключ шифрования (vault)
    # ----------------------------------------------------------

    def read_meta(self) -> dict | None:
        """Возвращает мету vault из servers.json (не требует ключа).

        None — файла нет или старый плоский формат без меты.
        """
        with self._lock:
            try:
                raw = json.loads(self.servers_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            if isinstance(raw, dict) and "meta" in raw:
                return raw["meta"]
            return None

    def needs_unlock(self) -> bool:
        """Нужно ли действие пользователя до загрузки данных.

        True: существует vault вида master_password и он не разблокирован.
        Для file_key разблокировка происходит автоматически.
        """
        meta = self.read_meta()
        if not meta:
            return False
        if meta.get("kind") == BACKEND_FILE_KEY:
            return False
        return not self.vault.unlocked

    def unlock_master(self, password: str) -> None:
        """Разблокирует vault существующим мастер-паролем."""
        meta = self.read_meta()
        if not meta:
            raise VaultError("Нет метаданных ключа в servers.json")
        self.vault.unlock_master(password, meta)

    def ensure_key(self) -> None:
        """Разблокирует vault по типу меты (автоматически для file_key)."""
        meta = self.read_meta()
        if not meta or self.vault.unlocked:
            return
        if meta.get("kind") == BACKEND_FILE_KEY:
            self.vault.unlock_file(self.key_file)

    def setup_vault(self, kind: str, password: str | None = None) -> None:
        """Создаёт vault для нового/первого запуска (без записи файла)."""
        if kind == BACKEND_MASTER_PASSWORD:
            if not password:
                raise VaultError("Для мастер-пароля требуется пароль")
            self.vault.setup_master(password, config.security.kdf_iterations)
        elif kind == BACKEND_FILE_KEY:
            self.vault.setup_file(self.key_file)
        else:
            raise VaultError(f"Неизвестный тип ключа: {kind}")

    def rekey(self, kind: str, password: str | None = None) -> None:
        """Перешифровывает servers.json под новый тип ключа.

        Требует разблокированного vault (текущий ключ). Возвращает None;
        при неверном пароле/блокировке поднимает VaultError.
        """
        with self._lock:
            specs = self.load()
            self.setup_vault(kind, password)
            self.save(specs)

    def encrypt(self, value: str) -> str:
        if not value:
            return ""
        return self.vault.encrypt(value)

    def decrypt(self, value: str) -> str:
        if not value:
            return ""
        try:
            return self.vault.decrypt(value)
        except VaultLockedError:
            raise
        except Exception:
            logger.warning(
                "Не удалось расшифровать пароль для одного из серверов "
                "(ключ не подходит или токен повреждён)"
            )
            return ""

    # ----------------------------------------------------------
    # Загрузка / сохранение
    # ----------------------------------------------------------

    def load(self) -> list[ServerSpec]:
        with self._lock:
            if self._loaded:
                return list(self._specs)

            if not self.servers_file.exists():
                self._migrate_from_reference()
                return list(self._specs)

            try:
                raw = json.loads(self.servers_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = []

            legacy = not isinstance(raw, dict) or "meta" not in raw

            if legacy:
                # Старый плоский формат: пароли пытаемся расшифровать
                # текущим ключом; без ключа — только хосты (legacy-миграция).
                self.ensure_key()
                entries = raw if isinstance(raw, list) else []
            else:
                self.ensure_key()
                kind = raw["meta"].get("kind")
                if kind not in (BACKEND_MASTER_PASSWORD, BACKEND_FILE_KEY):
                    raise VaultError(f"Неизвестный тип ключа: {kind}")
                if not self.vault.unlocked:
                    raise VaultLockedError(
                        "Хранилище зашифровано мастер-паролем — "
                        "требуется разблокировка"
                    )
                entries = raw.get("servers", [])

            specs: list[ServerSpec] = []

            can_decrypt = self.vault.unlocked

            for entry in entries:
                try:
                    raw_password = str(entry.get("password", ""))
                    password = (
                        self.decrypt(raw_password)
                        if can_decrypt and raw_password
                        else ""
                    )
                    spec = ServerSpec(
                        host=str(entry.get("host", "")).strip(),
                        port=int(entry.get("port") or 0),
                        engine=str(entry.get("engine") or ENGINE_MYSQL).lower(),
                        user=str(entry.get("user", "")),
                        password=password,
                        name=str(entry.get("name", "")),
                        ref=bool(entry.get("ref")),
                    )
                except (TypeError, ValueError):
                    continue

                if not spec.host:
                    continue

                if spec.engine not in (ENGINE_MYSQL, ENGINE_MSSQL, ENGINE_PGSQL):
                    spec.engine = ENGINE_MYSQL

                specs.append(spec)

            self._specs = specs
            self._loaded = True

            stats = self._sync_reference()
            if any(stats):
                logger.info(
                    f"Синхронизация с эталоном: "
                    f"+{stats[0]} добавлено, ~{stats[1]} обновлено, "
                    f"-{stats[2]} удалено"
                )

            return list(self._specs)

    def reload(self) -> list[ServerSpec]:
        """Принудительное перечитывание servers.json с диска.

        Сбрасывает флаг _loaded и перезапускает load(). При ошибке
        (файл повреждён, нет доступа) — восстанавливает предыдущий
        список серверов и логирует причину.
        """
        with self._lock:
            old_specs = list(self._specs)
            old_loaded = self._loaded
            self._loaded = False
        try:
            return self.load()
        except Exception:
            with self._lock:
                self._specs = old_specs
                self._loaded = old_loaded
            logger.warning(
                f"reload failed, restored {len(old_specs)} servers "
                f"from cache"
            )
            raise

    def _reference_file(self) -> Path:
        """Путь к эталону серверов (servers.reference.json).

        В frozen-сборке файл лежит внутри бандла (sys._MEIPASS),
        в dev-режиме — в корне репозитория.
        """
        if getattr(sys, "frozen", False):
            return Path(sys._MEIPASS) / "servers.reference.json"
        return Path(__file__).resolve().parent.parent / "servers.reference.json"

    def _parse_reference(self) -> list[ServerSpec]:
        """Читает эталон servers.reference.json (best-effort).

        Невалидный/отсутствующий файл → пустой список.
        """
        try:
            raw = json.loads(self._reference_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

        entries = raw if isinstance(raw, list) else []
        specs: list[ServerSpec] = []
        for entry in entries:
            host = entry.get("host", "") if isinstance(entry, dict) else ""
            if not isinstance(host, str):
                continue
            host = host.strip()
            if not host:
                continue
            engine = str(entry.get("engine") or ENGINE_MYSQL).lower()
            if engine not in (ENGINE_MYSQL, ENGINE_MSSQL, ENGINE_PGSQL):
                engine = ENGINE_MYSQL
            specs.append(
                ServerSpec(
                    host=host,
                    port=int(entry.get("port") or 0),
                    engine=engine,
                    user="",
                    password="",
                    name=str(entry.get("name", "")),
                )
            )
        return specs

    def _migrate_from_reference(self) -> None:
        """Первый запуск: импорт серверов из эталона servers.reference.json.

        Реквизиты из эталона не копируются — пустые поля означают
        наследование глобальных значений config.ini своего движка.
        Если эталона нет — откат к legacy-импорту из servers.txt.
        """
        specs = self._parse_reference()
        if not specs:
            self._migrate_from_txt()
            return

        for spec in specs:
            spec.ref = True
        self._specs = specs
        self._loaded = True
        if self.vault.unlocked:
            self.save(list(self._specs))

    def _sync_reference(self) -> tuple[int, int, int]:
        """Синхронизирует реестр с эталоном servers.reference.json.

        Эталон — источник истины для списка:
        - новые хосты эталона добавляются (с пометкой ref);
        - хосты эталона обновляются по engine/port/name (реквизиты
          пользователя сохраняются);
        - хосты с пометкой ref, которых больше нет в эталоне, удаляются;
        - непомеченные хосты (добавленные пользователем вручную)
          сохраняются, кроме legacy-«оболочек» от старой миграции
          servers.txt: engine=mysql, реквизиты равны глобальным из
          config.ini, без имени и нестандартного порта.

        Возвращает (добавлено, обновлено, удалено).
        """
        reference = {
            spec.host: spec for spec in self._parse_reference()
        }

        added = 0
        updated = 0
        removed = 0
        changed = False

        merged: list[ServerSpec] = []
        for spec in self._specs:
            ref_spec = reference.get(spec.host)
            if ref_spec is not None:
                attrs = (spec.engine, spec.port, spec.name)
                spec.engine = ref_spec.engine
                spec.port = ref_spec.port
                spec.name = ref_spec.name
                spec.ref = True
                if (spec.engine, spec.port, spec.name) != attrs:
                    updated += 1
                    changed = True
                merged.append(spec)
                continue

            if spec.ref:
                removed += 1
                changed = True
                continue

            # Legacy-«оболочка» от миграции servers.txt: без собственных
            # данных — глобальные реквизиты mysql, без имени, порт по
            # умолчанию. Таких хостов в эталоне уже нет — удаляем.
            is_stale_shell = (
                spec.engine == ENGINE_MYSQL
                and spec.port == default_port(ENGINE_MYSQL)
                and not spec.name
                and spec.user == config.mysql.user
                and spec.password == config.mysql.password
            )
            if is_stale_shell:
                removed += 1
                changed = True
                continue

            merged.append(spec)  # пользовательский сервер

        for host, spec in reference.items():
            if not any(existing.host == host for existing in merged):
                spec.ref = True
                merged.append(spec)
                added += 1
                changed = True

        if changed:
            self._specs = merged
            if self.vault.unlocked:
                try:
                    self.save(list(self._specs))
                except Exception:
                    pass
        return added, updated, removed

    def _migrate_from_txt(self) -> None:
        """Legacy-импорт серверов из servers.txt (просто хосты, MySQL).

        Используется как запасной вариант, если эталона
        servers.reference.json нет.
        """
        txt = Path(config.advanced.servers_file).with_suffix(".txt")
        servers_txt = txt if txt.exists() else self.servers_file.with_name("servers.txt")

        if not servers_txt.exists():
            self._loaded = True
            return

        try:
            hosts = [
                line.strip()
                for line in servers_txt.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except OSError:
            self._loaded = True
            return

        self._specs = [
            ServerSpec(
                host=host,
                engine=ENGINE_MYSQL,
                user=config.mysql.user,
                password=config.mysql.password,
            )
            for host in hosts
        ]
        self._loaded = True
        if self.vault.unlocked:
            self.save(list(self._specs))

    def _create_backup(self) -> None:
        """Создаёт timestamp-резервную копию servers.json в backups/."""
        try:
            # Создаём папку backups, если её нет
            self.backups_dir.mkdir(parents=True, exist_ok=True)

            # Генерируем имя файла с timestamp
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_file = self.backups_dir / f"servers-{timestamp}.bak.json"

            # Копируем текущий файл
            if self.servers_file.exists():
                content = self.servers_file.read_text(encoding="utf-8")
                backup_file.write_text(content, encoding="utf-8")
                if os.name != "nt":
                    backup_file.chmod(0o600)

            # Очищаем старые копии
            self._cleanup_backups()
        except OSError:
            pass

    def _cleanup_backups(self) -> None:
        """Удаляет старые резервные копии, оставляя только backup_count штук."""
        try:
            if not self.backups_dir.exists():
                return

            # Получаем все файлы резервных копий, отсортированные по времени
            backups = sorted(
                self.backups_dir.glob("servers-*.bak.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

            # Удаляем старые копии (оставляем только backup_count)
            for backup in backups[config.security.backup_count:]:
                backup.unlink()
        except OSError:
            pass

    def save(self, specs: list[ServerSpec]) -> None:
        with self._lock:
            if not self.vault.unlocked:
                raise VaultLockedError(
                    "Хранилище заблокировано — сохранить нельзя. "
                    "Разблокируйте ключ (мастер-пароль или файл ключа)."
                )

            self._specs = [s for s in specs if s and s.host]
            self._loaded = True

            meta = self.vault.meta or {
                "version": 1,
                "kind": BACKEND_FILE_KEY,
            }
            payload = {
                "meta": meta,
                "servers": [
                    {
                        "host": s.host,
                        "port": s.port,
                        "engine": s.engine,
                        "user": s.user,
                        "password": self.vault.encrypt(s.password),
                        "name": s.name,
                        "ref": s.ref,
                    }
                    for s in self._specs
                ],
            }

            try:
                # Создаём резервную копию перед сохранением
                self._create_backup()

                # Сохраняем основной файл
                self.servers_file.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                # Устанавливаем права 0600
                if os.name != "nt":
                    self.servers_file.chmod(0o600)
            except OSError:
                pass

    # ----------------------------------------------------------
    # Доступ к спецификациям
    # ----------------------------------------------------------

    def specs(self) -> list[ServerSpec]:
        return self.load()

    def hosts(self) -> list[str]:
        return [spec.host for spec in self.load()]

    def find(self, host: str) -> ServerSpec | None:
        for spec in self.load():
            if spec.host == host:
                return spec
        return None

    def engine(self, host: str) -> str:
        spec = self.find(host)
        if spec is not None:
            return spec.engine
        return ENGINE_MYSQL

    def credentials_for(self, host: str) -> tuple[str, str, int]:
        """Возвращает (user, password, port) для подключения к хосту.

        Приоритет: реквизиты сервера из реестра → глобальные из config.ini
        соответствующей СУБД. Пустое поле в записи сервера означает
        «взять глобальное значение» (записи без собственного пароля
        наследуют пароль из config.ini своего движка).
        """
        spec = self.find(host)

        if spec is None:
            return config.mysql.user, config.mysql.password, config.mysql.port

        if spec.engine == ENGINE_MSSQL:
            user = spec.user or config.mssql.user
            password = spec.password or config.mssql.password
            port = spec.port or config.mssql.port
        elif spec.engine == ENGINE_PGSQL:
            user = spec.user or config.pgsql.user
            password = spec.password or config.pgsql.password
            port = spec.port or config.pgsql.port
        else:
            user = spec.user or config.mysql.user
            password = spec.password or config.mysql.password
            port = spec.port or config.mysql.port

        return user, password, port

    def engine_is_mssql(self, host: str) -> bool:
        return self.engine(host) == ENGINE_MSSQL

    # ----------------------------------------------------------
    # Мутации
    # ----------------------------------------------------------

    def add(self, spec: ServerSpec) -> None:
        with self._lock:
            specs = self.load()
            specs = [s for s in specs if s.host != spec.host]
            specs.append(spec)
            self.save(specs)

    def update(self, old_host: str, spec: ServerSpec) -> None:
        with self._lock:
            specs = self.load()
            specs = [s for s in specs if s.host != old_host]
            specs.append(spec)
            self.save(specs)

    def remove(self, host: str) -> bool:
        with self._lock:
            specs = self.load()
            before = len(specs)
            specs = [s for s in specs if s.host != host]
            if len(specs) == before:
                return False
            self.save(specs)
            return True


registry = ServerRegistry()


def client_for(host: str):
    """Возвращает клиент БД для сервера (MySQL, MSSQL или PostgreSQL)."""
    from common.mssql_client import mssql

    if registry.engine(host) == ENGINE_MSSQL:
        return mssql

    from common.pgsql_client import pgsql

    if registry.engine(host) == ENGINE_PGSQL:
        return pgsql

    from common.mysql_client import mysql

    return mysql


def quote_ident(engine: str, name: str) -> str:
    """Экранирование идентификатора для конкретной СУБД.

    MySQL — обратные кавычки, MSSQL — квадратные скобки,
    PostgreSQL — двойные кавычки.
    """
    if engine == ENGINE_MSSQL:
        return f"[{name.replace(']', ']]')}]"
    if engine == ENGINE_PGSQL:
        return f'"{name.replace(chr(34), chr(34) * 2)}"'
    return f"`{name.replace('`', '``')}`"


def build_select_sql(engine: str, database: str, table: str, limit: int = 1000) -> str:
    """SELECT * с учётом синтаксиса СУБД (LIMIT для MySQL, TOP для MSSQL)."""
    if engine == ENGINE_MSSQL:
        parts = [quote_ident(engine, database)]

        # MSSQL-таблица может быть вида "schema.table".
        # Если схема не указана — подставляем dbo: [db].[dbo].[table],
        # иначе [db].[Users] интерпретируется как [db].[схема] и падает
        # с "Invalid object name".
        table_parts = [p.strip() for p in table.split(".") if p.strip()]
        if len(table_parts) == 1:
            table_parts = ["dbo"] + table_parts

        for part in table_parts:
            parts.append(quote_ident(engine, part))

        return f"SELECT TOP {int(limit)} * FROM {'.'.join(parts)}"

    if engine == ENGINE_PGSQL:
        # PostgreSQL: без схемы — public (аналогично MSSQL dbo).
        # Иначе "db"."table" интерпретируется как "схема"."таблица",
        # и запрос падает с "relation ... does not exist".
        table_parts = [p.strip() for p in table.split(".") if p.strip()]
        if len(table_parts) == 1:
            table_parts = ["public"] + table_parts

        table_ref = ".".join(quote_ident(engine, p) for p in table_parts)
        return (
            f"SELECT * FROM {quote_ident(engine, database)}.{table_ref} "
            f"LIMIT {int(limit)}"
        )

    return (
        f"SELECT * FROM {quote_ident(engine, database)}.{quote_ident(engine, table)} "
        f"LIMIT {int(limit)}"
    )


if __name__ == "__main__":
    print("Server registry loaded.")
