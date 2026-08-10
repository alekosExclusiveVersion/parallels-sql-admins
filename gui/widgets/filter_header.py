"""
gui/widgets/filter_header.py

Встроенная строка поколоночных фильтров для Results.

Поля являются дочерними элементами таблицы, располагаются непосредственно
под QHeaderView и используют координаты самого заголовка. Поэтому вертикальная
прокрутка строк их не двигает, а горизонтальная прокрутка перемещает каждое
поле вместе с соответствующей колонкой.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QLineEdit, QTableWidget, QWidget


class FilterHeaderRow(QWidget):
    """Overlay-строка фильтров, закреплённая под шапкой таблицы."""

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
        """Встраивает overlay в таблицу и подключает геометрические сигналы."""
        self._table = table
        self.setParent(table)
        self.raise_()

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
        if table is None:
            return

        header = table.horizontalHeader()
        header_viewport = header.viewport()
        header_origin = header_viewport.mapTo(table, header_viewport.rect().topLeft())
        row_origin = header_origin.y() + header_viewport.height()

        # Строка занимает ровно область шапки (до вертикального скроллбара).
        # Поля — её дети, Qt клипает их по границе строки, поэтому они не
        # могут вылезти под скроллбар даже при минимальной ширине поля
        # и при растянутой последней колонке.
        viewport_right = header_origin.x() + header_viewport.width()
        self.setGeometry(
            0,
            row_origin,
            viewport_right,
            self._row_height,
        )

        visible_left = header_origin.x()
        visible_right = viewport_right
        for logical_index, edit in enumerate(self._edits):
            if logical_index >= header.count():
                edit.hide()
                continue

            x = header_origin.x() + header.sectionViewportPosition(logical_index)
            width = header.sectionSize(logical_index)
            edit.setGeometry(x, 0, width, self._row_height)
            edit.setVisible(
                width > 0 and x < visible_right and x + width > visible_left
            )

        self.raise_()

    def eventFilter(self, watched: QWidget, event: QEvent) -> bool:
        if event.type() in (QEvent.Resize, QEvent.LayoutRequest, QEvent.Move):
            self._sync_geometry()
        return super().eventFilter(watched, event)
