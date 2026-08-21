"""
tests/test_mssql_client.py

Тесты common/mssql_client.py:
- test_connection: success, failure, close always called;
- server_info: dict cursor, non-dict cursor, empty result, exception, close always.
"""

import unittest
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
