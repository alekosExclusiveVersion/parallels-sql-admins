"""
common/connection_string.py

Импорт/экспорт серверов в виде строк подключения.

Формат (URI-стиль, одна строка на сервер):

    engine://user:password@host:port

    Примеры:
        mysql://root:secret@db.example.com:3306
        mssql://sa:Passw0rd@sql.corp.local:1433
        pgsql://postgres:my@pass@pg.example.com:5432

Движок обязателен (mysql/mssql/pgsql) — по нему при импорте
определяется СУБД. Принимаются алиасы: sqlserver/sql_server/sqlsrv
вместо mssql, postgres/postgresql вместо pgsql. user и password
экранируются URL-кодированием (percent-encoding), так что любые
символы, включая '@'/':' и пробелы, корректно обрабатываются.
Порт необязателен: если опущен, при создании ServerSpec подставляется
порт по умолчанию для движка.

Дополнительные параметры после host:port игнорируются — как ADO.NET
(;connection_timeout=30), так и query-строка URI (?ssl=true):

    sqlserver://sa:1qazXSW%40@192.168.128.160:1436;connection_timeout=30

Функция parse_connection_string() используется диалогом импорта
и тестами.
"""

from __future__ import annotations

from urllib.parse import quote, unquote

from common.server_registry import (
    ENGINE_MSSQL,
    ENGINE_MYSQL,
    ENGINE_PGSQL,
    ServerSpec,
    default_port,
)

# Движки, поддерживаемые строками подключения (порядок важен для подсказок).
SUPPORTED_ENGINES = (ENGINE_MYSQL, ENGINE_MSSQL, ENGINE_PGSQL)

# Алиасы схем в строках подключения → канонический движок.
_ENGINE_ALIASES = {
    "sqlserver": ENGINE_MSSQL,
    "sql_server": ENGINE_MSSQL,
    "sqlsrv": ENGINE_MSSQL,
    "postgres": ENGINE_PGSQL,
    "postgresql": ENGINE_PGSQL,
}


def _validate_engine(engine: str) -> str:
    engine = _ENGINE_ALIASES.get(
        (engine or "").strip().lower(), (engine or "").strip().lower()
    )
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(
            f"Неизвестный движок '{engine}'. Ожидается один из: "
            + ", ".join(SUPPORTED_ENGINES)
        )
    return engine


def format_connection_string(spec: ServerSpec) -> str:
    """Превращает ServerSpec в строку подключения.

    Порт выводится всегда (даже если совпадает с портом по умолчанию),
    чтобы экспортированный файл был самодостаточным.
    """
    engine = _validate_engine(spec.engine)
    user = quote(spec.user or "", safe="")
    password = quote(spec.password or "", safe="")
    port = int(spec.port or default_port(engine))

    credentials = ""
    if user or password:
        credentials = f"{user}:{password}@"

    return f"{engine}://{credentials}{spec.host}:{port}"


def parse_connection_string(line: str) -> ServerSpec:
    """Разбирает строку подключения в ServerSpec.

    Формат: engine://[user[:password]@]host[:port][;params][?query]

    Принимаются алиасы движков (sqlserver→mssql, postgres→pgsql),
    параметры после host:port (ADO.NET `;key=value`, URI `?key=value`)
    игнорируются. user/password декодируются из percent-encoding.
    Строка БЕЗ движка или с неизвестным движком выбрасывает ValueError
    с понятным текстом.
    """
    raw = (line or "").strip()

    if not raw:
        raise ValueError("Пустая строка подключения.")

    if "://" not in raw:
        raise ValueError(
            f"Неверный формат '{raw}'. Ожидается engine://user:pass@host:port "
            f"(например pgsql://postgres:secret@127.0.0.1:5432)."
        )

    engine, rest = raw.split("://", 1)
    engine = _validate_engine(engine)

    # Отделяем host:port от credentials.
    credentials, sep, host_part = rest.rpartition("@")

    if not sep:
        host_part = rest
        credentials = ""

    # Игнорируем дополнительные параметры после host:port:
    # ADO.NET (;connection_timeout=30) и query-строку URI (?ssl=true).
    host_part = host_part.split(";", 1)[0].split("?", 1)[0]

    # host[:port]
    if host_part.startswith("["):
        # IPv6-адрес вида [::1]:5432
        host, _, port_str = host_part[1:].partition("]")
        if host_part.startswith("]"):
            raise ValueError(f"Неверный адрес хоста '{host_part}'.")
        if port_str.startswith(":"):
            port_str = port_str[1:]
        else:
            port_str = ""
    elif ":" in host_part:
        host, port_str = host_part.rsplit(":", 1)
        if not port_str.isdigit():
            raise ValueError(f"Неверный порт '{port_str}' в строке '{raw}'.")
    else:
        host, port_str = host_part, ""

    host = host.strip()

    if not host:
        raise ValueError(f"Пустой хост в строке '{raw}'.")

    # credentials: user[:password]
    user = ""
    password = ""

    if credentials:
        user_raw, _, password_raw = credentials.partition(":")
        user = unquote(user_raw)
        if password_raw:
            password = unquote(password_raw)

    port = int(port_str) if port_str.isdigit() else 0

    return ServerSpec(
        host=host,
        port=port,
        engine=engine,
        user=user,
        password=password,
    )