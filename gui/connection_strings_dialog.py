"""
gui/connection_strings_dialog.py

Диалог импорта/экспорта серверов в виде строк подключения
(URI-стиль, одна строка на сервер).

Формат:

    engine://user:password@host:port

    Примеры:
        mysql://root:secret@db.example.com:3306
        mssql://sa:Passw0rd@sql.corp.local:1433
        pgsql://postgres:my@pass@pg.example.com:5432

Импорт: вставьте строки (по одной на сервер) либо загрузите из
файла .txt/.uri, укажите действие при совпадении хоста
(пропустить/заменить) и добавьте серверы в реестр.

Экспорт: список серверов реестра показывается сгенерированными
строками подключения; можно скопировать в буфер обмена либо
сохранить в файл.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from common.connection_string import (
    format_connection_string,
    parse_connection_string,
)
from common.server_registry import ServerSpec, registry
from gui import styles as theme_styles
from gui.widgets.copyable_alert import CopyableMessageBox


class ConnectionStringsDialog(QDialog):

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.setWindowTitle("Строки подключения")
        self.resize(640, 460)

        self._build_ui()

        theme_styles.register_theme_listener(self._refresh_theme)
        theme_styles.apply_window_appearance(self)

    # ----------------------------------------------------------
    # UI
    # ----------------------------------------------------------

    def _refresh_theme(self) -> None:
        self.setStyleSheet(theme_styles.dialog_stylesheet())
        theme_styles.apply_window_appearance(self)

    def _build_ui(self) -> None:
        self.setStyleSheet(theme_styles.dialog_stylesheet())

        layout = QVBoxLayout(self)

        title = QLabel("Импорт/экспорт строк подключения")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_import_tab(), "Импорт")
        self.tabs.addTab(self._build_export_tab(), "Экспорт")
        layout.addWidget(self.tabs, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.btn_close = QPushButton("Закрыть")
        self.btn_close.setObjectName("btn_primary")
        self.btn_close.clicked.connect(self.accept)
        buttons.addWidget(self.btn_close)
        layout.addLayout(buttons)

    # ----------------------------------------------------------
    # Импорт
    # ----------------------------------------------------------

    def _build_import_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        hint = QLabel(
            "Формат: engine://user:password@host:port — по одной строке "
            "на сервер.\n"
            "Поддерживаются алиасы движков (sqlserver = mssql, "
            "postgres = pgsql) и параметры после порта "
            "(;connection_timeout=30 и ?key=value игнорируются).\n"
            "Примеры:\n"
            "  mysql://root:secret@db.example.com:3306\n"
            "  mssql://sa:Passw0rd@sql.corp.local:1433\n"
            "  sqlserver://sa:pw@10.0.0.5:1433;connection_timeout=30\n"
            "  pgsql://postgres:my@pass@pg.example.com:5432"
        )
        hint.setWordWrap(True)
        hint.setObjectName("MutedLabel")
        layout.addWidget(hint)

        self.ed_import = QPlainTextEdit()
        self.ed_import.setPlaceholderText(
            "Вставьте строки подключения здесь или загрузите из файла…"
        )
        self.ed_import.setAcceptDrops(False)
        layout.addWidget(self.ed_import, 1)

        row = QHBoxLayout()
        row.setSpacing(8)

        self.chk_replace = QCheckBox("Заменить существующие (по хосту)")
        self.chk_replace.setFixedHeight(26)
        row.addWidget(self.chk_replace)

        row.addStretch()

        self.btn_load_file = QPushButton("Загрузить из файла…")
        self.btn_load_file.clicked.connect(self._import_from_file)
        row.addWidget(self.btn_load_file)

        self.btn_import = QPushButton("Импортировать")
        self.btn_import.setObjectName("btn_primary")
        self.btn_import.clicked.connect(self._do_import)
        row.addWidget(self.btn_import)

        layout.addLayout(row)

        return tab

    def _import_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Загрузить строки подключения",
            "",
            "Строки подключения (*.txt *.uri);;Все файлы (*)",
        )
        if not path:
            return

        try:
            content = Path(path).read_text(encoding="utf-8")
        except OSError as ex:
            CopyableMessageBox.warning(self, "Импорт", f"Не удалось прочитать файл: {ex}")
            return

        self.ed_import.setPlainText(content)

    def _do_import(self) -> None:
        text = self.ed_import.toPlainText()
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

        if not lines:
            CopyableMessageBox.warning(self, "Импорт", "Введите строки подключения.")
            return

        replace = self.chk_replace.isChecked()
        specs: list[ServerSpec] = []
        errors: list[str] = []
        skipped = 0

        for idx, line in enumerate(lines, 1):
            try:
                spec = parse_connection_string(line)
            except ValueError as ex:
                errors.append(f"Строка {idx}: {ex}")
                continue

            if not replace and registry.find(spec.host_key()) is not None:
                skipped += 1
                continue

            specs.append(spec)

        if not specs and not errors:
            CopyableMessageBox.information(
                self,
                "Импорт",
                "Все серверы уже существуют. Используйте «Заменить "
                "существующие», чтобы обновить их.",
            )
            return

        if specs:
            current = registry.specs()

            if replace:
                current = [
                    s for s in current if s.host not in {x.host for x in specs}
                ]

            current.extend(specs)
            registry.save(current)

        parts = [f"Добавлено: {len(specs)}"]
        if replace:
            parts.append("с заменой по хосту")
        if skipped:
            parts.append(f"пропущено совпадений: {skipped}")
        if errors:
            parts.append(f"ошибок: {len(errors)}")

        summary = f"Импорт завершён. {', '.join(parts)}."

        if errors:
            CopyableMessageBox.warning(self, "Импорт", summary + "\n\n" + "\n".join(errors))
        else:
            CopyableMessageBox.information(self, "Импорт", summary)

        self.accept()

    # ----------------------------------------------------------
    # Экспорт
    # ----------------------------------------------------------

    def _build_export_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        hint = QLabel(
            "Серверы реестра в виде строк подключения "
            "(engine://user:password@host:port)."
        )
        hint.setObjectName("MutedLabel")
        layout.addWidget(hint)

        self.ed_export = QPlainTextEdit()
        self.ed_export.setReadOnly(True)
        layout.addWidget(self.ed_export, 1)

        row = QHBoxLayout()
        row.setSpacing(8)

        self.btn_copy = QPushButton("Копировать в буфер")
        self.btn_copy.clicked.connect(self._copy_export)
        row.addWidget(self.btn_copy)

        row.addStretch()

        self.btn_save_file = QPushButton("Сохранить в файл…")
        self.btn_save_file.setObjectName("btn_primary")
        self.btn_save_file.clicked.connect(self._export_to_file)
        row.addWidget(self.btn_save_file)

        layout.addLayout(row)

        self._fill_export()

        return tab

    def _export_lines(self) -> list[str]:
        return [
            format_connection_string(spec)
            for spec in registry.specs()
            if spec.host
        ]

    def _fill_export(self) -> None:
        self.ed_export.setPlainText("\n".join(self._export_lines()))

    def _copy_export(self) -> None:
        text = self.ed_export.toPlainText().strip()

        if not text:
            CopyableMessageBox.information(self, "Экспорт", "Нет серверов для экспорта.")
            return

        QApplication.instance().clipboard().setText(text)
        CopyableMessageBox.information(
            self,
            "Экспорт",
            f"Скопировано строк: {len(text.splitlines())}.",
        )

    def _export_to_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить строки подключения",
            "connections.uri",
            "Строки подключения (*.uri *.txt);;Все файлы (*)",
        )
        if not path:
            return

        text = self.ed_export.toPlainText().strip()

        try:
            Path(path).write_text(text + ("\n" if text else ""), encoding="utf-8")
        except OSError as ex:
            CopyableMessageBox.warning(self, "Экспорт", f"Не удалось сохранить файл: {ex}")
            return

        CopyableMessageBox.information(
            self,
            "Экспорт",
            f"Сохранено строк: {len(text.splitlines())}.\nФайл: {path}",
        )