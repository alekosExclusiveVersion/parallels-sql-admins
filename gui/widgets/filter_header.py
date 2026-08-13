"""
gui/widgets/filter_header.py

Строка поколоночных фильтров для Results, закреплённая под шапкой.

Поля фильтров — дочерние виджеты viewport горизонтальной шапки
(QHeaderView), а сама шапка увеличивается на высоту полосы фильтров.
QTableView игнорирует setViewportMargins для строк (rowViewportPosition(0)
остаётся 0), поэтому вложенный в viewport таблицы оверлей визуально прятал
первую строку данных — поля живут в шапке, а данные начинаются строго под ней,
и первая строка всегда видна целиком.

Подписи колонок принудительно якорим к верху секции (AlignTop): по умолчанию
QHeaderView центрирует текст (AlignCenter), и в увеличенной шапке он залез бы
на поля фильтров. Поля выравниваются по секциям через sectionViewportPosition
(учитывает горизонтальную прокрутку), вертикальная прокрутка на них не влияет.
Жизненный цикл защищён shiboken6.isValid(): синхронизация после уничтожения
таблицы не вызывает RuntimeError (C++ object already deleted).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QLineEdit, QTableWidget, QWidget

try:
    from shiboken6 import isValid
except ImportError:  # pragma: no cover
    def isValid(obj) -> bool:  # type: ignore
        return obj is not None


class FilterHeaderRow(QWidget):
    """Менеджер поколоночных фильтров, закреплённых под шапкой таблицы."""

    filterChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._table: QTableWidget | None = None
        self._edits: list[QLineEdit] = []
        self._row_height = 24
        self._label_h = 0
        self.hide()

    def bind(self, table: QTableWidget) -> None:
        """Подключает фильтры к таблице и геометрические сигналы."""
        if table is None:
            return
        self._table = table

        header = table.horizontalHeader()
        header.sectionResized.connect(self._schedule_sync)
        header.sectionMoved.connect(self._schedule_sync)
        header.geometriesChanged.connect(self._schedule_sync)
        table.horizontalScrollBar().valueChanged.connect(
            self._schedule_sync
        )
        table.installEventFilter(self)
        header.installEventFilter(self)

        self._sync_geometry()

    def rebuild(self, columns: list[str]) -> None:
        """Создаёт по одному полю фильтра для каждой логической колонки."""
        for edit in self._edits:
            edit.deleteLater()
        self._edits = []

        table = self._table
        if table is None or not isValid(table):
            return

        header = table.horizontalHeader()
        header_viewport = header.viewport()
        if not columns or not isValid(header_viewport):
            self._restore_header_height(header)
            self._sync_geometry()
            return

        for column in columns:
            edit = QLineEdit(header_viewport)
            edit.setObjectName("ColumnFilter")
            edit.setFixedHeight(self._row_height)
            edit.setPlaceholderText("…")
            edit.setClearButtonEnabled(True)
            edit.setToolTip(f"Фильтр по колонке «{column}»")
            edit.setMinimumWidth(40)
            edit.textChanged.connect(self._on_text_changed)
            edit.hide()
            self._edits.append(edit)

        self._sync_geometry()

    def get_filters(self) -> list[str]:
        """Возвращает фильтры в логическом порядке колонок."""
        return [edit.text().strip().lower() for edit in self._edits]

    def clear_filters(self) -> None:
        """Очищает все поколоночные фильтры."""
        for edit in self._edits:
            edit.blockSignals(True)
            edit.clear()
            edit.blockSignals(False)
        self._sync_geometry()

    def _on_text_changed(self) -> None:
        self.filterChanged.emit()

    def _schedule_sync(self, *args) -> None:
        self._sync_geometry()

    def _ensure_header_space(self, header) -> bool:
        """Увеличивает шапку на высоту фильтров после реальной раскладки."""
        if self._label_h:
            return True
        # Натуральная высота шапки доступна только после раскладки с секциями.
        if not header.count() or header.height() <= 0:
            return False
        self._label_h = header.height()
        # Подписи по умолчанию центрируются, а в увеличенной шапке текст
        # залез бы на фильтры — якорим текст к верху секции.
        header.setDefaultAlignment(Qt.AlignHCenter | Qt.AlignTop)
        header.setFixedHeight(self._label_h + self._row_height)
        return True

    def _restore_header_height(self, header) -> None:
        """Возвращает шапке натуральную высоту, если колонок больше нет."""
        if not self._label_h:
            return
        header.setFixedHeight(self._label_h)
        self._label_h = 0

    def _sync_geometry(self) -> None:
        """Привязывает поля к текущей геометрии секций QHeaderView."""
        table = self._table
        if table is None or not isValid(table):
            return

        header = table.horizontalHeader()
        header_viewport = header.viewport()
        if not isValid(header) or not isValid(header_viewport):
            return

        if not self._ensure_header_space(header):
            return

        visible_width = header_viewport.width()
        for logical_index, edit in enumerate(self._edits):
            if logical_index >= header.count():
                edit.hide()
                continue

            x = header.sectionViewportPosition(logical_index)
            width = header.sectionSize(logical_index)
            edit.setGeometry(x, self._label_h, width, self._row_height)
            edit.setVisible(
                width > 0 and x < visible_width and x + width > 0
            )

    def eventFilter(self, watched: QWidget, event: QEvent) -> bool:
        if event.type() in (QEvent.Resize, QEvent.LayoutRequest, QEvent.Move):
            table = self._table
            if table is not None and isValid(table):
                self._sync_geometry()
        return super().eventFilter(watched, event)
