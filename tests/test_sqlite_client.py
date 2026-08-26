"""
tests/test_sqlite_client.py

Тесты SQLite-клиента:
  - query / execute_on_connection
  - list_databases / list_all_databases
  - tables / columns / describe_table
  - edit_meta
  - database_sizes / database_table_sizes / server_catalog
  - drop_database
  - test_connection / server_info
  - Ошибки (несуществующий файл, невалидный SQL)
"""

import os
import sqlite3
import tempfile
import unittest

from common.sqlite_client import SQLiteClient


class _FakeConfig:
    connect_timeout = 5
    retry = 1
    pool_idle = 1
    idle_timeout = 60
    max_idle_connections = 2
    max_connections = 10
    max_per_key = 2
    acquire_timeout = 5


def _make_db(tables: dict[str, str] | None = None) -> str:
    """Создаёт временный .db файл с опциональными таблицами.

    tables: {table_name: create_sql}
    Возвращает путь к файлу.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    if tables:
        for _, ddl in tables.items():
            conn.execute(ddl)
        conn.commit()
    conn.close()
    return path


class TestSQLiteQuery(unittest.TestCase):

    def setUp(self):
        self.client = SQLiteClient(cfg=_FakeConfig())
        self.db_path = _make_db({
            "users": "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)",
        })

    def tearDown(self):
        self.client.close_all()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_query_returns_dicts(self):
        self.client.query(self.db_path, "INSERT INTO users (name) VALUES (?)", params=("Alice",))
        rows = self.client.query(self.db_path, "SELECT * FROM users")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Alice")

    def test_query_empty_table(self):
        rows = self.client.query(self.db_path, "SELECT * FROM users")
        self.assertEqual(rows, [])

    def test_query_with_params(self):
        self.client.query(self.db_path, "INSERT INTO users (name) VALUES (?)", params=("Bob",))
        self.client.query(self.db_path, "INSERT INTO users (name) VALUES (?)", params=("Charlie",))
        rows = self.client.query(
            self.db_path,
            "SELECT * FROM users WHERE name = ?",
            params=("Bob",),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Bob")


class TestSQLiteListDatabases(unittest.TestCase):

    def setUp(self):
        self.client = SQLiteClient(cfg=_FakeConfig())
        self.db_path = _make_db()

    def tearDown(self):
        self.client.close_all()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_list_databases_returns_filename(self):
        dbs = self.client.list_databases(self.db_path)
        self.assertEqual(dbs, [os.path.basename(self.db_path)])

    def test_list_databases_nonexistent(self):
        dbs = self.client.list_databases("/nonexistent/path.db")
        self.assertEqual(dbs, [])

    def test_list_all_databases_same_as_list(self):
        dbs = self.client.list_all_databases(self.db_path)
        self.assertEqual(dbs, self.client.list_databases(self.db_path))


class TestSQLiteTables(unittest.TestCase):

    def setUp(self):
        self.client = SQLiteClient(cfg=_FakeConfig())
        self.db_path = _make_db({
            "users": "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)",
            "posts": "CREATE TABLE posts (id INTEGER PRIMARY KEY, title TEXT, user_id INTEGER)",
        })

    def tearDown(self):
        self.client.close_all()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_tables_returns_sorted(self):
        tables = self.client.tables(self.db_path, "testdb")
        self.assertIn("users", tables)
        self.assertIn("posts", tables)
        self.assertEqual(tables, sorted(tables))

    def test_tables_excludes_sqlite_internal(self):
        tables = self.client.tables(self.db_path, "testdb")
        for t in tables:
            self.assertFalse(t.startswith("sqlite_"))


class TestSQLiteColumns(unittest.TestCase):

    def setUp(self):
        self.client = SQLiteClient(cfg=_FakeConfig())
        self.db_path = _make_db({
            "users": "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT)",
        })

    def tearDown(self):
        self.client.close_all()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_columns_returns_all(self):
        cols = self.client.columns(self.db_path, "testdb", "users")
        names = [c["name"] for c in cols]
        self.assertEqual(names, ["id", "name", "email"])

    def test_columns_includes_pk(self):
        cols = self.client.columns(self.db_path, "testdb", "users")
        id_col = next(c for c in cols if c["name"] == "id")
        self.assertEqual(id_col["pk"], 1)


class TestSQLiteEditMeta(unittest.TestCase):

    def setUp(self):
        self.client = SQLiteClient(cfg=_FakeConfig())
        self.db_path = _make_db({
            "users": "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)",
        })

    def tearDown(self):
        self.client.close_all()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_edit_meta_returns_pk_and_cols(self):
        pk, cols = self.client.edit_meta(self.db_path, "testdb", "users")
        self.assertEqual(pk, ["id"])
        self.assertEqual(cols, ["id", "name", "email"])

    def test_edit_meta_composite_pk(self):
        self.client.close_all()
        os.remove(self.db_path)
        self.db_path = _make_db({
            "multi": "CREATE TABLE multi (a INTEGER, b INTEGER, val TEXT, PRIMARY KEY (a, b))",
        })
        pk, cols = self.client.edit_meta(self.db_path, "testdb", "multi")
        self.assertEqual(pk, ["a", "b"])
        self.assertEqual(cols, ["a", "b", "val"])


class TestSQLiteSizes(unittest.TestCase):

    def setUp(self):
        self.client = SQLiteClient(cfg=_FakeConfig())
        self.db_path = _make_db({
            "users": "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)",
        })
        self.client.query(self.db_path, "INSERT INTO users (name) VALUES (?)", params=("Alice",))

    def tearDown(self):
        self.client.close_all()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_database_sizes_returns_file_size(self):
        sizes = self.client.database_sizes(self.db_path)
        self.assertIn(os.path.basename(self.db_path), sizes)
        self.assertGreater(sizes[os.path.basename(self.db_path)], 0)

    def test_database_table_sizes(self):
        result = self.client.database_table_sizes(self.db_path, "testdb")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "users")

    def test_server_catalog(self):
        sizes, tables = self.client.server_catalog(self.db_path)
        self.assertIn(os.path.basename(self.db_path), sizes)
        self.assertIn(os.path.basename(self.db_path), tables)


class TestSQLiteDropDatabase(unittest.TestCase):

    def setUp(self):
        self.client = SQLiteClient(cfg=_FakeConfig())

    def tearDown(self):
        self.client.close_all()

    def test_drop_database_removes_file(self):
        db_path = _make_db()
        self.assertTrue(os.path.exists(db_path))
        self.client.drop_database(db_path, "testdb")
        self.assertFalse(os.path.exists(db_path))

    def test_drop_nonexistent_no_error(self):
        self.client.drop_database("/nonexistent/path.db", "testdb")


class TestSQLiteConnection(unittest.TestCase):

    def setUp(self):
        self.client = SQLiteClient(cfg=_FakeConfig())
        self.db_path = _make_db()

    def tearDown(self):
        self.client.close_all()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_test_connection_success(self):
        ok, msg = self.client.test_connection(self.db_path, 0, "", "")
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_test_connection_failure(self):
        ok, msg = self.client.test_connection("/nonexistent/path.db", 0, "", "")
        self.assertFalse(ok)
        self.assertIn("unable to open", msg.lower())

    def test_server_info(self):
        info = self.client.server_info(self.db_path, 0, "", "")
        self.assertIn("SQLite", info)


class TestSQLiteErrors(unittest.TestCase):

    def setUp(self):
        self.client = SQLiteClient(cfg=_FakeConfig())

    def tearDown(self):
        self.client.close_all()

    def test_open_nonexistent_file_raises(self):
        with self.assertRaises(RuntimeError):
            self.client.query("/nonexistent/path.db", "SELECT 1")

    def test_invalid_sql_raises(self):
        db_path = _make_db()
        try:
            with self.assertRaises(Exception):
                self.client.query(db_path, "NOT VALID SQL AT ALL")
        finally:
            os.remove(db_path)


class TestSQLiteEngineConstant(unittest.TestCase):

    def test_engine_sqlite_exists(self):
        from common.server_registry import ENGINE_SQLITE
        self.assertEqual(ENGINE_SQLITE, "sqlite")


if __name__ == "__main__":
    unittest.main()
