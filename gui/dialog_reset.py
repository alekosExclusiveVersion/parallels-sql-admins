from __future__ import annotations

from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
import shiboken6

_SNAPSHOT_ATTR = "_dialog_default_snapshot"


def _get_value(w: QWidget) -> object:
    if isinstance(w, (QCheckBox, QRadioButton)) or (
        isinstance(w, QGroupBox) and w.isCheckable()
    ):
        return w.isChecked()
    if isinstance(w, QComboBox):
        return (w.currentIndex(), w.currentText() if w.isEditable() else None)
    if isinstance(w, (QSpinBox, QDoubleSpinBox, QSlider)):
        return w.value()
    if isinstance(w, QDateTimeEdit):
        return w.dateTime()
    if isinstance(w, QListWidget):
        return w.currentRow()
    if isinstance(w, (QPlainTextEdit, QTextEdit)):
        return w.toPlainText()
    if isinstance(w, QLineEdit):
        return w.text()
    return None


def _set_value(w: QWidget, value: object) -> None:
    if isinstance(w, (QCheckBox, QRadioButton)) or (
        isinstance(w, QGroupBox) and w.isCheckable()
    ):
        w.setChecked(bool(value))
    elif isinstance(w, QComboBox):
        index, text = value if isinstance(value, tuple) else (value, None)
        if isinstance(index, int) and 0 <= index < w.count():
            w.setCurrentIndex(index)
        elif w.isEditable() and text is not None:
            w.setCurrentText(str(text))
    elif isinstance(w, (QSpinBox, QDoubleSpinBox, QSlider)):
        w.setValue(float(value) if isinstance(w, QDoubleSpinBox) else int(value))
    elif isinstance(w, QDateTimeEdit):
        w.setDateTime(value if isinstance(value, QDateTime) else QDateTime())
    elif isinstance(w, QListWidget):
        w.setCurrentRow(int(value))
    elif isinstance(w, (QPlainTextEdit, QTextEdit)):
        w.setPlainText(str(value))
    elif isinstance(w, QLineEdit):
        w.setText(str(value))


def snapshot_dialog_defaults(dialog: QWidget) -> None:
    editable = []
    for w in dialog.findChildren(QWidget):
        if isinstance(w, (QLineEdit, QPlainTextEdit, QTextEdit)) and w.isReadOnly():
            continue
        value = _get_value(w)
        if value is None:
            continue
        editable.append((w, value))
    setattr(dialog, _SNAPSHOT_ATTR, editable)


def restore_dialog_defaults(dialog: QWidget) -> None:
    pairs = [
        (w, value)
        for w, value in getattr(dialog, _SNAPSHOT_ATTR, ())
        if shiboken6.isValid(w)
    ]
    for w, value in pairs:
        if isinstance(w, QComboBox):
            _set_value(w, value)
    for w, value in pairs:
        if not isinstance(w, QComboBox):
            _set_value(w, value)


def add_dialog_reset_button(
    dialog: QWidget,
    btn_row: QHBoxLayout | None = None,
) -> QPushButton:
    btn = QPushButton("Сброс")
    btn.setToolTip("Вернуть значения полей к исходным")
    btn.clicked.connect(lambda: restore_dialog_defaults(dialog))

    box = dialog.findChild(QDialogButtonBox)
    if box is not None:
        box.addButton(btn, QDialogButtonBox.ResetRole)
    elif btn_row is not None:
        btn_row.insertWidget(max(btn_row.count() - 2, 0), btn)
    else:
        layout = dialog.layout()
        if layout is not None:
            layout.addWidget(btn)
    return btn
