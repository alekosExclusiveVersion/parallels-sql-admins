"""
tests/test_result_table.py

Тесты Results: кликабельность шапки (сортировка по клику на кастомной
RoundedHeader) и фильтры контекстного меню шапки «пустые/не пустые»
(видимость строк в apply_filters, взаимное исключение фильтров колонки,
«Снять фильтр колонки»).
"""

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gui.result_table import ResultTable


class ResultTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.table = ResultTable()
        self.table.setup_columns(
            ["Source", "Server", "Database", "Value"],
            {0: 64, 1: 190, 2: 160},
        )

    def _add(self, values):
        self.table.add_row(values)

    def _visible_rows(self):
        return [
            i for i in range(self.table.rowCount())
            if not self.table.isRowHidden(i)
        ]

    def test_header_clickable_and_sort_indicator(self):
        header = self.table.horizontalHeader()
        self.assertTrue(self.table.isSortingEnabled())
        self.assertTrue(header.sectionsClickable())
        self.assertTrue(header.isSortIndicatorShown())

    def test_header_context_menu_attached(self):
        header = self.table.horizontalHeader()
        self.assertEqual(header.contextMenuPolicy().name, "CustomContextMenu")
        self.assertTrue(hasattr(self.table, "_show_header_menu"))

    def test_no_filters_keeps_all_rows_visible(self):
        self._add(["SQL", "h", "db", "a"])
        self._add(["SQL", "h", "db", ""])
        self.table.apply_filters()
        self.assertEqual(self._visible_rows(), [0, 1])

    def test_empty_filter_keeps_only_empty(self):
        self._add(["SQL", "h", "db", "a"])
        self._add(["SQL", "h", "db", ""])
        self._add(["SQL", "h", "db", "   "])
        self._add(["SQL", "h", "db", "b"])

        self.table._toggle_empty_filter(3, True)

        self.assertEqual(self._visible_rows(), [1, 2])
        self.assertIn(3, self.table._empty_filter_columns)
        self.assertNotIn(3, self.table._nonempty_filter_columns)

    def test_nonempty_filter_keeps_only_nonempty(self):
        self._add(["SQL", "h", "db", "a"])
        self._add(["SQL", "h", "db", ""])
        self._add(["SQL", "h", "db", "b"])

        self.table._toggle_nonempty_filter(3, True)

        self.assertEqual(self._visible_rows(), [0, 2])
        self.assertIn(3, self.table._nonempty_filter_columns)
        self.assertNotIn(3, self.table._empty_filter_columns)

    def test_empty_and_nonempty_are_mutually_exclusive(self):
        self._add(["SQL", "h", "db", "a"])
        self._add(["SQL", "h", "db", ""])

        self.table._toggle_empty_filter(3, True)
        self.table._toggle_nonempty_filter(3, True)

        self.assertNotIn(3, self.table._empty_filter_columns)
        self.assertIn(3, self.table._nonempty_filter_columns)
        self.assertEqual(self._visible_rows(), [0])

    def test_clear_column_filter_restores_all(self):
        self._add(["SQL", "h", "db", "a"])
        self._add(["SQL", "h", "db", ""])

        self.table._toggle_nonempty_filter(3, True)
        self.assertEqual(self._visible_rows(), [0])

        self.table._clear_column_filter(3)

        self.assertEqual(self._visible_rows(), [0, 1])
        self.assertNotIn(3, self.table._nonempty_filter_columns)
        self.assertEqual(self.table.filter_header.get_filters()[3], "")

    def test_filter_combines_with_contains_filter(self):
        self._add(["SQL", "h", "db", "aa"])
        self._add(["SQL", "h", "db", ""])
        self._add(["SQL", "h", "db", "bb"])

        # contains-фильтр «a» по колонке 3
        edit = self.table.filter_header._edits[3]
        edit.setText("a")

        self.table._toggle_nonempty_filter(3, True)

        # Строка "aa" непустая и содержит "a"; "bb" непустая, но не содержит.
        self.assertEqual(self._visible_rows(), [0])

    def test_sync_filter_columns_resets_empty_flags(self):
        self._add(["SQL", "h", "db", "a"])
        self.table._toggle_empty_filter(3, True)
        self.assertIn(3, self.table._empty_filter_columns)

        self.table.sync_filter_columns()

        self.assertNotIn(3, self.table._empty_filter_columns)
        self.assertNotIn(3, self.table._nonempty_filter_columns)

    def test_reset_table_resets_empty_flags(self):
        self._add(["SQL", "h", "db", "a"])
        self.table._toggle_empty_filter(3, True)

        self.table.reset_table()

        self.assertEqual(self.table._empty_filter_columns, set())

    def test_sort_by_column_changes_row_order(self):
        self._add(["SQL", "h", "db", "2"])
        self._add(["SQL", "h", "db", "10"])
        self._add(["SQL", "h", "db", "1"])

        self.table.sortByColumn(3, Qt.AscendingOrder)

        self.assertEqual(self.table.item(0, 3).text(), "1")
        self.assertEqual(self.table.item(1, 3).text(), "10")
        self.assertEqual(self.table.item(2, 3).text(), "2")


class TestMarkWorkingDatabases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_table(self):
        table = ResultTable()
        table.setup_columns(
            ["Server", "Database", "Последнее обновление", "Статус"],
            {0: 190, 1: 160, 2: 160, 3: 100},
        )
        return table

    def _status_text(self, table, row):
        idx = table.column_index("Статус")
        return table.item(row, idx).text()

    def test_mark_today_shows_working(self):
        table = self._make_table()
        today = time.strftime("%Y-%m-%d")
        table.add_row(["srv1", "ar_test", f"{today} 12:00:00", ""])

        table.mark_working_databases()

        self.assertEqual(self._status_text(table, 0), "● Рабочая")

    def test_mark_old_date_shows_date(self):
        table = self._make_table()
        table.add_row(["srv1", "ar_test", "2025-01-15 08:30:00", ""])

        table.mark_working_databases()

        self.assertEqual(self._status_text(table, 0), "2025-01-15")

    def test_mark_empty_shows_dash(self):
        table = self._make_table()
        table.add_row(["srv1", "ar_test", "", ""])

        table.mark_working_databases()

        self.assertEqual(self._status_text(table, 0), "—")

    def test_mark_none_ts_shows_dash(self):
        table = self._make_table()
        table.add_row(["srv1", "ar_test", "", ""])
        ts_idx = table.column_index("Последнее обновление")
        table.item(0, ts_idx).setText("")

        table.mark_working_databases()

        self.assertEqual(self._status_text(table, 0), "—")


class TestEmptyFilterNulls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_table(self):
        table = ResultTable()
        table.setup_columns(
            ["Server", "Database", "Value"],
            {0: 190, 1: 160, 2: 160},
        )
        return table

    def _visible_rows(self, table):
        return [
            i for i in range(table.rowCount())
            if not table.isRowHidden(i)
        ]

    def test_empty_filter_catches_null_string(self):
        table = self._make_table()
        table.add_row(["srv1", "ar_test", "Null"])
        table.add_row(["srv1", "ar_other", "data"])

        table._empty_filter_columns.add(2)
        table.apply_filters()

        visible = self._visible_rows(table)
        self.assertEqual(visible, [0])

    def test_nonempty_filter_excludes_null_string(self):
        table = self._make_table()
        table.add_row(["srv1", "ar_test", "Null"])
        table.add_row(["srv1", "ar_other", "data"])

        table._nonempty_filter_columns.add(2)
        table.apply_filters()

        visible = self._visible_rows(table)
        self.assertEqual(visible, [1])


if __name__ == "__main__":
    unittest.main()
