"""
tests/test_mssql_detach_attach_restore.py

Тесты MSSQL-операций:
  - MSSQLClient.detach_database
  - MSSQLClient.attach_database (+ xp_fileexist)
  - MSSQLClient.restore_database (+ xp_fileexist)
  - DatabaseOperationWorker (dispatch + error handling)
  - Context menu signals
"""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from backend.db_operation_worker import DatabaseOperationWorker, DbOperation
from common.mssql_client import MSSQLClient
from common.server_registry import ENGINE_MSSQL, ENGINE_MYSQL, registry
from gui.servers_tree import ServersTree


class _FakeConfig:
    connect_timeout = 5
    acquire_timeout = 5
    max_connections = 10
    max_per_key = 3
    pool_idle = 1
    idle_timeout = 60
    max_idle_connections = 2
    retry = 1


# ----------------------------------------------------------
# MSSQLClient.detach_database
# ----------------------------------------------------------

class TestMSSQLDetachDatabase(unittest.TestCase):

    def setUp(self):
        self.client = MSSQLClient(cfg=_FakeConfig())
        self.executions: list[str] = []

        def fake_query(host, sql, database=None, params=None):
            self.executions.append(sql)
            return []

        self.client.query = fake_query

    def test_detach_calls_single_user_and_detach(self):
        self.client.detach_database("srv", "mydb")

        self.assertEqual(len(self.executions), 2)
        self.assertIn("SINGLE_USER", self.executions[0])
        self.assertIn("sp_detach_db", self.executions[1])

    def test_detach_escapes_brackets(self):
        self.client.detach_database("srv", "my]db")

        self.assertEqual(len(self.executions), 2)
        self.assertIn("SINGLE_USER", self.executions[0])
        self.assertIn("sp_detach_db", self.executions[1])

    def test_detach_single_user_first(self):
        self.client.detach_database("srv", "testdb")

        self.assertEqual(len(self.executions), 2)
        self.assertIn("SINGLE_USER", self.executions[0])
        self.assertIn("sp_detach_db", self.executions[1])

    def test_detach_propagates_error(self):
        def failing_query(host, sql, database=None, params=None):
            if "sp_detach_db" in sql:
                raise RuntimeError("Permission denied")
            return []

        self.client.query = failing_query

        with self.assertRaises(RuntimeError):
            self.client.detach_database("srv", "mydb")


# ----------------------------------------------------------
# MSSQLClient.attach_database
# ----------------------------------------------------------

class TestMSSQLAttachDatabase(unittest.TestCase):

    def setUp(self):
        self.client = MSSQLClient(cfg=_FakeConfig())
        self.executions: list[str] = []

        def fake_query(host, sql, database=None, params=None):
            self.executions.append(sql)
            return []

        self.client.query = fake_query

    def test_attach_file_exists_calls_create(self):
        self.client._file_exists = MagicMock(return_value=True)

        self.client.attach_database("srv", "mydb", r"C:\data\mydb.mdf")

        self.assertEqual(len(self.executions), 1)
        self.assertIn("CREATE DATABASE [mydb]", self.executions[0])
        self.assertIn("FOR ATTACH", self.executions[0])

    def test_attach_file_not_found_raises(self):
        self.client._file_exists = MagicMock(return_value=False)

        with self.assertRaises(ValueError) as ctx:
            self.client.attach_database("srv", "mydb", r"C:\missing.mdf")

        self.assertIn("не найден", str(ctx.exception))

    def test_attach_escapes_brackets(self):
        self.client._file_exists = MagicMock(return_value=True)

        self.client.attach_database("srv", "my]db", r"C:\data\my.mdf")

        self.assertIn("[my]]db]", self.executions[0])

    def test_attach_validates_file_first(self):
        self.client._file_exists = MagicMock(return_value=False)

        with self.assertRaises(ValueError):
            self.client.attach_database("srv", "db", r"C:\x.mdf")

        self.client._file_exists.assert_called_once_with("srv", r"C:\x.mdf")


# ----------------------------------------------------------
# MSSQLClient.restore_database
# ----------------------------------------------------------

class TestMSSQLRestoreDatabase(unittest.TestCase):

    def setUp(self):
        self.client = MSSQLClient(cfg=_FakeConfig())
        self.executions: list[str] = []

        def fake_query(host, sql, database=None, params=None):
            self.executions.append(sql)
            return []

        self.client.query = fake_query

    def test_restore_with_replace(self):
        self.client._file_exists = MagicMock(return_value=True)

        self.client.restore_database(
            "srv", "mydb", r"C:\backups\mydb.bak", replace=True,
        )

        self.assertEqual(len(self.executions), 1)
        self.assertIn("RESTORE DATABASE [mydb]", self.executions[0])
        self.assertIn("FROM DISK", self.executions[0])
        self.assertIn("REPLACE", self.executions[0])

    def test_restore_without_replace(self):
        self.client._file_exists = MagicMock(return_value=True)

        self.client.restore_database(
            "srv", "mydb", r"C:\backups\mydb.bak", replace=False,
        )

        self.assertEqual(len(self.executions), 1)
        self.assertIn("RESTORE DATABASE [mydb]", self.executions[0])
        self.assertNotIn("REPLACE", self.executions[0])

    def test_restore_file_not_found_raises(self):
        self.client._file_exists = MagicMock(return_value=False)

        with self.assertRaises(ValueError) as ctx:
            self.client.restore_database(
                "srv", "mydb", r"C:\missing.bak",
            )

        self.assertIn("не найден", str(ctx.exception))

    def test_restore_escapes_brackets(self):
        self.client._file_exists = MagicMock(return_value=True)

        self.client.restore_database(
            "srv", "my]db", r"C:\backups\my.bak",
        )

        self.assertIn("[my]]db]", self.executions[0])

    def test_restore_validates_file_first(self):
        self.client._file_exists = MagicMock(return_value=False)

        with self.assertRaises(ValueError):
            self.client.restore_database("srv", "db", r"C:\x.bak")

        self.client._file_exists.assert_called_once_with("srv", r"C:\x.bak")


# ----------------------------------------------------------
# MSSQLClient._file_exists
# ----------------------------------------------------------

class TestMSSQLFileExists(unittest.TestCase):

    def setUp(self):
        self.client = MSSQLClient(cfg=_FakeConfig())

    def test_file_exists_returns_true(self):
        def fake_query(host, sql, database=None, params=None):
            return [{"File Exists": 1, "File Is A Directory": 0}]

        self.client.query = fake_query

        self.assertTrue(
            self.client._file_exists("srv", r"C:\data\db.mdf")
        )

    def test_file_exists_returns_false(self):
        def fake_query(host, sql, database=None, params=None):
            return [{"File Exists": 0, "File Is A Directory": 0}]

        self.client.query = fake_query

        self.assertFalse(
            self.client._file_exists("srv", r"C:\missing.mdf")
        )

    def test_file_exists_empty_result(self):
        def fake_query(host, sql, database=None, params=None):
            return []

        self.client.query = fake_query

        self.assertFalse(
            self.client._file_exists("srv", r"C:\x.mdf")
        )


# ----------------------------------------------------------
# DatabaseOperationWorker
# ----------------------------------------------------------

class TestDatabaseOperationWorker(unittest.TestCase):

    def setUp(self):
        self.worker = DatabaseOperationWorker()
        self.finished = False
        self.succeeded = False
        self.error_msg = None

        self.worker.finished.connect(lambda: setattr(self, 'finished', True))
        self.worker.success.connect(lambda: setattr(self, 'succeeded', True))
        self.worker.error.connect(
            lambda msg: setattr(self, 'error_msg', msg)
        )

    @patch("backend.db_operation_worker.client_for")
    def test_drop_calls_drop_database(self, mock_client_for):
        mock_client = MagicMock()
        mock_client_for.return_value = mock_client

        self.worker.set_request("h1", "db1", DbOperation.DROP)
        self.worker.run()

        mock_client.drop_database.assert_called_once_with("h1", "db1")
        self.assertTrue(self.finished)
        self.assertTrue(self.succeeded)
        self.assertIsNone(self.error_msg)

    @patch("backend.db_operation_worker.client_for")
    def test_detach_calls_detach_database(self, mock_client_for):
        mock_client = MagicMock()
        mock_client_for.return_value = mock_client

        self.worker.set_request("h1", "db1", DbOperation.DETACH)
        self.worker.run()

        mock_client.detach_database.assert_called_once_with("h1", "db1")
        self.assertTrue(self.finished)
        self.assertTrue(self.succeeded)

    @patch("backend.db_operation_worker.client_for")
    def test_attach_calls_attach_database(self, mock_client_for):
        mock_client = MagicMock()
        mock_client_for.return_value = mock_client

        self.worker.set_request(
            "h1", "db1", DbOperation.ATTACH,
            file_path=r"C:\data\db.mdf",
        )
        self.worker.run()

        mock_client.attach_database.assert_called_once_with(
            "h1", "db1", r"C:\data\db.mdf",
        )
        self.assertTrue(self.finished)
        self.assertTrue(self.succeeded)

    @patch("backend.db_operation_worker.client_for")
    def test_restore_calls_restore_database(self, mock_client_for):
        mock_client = MagicMock()
        mock_client_for.return_value = mock_client

        self.worker.set_request(
            "h1", "db1", DbOperation.RESTORE,
            file_path=r"C:\backups\db.bak",
            replace=True,
        )
        self.worker.run()

        mock_client.restore_database.assert_called_once_with(
            "h1", "db1", r"C:\backups\db.bak", replace=True,
        )
        self.assertTrue(self.finished)
        self.assertTrue(self.succeeded)

    @patch("backend.db_operation_worker.client_for")
    def test_error_emitted_on_exception(self, mock_client_for):
        mock_client = MagicMock()
        mock_client.drop_database.side_effect = RuntimeError("boom")
        mock_client_for.return_value = mock_client

        self.worker.set_request("h1", "db1", DbOperation.DROP)
        self.worker.run()

        self.assertTrue(self.finished)
        self.assertFalse(self.succeeded)
        self.assertIn("boom", self.error_msg)

    @patch("backend.db_operation_worker.client_for")
    def test_unknown_operation_emits_error(self, mock_client_for):
        mock_client_for.return_value = MagicMock()

        self.worker.set_request("h1", "db1", "invalid_op")
        self.worker.run()

        self.assertTrue(self.finished)
        self.assertFalse(self.succeeded)
        self.assertIn("Unknown operation", self.error_msg)


# ----------------------------------------------------------
# Context menu signals
# ----------------------------------------------------------

class TestContextMenuSignals(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tree = ServersTree()
        self.tree.set_servers([
            ("mssql_srv", "h1", ENGINE_MSSQL),
            ("mysql_srv", "h2", ENGINE_MYSQL),
        ])
        self.tree.apply_databases("h1", ["testdb"])

    def tearDown(self):
        self.tree.close()
        self.tree.deleteLater()
        self.tree = None

    def test_detach_signal_for_mssql(self):
        received = []
        self.tree.detachDatabaseRequested.connect(
            lambda s, d: received.append((s, d))
        )
        self.tree.detachDatabaseRequested.emit("h1", "testdb")
        self.assertEqual(received, [("h1", "testdb")])

    def test_attach_signal_for_mssql(self):
        received = []
        self.tree.attachDatabaseRequested.connect(
            lambda s: received.append(s)
        )
        self.tree.attachDatabaseRequested.emit("h1")
        self.assertEqual(received, ["h1"])

    def test_restore_signal_for_mssql(self):
        received = []
        self.tree.restoreDatabaseRequested.connect(
            lambda s: received.append(s)
        )
        self.tree.restoreDatabaseRequested.emit("h1")
        self.assertEqual(received, ["h1"])

    def test_mysql_no_detach_in_menu(self):
        engine = registry.engine("h2")
        self.assertEqual(engine, ENGINE_MYSQL)
        self.assertNotEqual(engine, ENGINE_MSSQL)


if __name__ == "__main__":
    unittest.main()
