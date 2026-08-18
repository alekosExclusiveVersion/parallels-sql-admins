"""
common/sql_completion.py

Чистая логика автодополнения SQL (без Qt и без БД) — тестируется
отдельно от GUI.

Анализирует текст редактора и позицию курсора и определяет, что
подсказывать:

  * "table"   — после FROM/JOIN/INTO/UPDATE/TABLE подсказываем таблицы;
  * "column"  — после `таблица.` подсказываем колонки этой таблицы;
  * "keyword" — во всех остальных случаях ключевые слова (+ таблицы и
    колонки текущей БД как вспомогательные);
  * "script"  — сохранённые скрипты (по имени и содержимому тела).

Используется SqlCompleter (gui/sql_completer.py) и SQLHighlighter
(единый список ключевых слов SQL_KEYWORDS).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Единый источник ключевых слов: используется и подсветкой, и подсказками.
SQL_KEYWORDS = [
    "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "BETWEEN",
    "LIKE", "ORDER", "BY", "GROUP", "HAVING", "LIMIT", "OFFSET",
    "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "CROSS", "ON", "AS",
    "UNION", "ALL", "DISTINCT", "CASE", "WHEN", "THEN", "ELSE", "END",
    "INSERT", "INTO", "VALUES", "UPDATE", "SET", "DELETE",
    "CREATE", "ALTER", "DROP", "TRUNCATE", "REPLACE", "RENAME",
    "GRANT", "REVOKE", "TABLE", "DATABASE", "INDEX", "VIEW", "IF",
    "EXISTS", "NULL", "TRUE", "FALSE", "USING", "NATURAL",
    "MAX", "MIN", "COUNT", "SUM", "AVG", "COALESCE", "NOW", "IFNULL",
]

# После этих ключевых слов ожидается имя таблицы.
TABLE_TRIGGER_KEYWORDS = frozenset(
    ("FROM", "JOIN", "INTO", "UPDATE", "TABLE", "INSERT")
)

KIND_TABLE = "table"
KIND_COLUMN = "column"
KIND_KEYWORD = "keyword"
KIND_SCRIPT = "script"

# Максимум строк в попапе (защита от огромных БД).
MAX_SUGGESTIONS = 200

# Символы, из которых состоит идентификатор. Точка обрабатывается отдельно.
_IDENTIFIER_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$"
)

_TRIGGER_RE = re.compile(
    r"\b(" + "|".join(TABLE_TRIGGER_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CompletionContext:
    """Что именно дополняется в текущей позиции курсора."""

    prefix: str            # вводимая часть слова (после последней точки)
    table: str | None      # имя таблицы для режима колонок (или None)
    kind: str              # KIND_TABLE / KIND_COLUMN / KIND_KEYWORD
    has_dot: bool          # есть ли точка перед вводимым словом


def analyze(text: str, position: int) -> CompletionContext:
    """Определяет контекст дополнения в позиции `position` текста."""
    before = text[:position]

    start = position
    while start > 0:
        ch = before[start - 1]
        if ch in _IDENTIFIER_CHARS or ch == ".":
            start -= 1
        else:
            break

    token = before[start:position]

    if "." in token:
        table_part, _, prefix = token.rpartition(".")
        return CompletionContext(
            prefix=prefix,
            table=table_part.strip("`[]\"' ") or None,
            kind=KIND_COLUMN,
            has_dot=True,
        )

    kind = _context_kind(before[:start])
    return CompletionContext(
        prefix=token,
        table=None,
        kind=kind,
        has_dot=False,
    )


def _context_kind(segment: str) -> str:
    """Режим по последнему ключевому слову перед вводимым токеном."""
    matches = list(_TRIGGER_RE.finditer(segment))
    if matches:
        return KIND_TABLE
    return KIND_KEYWORD


def suggest(
    context: CompletionContext,
    keywords: list[str] | tuple[str, ...] | None = None,
    tables: list[str] | tuple[str, ...] | None = None,
    columns: dict[str, list[str]] | None = None,
    scripts: list[dict] | None = None,
) -> list[tuple[str, str]]:
    """Возвращает подсказки как список (текст, тип).

    `columns` — словарь {имя_таблицы: [колонки]}. `scripts` — список
    словарей {name, body}. Порядок: самое релевантное впереди;
    дубликаты убираются; список ограничен MAX_SUGGESTIONS.
    """
    keywords = list(keywords or SQL_KEYWORDS)
    tables = list(tables or [])
    columns = columns or {}
    scripts = scripts or []

    prefix = context.prefix.lower()
    results: list[tuple[str, str]] = []

    if context.kind == KIND_TABLE:
        results.extend(
            (name, KIND_TABLE)
            for name in tables
            if name.lower().startswith(prefix)
        )

    elif context.kind == KIND_COLUMN:
        if context.table and context.table in columns:
            results.extend(
                (name, KIND_COLUMN)
                for name in columns[context.table]
                if name.lower().startswith(prefix)
            )
        else:
            results.extend(_all_columns(columns, prefix))

    else:  # KIND_KEYWORD — общий случай
        results.extend(
            (word, KIND_KEYWORD)
            for word in keywords
            if word.lower().startswith(prefix)
        )
        results.extend(
            (name, KIND_TABLE)
            for name in tables
            if name.lower().startswith(prefix)
        )
        results.extend(_all_columns(columns, prefix))

    results.extend(_match_scripts(scripts, prefix))

    return _dedupe(results)[:MAX_SUGGESTIONS]


def _match_scripts(
    scripts: list[dict],
    prefix: str,
) -> list[tuple[str, str]]:
    """Подбирает скрипты по имени (prefix) и по содержимому тела (contains).

    Приоритет: имя > тело. Формат отображения: "📜 Имя скрипта".
    """
    name_matches: list[tuple[str, str]] = []
    body_matches: list[tuple[str, str]] = []
    seen: set[str] = set()

    for s in scripts:
        name = s.get("name", "")
        body = s.get("body", "")
        if not name or name in seen:
            continue

        name_lower = name.lower()
        display = f"\U0001f4dc {name}"

        if prefix and name_lower.startswith(prefix):
            name_matches.append((display, KIND_SCRIPT))
            seen.add(name)
        elif prefix and prefix in body.lower():
            body_matches.append((display, KIND_SCRIPT))
            seen.add(name)

    return name_matches + body_matches


def _all_columns(
    columns: dict[str, list[str]],
    prefix: str,
) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for names in columns.values():
        for name in names:
            if name in seen or not name.lower().startswith(prefix):
                continue
            seen.add(name)
            out.append((name, KIND_COLUMN))
    return out


def _dedupe(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for text, kind in items:
        if text in seen:
            continue
        seen.add(text)
        out.append((text, kind))
    return out
