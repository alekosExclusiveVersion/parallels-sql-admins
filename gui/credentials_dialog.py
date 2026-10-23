"""
gui/credentials_dialog.py

Диалог ввода логина и пароля для сервера, у которого реквизиты не заданы
(или оказались неверными).

Пароль нигде не логируется. При включённом чекбоксе «Сохранить» реквизиты
пишутся в servers.json (в зашифрованном виде) через
ServerRegistry.set_credentials().
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from gui.widgets.copyable_alert import CopyableMessageBox
from gui.dialog_reset import snapshot_dialog_defaults, add_dialog_reset_button


class CredentialsDialog(QDialog):

    def __init__(
        self,
        server_label: str,
        user: str = "",
        parent=None,
        message: str = "",
        allow_persist: bool = True,
    ) -> None:
        super().__init__(parent)

        self._server_label = server_label
        self._allow_persist = allow_persist

        self.setWindowTitle("Учётные данные")
        self.setMinimumWidth(440)
        self._build_ui(message)

        self.ed_user.setText(user)
        if user:
            self.ed_password.setFocus()
        else:
            self.ed_user.setFocus()

        snapshot_dialog_defaults(self)
        add_dialog_reset_button(self)

    def _build_ui(self, message: str) -> None:
        layout = QVBoxLayout(self)

        hint = QLabel(
            f"Сервер: {self._server_label}\n\n"
            "Для подключения не заданы логин и пароль."
        )
        hint.setWordWrap(True)
        hint.setObjectName("textMuted")
        layout.addWidget(hint)

        if message:
            warning = QLabel(message)
            warning.setWordWrap(True)
            layout.addWidget(warning)

        layout.addSpacing(8)

        form = QFormLayout()

        self.ed_user = QLineEdit()
        self.ed_user.setPlaceholderText("Логин")
        self.ed_user.setMinimumWidth(300)
        form.addRow("Логин", self.ed_user)

        self.ed_password = QLineEdit()
        self.ed_password.setPlaceholderText("Пароль")
        self.ed_password.setEchoMode(QLineEdit.Password)
        form.addRow("Пароль", self.ed_password)

        layout.addLayout(form)

        self.chk_show = QCheckBox("Показать пароль")
        self.chk_show.toggled.connect(self._toggle_visibility)
        layout.addWidget(self.chk_show)

        self.chk_remember = QCheckBox("Сохранить в servers.json")
        self.chk_remember.setChecked(True)
        self.chk_remember.setVisible(self._allow_persist)
        layout.addWidget(self.chk_remember)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Ok).setText("Продолжить")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        layout.addWidget(buttons)

    def _toggle_visibility(self, show: bool) -> None:
        self.ed_password.setEchoMode(
            QLineEdit.Normal if show else QLineEdit.Password
        )

    def _on_accept(self) -> None:
        if not self.ed_user.text().strip():
            CopyableMessageBox.warning(
                self, "Учётные данные", "Введите логин.",
            )
            self.ed_user.setFocus()
            return

        if not self.ed_password.text():
            CopyableMessageBox.warning(
                self, "Учётные данные", "Введите пароль.",
            )
            self.ed_password.setFocus()
            return

        self.accept()

    def user(self) -> str:
        return self.ed_user.text().strip()

    def password(self) -> str:
        return self.ed_password.text()

    def remember(self) -> bool:
        return self._allow_persist and self.chk_remember.isChecked()
