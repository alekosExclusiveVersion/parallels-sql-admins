"""
gui/sql_completer.py

Попап автодополнения SQL: QCompleter с иконками для ключевых слов,
таблиц и колонок. Список подсказок формируется заранее функцией
suggest() из common/sql_completion.py (по контексту под курсором),
поэтому используется режим UnfilteredPopupCompletion — Qt не
фильтрует повторно.

Каталог (таблицы + колонки текущей БД) подгружается фоново и
передаётся через set_catalog(). Попап стилизуется под тему через QSS
(см. QListView#CompletionPopup в gui/styles.py).
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QCompleter

from common.sql_completion import (
    KIND_COLUMN,
    KIND_KEYWORD,
    KIND_TABLE,
    suggest,
)
from gui.icons import icon

_ICON_BY_KIND = {
    KIND_KEYWORD: lambda: icon("edit", 14, "@icon_muted"),
    KIND_TABLE: lambda: icon("table", 14, "@icon_accent"),
    KIND_COLUMN: lambda: icon("grid_on", 14, "@icon_secondary"),
}


class SqlCompleter(QCompleter):
    """Автодополнение SQL поверх редактора QPlainTextEdit."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self.setCaseSensitivity(Qt.CaseInsensitive)
        self.setMaxVisibleItems(12)
        self.setWidget(parent)

        popup = self.popup()
        popup.setObjectName("CompletionPopup")
        popup.setStyleSheet("")
        popup.setUniformItemSizes(True)

        self._tables: list[str] = []
        self._columns: dict[str, list[str]] = {}

    # ----------------------------------------------------------
    # Данные
    # ----------------------------------------------------------

    def set_catalog(self, tables: list[str], columns: dict[str, list[str]]) -> None:
        """Обновляет каталог таблиц/колонок текущей БД."""
        self._tables = list(tables or [])
        self._columns = columns or {}

    def clear_catalog(self) -> None:
        self._tables = []
        self._columns = {}
        self._clear_and_hide()

    # ----------------------------------------------------------
    # Показ
    # ----------------------------------------------------------

    def show_suggestions(self, context, force: bool = False) -> None:
        """Показывает подсказки для контекста под курсором."""
        prefix = context.prefix

        if not force and not prefix:
            self._clear_and_hide()
            return

        min_len = 1 if context.has_dot else 2
        if not force and len(prefix) < min_len:
            self._clear_and_hide()
            return

        items = suggest(context, tables=self._tables, columns=self._columns)

        self._model.clear()
        for text, kind in items:
            item = QStandardItem(text)
            item.setEditable(False)
            item.setIcon(_ICON_BY_KIND.get(kind, _ICON_BY_KIND[KIND_KEYWORD])())
            self._model.appendRow(item)

        if not items:
            self._clear_and_hide()
            return

        self.setCompletionPrefix(prefix)

        cursor = self.widget().textCursor()
        rect = self.widget().cursorRect(cursor)
        rect.setWidth(320)
        self.complete(rect)

    def _clear_and_hide(self) -> None:
        self._model.clear()
        if self.popup().isVisible():
            self.popup().hide()

    def hide_popup(self) -> None:
        if self.popup().isVisible():
            self.popup().hide()
