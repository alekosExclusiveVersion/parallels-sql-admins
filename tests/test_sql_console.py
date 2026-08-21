"""
tests/test_sql_console.py

Проверка панели SQL-консоли: в списке серверов отображается Name,
host скрыт в данных пункта и резолвится через current_host()/
set_target() без потери функциональности.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeyEvent
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


class TestSqlConsoleEngineIcons(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = SqlConsolePanel()

    def tearDown(self):
        self.panel.close()

    def test_three_tuple_sets_engine_role_and_icon(self):
        self.panel.set_servers([
            ("P", "h1", "pgsql"),
            ("M", "h2", "mysql"),
            ("S", "h3", "mssql"),
        ])

        self.assertEqual(self.panel.cb_server.count(), 3)

        for i, expected in enumerate(["pgsql", "mysql", "mssql"]):
            engine = self.panel.cb_server.itemData(i, Qt.UserRole + 1)
            self.assertEqual(engine, expected)
            qicon = self.panel.cb_server.itemIcon(i)
            self.assertFalse(qicon.isNull())

    def test_empty_engine_no_icon(self):
        self.panel.set_servers([
            ("O", "h1", ""),
        ])

        engine = self.panel.cb_server.itemData(0, Qt.UserRole + 1)
        self.assertIsNone(engine)

    def test_set_databases_icons_follow_engine(self):
        self.panel.set_servers([("P", "h1", "pgsql")])
        self.panel.cb_server.setCurrentIndex(0)

        self.panel.set_databases(["db_a", "db_b"])

        for i in range(self.panel.cb_database.count()):
            qicon = self.panel.cb_database.itemIcon(i)
            self.assertFalse(qicon.isNull())
            engine = self.panel.cb_database.itemData(i, Qt.UserRole + 1)
            self.assertEqual(engine, "pgsql")

    def test_set_databases_restores_current_if_exists(self):
        self.panel.set_servers([("P", "h1", "pgsql")])
        self.panel.cb_server.setCurrentIndex(0)
        self.panel.set_databases(["db_a", "db_b"])
        self.panel.cb_database.setCurrentText("db_b")

        self.panel.set_databases(["db_a", "db_b", "db_c"])

        self.assertEqual(self.panel.cb_database.currentText(), "db_b")

    def test_set_databases_clears_if_not_in_new_list(self):
        self.panel.set_servers([("P", "h1", "pgsql")])
        self.panel.cb_server.setCurrentIndex(0)
        self.panel.set_databases(["db_a", "db_b"])
        self.panel.cb_database.setCurrentText("db_b")

        self.panel.set_databases(["db_x", "db_y"])

        self.assertEqual(self.panel.cb_database.currentText(), "")


class TestSqlEditorEscape(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = SqlConsolePanel()

    def tearDown(self):
        self.panel.close()

    def test_escape_without_popup_emits_stop_requested(self):
        stop_signals = []
        self.panel.stopRequested.connect(lambda: stop_signals.append(True))

        self.panel.editor.setFocus()
        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        self.panel.editor.keyPressEvent(event)

        self.assertEqual(len(stop_signals), 1)

    def test_escape_inside_popup_hides_popup_no_stop(self):
        stop_signals = []
        self.panel.stopRequested.connect(lambda: stop_signals.append(True))

        completer = self.panel.editor._completer
        if completer is None:
            self.skipTest("no completer set")
        completer.set_catalog(["users", "orders"], {"users": ["id"]})

        self.panel.editor.setPlainText("u")
        context = __import__(
            "common.sql_completion", fromlist=["analyze"]
        ).analyze("u", 1)
        completer.show_suggestions(context)

        popup = completer.popup()
        if not popup.isVisible():
            self.skipTest("popup did not show")

        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        popup.keyPressEvent(event)

        self.assertFalse(popup.isVisible())
        self.assertEqual(len(stop_signals), 0)


if __name__ == "__main__":
    unittest.main()
