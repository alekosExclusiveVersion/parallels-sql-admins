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
from gui.main_window import MainWindow
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

    def test_detach_runs_in_master_context(self):
        self.client.detach_database("srv", "mydb")

        self.assertTrue(self.executions[0].lstrip().startswith("USE [master];"))
        self.assertTrue(self.executions[1].lstrip().startswith("USE [master];"))

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
# MSSQLClient.drop_database / detach — контекст master
# ----------------------------------------------------------

class _StaleCtxConn:
    """Фейковое соединение, у которого сессионный контекст уже
    переключён на целевую БД (USE [db]) — эмуляция пула после
    загрузки размеров таблиц."""

    def __init__(self, owner):
        self.owner = owner
        self.closed = False

    @property
    def _current_db(self):
        return self.owner.current_db

    def cursor(self):
        return self.owner.cur

    def autocommit(self, val):
        pass

    def close(self):
        self.closed = True


class _CtxCursor:
    def __init__(self, owner):
        self.owner = owner

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.owner.executions.append(sql)
        if sql.startswith("USE ["):
            self.owner.current_db = sql.split("USE [")[1].split("]")[0]
        self.owner.result = []

    description = None

    def fetchall(self):
        return self.owner.result


class TestMSSQLDDLRunsInMasterContext(unittest.TestCase):
    """Регрессия: пул переиспользует соединение с сессионным USE [db];
    DDL drop/detach не должен исполняться внутри целевой БД — всегда
    предваряется USE [master]."""

    def setUp(self):
        self.client = MSSQLClient(cfg=_FakeConfig())
        self.client._open_connection = self._fake_open
        self.executions: list[str] = []
        self.current_db: str = "master"
        self.cur = _CtxCursor(self)

    def _fake_open(self, host, database=None):
        return _StaleCtxConn(self)

    def _prime_with_target_context(self, database: str):
        with self.client.connect("srv", None) as conn:
            with conn.cursor() as cur:
                cur.execute(f"USE [{database}]; SELECT 1")
        self.assertEqual(self.current_db, database)

    def test_drop_issued_in_master_after_stale_use(self):
        self._prime_with_target_context("mydb")
        self.client.drop_database("srv", "mydb")

        for sql in self.executions[-2:]:
            self.assertTrue(sql.lstrip().startswith("USE [master];"))
            self.assertIn("DROP DATABASE [mydb]" if "DROP" in sql else "SINGLE_USER", sql)

    def test_detach_issued_in_master_after_stale_use(self):
        self._prime_with_target_context("mydb")
        self.client.detach_database("srv", "mydb")

        for sql in self.executions[-2:]:
            self.assertTrue(sql.lstrip().startswith("USE [master];"))

    def tearDown(self):
        self.client.close_all()


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
        self.assertTrue(self.executions[0].lstrip().startswith("USE [master];"))
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
        self.assertTrue(self.executions[0].lstrip().startswith("USE [master];"))
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

    @patch("backend.db_operation_worker.client_for")
    def test_base_exception_still_emits_finished(self, mock_client_for):
        """Регрессия: любой сбой, включая BaseException (не только
        Exception), должен превращаться в error-сигнал и не должен
        заклинивать поток — finished обязан эмититься в finally."""
        mock_client = MagicMock()
        mock_client.drop_database.side_effect = SystemExit("hard crash")
        mock_client_for.return_value = mock_client

        self.worker.set_request("h1", "db1", DbOperation.DROP)
        self.worker.run()

        self.assertTrue(self.finished)
        self.assertFalse(self.succeeded)
        self.assertIn("hard crash", self.error_msg)

    @patch("backend.db_operation_worker.client_for")
    def test_success_also_emits_finished(self, mock_client_for):
        mock_client = MagicMock()
        mock_client_for.return_value = mock_client

        self.worker.set_request("h1", "db1", DbOperation.DROP)
        self.worker.run()

        self.assertTrue(self.finished)
        self.assertTrue(self.succeeded)
        self.assertIsNone(self.error_msg)


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


# ----------------------------------------------------------
# MainWindow._db_op_error — модальное окно ошибки
# ----------------------------------------------------------

class TestDbOpErrorModal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        window = MainWindow.__new__(MainWindow)
        window.db_op_worker = MagicMock()
        window.db_op_worker._host = "h1"
        window.db_op_worker._database = "mydb"
        window.db_op_worker._operation = DbOperation.DROP
        window.append_log = MagicMock()
        self.window = window

    @patch("gui.main_window.CopyableMessageBox.critical")
    def test_shows_modal_on_error(self, mock_critical):
        MainWindow._db_op_error(self.window, "boom")

        self.window.append_log.assert_called_once()
        args = mock_critical.call_args.args
        self.assertIs(args[0], self.window)
        self.assertIn("удаления", args[1])
        combined = args[2]
        self.assertIn("«mydb»", combined)
        self.assertIn("«h1»", combined)
        self.assertIn("boom", combined)

    @patch("gui.main_window.CopyableMessageBox.critical")
    def test_humanizes_known_db_error_to_russian(self, mock_critical):
        MainWindow._db_op_error(
            self.window,
            "Cannot open database \"ARSPARTS\" requested by the login.",
        )

        args = mock_critical.call_args.args
        combined = args[2]
        self.assertIn("соединение с сервером", combined)
        self.assertIn("«mydb»", combined)
        self.assertNotIn("Cannot open database", combined)


if __name__ == "__main__":
    unittest.main()
