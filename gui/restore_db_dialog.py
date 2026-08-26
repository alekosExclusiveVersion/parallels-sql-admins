"""
gui/restore_db_dialog.py

Диалог восстановления БД из резервной копии (MSSQL):
  имя БД + путь к .bak файлу + REPLACE checkbox.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class RestoreDatabaseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Восстановить из резервной копии")
        self.setMinimumWidth(480)

        self._db_name = QLineEdit()
        self._db_name.setPlaceholderText("Имя базы данных")

        self._bak_path = QLineEdit()
        self._bak_path.setPlaceholderText(
            r"\\server\share\backups\db.bak"
        )

        browse = QPushButton("Обзор…")
        browse.setFixedWidth(80)
        browse.clicked.connect(self._browse)

        path_row = QHBoxLayout()
        path_row.addWidget(self._bak_path, 1)
        path_row.addWidget(browse)

        self._replace_cb = QCheckBox("Заменить существующую БД (REPLACE)")
        self._replace_cb.setChecked(True)

        btn_ok = QPushButton("Восстановить")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._accept)

        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Имя БД:"))
        layout.addWidget(self._db_name)
        layout.addSpacing(8)
        layout.addWidget(QLabel("Путь к резервной копии (.bak):"))
        layout.addLayout(path_row)
        layout.addSpacing(8)
        layout.addWidget(self._replace_cb)
        layout.addSpacing(16)
        layout.addLayout(btn_row)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выбрать файл бэкапа",
            "",
            "Backup-файлы (*.bak);;Все файлы (*.*)",
        )
        if path:
            self._bak_path.setText(path)

    def _accept(self):
        if self._db_name.text().strip() and self._bak_path.text().strip():
            self.accept()

    def data(self) -> tuple[str, str, bool]:
        return (
            self._db_name.text().strip(),
            self._bak_path.text().strip(),
            self._replace_cb.isChecked(),
        )
