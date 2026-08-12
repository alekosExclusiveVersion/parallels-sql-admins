"""
common/server_registry.py

Реестр серверов (MySQL/MSSQL) с персональными реквизитами подключения.

Каждый сервер хранится как ServerSpec (host, port, engine, user, password)
в JSON-файле servers.json. Пароли шифруются Fernet (cryptography): ключ
лежит рядом в servers.key. Логин/пароль «зашиты» в настройки каждого
сервера и используются клиентами при подключении (вместо глобальных).

Миграция: если servers.json ещё нет, а рядом есть servers.txt (старый
формат — просто хосты), серверы импортируются как MySQL с реквизитами
из [mysql] config.ini.

Потокобезопасность: доступ к кэшу — под RLock; credentials_for()
вызывается из рабочих потоков (GUI/worker), поэтому чтение безопасно.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

from cryptography.fernet import Fernet

from common.config import config

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
        self._fernet = None

    # ----------------------------------------------------------
    # Ключ шифрования
    # ----------------------------------------------------------

    def _load_fernet(self) -> Fernet:
        if self._fernet is not None:
            return self._fernet

        try:
            raw = self.key_file.read_bytes()
            self._fernet = Fernet(raw)
        except Exception:
            key = Fernet.generate_key()
            try:
                self.key_file.write_bytes(key)
                self.key_file.chmod(0o600)
            except OSError:
                pass
            self._fernet = Fernet(key)

        return self._fernet

    def encrypt(self, value: str) -> str:
        if not value:
            return ""
        return self._load_fernet().encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        if not value:
            return ""
        try:
            return self._load_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    # ----------------------------------------------------------
    # Загрузка / сохранение
    # ----------------------------------------------------------

    def load(self) -> list[ServerSpec]:
        with self._lock:
            if self._loaded:
                return list(self._specs)

            if not self.servers_file.exists():
                self._migrate_from_txt()
                return list(self._specs)

            try:
                raw = json.loads(self.servers_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = []

            specs: list[ServerSpec] = []

            for entry in raw:
                try:
                    spec = ServerSpec(
                        host=str(entry.get("host", "")).strip(),
                        port=int(entry.get("port") or 0),
                        engine=str(entry.get("engine") or ENGINE_MYSQL).lower(),
                        user=str(entry.get("user", "")),
                        password=self.decrypt(str(entry.get("password", ""))),
                        name=str(entry.get("name", "")),
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
            return list(self._specs)

    def _migrate_from_txt(self) -> None:
        """Импорт серверов из старого servers.txt (просто хосты)."""
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
        self.save(list(self._specs))

    def save(self, specs: list[ServerSpec]) -> None:
        with self._lock:
            self._specs = [s for s in specs if s and s.host]
            self._loaded = True

            payload = [
                {
                    "host": s.host,
                    "port": s.port,
                    "engine": s.engine,
                    "user": s.user,
                    "password": self.encrypt(s.password),
                    "name": s.name,
                }
                for s in self._specs
            ]

            try:
                self.servers_file.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
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
    """Экранирование идентификатора для конкретной СУБД."""
    if engine == ENGINE_MSSQL:
        return f"[{name.replace(']', ']]')}]"
    return f"`{name.replace('`', '``')}`"


def build_select_sql(engine: str, database: str, table: str, limit: int = 1000) -> str:
    """SELECT * с учётом синтаксиса СУБД (LIMIT для MySQL, TOP для MSSQL)."""
    if engine == ENGINE_MSSQL:
        parts = [quote_ident(engine, database)]

        # MSSQL-таблица может быть вида "schema.table".
        for part in table.split("."):
            parts.append(quote_ident(engine, part.strip()))

        return f"SELECT TOP {int(limit)} * FROM {'.'.join(parts)}"

    return (
        f"SELECT * FROM {quote_ident(engine, database)}.{quote_ident(engine, table)} "
        f"LIMIT {int(limit)}"
    )


if __name__ == "__main__":
    print("Server registry loaded.")
