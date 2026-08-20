"""
common/mysql_client.py

Единая точка работы с MySQL.

Соединения обслуживает глобальный пул common/conn_pool.py: пары
(host, database) переиспользуют одно соединение между последовательными
запросами из любых потоков, а idle-кэш ограничен (pool_idle /
max_idle_connections / idle_timeout). Это исключает размножение
коннектов при параллельном батчинге, поиске размеров и мульти-запросах.

Ограничения (config.ini [mysql]):
  - max_connections     — потолок одновременно занятых соединений;
  - max_per_key         — максимум одновременных соединений к одной паре;
  - acquire_timeout     — ожидание свободного соединения в пуле.

Разорванные соединения пересоздаются, транзиентные ошибки
(2006/2013/1927/1053) повторяются один раз на свежем соединении.
"""

from __future__ import annotations

import atexit
import re
import threading
import time
from contextlib import contextmanager
from typing import Any

import pymysql
from pymysql.cursors import DictCursor
from pymysql.err import OperationalError

from common.config import config
from common.conn_pool import ConnectionPool
from common.logger import logger
from common.server_registry import registry
from common.sql_builder import sql_builder

# Коды ошибок, означающих разрыв/невалидность соединения —
# после них запрос безопасно повторить на свежем соединении.
_RETRY_ERRNOS = {2006, 2013, 1927, 1053}


def _is_transient(ex: Exception) -> bool:
    if isinstance(ex, OperationalError) and ex.args:
        code = ex.args[0]
        if isinstance(code, int):
            return code in _RETRY_ERRNOS
    return False


class MySQLClient:
    _UPDATE_TIMES_TTL = 300  # 5 минут кэш update_times

    def __init__(self, cfg: Any = None) -> None:
        self.cfg = cfg or config.mysql
        self._query_hook = None
        self._hook_lock = threading.Lock()
        self._update_times_cache: dict[str, tuple[float, dict]] = {}
        self._pool = ConnectionPool(
            cfg=lambda: self.cfg,
            open_conn=lambda host, db: self._open_connection(host, db),
            alive_check=lambda conn: self._is_alive(conn),
            acquire_timeout=self.cfg.acquire_timeout,
            name="mysql",
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
        conn = None
        last_error = None

        user, password, port = registry.credentials_for(host)

        for attempt in range(1, self.cfg.retry + 1):
            try:
                conn = pymysql.connect(
                    host=host,
                    port=port,
                    user=user,
                    password=password,
                    database=database,
                    connect_timeout=self.cfg.connect_timeout,
                    read_timeout=self.cfg.read_timeout,
                    write_timeout=self.cfg.write_timeout,
                    cursorclass=DictCursor,
                    autocommit=True,
                    charset="utf8mb4",
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
            conn.ping(reconnect=False)
            return True
        except Exception:
            return False

    def _pool_state(self) -> dict:
        """Снимок пула для тестов."""
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
        """Закрывает все соединения пула (для CLI и завершения)."""
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

                cur.execute(
                    sql,
                    params,
                )

                return cur.fetchall()

        except OperationalError as ex:
            if not _is_transient(ex):
                raise

            # Соединение разорвалось во время выполнения — повторяем
            # запрос один раз на свежем соединении.
            host = getattr(conn, "host", None)

            if not host:
                raise

            logger.warning(
                f"{host}: соединение разорвано ({ex}), повтор запроса"
            )

            new_conn = self._open_connection(
                host,
                getattr(conn, "_psql_db", None),
            )

            try:
                with new_conn.cursor() as cur:
                    cur.execute(sql, params)
                    return cur.fetchall()
            finally:
                self._discard_conn(new_conn)

    def list_databases_conn(
        self,
        conn,
    ):

        rows = self.execute_on_connection(
            conn,
            "SHOW DATABASES",
        )

        ignore = set(
            config.advanced.ignore_databases
        )

        prefix = config.filter.database_prefix
        pattern = config.filter.exclude_database_regex

        return [
            db
            for row in rows
            for db in row.values()
            if (
                db not in ignore
                and db.startswith(prefix)
                and not re.search(pattern, db)
            )
        ]

    def scan_settings_batch(
        self,
        conn,
        databases,
    ):

        rows = []

        for sql in sql_builder.build_scan_query(databases):
            rows.extend(
                self.execute_on_connection(
                    conn,
                    sql,
                )
            )

        return rows

    def get_settings_conn(
        self,
        conn,
        database,
    ):

        sql = f"""
    SELECT
        stg_name,
        stg_value
    FROM {sql_builder.quote_identifier(database)}.{sql_builder.quote_identifier(config.advanced.settings_table)}
    WHERE stg_name IN (%s,%s)
    """

        rows = self.execute_on_connection(
            conn,
            sql,
            (
                config.filter.country_setting,
                config.filter.target_setting,
            ),
        )

        return {
            r["stg_name"]: r["stg_value"]
            for r in rows
        }

    def query(self, host: str, sql: str, database: str | None = None,
              params: tuple[Any, ...] | None = None) -> list[dict]:
        with self.connect(host, database) as conn:
            return self.execute_on_connection(conn, sql, params)

    def list_databases(self, host: str) -> list[str]:
        """Список БД на сервере с учётом фильтров (prefix/regex/ignore)."""
        with self.connect(host) as conn:
            return self.list_databases_conn(conn)

    def list_all_databases(self, host: str) -> list[str]:
        """Все БД сервера (кроме системных из ignore_databases).

        Быстрый SHOW DATABASES — используется для мгновенного показа
        списка БД при раскрытии сервера (размеры подгружаются отдельно).
        """
        with self.connect(host) as conn:
            rows = self.execute_on_connection(conn, "SHOW DATABASES")

        ignore = set(config.advanced.ignore_databases)

        return sorted(
            db
            for row in rows
            for db in row.values()
            if db not in ignore
        )

    def edit_meta(self, host: str, database: str, table: str):
        """(первичные ключи, все колонки) таблицы для редактирования ячеек.

        Оба запроса идут на одном соединении из пула.
        """
        with self.connect(host, database) as conn:
            pk = self.execute_on_connection(
                conn,
                "SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
                "AND CONSTRAINT_NAME = 'PRIMARY' ORDER BY ORDINAL_POSITION",
                (database, table),
            )
            cols = self.execute_on_connection(
                conn,
                "SELECT COLUMN_NAME FROM information_schema.columns "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
                "ORDER BY ORDINAL_POSITION",
                (database, table),
            )

        return (
            [row["COLUMN_NAME"] for row in pk],
            [row["COLUMN_NAME"] for row in cols],
        )

    def search_databases(self, host: str, mask: str) -> list[str]:
        """Поиск БД по маске в стиле LIKE (например 'ar_%45').

        MySQL не поддерживает плейсхолдеры в `SHOW DATABASES LIKE`,
        поэтому маска экранируется через conn.escape() и подставляется
        вручную. Никаких дополнительных фильтров (prefix/regex/ignore)
        не применяется — маску задаёт пользователь явно.

        Если маска похожа на домен (содержит точку), дополнительно ищет
        БД через Plesk `psa`: связку data_bases.dom_id -> domains.name.
        Запрос выполняется на том же соединении, что и SHOW DATABASES,
        поэтому новых коннектов не открывается. При недоступности psa
        поиск тихо откатывается к результатам по имени БД.
        """
        mask = mask.strip()

        if not mask:
            return []

        with self.connect(host) as conn:
            escaped = conn.escape(mask)

            rows = self.execute_on_connection(
                conn,
                f"SHOW DATABASES LIKE {escaped}",
            )

            found = [
                db
                for row in rows
                for db in row.values()
            ]

            if "." in mask:
                found.extend(
                    self._search_databases_by_domain_conn(conn, mask)
                )

        seen: set[str] = set()
        return [db for db in found if not (db in seen or seen.add(db))]

    def database_update_times(
        self, host: str, databases: list[str]
    ) -> dict[str, str]:
        """БД, обновлённые за сегодня, для списка БД на сервере.

        Один запрос к information_schema.tables с фильтром CURDATE()
        — lightweight метаданные. Результат кэшируется 5 минут, чтобы
        не нагружать MySQL повторными запросами.

        Возвращает {db_name: 'YYYY-MM-DD HH:MM:SS'}.
        При ошибке — тихо возвращает пустой dict (маркер не ставится).
        """
        if not databases:
            return {}

        cache_key = f"{host}:{','.join(sorted(databases))}"
        now = time.time()
        cached = self._update_times_cache.get(cache_key)
        if cached and now - cached[0] < self._UPDATE_TIMES_TTL:
            return cached[1]

        try:
            placeholders = ", ".join(["%s"] * len(databases))
            sql = (
                "SELECT table_schema AS db, "
                "MAX(update_time) AS last_update "
                "FROM information_schema.tables "
                f"WHERE table_schema IN ({placeholders}) "
                "AND update_time IS NOT NULL "
                "AND update_time >= CURDATE() "
                "GROUP BY table_schema"
            )
            rows = self.query(host, sql, params=tuple(databases))
            result = {
                row["db"]: str(row.get("last_update") or "")
                for row in rows
                if row.get("db")
            }
            self._update_times_cache[cache_key] = (now, result)
            return result
        except Exception as ex:
            logger.warning(
                f"{host}: database_update_times failed ({ex}), "
                f"working DB detection disabled for this server"
            )
            return {}

    def _search_databases_by_domain_conn(
        self,
        conn,
        mask: str,
    ) -> list[str]:
        """Ищет БД по домену/адресу сайта через Plesk psa.

        Возвращает имена БД, чей домен (psa.domains.name) совпадает
        с маской. Выполняется на переданном соединении; при отсутствии
        доступа к psa логирует предупреждение и возвращает пустой список.
        """
        pattern = mask

        if "%" not in pattern:
            pattern = f"%{pattern}%"

        escaped = conn.escape(pattern)

        try:
            rows = self.execute_on_connection(
                conn,
                "SELECT db.name AS db_name "
                "FROM psa.data_bases db "
                "JOIN psa.domains d ON d.id = db.dom_id "
                "WHERE db.type = 'mysql' "
                f"AND d.name LIKE {escaped}",
            )
        except Exception as ex:
            logger.warning(
                f"{getattr(conn, 'host', '?')}: поиск по домену "
                f"недоступен (psa) — {ex}"
            )
            return []

        return [
            row["db_name"]
            for row in rows
            if row.get("db_name")
        ]

    def has_cfg_settings_conn(self, conn, database: str) -> bool:
        rows = self.execute_on_connection(
            conn,
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = %s LIMIT 1",
            (database, config.advanced.settings_table),
        )
        return bool(rows)

    def filter_databases_with_settings_conn(
        self,
        conn,
        databases: list[str],
    ) -> list[str]:
        """Оставляет БД, в которых есть таблица настроек.

        Один запрос на чанк (вместо отдельного запроса на каждую БД),
        что резко сокращает число обращений к серверу для больших списков.
        """
        if not databases:
            return []

        settings_table = config.advanced.settings_table
        found = set()

        for chunk in sql_builder.chunk(list(databases), 200):
            placeholders = ", ".join(["%s"] * len(chunk))

            rows = self.execute_on_connection(
                conn,
                "SELECT DISTINCT table_schema "
                "FROM information_schema.tables "
                "WHERE table_name = %s "
                f"AND table_schema IN ({placeholders})",
                (settings_table, *chunk),
            )

            found.update(
                row["table_schema"]
                for row in rows
            )

        return [db for db in databases if db in found]

    def has_cfg_settings(self, host: str, database: str) -> bool:
        with self.connect(host, database) as conn:
            return self.has_cfg_settings_conn(conn, database)

    def get_settings(self, host: str, database: str) -> dict[str, str]:
        """Возвращает country/target настройки БД по открытому соединению."""
        with self.connect(host, database) as conn:
            return self.get_settings_conn(conn, database)

    # ----------------------------------------------------------
    # Размеры БД и таблиц
    # ----------------------------------------------------------

    def kill_connection(self, host: str, connection_id: int) -> None:
        """Прерывает запрос на сервере через KILL (отдельным соединением)."""
        with self.connect(host) as conn:
            with conn.cursor() as cur:
                cur.execute(f"KILL {int(connection_id)}")

    def connection_id(self, conn) -> int | None:
        """Идентификатор соединения для прерывания активного запроса."""
        try:
            return conn.thread_id()
        except Exception:
            return None

    def test_connection(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
    ) -> tuple[bool, str]:
        """Проверка подключения с явными реквизитами (для диалога сервера)."""
        try:
            conn = pymysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                connect_timeout=self.cfg.connect_timeout,
                cursorclass=DictCursor,
                autocommit=True,
                charset="utf8mb4",
            )
            conn.close()
        except Exception as ex:
            return False, str(ex)

        return True, ""

    def server_catalog(
        self,
        host: str,
    ) -> tuple[dict[str, int], dict[str, list[tuple[str, int]]]]:
        """Размеры всех БД и полный список таблиц сервера одним запросом.

        Возвращает (sizes, tables):
          sizes — {db: суммарный размер в байтах};
          tables — {db: [(table_name, размер в байтах)]} по убыванию размера.

        Используется при раскрытии сервера, чтобы показывать таблицы
        мгновенно (без отдельного запроса на каждую БД).
        """
        sql = """
SELECT
    table_schema AS db,
    table_name AS table_name,
    (data_length + index_length) AS total
FROM information_schema.tables
WHERE table_schema NOT IN ('information_schema', 'performance_schema', 'mysql', 'sys')
ORDER BY table_schema, total DESC
"""
        rows = self.query(host, sql)

        sizes: dict[str, int] = {}
        tables: dict[str, list[tuple[str, int]]] = {}

        for row in rows:
            db = row.get("db")
            if not db:
                continue

            size = int(row.get("total") or 0)
            sizes[db] = sizes.get(db, 0) + size

            table_name = row.get("table_name")
            if table_name:
                tables.setdefault(db, []).append((table_name, size))

        return sizes, tables

    def database_sizes(self, host: str) -> dict[str, int]:
        """Суммарный размер (в байтах) по каждой БД на сервере.

        Запрос читает статистику information_schema и не требует
        полного доступа к данным.
        """
        sql = """
SELECT
    table_schema AS db,
    SUM(data_length + index_length) AS total
FROM information_schema.tables
WHERE table_schema NOT IN ('information_schema', 'performance_schema', 'mysql', 'sys')
GROUP BY table_schema
ORDER BY table_schema
"""
        rows = self.query(host, sql)

        return {
            row["db"]: int(row["total"] or 0)
            for row in rows
            if row.get("db")
        }

    def database_table_sizes(
        self,
        host: str,
        database: str,
    ) -> list[tuple[str, int]]:
        """Список (таблица, размер в байтах) для одной БД.

        Соединение открывается без default-схемы (ключ пула (host, None)),
        поэтому последовательные вызовы для разных БД сервера
        переиспользуют одно и то же соединение.
        """
        sql = f"""
SELECT
    table_name AS table_name,
    (data_length + index_length) AS total
FROM information_schema.tables
WHERE table_schema = %s
ORDER BY total DESC
"""
        rows = self.query(host, sql, None, (database,))

        return [
            (row["table_name"], int(row["total"] or 0))
            for row in rows
            if row.get("table_name")
        ]


mysql = MySQLClient()


if __name__ == "__main__":
    print("MySQL client loaded.")
