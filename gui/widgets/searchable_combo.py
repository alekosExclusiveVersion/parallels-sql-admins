"""
gui/widgets/searchable_combo.py

Editable QComboBox с поиском по любому вхождению (substring, без учёта
регистра). Используется для выбора сервера и БД в SQL-консоли.

Поиск ведётся по видимому названию пункта и по его скрытым данным
(userData, например host сервера): ввод «p5g» найдёт сервер с таким
хостом, даже если его Name другой. Доменный суффикс хоста (.ru и т.п.)
в поиске не участвует — иначе ввод «ru» совпадал бы с каждым
хостом *.tradesoft.ru.

Попап подсказок построен по образцу gui/sql_completer.py
(UnfilteredPopupCompletion) — Qt не фильтрует повторно, список уже
отфильтрован моделью при каждом вводе.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox, QCompleter


def _without_tld(text: str) -> str:
    """Текст без доменного суффикса (TLD: .ru, .com и т.п.).

    TLD отрезается, чтобы ввод «ru» не совпадал с суффиксом каждого
    хоста *.tradesoft.ru (даже когда имя пункта — это полный хост).
    IP-адреса и имена без точки возвращаются целиком (последняя метка
    «5» в 10.0.0.5 — не буквенный TLD).
    """
    text = str(text)
    labels = text.split(".")
    if len(labels) > 1:
        tld = labels[-1]
        if tld.isalpha() and len(tld) >= 2:
            return ".".join(labels[:-1])
    return text


def contains_match(needle: str, display: str, host: str) -> bool:
    """Подстрока needle встречается в display или host (без TLD).

    Пустой/пробельный запрос совпадает со всем.
    """
    query = needle.strip().lower()
    if not query:
        return True
    return query in _without_tld(display).lower() or (bool(host) and query in _without_tld(host).lower())


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
        self._completer.refresh(self._combo_items(), text)
        if not text or not self.isVisible():
            self._completer.popup().hide()
            return
        exact = any(text == self.itemText(i) for i in range(self.count()))
        if exact:
            QTimer.singleShot(0, self._hide_if_exact)
            return
        self._completer.complete()

    def _hide_if_exact(self) -> None:
        """Прячет попап, если текст по-прежнему равен пункту списка.

        Отложенный вызов: собственное completion-обновление editable-комбо
        (Qt) успевает перепоказать попап сразу после ввода, поэтому hide
        выполняем после обработки события, перепроверив состояние.
        """
        text = self.currentText()
        if any(text == self.itemText(i) for i in range(self.count())):
            self._completer.popup().hide()

    def refresh_completion(self) -> None:
        """Пересобирает модель подсказок под текущий текст.

        Нужно вызывать после пересборки списка пунктов комбо
        (например, при обновлении списка серверов/БД), чтобы открытый
        попап не показывал устаревший набор.
        """
        self._completer.refresh(self._combo_items(), self.currentText())

    def _on_activated(self, text: str) -> None:
        for i in range(self.count()):
            if self.itemText(i) == text:
                self.setCurrentIndex(i)
                return
        self.setCurrentText(text)
