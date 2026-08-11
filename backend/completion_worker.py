"""
backend/completion_worker.py

Фоновый сбор метаданных (таблицы и колонки текущей БД) для
автодополнения в SQL Console.

Оптимизация соединений:
  - Оба запроса (таблицы + колонки) выполняются на одном соединении
    из глобального пула (client.connect один раз, release один раз) —
    никаких «сырых» коннектов;
  - результат кэшируется в MainWindow по паре (host, database), поэтому
    на каждое нажатие клавиши сеть не дёргается;
  - запросы идут только на выбранную БД, а число прочитанных колонок
    ограничено, чтобы не держать соединение пула на огромных БД.

Запросы используют information_schema, который есть и в MySQL, и в MSSQL.
Ветвится только фильтр по схеме: в MySQL это имя БД (table_schema),
в MSSQL — контекст подключения (схема не нужна).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from common.logger import logger
from common.server_registry import client_for, registry, ENGINE_MSSQL

# Ограничение числа строк колонок: защита от гигантских БД
# (обычно 1 строка = 1 колонка). Дальше считаем каталог «достаточным».
MAX_COLUMN_ROWS = 30000


def build_metadata_queries(
    host: str,
    database: str,
) -> tuple[list[tuple[str, str, tuple | None]], str]:
    """Собирает (sql, engine) для запроса таблиц и колонок.

    Возвращает (запросы, движок). Каждый запрос — (label, sql, params).
    Вынесено отдельно от run(), чтобы покрывать тестами без БД.
    """
    if registry.engine(host) == ENGINE_MSSQL:
        # MSSQL: подключение уже в контексте выбранной БД, фильтр по
        # схеме не нужен — иначе (dbo) потеряем таблицы других схем.
        tables_sql = (
            "SELECT TABLE_NAME FROM information_schema.tables "
            "WHERE TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME"
        )
        columns_sql = (
            "SELECT TABLE_NAME, COLUMN_NAME "
            "FROM information_schema.columns "
            "ORDER BY TABLE_NAME, ORDINAL_POSITION"
        )
        return [
            ("tables", tables_sql, None),
            ("columns", columns_sql, None),
        ], "mssql"

    # MySQL: информация лежит в information_schema, фильтруем по имени БД.
    tables_sql = (
        "SELECT TABLE_NAME FROM information_schema.tables "
        "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' "
        "ORDER BY TABLE_NAME"
    )
    columns_sql = (
        "SELECT TABLE_NAME, COLUMN_NAME "
        "FROM information_schema.columns "
        "WHERE TABLE_SCHEMA = %s "
        "ORDER BY TABLE_NAME, ORDINAL_POSITION"
    )
    return [
        ("tables", tables_sql, (database,)),
        ("columns", columns_sql, (database,)),
    ], "mysql"


def parse_catalog(
    tables_rows: list[dict],
    columns_rows: list[dict],
) -> tuple[list[str], dict[str, list[str]]]:
    """Превращает строки information_schema в (таблицы, {таблица: [колонки]})."""
    tables = sorted({str(r["TABLE_NAME"]) for r in tables_rows})

    columns: dict[str, list[str]] = {}
    for row in columns_rows:
        table = str(row["TABLE_NAME"])
        column = str(row["COLUMN_NAME"])
        columns.setdefault(table, []).append(column)
    for names in columns.values():
        names.sort()

    return tables, columns


class CompletionWorker(QObject):
    started = Signal()
    finished = Signal()
    catalog_ready = Signal(str, str, list, dict)   # host, database, tables, columns
    error = Signal(str, str, str)                  # host, database, message

    def __init__(self):
        super().__init__()
        self._host = ""
        self._database = None

    def set_request(self, host: str, database: str) -> None:
        self._host = host
        self._database = database

    def stop(self) -> None:
        """Заглушка для единообразного завершения фоновых потоков."""

    @Slot()
    def run(self):
        """Точка входа потока. Исключения не покидают слот."""
        self.started.emit()
        try:
            self._dispatch()
        except Exception as ex:
            logger.exception(ex)
            self.error.emit(self._host, self._database or "", str(ex))
        finally:
            self.finished.emit()

    def _dispatch(self) -> None:
        host = self._host
        database = self._database

        if not host or not database:
            self.error.emit(host, database or "", "Не выбран сервер или БД.")
            return

        queries, engine = build_metadata_queries(host, database)

        client = client_for(host)

        # Оптимизация: один acquire из пула на оба запроса.
        with client.connect(host, database) as conn:
            tables_rows: list[dict] = []
            columns_rows: list[dict] = []

            for label, sql, params in queries:
                rows = client.execute_on_connection(conn, sql, params)
                if label == "tables":
                    tables_rows = rows or []
                elif label == "columns":
                    columns_rows = (rows or [])[:MAX_COLUMN_ROWS]
                    if len(rows) > MAX_COLUMN_ROWS:
                        logger.warning(
                            f"{host}/{database}: колонок больше "
                            f"{MAX_COLUMN_ROWS}, каталог усечён"
                        )

        tables, columns = parse_catalog(tables_rows, columns_rows)
        logger.info(
            f"Completion catalog {host}/{database}: "
            f"{len(tables)} таблиц, {sum(len(v) for v in columns.values())} колонок "
            f"(engine={engine})"
        )
        self.catalog_ready.emit(host, database, tables, columns)
