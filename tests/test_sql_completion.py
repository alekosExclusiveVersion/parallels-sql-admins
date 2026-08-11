"""
tests/test_sql_completion.py

Чистая логика автодополнения: определение контекста (analyze),
формирование подсказок (suggest) и построение запросов каталога
(build_metadata_queries / parse_catalog).
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from common.sql_completion import (
    KIND_COLUMN,
    KIND_KEYWORD,
    KIND_TABLE,
    analyze,
    suggest,
)
from backend.completion_worker import parse_catalog


TABLES = ["users", "orders", "payments"]
COLUMNS = {
    "users": ["id", "name", "email"],
    "orders": ["id", "user_id", "total"],
    "payments": ["id", "order_id", "amount"],
}

_MARKER = "\u25c8"  # позиция курсора


def ctx(marked: str):
    """analyze() по строке с маркером курсора."""
    position = marked.index(_MARKER)
    return analyze(marked.replace(_MARKER, ""), position)


class TestAnalyze(unittest.TestCase):

    def test_empty_text(self):
        c = ctx(_MARKER)
        self.assertEqual(c.kind, KIND_KEYWORD)
        self.assertEqual(c.prefix, "")
        self.assertFalse(c.has_dot)

    def test_keyword_prefix(self):
        c = ctx(f"SEL{_MARKER}")
        self.assertEqual(c.kind, KIND_KEYWORD)
        self.assertEqual(c.prefix, "SEL")

    def test_table_after_from(self):
        c = ctx(f"SELECT * FROM us{_MARKER}")
        self.assertEqual(c.kind, KIND_TABLE)
        self.assertEqual(c.prefix, "us")

    def test_table_after_join(self):
        c = ctx(f"SELECT * FROM users JOIN ord{_MARKER}")
        self.assertEqual(c.kind, KIND_TABLE)
        self.assertEqual(c.prefix, "ord")

    def test_column_after_dot(self):
        c = ctx(f"SELECT users.n{_MARKER} FROM users")
        self.assertEqual(c.kind, KIND_COLUMN)
        self.assertEqual(c.table, "users")
        self.assertEqual(c.prefix, "n")
        self.assertTrue(c.has_dot)

    def test_column_after_dot_qualified_table(self):
        c = ctx(f"SELECT ar_db.users.na{_MARKER} FROM users")
        self.assertEqual(c.kind, KIND_COLUMN)
        self.assertEqual(c.table, "ar_db.users")
        self.assertEqual(c.prefix, "na")

    def test_column_after_empty_dot(self):
        c = ctx(f"SELECT users.{_MARKER} FROM users")
        self.assertEqual(c.kind, KIND_COLUMN)
        self.assertEqual(c.table, "users")
        self.assertEqual(c.prefix, "")

    def test_not_a_trigger_keyword(self):
        # "FROMX" — не ключевое слово; перед курсором только OFFSET.
        c = ctx(f"OFFSET {_MARKER}FROMX")
        self.assertEqual(c.kind, KIND_KEYWORD)

    def test_mid_word_cursor(self):
        c = ctx(f"SELECT * FROM us{_MARKER}e")
        self.assertEqual(c.kind, KIND_TABLE)
        self.assertEqual(c.prefix, "us")


class TestSuggest(unittest.TestCase):

    def test_table_context(self):
        items = suggest(
            ctx("SELECT * FROM us" + _MARKER), tables=TABLES, columns=COLUMNS
        )
        self.assertEqual(items, [("users", KIND_TABLE)])

    def test_table_context_no_match(self):
        items = suggest(
            ctx("SELECT * FROM zz" + _MARKER), tables=TABLES, columns=COLUMNS
        )
        self.assertEqual(items, [])

    def test_column_context_known_table(self):
        items = suggest(
            ctx("SELECT users.e" + _MARKER + " FROM users"),
            tables=TABLES, columns=COLUMNS,
        )
        self.assertEqual(items, [("email", KIND_COLUMN)])

    def test_column_context_other_table_not_leaked(self):
        items = suggest(
            ctx("SELECT users.na" + _MARKER + " FROM users"),
            tables=TABLES, columns=COLUMNS,
        )
        names = [text for text, _ in items]
        self.assertIn("name", names)
        self.assertNotIn("total", names)

    def test_column_context_unknown_table_all_columns(self):
        items = suggest(
            ctx("SELECT foo.i" + _MARKER + " FROM foo"),
            tables=TABLES, columns=COLUMNS,
        )
        names = [text for text, _ in items]
        self.assertEqual(names, ["id"])

    def test_keyword_context(self):
        items = suggest(
            ctx("SE" + _MARKER),
            keywords=["SELECT", "SET", "UPDATE"],
        )
        self.assertEqual(
            items,
            [("SELECT", KIND_KEYWORD), ("SET", KIND_KEYWORD)],
        )

    def test_keyword_context_also_tables_and_columns(self):
        items = suggest(
            ctx("us" + _MARKER), tables=TABLES, columns=COLUMNS
        )
        kinds = {kind for _, kind in items}
        self.assertIn(KIND_TABLE, kinds)
        self.assertIn(KIND_COLUMN, kinds)

    def test_case_insensitive(self):
        items = suggest(
            ctx("SELECT * FROM USE" + _MARKER), tables=TABLES, columns=COLUMNS
        )
        self.assertEqual(items, [("users", KIND_TABLE)])

    def test_dedupe_columns(self):
        items = suggest(ctx("i" + _MARKER), tables=TABLES, columns=COLUMNS)
        names = [text for text, kind in items if kind == KIND_COLUMN]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("id", names)

    def test_default_keywords_used(self):
        items = suggest(ctx("SEL" + _MARKER))
        self.assertIn(("SELECT", KIND_KEYWORD), items)


class TestCatalogQueries(unittest.TestCase):

    def test_parse_catalog(self):
        tables, columns = parse_catalog(
            [{"TABLE_NAME": "orders"}, {"TABLE_NAME": "users"}],
            [
                {"TABLE_NAME": "users", "COLUMN_NAME": "name"},
                {"TABLE_NAME": "users", "COLUMN_NAME": "id"},
                {"TABLE_NAME": "orders", "COLUMN_NAME": "id"},
            ],
        )
        self.assertEqual(tables, ["orders", "users"])
        self.assertEqual(columns["users"], ["id", "name"])
        self.assertEqual(columns["orders"], ["id"])


if __name__ == "__main__":
    unittest.main()
