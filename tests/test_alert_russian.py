"""
tests/test_alert_russian.py

Регрессионные «стражи» русскоязычности и копируемости алертов, действующие
на весь код gui/**: и текущая, и любые будущие реализации алертов обязаны:

1. Показываться через CopyableMessageBox (нативный QMessageBox не позволяет
   выделить/скопировать текст и не стилизуется через QSS темы).
2. Иметь русскоязычные статические строки заголовка, текста и подписей кнопок
   (английские литералы в алертах запрещены).

Проверка построена на AST-обходе исходников, поэтому не зависит от рантайма.
"""

import ast
import re
import unittest
from pathlib import Path

GUI_DIR = Path(__file__).resolve().parent.parent / "gui"

_NATIVE_METHODS = {"warning", "information", "critical", "question", "about"}
_ALERT_METHODS = {"warning", "information", "critical", "question", "about"}

_CYRILLIC = re.compile(r"[а-яё]")
_ASCII_LETTER = re.compile(r"[a-zA-Z]")


def _is_meaningful(text: str) -> bool:
    return bool(_ASCII_LETTER.search(text)) or bool(_CYRILLIC.search(text))


def _constant_ok(text: str) -> bool:
    if not _is_meaningful(text):
        return True
    return bool(_CYRILLIC.search(text))


class _StringStatus:
    def __init__(self):
        self.has_cyrillic = False
        self.has_dynamic = False
        self.problems: list[str] = []


def _analyze_string(node: ast.AST, status: "_StringStatus") -> None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value: str = node.value
        if _constant_ok(value):
            if _CYRILLIC.search(value):
                status.has_cyrillic = True
        else:
            status.problems.append(f"не-кириллический литерал: {value!r}")
        return

    if isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                status.has_dynamic = True
            else:
                _analyze_string(part, status)
        return

    if isinstance(node, ast.BinOp):
        _analyze_string(node.left, status)
        _analyze_string(node.right, status)
        return

    status.has_dynamic = True


def _string_ok(node: ast.AST) -> bool:
    status = _StringStatus()
    _analyze_string(node, status)
    if status.problems:
        return False
    return bool(status.has_cyrillic or status.has_dynamic)


def _button_labels_ok(node: ast.AST) -> bool:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return True
    for item in node.elts:
        if not isinstance(item, (ast.List, ast.Tuple)) or not item.elts:
            continue
        label = item.elts[0]
        if isinstance(label, ast.Constant) and isinstance(label.value, str):
            if not _CYRILLIC.search(label.value):
                return False
    return True


def _arg(call: ast.Call, name: str, index: int) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    if len(call.args) > index:
        return call.args[index]
    return None


def _scan_problems(source: Path, tree: ast.Module) -> list[str]:
    problems: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func

        native_constructor = isinstance(func, ast.Name) and func.id == "QMessageBox"
        native_method = (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "QMessageBox"
            and func.attr in _NATIVE_METHODS
        )
        if native_constructor or native_method:
            problems.append(
                f"{source}:{node.lineno}: "
                f"нативный QMessageBox — используйте CopyableMessageBox"
            )
            continue

        is_constructor = isinstance(func, ast.Name) and func.id == "CopyableMessageBox"
        is_method = (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "CopyableMessageBox"
            and func.attr in _ALERT_METHODS
        )
        if not (is_constructor or is_method):
            continue

        if is_constructor:
            title = _arg(node, "title", 1)
            text = _arg(node, "text", 2)
            buttons = _arg(node, "buttons", -1)
            if title is not None and not _string_ok(title):
                problems.append(f"{source}:{node.lineno}: заголовок не кириллический")
            if text is not None and not _string_ok(text):
                problems.append(f"{source}:{node.lineno}: текст не кириллический")
            if buttons is not None and not _button_labels_ok(buttons):
                problems.append(f"{source}:{node.lineno}: подписи кнопок не русские")
        else:
            title = _arg(node, "title", 1)
            text = _arg(node, "text", 2)
            if title is not None and not _string_ok(title):
                problems.append(f"{source}:{node.lineno}: заголовок не кириллический")
            if text is not None and not _string_ok(text):
                problems.append(f"{source}:{node.lineno}: текст не кириллический")

    return problems


def _iter_gui_sources():
    for path in sorted(GUI_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


class TestAlertsUseCopyableComponent(unittest.TestCase):
    def test_no_native_qmessagebox_alerts_in_gui(self):
        problems = []
        for source in _iter_gui_sources():
            tree = ast.parse(source.read_text(encoding="utf-8"))
            problems.extend(_scan_problems(source, tree))
        self.assertEqual(problems, [])


class TestAlertStringsAreRussian(unittest.TestCase):
    def test_all_alert_literals_are_cyrillic(self):
        problems = []
        for source in _iter_gui_sources():
            tree = ast.parse(source.read_text(encoding="utf-8"))
            problems.extend(_scan_problems(source, tree))
        self.assertEqual(problems, [])

    def test_copyable_alert_is_the_only_alert_channel(self):
        # Если все алерты идут через CopyableMessageBox — копируемость текста
        # гарантирована самим компонентом (проверяется в test_copyable_alert).
        for source in _iter_gui_sources():
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    native_method = (
                        isinstance(func, ast.Attribute)
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "QMessageBox"
                        and func.attr in _NATIVE_METHODS
                    )
                    native_constructor = (
                        isinstance(func, ast.Name) and func.id == "QMessageBox"
                    )
                    self.assertFalse(
                        native_method or native_constructor,
                        f"{source}:{node.lineno}: нативный QMessageBox",
                    )


if __name__ == "__main__":
    unittest.main()