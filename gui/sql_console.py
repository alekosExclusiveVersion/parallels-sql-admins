"""
gui/sql_console.py

Панель SQL Console: выбор сервера/БД, скоуп выполнения, редактор SQL,
кнопки Run/Stop и хоткеи.

Панель не знает о MySQL: она резолвит выполняемый оператор/выделение и
эмитит runRequested(sql). Фактическое выполнение остаётся в MainWindow.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QFontDatabase, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStyledItemDelegate,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from common.sql_splitter import statement_at
from gui.icons import icon
from gui.styles import qcolor
from gui.sql_highlighter import SQLHighlighter
from gui.widgets.help_icon import HelpIcon


class ComboItemDelegate(QStyledItemDelegate):
    """Отступы внутри пунктов выпадающего списка."""

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(
            size.width() + 24,
            max(size.height() + 12, 34),
        )


class LineNumberArea(QWidget):
    """Полоса с номерами строк слева от редактора SQL."""

    def __init__(self, editor: "SqlEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.line_number_area_paint_event(event)


class SqlEditor(QPlainTextEdit):
    """Редактор SQL с нумерацией строк и подсветкой текущей строки."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._line_number_area = LineNumberArea(self)

        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self._update_line_number_area_width()

    def line_number_area_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_number_area_width(self) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy) -> None:
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(
                0, rect.y(), self._line_number_area.width(), rect.height(),
            )

        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()),
        )

    def retheme(self) -> None:
        """Перекрашивает полосу номеров строк при смене темы."""
        self.viewport().update()
        self._line_number_area.update()

    def line_number_area_paint_event(self, event) -> None:
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), qcolor("editor_gutter_bg"))
        painter.setPen(qcolor("editor_gutter_border"))
        x = self._line_number_area.width() - 1
        painter.drawLine(x, event.rect().top(), x, event.rect().bottom())

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        offset = self.contentOffset()
        top = round(self.blockBoundingGeometry(block).translated(offset).top())
        bottom = top + round(self.blockBoundingRect(block).height())

        current = self.textCursor().blockNumber()
        width = self._line_number_area.width() - 8

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                if block_number == current:
                    painter.setPen(qcolor("editor_current_line"))
                    font = painter.font()
                    font.setBold(True)
                    painter.setFont(font)
                else:
                    painter.setPen(qcolor("editor_line_number"))
                painter.drawText(
                    0, top, width, self.fontMetrics().height(),
                    Qt.AlignRight, number,
                )

            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1


class SqlConsolePanel(QWidget):
    runRequested = Signal(str)               # выполнить переданный SQL
    stopRequested = Signal()
    refreshDatabasesRequested = Signal()
    clearRequested = Signal()
    serverChanged = Signal(str)
    scopeChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ----------------------------------------------------------
    # UI
    # ----------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        sctop = QHBoxLayout()

        self.lbl_title = QLabel("SQL Консоль")
        self.lbl_title.setObjectName("SectionTitle")
        sctop.addWidget(self.lbl_title)

        sctop.addStretch()

        self.btn_refresh_db = QToolButton()
        self.btn_refresh_db.setObjectName("btn_icon")
        self.btn_refresh_db.setIcon(icon("refresh"))
        self.btn_refresh_db.setIconSize(QSize(16, 16))
        self.btn_refresh_db.setToolTip("Обновить список БД")

        self.btn_clear = QToolButton()
        self.btn_clear.setObjectName("btn_icon")
        self.btn_clear.setIcon(icon("delete_outline"))
        self.btn_clear.setIconSize(QSize(16, 16))
        self.btn_clear.setToolTip("Очистить консоль")

        sctop.addWidget(self.btn_refresh_db)
        sctop.addWidget(self.btn_clear)

        layout.addLayout(sctop)

        scontrols = QHBoxLayout()

        self.cb_server = QComboBox()
        self.cb_server.setEditable(True)
        self.cb_server.setMinimumWidth(180)
        self.cb_server.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.cb_server.lineEdit().setStyleSheet(
            "border:none;background:transparent;padding:0;"
        )
        self.cb_server.view().setItemDelegate(
            ComboItemDelegate(self.cb_server.view())
        )

        self.cb_database = QComboBox()
        self.cb_database.setEditable(True)
        self.cb_database.setMinimumWidth(160)
        self.cb_database.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.cb_database.lineEdit().setStyleSheet(
            "border:none;background:transparent;padding:0;"
        )
        self.cb_database.view().setItemDelegate(
            ComboItemDelegate(self.cb_database.view())
        )

        scontrols.addWidget(self.cb_server)
        scontrols.addWidget(self.cb_database)

        self.chk_write = QCheckBox("Разрешить запросы на запись")
        scontrols.addWidget(self.chk_write)

        scontrols.addStretch()

        layout.addLayout(scontrols)

        scope_row = QHBoxLayout()

        self.chk_all_servers = QCheckBox("Все выбранные серверы")
        self.chk_all_servers.setToolTip(
            "Выполнять на серверах, выбранных в списке"
        )

        self.chk_all_databases = QCheckBox("Все базы данных")
        self.chk_all_databases.setToolTip(
            "Выполнять по всем базам данных каждого сервера"
        )

        scope_row.addWidget(self.chk_all_servers)
        scope_row.addWidget(self.chk_all_databases)

        scope_row.addStretch()

        layout.addLayout(scope_row)

        # Ряд кнопок Run/Stop непосредственно над полем ввода SQL
        run_row = QHBoxLayout()
        run_row.addStretch()

        self.btn_run = QPushButton("Выполнить")
        self.btn_run.setObjectName("btn_primary")
        self.btn_run.setToolTip(
            "Выполнить скрипт (Cmd/Ctrl+Shift+Enter); "
            "выполнить выделение или оператор под курсором (Cmd/Ctrl+Enter)"
        )

        run_row.addWidget(self.btn_run)

        self.btn_stop = QPushButton("Остановить")
        self.btn_stop.setObjectName("btn_danger")
        self.btn_stop.setToolTip("Остановить выполняемый запрос")
        self.btn_stop.setEnabled(False)

        run_row.addWidget(self.btn_stop)

        run_row.addWidget(
            HelpIcon(
                "Cmd/Ctrl+Enter — выполнить выделение или оператор "
                "под курсором; Cmd/Ctrl+Shift+Enter — выполнить всё."
            )
        )

        layout.addLayout(run_row)

        self.editor = SqlEditor()
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setPlaceholderText("Введите SQL-запрос…")
        self.editor.setTabStopDistance(40)

        console_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        console_font.setPointSize(12)
        self.editor.setFont(console_font)

        layout.addWidget(self.editor)

        self.highlighter = SQLHighlighter(self.editor.document())

        # ----------------------------------------------------------
        # Сигналы
        # ----------------------------------------------------------

        self.btn_run.clicked.connect(self._run_all)
        self.btn_stop.clicked.connect(self.stopRequested)
        self.btn_refresh_db.clicked.connect(self.refreshDatabasesRequested)
        self.btn_clear.clicked.connect(self._clear)

        self.cb_server.currentTextChanged.connect(self.serverChanged)
        self.chk_all_servers.toggled.connect(self.scopeChanged)
        self.chk_all_databases.toggled.connect(self.scopeChanged)

        # Cmd/Ctrl+Enter — выделение или оператор под курсором
        self.run_shortcut = QShortcut(
            QKeySequence(Qt.CTRL | Qt.Key_Return),
            self,
        )
        self.run_shortcut.activated.connect(self._run_context)

        # Cmd/Ctrl+Shift+Enter — выполнить весь скрипт
        self.run_all_shortcut = QShortcut(
            QKeySequence(Qt.CTRL | Qt.SHIFT | Qt.Key_Return),
            self,
        )
        self.run_all_shortcut.activated.connect(self._run_all)

    # ----------------------------------------------------------
    # API для MainWindow
    # ----------------------------------------------------------

    def set_busy(self, busy: bool) -> None:
        self.btn_run.setEnabled(not busy)
        self.btn_refresh_db.setEnabled(not busy)
        self.btn_stop.setEnabled(busy)
        self.chk_all_servers.setEnabled(not busy)
        self.chk_all_databases.setEnabled(not busy)

        self.cb_server.setEnabled(
            not busy and not self.chk_all_servers.isChecked()
        )
        self.cb_database.setEnabled(
            not busy and not self.chk_all_databases.isChecked()
        )

    def set_stop_enabled(self, enabled: bool) -> None:
        self.btn_stop.setEnabled(enabled)

    def set_databases(self, names: list[str]) -> None:
        current = self.cb_database.currentText()

        self.cb_database.blockSignals(True)

        self.cb_database.clear()
        self.cb_database.addItems(names)

        # Восстанавливаем выбранную БД только если она есть на новом сервере,
        # иначе очищаем выбор, чтобы не оставалась несуществующая БД.
        if current and current in names:
            self.cb_database.setCurrentText(current)
        else:
            self.cb_database.setCurrentText("")

        self.cb_database.blockSignals(False)

    def set_target(self, server: str, database: str) -> None:
        self._select_server_by_host(server)
        self.cb_database.setCurrentText(database)

    def _select_server_by_host(self, server: str) -> None:
        """Выбирает сервер по хосту: в списке хранится имя (Name),
        а host — в данных пункта."""
        for index in range(self.cb_server.count()):
            if self.cb_server.itemData(index) == server:
                self.cb_server.setCurrentIndex(index)
                return
        # Сервера нет в списке — подставляем хост как текст
        self.cb_server.setCurrentText(server)

    def set_servers(
        self, servers: list[str] | list[tuple]
    ) -> None:
        """Заполняет выпадающий список серверов.

        Элемент — строка-хост либо кортеж (display_name, host) или
        (display_name, host, engine): отображается Name, host хранится
        в данных пункта и используется как цель подключения
        (current_host()). Движок не используется — комбо без иконок.
        """
        previous = self.current_host()

        self.cb_server.blockSignals(True)

        self.cb_server.clear()

        for entry in servers:
            if isinstance(entry, (tuple, list)):
                display, host = entry[0], entry[1]
            else:
                display = host = entry
            self.cb_server.addItem(display, host)

        if previous:
            self._select_server_by_host(previous)

        self.cb_server.blockSignals(False)

    def clear_editor(self) -> None:
        self.editor.clear()

    def current_host(self) -> str:
        """Хост выбранного сервера (имя в списке, host — в данных пункта).

        Если пользователь ввёл произвольный текст (не совпадает с пунктом
        списка) — возвращает его как есть.
        """
        index = self.cb_server.currentIndex()
        if index >= 0:
            text = self.cb_server.currentText()
            if text != self.cb_server.itemText(index):
                return text.strip()
            host = self.cb_server.itemData(index)
            if host:
                return str(host)
        return self.cb_server.currentText().strip()

    def current_database(self) -> str:
        return self.cb_database.currentText().strip()

    def write_enabled(self) -> bool:
        return self.chk_write.isChecked()

    def all_servers_checked(self) -> bool:
        return self.chk_all_servers.isChecked()

    def all_databases_checked(self) -> bool:
        return self.chk_all_databases.isChecked()

    def retheme(self) -> None:
        """Перекрашивает редактор и подсветку при смене темы."""
        self.highlighter.retheme()
        self.editor.retheme()

    def script_text(self) -> str:
        return self.editor.toPlainText()

    def insert_script(self, text: str) -> None:
        """Заменяет содержимое редактора текстом скрипта."""
        self.editor.setPlainText(text)
        self.editor.setFocus()

    # ----------------------------------------------------------
    # Запуск
    # ----------------------------------------------------------

    def _run_all(self) -> None:
        self.runRequested.emit(self.editor.toPlainText())

    def _run_context(self) -> None:
        """Выделенный фрагмент, иначе оператор под курсором."""
        editor = self.editor
        text = editor.toPlainText()
        cursor = editor.textCursor()

        if cursor.hasSelection():
            sql = cursor.selectedText()
            # selectedText() возвращает символы U+2029 вместо переносов строк
            sql = sql.replace("\u2029", "\n").strip()
        else:
            sql = statement_at(text, cursor.position()).strip()

        if sql:
            self.runRequested.emit(sql)

    def _clear(self) -> None:
        self.editor.clear()
        self.clearRequested.emit()
