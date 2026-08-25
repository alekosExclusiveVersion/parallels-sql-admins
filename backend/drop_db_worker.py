"""
backend/drop_db_worker.py

Фоновое удаление базы данных (MSSQL / PostgreSQL).

Worker выполняется в QThread через WorkerHost: при вызове run()
отправляет SQL на сервер, эмитит finished или error.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from common.logger import logger
from common.server_registry import client_for


class DropDatabaseWorker(QObject):
    finished = Signal()
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self._host: str = ""
        self._database: str = ""

    def set_request(self, host: str, database: str) -> None:
        self._host = host
        self._database = database

    def run(self) -> None:
        try:
            client = client_for(self._host)
            client.drop_database(self._host, self._database)
        except Exception as ex:
            logger.exception(ex)
            self.error.emit(str(ex))
        finally:
            self.finished.emit()
