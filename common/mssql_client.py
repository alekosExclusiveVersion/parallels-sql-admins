"""
common/mssql_client.py

Единая точка работы с Microsoft SQL Server (pymssql).

Интерфейс повторяет MySQLClient (connect / query / list_databases /
server_catalog / database_table_sizes / kill_connection / connection_id),
чтобы воркеры могли работать с обоими движками через client_for().

Соединения обслуживает глобальный пул common/conn_pool.py (аналогично
MySQL): пары (host, database) переиспользуют одно соединение между
запросами из любых потоков, idle-кэш ограничен
(pool_idle / max_idle_connections / idle_timeout).
"""

from __future__ import annotations

import atexit
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any

import pymssql

from common.config import config
from common.conn_pool import ConnectionPool
from common.logger import logger
from common.server_registry import registry

_SYSTEM_DBS = frozenset(
    ("master", "tempdb", "model", "msdb",
     "information_schema", "performance_schema", "mysql", "sys"),
)


def _escape_bracket(name: str) -> str:
    """Экранирование имени БД внутри [..] (T-SQL)."""
    return name.replace("]", "]]")


# Запрос размеров таблиц текущей БД (контекст задаётся USE [db]).
_TABLE_SIZES_SQL = """
SELECT
    CASE WHEN s.name = 'dbo' THEN t.name ELSE s.name + N'.' + t.name END
        AS table_name,
    SUM(a.total_pages) * 8 * 1024 AS total_bytes
FROM sys.tables t
JOIN sys.schemas s ON t.schema_id = s.schema_id
JOIN sys.indexes i ON t.object_id = i.object_id
JOIN sys.partitions p ON i.object_id = p.object_id AND i.index_id = p.index_id
JOIN sys.allocation_units a ON p.partition_id = a.container_id
WHERE a.type IN (1, 2)
GROUP BY s.name, t.name
ORDER BY total_bytes DESC
"""


class MSSQLClient:
    def __init__(self, cfg: Any = None) -> None:
        self.cfg = cfg or config.mssql
        self._pool = ConnectionPool(
            cfg=lambda: self.cfg,
            open_conn=lambda host, db: self._open_connection(host, db),
            alive_check=None,
            acquire_timeout=self.cfg.acquire_timeout,
            name="mssql",
        )
        # pymssql.Connection — C-расширение без __dict__: атрибуты
        # (host/db/spid) нельзя присваивать объекту, храним их по id(conn).
        self._meta: dict[int, dict] = {}
        self._meta_lock = threading.Lock()
        atexit.register(self.close_all)

    # ----------------------------------------------------------
    # Пул соединений
    # ----------------------------------------------------------

    def _open_connection(self, host: str, database: str | None = None):
        user, password, port = registry.credentials_for(host)
        conn = None
        last_error = None

        for attempt in range(1, self.cfg.retry + 1):
            try:
                conn = pymssql.connect(
                    server=host,
                    port=port,
                    user=user,
                    password=password,
                    database=database,
                    login_timeout=self.cfg.connect_timeout,
                    as_dict=True,
                    tds_version="7.0",
                )
                break
            except Exception as ex:
                last_error = ex
                logger.warning(
                    f"{host}: попытка {attempt}/{self.cfg.retry} подключения "
                    f"не удалась ({ex})"
                )
                if attempt < self.cfg.retry:
                    import time
                    time.sleep(1)

        if conn is None:
            raise RuntimeError(
                f"Не удалось подключиться к {host}: {last_error}"
            )

        self._meta_set(conn, host=host, db=database, spid=None)

        try:
            conn.autocommit(True)
        except Exception:
            pass

        try:
            with conn.cursor() as cur:
                cur.execute("SELECT @@SPID AS spid")
                row = cur.fetchone()
                if row:
                    self._meta_set(
                        conn, spid=int(row.get("spid") or 0) or None
                    )
        except Exception:
            pass

        return conn

    def _pool_state(self) -> dict:
        """Снимок пула для тестов."""
        return self._pool.debug_state()

    def _meta_set(self, conn, **kwargs: Any) -> None:
        with self._meta_lock:
            self._meta.setdefault(id(conn), {}).update(kwargs)

    def _meta_get(self, conn, key: str, default: Any = None) -> Any:
        with self._meta_lock:
            return self._meta.get(id(conn), {}).get(key, default)

    def _meta_clear(self, conn) -> None:
        with self._meta_lock:
            self._meta.pop(id(conn), None)

    def close_all(self) -> None:
        with self._meta_lock:
            self._meta.clear()
        self._pool.close_all()

    @contextmanager
    def connect(self, host: str, database: str | None = None):
        conn = self._pool.acquire(host, database)

        try:
            yield conn
        finally:
            self._pool.release(host, database, conn)

    def execute_on_connection(self, conn, sql: str, params=None):
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)

                if cur.description is not None:
                    return cur.fetchall()
                return []
        except Exception:
            # Разрыв соединения — один повтор на свежем соединении.
            if not getattr(conn, "closed", False):
                raise

            host = self._meta_get(conn, "host")
            database = self._meta_get(conn, "db")

            if not host:
                raise

            logger.warning(f"{host}: соединение разорвано, повтор запроса")

            new_conn = self._open_connection(host, database)

            try:
                with new_conn.cursor() as cur:
                    cur.execute(sql, params)

                    if cur.description is not None:
                        return cur.fetchall()
                    return []
            finally:
                try:
                    new_conn.close()
                except Exception:
                    pass

    def query(self, host: str, sql: str, database: str | None = None,
              params: tuple[Any, ...] | None = None) -> list[dict]:
        with self.connect(host, database) as conn:
            return self.execute_on_connection(conn, sql, params)

    # ----------------------------------------------------------
    # Список БД
    # ----------------------------------------------------------

    def _filtered_databases(self, host: str, with_prefix: bool) -> list[str]:
        rows = self.query(host, "SELECT name FROM sys.databases")

        ignore = set(config.advanced.ignore_databases) | _SYSTEM_DBS

        names = [
            row.get("name")
            for row in rows
            if row.get("name") not in ignore
        ]

        if with_prefix:
            prefix = config.filter.database_prefix
            pattern = config.filter.exclude_database_regex
            names = [
                db
                for db in names
                if db.startswith(prefix) and not re.search(pattern, db)
            ]

        return sorted(names)

    def list_databases(self, host: str) -> list[str]:
        return self._filtered_databases(host, with_prefix=True)

    def list_all_databases(self, host: str) -> list[str]:
        return self._filtered_databases(host, with_prefix=False)

    # ----------------------------------------------------------
    # Размеры БД и таблиц
    # ----------------------------------------------------------

    def database_sizes(self, host: str) -> dict[str, int]:
        sql = """
SELECT
    DB_NAME(database_id) AS db,
    SUM(size) * 8 * 1024 AS total_bytes
FROM sys.master_files
WHERE type = 0
GROUP BY database_id
"""
        rows = self.query(host, sql)

        ignore = set(config.advanced.ignore_databases) | _SYSTEM_DBS

        return {
            row["db"]: int(row["total_bytes"] or 0)
            for row in rows
            if row.get("db") and row["db"] not in ignore
        }

    def server_catalog(
        self,
        host: str,
    ) -> tuple[dict[str, int], dict[str, list[tuple[str, int]]]]:
        """Размеры всех БД сервера и таблицы по каждой БД.

        Таблицы грузятся параллельно через all_databases_table_sizes —
        все запросы идут по ключу пула (host, None) с USE [db], поэтому
        соединений не больше max_per_key, независимо от числа БД.
        """
        sizes = self.database_sizes(host)

        try:
            tables = self.all_databases_table_sizes(host, list(sizes))
        except Exception:
            logger.warning(
                f"{host}: не удалось получить таблицы разом, "
                "будут загружаться по БД при раскрытии"
            )
            tables = {}

        return sizes, tables

    def all_databases_table_sizes(
        self,
        host: str,
        databases: list[str],
    ) -> dict[str, list[tuple[str, int]]]:
        """Таблицы для набора БД одной пачкой на общем соединении.

        Каждый запрос выполняется как USE [db]; <sql> по ключу пула
        (host, None), так что набор БД сервера переиспользует до
        config.sizes.table_workers соединений вместо одного на БД.
        """
        databases = list(databases)
        if not databases:
            return {}

        max_workers = max(1, min(config.sizes.table_workers, len(databases)))

        def _fetch(db: str) -> tuple[str, list[tuple[str, int]]]:
            sql = f"USE [{_escape_bracket(db)}];\n{_TABLE_SIZES_SQL}"
            rows = self.query(host, sql)
            return db, [
                (row["table_name"], int(row["total_bytes"] or 0))
                for row in rows
                if row.get("table_name")
            ]

        results: dict[str, list[tuple[str, int]]] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for db, table_sizes in ex.map(_fetch, databases):
                results[db] = table_sizes

        return results

    def database_table_sizes(
        self,
        host: str,
        database: str,
    ) -> list[tuple[str, int]]:
        sql = _TABLE_SIZES_SQL
        rows = self.query(host, sql, database)

        return [
            (row["table_name"], int(row["total_bytes"] or 0))
            for row in rows
            if row.get("table_name")
        ]

    # ----------------------------------------------------------
    # Прерывание запросов
    # ----------------------------------------------------------

    def kill_connection(self, host: str, connection_id: int) -> None:
        """Прерывает запрос через KILL (отдельным соединением)."""
        with self.connect(host) as conn:
            with conn.cursor() as cur:
                cur.execute(f"KILL {int(connection_id)}")

    def connection_id(self, conn) -> int | None:
        """SPID соединения для прерывания активного запроса."""
        return self._meta_get(conn, "spid")

    def test_connection(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
    ) -> tuple[bool, str]:
        """Проверка подключения с явными реквизитами (для диалога сервера)."""
        try:
            conn = pymssql.connect(
                server=host,
                port=port,
                user=user,
                password=password,
                login_timeout=self.cfg.connect_timeout,
            )
            conn.close()
        except Exception as ex:
            return False, str(ex)

        return True, ""


mssql = MSSQLClient()


if __name__ == "__main__":
    print("MSSQL client loaded.")
