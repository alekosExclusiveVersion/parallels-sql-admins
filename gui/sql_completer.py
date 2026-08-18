"""
gui/sql_completer.py

Попап автодополнения SQL: QCompleter с иконками для ключевых слов,
таблиц, колонок и сохранённых скриптов. Список подсказок формируется
заранее функцией suggest() из common/sql_completion.py (по контексту
под курсором), поэтому используется режим UnfilteredPopupCompletion —
Qt не фильтрует повторно.

Каталог (таблицы + колонки текущей БД) подгружается фоново и
передаётся через set_catalog(). Скрипты передаются через set_scripts().
Попап стилизуется под тему через QSS
(см. QListView#CompletionPopup в gui/styles.py).
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QCompleter

from common.sql_completion import (
    KIND_COLUMN,
    KIND_KEYWORD,
    KIND_SCRIPT,
    KIND_TABLE,
    suggest,
)
from gui.icons import icon

_ICON_BY_KIND = {
    KIND_KEYWORD: lambda: icon("edit", 14, "@icon_muted"),
    KIND_TABLE: lambda: icon("table", 14, "@icon_accent"),
    KIND_COLUMN: lambda: icon("grid_on", 14, "@icon_secondary"),
    KIND_SCRIPT: lambda: icon("content_copy", 14, "@icon_accent"),
}

_SCRIPT_BODY_ROLE = Qt.UserRole + 1


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
        self._scripts: list[dict] = []

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

    def set_scripts(self, scripts: list[dict]) -> None:
        """Обновляет список скриптов для автодополнения."""
        self._scripts = list(scripts or [])

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

        items = suggest(
            context,
            tables=self._tables,
            columns=self._columns,
            scripts=self._scripts,
        )

        self._model.clear()
        for text, kind in items:
            item = QStandardItem(text)
            item.setEditable(False)
            item.setIcon(_ICON_BY_KIND.get(kind, _ICON_BY_KIND[KIND_KEYWORD])())
            if kind == KIND_SCRIPT:
                script_name = text[2:]  # strip "📜 "
                for s in self._scripts:
                    if s.get("name") == script_name:
                        item.setData(s.get("body", ""), _SCRIPT_BODY_ROLE)
                        break
            self._model.appendRow(item)

        if not items:
            self._clear_and_hide()
            return

        self.setCompletionPrefix(prefix)

        cursor = self.widget().textCursor()
        rect = self.widget().cursorRect(cursor)
        rect.setWidth(320)
        self.complete(rect)

    def script_body_for(self, display_text: str) -> str | None:
        """Возвращает тело скрипта по отображаемому тексту (📜 Name)."""
        for s in self._scripts:
            if f"\U0001f4dc {s.get('name')}" == display_text:
                return s.get("body", "")
        return None

    def _clear_and_hide(self) -> None:
        self._model.clear()
        if self.popup().isVisible():
            self.popup().hide()

    def hide_popup(self) -> None:
        if self.popup().isVisible():
            self.popup().hide()
