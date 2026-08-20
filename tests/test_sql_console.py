"""
tests/test_sql_console.py

Проверка панели SQL-консоли: в списке серверов отображается Name,
host скрыт в данных пункта и резолвится через current_host()/
set_target() без потери функциональности.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.sql_console import SqlConsolePanel


class TestSqlConsolePanel(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = SqlConsolePanel()

    def tearDown(self):
        self.panel.close()

    def test_set_servers_with_names(self):
        self.panel.set_servers([
            ("Prod", "db1.example.com"),
            ("Report", "db2.example.com"),
        ])

        self.assertEqual(self.panel.cb_server.count(), 2)
        # В списке показывается имя, а не хост
        self.assertEqual(self.panel.cb_server.itemText(0), "Prod")
        self.assertEqual(self.panel.cb_server.itemData(0), "db1.example.com")

    def test_default_server_selection_empty(self):
        self.panel.set_servers([
            ("Prod", "db1.example.com"),
            ("Report", "db2.example.com"),
        ])

        self.assertEqual(self.panel.cb_server.currentIndex(), -1)
        self.assertEqual(self.panel.cb_server.currentText(), "")

    def test_set_servers_keeps_existing_selection(self):
        self.panel.set_servers([
            ("Prod", "db1.example.com"),
            ("Report", "db2.example.com"),
        ])
        self.panel.cb_server.setCurrentIndex(1)
        self.panel.set_servers([
            ("Prod", "db1.example.com"),
            ("Report", "db2.example.com"),
            ("New", "db3.example.com"),
        ])

        self.assertEqual(self.panel.cb_server.currentIndex(), 1)

    def test_current_host_resolves_host_from_data(self):
        self.panel.set_servers([
            ("Prod", "db1.example.com"),
            ("Report", "db2.example.com"),
        ])

        self.panel.cb_server.setCurrentIndex(1)

        self.assertEqual(self.panel.current_host(), "db2.example.com")

    def test_current_host_fallback_to_typed_text(self):
        self.panel.set_servers([("Prod", "db1.example.com")])

        self.panel.cb_server.setCurrentText("arbitrary.host.ru")

        self.assertEqual(self.panel.current_host(), "arbitrary.host.ru")

    def test_set_target_selects_by_host(self):
        self.panel.set_servers([
            ("Prod", "db1.example.com"),
            ("Report", "db2.example.com"),
        ])

        self.panel.set_target("db2.example.com", "ar_b")

        self.assertEqual(
            self.panel.cb_server.currentData(), "db2.example.com"
        )
        self.assertEqual(self.panel.current_host(), "db2.example.com")
        self.assertEqual(self.panel.current_database(), "ar_b")

    def test_set_servers_keeps_previous_selection(self):
        self.panel.set_servers([
            ("Prod", "db1.example.com"),
            ("Report", "db2.example.com"),
        ])
        self.panel.cb_server.setCurrentIndex(1)

        self.panel.set_servers([
            ("Prod", "db1.example.com"),
            ("Report", "db2.example.com"),
            ("New", "db3.example.com"),
        ])

        self.assertEqual(self.panel.current_host(), "db2.example.com")

    def test_server_index_changed_emits_server_changed(self):
        self.panel.set_servers([
            ("Prod", "db1.example.com"),
            ("Report", "db2.example.com"),
        ])
        signals = []
        self.panel.serverChanged.connect(
            lambda name: signals.append(name)
        )

        self.panel.cb_server.setCurrentIndex(1)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0], "Report")

    def test_server_index_negative_does_not_emit(self):
        self.panel.set_servers([
            ("Prod", "db1.example.com"),
            ("Report", "db2.example.com"),
        ])
        signals = []
        self.panel.serverChanged.connect(
            lambda name: signals.append(name)
        )

        self.panel.cb_server.setCurrentIndex(-1)

        self.assertEqual(len(signals), 0)


if __name__ == "__main__":
    unittest.main()
