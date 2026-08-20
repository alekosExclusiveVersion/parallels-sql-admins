"""
gui/sql_console.py

Панель SQL Console: выбор сервера/БД, скоуп выполнения, редактор SQL,
кнопки Run/Stop и хоткеи.

Панель не знает о MySQL: она резолвит выполняемый оператор/выделение и
эмитит runRequested(sql). Фактическое выполнение остаётся в MainWindow.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QFontDatabase,
    QKeySequence,
    QPainter,
    QShortcut,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStyledItemDelegate,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from common.sql_completion import analyze as analyze_completion
from common.sql_splitter import statement_at
from gui.icons import engine_icon_color, icon
from gui.sql_completer import SqlCompleter
from gui.styles import qcolor
from gui.sql_highlighter import SQLHighlighter
from gui.widgets.help_icon import HelpIcon
from gui.widgets.searchable_combo import SearchableComboBox
from common.logger import logger


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

        self._completer = None
        self._completion_timer = QTimer(self)
        self._completion_timer.setSingleShot(True)
        self._completion_timer.setInterval(120)
        self._completion_timer.timeout.connect(self._run_completion)

        self.textChanged.connect(self._schedule_completion)
        self.cursorPositionChanged.connect(self._schedule_completion)

        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self._update_line_number_area_width()

    def set_completer(self, completer) -> None:
        """Устанавливает автодополнение и перехватывает Enter/Tab/Esc
        в попапе, чтобы QPlainTextEdit не съедал эти клавиши."""
        self._completer = completer
        if completer is not None:
            completer.activated.connect(self._insert_completion)
            completer.popup().installEventFilter(self)

    def _insert_completion(self, text: str) -> None:
        """Вставляет выбранную подсказку вместо вводимого префикса."""
        if self._completer is None:
            return

        body = self._completer.script_body_for(text)
        if body is not None:
            tc = self.textCursor()
            tc.movePosition(QTextCursor.End)
            current = self.toPlainText()
            if current and not current.endswith("\n"):
                tc.insertText("\n")
            tc.insertText("\n\n\n")
            tc.insertText(body)
            self.setTextCursor(tc)
            self._completer.hide_popup()
            return

        tc = self.textCursor()
        prefix = self._completer.completionPrefix()
        if prefix:
            tc.movePosition(
                QTextCursor.Left,
                QTextCursor.KeepAnchor,
                len(prefix),
            )
        tc.insertText(text)
        self.setTextCursor(tc)
        self._completer.hide_popup()

    def _accept_current_completion(self) -> bool:
        """Вставляет подсвеченную в попапе подсказку.

        Использует текущий индекс попапа (текущая строка QCompleter
        не меняется при навигации стрелками).
        """
        completer = self._completer
        if completer is None or not completer.popup().isVisible():
            return False

        index = completer.popup().currentIndex()
        if not index.isValid():
            return False

        model = completer.popup().model()
        if model is None:
            return False

        source_index = model.mapToSource(index)
        if not source_index.isValid():
            return False

        text = source_index.data()
        if not text:
            return False

        completer.activated.emit(str(text))
        return True

    def eventFilter(self, obj, event) -> bool:
        completer = self._completer

        if completer is None:
            return super().eventFilter(obj, event)

        popup = completer.popup()

        if obj is popup:
            if event.type() == QEvent.Hide:
                self._completion_timer.stop()
            if event.type() == QEvent.KeyPress:
                key = event.key()
                if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
                    self._accept_current_completion()
                    popup.hide()
                    return True
                if key == Qt.Key_Escape:
                    self._completion_timer.stop()
                    completer.hide_popup()
                    return True
                if key in (Qt.Key_Down, Qt.Key_Up):
                    return self._move_popup_cursor(key)

        return super().eventFilter(obj, event)

    def _move_popup_cursor(self, key: int) -> bool:
        """Перемещает подсветку попапа на одну строку (без обёртки).

        Штатный QCompleter съедает первый Down на первой строке и после
        последней уводит индекс в -1; здесь навигация предсказуема.
        """
        completer = self._completer
        if completer is None:
            return False

        popup = completer.popup()
        model = popup.model()
        rows = model.rowCount()
        if rows == 0:
            return True

        index = popup.currentIndex()
        row = index.row() if index.isValid() else (-1 if key == Qt.Key_Down else rows)
        if key == Qt.Key_Down:
            row = min(row + 1, rows - 1)
        else:
            row = max(row - 1, 0)
        popup.setCurrentIndex(model.index(row, 0))
        return True

    def keyPressEvent(self, event) -> None:
        completer = self._completer
        if completer is not None:
            # Cmd/Ctrl+Space — принудительно показать автодополнение.
            if (
                event.key() == Qt.Key_Space
                and event.modifiers() & Qt.ControlModifier
            ):
                context = analyze_completion(
                    self.toPlainText(), self.textCursor().position()
                )
                completer.show_suggestions(context, force=True)
                return

            # Пока попап открыт: Enter/Tab выбирают подсказку, Esc — закрыть.
            if completer.popup().isVisible():
                key = event.key()
                if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
                    self._accept_current_completion()
                    completer.popup().hide()
                    return
                if key == Qt.Key_Escape:
                    self._completion_timer.stop()
                    completer.hide_popup()
                    return

        super().keyPressEvent(event)

    def _schedule_completion(self) -> None:
        self._completion_timer.start()

    def _run_completion(self) -> None:
        if self._completer is None:
            return
        context = analyze_completion(
            self.toPlainText(), self.textCursor().position()
        )
        self._completer.show_suggestions(context)

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
    searchRequested = Signal(str)            # найти БД по маске
    searchStopRequested = Signal()
    catalogRequested = Signal(str, str)      # запросить каталог таблиц/колонок
    scopeEnabledChanged = Signal(bool)       # доступность скоупа (не busy)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._server_engines: dict[str, str] = {}
        self._working_db: bool = False
        self._build_ui()

    # ----------------------------------------------------------
    # UI
    # ----------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        # --- Тулбар: поиск БД, служебные действия ---
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self.ed_search_mask = QLineEdit()
        self.ed_search_mask.setObjectName("SearchField")
        self.ed_search_mask.setPlaceholderText("Маска БД или домен сайта…")
        self.ed_search_mask.setClearButtonEnabled(True)
        self.ed_search_mask.setFixedHeight(28)
        self.ed_search_mask.setMaximumWidth(280)
        self.ed_search_mask.addAction(
            icon("search", 14, "@icon_muted"), QLineEdit.LeadingPosition
        )
        toolbar.addWidget(self.ed_search_mask)

        toolbar.addWidget(
            HelpIcon(
                "Поиск БД по маске имени (% вводить не нужно — "
                "ищется как %текст%). Маска с точкой дополнительно "
                "ищется по домену/адресу сайта (через Plesk psa). "
                "Двойной клик по строке результата подставит сервер "
                "и БД в консоль."
            )
        )

        self.btn_search = QPushButton("Найти БД")
        self.btn_search.setObjectName("btn_primary")
        self.btn_search.setFixedHeight(28)
        self.btn_search.setToolTip("Найти БД по маске на серверах")
        toolbar.addWidget(self.btn_search)

        self.btn_search_stop = QToolButton()
        self.btn_search_stop.setObjectName("btn_icon_danger")
        self.btn_search_stop.setIcon(icon("stop", 16, "@icon_danger"))
        self.btn_search_stop.setIconSize(QSize(16, 16))
        self.btn_search_stop.setToolTip("Остановить поиск БД")
        self.btn_search_stop.setEnabled(False)
        toolbar.addWidget(self.btn_search_stop)

        toolbar.addStretch()

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

        toolbar.addWidget(self.btn_refresh_db)
        toolbar.addWidget(self.btn_clear)

        layout.addLayout(toolbar)

        scontrols = QHBoxLayout()

        self.cb_server = SearchableComboBox()
        self.cb_server.setObjectName("combo_select")
        self.cb_server.setMinimumWidth(180)
        self.cb_server.lineEdit().setPlaceholderText("Выберите сервер…")
        self.cb_server.view().setItemDelegate(
            ComboItemDelegate(self.cb_server.view())
        )

        self.cb_database = SearchableComboBox()
        self.cb_database.setObjectName("combo_select")
        self.cb_database._item_icon_name = "storage"
        self.cb_database.setMinimumWidth(160)
        self.cb_database.lineEdit().setPlaceholderText("Выберите БД…")
        self.cb_database.view().setItemDelegate(
            ComboItemDelegate(self.cb_database.view())
        )

        scontrols.addWidget(self.cb_server, 2)
        scontrols.addWidget(self.cb_database, 1)

        self.chk_write = QCheckBox("Разрешить запросы на запись")
        scontrols.addWidget(self.chk_write)

        layout.addLayout(scontrols)

        # Скоуп выполнения + кнопки Run/Stop в одном ряду
        run_row = QHBoxLayout()
        run_row.setSpacing(6)

        self.chk_all_servers = QCheckBox("Все выбранные серверы")
        self.chk_all_servers.setToolTip(
            "Выполнять на серверах, выбранных в списке"
        )
        self.chk_all_servers.setVisible(False)

        self.chk_all_databases = QCheckBox("Все базы данных")
        self.chk_all_databases.setToolTip(
            "Выполнять по всем базам данных каждого сервера"
        )
        self.chk_all_databases.setVisible(False)

        run_row.addWidget(self.chk_all_servers)
        run_row.addWidget(self.chk_all_databases)

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

        # Автодополнение: каталог (таблицы/колонки) подгружает MainWindow
        # по catalogRequested и отдаёт обратно через set_catalog().
        self._completer = SqlCompleter(self.editor)
        self.editor.set_completer(self._completer)

        self._catalog_timer = QTimer(self)
        self._catalog_timer.setSingleShot(True)
        self._catalog_timer.setInterval(350)
        self._catalog_timer.timeout.connect(self._catalog_request)

        # ----------------------------------------------------------
        # Сигналы
        # ----------------------------------------------------------

        self.btn_run.clicked.connect(self._run_all)
        self.btn_stop.clicked.connect(self.stopRequested)
        self.btn_refresh_db.clicked.connect(self.refreshDatabasesRequested)
        self.btn_clear.clicked.connect(self._clear)

        self.btn_search.clicked.connect(self._search_submit)
        self.btn_search_stop.clicked.connect(self.searchStopRequested)
        self.ed_search_mask.returnPressed.connect(self._search_submit)

        self.cb_server.currentIndexChanged.connect(self._on_server_index_changed)
        self.cb_server.currentIndexChanged.connect(self._completion_server_changed)
        self.cb_database.currentTextChanged.connect(self._catalog_schedule)
        self.chk_all_servers.toggled.connect(self.scopeChanged)
        self.chk_all_databases.toggled.connect(self.scopeChanged)
        self.chk_all_servers.toggled.connect(self._completion_scope_changed)
        self.chk_all_databases.toggled.connect(self._completion_scope_changed)

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
        self.scopeEnabledChanged.emit(not busy)

        self.cb_server.setEnabled(
            not busy and not self.chk_all_servers.isChecked()
        )
        self.cb_database.setEnabled(
            not busy and not self.chk_all_databases.isChecked()
        )

    def set_stop_enabled(self, enabled: bool) -> None:
        self.btn_stop.setEnabled(enabled)

    def set_scope_checkboxes_visible(self, visible: bool) -> None:
        """Показывает/скрывает чекбоксы скоупа в панели консоли."""
        self.chk_all_servers.setVisible(visible)
        self.chk_all_databases.setVisible(visible)

    def set_databases(self, names: list[str]) -> None:
        current = self.cb_database.currentText()

        engine = self._server_engines.get(self.current_host(), "")
        db_icon = icon("storage", 16, engine_icon_color(engine)) if engine else None

        self.cb_database.blockSignals(True)

        self.cb_database.clear()
        for name in names:
            self.cb_database.addItem(name)
            index = self.cb_database.count() - 1
            if engine:
                self.cb_database.setItemData(index, engine, Qt.UserRole + 1)
            if db_icon is not None:
                self.cb_database.setItemIcon(index, db_icon)

        # Восстанавливаем выбранную БД только если она есть на новом сервере,
        # иначе очищаем выбор, чтобы не оставалась несуществующая БД.
        if current and current in names:
            self.cb_database.setCurrentText(current)
        else:
            self.cb_database.setCurrentText("")

        self.cb_database.blockSignals(False)

        self.cb_database.refresh_completion()

        self._catalog_schedule()

    def mark_working_database(
        self, update_times: dict[str, str]
    ) -> None:
        """Подсвечивает БД, обновлённые сегодня, зелёной иконкой."""
        if not update_times:
            logger.debug("No update_times provided, skipping marker")
            return
        today = time.strftime("%Y-%m-%d")
        green = "#4caf50"
        working_icon = icon("storage", 16, green)
        marked = 0
        for i in range(self.cb_database.count()):
            name = self.cb_database.itemText(i)
            ts = update_times.get(name, "")
            if ts and ts.startswith(today):
                self.cb_database.setItemIcon(i, working_icon)
                marked += 1
        if marked:
            self._working_db = True
            logger.info(
                f"Working DB(s) marked in combo: {marked}"
            )

    # ----------------------------------------------------------
    # Автодополнение (каталог таблиц/колонок)
    # ----------------------------------------------------------

    def set_catalog(self, tables: list[str], columns: dict[str, list[str]]) -> None:
        """Обновляет подсказки таблиц/колонок (из MainWindow)."""
        self._completer.set_catalog(tables, columns)

    def set_scripts(self, scripts: list[dict]) -> None:
        """Обновляет подсказки скриптов (из MainWindow)."""
        self._completer.set_scripts(scripts)

    def clear_completion(self) -> None:
        """Сбрасывает каталог подсказок (смена сервера/скоупа)."""
        self._completer.clear_catalog()
        self._completer.hide_popup()
        self._catalog_timer.stop()

    def _catalog_schedule(self) -> None:
        if self.current_host() and self.current_database():
            self._catalog_timer.start()

    def _catalog_request(self) -> None:
        host = self.current_host()
        database = self.current_database()
        if host and database:
            self.catalogRequested.emit(host, database)

    def _on_server_index_changed(self, index: int) -> None:
        if index >= 0:
            self.serverChanged.emit(self.cb_server.currentText())

    def _completion_server_changed(self, _index: int = -1) -> None:
        self.clear_completion()
        self._catalog_schedule()

    def _completion_scope_changed(self, _checked: bool) -> None:
        # В мульти-скоупе (все серверы/БД) подсказки нерелевантны.
        if self.chk_all_servers.isChecked() or self.chk_all_databases.isChecked():
            self.clear_completion()

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
        (current_host()). Движок хранится отдельным ролью и задаёт
        фирменную иконку пункта (как в дереве серверов).
        """
        previous = self.current_host()

        self._server_engines.clear()
        self.cb_server.blockSignals(True)

        self.cb_server.clear()

        for entry in servers:
            if isinstance(entry, (tuple, list)):
                display, host = entry[0], entry[1]
                engine = entry[2] if len(entry) > 2 else ""
            else:
                display = host = entry
                engine = ""
            self.cb_server.addItem(display, host)
            if engine:
                self.cb_server.setItemData(
                    self.cb_server.count() - 1, engine, Qt.UserRole + 1
                )
                self.cb_server.setItemIcon(
                    self.cb_server.count() - 1,
                    icon("server", 16, engine_icon_color(engine)),
                )
            self._server_engines[host] = engine

        if previous:
            self._select_server_by_host(previous)
        else:
            # По умолчанию поле пустое: addItem сам выставляет первый пункт.
            self.cb_server.setCurrentIndex(-1)
            self.cb_server.setCurrentText("")

        self.cb_server.blockSignals(False)

        self.cb_server.refresh_completion()

    def clear_editor(self) -> None:
        self.editor.clear()

    def current_host(self) -> str:
        """Хост выбранного сервера (имя в списке, host — в данных пункта)."""
        index = self.cb_server.currentIndex()
        if index >= 0:
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
        """Перекрашивает редактор, подсветку и иконки при смене темы."""
        self.highlighter.retheme()
        self.editor.retheme()
        if self.ed_search_mask.actions():
            self.ed_search_mask.actions()[0].setIcon(
                icon("search", 14, "@icon_muted")
            )
        self.btn_search_stop.setIcon(icon("stop", 16, "@icon_danger"))
        self.btn_refresh_db.setIcon(icon("refresh"))
        self.btn_clear.setIcon(icon("delete_outline"))

    def search_mask(self) -> str:
        return self.ed_search_mask.text().strip()

    def set_search_busy(self, busy: bool) -> None:
        self.btn_search.setEnabled(not busy)
        self.btn_search_stop.setEnabled(busy)
        self.ed_search_mask.setEnabled(not busy)

    def _search_submit(self) -> None:
        self.searchRequested.emit(self.search_mask())

    def script_text(self) -> str:
        return self.editor.toPlainText()

    def insert_script(self, text: str) -> None:
        """Вставляет текст скрипта в конец редактора с отступом 3 строки."""
        text = text.strip()
        if not text:
            return
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        current = self.editor.toPlainText()
        if current:
            if not current.endswith("\n"):
                cursor.insertText("\n")
            cursor.insertText("\n\n\n")
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
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
