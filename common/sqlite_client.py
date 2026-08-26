"""
common/sqlite_client.py

Единая точка работы с SQLite.

Каждый «сервер» — это путь к файлу .db. Один файл = одна БД.
Соединения обслуживаются глобальным пулом common/conn_pool.py.
"""

from __future__ import annotations

import atexit
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any

from common.config import config
from common.conn_pool import ConnectionPool
from common.logger import logger
from common.server_registry import registry


class SQLiteClient:
    def __init__(self, cfg: Any = None) -> None:
        self.cfg = cfg or config.sqlite
        self._pool = ConnectionPool(
            cfg=lambda: self.cfg,
            open_conn=lambda host, db: self._open_connection(host, db),
            alive_check=lambda conn: self._is_alive(conn),
            acquire_timeout=self.cfg.acquire_timeout,
            name="sqlite",
        )
        self._meta: dict[int, dict] = {}
        self._meta_lock = threading.Lock()
        atexit.register(self.close_all)

    # ----------------------------------------------------------
    # Пул соединений
    # ----------------------------------------------------------

    def _open_connection(self, host: str, database: str | None = None):
        db_path = host
        conn = None
        last_error = None

        for attempt in range(1, self.cfg.retry + 1):
            try:
                conn = sqlite3.connect(
                    db_path,
                    timeout=self.cfg.connect_timeout,
                )
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=5000")
                break
            except Exception as ex:
                last_error = ex
                logger.warning(
                    f"{db_path}: попытка {attempt}/{self.cfg.retry} "
                    f"подключения не удалась ({ex})"
                )
                if attempt < self.cfg.retry:
                    import time
                    time.sleep(1)

        if conn is None:
            raise RuntimeError(
                f"Не удалось открыть {db_path}: {last_error}"
            )

        self._meta_set(conn, host=db_path)

        return conn

    def _is_alive(self, conn) -> bool:
        try:
            conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def _meta_set(self, conn, **kw) -> None:
        with self._meta_lock:
            self._meta[id(conn)] = kw

    def _meta_get(self, conn, key: str, default=None):
        with self._meta_lock:
            return self._meta.get(id(conn), {}).get(key, default)

    def close_all(self) -> None:
        self._pool.close_all()

    @contextmanager
    def connect(self, host: str, database: str | None = None):
        conn = self._pool.acquire(host, database)
        try:
            yield conn
        finally:
            self._pool.release(host, database, conn)

    # ----------------------------------------------------------
    # Выполнение запросов
    # ----------------------------------------------------------

    def execute_on_connection(self, conn, sql: str, params=None):
        try:
            cur = conn.execute(sql, params or ())
            if cur.description:
                rows = cur.fetchall()
                return [dict(row) for row in rows]
            conn.commit()
            return []
        except Exception:
            conn.rollback()
            raise

    def query(
        self,
        host: str,
        sql: str,
        database: str | None = None,
        params: tuple[Any, ...] | None = None,
    ) -> list[dict]:
        with self.connect(host, database) as conn:
            return self.execute_on_connection(conn, sql, params)

    # ----------------------------------------------------------
    # Список БД (один .db файл = одна БД)
    # ----------------------------------------------------------

    def list_databases(self, host: str) -> list[str]:
        db_path = host
        if not os.path.isfile(db_path):
            return []
        return [os.path.basename(db_path)]

    def list_all_databases(self, host: str) -> list[str]:
        return self.list_databases(host)

    # ----------------------------------------------------------
    # Таблицы
    # ----------------------------------------------------------

    def tables(self, host: str, database: str) -> list[str]:
        rows = self.query(
            host,
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name",
        )
        return [row["name"] for row in rows]

    def columns(
        self,
        host: str,
        database: str,
        table: str,
    ) -> list[dict]:
        rows = self.query(host, f"PRAGMA table_info({table})")
        return rows

    def describe_table(
        self,
        host: str,
        database: str,
        table: str,
    ) -> list[dict]:
        cols = self.columns(host, database, table)
        count_rows = self.query(
            host,
            f"SELECT COUNT(*) AS cnt FROM {table}",
        )
        count = count_rows[0]["cnt"] if count_rows else 0
        return {
            "columns": cols,
            "row_count": count,
        }

    # ----------------------------------------------------------
    # Мета-данные для редактирования
    # ----------------------------------------------------------

    def edit_meta(
        self,
        host: str,
        database: str,
        table: str,
        conn=None,
    ):
        own = conn is None
        if own:
            conn = self.connect(host, database).__enter__()
        try:
            pk_rows = self.execute_on_connection(
                conn,
                "SELECT name FROM pragma_table_info(?) WHERE pk > 0 "
                "ORDER BY cid",
                (table,),
            )
            col_rows = self.execute_on_connection(
                conn,
                "SELECT name FROM pragma_table_info(?) ORDER BY cid",
                (table,),
            )
        finally:
            if own:
                conn.__exit__(None, None, None)

        return (
            [row["name"] for row in pk_rows],
            [row["name"] for row in col_rows],
        )

    # ----------------------------------------------------------
    # Размеры
    # ----------------------------------------------------------

    def database_sizes(self, host: str) -> dict[str, int]:
        db_path = host
        if not os.path.isfile(db_path):
            return {}
        return {os.path.basename(db_path): os.path.getsize(db_path)}

    def database_table_sizes(
        self,
        host: str,
        database: str,
    ) -> list[tuple[str, int]]:
        table_names = self.tables(host, database)
        result: list[tuple[str, int]] = []
        for name in table_names:
            try:
                rows = self.query(
                    host,
                    f"SELECT SUM(pgsize) AS total "
                    f"FROM dbstat WHERE name=?",
                    params=(name,),
                )
                total = rows[0]["total"] if rows else 0
                result.append((name, int(total or 0)))
            except Exception:
                result.append((name, 0))
        return sorted(result, key=lambda x: x[1], reverse=True)

    def server_catalog(
        self,
        host: str,
    ) -> tuple[dict[str, int], dict[str, list[tuple[str, int]]]]:
        sizes = self.database_sizes(host)
        tables: dict[str, list[tuple[str, int]]] = {}
        for db_name in sizes:
            tables[db_name] = self.database_table_sizes(host, db_name)
        return sizes, tables

    # ----------------------------------------------------------
    # Удаление БД
    # ----------------------------------------------------------

    def drop_database(self, host: str, database: str) -> None:
        db_path = host
        if os.path.isfile(db_path):
            self.close_all()
            os.remove(db_path)

    # ----------------------------------------------------------
    # Тест подключения / Информация
    # ----------------------------------------------------------

    def test_connection(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
    ) -> tuple[bool, str]:
        try:
            conn = sqlite3.connect(host, timeout=5)
            conn.execute("SELECT 1")
            conn.close()
        except Exception as ex:
            return False, str(ex)
        return True, ""

    def server_info(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
    ) -> str:
        return f"SQLite {sqlite3.sqlite_version}"

    # ----------------------------------------------------------
    # Прерывание запросов (не применимо к SQLite)
    # ----------------------------------------------------------

    def kill_connection(self, host: str, connection_id: int) -> None:
        raise NotImplementedError("SQLite не поддерживает KILL запросов")

    def connection_id(self, conn) -> int | None:
        return None

    # ----------------------------------------------------------
    # Stub-методы для совместимости с интерфейсом
    # ----------------------------------------------------------

    def search_databases(
        self, host: str, mask: str
    ) -> list[str]:
        return []

    def scan_settings_batch(self, conn, databases) -> list:
        return []

    def get_settings_conn(self, conn, database) -> dict:
        return {}

    def has_cfg_settings_conn(self, conn, database: str) -> bool:
        return False

    def has_cfg_settings(self, host: str, database: str) -> bool:
        return False

    def get_settings(self, host: str, database: str) -> dict[str, str]:
        return {}

    def filter_databases_with_settings_conn(
        self, conn, databases: list[str]
    ) -> list[str]:
        return list(databases)


sqlite = SQLiteClient()
