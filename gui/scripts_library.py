"""
gui/scripts_library.py

Библиотека скриптов: список сохранённых SQL-шаблонов + редактор.

Скрипт «Проверка cfg_settings» используется check-процессом — он отдаётся
в build_scan_query через sql_builder. Остальные скрипты можно создавать,
дублировать и запускать тем же образом.

Персистентность — JSON-файл в каталоге данных приложения (common/paths.app_data_dir):
scripts.json. При первом запуске библиотека заполняется
скриптом проверки по умолчанию.
"""

from __future__ import annotations

import json
import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from common.sql_builder import DEFAULT_SCAN_TEMPLATE
from common.paths import app_data_dir
from gui.icons import icon
from gui.widgets.help_icon import HelpIcon
from gui.widgets.copyable_alert import CopyableMessageBox

DATA_DIR = app_data_dir()
SCRIPTS_FILE = DATA_DIR / "scripts.json"

DEFAULT_SCRIPT_NAME = "Проверка cfg_settings"

DEFAULT_FINALITY_STATES_SCRIPT_NAME = (
    "Финальность состояний позиций (Возврат от клиента / поставщику)"
)

DEFAULT_FINALITY_STATES_SCRIPT = """SELECT
    stt_id, stt_name, stt_archive, stt_archive_restriction
FROM
    order_states
WHERE
    LOWER(stt_name) IN ('возврат от клиента', 'возврат поставщику');

UPDATE
    order_states
SET
    stt_archive = 'Y'
WHERE
    LOWER(stt_name) IN ('возврат от клиента', 'возврат поставщику');

SELECT
    stt_id, stt_name, stt_archive, stt_archive_restriction
FROM
    order_states
WHERE
    LOWER(stt_name) IN ('возврат от клиента', 'возврат поставщику');"""


class ScriptStore:
    """Загрузка и сохранение библиотеки скриптов (scripts.json).

    Используется как самим ScriptsLibrary, так и меню приложения и
    вкладками скриптов (не зависят от виджета-библиотеки).
    """

    def __init__(self) -> None:
        self._scripts: list[dict] = []
        self.load_scripts()

    def load_scripts(self) -> None:
        self._scripts = []
        if SCRIPTS_FILE.exists():
            try:
                data = json.loads(SCRIPTS_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._scripts = [
                        s for s in data
                        if isinstance(s, dict) and s.get("name")
                        and isinstance(s.get("body"), str)
                    ]
            except (OSError, json.JSONDecodeError):
                self._scripts = []
        if not self._scripts:
            self._scripts = [
                {"name": DEFAULT_SCRIPT_NAME, "body": DEFAULT_SCAN_TEMPLATE},
                {
                    "name": DEFAULT_FINALITY_STATES_SCRIPT_NAME,
                    "body": DEFAULT_FINALITY_STATES_SCRIPT,
                },
            ]
            self.save_scripts()

    def save_scripts(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            tmp = SCRIPTS_FILE.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(self._scripts, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, SCRIPTS_FILE)
        except OSError:
            pass

    def script_items(self) -> list[dict]:
        """Копия списка скриптов {name, body} для меню и вкладок."""
        return [dict(s) for s in self._scripts]

    def update_script(self, name: str, body: str) -> bool:
        """Перезаписывает тело скрипта по имени. True — скрипт найден."""
        for script in self._scripts:
            if script["name"] == name:
                script["body"] = body
                self.save_scripts()
                return True
        return False


class ScriptsLibrary(QWidget):
    """Список скриптов слева, редактор справа, запуск текущего скрипта."""

    runRequested = Signal(str)      # запустить check со скриптом (body)
    clearLogRequested = Signal()
    renamed = Signal(str, str)      # (old_name, new_name)

    def __init__(self, parent=None, show_query_log: bool = True) -> None:
        super().__init__(parent)
        self._show_query_log = show_query_log
        self.store = ScriptStore()
        self._scripts = self.store._scripts
        self._current = -1
        self._dirty = False

        self._build_ui()
        self.load_scripts()
        self._select(0)

    # ----------------------------------------------------------
    # UI
    # ----------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QHBoxLayout()

        self.lbl_title = QLabel("Библиотека скриптов")
        self.lbl_title.setObjectName("SectionTitle")
        header.addWidget(self.lbl_title)

        header.addStretch()

        self.ed_search = QLineEdit()
        self.ed_search.setObjectName("SearchField")
        self.ed_search.setPlaceholderText("Поиск скрипта…")
        self.ed_search.setClearButtonEnabled(True)
        self.ed_search.setFixedWidth(200)
        self.ed_search.textChanged.connect(self._filter)
        header.addWidget(self.ed_search)

        layout.addLayout(header)

        body = QSplitter(Qt.Horizontal)
        body.setHandleWidth(6)

        # --- Левая колонка: список + действия ---
        list_card = QFrame()
        list_card.setObjectName("ScriptsListCard")
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(6)

        self.list = QListWidget()
        self.list.setObjectName("ScriptsList")
        self.list.setMinimumWidth(180)
        self.list.currentRowChanged.connect(self._on_selected)
        list_layout.addWidget(self.list, 1)

        actions = QHBoxLayout()
        actions.setSpacing(6)

        self.btn_add = QToolButton()
        self.btn_add.setObjectName("btn_icon")
        self.btn_add.setIcon(icon("add", 16, "@icon_accent"))
        self.btn_add.setIconSize(QSize(16, 16))
        self.btn_add.setToolTip("Новый скрипт")
        self.btn_add.clicked.connect(self._add_script)

        self.btn_rename = QToolButton()
        self.btn_rename.setObjectName("btn_icon")
        self.btn_rename.setIcon(icon("edit", 16, "@icon_muted"))
        self.btn_rename.setIconSize(QSize(16, 16))
        self.btn_rename.setToolTip("Переименовать скрипт")
        self.btn_rename.clicked.connect(self._rename_script)

        self.btn_duplicate = QToolButton()
        self.btn_duplicate.setObjectName("btn_icon")
        self.btn_duplicate.setIcon(icon("content_copy", 16, "@icon_muted"))
        self.btn_duplicate.setIconSize(QSize(16, 16))
        self.btn_duplicate.setToolTip("Дублировать скрипт")
        self.btn_duplicate.clicked.connect(self._duplicate_script)

        self.btn_delete = QToolButton()
        self.btn_delete.setObjectName("btn_icon")
        self.btn_delete.setIcon(icon("delete_outline", 16, "@icon_danger"))
        self.btn_delete.setIconSize(QSize(16, 16))
        self.btn_delete.setToolTip("Удалить скрипт")
        self.btn_delete.clicked.connect(self._delete_script)

        actions.addWidget(self.btn_add)
        actions.addWidget(self.btn_rename)
        actions.addWidget(self.btn_duplicate)
        actions.addWidget(self.btn_delete)
        actions.addStretch()

        list_layout.addLayout(actions)

        body.addWidget(list_card)

        # --- Правая колонка: редактор ---
        editor_card = QFrame()
        editor_card.setObjectName("ScriptsListCard")
        editor_layout = QVBoxLayout(editor_card)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(6)

        name_row = QHBoxLayout()
        name_row.setSpacing(4)
        name_row.setContentsMargins(0, 0, 0, 0)

        self.lbl_script_name = QLabel("")
        self.lbl_script_name.setObjectName("InlineLabel")
        self.lbl_script_name.setMouseTracking(True)
        self.lbl_script_name.mouseDoubleClickEvent = (
            lambda _: self._rename_script()
        )
        name_row.addWidget(self.lbl_script_name)
        name_row.addStretch()
        name_row.addWidget(
            HelpIcon(
                "Плейсхолдеры: {db} — имя БД без экранирования; "
                "{dbq} — имя БД в обратных кавычках; "
                "{table} — таблица настроек; {country} — имя настройки "
                "страны; {target} — имя целевой настройки."
            )
        )
        editor_layout.addLayout(name_row)

        self.editor = QPlainTextEdit()
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        console_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        console_font.setPointSize(12)
        self.editor.setFont(console_font)
        self.editor.setPlaceholderText("SQL-шаблон…")
        self.editor.textChanged.connect(self._on_editor_changed)
        editor_layout.addWidget(self.editor, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()

        self.btn_save = QPushButton("Сохранить")
        self.btn_save.setIcon(icon("save", 16, "@icon_fg"))
        self.btn_save.clicked.connect(self._save_current)

        self.btn_run = QPushButton("Запустить")
        self.btn_run.setObjectName("btn_primary")
        self.btn_run.setIcon(icon("play_arrow", 16, "#ffffff"))
        self.btn_run.clicked.connect(self._run)

        buttons.addWidget(self.btn_save)
        buttons.addWidget(self.btn_run)

        editor_layout.addLayout(buttons)

        body.addWidget(editor_card)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setSizes([240, 640])

        layout.addWidget(body, 1)

        # --- Журнал запросов ---
        if self._show_query_log:
            log_header = QHBoxLayout()

            self.lbl_log_title = QLabel("Журнал запросов")
            self.lbl_log_title.setObjectName("SectionTitle")
            log_header.addWidget(self.lbl_log_title)

            log_header.addStretch()

            self.btn_log_clear = QToolButton()
            self.btn_log_clear.setObjectName("btn_icon")
            self.btn_log_clear.setIcon(icon("delete_outline"))
            self.btn_log_clear.setIconSize(QSize(16, 16))
            self.btn_log_clear.setToolTip("Очистить журнал запросов")
            self.btn_log_clear.clicked.connect(self.clearLogRequested)
            log_header.addWidget(self.btn_log_clear)

            layout.addLayout(log_header)

            self.log = QPlainTextEdit()
            self.log.setReadOnly(True)
            self.log.setMaximumBlockCount(2000)
            self.log.setFixedHeight(96)
            layout.addWidget(self.log)

        self.save_shortcut = QShortcut(
            QKeySequence(Qt.CTRL | Qt.Key_S), self
        )
        self.save_shortcut.activated.connect(self._save_current)

        self.run_shortcut = QShortcut(
            QKeySequence(Qt.CTRL | Qt.Key_Return), self
        )
        self.run_shortcut.activated.connect(self._run)

    # ----------------------------------------------------------
    # Персистентность
    # ----------------------------------------------------------

    def load_scripts(self) -> None:
        self.store.load_scripts()
        self._scripts = self.store._scripts
        self._rebuild_list()

    def save_scripts(self) -> None:
        self.store.save_scripts()

    def script_items(self) -> list[dict]:
        return self.store.script_items()

    def update_script(self, name: str, body: str) -> bool:
        return self.store.update_script(name, body)

    def current_body(self) -> str:
        if 0 <= self._current < len(self._scripts):
            return self._scripts[self._current]["body"]
        return ""

    def set_running(self, running: bool) -> None:
        self.btn_run.setEnabled(not running)
        self.btn_run.setText("Запустить" if not running else "Выполняется…")

    def retheme_icons(self) -> None:
        self.btn_add.setIcon(icon("add", 16, "@icon_accent"))
        self.btn_duplicate.setIcon(icon("content_copy", 16, "@icon_muted"))
        self.btn_delete.setIcon(icon("delete_outline", 16, "@icon_danger"))
        if self._show_query_log:
            self.btn_log_clear.setIcon(icon("delete_outline"))
        self.btn_save.setIcon(icon("save", 16, "@icon_fg"))
        self.btn_run.setIcon(icon("play_arrow", 16, "#ffffff"))

    def append_query(self, text: str) -> None:
        if not self._show_query_log:
            return
        from datetime import datetime
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{stamp}] {text}")

    # ----------------------------------------------------------
    # Внутренние операции
    # ----------------------------------------------------------

    def _rebuild_list(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for script in self._scripts:
            self.list.addItem(QListWidgetItem(script["name"]))
        self.list.blockSignals(False)

    def _select(self, index: int) -> None:
        if 0 <= index < self.list.count():
            self.list.setCurrentRow(index)
        else:
            self._on_selected(-1)

    def _on_selected(self, row: int) -> None:
        if self._dirty and self._current >= 0:
            if not self._confirm_save_if_dirty():
                self.list.blockSignals(True)
                self.list.setCurrentRow(self._current)
                self.list.blockSignals(False)
                return
        self._current = row
        self._dirty = False
        if 0 <= row < len(self._scripts):
            script = self._scripts[row]
            self.editor.blockSignals(True)
            self.editor.setPlainText(script["body"])
            self.editor.blockSignals(False)
            self.lbl_script_name.setText(script["name"])
            self.editor.setEnabled(True)
            self.btn_run.setEnabled(True)
        else:
            self.editor.clear()
            self.editor.setEnabled(False)
            self.btn_run.setEnabled(False)
            self.lbl_script_name.setText("")

    def _on_editor_changed(self) -> None:
        if self._current < 0:
            return
        body = self.editor.toPlainText()
        if body != self._scripts[self._current]["body"]:
            self._dirty = True
            self.lbl_script_name.setText(
                self._scripts[self._current]["name"] + " *"
            )

    def _filter(self, text: str) -> None:
        text = text.strip().lower()
        for row in range(self.list.count()):
            item = self.list.item(row)
            item.setHidden(bool(text) and text not in item.text().lower())

    def _current_item(self):
        return self.list.item(self._current)

    def _add_script(self) -> None:
        if self._dirty and not self._confirm_save_if_dirty():
            return
        name, ok = QInputDialog.getText(
            self, "Новый скрипт", "Имя скрипта:"
        )
        if not ok or not name.strip():
            return
        name = self._unique_name(name.strip())
        self._scripts.append({"name": name, "body": ""})
        self._dirty = False
        self.save_scripts()
        self._rebuild_list()
        self._select(len(self._scripts) - 1)
        self._dirty = True

    def _rename_script(self) -> None:
        if self._current < 0:
            return
        old_name = self._scripts[self._current]["name"]
        new_name, ok = QInputDialog.getText(
            self, "Переименовать скрипт", "Имя:", text=old_name,
        )
        if not ok or not new_name.strip() or new_name == old_name:
            return
        new_name = new_name.strip()
        names = {s["name"] for s in self._scripts}
        if new_name in names:
            CopyableMessageBox.warning(
                self, "Ошибка",
                f"Скрипт «{new_name}» уже существует.",
            )
            return
        self._scripts[self._current]["name"] = new_name
        self.save_scripts()
        self.lbl_script_name.setText(new_name)
        self._rebuild_list()
        self._select(self._current)
        self.renamed.emit(old_name, new_name)

    def _duplicate_script(self) -> None:
        if self._current < 0:
            return
        if self._dirty and not self._confirm_save_if_dirty():
            return
        src = self._scripts[self._current]
        name = self._unique_name(src["name"] + " — копия")
        self._scripts.append({"name": name, "body": src["body"]})
        self._dirty = False
        self.save_scripts()
        self._rebuild_list()
        self._select(len(self._scripts) - 1)

    def _delete_script(self) -> None:
        if self._current < 0:
            return
        name = self._scripts[self._current]["name"]
        answer = CopyableMessageBox.question(
            self,
            "Удалить скрипт",
            f"Удалить скрипт «{name}»?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        del self._scripts[self._current]
        self._dirty = False
        self.save_scripts()
        self._rebuild_list()
        self._select(max(0, min(self._current, len(self._scripts) - 1)))

    def _save_current(self) -> None:
        if self._current < 0:
            return
        body = self.editor.toPlainText()
        self._scripts[self._current]["body"] = body
        self._dirty = False
        self.save_scripts()
        self.lbl_script_name.setText(self._scripts[self._current]["name"])
        item = self._current_item()
        if item is not None:
            item.setText(self._scripts[self._current]["name"])

    def _confirm_save_if_dirty(self) -> bool:
        """Спрашивает про несохранённые изменения. True — можно уходить."""
        answer = CopyableMessageBox.question(
            self,
            "Несохранённые изменения",
            f"Сохранить изменения скрипта "
            f"«{self._scripts[self._current]['name']}»?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Save:
            self._save_current()
            return True
        if answer == QMessageBox.Discard:
            self._dirty = False
            return True
        return False

    def _unique_name(self, base: str) -> str:
        names = {s["name"] for s in self._scripts}
        if base not in names:
            return base
        i = 2
        while f"{base} {i}" in names:
            i += 1
        return f"{base} {i}"

    def _run(self) -> None:
        if self._current < 0:
            return
        self.runRequested.emit(self.editor.toPlainText())
