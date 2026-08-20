"""
tests/test_db_search_worker.py

Интеграционные тесты DatabaseSearchWorker.run():
- result сигнал эмитится с 4 аргументами (server, db, last_update, site);
- finished гарантированно эмитится (даже при ошибках);
- пустой список серверов → finished без краша;
- ошибка search_databases → error + finished;
- ошибка database_update_times → result с пустым last_update + finished.
"""

import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from backend.db_search_worker import DatabaseSearchWorker


app = QApplication.instance() or QApplication([])


class TestDatabaseSearchWorker(unittest.TestCase):

    def _wait(self, events, count, timeout=3.0):
        deadline = time.monotonic() + timeout
        while len(events) < count and time.monotonic() < deadline:
            time.sleep(0.01)
            QApplication.processEvents()
        return len(events)

    @patch("backend.db_search_worker.mysql")
    def test_run_emits_result_with_site(self, mock_mysql):
        mock_mysql.search_databases.return_value = [
            {"db": "ar_shop", "site": "shop.ru"},
            {"db": "ar_market", "site": "market.com"},
        ]
        mock_mysql.database_update_times.return_value = {
            "ar_shop": "2026-08-20 12:00:00",
        }

        worker = DatabaseSearchWorker()
        results = []
        finished = []
        worker.result.connect(
            lambda s, d, u, st: results.append((s, d, u, st)),
            Qt.ConnectionType.DirectConnection,
        )
        worker.finished.connect(
            lambda: finished.append(True),
            Qt.ConnectionType.DirectConnection,
        )

        worker.set_request("shop", ["srv1"])
        worker.run()

        self.assertEqual(len(results), 2)

        dbs = {r[1]: r for r in results}
        self.assertEqual(
            dbs["ar_shop"],
            ("srv1", "ar_shop", "2026-08-20 12:00:00", "shop.ru"),
        )
        self.assertEqual(
            dbs["ar_market"],
            ("srv1", "ar_market", "", "market.com"),
        )
        self.assertEqual(len(finished), 1)

    @patch("backend.db_search_worker.mysql")
    def test_run_emits_finished(self, mock_mysql):
        mock_mysql.search_databases.return_value = []
        mock_mysql.database_update_times.return_value = {}

        worker = DatabaseSearchWorker()
        finished = []
        worker.finished.connect(
            lambda: finished.append(True),
            Qt.ConnectionType.DirectConnection,
        )

        worker.set_request("test", ["srv1"])
        worker.run()

        self.assertEqual(len(finished), 1)

    def test_run_no_servers(self):
        worker = DatabaseSearchWorker()
        statuses = []
        finished = []
        worker.status.connect(
            lambda s: statuses.append(s),
            Qt.ConnectionType.DirectConnection,
        )
        worker.finished.connect(
            lambda: finished.append(True),
            Qt.ConnectionType.DirectConnection,
        )

        worker.set_request("test", [])
        worker.run()

        self.assertEqual(len(finished), 1)
        self.assertTrue(any("No servers" in s for s in statuses))

    @patch("backend.db_search_worker.mysql")
    def test_run_search_error(self, mock_mysql):
        mock_mysql.search_databases.side_effect = RuntimeError("conn refused")

        worker = DatabaseSearchWorker()
        errors = []
        finished = []
        worker.error.connect(
            lambda s, m: errors.append((s, m)),
            Qt.ConnectionType.DirectConnection,
        )
        worker.finished.connect(
            lambda: finished.append(True),
            Qt.ConnectionType.DirectConnection,
        )

        worker.set_request("test", ["bad_server"])
        worker.run()

        self.assertEqual(len(finished), 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0][0], "bad_server")
        self.assertIn("conn refused", errors[0][1])

    @patch("backend.db_search_worker.mysql")
    def test_run_update_times_error(self, mock_mysql):
        mock_mysql.search_databases.return_value = [
            {"db": "ar_test", "site": "test.com"},
        ]
        mock_mysql.database_update_times.side_effect = RuntimeError("timeout")

        worker = DatabaseSearchWorker()
        results = []
        finished = []
        worker.result.connect(
            lambda s, d, u, st: results.append((s, d, u, st)),
            Qt.ConnectionType.DirectConnection,
        )
        worker.finished.connect(
            lambda: finished.append(True),
            Qt.ConnectionType.DirectConnection,
        )

        worker.set_request("test", ["srv1"])
        worker.run()

        self.assertEqual(len(finished), 1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], ("srv1", "ar_test", "", "test.com"))


if __name__ == "__main__":
    unittest.main()
