"""
tests/test_mysql_update_times.py

Тесты database_update_times() — самый багоопасный метод:
- update_time из information_schema.tables (NULL / stale для InnoDB);
- known-pattern fallback через information_schema.columns + UNION ALL MAX(col);
- батчинг UNION ALL по 50, graceful fallback при ошибке батча;
- graceful fallback при ошибке запроса.
"""

import unittest
from datetime import datetime
from unittest.mock import patch

from common.mysql_client import MySQLClient


class TestDatabaseUpdateTimes(unittest.TestCase):

    def _make_client(self):
        client = MySQLClient()
        client._update_times_cache.clear()
        return client

    def test_returns_timestamp_when_update_time_present(self):
        client = self._make_client()
        now = datetime(2026, 8, 20, 12, 0, 0)

        with patch.object(client, "query") as mock_q:
            mock_q.return_value = [
                {"db": "ar_test", "last_update": now, "total_size": 1000}
            ]
            result = client.database_update_times("srv1", ["ar_test"])

        self.assertEqual(result, {"ar_test": "2026-08-20 12:00:00"})
        self.assertEqual(mock_q.call_count, 1)

    def test_returns_empty_when_null_and_no_data(self):
        client = self._make_client()

        with patch.object(client, "query") as mock_q:
            def side_effect(host, sql, database=None, params=None):
                if "information_schema.tables" in sql:
                    return [{"db": "ar_test", "last_update": None, "total_size": 0}]
                return []

            mock_q.side_effect = side_effect
            result = client.database_update_times("srv1", ["ar_test"])

        self.assertNotIn("ar_test", result)

    def test_stale_triggers_known_pattern(self):
        client = self._make_client()
        stale_time = datetime(2025, 1, 1, 0, 0, 0)

        with patch.object(client, "query") as mock_q:
            def side_effect(host, sql, database=None, params=None):
                if "information_schema.tables" in sql:
                    return [{"db": "ar_test", "last_update": stale_time, "total_size": 5000}]
                if "information_schema.columns" in sql:
                    return [{"db": "ar_test", "tbl": "orders", "col": "created_at"}]
                return [{"db": "ar_test", "act": datetime(2026, 8, 20, 10, 0, 0)}]

            mock_q.side_effect = side_effect
            result = client.database_update_times("srv1", ["ar_test"])

        self.assertEqual(result["ar_test"], "2026-08-20 10:00:00")

    def test_known_pattern_takes_max_multiple_columns(self):
        client = self._make_client()
        stale_time = datetime(2025, 1, 1, 0, 0, 0)

        with patch.object(client, "query") as mock_q:
            def side_effect(host, sql, database=None, params=None):
                if "information_schema.tables" in sql:
                    return [{"db": "ar_test", "last_update": stale_time, "total_size": 5000}]
                if "information_schema.columns" in sql:
                    return [
                        {"db": "ar_test", "tbl": "orders", "col": "created_at"},
                        {"db": "ar_test", "tbl": "products", "col": "ste_datetime"},
                    ]
                return [
                    {"db": "ar_test", "act": datetime(2026, 8, 20, 10, 0, 0)},
                    {"db": "ar_test", "act": datetime(2026, 7, 1, 8, 0, 0)},
                ]

            mock_q.side_effect = side_effect
            result = client.database_update_times("srv1", ["ar_test"])

        self.assertEqual(result["ar_test"], "2026-08-20 10:00:00")

    def test_union_batch_error_continues(self):
        client = self._make_client()
        stale_time = datetime(2025, 1, 1, 0, 0, 0)

        with patch.object(client, "query") as mock_q:
            call_count = [0]

            def side_effect(host, sql, database=None, params=None):
                call_count[0] += 1
                if "information_schema.tables" in sql:
                    return [{"db": "ar_test", "last_update": stale_time, "total_size": 5000}]
                if "information_schema.columns" in sql:
                    return [
                        {"db": "ar_test", "tbl": f"t{i}", "col": "created_at"}
                        for i in range(100)
                    ]
                if call_count[0] == 3:
                    raise RuntimeError("batch fail")
                return [{"db": "ar_test", "act": datetime(2026, 8, 20, 10, 0, 0)}]

            mock_q.side_effect = side_effect
            result = client.database_update_times("srv1", ["ar_test"])

        self.assertEqual(result["ar_test"], "2026-08-20 10:00:00")

    def test_empty_databases_returns_empty(self):
        client = self._make_client()
        result = client.database_update_times("srv1", [])
        self.assertEqual(result, {})

    def test_exception_returns_empty_dict(self):
        client = self._make_client()

        with patch.object(client, "query", side_effect=RuntimeError("conn refused")):
            result = client.database_update_times("srv1", ["ar_test"])

        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
