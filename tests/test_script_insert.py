"""
tests/test_script_insert.py

Тесты фичи вставки SQL-скриптов в консоль:
  - insert_script / replace_script (SqlConsolePanel)
  - _remove_completion_prefix (SqlEditor)
  - сигнал scriptInsertRequested при выборе скрипта через автодополнение
  - pass-through сигнал scriptInsertFromEditor
  - диспетчер _script_insert_to_console: замена / добавление / отмена с восстановлением префикса
"""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.sql_console import SqlConsolePanel


def _teardown_panel(panel):
    panel.editor.set_completer(None)
    panel.close()


class TestInsertScript(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = SqlConsolePanel()

    def tearDown(self):
        _teardown_panel(self.panel)

    def test_append_to_empty(self):
        self.assertTrue(self.panel.insert_script("SELECT 1;"))
        self.assertEqual(self.panel.script_text(), "SELECT 1;")

    def test_append_separator(self):
        self.panel.editor.setPlainText("SELECT 1;")
        # setPlainText ставит курсор в начало — moveEnd для корректности
        from PySide6.QtGui import QTextCursor
        c = self.panel.editor.textCursor()
        c.movePosition(QTextCursor.End)
        self.panel.editor.setTextCursor(c)

        self.panel.insert_script("SELECT 2;")
        self.assertIn("\n\n\nSELECT 2;", self.panel.script_text())

    def test_separator_not_when_current_ends_with_newline(self):
        """При тексте с завершающим \\n лишний \\n перед разделителем не добавляется."""
        self.panel.editor.setPlainText("SELECT 1;\n")
        from PySide6.QtGui import QTextCursor
        c = self.panel.editor.textCursor()
        c.movePosition(QTextCursor.End)
        self.panel.editor.setTextCursor(c)

        self.panel.insert_script("SELECT 2;")
        between = self.panel.script_text().split("SELECT 1;")[1].rsplit("SELECT 2;", 1)[0]
        # Существующий trailing \n + \n\n\n разделитель = 4 \n (а не 5)
        self.assertEqual(between, "\n\n\n\n")

    def test_returns_true(self):
        self.assertTrue(self.panel.insert_script("SELECT 1;"))

    def test_returns_false_on_empty(self):
        self.assertFalse(self.panel.insert_script(""))

    def test_returns_false_on_none(self):
        self.assertFalse(self.panel.insert_script(None))

    def test_returns_false_on_whitespace(self):
        self.assertFalse(self.panel.insert_script("  \n\t "))

    def test_cursor_at_end(self):
        self.panel.insert_script("SELECT 1;")
        from PySide6.QtGui import QTextCursor
        cursor = self.panel.editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        # после insert_script курсор должен быть в конце
        self.assertEqual(self.panel.editor.textCursor().position(), cursor.position())


class TestReplaceScript(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = SqlConsolePanel()

    def tearDown(self):
        _teardown_panel(self.panel)

    def test_replace(self):
        self.panel.editor.setPlainText("OLD")
        self.assertTrue(self.panel.replace_script("NEW"))
        self.assertEqual(self.panel.script_text(), "NEW")

    def test_replace_empty_editor(self):
        self.assertTrue(self.panel.replace_script("NEW"))
        self.assertEqual(self.panel.script_text(), "NEW")

    def test_returns_false_on_none(self):
        self.assertFalse(self.panel.replace_script(None))

    def test_returns_false_on_whitespace(self):
        self.assertFalse(self.panel.replace_script("  "))

    def test_undo_available(self):
        self.panel.editor.setPlainText("BEFORE")
        self.panel.replace_script("AFTER")
        self.assertTrue(self.panel.editor.document().isUndoAvailable())

    def test_undo_restores_content(self):
        original = "SELECT id FROM users WHERE active = 1"
        self.panel.editor.setPlainText(original)
        self.panel.replace_script("DROP TABLE users;")
        self.panel.editor.document().undo()
        self.assertEqual(self.panel.script_text(), original)


class TestRemoveCompletionPrefix(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = SqlConsolePanel()
        self.editor = self.panel.editor

    def tearDown(self):
        _teardown_panel(self.panel)

    def _make_completer(self, prefix="", body_for=None):
        completer = MagicMock()
        completer.script_body_for.side_effect = (
            (lambda t: body_for.get(t)) if body_for else (lambda t: None)
        )
        return completer

    def test_removes_prefix(self):
        self.editor.setPlainText("updat")
        self.editor._completer = self._make_completer()
        self.editor._completion_prefix = "updat"
        removed = self.editor._remove_completion_prefix()
        self.assertEqual(self.editor.toPlainText(), "")
        self.assertEqual(removed, "updat")

    def test_returns_prefix(self):
        self.editor.setPlainText("sel")
        self.editor._completer = self._make_completer()
        self.editor._completion_prefix = "sel"
        self.assertEqual(self.editor._remove_completion_prefix(), "sel")

    def test_no_prefix(self):
        self.editor.setPlainText("SELECT")
        self.editor._completer = self._make_completer()
        self.editor._completion_prefix = ""
        self.assertEqual(self.editor._remove_completion_prefix(), "")
        self.assertEqual(self.editor.toPlainText(), "SELECT")

    def test_no_completer(self):
        self.editor.setPlainText("TEXT")
        self.editor._completer = None
        self.assertEqual(self.editor._remove_completion_prefix(), "")
        self.assertEqual(self.editor.toPlainText(), "TEXT")

    def test_cursor_at_start(self):
        self.editor.setPlainText("updat")
        self.editor._completer = self._make_completer()
        self.editor._completion_prefix = "updat"
        # курсор в начале (артефакт setPlainText)
        self.editor._remove_completion_prefix()
        self.assertEqual(self.editor.toPlainText(), "")


class TestInsertCompletionSignal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = SqlConsolePanel()
        self.editor = self.panel.editor

    def tearDown(self):
        _teardown_panel(self.panel)

    def _make_completer(self, prefix, body_for):
        completer = MagicMock()
        completer.script_body_for.side_effect = lambda t: body_for.get(t)
        return completer

    def test_script_emits_signal(self):
        received = []
        self.editor.scriptInsertRequested.connect(
            lambda b, p: received.append((b, p))
        )
        self.editor._completer = self._make_completer(
            "upd", {"update_ticks": "UPDATE ticks SET t = NOW()"}
        )
        self.editor._completion_prefix = "upd"
        self.editor._insert_completion("update_ticks")
        self.assertEqual(len(received), 1)

    def test_script_body_correct(self):
        received = []
        self.editor.scriptInsertRequested.connect(
            lambda b, p: received.append((b, p))
        )
        body = "UPDATE ticks SET t = NOW()"
        self.editor._completer = self._make_completer("upd", {"update_ticks": body})
        self.editor._completion_prefix = "upd"
        self.editor._insert_completion("update_ticks")
        self.assertEqual(received[0][0], body)

    def test_script_prefix_correct(self):
        received = []
        self.editor.scriptInsertRequested.connect(
            lambda b, p: received.append((b, p))
        )
        self.editor._completer = self._make_completer(
            "upd", {"update_ticks": "UPDATE ticks"}
        )
        self.editor._completion_prefix = "upd"
        self.editor._insert_completion("update_ticks")
        self.assertEqual(received[0][1], "upd")

    def test_script_removes_prefix(self):
        self.editor.setPlainText("upd")
        self.editor._completer = self._make_completer(
            "upd", {"update_ticks": "UPDATE ticks"}
        )
        self.editor._completion_prefix = "upd"
        self.editor._insert_completion("update_ticks")
        self.assertNotIn("upd", self.editor.toPlainText())

    def test_script_hides_popup(self):
        completer = self._make_completer(
            "upd", {"update_ticks": "UPDATE ticks"}
        )
        self.editor._completer = completer
        self.editor._insert_completion("update_ticks")
        completer.hide_popup.assert_called_once()

    def test_non_script_no_signal(self):
        received = []
        self.editor.scriptInsertRequested.connect(
            lambda b, p: received.append((b, p))
        )
        self.editor._completer = self._make_completer("SEL", {})
        self.editor._completion_prefix = "SEL"
        self.editor._insert_completion("SELECT")
        self.assertEqual(len(received), 0)

    def test_completer_none_no_crash(self):
        self.editor._completer = None
        self.editor._insert_completion("anything")
        # не должно упасть


class TestPassThroughSignal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = SqlConsolePanel()

    def tearDown(self):
        _teardown_panel(self.panel)

    def test_editor_signal_relayed(self):
        received = []
        self.panel.scriptInsertFromEditor.connect(
            lambda b, p: received.append((b, p))
        )
        self.panel.editor.scriptInsertRequested.emit("body text", "prefix")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0], ("body text", "prefix"))


class TestDispatcherWithPrefix(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = SqlConsolePanel()
        self.console_tabs = MagicMock()
        self.console_tabs.setCurrentWidget = MagicMock()

        class FakeMainWindow:
            panel = self.panel
            console_tabs = self.console_tabs

            def _ask_insert_mode(self):
                return None

        self.window = FakeMainWindow()

    def tearDown(self):
        _teardown_panel(self.panel)

    def _call(self, text="SCRIPT_BODY", prefix="", mode=None, console_text=""):
        from gui import main_window as mw
        self.panel.editor.setPlainText(console_text)
        with patch.object(self.panel, "replace_script", wraps=self.panel.replace_script) as rp, \
             patch.object(self.panel, "insert_script", wraps=self.panel.insert_script) as ip, \
             patch("gui.main_window.logger"):
            with patch.object(self.window, "_ask_insert_mode", return_value=mode):
                mw.MainWindow._script_insert_to_console(self.window, text, prefix)
            return rp, ip

    def test_replace_removes_prefix(self):
        rp, ip = self._call(mode="replace", console_text="OLD CONTENT")
        rp.assert_called_once()
        ip.assert_not_called()

    def test_append_inserts_text(self):
        rp, ip = self._call(mode="append", console_text="OLD CONTENT")
        ip.assert_called_once()
        rp.assert_not_called()

    def test_cancel_restores_prefix(self):
        from gui import main_window as mw
        self.panel.editor.setPlainText("EXISTING")
        with patch("gui.main_window.logger"), \
             patch.object(self.window, "_ask_insert_mode", return_value=None):
            mw.MainWindow._script_insert_to_console(self.window, "BODY", "upd")
        self.assertIn("upd", self.panel.editor.toPlainText())

    def test_cancel_no_prefix(self):
        from gui import main_window as mw
        self.panel.editor.setPlainText("EXISTING")
        with patch("gui.main_window.logger"), \
             patch.object(self.window, "_ask_insert_mode", return_value=None):
            mw.MainWindow._script_insert_to_console(self.window, "BODY", "")
        self.assertEqual(self.panel.editor.toPlainText(), "EXISTING")

    def test_empty_console_skips_dialog(self):
        self.panel.editor.setPlainText("")
        from gui import main_window as mw
        with patch("gui.main_window.logger"), \
             patch.object(self.window, "_ask_insert_mode", return_value="replace") as mock_ask:
            mw.MainWindow._script_insert_to_console(self.window, "BODY")
        mock_ask.assert_not_called()

    def test_non_empty_console_shows_dialog(self):
        self.panel.editor.setPlainText("EXISTING")
        from gui import main_window as mw
        with patch.object(self.window, "_ask_insert_mode", return_value=None) as mock_ask:
            mw.MainWindow._script_insert_to_console(self.window, "BODY")
        mock_ask.assert_called_once()


if __name__ == "__main__":
    unittest.main()
