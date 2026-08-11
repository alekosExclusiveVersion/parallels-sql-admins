"""
gui/widgets/status_bar.py

Строка состояний приложения: статус проверки, счётчик серверов, прошедшее
время, статус SQL-консоли, прогресс и кнопка темы.

Вынесена из MainWindow: виджет сам создаёт и раскрашивает свои QLabel,
прогресс-бар и API обновления, а цвета берутся из QSS-токенов темы
(без хардкода цветов в коде).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QWidget,
)


class StatusBar(QFrame):
    """Полноширинная строка состояний внизу главного окна."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusBar")

        self._lbl_status_value = QLabel("Готово")
        self._lbl_servers_value = QLabel("0 / 0")
        self._lbl_elapsed_value = QLabel("00:00:00")
        self._lbl_sql_status = QLabel("Готово")

        for label in (
            self._lbl_status_value,
            self._lbl_servers_value,
            self._lbl_elapsed_value,
            self._lbl_sql_status,
        ):
            label.setObjectName("StatusValue")

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedWidth(160)
        self._progress.setTextVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 3, 12, 3)
        layout.setSpacing(6)

        layout.addWidget(self._make_group("Статус:", self._lbl_status_value))
        layout.addSpacing(12)
        layout.addWidget(self._make_group("Серверы:", self._lbl_servers_value))
        layout.addSpacing(12)
        layout.addWidget(self._make_group("Прошло:", self._lbl_elapsed_value))
        layout.addSpacing(12)
        layout.addWidget(self._make_group("SQL Консоль:", self._lbl_sql_status))

        layout.addStretch()

        self._progress_container: QWidget | None = None
        layout.addWidget(self._progress)

    # ----------------------------------------------------------
    # Сборка
    # ----------------------------------------------------------

    @staticmethod
    def _make_group(caption: str, value: QLabel) -> QWidget:
        group = QWidget()
        row = QHBoxLayout(group)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        caption_label = QLabel(caption)
        caption_label.setObjectName("StatusCaption")

        row.addWidget(caption_label)
        row.addWidget(value)
        return group

    # ----------------------------------------------------------
    # API обновления
    # ----------------------------------------------------------

    def set_status(self, text: str) -> None:
        self._lbl_status_value.setText(text)

    def set_sql_status(self, text: str) -> None:
        self._lbl_sql_status.setText(text)

    def set_servers(self, current: int, total: int) -> None:
        self._lbl_servers_value.setText(f"{current} / {total}")

    def set_elapsed(self, seconds: int) -> None:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        self._lbl_elapsed_value.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def set_progress(self, current: int, total: int) -> None:
        if total == 0:
            self._progress.setValue(0)
            return
        percent = int(current * 100 / total)
        self._progress.setValue(percent)

    def reset(self) -> None:
        self.set_status("Готово")
        self.set_sql_status("Готово")
        self.set_elapsed(0)
        self._progress.setValue(0)

    def add_widget(self, widget: QWidget) -> None:
        """Добавляет виджет в правую часть строки (после прогресса)."""
        self.layout().addWidget(widget)
