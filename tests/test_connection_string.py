"""
tests/test_connection_string.py

Тесты импорта/экспорта строк подключения (URI-стиль):

    engine://user:password@host:port
"""

from __future__ import annotations

import pytest

from common.connection_string import (
    format_connection_string,
    parse_connection_string,
)
from common.server_registry import (
    ENGINE_MSSQL,
    ENGINE_MYSQL,
    ENGINE_PGSQL,
    ServerSpec,
)


class TestFormat:
    def test_mysql_full(self):
        spec = ServerSpec(
            host="db.example.com",
            engine=ENGINE_MYSQL,
            user="root",
            password="secret",
            port=3306,
        )
        assert (
            format_connection_string(spec)
            == "mysql://root:secret@db.example.com:3306"
        )

    def test_mssql_escaped_password(self):
        spec = ServerSpec(
            host="sql.corp.local",
            engine=ENGINE_MSSQL,
            user="sa",
            password="my@pass:123",
            port=1433,
        )
        assert (
            format_connection_string(spec)
            == "mssql://sa:my%40pass%3A123@sql.corp.local:1433"
        )

    def test_pgsql_with_password(self):
        spec = ServerSpec(
            host="pg.example.com",
            engine=ENGINE_PGSQL,
            user="postgres",
            password="secret",
            port=5432,
        )
        assert (
            format_connection_string(spec)
            == "pgsql://postgres:secret@pg.example.com:5432"
        )

    def test_no_credentials(self):
        spec = ServerSpec(host="10.0.0.5", engine=ENGINE_MYSQL)
        assert format_connection_string(spec) == "mysql://10.0.0.5:3306"


class TestParse:
    def test_basic(self):
        spec = parse_connection_string(
            "pgsql://postgres:secret@127.0.0.1:5432"
        )
        assert spec.engine == ENGINE_PGSQL
        assert spec.host == "127.0.0.1"
        assert spec.user == "postgres"
        assert spec.password == "secret"
        assert spec.port == 5432

    def test_escaped_credentials_roundtrip(self):
        line = "pgsql://postgres:my%40pass%3A123@db.example.com:5432"
        spec = parse_connection_string(line)
        assert spec.password == "my@pass:123"
        # Round trip: format → parse → format сохраняет строку.
        assert format_connection_string(spec) == line

    def test_default_port(self):
        spec = parse_connection_string("mysql://root:secret@127.0.0.1")
        assert spec.port == 3306
        assert spec.engine == ENGINE_MYSQL

    def test_ipv6(self):
        spec = parse_connection_string("pgsql://admin:pw@[::1]:5433")
        assert spec.host == "::1"
        assert spec.port == 5433

    def test_no_password(self):
        spec = parse_connection_string("mssql://sa@sql.local:1433")
        assert spec.user == "sa"
        assert spec.password == ""

    def test_empty_line_raises(self):
        with pytest.raises(ValueError):
            parse_connection_string("")

    def test_no_scheme_raises(self):
        with pytest.raises(ValueError):
            parse_connection_string("root:secret@host:3306")

    def test_unknown_engine_raises(self):
        with pytest.raises(ValueError):
            parse_connection_string("oracle://x@y:1")

    def test_bad_port_raises(self):
        with pytest.raises(ValueError):
            parse_connection_string("mysql://root@host:notaport")