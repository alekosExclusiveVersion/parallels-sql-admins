"""
gui/result_table.py

Таблица Results: вставка строк с подсветкой статуса, поколоночные и сквозной
фильтры, контекстное меню и экспорт в CSV.

Вынесена из MainWindow, чтобы разгрузить монолитный класс: виджет сам
управляет QHeaderView, FilterHeaderRow, полем поиска и чекбоксом
«Только ошибки» (которые подключаются через attach_filters()).
"""

from __future__ import annotations

import csv

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QMenu,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QCheckBox,
)

from gui.styles import ERROR_BG, STATUS_COLORS, color as theme_color
from gui.widgets.filter_header import FilterHeaderRow
from common.logger import logger

CHECK_HEADERS = [
    "Source",
    "Server",
    "Database",
    "Country",
    "Value",
    "Status",
    "Message",
]

CHECK_HEADER_WIDTHS = {
     0: 64,
     1: 190,
     2: 160,
     4: 180,
}

# Роль: индекс строки в исходном результате (не меняется при сортировке).
SOURCE_ROW_ROLE = Qt.UserRole + 200


class CellEditDelegate(QStyledItemDelegate):
    """Разрешает редактирование только редактируемым колонкам данных.

    Возврат None из createEditor запрещает начать редактирование
    (служебные колонки 0-2 и колонки, не совпадающие с реальными
    колонками таблицы). setModelData не пишет в модель: вместо этого
    испускается editRequested — значение попадает в ячейку только
    после подтверждения и успешного UPDATE в главном окне.
    """

    def __init__(self, table: "ResultTable") -> None:
        super().__init__(table)
        self._table = table

    def createEditor(self, parent, option, index):
        if not self._table.can_edit_cell(index.row(), index.column()):
            return None
        return super().createEditor(parent, option, index)

    def setModelData(self, editor, model, index):
        table = self._table
        if not table.can_edit_cell(index.row(), index.column()):
            return

        text = editor.text() if hasattr(editor, "text") else ""
        new_text = text.strip() if text else ""
        item = table.item(index.row(), index.column())
        old_text = item.text() if item is not None else ""

        if new_text == old_text:
            return

        table.editRequested.emit(
            index.row(), index.column(), new_text, old_text
        )

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)

        # Подсветка активной (текущей) редактируемой ячейки: пользователь
        # должен видеть, к какой ячейке применятся ±1/редактирование.
        table = self._table
        if table._editable_columns is None:
            return
        if (index.row(), index.column()) != (
            table.currentRow(),
            table.currentColumn(),
        ):
            return
        if not table.can_edit_cell(index.row(), index.column()):
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(theme_color("accent")))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(option.rect.adjusted(1, 1, -1, -1))
        painter.restore()


class RoundedHeader(QHeaderView):
    """Горизонтальная шапка Results со скруглёнными верхними углами.

    QSS border-radius не срезает фон QHeaderView, а ::section:last не матчится
    для растянутой последней секции (stretchLastSection). Вместо этого поверх
    верхних углов viewport рисуется антиалиасинговый «клин» в цвет фона таблицы:
    серые углы шапки плавно срезаются, без ступенчатых артефактов маски.
    """

    radius = 8

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        vp = self.viewport()
        if vp is None:
            return
        bg = self.parentWidget().palette().window().color()
        r = vp.rect()
        rad = min(self.radius, r.width() // 2, r.height() // 2)
        p = QPainter(vp)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        c = 0.5522847498 * rad
        path = QPainterPath()
        path.moveTo(0, 0)
        path.lineTo(0, rad)
        path.cubicTo(0, rad - c, rad - c, 0, rad, 0)
        path.closeSubpath()
        path.moveTo(r.width(), 0)
        path.lineTo(r.width() - rad, 0)
        path.cubicTo(r.width() - rad + c, 0, r.width(), rad - c, r.width(), rad)
        path.lineTo(r.width(), 0)
        path.closeSubpath()
        p.drawPath(path)
        # Клин закрывает белым и внутреннюю часть дуги QSS-контура таблицы
        # (дуга описана вокруг угла таблицы, а клин — вокруг угла viewport,
        # он на 1px внутри). Дорисовываем дугу границы поверх клина, чтобы
        # контур в углах не прерывался. Цвет дуги повторяет цвет рамки
        # таблицы: при фокусе — accent, иначе border (иначе при фокусе
        # акцентная рамка «разрывается» в углу серой дугой).
        if rad >= 2:
            stroke_r = rad - 0.5
            cy = rad - 1.0
            table = self.parentWidget()
            focused = bool(table is not None and table.hasFocus())
            stroke = QColor(
                theme_color("accent") if focused else theme_color("border")
            )
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(stroke, 1.0))
            p.drawArc(QRectF(rad - 1.0 - stroke_r, cy - stroke_r, 2 * stroke_r, 2 * stroke_r), 90 * 16, 90 * 16)
            p.drawArc(QRectF(r.width() - rad + 1.0 - stroke_r, cy - stroke_r, 2 * stroke_r, 2 * stroke_r), 0 * 16, 90 * 16)
        p.end()

    def refresh(self) -> None:
        """Перерисовывает скруглённые углы (смена фокуса таблицы)."""
        self.viewport().update()


class ResultTable(QTableWidget):
    dbSelected = Signal(str, str)        # server, database (двойной клик по строке)
    logMessage = Signal(str, str)        # level, message
    visibilityRequested = Signal(bool)   # авто-показ блока Results

    # Редактирование ячеек: запрос на изменение значения / ±1.
    # editRequested(row, col, new_text, old_text)
    editRequested = Signal(int, int, str, str)
    stepRequested = Signal(int)            # delta (+1 / -1)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ResultTable")

        self._rounded_header = RoundedHeader(Qt.Horizontal)
        self.setHorizontalHeader(self._rounded_header)

        self.filter_header = FilterHeaderRow(self)

        self._search_edit: QLineEdit | None = None
        self._only_errors: QCheckBox | None = None
        self._results_source: str | None = None

        # Множество редактируемых колонок данных (>= 3); None — редактирование
        # выключено (check/search результаты, мульти-скоуп, несложный SELECT).
        self._editable_columns: set[int] | None = None

        # Фильтры «пустые/не пустые» по колонкам (контекстное меню шапки).
        self._empty_filter_columns: set[int] = set()
        self._nonempty_filter_columns: set[int] = set()

        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(40)
        self._filter_timer.timeout.connect(self.apply_filters)

        self._configure()

        self.setItemDelegate(CellEditDelegate(self))

        self.filter_header.bind(self)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_table_menu)
        self.itemDoubleClicked.connect(self._table_double_click)

        header = self.horizontalHeader()
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_menu)

    # ----------------------------------------------------------
    # Настройка
    # ----------------------------------------------------------

    def _configure(self) -> None:
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(28)
        self.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)

        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)

        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        # Кастомная шапка (RoundedHeader), установленная через
        # setHorizontalHeader(), не наследует кликабельность и индикатор
        # сортировки — Qt применяет их только к штатной шапке.
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setCornerButtonEnabled(False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self._rounded_header.refresh()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self._rounded_header.refresh()

    def attach_filters(
        self,
        search_edit: QLineEdit,
        only_errors: QCheckBox,
    ) -> None:
        """Подключает внешнее поле сквозного поиска и чекбокс «Только ошибки»."""
        self._search_edit = search_edit
        self._only_errors = only_errors

        search_edit.textChanged.connect(self._on_filter_changed)
        only_errors.toggled.connect(self._on_filter_changed)
        self.filter_header.filterChanged.connect(self._on_filter_changed)

        self._update_only_errors_visibility()

    # ----------------------------------------------------------
    # Состояние результата
    # ----------------------------------------------------------

    @property
    def results_source(self) -> str | None:
        return self._results_source

    @results_source.setter
    def results_source(self, value: str | None) -> None:
        self._results_source = value
        self._update_only_errors_visibility()

    def _update_only_errors_visibility(self) -> None:
        if self._only_errors is None:
            return
        visible = self._results_source == "check"
        self._only_errors.setVisible(visible)
        if not visible and self._only_errors.isChecked():
            self._only_errors.setChecked(False)

    # ----------------------------------------------------------
    # Наполнение
    # ----------------------------------------------------------

    def reset_table(self) -> None:
        """Полная очистка перед новым результатом (колонки пересоздаются)."""
        self.clear()
        self.setColumnCount(0)
        self.setRowCount(0)
        self.setSortingEnabled(False)
        self.results_source = None
        self.set_editing_context(None)
        self._clear_column_filters()

    def _fit_header_widths(self, fixed_widths: dict[int, int]) -> None:
        """Растягивает колонки так, чтобы имена заголовков влезали целиком."""
        header = self.horizontalHeader()
        fm = self.fontMetrics()
        for column in range(self.columnCount()):
            item = self.horizontalHeaderItem(column)
            if item is None:
                continue
            base = fixed_widths.get(column, 0)
            text_width = fm.horizontalAdvance(item.text())
            header.resizeSection(column, max(base, text_width + 26))

    def clear_results(self) -> None:
        """Очистка под формат Check (фиксированные 7 колонок)."""
        self.setSortingEnabled(False)
        self.setColumnCount(len(CHECK_HEADERS))
        self.setHorizontalHeaderLabels(CHECK_HEADERS)

        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)

        for index, width in CHECK_HEADER_WIDTHS.items():
            header.resizeSection(index, width)

        self._fit_header_widths(CHECK_HEADER_WIDTHS)

        self.results_source = None
        self.set_editing_context(None)

        self.sync_filter_columns()
        self.apply_filters()
        self._update_only_errors_visibility()

    def add_result(
        self,
        server,
        database,
        country,
        value,
        status="OK",
        message="",
    ) -> None:
        self.add_row(
            ["Check", server, database, country, value, status, message],
            status_col=5,
        )

    def add_search_result(
        self, server: str, database: str, last_update: str = ""
    ) -> None:
        if self.columnCount() == 0:
            self.setup_columns(
                ["Server", "Database", "Последнее обновление", "Статус"],
                {0: 190, 1: 160, 2: 160, 3: 100},
            )
        self.add_row([server, database, last_update, ""])

    def mark_working_databases(self):
        """Помечает статус БД на основе времени обновления.

        - Сегодня → «● Рабочая»
        - Есть дата, но не сегодня → показывает дату
        - update_time=NULL, но есть данные → «Есть данные» + «● Активная»
        - Нет данных → «—»
        """
        import time as _time
        today = _time.strftime("%Y-%m-%d")
        marked = 0
        active = 0
        for row in range(self.rowCount()):
            ts_item = self.item(row, 2)
            status_item = self.item(row, 3)
            if not status_item:
                continue
            ts = ts_item.text() if ts_item else ""
            if not ts:
                status_item.setText("—")
            elif ts == "__HAS_DATA__":
                if ts_item:
                    ts_item.setText("Есть данные")
                status_item.setText("● Активная")
                active += 1
            elif ts.startswith(today):
                status_item.setText("● Рабочая")
                marked += 1
            else:
                status_item.setText(ts[:10])
        if marked or active:
            logger.info(
                f"Status: {marked} working, "
                f"{active} active (no timestamp)"
            )

    def fill_sql_result(
        self,
        host: str,
        database: str,
        rows: list,
        columns: list,
        message: str,
    ) -> None:
        if self.columnCount() == 0:
            labels = (
                ["Source", "Server", "Database"] + list(columns)
                if columns
                else ["Source", "Server", "Database", "Result"]
            )
            self.setup_columns(labels, {0: 64, 1: 190, 2: 160})

        if not columns:
            rows = [[message]]

        for row in rows:
            display = ["SQL", host, database] + list(row)
            self.add_row(display[: self.columnCount()])

    def setup_columns(self, labels: list[str], fixed_widths: dict[int, int]) -> None:
        self.setColumnCount(len(labels))
        self.setHorizontalHeaderLabels(labels)

        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)

        for index, width in fixed_widths.items():
            if index < len(labels):
                header.resizeSection(index, width)

        self._fit_header_widths(fixed_widths)

        self.sync_filter_columns()

    def add_row(self, values: list, status_col: int | None = None) -> None:
        self.visibilityRequested.emit(True)

        table = self
        row = table.rowCount()
        table.insertRow(row)

        col_count = table.columnCount()

        # Выравнивание количества значений
        padded = list(values)
        if len(padded) > col_count:
            padded = padded[:col_count]
        else:
            padded += [""] * (col_count - len(padded))

        for col, text in enumerate(padded):
            display = "Null" if text is None else str(text)
            item = QTableWidgetItem(display)
            item.setToolTip(display)
            item.setData(SOURCE_ROW_ROLE, row)

            flags = item.flags() & ~Qt.ItemIsEditable
            if col >= 3:
                flags |= Qt.ItemIsEditable
            item.setFlags(flags)

            if status_col is not None and col == status_col:
                fg = STATUS_COLORS.get(text)
                if fg:
                    item.setForeground(QBrush(fg))

            table.setItem(row, col, item)

        # Подсветка фона для строк с ошибкой
        if status_col is not None and padded[status_col] == "ERROR":
            for col in range(col_count):
                if (widget_item := table.item(row, col)):
                    widget_item.setBackground(ERROR_BG)

        self._filter_timer.start()
        self.visibilityRequested.emit(True)

    # ----------------------------------------------------------
    # Редактирование ячеек
    # ----------------------------------------------------------

    def set_editing_context(self, editable_columns: set[int] | None) -> None:
        """Включает/выключает редактирование ячеек результата.

        editable_columns — множество индексов колонок данных (>= 3),
        разрешённых к редактированию, или None, если редактирование
        недоступно (check/search результаты, мульти-скоуп, сложный SQL).
        """
        self._editable_columns = editable_columns

        if editable_columns:
            self.setEditTriggers(
                QAbstractItemView.DoubleClicked
                | QAbstractItemView.EditKeyPressed
                | QAbstractItemView.AnyKeyPressed
            )
        else:
            self.setEditTriggers(QAbstractItemView.NoEditTriggers)

        self.viewport().update()

    def editing_active(self) -> bool:
        """Доступно ли редактирование ячеек текущего результата."""
        return self._editable_columns is not None

    def can_edit_cell(self, row: int, col: int) -> bool:
        if self._editable_columns is None:
            return False
        if col not in self._editable_columns:
            return False
        return self.item(row, col) is not None

    def original_row(self, row: int) -> int:
        """Индекс строки в исходном результате (без сортировки/фильтров)."""
        item = self.item(row, 0)
        if item is not None:
            value = item.data(SOURCE_ROW_ROLE)
            if value is not None:
                return int(value)
        return row

    def keyPressEvent(self, event) -> None:
        if (
            self._editable_columns is not None
            and event.modifiers() == Qt.AltModifier
            and event.key() in (Qt.Key_Up, Qt.Key_Down)
        ):
            row = self.currentRow()
            col = self.currentColumn()
            if self.can_edit_cell(row, col):
                delta = 1 if event.key() == Qt.Key_Down else -1
                self.stepRequested.emit(delta)
                return
        super().keyPressEvent(event)

    # ----------------------------------------------------------
    # Фильтры
    # ----------------------------------------------------------

    def _on_filter_changed(self) -> None:
        """Debounce: перезапускает таймер, чтобы не перерисовывать
        таблицу на каждый нажатый символ."""
        self._filter_timer.start()

    def apply_filters(self) -> None:
        """Применяет сквозной, поколоночные и «Только ошибки» фильтры.

        Общий поиск и поколоночный поиск связаны через AND; несколько
        заполненных полей колонок объединяются через OR.
        """
        search = (self._search_edit.text().strip().lower()
                  if self._search_edit is not None else "")
        only_errors = self._only_errors.isChecked() if self._only_errors is not None else False

        status_index = self.column_index("Status")

        column_filters = self.filter_header.get_filters()

        table = self
        sorting = table.isSortingEnabled()

        table.setSortingEnabled(False)
        table.setUpdatesEnabled(False)

        def _row_texts(row):
            texts = []
            for column in range(table.columnCount()):
                item = table.item(row, column)
                texts.append((item.text().strip() if item else "").lower())
            return texts

        def _matches_global(row_texts):
            if not search:
                return False
            return any(search in text for text in row_texts)

        def _matches_columns(row_texts):
            for column, col_filter in enumerate(column_filters):
                if col_filter and column < len(row_texts):
                    if col_filter in row_texts[column]:
                        return True
            return False

        def _matches_empty_nonempty(row_texts):
            """Фильтры «пустые/не пустые» из меню шапки (AND по колонкам)."""
            for column in self._empty_filter_columns:
                if column >= len(row_texts):
                    continue
                if row_texts[column] != "":
                    return False
            for column in self._nonempty_filter_columns:
                if column >= len(row_texts):
                    continue
                if row_texts[column] == "":
                    return False
            return True

        try:
            for row in range(table.rowCount()):
                row_texts = _row_texts(row)

                has_global_filter = bool(search)
                has_column_filters = any(column_filters)

                visible = (
                    (not has_global_filter or _matches_global(row_texts))
                    and (
                        not has_column_filters
                        or _matches_columns(row_texts)
                    )
                    and _matches_empty_nonempty(row_texts)
                )

                if visible and only_errors and status_index is not None:
                    item = table.item(row, status_index)
                    status_text = item.text() if item else ""
                    visible = status_text == "ERROR"

                table.setRowHidden(row, not visible)
        finally:
            table.setUpdatesEnabled(True)
            table.setSortingEnabled(sorting)

        table.viewport().update()

    def sync_filter_columns(self) -> None:
        """Пересоздаёт поколоночные фильтры по текущим заголовкам."""
        headers = [
            self.horizontalHeaderItem(column).text()
            for column in range(self.columnCount())
            if self.horizontalHeaderItem(column) is not None
        ]
        self.filter_header.rebuild(headers)
        # Колонки пересозданы — фильтры «пустые/не пустые» сбрасываем.
        self._empty_filter_columns.clear()
        self._nonempty_filter_columns.clear()

    def column_index(self, name: str) -> int | None:
        for column in range(self.columnCount()):
            item = self.horizontalHeaderItem(column)
            if item is not None and item.text() == name:
                return column
        return None

    # ----------------------------------------------------------
    # Контекстное меню
    # ----------------------------------------------------------

    def _show_header_menu(self, pos) -> None:
        """Контекстное меню шапки: сортировка и фильтр «пустые/не пустые»."""
        header = self.horizontalHeader()
        column = header.logicalIndexAt(pos)
        if column < 0 or column >= self.columnCount():
            return

        title = f"Колонка {column + 1}"
        header_item = self.horizontalHeaderItem(column)
        if header_item is not None and header_item.text():
            title = header_item.text()

        menu = QMenu(self)
        menu.setTitle(title)
        sort_asc = menu.addAction("Сортировать по возрастанию")
        sort_desc = menu.addAction("Сортировать по убыванию")

        menu.addSeparator()

        filter_empty = menu.addAction("Показать только пустые значения")
        filter_empty.setCheckable(True)
        filter_empty.setChecked(column in self._empty_filter_columns)

        filter_nonempty = menu.addAction("Показать только не пустые значения")
        filter_nonempty.setCheckable(True)
        filter_nonempty.setChecked(column in self._nonempty_filter_columns)

        clear_column = menu.addAction("Снять фильтр колонки")
        clear_column.setEnabled(self._column_has_any_filter(column))

        action = menu.exec(header.mapToGlobal(pos))

        if action == sort_asc:
            self.sortByColumn(column, Qt.AscendingOrder)
        elif action == sort_desc:
            self.sortByColumn(column, Qt.DescendingOrder)
        elif action == filter_empty:
            self._toggle_empty_filter(column, filter_empty.isChecked())
        elif action == filter_nonempty:
            self._toggle_nonempty_filter(column, filter_nonempty.isChecked())
        elif action == clear_column:
            self._clear_column_filter(column)

    def _column_has_any_filter(self, column: int) -> bool:
        filters = self.filter_header.get_filters()
        return (
            column in self._empty_filter_columns
            or column in self._nonempty_filter_columns
            or (column < len(filters) and bool(filters[column]))
        )

    def _toggle_empty_filter(self, column: int, enabled: bool) -> None:
        if enabled:
            self._empty_filter_columns.add(column)
            self._nonempty_filter_columns.discard(column)
        else:
            self._empty_filter_columns.discard(column)
        self._refresh_column_marker(column)
        self.apply_filters()

    def _toggle_nonempty_filter(self, column: int, enabled: bool) -> None:
        if enabled:
            self._nonempty_filter_columns.add(column)
            self._empty_filter_columns.discard(column)
        else:
            self._nonempty_filter_columns.discard(column)
        self._refresh_column_marker(column)
        self.apply_filters()

    def _clear_column_filter(self, column: int) -> None:
        """Снимает с колонки фильтр «пустые/не пустые» и contains-фильтр."""
        self._empty_filter_columns.discard(column)
        self._nonempty_filter_columns.discard(column)
        self.filter_header.clear_column(column)
        self._refresh_column_marker(column)
        self.apply_filters()

    def _clear_column_filters(self) -> None:
        self._empty_filter_columns.clear()
        self._nonempty_filter_columns.clear()
        self.filter_header.clear_filters()

    def _refresh_column_marker(self, column: int) -> None:
        if column in self._empty_filter_columns:
            state = "empty"
        elif column in self._nonempty_filter_columns:
            state = "nonempty"
        else:
            state = None
        self.filter_header.set_column_state(column, state)

    def _show_table_menu(self, pos) -> None:
        row = self.currentRow()

        menu = QMenu(self)
        copy_row = menu.addAction("Копировать строку")
        copy_server = menu.addAction("Копировать сервер")
        copy_database = menu.addAction("Копировать БД")

        menu.addSeparator()

        export_csv = menu.addAction("Экспорт CSV...")

        menu.addSeparator()

        editing_actions = None
        if (
            self._editable_columns is not None
            and row >= 0
            and self.can_edit_cell(row, self.currentColumn())
        ):
            menu.addSeparator()
            inc_action = menu.addAction("Увеличить на 1")
            dec_action = menu.addAction("Уменьшить на 1")
            edit_action = menu.addAction("Изменить значение…")
            editing_actions = (inc_action, dec_action, edit_action)

        menu.addSeparator()

        clear_action = menu.addAction("Очистить результаты")

        action = menu.exec(self.viewport().mapToGlobal(pos))

        if row < 0:
            return

        if action == copy_row:
            self._copy_row(row)
        elif action == copy_server:
            self._copy_cell(row, "Server")
        elif action == copy_database:
            self._copy_cell(row, "Database")
        elif action == export_csv:
            self.export_csv()
        elif editing_actions is not None:
            inc_action, dec_action, edit_action = editing_actions
            if action == inc_action:
                self.stepRequested.emit(1)
            elif action == dec_action:
                self.stepRequested.emit(-1)
            elif action == edit_action:
                self._ask_edit_value(row, self.currentColumn())
        elif action == clear_action:
            self.clear_results()

    def _ask_edit_value(self, row: int, col: int) -> None:
        if not self.can_edit_cell(row, col):
            return
        item = self.item(row, col)
        old_text = item.text() if item is not None else ""
        new_text, ok = QInputDialog.getText(
            self,
            "Изменить значение",
            "Новое значение:",
            text=old_text,
        )
        if ok and new_text.strip() != old_text:
            self.editRequested.emit(row, col, new_text.strip(), old_text)

    def _copy_row(self, row: int) -> None:
        values = []
        for column in range(self.columnCount()):
            item = self.item(row, column)
            values.append(item.text() if item else "")

        QApplication.clipboard().setText("\t".join(values))

        self.logMessage.emit("SUCCESS", "Row copied to clipboard.")

    def _copy_cell(self, row: int, column_name: str) -> None:
        index = self.column_index(column_name)
        if index is None:
            return
        item = self.item(row, index)
        QApplication.clipboard().setText(item.text() if item else "")

    def _table_double_click(self, item: QTableWidgetItem) -> None:
        if item.column() >= 3:
            # Двойной клик по ячейке данных — редактирование, а не переход.
            return

        server_index = self.column_index("Server")
        database_index = self.column_index("Database")

        if server_index is None or database_index is None:
            return

        row = item.row()

        server_item = self.item(row, server_index)
        database_item = self.item(row, database_index)

        if not server_item or not database_item:
            return

        server = server_item.text().strip()
        database = database_item.text().strip()

        if not server or not database:
            return

        self.dbSelected.emit(server, database)

    # ----------------------------------------------------------
    # Экспорт
    # ----------------------------------------------------------

    def export_csv(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export CSV",
            "results.csv",
            "CSV files (*.csv);;All files (*)",
        )

        if not filename:
            return

        with open(
            filename,
            "w",
            newline="",
            encoding="utf-8-sig",
        ) as f:
            writer = csv.writer(f)
            headers = []

            for column in range(self.columnCount()):
                item = self.horizontalHeaderItem(column)
                headers.append(item.text() if item else "")

            writer.writerow(headers)

            for row in range(self.rowCount()):
                if self.isRowHidden(row):
                    continue

                values = []
                for column in range(self.columnCount()):
                    item = self.item(row, column)
                    values.append(item.text() if item else "")

                writer.writerow(values)

        self.logMessage.emit("SUCCESS", f"Results exported to {filename}")
