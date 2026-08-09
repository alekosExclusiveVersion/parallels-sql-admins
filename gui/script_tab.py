"""
gui/script_tab.py

Вкладка «Скрипт: <имя>» — редактируемая копия скрипта с действиями
«Вставить в консоль» и «Запустить проверку». Открывается из меню
«Скрипты», закрывается крестиком вкладки с подтверждением сохранения.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.icons import icon


class ScriptTab(QWidget):
    """Отдельная вкладка с одним скриптом (имя + тело)."""

    insertToConsoleRequested = Signal(str)
    runRequested = Signal(str)

    def __init__(self, name: str, body: str, parent=None) -> None:
        super().__init__(parent)
        self._name = name
        self._original = body

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QHBoxLayout()

        self.lbl_title = QLabel(name)
        self.lbl_title.setObjectName("SectionTitle")
        header.addWidget(self.lbl_title)

        header.addStretch()

        layout.addLayout(header)

        self.editor = QPlainTextEdit()
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        console_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        console_font.setPointSize(12)
        self.editor.setFont(console_font)
        self.editor.setPlainText(body)
        layout.addWidget(self.editor, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()

        self.btn_run = QPushButton("Запустить проверку")
        self.btn_run.setObjectName("btn_primary")
        self.btn_run.setIcon(icon("play_arrow", 16, "#ffffff"))
        self.btn_run.clicked.connect(
            lambda: self.runRequested.emit(self.current_text())
        )
        buttons.addWidget(self.btn_run)

        self.btn_insert = QPushButton("Вставить в консоль")
        self.btn_insert.setIcon(icon("content_copy", 16, "@icon_fg"))
        self.btn_insert.clicked.connect(
            lambda: self.insertToConsoleRequested.emit(self.current_text())
        )
        buttons.addWidget(self.btn_insert)

        layout.addLayout(buttons)

    def script_name(self) -> str:
        return self._name

    def current_text(self) -> str:
        return self.editor.toPlainText()

    def is_dirty(self) -> bool:
        return self.editor.toPlainText() != self._original

    def set_running(self, running: bool) -> None:
        self.btn_run.setEnabled(not running)
