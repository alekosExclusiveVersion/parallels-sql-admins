"""
tests/test_completion_worker.py

Тесты чистых функций completion_worker:
- parse_catalog() — дедупликация таблиц, группировка колонок;
- build_metadata_queries() — генерация SQL для MySQL и MSSQL.
"""

import unittest

from unittest.mock import patch

from backend.completion_worker import build_metadata_queries, parse_catalog


class TestParseCatalog(unittest.TestCase):

    def test_deduplicates_tables(self):
        tables_rows = [
            {"TABLE_NAME": "orders"},
            {"TABLE_NAME": "orders"},
            {"TABLE_NAME": "products"},
        ]
        columns_rows = []

        tables, columns = parse_catalog(tables_rows, columns_rows)

        self.assertEqual(tables, ["orders", "products"])

    def test_groups_columns_by_table(self):
        tables_rows = [{"TABLE_NAME": "orders"}]
        columns_rows = [
            {"TABLE_NAME": "orders", "COLUMN_NAME": "id"},
            {"TABLE_NAME": "orders", "COLUMN_NAME": "name"},
            {"TABLE_NAME": "orders", "COLUMN_NAME": "created_at"},
        ]

        tables, columns = parse_catalog(tables_rows, columns_rows)

        self.assertEqual(columns["orders"], ["created_at", "id", "name"])

    def test_empty_input(self):
        tables, columns = parse_catalog([], [])

        self.assertEqual(tables, [])
        self.assertEqual(columns, {})


class TestBuildMetadataQueries(unittest.TestCase):

    @patch("backend.completion_worker.registry")
    def test_mysql_queries_filter_by_schema(self, mock_registry):
        mock_registry.engine.return_value = "mysql"

        queries, engine = build_metadata_queries("srv1", "ar_test")

        self.assertEqual(engine, "mysql")
        self.assertEqual(len(queries), 2)
        tables_sql = queries[0][1]
        columns_sql = queries[1][1]
        self.assertIn("TABLE_SCHEMA = %s", tables_sql)
        self.assertIn("TABLE_SCHEMA = %s", columns_sql)
        self.assertEqual(queries[0][2], ("ar_test",))

    @patch("backend.completion_worker.registry")
    def test_mssql_queries_no_schema_filter(self, mock_registry):
        mock_registry.engine.return_value = "mssql"

        queries, engine = build_metadata_queries("srv1", "ar_test")

        self.assertEqual(engine, "mssql")
        self.assertEqual(len(queries), 2)
        tables_sql = queries[0][1]
        self.assertNotIn("TABLE_SCHEMA", tables_sql)
        self.assertIsNone(queries[0][2])


if __name__ == "__main__":
    unittest.main()
