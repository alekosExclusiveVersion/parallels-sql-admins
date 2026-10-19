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

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
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
        self.assertTrue(self.panel.cb_script.isHidden())
        self.assertEqual(self.panel.cb_script.count(), 0)

    def test_set_scripts_fills_combo(self):
        self.panel.set_scripts(_scripts())

        self.assertFalse(self.panel.cb_script.isHidden())
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

        self.assertTrue(self.panel.cb_script.isHidden())
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
        QApplication.processEvents()

        self.assertEqual(self.panel.cb_script.currentIndex(), -1)
        self.assertEqual(self.panel.cb_script.currentText(), "")

    def test_pick_same_script_twice_emits_twice(self):
        received = []
        self.panel.scriptPickRequested.connect(received.append)
        self.panel.set_scripts(_scripts())

        self.panel.cb_script.setCurrentIndex(0)
        QApplication.processEvents()
        self.panel.cb_script.setCurrentIndex(0)
        QApplication.processEvents()

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

        self.assertTrue(self.panel.cb_script.isHidden())


class TestScriptPickerInteraction(unittest.TestCase):
    """Поведение реального клика: без дублей и с открытием списка."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])
        from gui import styles as theme_styles

        cls._app.setStyleSheet(theme_styles.build_stylesheet())

    @classmethod
    def tearDownClass(cls):
        cls._app.setStyleSheet("")

    def setUp(self):
        self.panel = SqlConsolePanel()
        self.panel.resize(900, 400)
        self.panel.set_scripts(_scripts())
        self.panel.show()
        QApplication.processEvents()
        self.cb = self.panel.cb_script
        self.popup = self.cb._completer.popup()
        self.received = []
        self.panel.scriptPickRequested.connect(self.received.append)

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()

    def _open_list(self):
        QTest.mouseClick(
            self.cb.lineEdit(),
            Qt.LeftButton,
            Qt.NoModifier,
            self.cb.lineEdit().rect().center(),
        )
        QApplication.processEvents()

    def _click_row(self, row):
        index = self.popup.model().index(row, 0)
        QTest.mouseClick(
            self.popup.viewport(),
            Qt.LeftButton,
            Qt.NoModifier,
            self.popup.visualRect(index).center(),
        )
        QApplication.processEvents()

    def test_single_click_emits_once(self):
        self._open_list()
        self._click_row(1)

        self.assertEqual(self.received, ["SELECT 2;"])

    def test_repeated_pick_emits_again(self):
        self._open_list()
        self._click_row(1)
        self._open_list()
        self._click_row(1)

        self.assertEqual(self.received, ["SELECT 2;", "SELECT 2;"])

    def test_pick_resets_after_event_loop(self):
        self._open_list()
        self._click_row(0)

        self.assertEqual(self.cb.currentIndex(), -1)
        self.assertEqual(self.cb.currentText(), "")

    def test_click_field_opens_full_list(self):
        self._open_list()

        self.assertTrue(self.popup.isVisible())
        self.assertEqual(self.popup.model().rowCount(), 2)

    def test_arrow_click_opens_custom_popup(self):
        QTest.mouseClick(
            self.cb,
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(self.cb.width() - 8, self.cb.height() // 2),
        )
        QApplication.processEvents()

        self.assertTrue(self.popup.isVisible())
        self.assertFalse(self.cb.view().isVisible())

    def test_combo_aligned_with_run_buttons(self):
        self.assertLessEqual(
            abs(
                self.cb.geometry().center().y()
                - self.panel.btn_run.geometry().center().y()
            ),
            2,
        )
        self.assertLessEqual(
            abs(
                self.cb.geometry().center().y()
                - self.panel.btn_stop.geometry().center().y()
            ),
            2,
        )
        self.assertEqual(self.cb.height(), self.panel.btn_run.height())


if __name__ == "__main__":
    unittest.main()
