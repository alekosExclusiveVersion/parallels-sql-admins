"""
tests/test_db_operation_worker.py

Тесты backend/db_operation_worker.py для read-only операции DB_FILES:
результат файлов БД сохраняется в worker.result.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.db_operation_worker import DatabaseOperationWorker, DbOperation


class _FileRecording:
    def __init__(self, files):
        self._files = files

    def database_files(self, host, database):
        self.host = host
        self.database = database
        return self._files


class DbFilesOperationTest(unittest.TestCase):

    def _run(self, op):
        files = [
            {"type": "ROWS", "name": "f1", "file": "a.mdf",
             "bytes": 1024 * 1024 * 10, "used": 1024 * 1024 * 9},
            {"type": "LOG", "name": "f2", "file": "a.ldf",
             "bytes": 1024 * 1024 * 2, "used": 1024 * 1024 * 2},
        ]
        client = _FileRecording(files)

        signals = {"success": [], "error": []}
        worker = DatabaseOperationWorker()
        worker.success.connect(lambda: signals["success"].append(True))
        worker.error.connect(lambda m: signals["error"].append(m))
        worker.set_request("h", "vinpart", op)

        with patch("backend.db_operation_worker.client_for",
                   return_value=client):
            worker.run()

        return worker, signals, client

    def test_db_files_collects_result(self):
        worker, signals, _ = self._run(DbOperation.DB_FILES)

        self.assertEqual(len(signals["success"]), 1)
        self.assertEqual(signals["error"], [])
        self.assertEqual(worker.result[0]["type"], "ROWS")
        self.assertEqual(worker.result[1]["bytes"], 1024 * 1024 * 2)

    def test_db_files_reset_on_new_request(self):
        worker, _, _ = self._run(DbOperation.DB_FILES)
        worker.set_request("h", "other", DbOperation.DB_FILES)
        self.assertEqual(worker.result, [])


if __name__ == "__main__":
    unittest.main()
