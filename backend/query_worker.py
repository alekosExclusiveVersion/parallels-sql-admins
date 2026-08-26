"""
backend/query_worker.py

Выполнение произвольных SQL-запросов в фоновом потоке
для SQL Console.

Скрипт разбивается на отдельные операторы (common.sql_splitter),
и каждый выполняется последовательно на одном соединении. Результаты
агрегируются: первый оператор с результирующим набором задаёт колонки,
строки операторов с такими же колонками конкатенируются, операторы без
результата (INSERT/UPDATE/...) добавляют строки статуса. Операторы
с отличающимися колонками пропускаются и учитываются в сообщении.
"""

from __future__ import annotations

import csv
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal, Slot

from common.config import config
from common.logger import logger
from common.server_registry import client_for
from common.sql_editing import parse_select_table
from common.sql_splitter import split_statements


ALL_DATABASES = "*"


class QueryWorker(QObject):
    started = Signal()
    finished = Signal()
    query = Signal(str)
    result = Signal(list, list, str)
    error = Signal(str)
    databases = Signal(list)

    # Метаданные таблицы для редактирования ячеек Results:
    # host, database, table, первичные ключи, колонки.
    edit_meta = Signal(str, str, str, list, list)

    started_target = Signal(int, int, str, str)
    result_target = Signal(str, str, list, list, str)
    error_target = Signal(str, str, str)
    stopped = Signal(int, int)
    export_done = Signal(int, str)   # всего строк, путь к файлу

    def __init__(self):
        super().__init__()
        self._host = ""
        self._database = None
        self._sql = ""
        self._row_limit = 1000
        self._mode = "query"
        self._targets = []
        self._statements = []
        self._filepath = ""
        self._stop = False
        self._table_hint: str | None = None
        self._active_lock = threading.Lock()
        self._active_conns: dict[int, tuple[str, int]] = {}

    def set_request(self, host, database, sql, row_limit=1000):
        self._host = host
        self._database = database or None
        self._sql = sql
        self._statements = split_statements(sql or "")
        self._row_limit = row_limit
        self._mode = "query"
        self._stop = False
        self._table_hint = None
        self._reset_active()

    def set_databases_request(self, host):
        self._host = host
        self._database = None
        self._sql = ""
        self._statements = []
        self._mode = "databases"
        self._stop = False
        self._reset_active()

    def set_multi_request(self, targets, sql, row_limit=1000, table=None):
        self._targets = list(targets)
        self._sql = sql
        self._statements = split_statements(sql or "")
        self._row_limit = row_limit
        self._mode = "multi"
        self._stop = False
        # Хинт таблицы для просмотра из дерева серверов: SQL использует
        # квалифицированное имя (db.table), которое parse_select_table
        # не разбирает — метаданные берём напрямую.
        self._table_hint = table
        self._reset_active()

    def set_export_request(self, targets, sql, filepath):
        """Повторный запуск последнего запроса без лимита строк.

        Результаты пишутся напрямую в CSV батчами (без накопления в памяти).
        Разрешено только для чтения (SELECT): записывающие операторы
        не перезапускаются.
        """
        self._targets = list(targets)
        self._sql = sql
        self._statements = split_statements(sql or "")
        self._filepath = filepath
        self._mode = "export"
        self._stop = False
        self._table_hint = None
        self._reset_active()

    def stop(self):
        self._stop = True

    def _reset_active(self):
        with self._active_lock:
            self._active_conns.clear()

    def active_connections(self):
        """Список (host, connection_id) выполняющихся запросов."""
        with self._active_lock:
            return list(self._active_conns.values())

    def _register_active(self, host: str, conn_id) -> None:
        if conn_id is None:
            return
        with self._active_lock:
            self._active_conns[threading.get_ident()] = (host, conn_id)

    def _unregister_active(self) -> None:
        with self._active_lock:
            self._active_conns.pop(threading.get_ident(), None)

    def kill_active(self):
        """Прерывает все выполняющиеся запросы через KILL <connection_id>.

        Запускать в фоновом потоке: открывает отдельное соединение на
        каждый активный хост, поэтому сам по себе может блокироваться.
        """
        for host, conn_id in self.active_connections():
            try:
                client_for(host).kill_connection(host, conn_id)
            except Exception as ex:
                logger.warning(f"KILL {host}/{conn_id} failed: {ex}")

    def _execute_statement(
        self,
        conn,
        statement: str,
        row_limit: int,
    ) -> tuple[list[list[str]], list[str], str]:
        """Выполняет один оператор и возвращает (rows, columns, message)."""
        with conn.cursor() as cur:
            cur.execute(statement)

            if cur.description is not None:
                columns = [d[0] for d in cur.description]
                rows = list(cur.fetchmany(row_limit + 1))
                truncated = len(rows) > row_limit
                rows = rows[:row_limit]

                rows = [
                    list(row.values())
                    for row in rows
                ]

                total = f">{row_limit}" if truncated else str(len(rows))
                message = f"{len(rows)} row(s) of {total}"
                return columns, rows, message

            return [], [], f"{cur.rowcount} row(s) affected"

    def _execute_sql(
        self,
        host: str,
        database: str | None,
        statements: list[str],
        row_limit: int,
    ) -> tuple[list[list[str]], list[str], str]:
        """Выполняет список операторов и возвращает агрегированный
        результат (rows, columns, message)."""
        started_at = time.perf_counter()

        client = client_for(host)

        with client.connect(host, database) as conn:
            self._register_active(host, client.connection_id(conn))

            try:
                per_statement = []

                for statement in statements:
                    if self._stop:
                        break
                    per_statement.append(
                        self._execute_statement(conn, statement, row_limit)
                    )
            finally:
                self._unregister_active()

        return self._combine_results(
            per_statement,
            time.perf_counter() - started_at,
        )

    @staticmethod
    def _combine_results(
        per_statement: list,
        elapsed: float,
    ) -> tuple[list[list[str]], list[str], str]:
        """Собирает результаты операторов в один набор строк/колонок.

        Колонки берутся из первого оператора, вернувшего набор строк;
        операторы с такими же колонками добавляют строки; операторы без
        результата попадают в текстовую часть сообщения; операторы с
        отличающимися колонками пропускаются (учитываются в сообщении).
        """
        if not per_statement:
            return [], [], f"No statements executed ({elapsed:.2f} s)"

        if len(per_statement) == 1:
            columns, rows, message = per_statement[0]
            return rows, columns, f"{message} ({elapsed:.2f} s)"

        columns = None
        rows: list[list[str]] = []
        parts: list[str] = []
        skipped = 0

        for cols, stmt_rows, message in per_statement:
            if not cols:
                parts.append(message)
                continue
            if columns is None:
                columns = cols
            if cols == columns:
                rows.extend(stmt_rows)
            else:
                skipped += 1

        if columns is not None:
            parts.insert(0, f"{len(rows)} row(s)")

        if skipped:
            parts.append(f"{skipped} statement(s) skipped (columns differ)")

        message = "; ".join(parts) or "No result"
        message += f" ({elapsed:.2f} s)"

        return rows, columns, message

    @Slot()
    def run(self):
        """Точка входа потока.

        finished эмитится ровно один раз, а никакое исключение не
        покидает слот (в PySide6 вылетевшее из слота исключение может
        аварийно завершить процесс).
        """
        self.started.emit()

        try:
            self._dispatch()
        except Exception as ex:
            logger.exception(ex)
            if self._stop:
                self.stopped.emit(0, 1)
            else:
                self.error.emit(str(ex))
        finally:
            self.finished.emit()

    def _dispatch(self):

        if self._mode == "databases":
            logger.action(
                f"TRACE dispatch: mode=databases, host={self._host}"
            )
            names = client_for(self._host).list_databases(self._host)
            logger.action(
                f"TRACE dispatch: databases loaded={len(names)}, emitting"
            )
            self.databases.emit(names)
            return

        if self._mode == "multi":
            self._run_multi()
            return

        if self._mode == "export":
            self._run_export()
            return

        if not self._statements:
            self.error.emit("No SQL statements to run.")
            return

        logger.action(
            f"TRACE dispatch: mode=single, host={self._host}, "
            f"db={self._database}, stmts={len(self._statements)}"
        )

        self.query.emit(self._sql)

        client = client_for(self._host)
        started_at = time.perf_counter()

        try:
            logger.action(
                f"TRACE dispatch: acquiring connection for {self._host}.{self._database}"
            )
            with client.connect(self._host, self._database) as conn:
                self._register_active(
                    self._host, client.connection_id(conn)
                )
                try:
                    per_statement = []
                    for statement in self._statements:
                        if self._stop:
                            break
                        per_statement.append(
                            self._execute_statement(
                                conn, statement, self._row_limit,
                            )
                        )
                finally:
                    self._unregister_active()

                rows, columns, message = self._combine_results(
                    per_statement,
                    time.perf_counter() - started_at,
                )

                if self._stop:
                    self.stopped.emit(0, 1)
                else:
                    self.result.emit(rows, columns, message)
                    self._emit_edit_meta(
                        conn, self._host, self._database,
                    )
        except Exception as ex:
            logger.exception(ex)
            if self._stop:
                self.stopped.emit(0, 1)
            else:
                self.error.emit(str(ex))

    def _emit_edit_meta(
        self, conn, host: str, database: str | None,
    ) -> None:
        if self._stop or not database:
            return
        try:
            table = self._table_hint or parse_select_table(self._sql)
            if not table:
                return
            pk, columns = client_for(host).edit_meta(
                host, database, table, conn=conn,
            )
            self.edit_meta.emit(host, database, table, pk, columns)
        except Exception as ex:
            logger.warning(
                f"{host}/{database}: метаданные для редактирования "
                f"не загружены: {ex}"
            )

    def _emit_edit_meta_for_target(
        self, conn, host: str, database: str,
    ) -> None:
        if self._stop or len(self._targets) != 1:
            return
        self._emit_edit_meta(conn, host, database)

    def _expand_multi_targets(self) -> list[tuple[int, str, str]]:
        """Разворачивает цели в список (idx, host, db); `*` — все БД."""
        expanded = []

        for idx, (host, database) in enumerate(self._targets, 1):
            if database == ALL_DATABASES:
                try:
                    names = client_for(host).list_databases(host)
                except Exception as ex:
                    logger.exception(ex)
                    self.error_target.emit(host, "", str(ex))
                    continue

                for name in names:
                    expanded.append((idx, host, name))
            else:
                expanded.append((idx, host, database))

        return expanded

    def _run_multi(self):
        """Выполняет запрос на всех целях параллельно.

        Каждая цель обрабатывается в отдельном потоке пула: соединения
        выдаются общим пулом клиентов (общий лимит соединений соблюдается),
        результаты приходят по мере готовности через result_target.
        """
        expanded = self._expand_multi_targets()

        if not expanded:
            if self._stop:
                self.stopped.emit(0, len(self._targets))
            return

        done = 0
        done_lock = threading.Lock()
        workers = max(1, min(len(expanded), config.parallel.workers))

        def run_one(idx: int, host_name: str, db_name: str) -> None:
            nonlocal done

            if self._stop:
                return

            self.started_target.emit(
                idx,
                len(self._targets),
                host_name,
                db_name,
            )

            self.query.emit(self._sql)

            client = client_for(host_name)

            try:
                with client.connect(host_name, db_name) as conn:
                    self._register_active(
                        host_name, client.connection_id(conn),
                    )
                    try:
                        per_statement = []
                        for statement in self._statements:
                            if self._stop:
                                break
                            per_statement.append(
                                self._execute_statement(
                                    conn, statement, self._row_limit,
                                )
                            )
                    finally:
                        self._unregister_active()

                    rows, columns, message = self._combine_results(
                        per_statement, 0,
                    )

                    if self._stop:
                        return

                    with done_lock:
                        done += 1

                    self.result_target.emit(
                        host_name, db_name, rows, columns, message,
                    )
                    self._emit_edit_meta_for_target(
                        conn, host_name, db_name,
                    )
            except Exception as ex:
                logger.exception(ex)
                if not self._stop:
                    self.error_target.emit(host_name, db_name, str(ex))

        executor = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="query-multi",
        )

        try:
            futures = [
                executor.submit(run_one, idx, host_name, db_name)
                for idx, host_name, db_name in expanded
            ]
            for future in futures:
                future.result()
        finally:
            executor.shutdown(wait=True)

        if self._stop:
            self.stopped.emit(done, len(self._targets))

    def _export_target(self, host_name, db_name, writer, state) -> None:
        """Выполняет операторы на одном целевом сервере/БД, пишет строки
        в CSV. Состояние (колонки, заголовок, счётчики) ведётся в `state`."""
        client = client_for(host_name)

        with client.connect(host_name, db_name) as conn:
            self._register_active(host_name, client.connection_id(conn))

            try:
                for statement in self._statements:
                    if self._stop:
                        break

                    with conn.cursor() as cur:
                        cur.execute(statement)

                        if cur.description is None:
                            continue

                        stmt_columns = [d[0] for d in cur.description]

                        if state["chosen"] is None:
                            state["chosen"] = stmt_columns

                        if stmt_columns != state["chosen"]:
                            continue

                        if not state["header_written"]:
                            writer.writerow(
                                ["Server", "Database"] + list(state["chosen"]),
                            )
                            state["header_written"] = True

                        while not self._stop:
                            batch = cur.fetchmany(5000)
                            if not batch:
                                break

                            state["total"] += len(batch)

                            for row in batch:
                                writer.writerow(
                                    [host_name, db_name]
                                    + [
                                        "Null" if value is None else str(value)
                                        for value in row.values()
                                    ],
                                )
            finally:
                self._unregister_active()

    def _run_export(self):
        """Выполняет последний запрос на всех целях без лимита строк
        и пишет результат в CSV."""
        filepath = self._filepath

        try:
            f = open(filepath, "w", newline="", encoding="utf-8-sig")
        except OSError as ex:
            self.error.emit(f"Cannot open {filepath}: {ex}")
            return

        writer = csv.writer(f)
        state = {
            "chosen": None,
            "header_written": False,
            "total": 0,
        }
        done = 0

        self.query.emit(self._sql)

        try:
            for i, (host, database) in enumerate(self._targets, 1):
                if self._stop:
                    break

                if database == ALL_DATABASES:
                    try:
                        names = client_for(host).list_databases(host)
                    except Exception as ex:
                        logger.exception(ex)
                        self.error_target.emit(host, "", str(ex))
                        continue

                    targets = [(host, name) for name in names]
                else:
                    targets = [(host, database)]

                for host_name, db_name in targets:
                    if self._stop:
                        break

                    self.started_target.emit(
                        i,
                        len(self._targets),
                        host_name,
                        db_name,
                    )

                    try:
                        self._export_target(host_name, db_name, writer, state)
                    except Exception as ex:
                        logger.exception(ex)
                        if self._stop:
                            break
                        self.error_target.emit(host_name, db_name, str(ex))
                        continue

                    done += 1
        finally:
            f.close()

        if self._stop:
            self.stopped.emit(done, len(self._targets))
        else:
            self.export_done.emit(state["total"], filepath)
