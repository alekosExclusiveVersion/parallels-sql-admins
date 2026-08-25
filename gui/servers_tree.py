"""
gui/servers_tree.py

Дерево серверов → БД → таблиц с ленивой подгрузкой размеров.

Виджет не знает о деталях движков БД: запросы размеров эмитятся сигналами
(databasesRequested / tablesRequested), а результаты возвращаются
методами apply_sizes() / apply_tables(). Двойной клик по таблице
эмитит tableSelectRequested. Единственное знание о движке — строка
engine ("mysql"/"mssql") в данных узла для выбора фирменной иконки.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
)

from gui.icons import icon

from common.server_registry import (
    ENGINE_MSSQL,
    ENGINE_MYSQL,
    ENGINE_PGSQL,
    registry,
)

_PLACEHOLDER = "…"
_LOADING = "Загрузка…"
_NO_DB = "Нет БД"
_NO_TABLES = "Нет таблиц"

# Роль, в которой хранится отображаемое имя сервера (Name или host).
# В Qt.UserRole всегда остаётся host — по нему работают check/search/консоль.
_DISPLAY_ROLE = Qt.UserRole + 1

# Движок сервера ("mysql"/"mssql") — для выбора фирменной иконки.
_ENGINE_ROLE = Qt.UserRole + 2

# Фирменные цвета движков — токены темы (styles.py), чтобы иконка
# оставалась читаемой и на светлой, и на тёмной теме.
_ENGINE_ICON_COLORS = {
    ENGINE_MYSQL: "@mysql_brand",
    ENGINE_MSSQL: "@mssql_brand",
    ENGINE_PGSQL: "@pgsql_brand",
}

_ENGINE_ICONS = {
    ENGINE_MYSQL: "dns",
    ENGINE_MSSQL: "server",
    ENGINE_PGSQL: "account_tree",
}


class ServersTree(QTreeWidget):
    databasesRequested = Signal(list)        # серверы, для которых нужны размеры БД
    tablesRequested = Signal(str, str)       # server, database
    tableSelectRequested = Signal(str, str, str)  # server, database, table
    selectionChangedNotify = Signal()
    addServerRequested = Signal()
    editServerRequested = Signal(str)        # server
    removeServerRequested = Signal(str)      # server
    dropDatabaseRequested = Signal(str, str)  # server, database

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.setColumnCount(1)
        self.setHeaderHidden(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setRootIsDecorated(True)
        self.setItemsExpandable(True)
        self.setExpandsOnDoubleClick(False)
        self.setIndentation(18)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        # Автосортировка выключена: серверы приходят уже отсортированными
        # (сначала по движку, затем по алфавиту — MainWindow._load_servers),
        # а БД/таблицы сортируются явно после наполнения (sortChildren).
        # По умолчанию QHeaderView сортирует по убыванию — включаем по возрастанию.
        self.setSortingEnabled(False)
        self.header().setSortIndicator(0, Qt.AscendingOrder)

        header = self.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Stretch)

        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

        self.itemExpanded.connect(self._tree_item_expanded)
        self.itemDoubleClicked.connect(self._double_click)
        self.itemSelectionChanged.connect(self.selectionChangedNotify)
        self.customContextMenuRequested.connect(self._context_menu)

        # Кэш таблиц по серверам: {server: {db: [(table, size)]}}.
        # Заполняется при раскрытии сервера одним запросом, чтобы
        # раскрытие БД не требовало отдельного запроса на каждую БД.
        self._tables_cache: dict[str, dict[str, list]] = {}

    # ----------------------------------------------------------
    # Утилиты узлов
    # ----------------------------------------------------------

    @staticmethod
    def server_name(item: QTreeWidgetItem | None) -> str:
        """Host сервера для top-level узла (без суффиксов размера).

        Возвращает host из Qt.UserRole — по нему работают воркеры
        (check/search/консоль), независимо от отображаемого имени.
        """
        if item is None:
            return ""
        return item.data(0, Qt.UserRole) or item.text(0)

    @staticmethod
    def display_name(item: QTreeWidgetItem | None) -> str:
        """Отображаемое имя сервера (Name или host), без суффиксов размера."""
        if item is None:
            return ""
        return (
            item.data(0, _DISPLAY_ROLE)
            or item.data(0, Qt.UserRole)
            or item.text(0)
        )

    @staticmethod
    def db_name(item: QTreeWidgetItem | None) -> str:
        """Имя БД для узла второго уровня."""
        if item is None:
            return ""
        return item.data(0, Qt.UserRole) or item.text(0)

    @staticmethod
    def is_server_item(item: QTreeWidgetItem | None) -> bool:
        return item is not None and item.parent() is None

    @staticmethod
    def is_db_item(item: QTreeWidgetItem | None) -> bool:
        return (
            item is not None
            and item.parent() is not None
            and item.parent().parent() is None
        )

    @staticmethod
    def is_table_item(item: QTreeWidgetItem | None) -> bool:
        """Узел таблицы — третий уровень (сервер → БД → таблица)."""
        return (
            item is not None
            and item.parent() is not None
            and item.parent().parent() is not None
            and item.parent().parent().parent() is None
        )

    def table_name(self, item: QTreeWidgetItem | None) -> str:
        """Имя таблицы для узла третьего уровня (без суффикса размера)."""
        if item is None:
            return ""
        return item.data(0, Qt.UserRole) or item.text(0).split("  (")[0].strip()

    @staticmethod
    def format_size(size_bytes: int) -> str:
        size = float(size_bytes)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    # ----------------------------------------------------------
    # Наполнение
    # ----------------------------------------------------------

    def set_servers(self, servers: list[str] | list[tuple]) -> None:
        """Заполняет дерево серверами.

        Элемент может быть строкой-хостом, парой (display_name, host)
        либо тройкой (display_name, host, engine): display_name показывается
        в списке, host хранится в Qt.UserRole и используется воркерами как
        цель подключения, engine ("mysql"/"mssql") — для фирменной иконки.
        """
        self.clear()

        for entry in servers:
            if isinstance(entry, (tuple, list)):
                display, server = entry[0], entry[1]
                engine = entry[2] if len(entry) > 2 else ""
            else:
                display = server = entry
                engine = ""

            item = QTreeWidgetItem([display])
            item.setData(0, Qt.UserRole, server)
            item.setData(0, _DISPLAY_ROLE, display)
            item.setData(0, _ENGINE_ROLE, engine)
            # Host скрыт из списка, но доступен подсказкой при наведении.
            if server != display:
                item.setToolTip(0, server)
            item.setIcon(0, self._server_icon(item))
            # Заглушка-ребёнок, чтобы у сервера появился маркер раскрытия
            QTreeWidgetItem(item, [_PLACEHOLDER])
            self.addTopLevelItem(item)

    def _server_icon_key(self, item) -> str:
        """Имя иконки для сервера по движку (для тестов)."""
        engine = item.data(0, _ENGINE_ROLE)
        return _ENGINE_ICONS.get(engine, "server")

    def _server_icon(self, item):
        """Иконка сервера: MySQL — dns, PostgreSQL — account_tree,
        MSSQL — server, в фирменном цвете движка."""
        engine = item.data(0, _ENGINE_ROLE)
        color = _ENGINE_ICON_COLORS.get(engine, "@icon_accent")
        icon_name = _ENGINE_ICONS.get(engine, "server")
        return icon(icon_name, 20, color)

    def retheme_icons(self) -> None:
        """Перерисовывает иконки дерева под текущую тему (после смены
        палитры): серверы, БД и таблицы используют токены темы."""
        for i in range(self.topLevelItemCount()):
            srv = self.topLevelItem(i)
            srv.setIcon(0, self._server_icon(srv))
            for d in range(srv.childCount()):
                db = srv.child(d)
                if not self.db_name(db):
                    continue
                db.setIcon(0, icon("storage", 22, "@icon_secondary"))
                for t in range(db.childCount()):
                    table = db.child(t)
                    if self.table_name(table):
                        table.setIcon(0, icon("table", 22, "@icon_success"))

    def selected_servers(self) -> list[str]:
        return [
            self.server_name(item)
            for item in self.selectedItems()
            if self.is_server_item(item)
        ]

    def selected_count(self) -> int:
        return len(self.selected_servers())

    def reset_sizes(self) -> None:
        """Сбрасывает загруженные размеры, чтобы при следующем
        раскрытии узла подтянулись свежие данные."""
        self._tables_cache.clear()

        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            item.setText(0, self.display_name(item))
            item.setIcon(0, self._server_icon(item))
            item.takeChildren()
            QTreeWidgetItem(item, [_PLACEHOLDER])

    def apply_databases(self, server: str, names: list) -> None:
        """Показывает список БД сразу (быстрый SHOW DATABASES),
        без размеров — размеры доносит apply_sizes()."""
        for index in range(self.topLevelItemCount()):
            server_item = self.topLevelItem(index)
            if self.server_name(server_item) != server:
                continue

            server_item.setText(0, self.display_name(server_item))
            server_item.takeChildren()

            if not names:
                QTreeWidgetItem(server_item, [_NO_DB])
                break

            for db_name in names:
                db_item = QTreeWidgetItem(server_item, [db_name])
                db_item.setData(0, Qt.UserRole, db_name)
                db_item.setIcon(0, icon("storage", 22, "@icon_secondary"))
                QTreeWidgetItem(db_item, [_PLACEHOLDER])
            server_item.sortChildren(0, Qt.AscendingOrder)
            break

    def remove_database(self, server: str, database: str) -> None:
        """Удаляет узел БД из дерева (после DROP DATABASE)."""
        for index in range(self.topLevelItemCount()):
            server_item = self.topLevelItem(index)
            if self.server_name(server_item) != server:
                continue

            for child_index in range(server_item.childCount()):
                child = server_item.child(child_index)
                if self.db_name(child) == database:
                    server_item.removeChild(child)
                    break
            break

    def apply_sizes(self, server: str, sizes: dict) -> None:
        """Дописывает размеры к уже показанным узлам БД.

        Если список БД ещё не показан (apply_databases не успел) —
        строит узлы из sizes напрямую.
        """
        for index in range(self.topLevelItemCount()):
            server_item = self.topLevelItem(index)
            if self.server_name(server_item) != server:
                continue

            total = sum(sizes.values())
            server_item.setText(
                0,
                f"{self.display_name(server_item)}  ({self.format_size(total)})",
            )

            placeholder_only = (
                server_item.childCount() == 0
                or (
                    server_item.childCount() == 1
                    and server_item.child(0).text(0)
                    in (_PLACEHOLDER, _LOADING, _NO_DB)
                )
            )

            if placeholder_only:
                server_item.takeChildren()

                if not sizes:
                    QTreeWidgetItem(server_item, [_NO_DB])
                    break

                for db_name, db_size in sizes.items():
                    db_item = QTreeWidgetItem(
                        server_item,
                        [f"{db_name}  ({self.format_size(db_size)})"],
                    )
                    db_item.setData(0, Qt.UserRole, db_name)
                    db_item.setIcon(0, icon("storage", 22, "@icon_secondary"))
                    QTreeWidgetItem(db_item, [_PLACEHOLDER])
                server_item.sortChildren(0, Qt.AscendingOrder)
                break

            for db_index in range(server_item.childCount()):
                db_item = server_item.child(db_index)
                db = self.db_name(db_item)

                if not db or db not in sizes:
                    continue

                db_item.setText(
                    0,
                    f"{db}  ({self.format_size(sizes[db])})",
                )
            break

    def apply_server_tables(self, server: str, tables: dict) -> None:
        """Кэширует таблицы всех БД сервера (получены одним запросом).

        Узлы БД не заполняются сразу — таблицы появятся мгновенно
        при раскрытии БД из кэша, без отдельного запроса.
        """
        self._tables_cache[server] = tables or {}

    def _populate_tables(self, db_item: QTreeWidgetItem, tables: list) -> None:
        db_item.takeChildren()

        if not tables:
            QTreeWidgetItem(db_item, [_NO_TABLES])
            return

        for table_name, table_size in tables:
            table_item = QTreeWidgetItem(
                db_item,
                [f"{table_name}  ({self.format_size(table_size)})"],
            )
            table_item.setData(0, Qt.UserRole, table_name)
            table_item.setIcon(0, icon("table", 22, "@icon_success"))
        db_item.sortChildren(0, Qt.AscendingOrder)

    def apply_tables(self, server: str, database: str, tables: list) -> None:
        for index in range(self.topLevelItemCount()):
            server_item = self.topLevelItem(index)
            if self.server_name(server_item) != server:
                continue

            for db_index in range(server_item.childCount()):
                db_item = server_item.child(db_index)
                if self.db_name(db_item) != database:
                    continue

                self._populate_tables(db_item, tables)
                break
            break

    # ----------------------------------------------------------
    # Фильтрация и выделение
    # ----------------------------------------------------------

    def filter(self, text: str) -> None:
        text = text.lower().strip()
        for index in range(self.topLevelItemCount()):
            self._filter_item(self.topLevelItem(index), text)

    def invert_selection(self) -> None:
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            item.setSelected(not item.isSelected())

    def _filter_item(self, item: QTreeWidgetItem, text: str) -> bool:
        """Рекурсивно показывает/скрывает узлы по вхождению text.

        Возвращает True, если узел (или любой потомок) видим.
        """
        if not text:
            item.setHidden(False)
            for i in range(item.childCount()):
                child = item.child(i)
                child.setHidden(False)
                self._filter_item(child, "")
            return True

        self_match = text in item.text(0).lower()
        child_match = False

        for i in range(item.childCount()):
            if self._filter_item(item.child(i), text):
                child_match = True

        visible = self_match or child_match
        item.setHidden(not visible)
        return visible

    # ----------------------------------------------------------
    # Ленивая загрузка
    # ----------------------------------------------------------

    def _tree_item_expanded(self, item: QTreeWidgetItem) -> None:
        if self.is_server_item(item):
            self._load_server_children(item)
        elif self.is_db_item(item):
            self._load_db_children(item)

    def _load_server_children(self, item: QTreeWidgetItem) -> None:
        if not self._needs_load(item):
            return
        server = self.server_name(item)
        self.databasesRequested.emit([server])

    def _load_db_children(self, item: QTreeWidgetItem) -> None:
        if not self._needs_load(item):
            return

        server = self.server_name(item.parent())
        database = self.db_name(item)

        # Таблицы БД уже получены при раскрытии сервера — показываем
        # мгновенно, без запроса.
        cached = self._tables_cache.get(server, {}).get(database)
        if cached is not None:
            self._populate_tables(item, cached)
            return

        self.tablesRequested.emit(server, database)

    def _needs_load(self, item: QTreeWidgetItem) -> bool:
        """True, если узел ещё не загружался (содержит заглушку «…»)."""
        if item.childCount() == 1 and item.child(0).text(0) == _PLACEHOLDER:
            item.takeChildren()
            placeholder = QTreeWidgetItem(item, [_LOADING])
            placeholder.setDisabled(True)
            return True
        return False

    def _context_menu(self, pos) -> None:
        """Контекстное меню: добавить/редактировать/удалить сервер."""
        menu = QMenu(self)

        item = self.itemAt(pos)

        action_add = menu.addAction(icon("add", 16, "@icon_accent"), "Добавить сервер")
        action_add.triggered.connect(self.addServerRequested)

        if item is not None and self.is_server_item(item):
            server = self.server_name(item)
            label = self.display_name(item)

            action_edit = menu.addAction(
                icon("edit", 16, "@icon_muted"),
                f"Изменить «{label}»",
            )
            action_edit.triggered.connect(
                lambda: self.editServerRequested.emit(server)
            )

            action_remove = menu.addAction(
                icon("delete_outline", 16, "@icon_danger"),
                f"Удалить «{label}»",
            )
            action_remove.triggered.connect(
                lambda: self.removeServerRequested.emit(server)
            )

        if item is not None and self.is_db_item(item):
            server = self.server_name(item.parent())
            database = self.db_name(item)
            engine = registry.engine(server)

            if engine in (ENGINE_MSSQL, ENGINE_PGSQL):
                action_drop = menu.addAction(
                    icon("delete_outline", 16, "@icon_danger"),
                    f"Удалить БД «{database}»",
                )
                action_drop.triggered.connect(
                    lambda s=server, d=database: self.dropDatabaseRequested.emit(s, d)
                )

        menu.exec(self.viewport().mapToGlobal(pos))

    def _double_click(self, item: QTreeWidgetItem) -> None:
        """Двойной клик: на таблице — SELECT *, на сервере/БД — раскрытие."""
        if self.is_table_item(item):
            server = self.server_name(item.parent().parent())
            database = self.db_name(item.parent())
            table = self.table_name(item)

            if not server or not database or not table:
                return

            self.tableSelectRequested.emit(server, database, table)
            return

        # Сервер или БД — вручную раскрыть/свернуть узел
        if item.isExpanded():
            item.setExpanded(False)
        else:
            item.setExpanded(True)
            self._tree_item_expanded(item)
