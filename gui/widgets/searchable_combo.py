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

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox, QCompleter

from gui.icons import engine_icon_color, icon


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
    (display, host[, engine]), отбираются только совпадающие по любому
    вхождению. Для пунктов с движком ставится фирменная иконка.
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

    def refresh(self, items: list[tuple], query: str, icon_name: str = "server") -> None:
        """Перестраивает список подсказок под запрос (substring по Name/host).

        Элементы — пары (display, host) либо тройки (display, host, engine):
        для движка пункту ставится фирменная иконка icon_name в цвете движка.
        """
        self._model.clear()
        for entry in items:
            display, host = entry[0], entry[1]
            engine = entry[2] if len(entry) > 2 else ""
            if contains_match(query, display, host):
                item = QStandardItem(display)
                item.setData(host, Qt.UserRole)
                if engine:
                    item.setIcon(icon(icon_name, 16, engine_icon_color(engine)))
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

        self._item_icon_name = "server"
        self._popup_manual = False
        self._completer = SearchComboCompleter(self)
        self.setCompleter(self._completer)
        self._completer.activated.connect(self._on_activated)
        self._completer.popup().clicked.connect(self._on_popup_clicked)
        self.lineEdit().textChanged.connect(self._on_text_changed)
        # Клик по полю открывает выпадающий список целиком (даже когда
        # значение уже выбрано); ввод текста продолжает фильтровать.
        self.lineEdit().installEventFilter(self)

    # ----------------------------------------------------------
    # Внутреннее
    # ----------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:
        if (
            obj is self.lineEdit()
            and event.type() == QEvent.MouseButtonPress
            and event.button() == Qt.LeftButton
        ):
            self._show_popup_on_click()
        return super().eventFilter(obj, event)

    def _show_popup_on_click(self) -> None:
        """Показывает весь список пунктов при клике на поле.

        Сброс фильтра нужен, чтобы при уже выбранном значении клик
        показывал полный список для выбора, а не единственный пункт,
        совпадающий с текущим текстом.

        complete() вызывается через QTimer, чтобы popup не закрылся
        внутренним eventFilter QCompleter при обработке MousePress.
        """
        if self.count():
            self._popup_manual = True
            self._completer.refresh(self._combo_items(), "", self._item_icon_name)
            QTimer.singleShot(0, self._completer.complete)

    def _combo_items(self) -> list[tuple]:
        return [
            (
                self.itemText(i),
                str(self.itemData(i) or ""),
                str(self.itemData(i, Qt.UserRole + 1) or ""),
            )
            for i in range(self.count())
        ]

    def _on_text_changed(self, text: str) -> None:
        if self._popup_manual:
            self._popup_manual = False
            return
        self._completer.refresh(self._combo_items(), text, self._item_icon_name)
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
        self._completer.refresh(self._combo_items(), self.currentText(), self._item_icon_name)

    def _on_activated(self, text: str) -> None:
        for i in range(self.count()):
            if self.itemText(i) == text:
                self.setCurrentIndex(i)
                return
        self.setCurrentText(text)

    def _on_popup_clicked(self, index) -> None:
        text = index.data(Qt.DisplayRole)
        if text:
            self._on_activated(text)
