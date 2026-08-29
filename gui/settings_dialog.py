"""
gui/settings_dialog.py

Диалог «Настройки» приложения.

Раздел «Конфиденциальность»: выбор способа защиты ключа шифрования
реквизитов — персональный мастер-пароль или ключ на компьютере.

Смена режима выполняет перешифрование servers.json (registry.rekey):
требуется разблокировка текущего хранилища, затем данные шифруются уже
новым ключом. Предпочтение запоминается в settings.ini (security/backend)
и используется при создании нового хранилища.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
)

from common.key_store import (
    BACKEND_FILE_KEY,
    BACKEND_MASTER_PASSWORD,
    VaultError,
    WrongMasterPasswordError,
)
from common.server_registry import registry
from gui import styles as theme_styles
from gui.master_password_dialog import MasterPasswordDialog
from gui.widgets.copyable_alert import CopyableMessageBox


class SettingsDialog(QDialog):

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(520)
        self._build_ui()
        self._load_current()

    # ----------------------------------------------------------
    # UI
    # ----------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QLabel("Конфиденциальность")
        header.setObjectName("sectionTitle")
        layout.addWidget(header)

        intro = QLabel(
            "Пароли серверов хранятся в servers.json в зашифрованном виде. "
            "Здесь выбирается, как защищается ключ шифрования."
        )
        intro.setWordWrap(True)
        intro.setObjectName("textMuted")
        layout.addWidget(intro)
        layout.addSpacing(8)

        self.rb_master = QRadioButton("Персональный мастер-пароль")
        layout.addWidget(self.rb_master)
        l_master = QLabel(
            "Ключ выводится из вашего пароля (PBKDF2) и нигде не хранится. "
            "Без пароля данные не расшифровать даже при наличии бинарника "
            "и файла. Файл коллеги с другим паролем не прочитать."
        )
        l_master.setWordWrap(True)
        l_master.setObjectName("textMuted")
        l_master.setContentsMargins(22, 0, 0, 0)
        layout.addWidget(l_master)

        layout.addSpacing(6)

        self.rb_file = QRadioButton("Ключ на компьютере")
        layout.addWidget(self.rb_file)
        l_file = QLabel(
            "Случайный ключ в файле servers.key рядом с servers.json "
            "(права 0600). Данные переезжают вместе с этим файлом. "
            "Защита действует от утечки одного servers.json; "
            "не передавайте файл ключа посторонним."
        )
        l_file.setWordWrap(True)
        l_file.setObjectName("textMuted")
        l_file.setContentsMargins(22, 0, 0, 0)
        layout.addWidget(l_file)

        layout.addSpacing(16)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_current(self) -> None:
        meta = registry.read_meta()
        kind = (
            meta.get("kind")
            if meta
            else theme_styles.load_security_backend()
        )
        self.rb_master.setChecked(kind != BACKEND_FILE_KEY)
        self.rb_file.setChecked(kind == BACKEND_FILE_KEY)

    # ----------------------------------------------------------
    # Логика смены режима
    # ----------------------------------------------------------

    def _selected_kind(self) -> str:
        return (
            BACKEND_MASTER_PASSWORD
            if self.rb_master.isChecked()
            else BACKEND_FILE_KEY
        )

    def _on_accept(self) -> None:
        kind = self._selected_kind()

        if kind == self._current_kind():
            self.accept()
            return

        if not self._prepare_rekey():
            return

        try:
            if not self._rekey(kind):
                return
        except (VaultError, WrongMasterPasswordError) as ex:
            CopyableMessageBox.warning(self, "Конфиденциальность", str(ex))
            return

        theme_styles.save_security_backend(kind)
        CopyableMessageBox.information(
            self,
            "Конфиденциальность",
            "Режим защиты ключа изменён. Данные перешифрованы.",
        )
        self.accept()

    def _current_kind(self) -> str:
        meta = registry.read_meta()
        if meta:
            return meta.get("kind")
        return theme_styles.load_security_backend()

    def _prepare_rekey(self) -> bool:
        """Разблокирует текущее хранилище, если оно зашифровано.

        False — пользователь отменил разблокировку.
        """
        if registry.vault.unlocked:
            return True
        if registry.read_meta() is None:
            return True
        if registry.needs_unlock():
            return self._prompt_unlock()
        registry.ensure_key()
        return registry.vault.unlocked

    def _rekey(self, kind: str) -> bool:
        """Перешифровывает данные под новый режим. False — отмена пользователем."""
        if kind == BACKEND_MASTER_PASSWORD:
            dialog = MasterPasswordDialog(self, mode="create")
            if dialog.exec() != MasterPasswordDialog.Accepted:
                return False
            password = dialog.password()
        else:
            password = None
        registry.rekey(kind, password)
        return True

    def _prompt_unlock(self) -> bool:
        while True:
            dialog = MasterPasswordDialog(self, mode="unlock")
            if dialog.exec() != MasterPasswordDialog.Accepted:
                return False
            try:
                registry.unlock_master(dialog.password())
                return True
            except WrongMasterPasswordError:
                CopyableMessageBox.warning(
                    self,
                    "Мастер-пароль",
                    "Неверный мастер-пароль. Попробуйте ещё раз.",
                )
