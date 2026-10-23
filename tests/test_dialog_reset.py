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

    def test_field_reset_enables_clear_button(self):
        from gui.dialog_reset import enable_field_reset

        dialog = self._dialog()
        line = QLineEdit("исходный")
        dialog.layout().addWidget(line)

        enable_field_reset(dialog)

        self.assertTrue(line.isClearButtonEnabled())

        line.setText("изменённый")
        line.clear()
        self.assertEqual(line.text(), "")

    def test_field_reset_skips_read_only_line_edit(self):
        from gui.dialog_reset import enable_field_reset

        dialog = self._dialog()
        line = QLineEdit("только чтение")
        line.setReadOnly(True)
        dialog.layout().addWidget(line)

        enable_field_reset(dialog)

        self.assertFalse(line.isClearButtonEnabled())

    def test_field_reset_adds_corner_button_to_plain_text_edit(self):
        from gui.dialog_reset import enable_field_reset

        dialog = self._dialog()
        edit = QPlainTextEdit()
        edit.setPlainText("исходный текст")
        dialog.layout().addWidget(edit)

        enable_field_reset(dialog)

        corner = edit.cornerWidget()
        self.assertIsNotNone(corner)

        edit.setPlainText("изменённый текст")
        corner.click()
        self.assertEqual(edit.toPlainText(), "")

    def test_field_reset_enables_clear_button_on_combo(self):
        from gui.dialog_reset import enable_field_reset

        dialog = self._dialog()
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItem("item1")
        dialog.layout().addWidget(combo)

        enable_field_reset(dialog)

        self.assertTrue(combo.lineEdit().isClearButtonEnabled())

    def test_field_reset_does_not_add_buttons(self):
        from gui.dialog_reset import enable_field_reset

        dialog = self._dialog()
        dialog.layout().addWidget(QLineEdit("поле"))
        dialog.layout().addWidget(QPlainTextEdit())

        enable_field_reset(dialog)

        self.assertEqual(dialog.findChildren(QPushButton), [])


class DialogFieldResetTest(unittest.TestCase):

    def _start(self, factory):
        dialog = factory()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        buttons = [
            w for w in dialog.findChildren(QWidget)
            if isinstance(w, QPushButton) and w.text() == "Сброс"
        ]
        line_edits = [
            w for w in dialog.findChildren(QLineEdit)
            if not w.isReadOnly()
        ]
        return dialog, buttons, line_edits

    def test_server_dialog_reset_fields(self):
        from gui.server_dialog import ServerDialog

        dialog, buttons, line_edits = self._start(ServerDialog)
        self.assertEqual(buttons, [])
        self.assertTrue(line_edits)
        self.assertTrue(
            all(le.isClearButtonEnabled() for le in line_edits)
        )

        dialog.ed_name.setText("изменено")
        dialog.ed_name.clear()
        self.assertEqual(dialog.ed_name.text(), "")

    def test_credentials_dialog_reset_fields(self):
        from gui.credentials_dialog import CredentialsDialog

        dialog, buttons, line_edits = self._start(
            lambda: CredentialsDialog(server_label="test_server")
        )
        self.assertEqual(buttons, [])
        self.assertTrue(
            all(le.isClearButtonEnabled() for le in line_edits)
        )

        dialog.ed_user.setText("новый")
        dialog.ed_password.setText("пароль")
        dialog.ed_user.clear()
        dialog.ed_password.clear()
        self.assertEqual(dialog.ed_user.text(), "")
        self.assertEqual(dialog.ed_password.text(), "")

    def test_attach_db_dialog_reset_fields(self):
        from gui.attach_db_dialog import AttachDatabaseDialog

        dialog, buttons, line_edits = self._start(AttachDatabaseDialog)
        self.assertEqual(buttons, [])
        self.assertTrue(
            all(le.isClearButtonEnabled() for le in line_edits)
        )

        dialog._db_name.setText("модифицированная")
        dialog._mdf_path.setText(r"c:\mnt\data.mdf")
        dialog._db_name.clear()
        dialog._mdf_path.clear()
        self.assertEqual(dialog._db_name.text(), "")
        self.assertEqual(dialog._mdf_path.text(), "")

    def test_restore_db_dialog_reset_fields(self):
        from gui.restore_db_dialog import RestoreDatabaseDialog

        dialog, buttons, line_edits = self._start(RestoreDatabaseDialog)
        self.assertEqual(buttons, [])
        self.assertTrue(
            all(le.isClearButtonEnabled() for le in line_edits)
        )

        dialog._db_name.setText("модифицированная")
        dialog._bak_path.setText(r"c:\mnt\db.bak")
        dialog._db_name.clear()
        dialog._bak_path.clear()
        self.assertEqual(dialog._db_name.text(), "")
        self.assertEqual(dialog._bak_path.text(), "")

    def test_master_password_dialog_reset_unlock_mode(self):
        from gui.master_password_dialog import MasterPasswordDialog

        dialog, buttons, line_edits = self._start(MasterPasswordDialog)
        self.assertEqual(buttons, [])
        self.assertTrue(
            all(le.isClearButtonEnabled() for le in line_edits)
        )

        dialog.ed_password.setText("секрет")
        dialog.ed_password.clear()
        self.assertEqual(dialog.ed_password.text(), "")

    def test_master_password_dialog_reset_create_mode(self):
        from gui.master_password_dialog import MasterPasswordDialog

        dialog, buttons, line_edits = self._start(
            lambda: MasterPasswordDialog(mode="create")
        )
        self.assertEqual(buttons, [])

        dialog.ed_password.setText("секрет")
        dialog.ed_confirm.setText("секрет2")
        dialog.ed_password.clear()
        dialog.ed_confirm.clear()
        self.assertEqual(dialog.ed_password.text(), "")
        self.assertEqual(dialog.ed_confirm.text(), "")

    def test_connection_strings_dialog_reset_import_fields(self):
        from gui.connection_strings_dialog import ConnectionStringsDialog

        dialog, buttons, line_edits = self._start(ConnectionStringsDialog)
        self.assertEqual(buttons, [])

        corner = dialog.ed_import.cornerWidget()
        self.assertIsNotNone(corner)
        dialog.ed_import.setPlainText("mysql://u:p@h:3306")
        corner.click()
        self.assertEqual(dialog.ed_import.toPlainText(), "")

    def test_scripts_manager_dialog_has_no_reset_button(self):
        from gui.scripts_manager_dialog import ScriptsManagerDialog

        dialog, buttons, _ = self._start(ScriptsManagerDialog)
        self.assertEqual(buttons, [])

    def test_update_dialog_has_no_reset_button(self):
        from gui.update_dialog import UpdateDialog

        dialog, buttons, _ = self._start(lambda: UpdateDialog("1.0.0"))
        self.assertEqual(buttons, [])


if __name__ == "__main__":
    unittest.main()
