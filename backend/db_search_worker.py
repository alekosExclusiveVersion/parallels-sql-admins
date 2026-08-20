"""
backend/db_search_worker.py

Параллельный поиск баз данных по маске (LIKE) на нескольких серверах.
Выполняется в фоновом QThread, чтобы не блокировать GUI.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QObject, Signal, Slot

from common.config import config
from common.logger import logger
from common.mysql_client import mysql


class DatabaseSearchWorker(QObject):
    started = Signal()
    finished = Signal()
    progress = Signal(int, int)
    status = Signal(str)
    result = Signal(str, str, str)  # server, database, last_update
    error = Signal(str, str)   # server, message

    def __init__(self):
        super().__init__()
        self._mask = ""
        self._servers = []
        self._stop_requested = False

    def set_request(self, mask: str, servers: list[str]):
        self._mask = mask
        self._servers = list(servers)
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def _search_server(self, server: str):
        """Поиск БД на одном сервере. Возвращает (server, databases, update_times, error)."""
        if self._stop_requested:
            return server, [], {}, None

        try:
            databases = mysql.search_databases(server, self._mask)

            update_times = {}
            if databases:
                try:
                    update_times = mysql.database_update_times(
                        server, databases
                    )
                except Exception as ex:
                    logger.warning(
                        f"{server}: update_times query failed ({ex}), "
                        f"continuing without activity data"
                    )

            return server, databases, update_times, None
        except Exception as ex:
            logger.exception(ex)
            return server, [], {}, str(ex)

    @Slot()
    def run(self):
        self._stop_requested = False

        self.started.emit()

        if not self._servers:
            self.status.emit("No servers selected.")
            self.finished.emit()
            return

        self.status.emit(
            f"Searching '{self._mask}' on {len(self._servers)} server(s)..."
        )

        total = len(self._servers)
        completed = 0
        found = 0

        # Ограниченный пул потоков, чтобы не перегружать серверы.
        max_workers = min(
            config.parallel.search_workers,
            total,
        )
        max_workers = max(1, max_workers)

        executor = ThreadPoolExecutor(max_workers=max_workers)

        futures = {
            executor.submit(self._search_server, server): server
            for server in self._servers
        }

        try:
            for future in as_completed(futures):
                if self._stop_requested:
                    for pending in futures:
                        pending.cancel()
                    break

                server, databases, update_times, err = future.result()

                completed += 1

                if err:
                    self.error.emit(server, err)
                    self.status.emit(f"{server}: {err}")
                else:
                    for db in databases:
                        found += 1
                        last_update = update_times.get(db, "")
                        self.result.emit(server, db, last_update)

                    self.status.emit(
                        f"{server}: {len(databases)} database(s) found"
                    )

                self.progress.emit(completed, total)
        finally:
            executor.shutdown(wait=True)

        if self._stop_requested:
            self.status.emit("Search stopped.")
        else:
            self.status.emit(
                f"Search finished: {found} database(s) found "
                f"on {completed} server(s)."
            )

        self.finished.emit()
