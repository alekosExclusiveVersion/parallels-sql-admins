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

Навигация стрелками и выбор Enter/Escape обрабатываются через
eventFilter на попапе — на macOS попап (Qt::Popup) забирает фокус
клавиатуры, и Down/Up идут напрямую в попап, а не в lineEdit.
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
        self._navigating = False
        self._completer = SearchComboCompleter(self)
        self.setCompleter(self._completer)
        self._completer.activated.connect(self._on_activated)
        self._completer.popup().clicked.connect(self._on_popup_clicked)
        self.lineEdit().textChanged.connect(self._on_text_changed)
        self.lineEdit().installEventFilter(self)
        # eventFilter на попапе: перехват Enter/Escape/DOWN/UP
        # на macOS попап (Qt::Popup) забирает фокус — клавиши идут сюда.
        self._completer.popup().installEventFilter(self)

    # ----------------------------------------------------------
    # Внутреннее
    # ----------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        popup = self._completer.popup()

        # --- события попапа (фокус на попапе на macOS) ---
        if obj is popup and event.type() == QEvent.KeyPress:
            key = event.key()
            # Enter/Return: подтверждение выбора
            if key in (Qt.Key_Return, Qt.Key_Enter):
                idx = popup.currentIndex()
                if idx.isValid():
                    text = idx.data(Qt.DisplayRole)
                    if text:
                        self._on_activated(str(text))
                popup.hide()
                return True
            # Escape: закрыть попап
            if key == Qt.Key_Escape:
                popup.hide()
                return True
            # Down/Up: передаём нативной обработке попапа
            # (QAbstractItemView::keyPressEvent). Не потребляем событие.
            # Ставим флаг _navigating, чтобы _on_text_changed не обновлял
            # модель (highlighted → setEditText → textChanged иначе вызовет
            # refresh(), который уничтожит модель посреди навигации).
            if key in (Qt.Key_Down, Qt.Key_Up):
                self._navigating = True
                QTimer.singleShot(0, self._clear_navigating)
                return False

        # --- события lineEdit ---
        if obj is self.lineEdit():
            # Клик по полю: открываем попап целиком
            if (
                event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton
            ):
                self._show_popup_on_click()
                return super().eventFilter(obj, event)
            # Down когда попап ещё не видим: открываем попап
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Down:
                if not popup.isVisible() and self.count():
                    self._completer.refresh(
                        self._combo_items(), self.currentText(),
                        self._item_icon_name,
                    )
                    self._completer.complete()
                    return True

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
        # Когда попап видим и идёт навигация стрелкой, изменение текста
        # вызвано highlighted → setEditText. refresh() очищает модель
        # попапа и ломает навигацию. Пропускаем.
        # При обычном воде текста (попап видим, навигации нет) —
        # обновляем модель, чтобы отфильтровать список.
        if self._completer.popup().isVisible() and self._navigating:
            return
        self._completer.refresh(self._combo_items(), text, self._item_icon_name)
        if not text or not self.isVisible():
            self._completer.popup().hide()
            return
        if self._completer.popup().isVisible():
            return
        exact = any(text == self.itemText(i) for i in range(self.count()))
        if exact:
            return
        self._completer.complete()

    def refresh_completion(self) -> None:
        """Пересобирает модель подсказок под текущий текст.

        Нужно вызывать после пересборки списка пунктов комбо
        (например, при обновлении списка серверов/БД), чтобы открытый
        попап не показывал устаревший набор.
        """
        self._completer.refresh(self._combo_items(), self.currentText(), self._item_icon_name)

    def _clear_navigating(self) -> None:
        self._navigating = False

    def _on_activated(self, text: str) -> None:
        for i in range(self.count()):
            if self.itemText(i) == text:
                self.setCurrentIndex(i)
                self._completer.popup().hide()
                return
        self.setCurrentText(text)
        self._completer.popup().hide()

    def _on_popup_clicked(self, index) -> None:
        text = index.data(Qt.DisplayRole)
        if text:
            self._on_activated(str(text))
