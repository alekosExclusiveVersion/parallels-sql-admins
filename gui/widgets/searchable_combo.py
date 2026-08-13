"""
gui/widgets/searchable_combo.py

Editable QComboBox с поиском по любому вхождению (substring, без учёта
регистра). Используется для выбора сервера и БД в SQL-консоли.

Поиск ведётся по видимому названию пункта и по его скрытым данным
(userData, например host сервера): ввод «p5g» найдёт сервер с таким
хостом, даже если его Name другой.

Попап подсказок построен по образцу gui/sql_completer.py
(UnfilteredPopupCompletion) — Qt не фильтрует повторно, список уже
отфильтрован моделью при каждом вводе.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox, QCompleter


def contains_match(needle: str, display: str, host: str) -> bool:
    """Подстрока needle встречается в display или host (без учёта регистра).

    Пустой/пробельный запрос совпадает со всем.
    """
    query = needle.strip().lower()
    if not query:
        return True
    return query in display.lower() or (bool(host) and query in str(host).lower())


class SearchComboCompleter(QCompleter):
    """Попап-фильтр для SearchableComboBox.

    Модель пересобирается на каждый ввод из переданных пунктов
    (display, host), отбираются только совпадающие по любому вхождению.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self.setCaseSensitivity(Qt.CaseInsensitive)
        self.setMaxVisibleItems(12)

        popup = self.popup()
        popup.setObjectName("CompletionPopup")
        popup.setStyleSheet("")
        popup.setUniformItemSizes(True)

    def refresh(self, items: list[tuple[str, str]], query: str) -> None:
        """Перестраивает список подсказок под запрос (substring по Name/host)."""
        self._model.clear()
        for display, host in items:
            if contains_match(query, display, host):
                item = QStandardItem(display)
                item.setData(host, Qt.UserRole)
                self._model.appendRow(item)


class SearchableComboBox(QComboBox):
    """Editable-комбо с поиском по любому вхождению.

    Пункты добавляются как обычно (addItem/addItems), host — через
    userData. Список подсказок синхронизируется с комбо при каждом
    изменении текста, поэтому переопределять addItem/clear не нужно.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)

        self._completer = SearchComboCompleter(self)
        self.setCompleter(self._completer)
        self._completer.activated.connect(self._on_activated)
        self.lineEdit().textChanged.connect(self._on_text_changed)

    # ----------------------------------------------------------
    # Внутреннее
    # ----------------------------------------------------------

    def _combo_items(self) -> list[tuple[str, str]]:
        return [
            (self.itemText(i), str(self.itemData(i) or ""))
            for i in range(self.count())
        ]

    def _on_text_changed(self, text: str) -> None:
        index = self.currentIndex()
        if index >= 0 and text == self.itemText(index):
            return

        self._completer.refresh(self._combo_items(), text)
        if text and self.isVisible():
            exact = any(text == self.itemText(i) for i in range(self.count()))
            if not exact:
                self._completer.complete()

    def _on_activated(self, text: str) -> None:
        for i in range(self.count()):
            if self.itemText(i) == text:
                self.setCurrentIndex(i)
                return
        self.setCurrentText(text)
