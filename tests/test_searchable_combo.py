"""
tests/test_searchable_combo.py

Тесты виджета выбора сервера/БД с поиском по любому вхождению:
чистая функция contains_match и фильтрация попапа SearchableComboBox
(подстрока без учёта регистра, по Name и по host).
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPointingDevice
from PySide6.QtWidgets import QApplication

from gui.widgets.searchable_combo import SearchableComboBox, contains_match


class ContainsMatchTest(unittest.TestCase):
    def test_substring_in_name(self):
        self.assertTrue(contains_match("prod", "Prod-01", "p7ru1.tradesoft.ru"))

    def test_substring_in_host(self):
        self.assertTrue(contains_match("p5g", "Main cluster", "p5g21.tradesoft.ru"))

    def test_case_insensitive(self):
        self.assertTrue(contains_match("P5G", "x", "p5g25.tradesoft.ru"))
        self.assertTrue(contains_match("DEV", "Dev", ""))

    def test_no_match(self):
        self.assertFalse(contains_match("oracle", "MySQL box", "db.local"))

    def test_host_tld_not_matched(self):
        self.assertFalse(contains_match("ru", "Ext4", "ext4.tradesoft.ru"))
        self.assertTrue(contains_match("ru", "p7ru1", "p7ru1.tradesoft.ru"))

    def test_subdomain_still_matched(self):
        self.assertTrue(contains_match("tradesoft", "Ext4", "ext4.tradesoft.ru"))

    def test_ip_host_searched_whole(self):
        self.assertTrue(contains_match("10.0.0", "Srv", "10.0.0.5"))
        self.assertTrue(contains_match("0.0.5", "Srv", "10.0.0.5"))

    def test_single_label_host_searched_whole(self):
        self.assertTrue(contains_match("srv", "Main", "srv-01"))

    def test_empty_query_matches_all(self):
        self.assertTrue(contains_match("", "anything", "host"))
        self.assertTrue(contains_match("  ", "anything", "host"))


class SearchableComboBoxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make(self):
        combo = SearchableComboBox()
        combo.addItem("Prod-01", "p7ru1.tradesoft.ru")
        combo.addItem("Prod-02", "p5g21.tradesoft.ru")
        combo.addItem("Dev", "dev.local")
        return combo

    def _rows(self, combo):
        return [
            combo._completer.model().item(i).text()
            for i in range(combo._completer.model().rowCount())
        ]

    def test_filter_by_name(self):
        combo = self._make()
        combo._on_text_changed("dev")
        self.assertEqual(self._rows(combo), ["Dev"])

    def test_filter_by_host(self):
        combo = self._make()
        combo._on_text_changed("p5g")
        self.assertEqual(self._rows(combo), ["Prod-02"])

    def test_filter_any_occurrence_case_insensitive(self):
        combo = self._make()
        combo._on_text_changed("p7")
        self.assertEqual(self._rows(combo), ["Prod-01"])
        combo._on_text_changed("TRADE")
        self.assertEqual(self._rows(combo), ["Prod-01", "Prod-02"])

    def test_empty_query_returns_all(self):
        combo = self._make()
        combo._on_text_changed("")
        self.assertEqual(len(self._rows(combo)), 3)

    def test_typing_back_to_selected_item_refreshes_model(self):
        combo = self._make()
        combo._on_text_changed("Prod")
        self.assertEqual(self._rows(combo), ["Prod-01", "Prod-02"])
        combo._on_text_changed("Prod-01")
        self.assertEqual(self._rows(combo), ["Prod-01"])
        self.assertFalse(combo._completer.popup().isVisible())

    def test_empty_text_refreshes_model_and_hides_popup(self):
        combo = self._make()
        combo._on_text_changed("")
        self.assertEqual(len(self._rows(combo)), 3)
        self.assertFalse(combo._completer.popup().isVisible())

    def test_refresh_completion_after_rebuild(self):
        combo = self._make()
        combo._on_text_changed("dev")
        self.assertEqual(self._rows(combo), ["Dev"])
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("New-01", "h1")
        combo.addItem("New-02", "h2")
        combo.blockSignals(False)
        combo.refresh_completion()
        self.assertEqual(self._rows(combo), ["New-01"])

    def test_activated_resolves_item(self):
        combo = self._make()
        combo._on_text_changed("p5g")
        combo._on_activated("Prod-02")
        self.assertEqual(combo.currentIndex(), 1)
        self.assertEqual(combo.itemData(combo.currentIndex()), "p5g21.tradesoft.ru")

    def _make_with_engines(self):
        combo = SearchableComboBox()
        combo.addItem("MSSQL box", "aisql.tradesoft.corp\\supportsql")
        combo.setItemData(0, "mssql", Qt.UserRole + 1)
        combo.addItem("MySQL box", "kz1.tradesoft.ru")
        combo.setItemData(1, "mysql", Qt.UserRole + 1)
        combo.addItem("No engine", "plain.local")
        return combo

    def test_combo_items_include_engine(self):
        combo = self._make_with_engines()
        self.assertEqual(
            combo._combo_items(),
            [
                ("MSSQL box", "aisql.tradesoft.corp\\supportsql", "mssql"),
                ("MySQL box", "kz1.tradesoft.ru", "mysql"),
                ("No engine", "plain.local", ""),
            ],
        )

    def test_engine_icon_set_on_popup_item(self):
        combo = self._make_with_engines()
        combo._on_text_changed("")
        model = combo._completer.model()
        icon_by_text = {
            model.item(i).text(): model.item(i).icon() for i in range(model.rowCount())
        }
        self.assertFalse(icon_by_text["MSSQL box"].isNull())
        self.assertFalse(icon_by_text["MySQL box"].isNull())
        self.assertTrue(icon_by_text["No engine"].isNull())

    def test_refresh_accepts_two_and_three_tuples(self):
        combo = self._make()
        combo._completer.refresh([("A", "h1"), ("B", "h2", "mysql")], "")
        self.assertEqual(self._rows(combo), ["A", "B"])
        model = combo._completer.model()
        self.assertFalse(model.item(1).icon().isNull())

    def _click_field(self, combo):
        event = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(10, 5),
            QPointF(10, 5),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
            QPointingDevice.primaryPointingDevice(),
        )
        QApplication.sendEvent(combo.lineEdit(), event)

    def test_click_on_empty_field_shows_all_items(self):
        combo = self._make()
        self._click_field(combo)
        QApplication.processEvents()
        self.assertTrue(combo._completer.popup().isVisible())
        self.assertEqual(self._rows(combo), ["Prod-01", "Prod-02", "Dev"])

    def test_click_with_selected_value_shows_all_items(self):
        combo = self._make()
        combo.setCurrentIndex(0)
        self._click_field(combo)
        QApplication.processEvents()
        self.assertTrue(combo._completer.popup().isVisible())
        self.assertEqual(self._rows(combo), ["Prod-01", "Prod-02", "Dev"])

    def test_click_then_typing_filters(self):
        combo = self._make()
        self._click_field(combo)
        QApplication.processEvents()
        self.assertEqual(self._rows(combo), ["Prod-01", "Prod-02", "Dev"])
        combo._popup_manual = False
        combo._on_text_changed("dev")
        self.assertEqual(self._rows(combo), ["Dev"])

    def _send_key(self, widget, key):
        from PySide6.QtGui import QKeyEvent
        event = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
        QApplication.sendEvent(widget, event)
        QApplication.processEvents()

    def test_down_key_opens_popup(self):
        combo = self._make()
        popup = combo._completer.popup()

        combo.lineEdit().setFocus()
        self._send_key(combo.lineEdit(), Qt.Key_Down)

        self.assertTrue(popup.isVisible())

    def test_enter_confirms_selection(self):
        combo = self._make()
        popup = combo._completer.popup()

        combo.lineEdit().setFocus()
        self._send_key(combo.lineEdit(), Qt.Key_Down)
        self.assertTrue(popup.isVisible())

        self._send_key(popup, Qt.Key_Return)
        self.assertFalse(popup.isVisible())
        self.assertGreaterEqual(combo.currentIndex(), 0)

    def test_escape_hides_popup(self):
        combo = self._make()
        popup = combo._completer.popup()

        combo.lineEdit().setFocus()
        self._send_key(combo.lineEdit(), Qt.Key_Down)
        self.assertTrue(popup.isVisible())

        self._send_key(popup, Qt.Key_Escape)
        self.assertFalse(popup.isVisible())

    def test_navigation_does_not_clear_model(self):
        combo = self._make()
        popup = combo._completer.popup()
        model = combo._completer.model()

        combo.lineEdit().setFocus()
        self._send_key(combo.lineEdit(), Qt.Key_Down)
        self.assertTrue(popup.isVisible())

        initial_count = model.rowCount()
        for _ in range(3):
            self._send_key(popup, Qt.Key_Down)

        self.assertEqual(model.rowCount(), initial_count)


if __name__ == "__main__":
    unittest.main()
