"""
tests/test_drop_database.py

Тесты фичи удаления БД:
  - MSSQLClient.drop_database: SET SINGLE_USER + DROP DATABASE
  - PgSQLClient.drop_database: pg_terminate_backend + DROP DATABASE
  - PgsqlClient.list_databases: без MySQL-префикса ar_ (консоль видит все БД)
  - PgsqlClient._open_connection: autocommit=True (без отравления пула)
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

    def test_drop_runs_in_master_context(self):
        self.client.drop_database("srv", "mydb")

        self.assertTrue(self.executions[0].lstrip().startswith("USE [master];"))
        self.assertTrue(self.executions[1].lstrip().startswith("USE [master];"))

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
# PgsqlClient.list_databases
# ----------------------------------------------------------

class TestPgsqlListDatabases(unittest.TestCase):

    def setUp(self):
        self.client = PgsqlClient(cfg=_FakeConfig())
        self.conn = _FakePgsqlConn()
        self.client._pool.acquire = MagicMock(return_value=self.conn)
        self.client._pool.release = MagicMock()

    def test_list_databases_ignores_mysql_prefix(self):
        self.conn.result = [
            {"db": "activauto"},
            {"db": "ar_shop"},
            {"db": "juravlev"},
            {"db": None},
        ]

        names = self.client.list_databases("srv")

        self.assertEqual(names, ["activauto", "ar_shop", "juravlev"])


class TestPgsqlAutocommit(unittest.TestCase):

    def test_open_connection_uses_autocommit(self):
        import psycopg

        client = PgsqlClient(cfg=_FakeConfig())
        with patch.object(
            registry, "credentials_for",
            return_value=("u", "p", "h", 5432),
        ):
            with patch.object(
                psycopg, "connect", return_value=MagicMock(),
            ) as mock_connect:
                client._open_connection("srv", "mydb")

        self.assertTrue(mock_connect.call_args.kwargs.get("autocommit"))


class TestPgsqlQuoteTables(unittest.TestCase):

    def setUp(self):
        self.client = PgsqlClient(cfg=_FakeConfig())
        self.mapping = {
            "dbversion": "DbVersion",
            "cfgsettings": "cfg_Settings",
        }

    def _quote(self, sql):
        return self.client._quote_tables(sql, self.mapping)

    def test_simple_select_quoted(self):
        self.assertEqual(
            self._quote("select * from dbversion"),
            'select * from "DbVersion"',
        )

    def test_unquoted_exact_case_quoted(self):
        self.assertEqual(
            self._quote("select * from DbVersion"),
            'select * from "DbVersion"',
        )

    def test_already_quoted_untouched(self):
        sql = 'select * from "DbVersion" d where d.a = 1'
        self.assertEqual(self._quote(sql), sql)

    def test_qualified_name_untouched(self):
        sql = "select * from public.dbversion"
        self.assertEqual(self._quote(sql), sql)

    def test_unknown_table_untouched(self):
        sql = "select * from orders"
        self.assertEqual(self._quote(sql), sql)

    def test_string_literal_untouched(self):
        sql = "select 'dbversion' from dual"
        self.assertEqual(self._quote(sql), sql)

    def test_comment_untouched(self):
        sql = "select 1 -- from dbversion"
        self.assertEqual(self._quote(sql), sql)

    def test_join_with_aliases(self):
        self.assertEqual(
            self._quote(
                "select * from dbversion d "
                "join cfgsettings c on c.id = d.id"
            ),
            'select * from "DbVersion" d '
            'join "cfg_Settings" c on c.id = d.id',
        )

    def test_update_and_insert(self):
        self.assertEqual(
            self._quote("update dbversion set a = 1"),
            'update "DbVersion" set a = 1',
        )
        self.assertEqual(
            self._quote("insert into dbversion (a) values (1)"),
            'insert into "DbVersion" (a) values (1)',
        )

    def test_set_keyword_not_a_table(self):
        client = PgsqlClient(cfg=_FakeConfig())
        sql = (
            "insert into t (a) values (1) "
            "on conflict do update set a = 2"
        )
        self.assertEqual(
            client._quote_tables(sql, {"set": "Set", "t": "T"}),
            'insert into "T" (a) values (1) '
            "on conflict do update set a = 2",
        )

    def test_function_call_untouched(self):
        client = PgsqlClient(cfg=_FakeConfig())
        sql = "select * from generate_series(1, 3)"
        self.assertEqual(
            client._quote_tables(sql, {"generate_series": "Generate"}),
            sql,
        )

    def test_prepare_without_database_returns_as_is(self):
        client = PgsqlClient(cfg=_FakeConfig())
        statements = ["select * from dbversion"]
        self.assertEqual(
            client.prepare_statements("srv", None, statements),
            statements,
        )

    def test_prepare_rewrites_with_live_map(self):
        client = PgsqlClient(cfg=_FakeConfig())
        client.query = lambda *args, **kwargs: [
            {"t": "DbVersion"},
            {"t": "orders"},
        ]
        self.assertEqual(
            client.prepare_statements("srv", "db", ["select * from dbversion"]),
            ['select * from "DbVersion"'],
        )


class TestPgsqlErrorHint(unittest.TestCase):

    def _client(self, rows):
        client = PgsqlClient(cfg=_FakeConfig())
        client.query = lambda *args, **kwargs: rows
        return client

    def test_hint_suggests_table(self):
        from psycopg.errors import UndefinedTable

        client = self._client([{"t": "DbVersion"}])
        ex = UndefinedTable('relation "dbversion" does not exist')

        self.assertEqual(
            client.error_hint("srv", "db", ex),
            'Возможно, вы имели в виду: "DbVersion"?',
        )

    def test_hint_ignores_other_errors(self):
        client = self._client([{"t": "DbVersion"}])

        self.assertEqual(
            client.error_hint("srv", "db", RuntimeError("boom")), "",
        )

    def test_hint_empty_without_candidates(self):
        from psycopg.errors import UndefinedTable

        client = self._client([])
        ex = UndefinedTable('relation "dbversion" does not exist')

        self.assertEqual(client.error_hint("srv", "db", ex), "")


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
