"""
gui/master_password_dialog.py

Диалог персонального мастер-пароля.

Два режима:
- unlock — «Введите мастер-пароль» (разблокировка существующего хранилища);
- create — «Создайте мастер-пароль» (первый запуск сотрудника/смена режима).

Пароль нигде не сохраняется: из него выводится ключ шифрования
(PBKDF2-HMAC-SHA256, см. common/key_store.py). Забытый пароль означает
потерю доступа к данным — предупреждаем при создании.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from gui.widgets.copyable_alert import CopyableMessageBox

MIN_PASSWORD_LENGTH = 6


class MasterPasswordDialog(QDialog):

    def __init__(
        self,
        parent=None,
        mode: str = "unlock",
        title: str | None = None,
    ) -> None:
        super().__init__(parent)

        self._mode = mode if mode == "create" else "unlock"
        self.setWindowTitle(
            title
            or (
                "Создать мастер-пароль"
                if self._mode == "create"
                else "Разблокировать хранилище"
            )
        )
        self.setMinimumWidth(420)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        if self._mode == "create":
            hint = QLabel(
                "Придумайте мастер-пароль. Он нигде не хранится и не "
                "передаётся — из него выводится ключ шифрования ваших "
                "реквизитов.\n\n"
                "Забытый пароль означает потерю доступа к сохранённым "
                "паролям серверов. Восстановить его невозможно."
            )
            hint.setWordWrap(True)
            hint.setObjectName("textMuted")
        else:
            hint = QLabel(
                "Введите мастер-пароль, чтобы расшифровать реквизиты "
                "подключения."
            )
            hint.setWordWrap(True)
            hint.setObjectName("textMuted")

        layout.addWidget(hint)
        layout.addSpacing(8)

        self.ed_password = QLineEdit()
        self.ed_password.setPlaceholderText(
            "Мастер-пароль" if self._mode == "unlock" else "Придумайте пароль"
        )
        self.ed_password.setEchoMode(QLineEdit.Password)
        self.ed_password.setMinimumWidth(360)
        layout.addWidget(self.ed_password)

        if self._mode == "create":
            self.ed_confirm = QLineEdit()
            self.ed_confirm.setPlaceholderText("Повторите пароль")
            self.ed_confirm.setEchoMode(QLineEdit.Password)
            layout.addWidget(self.ed_confirm)

        self.chk_show = QCheckBox("Показать пароль")
        self.chk_show.toggled.connect(self._toggle_visibility)
        layout.addWidget(self.chk_show)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Ok).setText(
            "Создать" if self._mode == "create" else "Разблокировать"
        )
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        layout.addWidget(buttons)

        self.ed_password.setFocus()

    def _toggle_visibility(self, show: bool) -> None:
        echo = QLineEdit.Normal if show else QLineEdit.Password
        self.ed_password.setEchoMode(echo)
        if self._mode == "create":
            self.ed_confirm.setEchoMode(echo)

    def _on_accept(self) -> None:
        password = self.ed_password.text()

        if not password:
            CopyableMessageBox.warning(self, "Мастер-пароль", "Введите пароль.")
            return

        if self._mode == "create":
            if len(password) < MIN_PASSWORD_LENGTH:
                CopyableMessageBox.warning(
                    self,
                    "Мастер-пароль",
                    f"Пароль слишком короткий: минимум "
                    f"{MIN_PASSWORD_LENGTH} символов.",
                )
                return
            if password != self.ed_confirm.text():
                CopyableMessageBox.warning(
                    self,
                    "Мастер-пароль",
                    "Пароли не совпадают.",
                )
                return

        self.accept()

    def password(self) -> str:
        return self.ed_password.text()
