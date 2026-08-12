"""
gui/widgets/filter_header.py

Sibling-строка поколоночных фильтров для Results.

Overlay НЕ является дочерним виджетом таблицы: ResultTable размещает его
в общем QVBoxLayout-контейнере (overlay сверху, таблица снизу). Так поля
фильтров не перекрывают первую строку данных — QTableView игнорирует
setViewportMargins для строк (rowViewportPosition(0) остаётся 0), поэтому
вложенный overlay визуально прятал первую строку под полосой фильтров.

Поля выравниваются по секциям QHeaderView через mapTo в координаты overlay,
вертикальная прокрутка их не двигает, горизонтальная двигает вместе с
колонками. Жизненный цикл защищён shiboken6.isValid(): синхронизация после
уничтожения таблицы не вызывает RuntimeError (C++ object already deleted).
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
    """Sibling-строка поколоночных фильтров над таблицей."""

    filterChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._table: QTableWidget | None = None
        self._edits: list[QLineEdit] = []
        self._row_height = 24
        self.setFixedHeight(self._row_height)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "FilterHeaderRow { background: palette(base); }"
        )
        self.hide()

    def bind(self, table: QTableWidget) -> None:
        """Подключает overlay к таблице и геометрические сигналы."""
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
        table.verticalScrollBar().valueChanged.connect(
            self._schedule_sync
        )
        table.installEventFilter(self)
        table.viewport().installEventFilter(self)
        header.installEventFilter(self)

        # Резервируем место под фильтры между шапкой и данными. Overlay
        # остаётся дочерним таблицы, поэтому vertical scrollbar его не двигает.
        table.setViewportMargins(0, self._row_height, 0, 0)
        self._sync_geometry()

    def rebuild(self, columns: list[str]) -> None:
        """Создаёт по одному полю фильтра для каждой логической колонки."""
        for edit in self._edits:
            edit.deleteLater()
        self._edits = []

        if not columns:
            self.hide()
            self._sync_geometry()
            return

        for column in columns:
            edit = QLineEdit(self)
            edit.setFixedHeight(self._row_height)
            edit.setPlaceholderText("…")
            edit.setClearButtonEnabled(True)
            edit.setToolTip(f"Фильтр по колонке «{column}»")
            edit.setMinimumWidth(40)
            edit.textChanged.connect(self._on_text_changed)
            self._edits.append(edit)

        self.show()
        self.raise_()
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

    def _sync_geometry(self) -> None:
        """Привязывает поля к текущей геометрии секций QHeaderView."""
        table = self._table
        if table is None or not isValid(table):
            return

        header = table.horizontalHeader()
        header_viewport = header.viewport()
        if not isValid(header) or not isValid(header_viewport):
            return

        container = self.parentWidget()
        if container is None or not isValid(container):
            return

        # Общая ширина — как у viewport таблицы (без вертикального скроллбара),
        # поля не вылезают под скроллбар.
        self.setFixedWidth(table.viewport().width())

        # Overlay и таблица — sibling'и в общем контейнере.
        # Используем mapFrom для получения координат viewport в системе координат overlay.
        # table.viewport() — дочерний элемент table, который является sibling'ом overlay.
        my_origin = self.mapFrom(container, container.rect().topLeft())
        h_origin = table.viewport().mapTo(
            container, table.viewport().rect().topLeft()
        )
        x_base = h_origin.x() - my_origin.x()

        # Правый край viewport в координатах overlay — для скрытия полей,
        # вылезающих под вертикальный скроллбар.
        vp_right = (
            table.viewport().mapTo(container, table.viewport().rect().topRight()).x()
            - my_origin.x()
        )

        visible_left = x_base
        visible_right = vp_right
        for logical_index, edit in enumerate(self._edits):
            if logical_index >= header.count():
                edit.hide()
                continue

            x = x_base + header.sectionViewportPosition(logical_index)
            width = header.sectionSize(logical_index)
            edit.setGeometry(x, 0, width, self._row_height)
            edit.setVisible(
                width > 0 and x < visible_right and x + width > visible_left
            )

    def eventFilter(self, watched: QWidget, event: QEvent) -> bool:
        if event.type() in (QEvent.Resize, QEvent.LayoutRequest, QEvent.Move):
            table = self._table
            if table is not None and isValid(table):
                self._sync_geometry()
        return super().eventFilter(watched, event)
