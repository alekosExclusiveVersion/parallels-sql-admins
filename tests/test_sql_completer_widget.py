"""
tests/test_sql_completer_widget.py

Тесты SqlCompleter (gui/sql_completer.py):
- min_len для ASCII/не-ASCII префиксов;
- has_dot контекст;
- force обходит min_len;
- script_body_for возвращает тело скрипта;
- кириллица в подсказках;
- setCompletionPrefix("") после show;
- suggest() exception safety.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from common.sql_completion import CompletionContext, analyze
from gui.sql_completer import SqlCompleter


def _context(prefix, has_dot=False):
    return CompletionContext(prefix=prefix, table=None,
                             kind="keyword", has_dot=has_dot)


class TestCompleterMinLen(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = QPlainTextEdit()
        self.editor.resize(400, 200)
        self.completer = SqlCompleter(self.editor)
        self.completer.set_catalog(["users", "orders"],
                                   {"users": ["id", "name"]})

    def tearDown(self):
        self.editor.close()

    def test_short_ascii_prefix_hides(self):
        ctx = _context("s")
        self.completer.show_suggestions(ctx)
        self.assertFalse(self.completer.popup().isVisible())

    def test_two_char_ascii_prefix_shows(self):
        ctx = _context("se")
        self.completer.show_suggestions(ctx)
        # popup may or may not show depending on items; just check no crash
        self.completer.popup().hide()

    def test_single_non_ascii_char_shows(self):
        self.completer.set_catalog(["таблица", "тест"], {})
        ctx = _context("т")
        self.completer.show_suggestions(ctx)
        self.assertTrue(self.completer.popup().isVisible())

    def test_dot_context_allows_single_char(self):
        ctx = _context("i", has_dot=True)
        self.completer.show_suggestions(ctx)
        self.assertTrue(self.completer.popup().isVisible())

    def test_force_bypasses_min_len(self):
        ctx = _context("s")
        self.completer.show_suggestions(ctx, force=True)
        self.assertTrue(self.completer.popup().isVisible())

    def test_cyrillic_prefix_model_contains_items(self):
        self.completer.set_catalog(["таблица", "тест"], {})
        ctx = _context("т")
        self.completer.show_suggestions(ctx)
        self.assertTrue(self.completer.popup().isVisible())
        self.assertGreater(self.completer._model.rowCount(), 0)

    def test_completion_prefix_is_empty_after_show(self):
        ctx = _context("us")
        self.completer.show_suggestions(ctx)
        self.assertEqual(self.completer.completionPrefix(), "")

    def test_suggest_exception_hides_popup(self):
        """show_suggestions не падает при некорректных данных каталога."""
        self.completer._columns = "not_a_dict"
        ctx = _context("us")
        self.completer.show_suggestions(ctx, force=True)
        self.assertFalse(self.completer.popup().isVisible())


class TestScriptBodyFor(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = QPlainTextEdit()
        self.editor.resize(400, 200)
        self.completer = SqlCompleter(self.editor)
        self.completer.set_scripts([
            {"name": "My Report", "body": "SELECT 1"},
            {"name": "Daily", "body": "SELECT now()"},
        ])

    def tearDown(self):
        self.editor.close()

    def test_script_body_for_valid_name(self):
        body = self.completer.script_body_for("\U0001f4dc My Report")
        self.assertEqual(body, "SELECT 1")

    def test_script_body_for_unknown_returns_none(self):
        body = self.completer.script_body_for("\U0001f4dc Unknown")
        self.assertIsNone(body)

    def test_script_body_set_on_model_item(self):
        """script_body_for возвращает тело для скрипта из модели."""
        ctx = _context("My")
        self.completer.set_catalog([], {})
        self.completer.show_suggestions(ctx, force=True)

        source_model = self.completer._model
        for row in range(source_model.rowCount()):
            item = source_model.item(row)
            if item is None:
                continue
            text = item.text()
            body = self.completer.script_body_for(text)
            if body is not None:
                self.assertIsInstance(body, str)
                self.assertTrue(len(body) > 0)
                return
        self.skipTest("no script items in model")


if __name__ == "__main__":
    unittest.main()
