"""
backend/db_operation_worker.py

Универсальный worker для операций над БД:
  DROP / DETACH / ATTACH / RESTORE.

Выполняется в QThread через WorkerHost.
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QObject, Signal

from common.logger import logger
from common.server_registry import client_for


class DbOperation(str, Enum):
    DROP = "drop"
    DETACH = "detach"
    ATTACH = "attach"
    RESTORE = "restore"


class DatabaseOperationWorker(QObject):
    finished = Signal()
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self._host: str = ""
        self._database: str = ""
        self._operation: str = ""
        self._file_path: str = ""
        self._replace: bool = False

    def set_request(
        self,
        host: str,
        database: str,
        operation: str,
        *,
        file_path: str = "",
        replace: bool = False,
    ) -> None:
        self._host = host
        self._database = database
        self._operation = operation
        self._file_path = file_path
        self._replace = replace

    def run(self) -> None:
        try:
            client = client_for(self._host)

            match self._operation:
                case DbOperation.DROP:
                    client.drop_database(self._host, self._database)

                case DbOperation.DETACH:
                    client.detach_database(self._host, self._database)

                case DbOperation.ATTACH:
                    client.attach_database(
                        self._host,
                        self._database,
                        self._file_path,
                    )

                case DbOperation.RESTORE:
                    client.restore_database(
                        self._host,
                        self._database,
                        self._file_path,
                        replace=self._replace,
                    )

                case _:
                    raise ValueError(
                        f"Unknown operation: {self._operation}"
                    )

        except Exception as ex:
            logger.exception(ex)
            self.error.emit(str(ex))
        finally:
            self.finished.emit()
