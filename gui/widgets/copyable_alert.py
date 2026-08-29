"""Стилизованное модальное окно-алерт с копируемым текстом сообщения.

Заменяет нативные QMessageBox (в них нельзя выделить/скопировать текст и не
применяется QSS темы). Возвращает значения QMessageBox.StandardButton, чтобы
сравнения вида `answer == QMessageBox.Yes` продолжали работать.
"""

from __future__ import annotations

import re
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from gui import styles as theme_styles
from gui.icons import icon

_BUTTON_LABELS = {
    QMessageBox.StandardButton.Yes: "Да",
    QMessageBox.StandardButton.No: "Нет",
    QMessageBox.StandardButton.Ok: "ОК",
    QMessageBox.StandardButton.Cancel: "Отмена",
    QMessageBox.StandardButton.Save: "Сохранить",
    QMessageBox.StandardButton.Discard: "Не сохранять",
}

_STANDARD_ORDER = [
    QMessageBox.StandardButton.Yes,
    QMessageBox.StandardButton.No,
    QMessageBox.StandardButton.Save,
    QMessageBox.StandardButton.Discard,
    QMessageBox.StandardButton.Cancel,
    QMessageBox.StandardButton.Ok,
]

_SEVERITY = {
    "critical": ("error", "@icon_danger"),
    "warning": ("warning", "@icon_warning"),
    "information": ("info_outline", "@icon_accent"),
    "question": ("help", "@icon_accent"),
}

_HTML_RE = re.compile(r"<[a-z]")


class CopyableMessageBox(QDialog):
    def __init__(
        self,
        parent: Optional[object] = None,
        *,
        title: str = "",
        text: str = "",
        severity: str = "information",
        buttons: object = QMessageBox.StandardButton.Ok,
        defaultButton: object = QMessageBox.StandardButton.Ok,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(440)

        self._result = None
        self._default_value: object = defaultButton
        self._severity = severity

        self._build_ui(title, text, buttons, defaultButton)

        theme_styles.register_theme_listener(self._refresh_theme)
        theme_styles.apply_window_appearance(self)

    @staticmethod
    def _finish_guard(func):
        def wrapper(self, *args, **kwargs):
            if self._result is not None:
                return
            return func(self, *args, **kwargs)

        return wrapper

    # ----------------------------------------------------------
    # UI
    # ----------------------------------------------------------

    def _refresh_theme(self) -> None:
        self.setStyleSheet(theme_styles.dialog_stylesheet())
        theme_styles.apply_window_appearance(self)

    def _build_ui(
        self,
        title: str,
        text: str,
        buttons: object,
        defaultButton: object,
    ) -> None:
        self.setStyleSheet(theme_styles.dialog_stylesheet())

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(18, 18, 18, 18)

        icon_name, icon_color = _SEVERITY.get(self._severity, _SEVERITY["information"])
        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(self._make_icon(icon_name, icon_color))
        title_label = QLabel(title)
        title_label.setObjectName("DialogTitle")
        title_label.setWordWrap(True)
        header.addWidget(title_label, 1)
        root.addLayout(header)

        self._message = QTextEdit()
        self._message.setReadOnly(True)
        self._message.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._message.setAcceptRichText(True)
        if _HTML_RE.search(text):
            self._message.setHtml(text)
        else:
            self._message.setPlainText(text)
        root.addWidget(self._message, 1)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(8)
        buttons_row.addStretch(1)

        copy_button = QPushButton("Копировать")
        copy_button.clicked.connect(self._copy)
        buttons_row.addWidget(copy_button)

        default_value, widgets = self._make_buttons(buttons, defaultButton)
        for widget in widgets:
            buttons_row.addWidget(widget)
        if default_value is not None:
            self._default_value = default_value

        root.addLayout(buttons_row)

    def _make_icon(self, icon_name: str, icon_color: str) -> QLabel:
        pixmap = icon(icon_name, 24, icon_color).pixmap(24, 24)
        label = QLabel()
        label.setPixmap(pixmap)
        return label

    def _make_buttons(self, buttons: object, defaultButton: object):
        pairs = isinstance(buttons, (list, tuple)) and buttons and isinstance(
            buttons[0], (list, tuple)
        )
        if pairs:
            widgets = []
            for label, value in buttons:
                widgets.append(self._make_button(label, value))
            default_value = None
            if defaultButton is not None:
                for label, value in buttons:
                    if str(value) == str(defaultButton):
                        default_value = value
                        break
            return default_value, widgets

        flags = int(buttons)
        selected = [b for b in _STANDARD_ORDER if flags & int(b)]
        if not selected:
            selected = [QMessageBox.StandardButton.Ok]
        widgets = [
            self._make_button(
                _BUTTON_LABELS.get(b, str(b)),
                b,
                primary=(b is QMessageBox.StandardButton.Ok),
            )
            for b in selected
        ]
        default_value = None
        try:
            default_int = int(defaultButton)
        except (TypeError, ValueError):
            default_int = None
        if default_int is not None:
            for b in selected:
                if int(b) == default_int:
                    default_value = b
                    break
        return default_value, widgets

    def _make_button(self, label: str, value: object, primary: bool = False) -> QPushButton:
        button = QPushButton(label)
        if primary:
            button.setObjectName("btn_primary")
        button.clicked.connect(lambda _=False, v=value: self._finish(v))
        return button

    def _default_numeric(self, value: object) -> bool:
        return value is not None

    # ----------------------------------------------------------
    # Апи, зеркалящий QMessageBox
    # ----------------------------------------------------------

    @classmethod
    def _run(
        cls,
        parent,
        title,
        text,
        buttons,
        default_button,
        severity,
    ):
        dialog = cls(
            parent,
            title=title,
            text=text,
            severity=severity,
            buttons=buttons,
            defaultButton=default_button,
        )
        dialog.exec()
        return dialog.result_value

    @classmethod
    def warning(
        cls,
        parent,
        title,
        text,
        buttons=QMessageBox.StandardButton.Ok,
        defaultButton=QMessageBox.StandardButton.No,
    ):
        return cls._run(parent, title, text, buttons, defaultButton, "warning")

    @classmethod
    def critical(
        cls,
        parent,
        title,
        text,
        buttons=QMessageBox.StandardButton.Ok,
        defaultButton=QMessageBox.StandardButton.Ok,
    ):
        return cls._run(parent, title, text, buttons, defaultButton, "critical")

    @classmethod
    def information(
        cls,
        parent,
        title,
        text,
        buttons=QMessageBox.StandardButton.Ok,
        defaultButton=QMessageBox.StandardButton.Ok,
    ):
        return cls._run(parent, title, text, buttons, defaultButton, "information")

    @classmethod
    def question(
        cls,
        parent,
        title,
        text,
        buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        defaultButton=QMessageBox.StandardButton.No,
    ):
        return cls._run(parent, title, text, buttons, defaultButton, "question")

    @classmethod
    def about(cls, parent, title, text):
        return cls._run(
            parent,
            title,
            text,
            QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Ok,
            "information",
        )

    @property
    def result_value(self) -> object:
        return self._result

    # ----------------------------------------------------------
    # Поведение кнопок
    # ----------------------------------------------------------

    @_finish_guard
    def _finish(self, value: object) -> None:
        self._result = value
        self.accept()

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._message.toPlainText())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._finish(self._default_value)
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self._finish(self._default_value)
        super().closeEvent(event)

    def reject(self) -> None:
        self._finish(self._default_value)
        super().reject()