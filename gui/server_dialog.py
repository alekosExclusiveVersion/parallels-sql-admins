"""
gui/server_dialog.py

Диалог добавления/редактирования сервера (MySQL/MSSQL).

Поля: имя, хост, порт, движок, логин, пароль. Пароль опционален
(может остаться пустым — тогда при подключении берётся глобальный
из config.ini). Кнопка «Test Connection» проверяет подключение
в фоновом потоке с введёнными реквизитами.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtCore import QObject, Signal

from common.server_registry import (
    ENGINE_MSSQL,
    ENGINE_MYSQL,
    ENGINE_PGSQL,
    ENGINE_SQLITE,
    ServerSpec,
    default_port,
)
from gui import styles as theme_styles
from gui.widgets.help_icon import HelpIcon
from gui.worker_thread import WorkerHost


class _TestWorker(QObject):
    finished = Signal(bool, str, str)

    def run(self):
        from common.mssql_client import mssql
        from common.mysql_client import mysql
        from common.pgsql_client import pgsql
        from common.sqlite_client import sqlite

        if self._engine == ENGINE_MSSQL:
            client = mssql
        elif self._engine == ENGINE_PGSQL:
            client = pgsql
        elif self._engine == ENGINE_SQLITE:
            client = sqlite
        else:
            client = mysql
        ok, message = client.test_connection(
            self._host,
            self._port,
            self._user,
            self._password,
        )
        version = ""
        if ok:
            version = client.server_info(
                self._host,
                self._port,
                self._user,
                self._password,
            )
        self.finished.emit(ok, message, version)

    def set_request(self, host, port, engine, user, password):
        self._host = host
        self._port = port
        self._engine = engine
        self._user = user
        self._password = password


class ServerDialog(QDialog):

    def __init__(self, spec: ServerSpec | None = None, parent=None) -> None:
        super().__init__(parent)

        self._spec = spec

        self.setWindowTitle(
            "Изменить сервер" if spec is not None else "Добавить сервер"
        )
        self.setMinimumWidth(380)
        self._test_host = None

        self._build_ui()

        if spec is not None:
            self._load_spec(spec)

        theme_styles.register_theme_listener(self._refresh_theme)

        theme_styles.apply_window_appearance(self)

    # ----------------------------------------------------------
    # UI
    # ----------------------------------------------------------

    def _refresh_theme(self) -> None:
        self.setStyleSheet(theme_styles.dialog_stylesheet())
        theme_styles.apply_window_appearance(self)

    def _field_label(self, text: str, help_text: str = "") -> QWidget:
        """Лейбл поля формы; при наличии help_text — с иконкой «?»."""
        row = QHBoxLayout()
        row.setSpacing(4)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel(text))
        if help_text:
            row.addWidget(HelpIcon(help_text))
        row.addStretch()
        container = QWidget()
        container.setLayout(row)
        return container

    def _build_ui(self) -> None:
        self.setStyleSheet(theme_styles.dialog_stylesheet())

        layout = QVBoxLayout(self)

        title = QLabel(
            "Изменить сервер" if self._spec is not None else "Добавить сервер"
        )
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        form = QFormLayout()

        self.ed_name = QLineEdit()
        form.addRow(
            self._field_label(
                "Имя:",
                "Необязательно. Если не заполнено, в списке "
                "отображается хост.",
            ),
            self.ed_name,
        )

        self.ed_host = QLineEdit()
        form.addRow(
            self._field_label("Хост:", "Пример: db.example.com"),
            self.ed_host,
        )

        self.cb_engine = QComboBox()
        self.cb_engine.addItem("MySQL", ENGINE_MYSQL)
        self.cb_engine.addItem("MSSQL", ENGINE_MSSQL)
        self.cb_engine.addItem("PostgreSQL", ENGINE_PGSQL)
        self.cb_engine.addItem("SQLite", ENGINE_SQLITE)
        form.addRow("Движок:", self.cb_engine)

        self.sp_port = QSpinBox()
        self.sp_port.setRange(1, 65535)
        form.addRow("Порт:", self.sp_port)

        self.ed_user = QLineEdit()
        form.addRow("Логин:", self.ed_user)

        self.ed_password = QLineEdit()
        self.ed_password.setEchoMode(QLineEdit.Password)

        self.chk_show_password = QCheckBox("Показать")
        password_row = QHBoxLayout()
        password_row.addWidget(self.ed_password, 1)
        password_row.addWidget(self.chk_show_password)
        form.addRow("Пароль:", password_row)

        layout.addLayout(form)

        buttons = QHBoxLayout()

        self.btn_test = QPushButton("Проверить соединение")
        buttons.addWidget(self.btn_test)
        buttons.addStretch()

        self.btn_cancel = QPushButton("Отмена")
        buttons.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("Сохранить")
        self.btn_save.setObjectName("btn_primary")
        buttons.addWidget(self.btn_save)

        layout.addLayout(buttons)

        # ----------------------------------------------------------
        # Signals
        # ----------------------------------------------------------

        self.cb_engine.currentIndexChanged.connect(self._engine_changed)
        self.chk_show_password.toggled.connect(self._toggle_password)
        self.btn_test.clicked.connect(self._test)
        self.btn_save.clicked.connect(self._accept)
        self.btn_cancel.clicked.connect(self.reject)
        self.ed_host.returnPressed.connect(self._accept)
        self.ed_password.returnPressed.connect(self._accept)

        self._engine_changed()

    def _load_spec(self, spec: ServerSpec) -> None:
        self.ed_name.setText(spec.name)
        self.ed_host.setText(spec.host)
        index = self.cb_engine.findData(spec.engine)
        if index >= 0:
            self.cb_engine.setCurrentIndex(index)
        self.sp_port.setValue(spec.port)
        self.ed_user.setText(spec.user)
        self.ed_password.setText(spec.password)

    def _engine_changed(self) -> None:
        engine = self.cb_engine.currentData()
        self.sp_port.setValue(default_port(engine))
        is_sqlite = engine == ENGINE_SQLITE
        self.sp_port.setVisible(not is_sqlite)
        self.ed_user.setVisible(not is_sqlite)
        self.ed_password.setVisible(not is_sqlite)
        self.chk_show_password.setVisible(not is_sqlite)
        if is_sqlite:
            self.ed_host.setPlaceholderText("/path/to/database.db")
        else:
            self.ed_host.setPlaceholderText("")

    def _toggle_password(self, checked: bool) -> None:
        self.ed_password.setEchoMode(
            QLineEdit.Normal if checked else QLineEdit.Password
        )

    # ----------------------------------------------------------
    # Test connection
    # ----------------------------------------------------------

    def _test(self) -> None:
        host = self.ed_host.text().strip()

        if not host:
            self._show_error("Укажите хост сервера.")
            return

        if self._test_host is not None and self._test_host.thread.isRunning():
            return

        self.btn_test.setEnabled(False)
        self.btn_test.setText("Проверка...")

        host = WorkerHost(_TestWorker, self)
        self._test_host = host

        host.worker.set_request(
            self.ed_host.text().strip(),
            self.sp_port.value(),
            self.cb_engine.currentData(),
            self.ed_user.text(),
            self.ed_password.text(),
        )
        host.worker.finished.connect(self._on_test_finished)
        host.thread.start()

    def _on_test_finished(self, ok: bool, message: str, version: str) -> None:
        self.btn_test.setEnabled(True)
        self.btn_test.setText("Проверить соединение")
        self._test_host = None

        if ok:
            text = "Connection successful."
            if version:
                text += f"\n\nСервер: {version}"
            QMessageBox.information(
                self,
                "Test Connection",
                text,
            )
        else:
            QMessageBox.warning(
                self,
                "Test Connection",
                f"Connection failed: {message}",
            )

    # ----------------------------------------------------------
    # Accept
    # ----------------------------------------------------------

    def spec(self) -> ServerSpec:
        return ServerSpec(
            name=self.ed_name.text().strip(),
            host=self.ed_host.text().strip(),
            engine=self.cb_engine.currentData(),
            port=self.sp_port.value(),
            user=self.ed_user.text(),
            password=self.ed_password.text(),
        )

    def _accept(self) -> None:
        if not self.ed_host.text().strip():
            self._show_error("Enter the server host.")
            return

        if not self.ed_user.text().strip():
            self._show_error("Enter the user for the server.")
            return

        self.accept()

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(
            self,
            "Server",
            message,
        )
