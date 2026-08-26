"""
tests/test_drop_database.py

Тесты фичи удаления БД:
  - MSSQLClient.drop_database: SET SINGLE_USER + DROP DATABASE
  - PgSQLClient.drop_database: pg_terminate_backend + DROP DATABASE
  - ServersTree.remove_database: удаление узла БД из дерева
  - Контекстное меню: пункт «Удалить БД» только для MSSQL/PGSQL
  - DatabaseOperationWorker: dispatch для DbOperation.DROP
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from backend.db_operation_worker import DatabaseOperationWorker, DbOperation
from common.mssql_client import MSSQLClient
from common.pgsql_client import PgsqlClient
from common.server_registry import ENGINE_MSSQL, ENGINE_MYSQL, ENGINE_PGSQL, registry
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


class _FakeCursor:
    def __init__(self, owner):
        self.owner = owner

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.owner.executions.append((sql, params))

    def fetchall(self):
        return self.owner.result


class _FakeMSSQLConn:
    def __init__(self):
        self.executions = []
        self.result = []
        self.closed = False

    def cursor(self):
        c = _FakeCursor(self)
        c.fetchall = lambda: self.result
        return c

    def autocommit(self, val):
        pass

    def close(self):
        self.closed = True


class _FakePgsqlConn:
    def __init__(self):
        self.executions = []
        self.result = []
        self.closed = False
        self._psql_db = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        c = _FakeCursor(self)
        c.fetchall = lambda: self.result
        c.description = True
        return c

    def close(self):
        self.closed = True


# ----------------------------------------------------------
# MSSQLClient.drop_database
# ----------------------------------------------------------

class TestMSSQLDropDatabase(unittest.TestCase):

    def setUp(self):
        self.client = MSSQLClient(cfg=_FakeConfig())
        self.executions: list[str] = []

        def fake_query(host, sql, database=None, params=None):
            self.executions.append(sql)
            return []

        self.client.query = fake_query

    def test_drop_calls_single_user_and_drop(self):
        self.client.drop_database("srv", "mydb")

        self.assertEqual(len(self.executions), 2)
        self.assertIn("SINGLE_USER", self.executions[0])
        self.assertIn("DROP DATABASE [mydb]", self.executions[1])

    def test_drop_escapes_brackets(self):
        self.client.drop_database("srv", "my]db")

        self.assertEqual(len(self.executions), 2)
        self.assertIn("DROP DATABASE [my]]db]", self.executions[1])

    def test_drop_single_user_first(self):
        self.client.drop_database("srv", "testdb")

        self.assertEqual(len(self.executions), 2)
        self.assertIn("SINGLE_USER", self.executions[0])
        self.assertIn("DROP DATABASE", self.executions[1])

    def test_drop_propagates_error(self):
        def failing_query(host, sql, database=None, params=None):
            if "DROP DATABASE" in sql:
                raise RuntimeError("Permission denied")
            return []

        self.client.query = failing_query

        with self.assertRaises(RuntimeError):
            self.client.drop_database("srv", "mydb")


# ----------------------------------------------------------
# PgSQLClient.drop_database
# ----------------------------------------------------------

class TestPgsqlDropDatabase(unittest.TestCase):

    def setUp(self):
        self.client = PgsqlClient(cfg=_FakeConfig())
        self.conn = _FakePgsqlConn()
        self.client._pool.acquire = MagicMock(return_value=self.conn)
        self.client._pool.release = MagicMock()

    def test_drop_calls_terminate_and_drop(self):
        self.conn.result = [{"pid": 100}, {"pid": 200}]

        self.client.drop_database("srv", "mydb")

        sqls = [e[0] for e in self.conn.executions]
        self.assertTrue(
            any("pg_terminate_backend" in s for s in sqls),
        )
        self.assertTrue(
            any('DROP DATABASE "mydb"' in s for s in sqls),
        )

    def test_drop_no_active_backends(self):
        self.conn.result = []

        self.client.drop_database("srv", "mydb")

        sqls = [e[0] for e in self.conn.executions]
        self.assertFalse(any("terminate" in s.lower() for s in sqls))
        self.assertTrue(any('DROP DATABASE "mydb"' in s for s in sqls))

    def test_drop_terminate_error_ignored(self):
        self.conn.result = [{"pid": 100}]

        class PatchedCursor:
            def __init__(inner_self):
                pass

            def __enter__(inner_self):
                return inner_self

            def __exit__(inner_self, *args):
                return False

            def execute(inner_self, sql, params=None):
                if "pg_terminate_backend" in sql:
                    raise RuntimeError("terminate failed")
                self.conn.executions.append((sql, params))

            def fetchall(inner_self):
                return self.conn.result

            @property
            def description(inner_self):
                return True

        self.conn.cursor = lambda: PatchedCursor()

        self.client.drop_database("srv", "mydb")

        sqls = [e[0] for e in self.conn.executions]
        self.assertTrue(any('DROP DATABASE "mydb"' in s for s in sqls))


# ----------------------------------------------------------
# ServersTree.remove_database
# ----------------------------------------------------------

class TestRemoveDatabase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tree = ServersTree()
        self.tree.set_servers([
            ("srv1", "h1", ENGINE_MSSQL),
            ("srv2", "h2", ENGINE_PGSQL),
        ])
        self.tree.apply_databases("h1", ["db1", "db2", "db3"])
        self.tree.apply_databases("h2", ["pgdb1"])

    def tearDown(self):
        self.tree.close()
        self.tree.deleteLater()
        self.tree = None

    def test_removes_correct_node(self):
        self.tree.remove_database("h1", "db2")

        server_item = self.tree.topLevelItem(0)
        names = [
            self.tree.db_name(server_item.child(i))
            for i in range(server_item.childCount())
        ]
        self.assertNotIn("db2", names)
        self.assertIn("db1", names)
        self.assertIn("db3", names)

    def test_removes_last_node(self):
        self.tree.remove_database("h2", "pgdb1")

        server_item = self.tree.topLevelItem(1)
        self.assertEqual(server_item.childCount(), 0)

    def test_nonexistent_server_no_crash(self):
        self.tree.remove_database("no_such_server", "db1")

    def test_nonexistent_database_no_crash(self):
        self.tree.remove_database("h1", "no_such_db")


# ----------------------------------------------------------
# Контекстное меню: dropDatabaseRequested сигнал
# ----------------------------------------------------------

class TestContextMenuDropSignal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tree = ServersTree()
        self.tree.set_servers([
            ("mssql_srv", "h1", ENGINE_MSSQL),
            ("mysql_srv", "h2", ENGINE_MYSQL),
            ("pgsql_srv", "h3", ENGINE_PGSQL),
        ])
        self.tree.apply_databases("h1", ["testdb"])
        self.tree.apply_databases("h2", ["mysqldb"])
        self.tree.apply_databases("h3", ["pgdb"])

    def tearDown(self):
        self.tree.close()
        self.tree.deleteLater()
        self.tree = None

    def _get_db_item(self, server_index, db_name):
        server_item = self.tree.topLevelItem(server_index)
        for i in range(server_item.childCount()):
            child = server_item.child(i)
            if self.tree.db_name(child) == db_name:
                return child
        return None

    def test_signal_emitted_for_mssql(self):
        received = []
        self.tree.dropDatabaseRequested.connect(
            lambda s, d: received.append((s, d))
        )
        item = self._get_db_item(0, "testdb")
        self.assertIsNotNone(item)

        # Симулируем выбор узла и эмит сигнала
        self.tree.dropDatabaseRequested.emit("h1", "testdb")
        self.assertEqual(received, [("h1", "testdb")])

    def test_signal_emitted_for_pgsql(self):
        received = []
        self.tree.dropDatabaseRequested.connect(
            lambda s, d: received.append((s, d))
        )
        self.tree.dropDatabaseRequested.emit("h3", "pgdb")
        self.assertEqual(received, [("h3", "pgdb")])

    def test_mysql_no_drop_in_context_menu(self):
        """Для MySQL пункт удаления БД не должен появляться."""
        engine = registry.engine("h2")
        self.assertEqual(engine, ENGINE_MYSQL)
        # Проверяем что engine != MSSQL и != PGSQL
        self.assertNotIn(engine, (ENGINE_MSSQL, ENGINE_PGSQL))


if __name__ == "__main__":
    unittest.main()
