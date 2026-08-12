"""
common/pgsql_client.py

Единая точка работы с PostgreSQL (движок "pgsql").

Соединения обслуживает глобальный пул common/conn_pool.py так же, как
MySQL/MSSQL: пары (host, database) переиспользуют одно соединение между
последовательными запросами из любых потоков.

Драйвер psycopg импортируется лениво (только при фактическом
подключении), поэтому приложение запускается и без установленного
psycopg — ошибка возникнет лишь при попытке подключиться к серверу
PostgreSQL. Для работы с серверами pgsql установите psycopg:

    pip install "psycopg[binary]"

Методы повторяют интерфейс common/mysql_client.py, чтобы воркеры
(check/query/sizes/search) работали с pgsql без изменений: строки
возвращаются как dict (ключ — имя колонки), курсор поддерживает
description/fetchmany/rowcount.
"""

from __future__ import annotations

import atexit
import re
import threading
from contextlib import contextmanager
from typing import Any

from common.config import config
from common.conn_pool import ConnectionPool
from common.logger import logger
from common.server_registry import registry
from common.sql_builder import sql_builder

# Системные БД PostgreSQL — не показываем и не считаем в дереве.
_PG_SYSTEM_DBS = frozenset(
    ("postgres", "template0", "template1"),
)


def _load_psycopg():
    """Ленивый импорт драйвера; выбрасывает понятную ошибку, если
    psycopg не установлен."""
    try:
        import psycopg
        return psycopg
    except ImportError:
        raise RuntimeError(
            "Для работы с PostgreSQL установите драйвер psycopg: "
            'pip install "psycopg[binary]"'
        )


class PgsqlClient:
    def __init__(self, cfg: Any = None) -> None:
        self.cfg = cfg or config.pgsql
        self._query_hook = None
        self._hook_lock = threading.Lock()
        self._pool = ConnectionPool(
            cfg=lambda: self.cfg,
            open_conn=lambda host, db: self._open_connection(host, db),
            alive_check=lambda conn: self._is_alive(conn),
            acquire_timeout=self.cfg.acquire_timeout,
            name="pgsql",
        )
        atexit.register(self.close_all)

    def set_query_hook(self, hook) -> None:
        with self._hook_lock:
            self._query_hook = hook

    def _get_query_hook(self):
        with self._hook_lock:
            return self._query_hook

    # ----------------------------------------------------------
    # Пул соединений
    # ----------------------------------------------------------

    def _open_connection(self, host: str, database: str | None = None):
        """Открывает соединение с ретраями (без пула — «сырой» коннект)."""
        psycopg = _load_psycopg()

        from psycopg.rows import dict_row

        conn = None
        last_error = None

        user, password, port = registry.credentials_for(host)

        for attempt in range(1, self.cfg.retry + 1):
            try:
                conn = psycopg.connect(
                    host=host,
                    port=port,
                    user=user,
                    password=password,
                    dbname=database,
                    connect_timeout=self.cfg.connect_timeout,
                    row_factory=dict_row,
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

        conn._psql_db = database

        return conn

    def _discard_conn(self, conn) -> None:
        try:
            conn.close()
        except Exception:
            pass

    def _is_alive(self, conn) -> bool:
        try:
            if getattr(conn, "closed", False):
                return False
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return True
        except Exception:
            return False

    def _pool_state(self) -> dict:
        return self._pool.debug_state()

    @property
    def _idle_count(self) -> int:
        return self._pool.idle_count

    def _acquire(self, host: str, database: str | None = None):
        return self._pool.acquire(host, database)

    def _release(self, host: str, database: str | None = None, conn=None) -> None:
        if conn is not None:
            self._pool.release(host, database, conn)

    def close_all(self) -> None:
        self._pool.close_all()

    @contextmanager
    def connect(self, host: str, database: str | None = None):
        conn = self._pool.acquire(host, database)

        try:
            yield conn
        finally:
            self._pool.release(host, database, conn)

    def execute_on_connection(
        self,
        conn,
        sql: str,
        params=None,
    ):

        hook = self._get_query_hook()

        if hook is not None:
            hook(
                sql,
                getattr(conn, "host", ""),
            )

        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if cur.description is None:
                    return []
                return cur.fetchall()

        except Exception:
            # У psycopg нет транзиентных кодов как у MySQL — соединение
            # пересоздаётся пулом при следующем acquire (alive_check).
            raise

    # ----------------------------------------------------------
    # Списки БД
    # ----------------------------------------------------------

    def _db_filter_sql(self) -> str:
        system = ", ".join(
            f"'{db}'" for db in sorted(_PG_SYSTEM_DBS)
        )
        ignore = set(config.advanced.ignore_databases)
        extra = ", ".join(f"'{db}'" for db in sorted(ignore))
        if extra:
            system = f"{system}, {extra}"
        return f"datname NOT IN ({system})"

    def list_databases_conn(self, conn) -> list[str]:
        rows = self.execute_on_connection(
            conn,
            "SELECT datname AS db "
            "FROM pg_database "
            f"WHERE {self._db_filter_sql()} "
            "ORDER BY datname",
        )

        prefix = config.filter.database_prefix
        pattern = config.filter.exclude_database_regex

        return [
            row["db"]
            for row in rows
            if (
                row.get("db")
                and row["db"].startswith(prefix)
                and not re.search(pattern, row["db"])
            )
        ]

    def list_databases(self, host: str) -> list[str]:
        """Список БД на сервере с учётом фильтров (prefix/regex/ignore)."""
        with self.connect(host) as conn:
            return self.list_databases_conn(conn)

    def list_all_databases(self, host: str) -> list[str]:
        """Все БД сервера (кроме системных и ignore_databases)."""
        with self.connect(host) as conn:
            rows = self.execute_on_connection(
                conn,
                "SELECT datname AS db FROM pg_database "
                f"WHERE {self._db_filter_sql()} ORDER BY datname",
            )

        return [
            row["db"]
            for row in rows
            if row.get("db")
        ]

    def search_databases(self, host: str, mask: str) -> list[str]:
        mask = mask.strip()

        if not mask:
            return []

        like = mask.replace("_", r"\_").replace("%", r"\%")
        pattern = f"%{like}%"

        with self.connect(host) as conn:
            rows = self.execute_on_connection(
                conn,
                "SELECT datname AS db FROM pg_database "
                "WHERE datname ILIKE %s "
                f"AND {self._db_filter_sql()} ORDER BY datname",
                (pattern,),
            )

        return [
            row["db"]
            for row in rows
            if row.get("db")
        ]

    # ----------------------------------------------------------
    # Проверка соединения (диалог сервера)
    # ----------------------------------------------------------

    def test_connection(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
    ) -> tuple[bool, str]:
        """Проверка подключения с явными реквизитами."""
        try:
            psycopg = _load_psycopg()
            conn = psycopg.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                connect_timeout=self.cfg.connect_timeout,
            )
            conn.close()
        except Exception as ex:
            return False, str(ex)

        return True, ""

    # ----------------------------------------------------------
    # Размеры БД и таблиц
    # ----------------------------------------------------------

    def _pid(self, conn) -> int | None:
        try:
            pgconn = getattr(conn, "pgconn", None)
            if pgconn is not None:
                return pgconn.backend_pid
        except Exception:
            pass
        try:
            return conn.get_backend_pid()
        except Exception:
            return None

    def connection_id(self, conn) -> int | None:
        return self._pid(conn)

    def kill_connection(self, host: str, connection_id: int) -> None:
        with self.connect(host) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_terminate_backend(%s)",
                    (int(connection_id),),
                )

    def server_catalog(
        self,
        host: str,
    ) -> tuple[dict[str, int], dict[str, list[tuple[str, int]]]]:
        """Размеры всех БД и полный список таблиц сервера.

        Возвращает (sizes, tables):
          sizes — {db: суммарный размер в байтах};
          tables — {db: [(table_name, размер в байтах)]} по убыванию размера.
        """
        sql = """
SELECT
    d.datname AS db,
    pg_database_size(d.datname) AS db_size,
    t.schemaname AS schema_name,
    t.tablename AS table_name,
    pg_total_relation_size(
        quote_ident(t.schemaname) || '.' || quote_ident(t.tablename)
    ) AS total
FROM pg_database d
LEFT JOIN pg_tables t
    ON t.schemaname NOT IN ('pg_catalog', 'information_schema')
WHERE d.datallowconn = true
ORDER BY d.datname, total DESC
"""
        rows = self.query(host, sql)

        sizes: dict[str, int] = {}
        tables: dict[str, list[tuple[str, int]]] = {}

        for row in rows:
            db = row.get("db")
            if not db or db in _PG_SYSTEM_DBS:
                continue

            db_size = int(row.get("db_size") or 0)
            sizes[db] = db_size

            table_name = row.get("table_name")
            size = int(row.get("total") or 0)
            if table_name:
                schema = row.get("schema_name") or "public"
                label = f"{schema}.{table_name}" if schema != "public" else table_name
                tables.setdefault(db, []).append((label, size))

        return sizes, tables

    def database_sizes(self, host: str) -> dict[str, int]:
        sql = """
SELECT
    datname AS db,
    pg_database_size(datname) AS total
FROM pg_database
WHERE datallowconn = true
ORDER BY datname
"""
        rows = self.query(host, sql)

        return {
            row["db"]: int(row["total"] or 0)
            for row in rows
            if row.get("db") and row["db"] not in _PG_SYSTEM_DBS
        }

    def database_table_sizes(
        self,
        host: str,
        database: str,
    ) -> list[tuple[str, int]]:
        sql = """
SELECT
    schemaname AS schema_name,
    tablename AS table_name,
    pg_total_relation_size(
        quote_ident(schemaname) || '.' || quote_ident(tablename)
    ) AS total
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY total DESC
"""
        rows = self.query(host, sql, database)

        out = []
        for row in rows:
            table_name = row.get("table_name")
            if not table_name:
                continue
            schema = row.get("schema_name") or "public"
            label = f"{schema}.{table_name}" if schema != "public" else table_name
            out.append((label, int(row.get("total") or 0)))

        return out

    # ----------------------------------------------------------
    # Прочие методы (совместимость интерфейса)
    # ----------------------------------------------------------

    def scan_settings_batch(self, conn, databases):
        return []

    def get_settings_conn(self, conn, database):
        return {}

    def query(self, host: str, sql: str, database: str | None = None,
              params: tuple[Any, ...] | None = None) -> list[dict]:
        with self.connect(host, database) as conn:
            return self.execute_on_connection(conn, sql, params)

    def has_cfg_settings_conn(self, conn, database: str) -> bool:
        return False

    def has_cfg_settings(self, host: str, database: str) -> bool:
        return False

    def get_settings(self, host: str, database: str) -> dict[str, str]:
        return {}

    def filter_databases_with_settings_conn(self, conn, databases):
        return databases


pgsql = PgsqlClient()


if __name__ == "__main__":
    print("PostgreSQL client loaded.")