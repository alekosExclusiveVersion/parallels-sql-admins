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
    SUM(CAST(a.total_pages AS BIGINT)) * 8 * 1024 AS total_bytes
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
            alive_check=lambda conn: self._is_alive(conn),
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
        user, password, real_host, port = registry.credentials_for(host)
        conn = None
        last_error = None

        for attempt in range(1, self.cfg.retry + 1):
            try:
                conn = pymssql.connect(
                    server=real_host,
                    port=port,
                    user=user,
                    password=password,
                    database=database,
                    login_timeout=self.cfg.connect_timeout,
                    timeout=60,
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

    def _is_alive(self, conn) -> bool:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return True
        except Exception:
            return False

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
        # Префикс database_prefix (например 'ar_') — MySQL-конвенция
        # именования; для MSSQL он не применяется, иначе список БД
        # в SQL-консоли оказывается пустым. Исключаются только системные
        # и ignore_databases.
        return self._filtered_databases(host, with_prefix=False)

    def list_all_databases(self, host: str) -> list[str]:
        return self._filtered_databases(host, with_prefix=False)

    def edit_meta(self, host: str, database: str, table: str, conn=None):
        """(первичные ключи, все колонки) таблицы для редактирования ячеек.

        Если conn передан — переиспользует его (без второго acquire из пула).
        """
        own = conn is None
        if own:
            conn = self.connect(host, database).__enter__()
        try:
            pk = self.execute_on_connection(
                conn,
                "SELECT COL_NAME(ic.object_id, ic.column_id) AS column_name "
                "FROM sys.indexes i "
                "JOIN sys.index_columns ic "
                "  ON i.object_id = ic.object_id AND i.index_id = ic.index_id "
                "WHERE i.is_primary_key = 1 AND i.object_id = OBJECT_ID(%s) "
                "ORDER BY ic.key_ordinal",
                (table,),
            )
            cols = self.execute_on_connection(
                conn,
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
                (table,),
            )
        finally:
            if own:
                conn.__exit__(None, None, None)

        return (
            [row["column_name"] for row in pk],
            [row["COLUMN_NAME"] for row in cols],
        )

    # ----------------------------------------------------------
    # Размеры БД и таблиц
    # ----------------------------------------------------------

    def database_sizes(self, host: str) -> dict[str, int]:
        sql = """
SELECT
    DB_NAME(database_id) AS db,
    SUM(CAST(size AS BIGINT)) * 8 * 1024 AS total_bytes
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

    # ----------------------------------------------------------
    # Удаление БД
    # ----------------------------------------------------------

    def _set_single_user(self, host: str, database: str) -> None:
        """Переводит БД в SINGLE_USER WITH ROLLBACK IMMEDIATE.

        Команда исполняется в контексте master (USE [master]) — пул
        переиспользует соединение, у которого сессионный контекст мог
        остаться на целевой БД (USE [db] от загрузки размеров таблиц),
        из-за чего ALTER DATABASE внутри самой БД отклоняется SQL Server.
        """
        escaped = _escape_bracket(database)

        logger.info(f"{host}: SET SINGLE_USER [{escaped}]")
        self.query(
            host,
            f"USE [master]; "
            f"ALTER DATABASE [{escaped}] "
            f"SET SINGLE_USER WITH ROLLBACK IMMEDIATE",
        )

    def drop_database(self, host: str, database: str) -> None:
        """Переводит БД в SINGLE_USER (отбивает все соединения) и удаляет.

        Использует ``SET SINGLE_USER WITH ROLLBACK IMMEDIATE`` —
        встроенный MSSQL-механизм вместо ручного KILL.  Каждый шаг
        идёт отдельным ``query()``, чтобы пул выдал свежее соединение.
        DDL исполняется из контекста master (см. ``_set_single_user``).
        """
        escaped = _escape_bracket(database)

        self._set_single_user(host, database)

        logger.info(f"{host}: DROP DATABASE [{escaped}]")
        self.query(
            host,
            f"USE [master]; DROP DATABASE [{escaped}]",
        )

    # ----------------------------------------------------------
    # Отсоединение / Присоединение / Восстановление БД
    # ----------------------------------------------------------

    def detach_database(self, host: str, database: str) -> None:
        """Отсоединяет БД: SINGLE_USER → sp_detach_db.

        Файлы БД остаются на сервере. После отсоединения БД можно
        скопировать и присоединить на другом сервере.
        """
        escaped = _escape_bracket(database)

        self._set_single_user(host, database)

        logger.info(f"{host}: sp_detach_db [{escaped}]")
        self.query(
            host,
            f"USE [master]; "
            f"EXEC sp_detach_db N'{escaped}', 'true'",
        )

    def _file_exists(self, host: str, path: str) -> bool:
        """Проверяет существование файла на сервере через xp_fileexist."""
        rows = self.query(
            host,
            "EXEC master..xp_fileexist %s",
            params=(path,),
        )
        if rows and isinstance(rows[0], dict):
            return bool(rows[0].get("File Exists"))
        return False

    def attach_database(
        self,
        host: str,
        database: str,
        mdf_path: str,
    ) -> None:
        """Присоединяет БД из MDF-файла.

        Перед присоединением проверяет существование файла через
        ``xp_fileexist`` — если файл не найден, выбрасывает
        ValueError с понятным сообщением.
        """
        if not self._file_exists(host, mdf_path):
            raise ValueError(
                f"Файл не найден на сервере: {mdf_path}"
            )

        escaped = _escape_bracket(database)

        logger.info(f"{host}: CREATE DATABASE [{escaped}] FOR ATTACH")
        self.query(
            host,
            f"USE [master]; "
            f"CREATE DATABASE [{escaped}] "
            f"ON (FILENAME = N'{mdf_path}') "
            f"FOR ATTACH",
        )

    def restore_database(
        self,
        host: str,
        database: str,
        bak_path: str,
        replace: bool = True,
    ) -> None:
        """Восстанавливает БД из резервной копии (.bak).

        Перед восстановлением проверяет существование .bak через
        ``xp_fileexist``. По умолчанию использует REPLACE
        (перезаписывает существующую БД).
        """
        if not self._file_exists(host, bak_path):
            raise ValueError(
                f"Файл бэкапа не найден на сервере: {bak_path}"
            )

        escaped = _escape_bracket(database)
        with_replace = "REPLACE" if replace else ""

        logger.info(f"{host}: RESTORE DATABASE [{escaped}] FROM DISK = N'{bak_path}'")
        self.query(
            host,
            f"USE [master]; "
            f"RESTORE DATABASE [{escaped}] "
            f"FROM DISK = N'{bak_path}' "
            f"WITH {with_replace}".rstrip(),
        )

    def shrink_log(self, host: str, database: str) -> None:
        """Очищает журнал транзакций БД: SIMPLE → SHRINKFILE → FULL.

        Метод безопасен для production: RECOVERY FULL восстанавливается
        после шринка, даже если SHNINKFILE выбросил исключение.
        """
        escaped = _escape_bracket(database)

        logger.info(f"{host}: shrink log [{escaped}]")
        self.query(
            host,
            f"USE [master]; "
            f"ALTER DATABASE [{escaped}] SET RECOVERY SIMPLE",
        )
        try:
            self.query(
                host,
                f"USE [{escaped}]; DBCC SHRINKFILE(2, 0)",
            )
        finally:
            self.query(
                host,
                f"USE [master]; "
                f"ALTER DATABASE [{escaped}] SET RECOVERY FULL",
            )

    def test_connection(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
    ) -> tuple[bool, str]:
        """Проверка подключения с явными реквизитами (для диалога сервера)."""
        conn = None
        try:
            conn = pymssql.connect(
                server=host,
                port=port,
                user=user,
                password=password,
                login_timeout=self.cfg.connect_timeout,
            )
            return True, ""
        except Exception as ex:
            return False, str(ex)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def server_info(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
    ) -> str:
        """Версия сервера MSSQL (SELECT @@VERSION)."""
        conn = None
        try:
            conn = pymssql.connect(
                server=host,
                port=port,
                user=user,
                password=password,
                login_timeout=self.cfg.connect_timeout,
            )
            cursor = conn.cursor(as_dict=True)
            cursor.execute("SELECT @@VERSION AS v")
            row = cursor.fetchone()
            if row and isinstance(row, dict) and row.get("v"):
                return str(row["v"]).split("\n")[0]
            return ""
        except Exception:
            return ""
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


mssql = MSSQLClient()


if __name__ == "__main__":
    print("MSSQL client loaded.")
