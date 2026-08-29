"""
tests/test_copyable_alert.py

Функциональные тесты стилизованного алерта CopyableMessageBox: текст сообщения
можно выделить и скопировать, кнопки возвращают значения
QMessageBox.StandardButton, подписи кнопок — русские, Esc и закрытие окна
равнозначны кнопке по умолчанию.
"""

import re
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QTextEdit

from gui.widgets.copyable_alert import CopyableMessageBox, _BUTTON_LABELS

_CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)

_ALL_LABELS = set(_BUTTON_LABELS.values())


class TestMessageArea(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _mk(self, **kw):
        kw.setdefault("text", "Сообщение текста")
        dialog = CopyableMessageBox(
            None, title="Тест", **kw
        )
        self.addCleanup(lambda: (dialog.close(), dialog.deleteLater()))
        return dialog

    def _buttons(self, dialog):
        return [
            b for b in dialog.findChildren(QPushButton)
            if b.text() not in _ALL_LABELS and b.text() != "Копировать"
        ]

    def test_message_area_read_only_and_selectable(self):
        dialog = self._mk()
        edit = dialog._message
        self.assertIsInstance(edit, QTextEdit)
        self.assertTrue(edit.isReadOnly())
        flags = edit.textInteractionFlags()
        self.assertTrue(flags & Qt.TextInteractionFlag.TextSelectableByMouse)
        self.assertTrue(flags & Qt.TextInteractionFlag.TextSelectableByKeyboard)

    def test_copy_button_puts_full_text_to_clipboard(self):
        dialog = self._mk(severity="critical", text="Строка целиком.\nВторая строка")
        self.assertIn("Копировать", [b.text() for b in dialog.findChildren(QPushButton)])

        copy_button = next(
            b for b in dialog.findChildren(QPushButton) if b.text() == "Копировать"
        )
        copy_button.click()
        self.assertEqual(
            self._app.clipboard().text(), "Строка целиком.\nВторая строка"
        )

    def test_applies_dialog_stylesheet(self):
        dialog = self._mk()
        self.assertTrue(dialog.styleSheet())
        self.assertTrue(dialog.windowTitle())

    def test_styled_title_label_present(self):
        from PySide6.QtWidgets import QLabel

        dialog = self._mk()
        title = dialog.findChild(QLabel, "DialogTitle")
        self.assertIsNotNone(title)
        self.assertEqual(title.text(), "Тест")


class TestButtons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _mk(self, buttons=QMessageBox.StandardButton.Ok, default=QMessageBox.StandardButton.Ok, **kw):
        dialog = CopyableMessageBox(
            None, title="Тест", text="Сообщение", buttons=buttons,
            defaultButton=default, **kw
        )
        self.addCleanup(lambda: (dialog.close(), dialog.deleteLater()))
        return dialog

    def test_standard_button_labels_are_russian(self):
        self.assertEqual(_BUTTON_LABELS[QMessageBox.StandardButton.Yes], "Да")
        self.assertEqual(_BUTTON_LABELS[QMessageBox.StandardButton.No], "Нет")
        self.assertEqual(_BUTTON_LABELS[QMessageBox.StandardButton.Ok], "ОК")
        self.assertEqual(_BUTTON_LABELS[QMessageBox.StandardButton.Cancel], "Отмена")
        self.assertEqual(_BUTTON_LABELS[QMessageBox.StandardButton.Save], "Сохранить")
        self.assertEqual(
            _BUTTON_LABELS[QMessageBox.StandardButton.Discard], "Не сохранять"
        )

    def test_every_label_contains_cyrillic(self):
        for label in _BUTTON_LABELS.values():
            self.assertTrue(_CYRILLIC.search(label), label)

    def test_yes_no_buttons_return_standard_values(self):
        dialog = self._mk(
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default=QMessageBox.StandardButton.No,
        )
        yes = [b for b in dialog.findChildren(QPushButton) if b.text() == "Да"][0]
        no = [b for b in dialog.findChildren(QPushButton) if b.text() == "Нет"][0]
        yes.click()
        self.assertEqual(
            dialog.result_value, QMessageBox.StandardButton.Yes
        )
        dialog2 = self._mk(buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        [b for b in dialog2.findChildren(QPushButton) if b.text() == "Нет"][0].click()
        self.assertEqual(
            dialog2.result_value, QMessageBox.StandardButton.No
        )

    def test_save_discard_cancel_buttons(self):
        buttons = (
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )
        dialog = self._mk(buttons=buttons, default=QMessageBox.StandardButton.Save)
        labels = [b.text() for b in dialog.findChildren(QPushButton)]
        for expected in ("Сохранить", "Не сохранять", "Отмена"):
            self.assertIn(expected, labels)

        cancel = [b for b in dialog.findChildren(QPushButton) if b.text() == "Отмена"][0]
        cancel.click()
        self.assertEqual(
            dialog.result_value, QMessageBox.StandardButton.Cancel
        )

    def test_esc_returns_default_button(self):
        from PySide6.QtGui import QKeyEvent

        dialog = self._mk(
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default=QMessageBox.StandardButton.No,
        )
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
        )
        dialog.keyPressEvent(event)
        self.assertEqual(dialog.result_value, QMessageBox.StandardButton.No)

    def test_close_returns_default_button(self):
        dialog = self._mk(
            buttons=QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
            default=QMessageBox.StandardButton.Cancel,
        )
        dialog.reject()
        self.assertEqual(dialog.result_value, QMessageBox.StandardButton.Cancel)

    def test_custom_pair_buttons_return_values(self):
        dialog = CopyableMessageBox(
            None,
            title="x",
            text="y",
            buttons=[("Заменить", "replace"), ("Добавить", "append"), ("Отмена", None)],
            defaultButton=None,
        )
        self.addCleanup(lambda: (dialog.close(), dialog.deleteLater()))
        replace = [b for b in dialog.findChildren(QPushButton) if b.text() == "Заменить"][0]
        replace.click()
        self.assertEqual(dialog.result_value, "replace")
        self.assertIsNone(dialog._default_value)


class TestEscapedTextLegibility(unittest.TestCase):
    """Гарнитура: текст «Копировать» обязан попадать в буфер целиком."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_copy_is_full_text_not_selection(self):
        from PySide6.QtGui import QTextCursor

        dialog = CopyableMessageBox(
            None, title="Тест", text="Первая\nВторая строка",
        )
        self.addCleanup(lambda: (dialog.close(), dialog.deleteLater()))
        edit = dialog._message
        cursor = edit.textCursor()
        cursor.setPosition(5)
        cursor.setPosition(0, QTextCursor.MoveMode.KeepAnchor)
        edit.setTextCursor(cursor)
        copy = [b for b in dialog.findChildren(QPushButton) if b.text() == "Копировать"][0]
        copy.click()
        self.assertEqual(self._app.clipboard().text(), "Первая\nВторая строка")


if __name__ == "__main__":
    unittest.main()