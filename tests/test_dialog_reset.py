"""
tests/test_dialog_reset.py

Тесты механизма сброса полей диалогов (gui/dialog_reset.py) и его
встройки во все диалоги с полями ввода.
"""

from __future__ import annotations

import unittest

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QWidget,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QCheckBox,
    QRadioButton,
    QGroupBox,
    QPushButton,
    QPlainTextEdit,
    QLabel,
    QVBoxLayout,
)

from gui.dialog_reset import (
    snapshot_dialog_defaults,
    restore_dialog_defaults,
)

_app = QApplication.instance() or QApplication([])


class ResetSnapshotTest(unittest.TestCase):

    def _dialog(self) -> QDialog:
        dialog = QDialog()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        dialog.setLayout(QVBoxLayout())
        return dialog

    def test_restore_line_edit(self):
        dialog = self._dialog()
        line = QLineEdit("начальный текст")
        dialog.layout().addWidget(line)
        snapshot_dialog_defaults(dialog)

        line.setText("изменённый текст")

        restore_dialog_defaults(dialog)
        self.assertEqual(line.text(), "начальный текст")

    def test_restore_combo_box(self):
        dialog = self._dialog()
        combo = QComboBox()
        combo.addItems(["item1", "item2"])
        combo.setCurrentIndex(0)
        dialog.layout().addWidget(combo)
        snapshot_dialog_defaults(dialog)

        combo.setCurrentIndex(1)

        restore_dialog_defaults(dialog)
        self.assertEqual(combo.currentIndex(), 0)

    def test_restore_spin_box(self):
        dialog = self._dialog()
        spin = QSpinBox()
        spin.setValue(30)
        dialog.layout().addWidget(spin)
        snapshot_dialog_defaults(dialog)

        spin.setValue(90)

        restore_dialog_defaults(dialog)
        self.assertEqual(spin.value(), 30)

    def test_restore_check_box(self):
        dialog = self._dialog()
        box = QCheckBox("опция")
        box.setChecked(True)
        dialog.layout().addWidget(box)
        snapshot_dialog_defaults(dialog)

        box.setChecked(False)

        restore_dialog_defaults(dialog)
        self.assertTrue(box.isChecked())

    def test_restore_checkable_group_box(self):
        dialog = self._dialog()
        group = QGroupBox("группа")
        group.setCheckable(True)
        group.setChecked(True)
        dialog.layout().addWidget(group)
        snapshot_dialog_defaults(dialog)

        group.setChecked(False)

        restore_dialog_defaults(dialog)
        self.assertTrue(group.isChecked())

    def test_restore_plain_text_edit(self):
        dialog = self._dialog()
        text = QPlainTextEdit("исходный текст")
        dialog.layout().addWidget(text)
        snapshot_dialog_defaults(dialog)

        text.setPlainText("изменённый текст")

        restore_dialog_defaults(dialog)
        self.assertEqual(text.toPlainText(), "исходный текст")

    def test_restore_radio_group(self):
        dialog = self._dialog()
        first = QRadioButton("вариант 1")
        second = QRadioButton("вариант 2")
        first.setChecked(True)
        dialog.layout().addWidget(first)
        dialog.layout().addWidget(second)
        snapshot_dialog_defaults(dialog)

        second.setChecked(True)

        restore_dialog_defaults(dialog)
        self.assertTrue(first.isChecked())
        self.assertFalse(second.isChecked())

    def test_restore_skips_read_only_line_edit(self):
        dialog = self._dialog()
        line = QLineEdit("только чтение")
        line.setReadOnly(True)
        dialog.layout().addWidget(line)
        snapshot_dialog_defaults(dialog)

        self.assertEqual(getattr(dialog, "_dialog_default_snapshot"), [])

    def test_snapshot_skips_unsupported_widgets(self):
        dialog = self._dialog()
        label = QLabel("заголовок без состояния")
        dialog.layout().addWidget(label)

        snapshot_dialog_defaults(dialog)

        self.assertEqual(getattr(dialog, "_dialog_default_snapshot"), [])

    def test_restore_is_idempotent(self):
        dialog = self._dialog()
        line = QLineEdit("исходный")
        dialog.layout().addWidget(line)
        snapshot_dialog_defaults(dialog)

        line.setText("раз")
        restore_dialog_defaults(dialog)
        restore_dialog_defaults(dialog)

        self.assertEqual(line.text(), "исходный")

    def test_restore_after_widget_deleted(self):
        dialog = self._dialog()
        line = QLineEdit("исходный")
        dialog.layout().addWidget(line)
        snapshot_dialog_defaults(dialog)
        line.deleteLater()
        QApplication.processEvents()

        restore_dialog_defaults(dialog)

    def test_reset_button_added_and_works(self):
        from gui.dialog_reset import add_dialog_reset_button

        dialog = self._dialog()
        line = QLineEdit("исходный")
        dialog.layout().addWidget(line)
        snapshot_dialog_defaults(dialog)

        button = add_dialog_reset_button(dialog)
        self.assertIsInstance(button, QPushButton)
        self.assertEqual(button.text(), "Сброс")

        line.setText("изменённый")

        button.click()
        self.assertEqual(line.text(), "исходный")


class DialogResetButtonTest(unittest.TestCase):

    def _start(self, factory):
        dialog = factory()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        buttons = [
            w for w in dialog.findChildren(QWidget)
            if isinstance(w, QPushButton) and w.text() == "Сброс"
        ]
        return dialog, buttons

    def test_server_dialog_reset_fields(self):
        from gui.server_dialog import ServerDialog

        dialog, buttons = self._start(ServerDialog)
        self.assertEqual(len(buttons), 1)

        dialog.ed_name.setText("изменено")
        buttons[0].click()
        self.assertEqual(dialog.ed_name.text(), "")

    def test_credentials_dialog_reset_fields(self):
        from gui.credentials_dialog import CredentialsDialog

        dialog, buttons = self._start(
            lambda: CredentialsDialog(server_label="test_server")
        )
        self.assertEqual(len(buttons), 1)

        dialog.ed_user.setText("новый")
        dialog.ed_password.setText("пароль")
        buttons[0].click()
        self.assertEqual(dialog.ed_user.text(), "")
        self.assertEqual(dialog.ed_password.text(), "")

    def test_credentials_dialog_reset_keeps_prefilled_user(self):
        from gui.credentials_dialog import CredentialsDialog

        dialog, buttons = self._start(
            lambda: CredentialsDialog(server_label="s", user="alice")
        )
        dialog.ed_user.setText("bob")
        buttons[0].click()
        self.assertEqual(dialog.ed_user.text(), "alice")

    def test_attach_db_dialog_reset_fields(self):
        from gui.attach_db_dialog import AttachDatabaseDialog

        dialog, buttons = self._start(AttachDatabaseDialog)
        self.assertEqual(len(buttons), 1)

        dialog._db_name.setText("модифицированная")
        dialog._mdf_path.setText(r"c:\mnt\data.mdf")
        buttons[0].click()
        self.assertEqual(dialog._db_name.text(), "")
        self.assertEqual(dialog._mdf_path.text(), "")

    def test_restore_db_dialog_reset_fields(self):
        from gui.restore_db_dialog import RestoreDatabaseDialog

        dialog, buttons = self._start(RestoreDatabaseDialog)
        self.assertEqual(len(buttons), 1)

        dialog._db_name.setText("модифицированная")
        dialog._bak_path.setText(r"c:\mnt\db.bak")
        dialog._replace_cb.setChecked(False)
        buttons[0].click()
        self.assertEqual(dialog._db_name.text(), "")
        self.assertEqual(dialog._bak_path.text(), "")
        self.assertTrue(dialog._replace_cb.isChecked())

    def test_master_password_dialog_reset_unlock_mode(self):
        from gui.master_password_dialog import MasterPasswordDialog

        dialog, buttons = self._start(MasterPasswordDialog)
        self.assertEqual(len(buttons), 1)

        dialog.ed_password.setText("секрет")
        buttons[0].click()
        self.assertEqual(dialog.ed_password.text(), "")

    def test_master_password_dialog_reset_create_mode(self):
        from gui.master_password_dialog import MasterPasswordDialog

        dialog, buttons = self._start(
            lambda: MasterPasswordDialog(mode="create")
        )

        dialog.ed_password.setText("секрет")
        dialog.ed_confirm.setText("секрет2")
        buttons[0].click()
        self.assertEqual(dialog.ed_password.text(), "")
        self.assertEqual(dialog.ed_confirm.text(), "")

    def test_settings_dialog_reset_radios(self):
        from gui.settings_dialog import SettingsDialog

        dialog, buttons = self._start(SettingsDialog)
        self.assertEqual(len(buttons), 1)

        initial_master = dialog.rb_master.isChecked()
        initial_file = dialog.rb_file.isChecked()
        dialog.rb_master.setChecked(not initial_master)
        dialog.rb_file.setChecked(not initial_file)
        buttons[0].click()
        self.assertEqual(dialog.rb_master.isChecked(), initial_master)
        self.assertEqual(dialog.rb_file.isChecked(), initial_file)

    def test_connection_strings_dialog_reset_import_fields(self):
        from gui.connection_strings_dialog import ConnectionStringsDialog

        dialog, buttons = self._start(ConnectionStringsDialog)
        self.assertEqual(len(buttons), 1)

        dialog.ed_import.setPlainText("mysql://u:p@h:3306")
        dialog.chk_replace.setChecked(not dialog.chk_replace.isChecked())
        buttons[0].click()
        self.assertEqual(dialog.ed_import.toPlainText(), "")
        self.assertFalse(dialog.chk_replace.isChecked())
    def test_scripts_manager_dialog_has_no_reset_button(self):
        from gui.scripts_manager_dialog import ScriptsManagerDialog

        dialog, buttons = self._start(ScriptsManagerDialog)
        self.assertEqual(buttons, [])

    def test_update_dialog_has_no_reset_button(self):
        from gui.update_dialog import UpdateDialog

        dialog, buttons = self._start(lambda: UpdateDialog("1.0.0"))
        self.assertEqual(buttons, [])


if __name__ == "__main__":
    unittest.main()
