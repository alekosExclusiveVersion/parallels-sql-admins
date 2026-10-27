"""
tests/test_mssql_client.py

Тесты common/mssql_client.py:
- test_connection: success, failure, close always called;
- server_info: dict cursor, non-dict cursor, empty result, exception, close always.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from common.mssql_client import MSSQLClient


class _FakeConfig:
    connect_timeout = 5
    acquire_timeout = 5
    max_connections = 10
    max_per_key = 3
    pool_idle = 1
    idle_timeout = 60
    max_idle_connections = 2
    retry = 1
    user = "u"
    password = "p"
    port = 1433


class TestMSSQLTestConnection(unittest.TestCase):

    def setUp(self):
        self.client = MSSQLClient(cfg=_FakeConfig())

    @patch("common.mssql_client.pymssql.connect")
    def test_success(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        ok, msg = self.client.test_connection(
            host="h", port=1433, user="u", password="p",
        )
        self.assertTrue(ok)
        self.assertEqual(msg, "")
        mock_conn.close.assert_called_once()

    @patch("common.mssql_client.pymssql.connect")
    def test_failure(self, mock_connect):
        mock_connect.side_effect = RuntimeError("connection refused")

        ok, msg = self.client.test_connection(
            host="h", port=1433, user="u", password="p",
        )
        self.assertFalse(ok)
        self.assertIn("connection refused", msg)

    @patch("common.mssql_client.pymssql.connect")
    def test_close_always_called(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        self.client.test_connection("h", 1433, "u", "p")
        mock_conn.close.assert_called_once()

    @patch("common.mssql_client.pymssql.connect")
    def test_close_called_on_exception(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        ok, msg = self.client.test_connection("h", 1433, "u", "p")
        self.assertTrue(ok)
        mock_conn.close.assert_called_once()


class TestMSSQLDatabaseSizes(unittest.TestCase):

    def setUp(self):
        self.client = MSSQLClient(cfg=_FakeConfig())

    def _patched(self, ignore):
        cfg = SimpleNamespace(
            advanced=SimpleNamespace(ignore_databases=ignore)
        )
        return patch("common.mssql_client.config", cfg)

    def test_size_counts_data_files_only(self):
        captured = {}

        def fake_query(host, sql):
            captured["sql"] = sql
            return [{"db": "vinpart", "total_bytes": 8 * 1024 * 2}]

        with patch.object(self.client, "query", side_effect=fake_query), \
             self._patched(set()):
            sizes = self.client.database_sizes("h")

        self.assertEqual(sizes, {"vinpart": 8 * 1024 * 2})
        joined = " ".join(captured["sql"].split())
        self.assertIn("type = 0", joined)

    def test_database_files_returns_rows(self):
        captured = {}

        def fake_query(host, sql, database=None):
            captured["database"] = database
            return [
                {"type_desc": "ROWS", "name": "vinpart_base",
                 "physical_name": "d:\\data\\vinpart.mdf",
                 "bytes": 52_095_901_696},
                {"type_desc": "LOG", "name": "vinpart_log",
                 "physical_name": "d:\\data\\vinpart.ldf", "bytes": 8_388_608},
            ]

        with patch.object(self.client, "query", side_effect=fake_query):
            files = self.client.database_files("h", "vinpart")

        self.assertEqual(captured["database"], "vinpart")
        self.assertEqual(files, [
            {"type": "ROWS", "name": "vinpart_base",
             "file": "d:\\data\\vinpart.mdf", "bytes": 52_095_901_696},
            {"type": "LOG", "name": "vinpart_log",
             "file": "d:\\data\\vinpart.ldf", "bytes": 8_388_608},
        ])

    def test_size_excludes_ignored_databases(self):
        def fake_query(host, sql):
            return [
                {"db": "prod", "total_bytes": 8 * 1024},
                {"db": "skipped", "total_bytes": 8 * 1024},
            ]

        with patch.object(self.client, "query", side_effect=fake_query), \
             self._patched({"skipped"}):
            sizes = self.client.database_sizes("h")

        self.assertEqual(sizes, {"prod": 8 * 1024})


class TestMSSQLServerInfo(unittest.TestCase):

    def setUp(self):
        self.client = MSSQLClient(cfg=_FakeConfig())

    @patch("common.mssql_client.pymssql.connect")
    def test_dict_cursor(self, mock_connect):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"v": "Microsoft SQL Server 2019\nLine 2"}]
        mock_cursor.fetchone.return_value = {"v": "Microsoft SQL Server 2019\nLine 2"}

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = self.client.server_info("h", 1433, "u", "p")
        self.assertEqual(result, "Microsoft SQL Server 2019")
        mock_conn.close.assert_called_once()

    @patch("common.mssql_client.pymssql.connect")
    def test_non_dict_cursor_returns_empty(self, mock_connect):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("Microsoft SQL Server 2019",)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = self.client.server_info("h", 1433, "u", "p")
        self.assertEqual(result, "")
        mock_conn.close.assert_called_once()

    @patch("common.mssql_client.pymssql.connect")
    def test_empty_result(self, mock_connect):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = self.client.server_info("h", 1433, "u", "p")
        self.assertEqual(result, "")
        mock_conn.close.assert_called_once()

    @patch("common.mssql_client.pymssql.connect")
    def test_exception_swallows(self, mock_connect):
        mock_connect.side_effect = RuntimeError("timeout")

        result = self.client.server_info("h", 1433, "u", "p")
        self.assertEqual(result, "")

    @patch("common.mssql_client.pymssql.connect")
    def test_close_always_called(self, mock_connect):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = RuntimeError("broken pipe")

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = self.client.server_info("h", 1433, "u", "p")
        self.assertEqual(result, "")
        mock_conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
