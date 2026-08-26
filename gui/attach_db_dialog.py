"""
gui/attach_db_dialog.py

Диалог присоединения БД (MSSQL):
  имя БД + путь к MDF-файлу (QLineEdit + Browse).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class AttachDatabaseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Присоединить БД")
        self.setMinimumWidth(480)

        self._db_name = QLineEdit()
        self._db_name.setPlaceholderText("Имя базы данных")

        self._mdf_path = QLineEdit()
        self._mdf_path.setPlaceholderText(
            r"\\server\share\data\file.mdf"
        )

        browse = QPushButton("Обзор…")
        browse.setFixedWidth(80)
        browse.clicked.connect(self._browse)

        path_row = QHBoxLayout()
        path_row.addWidget(self._mdf_path, 1)
        path_row.addWidget(browse)

        btn_ok = QPushButton("Присоединить")
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
        layout.addWidget(QLabel("Путь к MDF-файлу:"))
        layout.addLayout(path_row)
        layout.addSpacing(16)
        layout.addLayout(btn_row)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выбрать MDF-файл",
            "",
            "MDF-файлы (*.mdf);;Все файлы (*.*)",
        )
        if path:
            self._mdf_path.setText(path)

    def _accept(self):
        if self._db_name.text().strip() and self._mdf_path.text().strip():
            self.accept()

    def data(self) -> tuple[str, str]:
        return (
            self._db_name.text().strip(),
            self._mdf_path.text().strip(),
        )
