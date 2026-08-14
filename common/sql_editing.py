"""
common/sql_editing.py

Разбор простых SELECT и построение безопасных UPDATE для редактирования
ячеек таблицы Results.

Редактирование доступно только для одиночного запроса вида
    SELECT ... FROM <one_table> [WHERE ...] [ORDER BY ...] [LIMIT ...]
— без JOIN, GROUP BY/HAVING, UNION, DISTINCT, подзапросов и скобок.
Такая форма позволяет однозначно сопоставить колонки результата реальным
колонкам таблицы и построить UPDATE по первичному ключу.

Значения в UPDATE экранируются: строки через удвоение одинарной кавычки,
числа подставляются как есть, None и текст "NULL" превращаются в SQL NULL.
Идентификаторы экранируются per-engine через server_registry.quote_ident.
"""

from __future__ import annotations

from typing import Callable

from common.server_registry import quote_ident


def strip_sql(sql: str) -> str:
    """Обрезает пробелы и хвостовую точку с запятой."""
    return sql.strip().rstrip(";")


_PUNCT = set("(),;")
_REJECT_KEYWORDS = {
    "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS",
    "UNION", "GROUP", "HAVING", "DISTINCT",
}


def _tokens(sql: str):
    """Сканирует SQL, выдавая слова и знаки пунктуации вне строк,
    идентификаторов в кавычках и комментариев: (текст, start, end)."""
    n = len(sql)
    i = 0

    while i < n:
        ch = sql[i]

        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            end = sql.find("\n", i)
            i = n if end == -1 else end + 1
            continue
        if ch == "#":
            end = sql.find("\n", i)
            i = n if end == -1 else end + 1
            continue
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            while i < n:
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                if quote == "'" and sql[i] == "\\":
                    i += 2
                    continue
                i += 1
            continue
        if ch == "`":
            start = i
            i += 1
            while i < n and sql[i] != "`":
                i += 1
            i += 1
            yield sql[start + 1:i - 1], start, i
            continue
        if ch.isalpha() or ch == "_" or ch == "$":
            start = i
            while i < n and (sql[i].isalnum() or sql[i] in "_$"):
                i += 1
            yield sql[start:i], start, i
            continue
        if ch == ".":
            yield ".", i, i + 1
            i += 1
            continue
        if ch in _PUNCT:
            yield ch, i, i + 1
        i += 1


def parse_select_table(sql: str) -> str | None:
    """Возвращает имя таблицы простого SELECT или None, если запрос
    не подходит для редактирования ячеек (JOIN, агрегаты, подзапросы,
    несколько операторов, квалифицированные имена таблиц)."""
    sql = strip_sql(sql)
    if not sql:
        return None

    tokens = list(_tokens(sql))
    if not tokens:
        return None

    if tokens[0][0].upper() != "SELECT":
        return None

    for tok, _, _ in tokens:
        if tok in _PUNCT and tok != ",":
            # '(' ')' ';' — подзапросы/несколько операторов
            return None
        if tok.upper() in _REJECT_KEYWORDS:
            return None

    for index, (tok, _, _) in enumerate(tokens):
        if tok.upper() != "FROM":
            continue
        if index + 1 >= len(tokens):
            return None
        table = tokens[index + 1][0]
        if table == "," or "(" in table:
            return None
        if index + 2 < len(tokens) and tokens[index + 2][0] == ".":
            # Квалифицированное имя (db.table) — неоднозначная цель.
            return None
        return table

    return None


def quote_literal(value) -> str:
    """Превращает значение в безопасный SQL-литерал.

    None → NULL; текст "NULL" (без кавычек) → NULL; числа — как есть;
    всё остальное — строка с удвоением одинарных кавычек.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text.strip().upper() == "NULL":
        return "NULL"
    return "'" + text.replace("'", "''") + "'"


def build_update_sql(
    engine: str,
    table: str,
    column: str,
    new_value,
    identity_pairs: list[tuple[str, object]],
    quote_ident_fn: Callable[[str, str], str] = quote_ident,
) -> str:
    """Строит UPDATE по первичному ключу.

    engine — движок сервера (для экранирования идентификаторов);
    identity_pairs — список (колонка, старое значение) для WHERE;
    новая строка не должна совпадать ни с одним значением identity.
    """
    if not identity_pairs:
        raise ValueError("identity_pairs must not be empty")

    ident = lambda name: quote_ident_fn(engine, name)  # noqa: E731

    set_clause = f"{ident(column)} = {quote_literal(new_value)}"
    where = " AND ".join(
        f"{ident(col)} = {quote_literal(value)}"
        for col, value in identity_pairs
    )
    return f"UPDATE {ident(table)} SET {set_clause} WHERE {where}"
