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

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHeaderView,
    QLineEdit,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QCheckBox,
)

from gui.styles import ERROR_BG, STATUS_COLORS, color as theme_color
from gui.widgets.filter_header import FilterHeaderRow

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
        # контур в углах не прерывался.
        if rad >= 2:
            stroke_r = rad - 0.5
            cy = rad - 1.0
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(theme_color("border")), 1.0))
            p.drawArc(QRectF(rad - 1.0 - stroke_r, cy - stroke_r, 2 * stroke_r, 2 * stroke_r), 90 * 16, 90 * 16)
            p.drawArc(QRectF(r.width() - rad + 1.0 - stroke_r, cy - stroke_r, 2 * stroke_r, 2 * stroke_r), 0 * 16, 90 * 16)
        p.end()


class ResultTable(QTableWidget):
    dbSelected = Signal(str, str)        # server, database (двойной клик по строке)
    logMessage = Signal(str, str)        # level, message
    visibilityRequested = Signal(bool)   # авто-показ блока Results

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ResultTable")

        self._rounded_header = RoundedHeader(Qt.Horizontal)
        self.setHorizontalHeader(self._rounded_header)

        self.filter_header = FilterHeaderRow(self)

        self._search_edit: QLineEdit | None = None
        self._only_errors: QCheckBox | None = None
        self._results_source: str | None = None

        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(40)
        self._filter_timer.timeout.connect(self.apply_filters)

        self._configure()

        self.filter_header.bind(self)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_table_menu)
        self.itemDoubleClicked.connect(self._table_double_click)

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
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setCornerButtonEnabled(False)
        self.setFocusPolicy(Qt.StrongFocus)

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

    def add_search_result(self, server: str, database: str) -> None:
        if self.columnCount() == 0:
            self.setup_columns(["Server", "Database"], {0: 190, 1: 160})
        self.add_row([server, database])

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
            item = QTableWidgetItem(str(text))
            item.setToolTip(str(text))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)

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
                texts.append((item.text() if item else "").lower())
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

    def column_index(self, name: str) -> int | None:
        for column in range(self.columnCount()):
            item = self.horizontalHeaderItem(column)
            if item is not None and item.text() == name:
                return column
        return None

    # ----------------------------------------------------------
    # Контекстное меню
    # ----------------------------------------------------------

    def _show_table_menu(self, pos) -> None:
        row = self.currentRow()

        menu = QMenu(self)
        copy_row = menu.addAction("Копировать строку")
        copy_server = menu.addAction("Копировать сервер")
        copy_database = menu.addAction("Копировать БД")

        menu.addSeparator()

        export_csv = menu.addAction("Экспорт CSV...")

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
        elif action == clear_action:
            self.clear_results()

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
