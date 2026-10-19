"""
tests/test_credentials_dialog.py

Тесты диалога ввода логина/пароля сервера (gui/credentials_dialog.py).
"""

import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QLabel, QLineEdit

from gui.credentials_dialog import CredentialsDialog

_app = QApplication.instance() or QApplication([])


class TestCredentialsDialog(unittest.TestCase):

    def _dialog(self, **kwargs):
        dialog = CredentialsDialog(
            kwargs.pop("server_label", "ext4 (ext4.tradesoft.ru:3306)"),
            **kwargs,
        )
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        return dialog

    def test_prefills_user(self):
        dialog = self._dialog(user="alice")

        self.assertEqual(dialog.user(), "alice")
        self.assertEqual(dialog.password(), "")

    def test_user_is_stripped(self):
        dialog = self._dialog()
        dialog.ed_user.setText("  alice  ")

        self.assertEqual(dialog.user(), "alice")

    def test_password_preserved_verbatim(self):
        dialog = self._dialog()
        dialog.ed_user.setText("alice")
        dialog.ed_password.setText("  s3cret  ")

        self.assertEqual(dialog.password(), "  s3cret  ")

    def test_password_masked_by_default(self):
        dialog = self._dialog()

        self.assertEqual(
            dialog.ed_password.echoMode(), QLineEdit.Password,
        )

    def test_show_password_toggle(self):
        dialog = self._dialog()

        dialog.chk_show.setChecked(True)
        self.assertEqual(dialog.ed_password.echoMode(), QLineEdit.Normal)

        dialog.chk_show.setChecked(False)
        self.assertEqual(dialog.ed_password.echoMode(), QLineEdit.Password)

    def test_remember_checked_by_default(self):
        dialog = self._dialog()

        self.assertTrue(dialog.remember())

    def test_remember_off(self):
        dialog = self._dialog()
        dialog.chk_remember.setChecked(False)

        self.assertFalse(dialog.remember())

    def test_remember_hidden_when_persist_disallowed(self):
        dialog = self._dialog(allow_persist=False)

        self.assertTrue(dialog.chk_remember.isHidden())
        self.assertFalse(dialog.remember())

    def test_empty_user_rejected(self):
        dialog = self._dialog()
        dialog.ed_password.setText("secret")

        with patch(
            "gui.credentials_dialog.CopyableMessageBox.warning"
        ) as warning:
            dialog._on_accept()

        self.assertEqual(dialog.result(), 0)
        self.assertEqual(warning.call_count, 1)

    def test_empty_password_rejected(self):
        dialog = self._dialog()
        dialog.ed_user.setText("alice")

        with patch(
            "gui.credentials_dialog.CopyableMessageBox.warning"
        ) as warning:
            dialog._on_accept()

        self.assertEqual(dialog.result(), 0)
        self.assertEqual(warning.call_count, 1)

    def test_valid_credentials_accepted(self):
        dialog = self._dialog()
        dialog.ed_user.setText("alice")
        dialog.ed_password.setText("secret")

        dialog._on_accept()

        self.assertEqual(
            dialog.result(), CredentialsDialog.Accepted,
        )

    def test_shows_server_and_backend_message(self):
        dialog = self._dialog(
            server_label="SQL Prod (sql-prod:1433)",
            message="Сервер отклонил предыдущие учётные данные.",
        )

        joined = " ".join(
            label.text() for label in dialog.findChildren(QLabel)
        )

        self.assertIn("SQL Prod (sql-prod:1433)", joined)
        self.assertIn("отклонил предыдущие", joined)


if __name__ == "__main__":
    unittest.main()
