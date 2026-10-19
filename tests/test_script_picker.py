"""
tests/test_script_picker.py

Тесты выбора сохранённого скрипта над редактором SQL-консоли:
- set_scripts заполняет комбо (пункт = имя, данные = тело);
- пустой список / скрипты без тела скрывают комбо;
- выбор пункта эмитит scriptPickRequested с телом скрипта;
- комбо сбрасывается после выбора, повторный выбор снова срабатывает;
- retheme() сохраняет пункты;
- set_busy блокирует выбор.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.sql_console import SqlConsolePanel


def _scripts():
    return [
        {"name": "Проверка cfg_settings", "body": "SELECT 1;"},
        {"name": "Финальность состояний", "body": "SELECT 2;"},
    ]


class TestScriptPicker(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = SqlConsolePanel()

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()

    def test_combo_hidden_without_scripts(self):
        self.assertTrue(self.panel.script_row.isHidden())
        self.assertEqual(self.panel.cb_script.count(), 0)

    def test_set_scripts_fills_combo(self):
        self.panel.set_scripts(_scripts())

        self.assertFalse(self.panel.script_row.isHidden())
        self.assertEqual(self.panel.cb_script.count(), 2)
        self.assertEqual(
            self.panel.cb_script.itemText(0), "Проверка cfg_settings"
        )
        self.assertEqual(self.panel.cb_script.itemData(0), "SELECT 1;")
        self.assertEqual(self.panel.cb_script.itemData(1), "SELECT 2;")

    def test_combo_starts_without_selection(self):
        self.panel.set_scripts(_scripts())

        self.assertEqual(self.panel.cb_script.currentIndex(), -1)
        self.assertEqual(self.panel.cb_script.currentText(), "")

    def test_scripts_without_body_are_skipped(self):
        self.panel.set_scripts([
            {"name": "Пустой", "body": "   "},
            {"name": "", "body": "SELECT 1;"},
            {"name": "Нет тела"},
            {"name": "Годный", "body": "SELECT 3;"},
        ])

        self.assertEqual(self.panel.cb_script.count(), 1)
        self.assertEqual(self.panel.cb_script.itemText(0), "Годный")

    def test_empty_script_list_hides_combo(self):
        self.panel.set_scripts(_scripts())
        self.panel.set_scripts([])

        self.assertTrue(self.panel.script_row.isHidden())
        self.assertEqual(self.panel.cb_script.count(), 0)

    def test_pick_emits_body(self):
        received = []
        self.panel.scriptPickRequested.connect(received.append)
        self.panel.set_scripts(_scripts())

        self.panel.cb_script.setCurrentIndex(1)

        self.assertEqual(received, ["SELECT 2;"])

    def test_pick_resets_combo(self):
        self.panel.set_scripts(_scripts())

        self.panel.cb_script.setCurrentIndex(0)

        self.assertEqual(self.panel.cb_script.currentIndex(), -1)
        self.assertEqual(self.panel.cb_script.currentText(), "")

    def test_pick_same_script_twice_emits_twice(self):
        received = []
        self.panel.scriptPickRequested.connect(received.append)
        self.panel.set_scripts(_scripts())

        self.panel.cb_script.setCurrentIndex(0)
        self.panel.cb_script.setCurrentIndex(0)

        self.assertEqual(received, ["SELECT 1;", "SELECT 1;"])

    def test_pick_does_not_touch_editor(self):
        self.panel.set_scripts(_scripts())
        self.panel.editor.setPlainText("EXISTING")

        self.panel.cb_script.setCurrentIndex(0)

        self.assertEqual(self.panel.editor.toPlainText(), "EXISTING")

    def test_retheme_keeps_items(self):
        self.panel.set_scripts(_scripts())

        self.panel.retheme()

        self.assertEqual(self.panel.cb_script.count(), 2)
        self.assertEqual(self.panel.cb_script.itemData(1), "SELECT 2;")

    def test_set_busy_disables_combo(self):
        self.panel.set_scripts(_scripts())

        self.panel.set_busy(True)
        self.assertFalse(self.panel.cb_script.isEnabled())

        self.panel.set_busy(False)
        self.assertTrue(self.panel.cb_script.isEnabled())

    def test_set_scripts_updates_completion(self):
        self.panel.set_scripts(_scripts())

        self.assertEqual(
            len(self.panel._completer._scripts), 2
        )

    def test_none_scripts_are_safe(self):
        self.panel.set_scripts(None)

        self.assertTrue(self.panel.script_row.isHidden())


if __name__ == "__main__":
    unittest.main()
