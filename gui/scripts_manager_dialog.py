"""
gui/scripts_manager_dialog.py

Модальное окно управления библиотекой скриптов (открывается из меню
«Скрипты → Управление скриптами…»). Содержит полноценную библиотеку
без блока «Журнал запросов» — тот живёт во вкладке «Журнал».
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
)

from gui.scripts_library import ScriptsLibrary


class ScriptsManagerDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Управление скриптами")
        self.resize(900, 560)

        layout = QVBoxLayout(self)

        self.library = ScriptsLibrary(show_query_log=False)
        layout.addWidget(self.library, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()

        self.btn_close = QPushButton("Закрыть")
        self.btn_close.clicked.connect(self.accept)
        buttons.addWidget(self.btn_close)

        layout.addLayout(buttons)
