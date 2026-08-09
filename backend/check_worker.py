from __future__ import annotations

from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)

from common.mysql_client import mysql
from common.stats import stats
from common.sql_builder import sql_builder
from common.logger import logger
from PySide6.QtCore import QObject, Signal, Slot
from common.config import config


class CheckWorker(QObject):
    started = Signal()
    finished = Signal()
    progress = Signal(int, int)
    status = Signal(str)
    query = Signal(str)
    result = Signal(
        str,
        str,
        str,
        str,
        str,
        str,
    )

    def __init__(self):
        super().__init__()
        self._servers = []
        self._stop_requested = False

    def set_servers(self, servers):
        self._servers = list(servers)
    
    def stop(self):

        self._stop_requested = True

    @property
    def servers(self):

        return self._servers

    def _check_server(self, server: str):

        results = []
        messages = []

        if self._stop_requested:
            return results, messages

        try:

            messages.append(
                f"{server}: connecting..."
            )

            with mysql.connect(server) as conn:

                databases = mysql.filter_databases_with_settings_conn(
                    conn,
                    mysql.list_databases_conn(conn),
                )

            messages.append(
                f"{server}: found {len(databases)} database(s)"
            )

            batches = list(
                sql_builder.chunk(
                    databases,
                    config.advanced.batch_size,
                )
            )

            with ThreadPoolExecutor(
                max_workers=config.parallel.database_workers,
            ) as executor:

                futures = {
                    executor.submit(
                        self._check_batch,
                        server,
                        batch,
                    ): batch
                    for batch in batches
                }

                for future in as_completed(futures):

                    if self._stop_requested:

                        for pending in futures:
                            pending.cancel()

                        break

                    rows, messages_batch = future.result()

                    results.extend(rows)

                    messages.extend(messages_batch)

        except Exception as ex:

            logger.exception(ex)

            messages.append(
                f"{server}: {ex}"
            )

            results.append(
                (
                    server,
                    "-",
                    "-",
                    "-",
                    "ERROR",
                    str(ex),
                )
            )

        return results, messages
    
    def _check_batch(
        self,
        server: str,
        databases: list,
    ):

        rows = []
        messages = []

        try:

            with mysql.connect(server) as conn:

                batch_rows = mysql.scan_settings_batch(
                    conn,
                    databases,
                )

            for item in batch_rows:

                rows.append(
                    (
                        server,
                        item["database_name"],
                        item["country"] or "-",
                        item["target_value"] or "-",
                        "OK",
                        "",
                    )
                )

        except Exception as ex:

            messages.append(
                f"{server}/{databases[0]}: batch query failed, "
                f"retrying per database ({ex})"
            )

            # Fallback: одно соединение для всей пачки, чтобы не
            # открывать новое подключение на каждую БД.
            try:
                with mysql.connect(server) as conn:
                    for database in databases:
                        try:
                            settings = mysql.get_settings_conn(
                                conn,
                                database,
                            )

                            rows.append(
                                (
                                    server,
                                    database,
                                    settings.get(
                                        config.filter.country_setting,
                                        "-",
                                    ),
                                    settings.get(
                                        config.filter.target_setting,
                                        "-",
                                    ),
                                    "OK",
                                    "",
                                )
                            )

                        except Exception as db_ex:

                            logger.exception(db_ex)

                            rows.append(
                                (
                                    server,
                                    database,
                                    "-",
                                    "-",
                                    "ERROR",
                                    str(db_ex),
                                )
                            )

                            messages.append(
                                f"{server}/{database}: {db_ex}"
                            )

            except Exception as conn_ex:
                # Не удалось открыть даже одно соединение — помечаем
                # все БД пачки ошибкой.
                logger.exception(conn_ex)
                for database in databases:
                    rows.append(
                        (
                            server,
                            database,
                            "-",
                            "-",
                            "ERROR",
                            str(conn_ex),
                        )
                    )

        return rows, messages

    def _log_query(self, sql, host):

        if not sql.strip().upper().startswith("SHOW"):
            self.query.emit(f"[{host}] {sql}")

    @Slot()    
    def run(self):
        
        self._stop_requested = False

        mysql.set_query_hook(self._log_query)
        
        self.started.emit()

        stats.reset()

        self.status.emit(
            f"Checking {len(self._servers)} server(s)..."
        )

        if not self._servers:

            self.status.emit(
                "No servers selected."
            )

            mysql.set_query_hook(None)

            self.finished.emit()
            return

        total = len(self._servers)

        completed = 0

        with ThreadPoolExecutor(
            max_workers=config.parallel.workers
        ) as executor:

            futures = {
                executor.submit(
                    self._check_server,
                    server,
                ): server
                for server in self._servers
            }

            for future in as_completed(futures):

                if self._stop_requested:

                    for pending in futures:
                        pending.cancel()

                    break

                try:
                    rows, messages = future.result()

                except Exception as ex:

                    self.status.emit(
                        f"Worker error: {ex}"
                    )

                    completed += 1
                    
                    stats.server()

                    self.progress.emit(
                        completed,
                        total,
                    )

                    continue

                for message in messages:
                    self.status.emit(message)

                for row in rows:
                    
                    stats.database()

                    if row[4] == "OK":
                        stats.success()
                    else:
                        stats.error()

                    self.result.emit(*row)

                stats.server()

                completed += 1

                self.progress.emit(
                    completed,
                    total,
                )
        
        if self._stop_requested:

            self.status.emit(
                "Check stopped."
            )

        else:

            self.status.emit(
                "Check finished."
            )
        summary = stats.summary()

        self.status.emit("")
        self.status.emit("========== SUMMARY ==========")
        self.status.emit(f"Servers   : {summary['servers']}")
        self.status.emit(f"Databases : {summary['databases']}")
        self.status.emit(f"Errors    : {summary['errors']}")
        self.status.emit(f"Elapsed   : {summary['elapsed']:.2f} sec")

        mysql.set_query_hook(None)

        self.finished.emit()