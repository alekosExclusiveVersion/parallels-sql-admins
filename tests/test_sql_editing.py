"""
tests/test_sql_editing.py

Тесты для common/sql_editing.py — разбор простых SELECT для редактирования
ячеек Results и построение безопасных UPDATE по первичному ключу.
"""

import unittest

from common.sql_editing import (
    build_update_sql,
    parse_select_table,
    quote_literal,
)


class TestParseSelectTable(unittest.TestCase):
    def test_simple_select(self):
        self.assertEqual(
            parse_select_table("SELECT id, name FROM users"),
            "users",
        )

    def test_select_with_where_order_limit(self):
        sql = (
            "SELECT id, name FROM users WHERE age > 18 "
            "ORDER BY id LIMIT 100"
        )
        self.assertEqual(parse_select_table(sql), "users")

    def test_trailing_semicolon(self):
        self.assertEqual(
            parse_select_table("SELECT * FROM users;"),
            "users",
        )

    def test_backtick_quoted_table(self):
        self.assertEqual(
            parse_select_table("SELECT * FROM `users` WHERE id = 1"),
            "users",
        )

    def test_keywords_in_column_name_not_trigger(self):
        sql = "SELECT from_id, join_note FROM orders"
        self.assertEqual(parse_select_table(sql), "orders")

    def test_keyword_in_string_ignored(self):
        sql = "SELECT 'from x JOIN y' AS t FROM users"
        self.assertEqual(parse_select_table(sql), "users")

    def test_join_rejected(self):
        sql = "SELECT * FROM a INNER JOIN b ON a.id = b.id"
        self.assertIsNone(parse_select_table(sql))

    def test_left_join_rejected(self):
        sql = "SELECT * FROM a LEFT JOIN b ON a.id = b.id"
        self.assertIsNone(parse_select_table(sql))

    def test_group_by_rejected(self):
        sql = "SELECT country, COUNT(*) FROM users GROUP BY country"
        self.assertIsNone(parse_select_table(sql))

    def test_having_rejected(self):
        sql = (
            "SELECT country FROM users GROUP BY country "
            "HAVING COUNT(*) > 1"
        )
        self.assertIsNone(parse_select_table(sql))

    def test_distinct_rejected(self):
        sql = "SELECT DISTINCT name FROM users"
        self.assertIsNone(parse_select_table(sql))

    def test_union_rejected(self):
        sql = "SELECT id FROM a UNION SELECT id FROM b"
        self.assertIsNone(parse_select_table(sql))

    def test_subquery_parens_rejected(self):
        sql = "SELECT * FROM (SELECT id FROM users) AS u"
        self.assertIsNone(parse_select_table(sql))

    def test_multiple_statements_rejected(self):
        sql = "SELECT * FROM users; SELECT * FROM admins"
        self.assertIsNone(parse_select_table(sql))

    def test_qualified_table_name_rejected(self):
        sql = "SELECT * FROM db.users"
        self.assertIsNone(parse_select_table(sql))

    def test_not_select_rejected(self):
        self.assertIsNone(parse_select_table("UPDATE users SET a = 1"))
        self.assertIsNone(parse_select_table("DELETE FROM users"))

    def test_empty_rejected(self):
        self.assertIsNone(parse_select_table(""))
        self.assertIsNone(parse_select_table("  "))

    def test_table_keyword_in_where_ignored(self):
        sql = "SELECT * FROM users WHERE name = 'from group'"
        self.assertEqual(parse_select_table(sql), "users")


class TestQuoteLiteral(unittest.TestCase):
    def test_none(self):
        self.assertEqual(quote_literal(None), "NULL")

    def test_bool(self):
        self.assertEqual(quote_literal(True), "1")
        self.assertEqual(quote_literal(False), "0")

    def test_int(self):
        self.assertEqual(quote_literal(5), "5")

    def test_float(self):
        self.assertEqual(quote_literal(3.14), "3.14")

    def test_text_null_becomes_null(self):
        self.assertEqual(quote_literal("NULL"), "NULL")
        self.assertEqual(quote_literal(" null "), "NULL")

    def test_plain_string(self):
        self.assertEqual(quote_literal("hello"), "'hello'")

    def test_string_escapes_single_quote(self):
        self.assertEqual(quote_literal("O'Reilly"), "'O''Reilly'")

    def test_numeric_string_stays_quoted(self):
        self.assertEqual(quote_literal("123"), "'123'")


class TestBuildUpdateSql(unittest.TestCase):
    def test_mysql(self):
        sql = build_update_sql(
            "mysql",
            "users",
            "name",
            "Bob",
            [("id", "7")],
        )
        self.assertEqual(
            sql,
            "UPDATE `users` SET `name` = 'Bob' WHERE `id` = '7'",
        )

    def test_mssql(self):
        sql = build_update_sql(
            "mssql",
            "users",
            "age",
            31,
            [("id", "7")],
        )
        self.assertEqual(
            sql,
            "UPDATE [users] SET [age] = 31 WHERE [id] = '7'",
        )

    def test_pgsql(self):
        sql = build_update_sql(
            "pgsql",
            "users",
            "name",
            None,
            [("id", "7"), ("tenant", "acme")],
        )
        self.assertEqual(
            sql,
            'UPDATE "users" SET "name" = NULL '
            'WHERE "id" = \'7\' AND "tenant" = \'acme\'',
        )

    def test_quotes_in_identity_escaped(self):
        sql = build_update_sql(
            "mysql",
            "users",
            "name",
            "x",
            [("id", "O'Reilly")],
        )
        self.assertIn("`id` = 'O''Reilly'", sql)

    def test_empty_identity_raises(self):
        with self.assertRaises(ValueError):
            build_update_sql("mysql", "users", "name", "x", [])


if __name__ == "__main__":
    unittest.main()
