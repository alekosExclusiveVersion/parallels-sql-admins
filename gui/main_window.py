from __future__ import annotations

import threading
import time
from datetime import datetime

from PySide6.QtCore import QEvent, Qt, QSize, QTimer
from PySide6.QtGui import QAction, QActionGroup, QTextCursor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QFrame,
    QFileDialog,
    QToolButton,
    QProgressBar,
    QLineEdit,
    QCheckBox,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QMenu,
    QApplication,
    QTabBar,
)

from backend.repository import Repository
from backend.check_worker import CheckWorker
from backend.completion_worker import CompletionWorker
from backend.query_worker import ALL_DATABASES, QueryWorker
from backend.db_search_worker import DatabaseSearchWorker
from backend.db_sizes_worker import DbSizesWorker
from common.sql_builder import sql_builder
from common.sql_security import is_write_statement
from common.sql_splitter import split_statements
from common.logger import logger
from common.version import APP_VERSION
from common.mysql_client import mysql
from common.server_registry import (
    ENGINE_MYSQL,
    ServerSpec,
    build_select_sql,
    registry,
)
from gui.icons import icon, set_icon_theme
from gui import styles as theme_styles
from gui.widgets.collapsible_splitter import CollapsibleSplitter
from gui.widgets.help_icon import HelpIcon
from gui.worker_thread import WorkerHost
from gui.servers_tree import ServersTree
from gui.result_table import ResultTable
from gui.sql_console import SqlConsolePanel
from gui.scripts_library import ScriptStore
from gui.script_tab import ScriptTab
from gui.scripts_manager_dialog import ScriptsManagerDialog
from gui.server_dialog import ServerDialog


class MainWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.repository = Repository()

        self._last_sql_request = None   # (targets, sql) последнего запроса SQL Console

        theme_styles.bootstrap()
        set_icon_theme(theme_styles.theme_colors())

        self._build_ui()
        self._create_backend()
        self._create_query_backend()
        self._create_export_backend()
        self._create_search_backend()
        self._create_sizes_backend()
        self._create_completion_backend()

        # Гарантия остановки потоков на ЛЮБОМ пути выхода: если процесс
        # завершается через QApplication.quit() (без закрытия окна, как в
        # debug-скриптах), closeEvent не вызывается и живые QThread падают
        # в _Py_Finalize (SIGABRT) — поэтому shutdown() привязываем и к
        # aboutToQuit (см. _on_about_to_quit).
        self._shutdown_done = False
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._on_about_to_quit)

        theme_styles.register_theme_listener(self._on_theme_applied)

        self._theme_timer = QTimer(self)
        self._theme_timer.setInterval(5000)
        self._theme_timer.timeout.connect(theme_styles.maybe_system_change)
        self._theme_timer.start()

        self._on_theme_applied()

        self._load_servers()

    # ----------------------------------------------------------
    # Backend
    # ----------------------------------------------------------

    def _create_backend(self):

        self.host = WorkerHost(CheckWorker, self)
        self.thread = self.host.thread
        self.worker = self.host.worker

        self.worker.started.connect(
            self._check_started
        )

        self.worker.finished.connect(
            self._check_finished
        )

        self.worker.progress.connect(
            self._update_progress
        )

        self.worker.status.connect(
            lambda text: self.append_log(
                "INFO",
                text,
            )
        )

        self.worker.result.connect(
            self.table.add_result
        )

        self.worker.query.connect(
            self._append_query
        )

    def _create_query_backend(self):

        self.query_host = WorkerHost(QueryWorker, self)
        self.query_thread = self.query_host.thread
        self.query_worker = self.query_host.worker

        self.query_worker.query.connect(
            self._append_query
        )

        self.query_worker.result.connect(
            self._show_query_result
        )

        self.query_worker.error.connect(
            self._sql_error
        )

        self.query_worker.databases.connect(
            self._show_databases
        )

        self.query_worker.started_target.connect(
            self._sql_target_started
        )

        self.query_worker.result_target.connect(
            self._sql_target_result
        )

        self.query_worker.error_target.connect(
            self._sql_target_error
        )

        self.query_worker.stopped.connect(
            self._sql_target_stopped
        )

        self.query_worker.finished.connect(
            self._sql_finished
        )

    def _create_export_backend(self):

        self.export_host = WorkerHost(QueryWorker, self)
        self.export_thread = self.export_host.thread
        self.export_worker = self.export_host.worker

        self.export_worker.export_done.connect(
            self._export_done
        )

        self.export_worker.error.connect(
            self._export_error
        )

        self.export_worker.error_target.connect(
            self._export_target_error
        )

        self.export_worker.stopped.connect(
            self._export_stopped
        )

        self.export_worker.finished.connect(
            self._export_finished
        )

    def _create_search_backend(self):

        self.search_host = WorkerHost(DatabaseSearchWorker, self)
        self.search_thread = self.search_host.thread
        self.search_worker = self.search_host.worker

        self.search_worker.started.connect(
            self._search_started
        )

        self.search_worker.finished.connect(
            self._search_finished
        )

        self.search_worker.progress.connect(
            self._search_progress
        )

        self.search_worker.status.connect(
            lambda text: self.append_log(
                "INFO",
                text,
            )
        )

        self.search_worker.result.connect(
            self._search_result
        )

        self.search_worker.error.connect(
            self._search_error
        )

    def _create_sizes_backend(self):

        self.sizes_host = WorkerHost(DbSizesWorker, self)
        self.sizes_thread = self.sizes_host.thread
        self.sizes_worker = self.sizes_host.worker

        self.sizes_worker.databases_names.connect(
            self.servers_tree.apply_databases
        )

        self.sizes_worker.databases.connect(
            self.servers_tree.apply_sizes
        )

        self.sizes_worker.server_tables.connect(
            self.servers_tree.apply_server_tables
        )

        self.sizes_worker.tables.connect(
            self.servers_tree.apply_tables
        )

        self.sizes_worker.error.connect(
            self._sizes_error
        )

    def _create_completion_backend(self):

        self.completion_host = WorkerHost(CompletionWorker, self)
        self.completion_thread = self.completion_host.thread
        self.completion_worker = self.completion_host.worker

        self.completion_worker.catalog_ready.connect(
            self._completion_catalog_ready
        )

        self.completion_worker.error.connect(
            self._completion_catalog_error
        )

        # Кэш каталога автодополнения по (host, database) с TTL.
        self._completion_cache: dict[tuple[str, str], tuple[list, dict, float]] = {}
        self._completion_pending = False
        self._completion_request = None

        self.servers_tree.databasesRequested.connect(
            self.sizes_worker.request_databases
        )

        self.servers_tree.tablesRequested.connect(
            self.sizes_worker.request_tables
        )

        # Постоянный поток-потребитель: стартует один раз,
        # задачи на загрузку размеров кладутся в очередь.
        self.sizes_thread.start()

    def _update_progress(self, current, total):

        if total == 0:
            self.progress.setValue(0)
            return

        percent = int(current * 100 / total)

        self.progress.setValue(percent)

    # ----------------------------------------------------------
    # Repository
    # ----------------------------------------------------------

    def _load_servers(self):

        servers = self.repository.load_servers()

        hosts = [spec.host for spec in servers]

        # В списках показываем Name (host скрыт), host остаётся
        # целью подключения для check/search/консоли; engine (mysql/mssql)
        # нужен дереву для фирменной иконки сервера.
        labels = [
            (spec.ui_label(), spec.host, spec.engine)
            for spec in servers
        ]

        self.servers_tree.set_servers(labels)

        self.panel.set_servers(labels)

        if self.panel.current_host().strip():
            self._sql_refresh_databases()

        count = len(hosts)

        self.lbl_servers_value.setText(
            f"{count} / {count}"
        )

        self.lbl_servers_title.setText(
            "Серверы — выбрано: 0"
        )

        self.append_log(
            "INFO",
            f"Loaded {count} server(s)."
        )

    # ----------------------------------------------------------
    # Server management
    # ----------------------------------------------------------

    def _add_server(self):
        self._open_server_dialog(None)

    def _edit_server(self, host: str):
        if not host:
            return
        spec = registry.find(host)
        if spec is None:
            return
        self._open_server_dialog(spec)

    def _remove_server(self, host: str):
        if not host:
            return

        answer = QMessageBox.question(
            self,
            "Remove server",
            f"Remove server '{host}'?",
        )

        if answer != QMessageBox.Yes:
            return

        if self.repository.remove_server(host):
            self.append_log(
                "SUCCESS",
                f"Server removed: {host}",
            )
            logger.action(f"Server removed: {host}")
            self._load_servers()

    def _open_server_dialog(self, spec: ServerSpec | None):
        dialog = ServerDialog(spec, self)

        if dialog.exec() != ServerDialog.Accepted:
            return

        new_spec = dialog.spec()

        if spec is None:
            self.repository.add_server(new_spec)
            self.append_log(
                "SUCCESS",
                f"Server added: {new_spec.display_name()} "
                f"({new_spec.engine})",
            )
            logger.action(
                f"Server added: {new_spec.display_name()} "
                f"({new_spec.engine})"
            )
        else:
            self.repository.update_server(spec.host, new_spec)
            self.append_log(
                "SUCCESS",
                f"Server updated: {spec.host} → {new_spec.display_name()} "
                f"({new_spec.engine})",
            )
            logger.action(
                f"Server updated: {spec.host} → {new_spec.display_name()} "
                f"({new_spec.engine})"
            )

        self._load_servers()

    # ----------------------------------------------------------
    # Refresh
    # ----------------------------------------------------------

    def _refresh_servers(self):

        previous = self.servers_tree.topLevelItemCount()

        self._load_servers()

        current = self.servers_tree.topLevelItemCount()

        self.append_log(
            "SUCCESS",
            f"Server list refreshed ({previous} → {current})"
        )

        logger.action(f"Server list refreshed ({previous} → {current})")

    # ----------------------------------------------------------
    # Check
    # ----------------------------------------------------------

    def _run_check(self):

        if self.thread.isRunning():
            return

        self.table.clear_results()
        self.table.results_source = "check"

        self.progress.setValue(0)

        self.lbl_elapsed_value.setText("00:00:00")

        self.lbl_status_value.setText("Готово")

        self.table.clearSelection()

        servers = self.servers_tree.selected_servers()

        # Check работает только с MySQL (MSSQL — браузинг и SQL-консоль).
        mysql_servers = [
            s for s in servers
            if registry.engine(s) == ENGINE_MYSQL
        ]
        skipped = len(servers) - len(mysql_servers)

        if skipped:
            self.append_log(
                "INFO",
                f"Skipped {skipped} MSSQL server(s) — check is MySQL-only.",
            )

        logger.action(
            f"Check run: {len(mysql_servers)} server(s)"
            f"{f', {skipped} MSSQL skipped' if skipped else ''}"
        )

        self.worker.set_servers(mysql_servers)

        self.thread.start()

    def _check_started(self):

        self._set_scripts_running(True)

        self.lbl_status_value.setText("Проверка...")

        self.append_log(
            "INFO",
            "Check started.",
        )
        self._started_at = time.perf_counter()

        self._elapsed_timer.start()

    def _check_finished(self):

        self._set_scripts_running(False)

        self.table.setSortingEnabled(True)

        for index in range(self.table.columnCount()):
            self.table.resizeColumnToContents(index)

        self.table.sync_filter_columns()

        self.table.apply_filters()

        self.progress.setValue(100)

        self.lbl_status_value.setText("Готово")

        self.append_log(
            "SUCCESS",
            "Check completed.",
        )
        self._elapsed_timer.stop()

        elapsed = 0.0
        if self._started_at is not None:
            elapsed = time.perf_counter() - self._started_at
            logger.action(f"Check finished: {elapsed:.2f} s")

        self._started_at = None

        # Неразрушающее обновление размеров раскрытых серверов:
        # дерево остаётся раскрытым, свежие данные приходят в фоне.
        self._refresh_expanded_sizes()

    # ----------------------------------------------------------
    # UI
    # ----------------------------------------------------------

    def _build_ui(self):
        self.setObjectName("MainWindow")

        self.setStyleSheet(theme_styles.build_stylesheet())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        content_widget = QWidget()
        content = QVBoxLayout(content_widget)
        content.setContentsMargins(8, 8, 8, 0)
        content.setSpacing(6)

        status_bar = QFrame()
        status_bar.setObjectName("StatusBar")

        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(12, 3, 12, 3)
        status_layout.setSpacing(6)

        self.lbl_status = QLabel("Статус:")
        self.lbl_status_value = QLabel("Готово")

        self.lbl_servers = QLabel("Серверы:")
        self.lbl_servers_value = QLabel("0 / 0")

        self.lbl_elapsed = QLabel("Прошло:")
        self.lbl_elapsed_value = QLabel("00:00:00")

        self.lbl_sql = QLabel("SQL Консоль:")
        self.lbl_sql_status = QLabel("Готово")

        for label in (
            self.lbl_status,
            self.lbl_servers,
            self.lbl_elapsed,
            self.lbl_sql,
        ):
            label.setStyleSheet(
                "color:#94a3b8;font-size:12px;border:none;"
                "background:transparent;"
            )

        for label in (
            self.lbl_status_value,
            self.lbl_servers_value,
            self.lbl_elapsed_value,
            self.lbl_sql_status,
        ):
            label.setStyleSheet(
                "color:#f8fafc;font-size:12px;font-weight:600;"
                "border:none;background:transparent;"
            )

        status_layout.addWidget(self.lbl_status)
        status_layout.addWidget(self.lbl_status_value)

        status_layout.addSpacing(12)

        status_layout.addWidget(self.lbl_servers)
        status_layout.addWidget(self.lbl_servers_value)

        status_layout.addSpacing(12)

        status_layout.addWidget(self.lbl_elapsed)
        status_layout.addWidget(self.lbl_elapsed_value)

        status_layout.addSpacing(12)

        status_layout.addWidget(self.lbl_sql)
        status_layout.addWidget(self.lbl_sql_status)

        status_layout.addStretch()

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedWidth(160)
        self.progress.setTextVisible(False)

        status_layout.addWidget(self.progress)

        self._build_theme_toggle()
        status_layout.addWidget(self.btn_theme)

        body_splitter = CollapsibleSplitter(Qt.Horizontal)
        body_splitter.setHandleWidth(6)
        body_splitter.sectionDoubleClicked.connect(
            self._body_section_double_clicked
        )

        self.server_frame = QFrame()
        self.server_frame.setMinimumWidth(200)
        server_layout = QVBoxLayout(self.server_frame)
        server_layout.setContentsMargins(8, 6, 8, 6)
        server_layout.setSpacing(6)

        self.lbl_servers_title = QLabel("Серверы — выбрано: 0")
        self.lbl_servers_title.setObjectName("SectionTitle")

        servers_top = QHBoxLayout()

        servers_top.addWidget(self.lbl_servers_title)

        servers_top.addStretch()

        server_layout.addLayout(servers_top)

        self.search = QLineEdit()
        self.search.setObjectName("SearchField")
        self.search.setPlaceholderText("Поиск сервера, БД, таблицы…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedHeight(26)
        self.search.addAction(
            icon("search", 14, "@icon_muted"), QLineEdit.LeadingPosition
        )
        server_layout.addWidget(self.search)

        buttons = QHBoxLayout()

        self.btn_refresh_servers = QToolButton()
        self.btn_refresh_servers.setObjectName("btn_icon")
        self.btn_refresh_servers.setIcon(icon("refresh", 16, "@icon_accent"))
        self.btn_refresh_servers.setIconSize(QSize(16, 16))
        self.btn_refresh_servers.setToolTip("Обновить список серверов")
        self.btn_refresh_servers.clicked.connect(
            self._refresh_servers
        )

        self.btn_add_server = QToolButton()
        self.btn_add_server.setObjectName("btn_icon")
        self.btn_add_server.setIcon(icon("add", 16, "@icon_accent"))
        self.btn_add_server.setIconSize(QSize(16, 16))
        self.btn_add_server.setToolTip("Добавить сервер")
        self.btn_add_server.clicked.connect(self._add_server)

        self.btn_select_all = QToolButton()
        self.btn_select_all.setObjectName("btn_icon")
        self.btn_select_all.setIcon(icon("done_all"))
        self.btn_select_all.setIconSize(QSize(16, 16))
        self.btn_select_all.setToolTip("Выбрать все")

        self.btn_clear = QToolButton()
        self.btn_clear.setObjectName("btn_icon")
        self.btn_clear.setIcon(icon("close"))
        self.btn_clear.setIconSize(QSize(16, 16))
        self.btn_clear.setToolTip("Снять выделение")

        self.btn_invert = QToolButton()
        self.btn_invert.setObjectName("btn_icon")
        self.btn_invert.setIcon(icon("swap_horiz"))
        self.btn_invert.setIconSize(QSize(16, 16))
        self.btn_invert.setToolTip("Инвертировать выделение")

        buttons.addWidget(self.btn_refresh_servers)
        buttons.addWidget(self.btn_add_server)
        buttons.addWidget(self.btn_select_all)
        buttons.addWidget(self.btn_clear)
        buttons.addWidget(self.btn_invert)

        server_layout.addLayout(buttons)

        self.servers_tree = ServersTree()
        server_layout.addWidget(self.servers_tree)

        body_splitter.addWidget(self.server_frame)

        right_container = QWidget()
        right_container.setMinimumWidth(200)
        body_splitter.addWidget(right_container)
        body_splitter.setStretchFactor(0, 0)
        body_splitter.setStretchFactor(1, 1)
        body_splitter.setSizes([280, 900])
        self.body_splitter = body_splitter

        right = QVBoxLayout(right_container)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)

        table_frame = QFrame()
        table_frame.setObjectName("TabPage")

        table_layout = QVBoxLayout(table_frame)
        table_layout.setContentsMargins(8, 6, 8, 6)
        table_layout.setSpacing(6)

        filter_layout = QHBoxLayout()

        self.result_search = QLineEdit()
        self.result_search.setObjectName("SearchField")
        self.result_search.setPlaceholderText(
            "Поиск по всем колонкам..."
        )
        self.result_search.setClearButtonEnabled(True)
        self.result_search.setFixedHeight(26)
        self.result_search.setMaximumWidth(420)
        self.result_search.addAction(
            icon("search", 14, "@icon_muted"), QLineEdit.LeadingPosition
        )
        self.result_search.setToolTip(
            "Сквозной поиск: строка видима, если текст найден "
            "хотя бы в одной колонке (OR)."
        )
        filter_layout.addWidget(
            self.result_search,
            1,
        )

        self.chk_only_errors = QCheckBox(
            "Только ошибки"
        )
        self.chk_only_errors.setFixedHeight(26)

        filter_layout.addWidget(self.chk_only_errors)

        self.btn_export_all = QToolButton()
        self.btn_export_all.setObjectName("btn_icon")
        self.btn_export_all.setIcon(icon("download"))
        self.btn_export_all.setIconSize(QSize(16, 16))
        self.btn_export_all.setToolTip(
            "Сохранить все результаты без ограничения строк "
            "(повторно выполнит последний SQL-запрос)"
        )
        self.btn_export_all.clicked.connect(self._export_all_results)

        filter_layout.addWidget(self.btn_export_all)

        table_layout.addLayout(filter_layout)

        self.table = ResultTable()
        table_layout.addWidget(self.table)

        self.table.attach_filters(
            self.result_search,
            self.chk_only_errors,
        )

        # ----------------------------------------------------------
        # Log Panel UI
        # ----------------------------------------------------------

        log_frame = QFrame()
        log_frame.setObjectName("TabPage")

        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(8, 8, 8, 8)
        log_layout.setSpacing(8)

        top = QHBoxLayout()

        top.addStretch()

        self.btn_log_clear = QToolButton()
        self.btn_log_clear.setObjectName("btn_icon")
        self.btn_log_clear.setIcon(icon("delete_outline"))
        self.btn_log_clear.setIconSize(QSize(16, 16))
        self.btn_log_clear.setToolTip("Очистить лог")

        self.btn_log_copy = QToolButton()
        self.btn_log_copy.setObjectName("btn_icon")
        self.btn_log_copy.setIcon(icon("content_copy"))
        self.btn_log_copy.setIconSize(QSize(16, 16))
        self.btn_log_copy.setToolTip("Копировать лог")

        self.btn_log_save = QToolButton()
        self.btn_log_save.setObjectName("btn_icon")
        self.btn_log_save.setIcon(icon("download"))
        self.btn_log_save.setIconSize(QSize(16, 16))
        self.btn_log_save.setToolTip("Сохранить лог")

        top.addWidget(self.btn_log_clear)
        top.addWidget(self.btn_log_copy)
        top.addWidget(self.btn_log_save)

        log_layout.addLayout(top)

        self.log = QTextEdit()
        self.log.setReadOnly(True)

        log_layout.addWidget(self.log)

        # --- Журнал запросов ---
        query_log_header = QHBoxLayout()

        self.lbl_query_log_title = QLabel("Журнал запросов")
        self.lbl_query_log_title.setObjectName("SectionTitle")
        query_log_header.addWidget(self.lbl_query_log_title)

        query_log_header.addStretch()

        self.btn_query_log_clear = QToolButton()
        self.btn_query_log_clear.setObjectName("btn_icon")
        self.btn_query_log_clear.setIcon(icon("delete_outline"))
        self.btn_query_log_clear.setIconSize(QSize(16, 16))
        self.btn_query_log_clear.setToolTip("Очистить журнал запросов")
        self.btn_query_log_clear.clicked.connect(self._clear_query_log)
        query_log_header.addWidget(self.btn_query_log_clear)

        log_layout.addLayout(query_log_header)

        self.query_log = QTextEdit()
        self.query_log.setReadOnly(True)
        self.query_log.setFixedHeight(96)
        log_layout.addWidget(self.query_log)

        # ----------------------------------------------------------
        # Scripts Library UI
        # ----------------------------------------------------------

        self.scripts_store = ScriptStore()
        self._script_tabs: list[ScriptTab] = []

        # ----------------------------------------------------------
        # SQL Console Panel UI
        # ----------------------------------------------------------

        sql_console_frame = QFrame()
        self.sql_console_frame = sql_console_frame

        # Единый интерфейс: SQL-консоль и открытые скрипты живут в одной
        # вкладке-блоке (скрипты больше не попадают в «Результаты/Журнал»).
        # DocumentMode не используется: нативная светлая заливка таб-бара
        # не перекрашивается QSS и даёт белую полосу в тёмной теме.
        self.console_tabs = QTabWidget()
        self.console_tabs.setTabsClosable(True)
        self.console_tabs.tabCloseRequested.connect(
            self._console_tab_close_requested
        )

        self.panel = SqlConsolePanel()

        self.console_tabs.addTab(self.panel, "SQL Консоль")
        self.console_tabs.tabBar().setTabButton(
            0, QTabBar.RightSide, None
        )

        sql_console_layout = QVBoxLayout(sql_console_frame)
        sql_console_layout.setContentsMargins(0, 0, 0, 0)
        sql_console_layout.setSpacing(0)
        sql_console_layout.addWidget(self.console_tabs)

        self.tabs = QTabWidget()
        self.tabs.addTab(table_frame, "Результаты")
        self.tabs.addTab(log_frame, "Журнал")

        self.tabs_frame = QFrame()
        self.tabs_frame.setObjectName("TabsBlock")
        self.tabs_frame_layout = QVBoxLayout(self.tabs_frame)
        self.tabs_frame_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs_frame_layout.setSpacing(0)

        self.tabs_frame_layout.addWidget(self.tabs)

        self.right_splitter = CollapsibleSplitter(Qt.Vertical)
        self.right_splitter.setOpaqueResize(True)
        self.right_splitter.setHandleWidth(8)
        self.right_splitter.addWidget(sql_console_frame)
        self.right_splitter.addWidget(self.tabs_frame)
        self.right_splitter.setSizes([240, 560])
        self.right_splitter.sectionDoubleClicked.connect(
            self._right_section_double_clicked
        )
        right.addWidget(self.right_splitter)

        self.append_log(
            "INFO",
            f"Parallels SQL Admins v{APP_VERSION} started."
        )
        self.append_log("SUCCESS", "GUI initialized.")
        self.append_log("INFO", "Ready.")

        # ----------------------------------------------------------
        # Signals
        # ----------------------------------------------------------

        self.servers_tree.selectionChangedNotify.connect(
            self._update_selected_count
        )

        self.btn_select_all.clicked.connect(
            self.servers_tree.selectAll
        )

        self.btn_clear.clicked.connect(
            self.servers_tree.clearSelection
        )

        self.btn_invert.clicked.connect(
            self.servers_tree.invert_selection
        )

        self.search.textChanged.connect(
            self.servers_tree.filter
        )

        self.servers_tree.tableSelectRequested.connect(
            self._run_table_select
        )

        self.servers_tree.addServerRequested.connect(
            self._add_server
        )

        self.servers_tree.editServerRequested.connect(
            self._edit_server
        )

        self.servers_tree.removeServerRequested.connect(
            self._remove_server
        )

        self.btn_log_clear.clicked.connect(
            lambda: (
                self.log.clear(),
                logger.action("Log cleared"),
            )
        )

        self.btn_log_copy.clicked.connect(
            lambda: (
                self.log.copy(),
                logger.action("Log copied to clipboard"),
            )
        )

        self.btn_log_save.clicked.connect(
            self._save_log
        )

        self.table.visibilityRequested.connect(
            self._ensure_results_visible
        )

        self.table.dbSelected.connect(
            self._apply_result_to_console
        )

        self.table.logMessage.connect(
            self.append_log
        )

        self.panel.runRequested.connect(
            self._run_sql
        )

        self.panel.stopRequested.connect(
            self._sql_stop
        )

        self.panel.refreshDatabasesRequested.connect(
            self._sql_refresh_databases
        )

        self.panel.clearRequested.connect(
            self._sql_clear
        )

        self.panel.serverChanged.connect(
            self._sql_server_changed
        )

        self.panel.scopeChanged.connect(
            self._sql_scope_changed
        )

        self.panel.catalogRequested.connect(
            self._completion_catalog_requested
        )

        self.panel.searchRequested.connect(
            self._search_run
        )

        self.panel.searchStopRequested.connect(
            self._search_stop
        )

        content.addWidget(body_splitter, 1)

        root.addWidget(content_widget, 1)

        root.addWidget(status_bar)

        self._started_at = None

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(
            self._update_elapsed
        )

    # --------------------------------------------------------------
    # Slots
    # --------------------------------------------------------------

    def _update_selected_count(self):
        self.lbl_servers_title.setText(
            f"Серверы — выбрано: {self.servers_tree.selected_count()}"
        )

    def _body_section_double_clicked(self, section: int) -> None:
        """Оставляет ручку Servers видимой после сворачивания секции."""
        # Не вызываем setVisible(False): скрытие самого виджета также скрывает
        # связанную с ним ручку QSplitter и лишает возможности раскрыть панель.
        if section == 0:
            collapsed = self.body_splitter.is_section_collapsed(0)
            logger.action(f"Servers panel {'collapsed' if collapsed else 'expanded'}")
            self.body_splitter.update()

    def _right_section_double_clicked(self, section: int) -> None:
        """Оставляет ручки вертикального splitter доступными."""
        # Панели остаются видимыми для Qt и скрываются только размером 0 px.
        if 0 <= section < self.right_splitter.count():
            names = {0: "SQL Console", 1: "Results"}
            name = names.get(section, f"Section {section}")
            collapsed = self.right_splitter.is_section_collapsed(section)
            logger.action(f"{name} panel {'collapsed' if collapsed else 'expanded'}")
            self.right_splitter.update()

    def _toggle_servers_panel(self, visible):
        """Программно показывает или сворачивает Servers без скрытия ручки."""
        sizes = self.body_splitter.sizes()
        if visible:
            if sizes[0] == 0:
                self.body_splitter.setSizes([280, max(1, sum(sizes) - 280)])
        else:
            sizes[0] = 0
            self.body_splitter.setSizes(sizes)

    def _toggle_results_panel(self, visible):
        """Показывает или сворачивает Results, сохраняя его ручку."""
        sizes = self.right_splitter.sizes()
        if visible:
            if sizes[1] == 0:
                self.right_splitter.setSizes([240, 560])
        else:
            sizes[1] = 0
            self.right_splitter.setSizes(sizes)

    def _ensure_results_visible(self, *_args) -> None:
        if not self.tabs_frame.isVisible():
            self._toggle_results_panel(True)
        if self.tabs.currentIndex() != 0:
            self.tabs.setCurrentIndex(0)

    def _apply_result_to_console(self, server: str, database: str) -> None:
        self.panel.set_target(server, database)

        self.append_log(
            "SUCCESS",
            f"Result applied to console: [{server}.{database}]",
        )

    # ----------------------------------------------------------
    # Sizes
    # ----------------------------------------------------------

    def _sizes_error(self, server: str, context: str, message: str):
        self.append_log(
            "ERROR",
            f"Sizes [{server}/{context}]: {message}",
        )

    # ----------------------------------------------------------
    # Log Methods
    # ----------------------------------------------------------

    def append_log(self, level: str, message: str):

        colors = {
            "INFO": theme_styles.color("log_info"),
            "SUCCESS": theme_styles.color("log_success"),
            "WARNING": theme_styles.color("log_warning"),
            "ERROR": theme_styles.color("log_error"),
        }

        color = colors.get(level.upper(), theme_styles.color("log_text"))

        stamp = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        self.log.append(
            f'<span style="color:{theme_styles.color("log_stamp")};">'
            f'{stamp}</span> '
            f'<span style="color:{color};"><b>[{level.upper()}]</b></span> '
            f'{message}'
        )

        self.log.moveCursor(QTextCursor.End)

        # Дублируем в файловый лог для изучения после закрытия приложения.
        _LEVELS = {
            "SUCCESS": logger.info,
            "WARNING": logger.warning,
            "ERROR": logger.error,
        }
        _LEVELS.get(level.upper(), logger.info)(message)

    # ----------------------------------------------------------
    # Scripts Library
    # ----------------------------------------------------------

    def _append_query(self, text):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.query_log.append(f"[{stamp}] {text}")
        logger.info(f"SQL: {text}")

    def _run_check_script(self, template: str):
        sql_builder.set_custom_template(template)
        self._run_check()

    def _set_scripts_running(self, running: bool) -> None:
        for tab in self._script_tabs:
            tab.set_running(running)

    def _open_script_tab(self, name: str, body: str) -> None:
        for tab in self._script_tabs:
            if tab.script_name() == name:
                self.console_tabs.setCurrentWidget(tab)
                return
        tab = ScriptTab(name, body)
        tab.insertToConsoleRequested.connect(self._script_insert_to_console)
        tab.runRequested.connect(self._script_run_requested)
        index = self.console_tabs.addTab(tab, f"Скрипт: {name}")
        self._script_tabs.append(tab)
        self.console_tabs.setCurrentIndex(index)

    def _script_insert_to_console(self, text: str) -> None:
        self.panel.insert_script(text)
        self.console_tabs.setCurrentWidget(self.panel)
        logger.action("Script inserted into console")

    def _script_run_requested(self, text: str) -> None:
        self._run_check_script(text)

    def _console_tab_close_requested(self, index: int) -> None:
        if index == 0:  # «SQL Консоль» — постоянная вкладка
            return
        tab = self.console_tabs.widget(index)
        if not isinstance(tab, ScriptTab):
            return
        if not self._confirm_script_tab_close(tab):
            return
        self.console_tabs.removeTab(index)
        if tab in self._script_tabs:
            self._script_tabs.remove(tab)

    def _confirm_script_tab_close(self, tab) -> bool:
        """True — вкладку можно закрыть (с сохранением или без)."""
        if not tab.is_dirty():
            return True
        answer = QMessageBox.question(
            self,
            "Несохранённые изменения",
            f"Сохранить изменения скрипта «{tab.script_name()}»?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            saved = self.scripts_store.update_script(
                tab.script_name(), tab.current_text()
            )
            if saved:
                logger.action(
                    f"Script updated: {tab.script_name()}"
                )
        return True

    def _clear_query_log(self):
        self.query_log.clear()
        logger.action("Query log cleared")

    # ----------------------------------------------------------
    # SQL Console
    # ----------------------------------------------------------

    def _run_sql(self, sql: str):

        if self.query_thread.isRunning():
            self.lbl_sql_status.setText("Запрос уже выполняется. Подождите или нажмите «Остановить».")
            return

        sql = sql.strip()

        if not sql:
            return

        if not split_statements(sql):
            self.lbl_sql_status.setText("Нет SQL-запросов для выполнения.")
            return

        targets = self._sql_build_targets()

        if not targets:
            self.lbl_sql_status.setText("Не выбраны цели.")
            return

        if not self.panel.write_enabled() and is_write_statement(sql):
            answer = QMessageBox.question(
                self,
                "Write query",
                "The query may modify data.\n\nContinue?",
            )

            if answer != QMessageBox.Yes:
                logger.action("Write query denied by user")
                return

            logger.action("Write query confirmed by user")

        logger.action(
            f"SQL run: targets={len(targets)}, "
            f"statements={len(split_statements(sql))}"
        )

        self.table.reset_table()
        self.table.results_source = "sql"

        self._last_sql_request = (targets, sql)

        self.lbl_sql_status.setText(
            f"Выполнение на {len(targets)} цели(ях)..."
        )
        self.panel.set_busy(True)

        if (
            len(targets) == 1
            and targets[0][1] != ALL_DATABASES
        ):
            self.query_worker.set_request(
                targets[0][0],
                targets[0][1],
                sql,
                1000,
            )

        else:

            self.query_worker.set_multi_request(
                targets,
                sql,
                1000,
            )

        self.query_thread.start()

    def _sql_build_targets(self):

        if self.panel.all_servers_checked():

            hosts = self.servers_tree.selected_servers()

            hosts = [host for host in hosts if host]

        else:

            host = self.panel.current_host()
            hosts = [host] if host else []

        if not hosts:
            return []

        database = (
            ALL_DATABASES
            if self.panel.all_databases_checked()
            else self.panel.current_database() or None
        )

        return [
            (host, database) for host in hosts
        ]

    def _sql_server_changed(self, text):
        self._sql_refresh_databases()

    def _sql_scope_changed(self, checked):
        self.panel.cb_server.setEnabled(
            not self.panel.all_servers_checked()
        )
        self.panel.cb_database.setEnabled(
            not self.panel.all_databases_checked()
        )

    _COMPLETION_TTL = 300  # секунд, после чего каталог перечитывается

    def _completion_catalog_requested(self, host, database):
        host = (host or "").strip()
        database = (database or "").strip()

        if not host or not database:
            return

        key = (host, database)
        cached = self._completion_cache.get(key)
        now = time.monotonic()

        if cached is not None and now - cached[2] < self._COMPLETION_TTL:
            self.panel.set_catalog(cached[0], cached[1])
            return

        if self.completion_thread.isRunning():
            # Текущий запрос ещё выполняется — запомним и повторим после.
            self._completion_pending = True
            self._completion_request = key
            return

        # Сбрасываем старый каталог, чтобы не показывать чужие таблицы.
        self.panel.clear_completion()

        logger.info(f"Completion catalog requested: {host}/{database}")

        self.completion_worker.set_request(host, database)
        self.completion_thread.start()

    def _completion_catalog_ready(self, host, database, tables, columns):
        self._completion_cache[(host, database)] = (
            list(tables),
            dict(columns),
            time.monotonic(),
        )
        self.panel.set_catalog(tables, columns)

        if self._completion_pending:
            self._completion_pending = False
            request = self._completion_request
            self._completion_request = None
            if request is not None:
                # Стартуем после того, как поток завершит текущую задачу.
                QTimer.singleShot(
                    0,
                    lambda: self._completion_catalog_requested(*request),
                )

    def _completion_catalog_error(self, host, database, message):
        self.panel.set_catalog([], {})
        self.append_log(
            "WARNING",
            f"Автодополнение [{host}/{database}]: {message}",
        )

    def _sql_stop(self):

        self.query_worker.stop()
        self.lbl_sql_status.setText("Остановка...")

        logger.action("SQL execution stopped by user")

        # KILL активного запроса в фоне, чтобы не блокировать GUI.
        threading.Thread(
            target=self.query_worker.kill_active,
            daemon=True,
        ).start()

    def _sql_refresh_databases(self):

        if self.query_thread.isRunning():
            return

        host = self.panel.current_host()

        if not host:
            self._sql_error("Не выбран сервер.")
            return

        self.lbl_sql_status.setText("Загрузка списка БД...")
        self.panel.set_busy(True)
        self.panel.set_stop_enabled(False)

        logger.action(f"Databases refresh requested: {host}")

        self.query_worker.set_databases_request(host)

        self.query_thread.start()

    def _sql_clear(self):

        self.table.clear_results()
        self.lbl_sql_status.setText("Готово")

    def _set_export_ui(self, running: bool) -> None:

        if running:
            self.btn_export_all.setIcon(icon("stop"))
            self.btn_export_all.setToolTip("Остановить экспорт")
        else:
            self.btn_export_all.setIcon(icon("download"))
            self.btn_export_all.setToolTip(
                "Сохранить все результаты без ограничения строк "
                "(повторно выполнит последний SQL-запрос)"
            )

    def _export_all_results(self):

        # Клик во время экспорта = остановить экспорт.
        if self.export_thread.isRunning():
            self.export_worker.stop()

            threading.Thread(
                target=self.export_worker.kill_active,
                daemon=True,
            ).start()

            self.lbl_sql_status.setText("Остановка экспорта...")
            return

        if self._last_sql_request is None:
            self.lbl_sql_status.setText("Сначала выполните запрос.")
            return

        targets, sql = self._last_sql_request

        if is_write_statement(sql):
            self.lbl_sql_status.setText("Экспорт доступен только для запросов на чтение.")
            return

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save all results",
            "results_all.csv",
            "CSV files (*.csv);;All files (*)",
        )

        if not filename:
            return

        self.lbl_sql_status.setText("Экспорт всех результатов...")
        self._set_export_ui(True)

        logger.action(f"Export started: {filename}")

        self.export_worker.set_export_request(targets, sql, filename)

        self.export_thread.start()

    def _export_done(self, total_rows, filepath):

        self.lbl_sql_status.setText(
            f"Сохранено строк: {total_rows} → {filepath}"
        )

        self.append_log(
            "SUCCESS",
            f"Exported {total_rows} row(s) to {filepath}",
        )

        logger.action(f"Export done: {total_rows} row(s) → {filepath}")

    def _export_finished(self):

        self._set_export_ui(False)

    def _export_error(self, message):

        self.lbl_sql_status.setText(f"Ошибка экспорта: {message}")
        self._set_export_ui(False)

        self.append_log(
            "ERROR",
            f"Export: {message}",
        )

    def _export_target_error(self, host, database, message):

        self.append_log(
            "ERROR",
            f"Export [{host}.{database}]: {message}",
        )

    def _export_stopped(self, done, total):

        self.lbl_sql_status.setText(
            f"Экспорт остановлен ({done} из {total})"
        )
        self._set_export_ui(False)

        logger.action(f"Export stopped ({done} of {total})")

    def _sql_finished(self):

        self.table.setSortingEnabled(True)
        self.table.sync_filter_columns()
        self.table.apply_filters()
        self.panel.set_busy(False)
        self._ensure_results_visible()

    def _sql_target_started(self, index, total, host, database):

        self.lbl_sql_status.setText(
            f"Выполнение ({index}/{total}) {host}.{database}"
        )

    def _sql_target_result(
        self,
        host,
        database,
        rows,
        columns,
        message,
    ):

        self.table.fill_sql_result(
            host,
            database,
            rows,
            columns,
            message,
        )

        self.lbl_sql_status.setText(
            f"OK {host}.{database} — {message}"
        )

    def _sql_target_error(self, host, database, message):

        self.append_log(
            "ERROR",
            f"SQL [{host}.{database}]: {message}",
        )

        self.table.fill_sql_result(
            host,
            database,
            [],
            [],
            f"ERROR: {message}",
        )

        self.lbl_sql_status.setText(
            f"Ошибка {host}.{database}"
        )

    def _sql_target_stopped(self, done, total):

        self.lbl_sql_status.setText(
            f"Остановлено ({done} из {total})"
        )
        self.panel.set_busy(False)

    def _show_query_result(self, rows, columns, message):

        host = self.panel.current_host()
        database = self.panel.current_database()

        self.table.fill_sql_result(
            host,
            database,
            rows,
            columns,
            message,
        )

        self.lbl_sql_status.setText(message)
        self.panel.set_busy(False)

    def _sql_error(self, message):

        self.lbl_sql_status.setText(f"Ошибка: {message}")
        self.panel.set_busy(False)

        self.append_log(
            "ERROR",
            f"SQL: {message}",
        )

    def _show_databases(self, names):

        self.panel.set_databases(names)

        self.lbl_sql_status.setText(
            f"Загружено БД: {len(names)}."
        )
        self.panel.set_busy(False)

    # ----------------------------------------------------------
    # Database search
    # ----------------------------------------------------------

    def _search_run(self):

        if self.search_thread.isRunning():
            return

        mask = self.panel.search_mask()

        if not mask:
            self.lbl_sql_status.setText("Введите маску БД.")
            return

        # Транслитерация '?' и '*' в LIKE-джокеры.
        # Затем автоматически обрамляем %...% — поиск по содержимому,
        # пользователю не нужно вводить символы %.
        mask = mask.replace("*", "%").replace("?", "_")
        mask = f"%{mask}%"

        # Запрещаем небезопасные символы (обратная кавычка, точка-звёздочка),
        # чтобы не ломать запрос и не выводить мусор.
        if any(ch in mask for ch in ("`", "\x00")):
            self.lbl_sql_status.setText(
                "Маска содержит недопустимые символы."
            )
            return

        servers = self.repository.load_servers()

        if not servers:
            self.lbl_sql_status.setText("Нет серверов для поиска.")
            return

        servers = [spec.host for spec in servers]

        # Поиск БД работает только с MySQL.
        servers = [s for s in servers if registry.engine(s) == ENGINE_MYSQL]

        if not servers:
            self.lbl_sql_status.setText("Нет MySQL-серверов для поиска.")
            return

        # Поиск показывает результат в таблице Results с колонками
        # Server и Database.
        self.table.reset_table()
        self.table.results_source = "search"

        self.progress.setValue(0)

        self._search_found = 0
        self._search_completed = 0
        self._search_stopped = False

        self.lbl_sql_status.setText(
            f"Поиск «{mask}» на {len(servers)} сервере(ах)..."
        )

        logger.action(
            f"Search run: mask={mask!r}, servers={len(servers)}"
        )

        self._search_busy(True)

        self.search_worker.set_request(mask, servers)

        self.search_thread.start()

    def _search_stop(self):

        if not self.search_thread.isRunning():
            return

        self.search_worker.stop()

        self._search_stopped = True

        logger.action("Search stopped.")

        self.lbl_sql_status.setText("Остановка поиска...")

    def _search_started(self):

        self.panel.set_search_busy(True)

    def _search_finished(self):

        self.panel.set_search_busy(False)

        self.table.setSortingEnabled(True)

        self.table.sync_filter_columns()

        self.table.apply_filters()

        self._search_busy(False)

        if self._search_stopped:
            self.lbl_sql_status.setText("Поиск остановлен.")
        else:
            self.lbl_sql_status.setText(
                f"Поиск завершён: найдено БД — {self._search_found} "
                f"на {self._search_completed} сервере(ах)."
            )
            logger.action(
                f"Search finished: found={self._search_found} "
                f"servers={self._search_completed}"
            )

        self.progress.setValue(0)

        # Неразрушающее обновление размеров раскрытых серверов:
        # дерево остаётся раскрытым, свежие данные приходят в фоне.
        self._refresh_expanded_sizes()

    def _refresh_expanded_sizes(self):
        """Обновляет размеры/таблицы раскрытых серверов в фоне,
        не сбрасывая раскрытое состояние дерева."""
        expanded = [
            self.servers_tree.server_name(self.servers_tree.topLevelItem(i))
            for i in range(self.servers_tree.topLevelItemCount())
            if self.servers_tree.topLevelItem(i).isExpanded()
        ]

        if expanded:
            self.sizes_worker.refresh_sizes(expanded)

    def _search_progress(self, current, total):
        self._update_progress(current, total)
        self._search_completed = current

    def _search_result(self, server, database):

        self._search_found += 1

        self.table.add_search_result(server, database)

    def _search_error(self, server, message):

        self.append_log(
            "ERROR",
            f"Search [{server}]: {message}",
        )

    def _search_busy(self, busy):

        self.panel.set_search_busy(busy)

    def _run_table_select(self, server: str, database: str, table: str):
        """Выполняет SELECT * FROM `db`.`table` в фоновом потоке."""
        # Если поток занят (например, загрузкой списка БД) — останавливаем его,
        # чтобы SELECT гарантированно выполнился. KILL всех активных запросов
        # убирает зависший SELECT на сервере; ждём выхода потока штатно,
        # без terminate(): принудительное убийство потока оставило бы
        # соединение в пуле навсегда занятым.
        if self.query_thread.isRunning():
            self.query_worker.stop()
            threading.Thread(
                target=self.query_worker.kill_active,
                daemon=True,
            ).start()
            self.query_thread.wait(5000)
            if self.query_thread.isRunning():
                self.lbl_sql_status.setText(
                    "Не удалось остановить текущий запрос."
                )
                self.append_log(
                    "ERROR",
                    "Не удалось остановить текущий запрос; "
                    "SELECT таблицы пропущен.",
                )
                return

        engine = registry.engine(server)

        sql = build_select_sql(engine, database, table, 1000)

        self.table.reset_table()
        self.table.results_source = "sql"

        self.lbl_sql_status.setText(
            f"Выполнение {server}.{database}.{table}..."
        )
        self.panel.set_busy(True)

        self._ensure_results_visible()

        self.query_worker.set_multi_request(
            [(server, database)],
            sql,
            1000,
        )
        self.query_thread.start()

        self.append_log(
            "INFO",
            f"{sql} @ {server}",
        )

        logger.action(f"Table select: {server}.{database}.{table}")

    def _save_log(self):

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save log",
            "parallels_sql_admins.log",
            "Log files (*.log);;Text files (*.txt);;All files (*)",
        )

        if not filename:
            self.append_log(
                "INFO",
                "Log save cancelled."
            )
            return

        with open(
            filename,
            "w",
            newline="",
            encoding="utf-8-sig",
            ) as f:
                f.write(
                    self.log.toPlainText()
                )

        self.append_log(
            "SUCCESS",
            f"Log saved to {filename}",
        )

        logger.action(f"Log saved to {filename}")

    def _on_about_to_quit(self):
        """QApplication.aboutToQuit → останавливаем потоки до выхода.

        Покрывает путь завершения через quit(), когда окно не закрывается и
        closeEvent не приходит.
        """
        self.shutdown()

    def shutdown(self):
        """Останавливает все фоновые потоки (вызывается из closeEvent/aboutToQuit)."""
        if self._shutdown_done:
            return
        self._shutdown_done = True

        self._theme_timer.stop()
        theme_styles.unregister_theme_listener(self._on_theme_applied)

        for worker in (
            self.worker,
            self.query_worker,
            self.search_worker,
            self.sizes_worker,
            self.export_worker,
            self.completion_worker,
        ):
            try:
                worker.stop()
            except Exception:
                pass

        # Прерываем активный экспорт на сервере (KILL), чтобы поток
        # вышел быстро, а не ждал read_timeout.
        try:
            if self.export_thread.isRunning():
                threading.Thread(
                    target=self.export_worker.kill_active,
                    daemon=True,
                ).start()
        except Exception:
            pass

        for thr in (
            self.thread,
            self.query_thread,
            self.search_thread,
            self.sizes_thread,
            self.export_thread,
            self.completion_thread,
        ):
            try:
                if thr.isRunning():
                    thr.requestInterruption()
                    thr.quit()
                    if not thr.wait(5000):
                        thr.terminate()
                        thr.wait(2000)
            except Exception:
                pass

        try:
            mysql.close_all()
        except Exception:
            pass

        try:
            logger.session_end()
        finally:
            logger.cleanup()

    def event(self, e):
        if e.type() == QEvent.ApplicationPaletteChange:
            theme_styles.maybe_system_change()
        return super().event(e)

    def _build_theme_toggle(self):
        self.btn_theme = QToolButton()
        self.btn_theme.setObjectName("ThemeToggle")
        self.btn_theme.setPopupMode(QToolButton.InstantPopup)
        self.btn_theme.setIconSize(QSize(16, 16))
        self.btn_theme.setCursor(Qt.PointingHandCursor)

        self._theme_menu = QMenu(self)
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        self._mode_actions = {}
        for mode, label, tip in (
            ("auto", "Авто (по системе)", "Следовать за темой macOS"),
            ("light", "Светлая", "Светлая тема"),
            ("dark", "Тёмная", "Тёмная тема"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setToolTip(tip)
            action.triggered.connect(
                lambda checked=False, m=mode: self._on_theme_mode(m)
            )
            self._theme_group.addAction(action)
            self._theme_menu.addAction(action)
            self._mode_actions[mode] = action
        self.btn_theme.setMenu(self._theme_menu)

    def _on_theme_mode(self, mode: str):
        theme_styles.set_mode(mode)
        logger.action(f"Theme mode set: {mode}")

    def _on_theme_applied(self):
        logger.action(
            f"Theme applied: {theme_styles.current_theme()} "
            f"({theme_styles.mode()})"
        )
        app = QApplication.instance()
        if app is not None:
            app.setPalette(theme_styles.build_palette())
        self.setStyleSheet(theme_styles.build_stylesheet())
        set_icon_theme(theme_styles.theme_colors())
        self._refresh_icons()
        self.servers_tree.retheme_icons()
        self.panel.retheme()
        self._sync_theme_ui()
        theme_styles.apply_window_appearance(self.window())

    def _sync_theme_ui(self):
        mode = theme_styles.mode()
        for mode_name, action in self._mode_actions.items():
            action.setChecked(mode_name == mode)
        theme = theme_styles.current_theme()
        mode_icon = {
            "auto": "auto_mode",
            "light": "light_mode",
            "dark": "dark_mode",
        }[mode]
        self.btn_theme.setIcon(icon(mode_icon, 16, "#f8fafc"))
        self.btn_theme.setToolTip(
            f"Тема: {theme} ({mode})\nАвто — следовать за системой"
        )

    def _refresh_icons(self):
        self.btn_refresh_servers.setIcon(icon("refresh", 16, "@icon_accent"))
        self.btn_add_server.setIcon(icon("add", 16, "@icon_accent"))
        self.btn_select_all.setIcon(icon("done_all"))
        self.btn_clear.setIcon(icon("close"))
        self.btn_invert.setIcon(icon("swap_horiz"))
        self.btn_export_all.setIcon(icon("download"))
        self.btn_log_clear.setIcon(icon("delete_outline"))
        self.btn_log_copy.setIcon(icon("content_copy"))
        self.btn_log_save.setIcon(icon("download"))
        for field in (self.search, self.result_search):
            actions = field.actions()
            if actions:
                actions[0].setIcon(icon("search", 14, "@icon_muted"))

    # ----------------------------------------------------------
    # Application Menu
    # ----------------------------------------------------------

    def build_menu(self, menu_bar) -> None:
        """Собирает меню приложения в переданную QMenuBar (App)."""
        menu_file = menu_bar.addMenu("&Файл")

        act_add_server = menu_file.addAction(
            icon("add", 16, "@icon_accent"), "Добавить сервер…"
        )
        act_add_server.triggered.connect(self._add_server)
        act_add_server.setShortcut("Ctrl+N")

        self._menu_edit = menu_file.addAction(
            icon("edit", 16, "@icon_muted"), "Изменить сервер…"
        )
        self._menu_edit.triggered.connect(self._menu_edit_server)
        self._menu_edit.setShortcut("Ctrl+E")

        self._menu_remove = menu_file.addAction(
            icon("delete_outline", 16, "@icon_danger"), "Удалить сервер"
        )
        self._menu_remove.triggered.connect(self._menu_remove_server)
        self._menu_remove.setShortcut("Ctrl+Del")

        act_refresh_servers = menu_file.addAction(
            icon("refresh", 16, "@icon_accent"), "Обновить список серверов"
        )
        act_refresh_servers.triggered.connect(self._refresh_servers)
        act_refresh_servers.setShortcut("Ctrl+R")

        menu_file.addSeparator()

        act_export = menu_file.addAction(
            icon("download"), "Экспорт всех результатов…"
        )
        act_export.triggered.connect(self._export_all_results)
        act_export.setShortcut("Ctrl+Shift+E")

        act_save_log = menu_file.addAction(
            icon("save"), "Сохранить журнал…"
        )
        act_save_log.triggered.connect(self._save_log)
        act_save_log.setShortcut("Ctrl+S")

        menu_file.addSeparator()

        act_quit = menu_file.addAction(icon("close"), "Выход")
        act_quit.triggered.connect(self.window().close)
        act_quit.setShortcut("Ctrl+Q")

        # --- Проверка ---
        menu_check = menu_bar.addMenu("&Проверка")
        act_run_check = menu_check.addAction(
            icon("play_arrow"), "Запустить проверку"
        )
        act_run_check.triggered.connect(self._run_check)
        act_run_check.setShortcut("F5")

        # --- Поиск ---
        menu_search = menu_bar.addMenu("&Поиск")
        act_search = menu_search.addAction(
            icon("search"), "Найти БД"
        )
        act_search.triggered.connect(self._search_run)
        act_search.setShortcut("Ctrl+F")
        act_search_stop = menu_search.addAction(
            icon("stop"), "Остановить поиск"
        )
        act_search_stop.triggered.connect(self._search_stop)
        act_search_stop.setShortcut("Ctrl+Shift+F")

        # --- Консоль ---
        menu_console = menu_bar.addMenu("&Консоль")
        menu_console.addAction(
            icon("play_arrow"), "Выполнить запрос"
        ).triggered.connect(self._menu_run_sql)
        act_sql_stop = menu_console.addAction(
            icon("stop"), "Остановить выполнение"
        )
        act_sql_stop.triggered.connect(self._sql_stop)
        act_sql_stop.setShortcut("Esc")
        act_sql_refresh = menu_console.addAction(
            icon("refresh"), "Обновить список БД"
        )
        act_sql_refresh.triggered.connect(self._sql_refresh_databases)
        act_sql_refresh.setShortcut("Ctrl+Shift+R")
        menu_console.addSeparator()
        act_sql_clear = menu_console.addAction(
            icon("close"), "Очистить результаты"
        )
        act_sql_clear.triggered.connect(self._sql_clear)
        act_sql_clear.setShortcut("Ctrl+Shift+Backspace")
        act_sql_clear_editor = menu_console.addAction(
            icon("delete_outline"), "Очистить редактор"
        )
        act_sql_clear_editor.triggered.connect(self.panel.clear_editor)
        act_sql_clear_editor.setShortcut("Ctrl+L")

        # --- Скрипты ---
        menu_scripts = menu_bar.addMenu("&Скрипты")
        self._menu_scripts_insert = menu_scripts.addMenu(
            "Вставить в консоль"
        )
        self._menu_scripts_run = menu_scripts.addMenu(
            "Запустить проверку"
        )
        menu_scripts.addSeparator()
        act_scripts_manager = menu_scripts.addAction(
            icon("edit"), "Управление скриптами…"
        )
        act_scripts_manager.triggered.connect(self._menu_scripts_manager)
        act_scripts_manager.setShortcut("Ctrl+Shift+S")
        act_clear_query_log = menu_scripts.addAction(
            icon("delete_outline"), "Очистить журнал запросов"
        )
        act_clear_query_log.triggered.connect(self._clear_query_log)
        act_clear_query_log.setShortcut("Ctrl+Shift+L")
        self._rebuild_scripts_menu()

        # --- Вид ---
        menu_view = menu_bar.addMenu("&Вид")
        menu_theme = menu_view.addMenu("Тема")
        for mode in ("auto", "light", "dark"):
            menu_theme.addAction(self._mode_actions[mode])
        menu_view.addSeparator()
        act_toggle_servers = menu_view.addAction(
            "Свернуть/развернуть панель серверов"
        )
        act_toggle_servers.triggered.connect(
            lambda: self._toggle_servers_panel(
                self.body_splitter.is_section_collapsed(0)
            )
        )
        act_toggle_servers.setShortcut("Ctrl+B")
        act_toggle_results = menu_view.addAction(
            "Свернуть/развернуть результаты"
        )
        act_toggle_results.triggered.connect(
            lambda: self._toggle_results_panel(
                self.right_splitter.is_section_collapsed(1)
            )
        )
        act_toggle_results.setShortcut("Ctrl+Shift+B")

        # --- Журнал ---
        menu_log = menu_bar.addMenu("&Журнал")
        act_log_clear = menu_log.addAction(
            icon("delete_outline"), "Очистить журнал"
        )
        act_log_clear.triggered.connect(
            lambda: (self.log.clear(), logger.action("Log cleared"))
        )
        act_log_clear.setShortcut("Ctrl+Shift+X")
        act_log_copy = menu_log.addAction(
            icon("content_copy"), "Копировать журнал"
        )
        act_log_copy.triggered.connect(
            lambda: (
                self.log.copy(),
                logger.action("Log copied to clipboard"),
            )
        )
        act_log_copy.setShortcut("Ctrl+Shift+C")
        menu_log.addAction(
            icon("save"), "Сохранить журнал…"
        ).triggered.connect(self._save_log)

        # --- Справка ---
        menu_help = menu_bar.addMenu("&Справка")
        act_about = menu_help.addAction(
            icon("info_outline"), "О программе…"
        )
        act_about.triggered.connect(self._menu_about)
        act_about.setShortcut("F1")

        self.servers_tree.selectionChangedNotify.connect(
            self._menu_update_server_actions
        )
        self._menu_update_server_actions()

    def _menu_selected_server(self) -> str:
        servers = self.servers_tree.selected_servers()
        return servers[0] if servers else ""

    def _menu_edit_server(self):
        self._edit_server(self._menu_selected_server())

    def _menu_remove_server(self):
        self._remove_server(self._menu_selected_server())

    def _menu_run_sql(self):
        self._run_sql(self.panel.script_text())

    def _rebuild_scripts_menu(self) -> None:
        for menu in (self._menu_scripts_insert, self._menu_scripts_run):
            menu.clear()
        for item in self.scripts_store.script_items():
            name = item["name"]
            body = item["body"]
            self._menu_scripts_insert.addAction(name).triggered.connect(
                lambda checked=False, n=name, b=body: self._open_script_tab(n, b)
            )
            self._menu_scripts_run.addAction(name).triggered.connect(
                lambda checked=False, n=name, b=body: self._run_check_script(b)
            )

    def _menu_scripts_manager(self):
        dialog = ScriptsManagerDialog(self)
        dialog.exec()
        self.scripts_store.load_scripts()
        self._rebuild_scripts_menu()

    def _menu_update_server_actions(self):
        has = bool(self.servers_tree.selected_servers())
        self._menu_edit.setEnabled(has)
        self._menu_remove.setEnabled(has)

    def _menu_about(self):
        QMessageBox.about(
            self,
            "О программе",
            f"<b>Parallels SQL Admin</b><br>"
            f"Версия {APP_VERSION}<br><br>"
            "Администрирование MySQL и MSSQL серверов: проверка настроек, "
            "поиск БД, SQL-консоль, экспорт результатов.",
        )

    def closeEvent(self, event):
        self.shutdown()
        event.accept()

    def _update_elapsed(self):

        if self._started_at is None:
            return

        seconds = int(
            time.perf_counter() - self._started_at
        )

        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60

        self.lbl_elapsed_value.setText(
            f"{h:02}:{m:02}:{s:02}"
        )
