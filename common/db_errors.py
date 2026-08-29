"""Перевод типовых сообщений об ошибках БД/пула на человекочитаемые русские
формулировки для алертов пользователя.

Сообщения, которые не распознаются, возвращаются без изменений.
"""

from __future__ import annotations

import re

_RESPONSES: list[tuple[re.Pattern, str]] = [
    (
        re.compile(
            r"login failed|logon failed|invalid (user|login|logon)|"
            r"incorrect (user|login|password)|failed to (login|logon)|"
            r"access denied for user|password|пароль|логин|"
            r"пользовател(ь|я).*(не (найден|существует))"
        ),
        "Не удалось войти под указанным пользователем. "
        "Проверьте имя пользователя и пароль.",
    ),
    (
        re.compile(
            r"permission denied|access [is ]?denied|"
            r"does not have permission|доступ запрещён|недостаточно прав|"
            r"нет прав"
        ),
        "Недостаточно прав для выполнения операции. "
        "Проверьте права пользователя на сервере.",
    ),
    (
        re.compile(
            r"cannot open database|could not connect|connection (refused|"
            r"reset|closed)|failed to connect|network-related or "
            r"instance-specific|server is not running|not reachable|"
            r"не удалось установить соединение|сервер недоступен|"
            r"соединение.*(закрыто|разорвано|отклонено)"
        ),
        "Не удалось установить соединение с сервером. "
        "Проверьте адрес, порт и доступность сервера.",
    ),
    (
        re.compile(
            r"single[_ -]?user|используется другим|занят[а-я]|in use|"
            r"cannot drop database because|restore is currently in progress|"
            r"монопольн"
        ),
        "База данных используется другим процессом. "
        "Закройте активные подключения и повторите операцию.",
    ),
    (
        re.compile(r"already been attached|already attached|уже присоединен"),
        "База данных уже присоединена к серверу.",
    ),
    (
        re.compile(
            r"file not found|cannot find (the )?file|could not find|"
            r"unable to open database file|файл.*не найден|"
            r"физическ.*не найден"
        ),
        "Не удалось найти файл базы данных. Проверьте путь к файлу.",
    ),
    (
        re.compile(
            r"лимит одновременных соединений|слишком много соединений|"
            r"не удалось получить соединение|pooltimeout"
        ),
        "Превышено время ожидания соединения (пул перегружен или сервер "
        "недоступен). Повторите попытку позже.",
    ),
    (
        re.compile(
            r"timeout expired|timed out|query timeout|таймаут|"
            r"истекло время"
        ),
        "Истекло время ожидания ответа от сервера.",
    ),
    (
        re.compile(r"database (already )?exists|already exists|уже существует"),
        "База данных с таким именем уже существует.",
    ),
]


def humanize_db_error(message: str) -> str:
    """Возвращает русскую формулировку для типовой ошибки БД/пула."""
    text = str(message or "")
    lowered = text.lower()
    for pattern, response in _RESPONSES:
        if pattern.search(lowered) or pattern.search(text):
            return response
    return text