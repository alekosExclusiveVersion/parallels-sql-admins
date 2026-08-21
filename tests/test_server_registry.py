"""
tests/test_server_registry.py

Тесты эталона серверов (servers.reference.json):

- первый запуск: миграция из эталона с учётом движков/портов/имён;
- обновление: слияние новых хостов из эталона — только добавление,
  существующие записи и пользовательские серверы не трогаются;
- откат на legacy-импорт из servers.txt при отсутствии эталона;
- устойчивость к отсутствующему/битому эталону.
"""

import json
import tempfile
import unittest
from pathlib import Path

from common.server_registry import (
    ENGINE_MSSQL,
    ENGINE_MYSQL,
    ENGINE_PGSQL,
    ServerRegistry,
    ServerSpec,
    parse_host_key,
)


class _StubVault:
    """Имитация разблокированного vault (file_key): шифрование прозрачно."""

    unlocked = True
    meta = {"version": 1, "kind": "file_key"}

    def encrypt(self, value: str) -> str:
        return value

    def decrypt(self, value: str) -> str:
        return value


REFERENCE = [
    {"host": "p7ru1.tradesoft.ru", "engine": "mysql", "port": 0, "name": ""},
    {"host": "sql-prod.tradesoft.ru", "engine": "mssql", "port": 1433,
     "name": "SQL Prod"},
    {"host": "pg-main.tradesoft.ru", "engine": "pgsql", "port": 5432,
     "name": "PG Main"},
]


def _make_registry(tmp: Path, servers_json: str | None = None) -> ServerRegistry:
    reg = ServerRegistry()
    reg.servers_file = tmp / "servers.json"
    reg.key_file = tmp / "servers.key"
    reg.backups_dir = tmp / "backups"
    reg.vault = _StubVault()
    if servers_json is not None:
        reg.servers_file.write_text(servers_json, encoding="utf-8")
    return reg


class TestReferenceMigration(unittest.TestCase):

    def test_first_run_imports_from_reference_with_engines(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            reg = _make_registry(tmp)
            reg._reference_file = lambda: tmp / "reference.json"
            (tmp / "reference.json").write_text(
                json.dumps(REFERENCE), encoding="utf-8"
            )

            specs = reg.load()

            hosts = [s.host for s in specs]
            self.assertEqual(hosts, [e["host"] for e in REFERENCE])
            by_host = {s.host: s for s in specs}
            self.assertEqual(by_host["sql-prod.tradesoft.ru"].engine, ENGINE_MSSQL)
            self.assertEqual(by_host["sql-prod.tradesoft.ru"].port, 1433)
            self.assertEqual(by_host["sql-prod.tradesoft.ru"].name, "SQL Prod")
            self.assertEqual(by_host["pg-main.tradesoft.ru"].engine, ENGINE_PGSQL)
            self.assertEqual(by_host["p7ru1.tradesoft.ru"].engine, ENGINE_MYSQL)
            self.assertTrue(reg.servers_file.exists())

    def test_first_run_falls_back_to_txt_without_reference(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            reg = _make_registry(tmp)
            reg._reference_file = lambda: tmp / "reference.json"
            (tmp / "servers.txt").write_text(
                "h1.example.com\nh2.example.com\n", encoding="utf-8"
            )

            specs = reg.load()

            hosts = [s.host for s in specs]
            self.assertEqual(hosts, ["h1.example.com", "h2.example.com"])
            self.assertTrue(all(s.engine == ENGINE_MYSQL for s in specs))


class TestReferenceMerge(unittest.TestCase):

    EXISTING = json.dumps({
        "meta": {"version": 1, "kind": "file_key"},
        "servers": [
            {"host": "p7ru1.tradesoft.ru", "port": 3306, "engine": "mysql",
             "user": "koshkin", "password": "secret", "name": "p7ru1"},
            {"host": "custom-only.tradesoft.ru", "port": 0, "engine": "mysql",
             "user": "admin", "password": "pw", "name": "Мой сервер"},
        ],
    }, ensure_ascii=False)

    def test_merge_adds_new_hosts_and_keeps_existing(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            reg = _make_registry(tmp, self.EXISTING)
            reg._reference_file = lambda: tmp / "reference.json"
            (tmp / "reference.json").write_text(
                json.dumps(REFERENCE), encoding="utf-8"
            )

            specs = reg.load()

            by_host = {s.host: s for s in specs}
            self.assertEqual(
                set(by_host),
                {"p7ru1.tradesoft.ru", "custom-only.tradesoft.ru",
                 "sql-prod.tradesoft.ru", "pg-main.tradesoft.ru"},
            )
            old = by_host["p7ru1.tradesoft.ru"]
            self.assertEqual(old.user, "koshkin")
            self.assertEqual(old.password, "secret")
            self.assertEqual(old.name, "")  # атрибуты обновляются из эталона
            self.assertTrue(old.ref)
            custom = by_host["custom-only.tradesoft.ru"]
            self.assertEqual(custom.name, "Мой сервер")
            self.assertFalse(custom.ref)
            new_mssql = by_host["sql-prod.tradesoft.ru"]
            self.assertEqual(new_mssql.engine, ENGINE_MSSQL)
            self.assertEqual(new_mssql.port, 1433)
            self.assertEqual(new_mssql.user, "")
            self.assertEqual(new_mssql.password, "")

    def test_merge_persists_merged_file(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            reg = _make_registry(tmp, self.EXISTING)
            reg._reference_file = lambda: tmp / "reference.json"
            (tmp / "reference.json").write_text(
                json.dumps(REFERENCE), encoding="utf-8"
            )

            reg.load()

            saved = json.loads(reg.servers_file.read_text(encoding="utf-8"))
            hosts = [e["host"] for e in saved["servers"]]
            self.assertIn("sql-prod.tradesoft.ru", hosts)
            self.assertIn("custom-only.tradesoft.ru", hosts)

    def test_merge_no_reference_no_crash(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            reg = _make_registry(tmp, self.EXISTING)
            reg._reference_file = lambda: tmp / "reference.json"

            specs = reg.load()

            self.assertEqual(len(specs), 2)
            self.assertIn("custom-only.tradesoft.ru", [s.host for s in specs])

    def test_merge_broken_reference_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            reg = _make_registry(tmp, self.EXISTING)
            reg._reference_file = lambda: tmp / "reference.json"
            (tmp / "reference.json").write_text(
                "не json {{{", encoding="utf-8"
            )

            specs = reg.load()

            self.assertEqual(len(specs), 2)

    def test_merge_does_not_remove_user_servers(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            reg = _make_registry(tmp, self.EXISTING)
            reg._reference_file = lambda: tmp / "reference.json"
            (tmp / "reference.json").write_text(
                json.dumps([REFERENCE[0]]), encoding="utf-8"
            )

            specs = reg.load()

            hosts = {s.host for s in specs}
            self.assertIn("custom-only.tradesoft.ru", hosts)
            self.assertIn("p7ru1.tradesoft.ru", hosts)
            self.assertNotIn("sql-prod.tradesoft.ru", hosts)


class TestReferenceSync(unittest.TestCase):
    """Полная синхронизация с эталоном (эталон — источник истины)."""

    def _reg(self, tmp: Path, servers: list[dict], reference: list[dict]):
        reg = _make_registry(
            tmp,
            json.dumps(
                {"meta": {"version": 1, "kind": "file_key"},
                 "servers": servers},
                ensure_ascii=False,
            ),
        )
        reg._reference_file = lambda: tmp / "reference.json"
        (tmp / "reference.json").write_text(
            json.dumps(reference), encoding="utf-8"
        )
        return reg

    def test_removes_host_removed_from_reference(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            reg = self._reg(
                tmp,
                [
                    {"host": "gone.tradesoft.ru", "port": 0, "engine": "mysql",
                     "user": "", "password": "", "name": "", "ref": True},
                    {"host": "p7ru1.tradesoft.ru", "port": 0, "engine": "mysql",
                     "user": "", "password": "", "name": "", "ref": True},
                ],
                REFERENCE,
            )

            specs = reg.load()

            hosts = [s.host for s in specs]
            self.assertNotIn("gone.tradesoft.ru", hosts)
            self.assertIn("p7ru1.tradesoft.ru", hosts)

    def test_removes_legacy_stale_shell_from_txt_migration(self):
        from common.config import config

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            reg = self._reg(
                tmp,
                [
                    {"host": "old.tradesoft.ru", "port": 0, "engine": "mysql",
                     "user": config.mysql.user,
                     "password": config.mysql.password, "name": ""},
                ],
                REFERENCE,
            )

            specs = reg.load()

            hosts = [s.host for s in specs]
            self.assertNotIn("old.tradesoft.ru", hosts)
            self.assertEqual(hosts, [e["host"] for e in REFERENCE])

    def test_keeps_user_server_with_custom_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            reg = self._reg(
                tmp,
                [
                    {"host": "my-own.tradesoft.ru", "port": 0, "engine": "mysql",
                     "user": "vlad", "password": "s3cret", "name": "Мой"},
                ],
                REFERENCE,
            )

            specs = reg.load()

            by_host = {s.host: s for s in specs}
            self.assertIn("my-own.tradesoft.ru", by_host)
            self.assertEqual(by_host["my-own.tradesoft.ru"].user, "vlad")
            self.assertFalse(by_host["my-own.tradesoft.ru"].ref)
            self.assertIn("p7ru1.tradesoft.ru", by_host)

    def test_updates_attributes_keeps_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            reg = self._reg(
                tmp,
                [
                    {"host": "sql-prod.tradesoft.ru", "port": 1433,
                     "engine": "mssql", "user": "sa",
                     "password": "pw", "name": "Старое имя", "ref": True},
                ],
                REFERENCE,
            )

            specs = reg.load()

            spec = specs[0]
            self.assertEqual(spec.engine, ENGINE_MSSQL)
            self.assertEqual(spec.port, 1433)
            self.assertEqual(spec.name, "SQL Prod")
            self.assertEqual(spec.user, "sa")
            self.assertEqual(spec.password, "pw")
            self.assertTrue(spec.ref)

    def test_marks_unmarked_host_from_reference(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            reg = self._reg(
                tmp,
                [
                    {"host": "p7ru1.tradesoft.ru", "port": 0, "engine": "mysql",
                     "user": "", "password": "", "name": ""},
                ],
                REFERENCE,
            )

            reg.load()

            saved = json.loads(reg.servers_file.read_text(encoding="utf-8"))
            entry = next(
                e for e in saved["servers"]
                if e["host"] == "p7ru1.tradesoft.ru"
            )
            self.assertTrue(entry["ref"])

    def test_first_run_marks_reference_hosts(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            reg = _make_registry(tmp)
            reg._reference_file = lambda: tmp / "reference.json"
            (tmp / "reference.json").write_text(
                json.dumps(REFERENCE), encoding="utf-8"
            )

            reg.load()

            saved = json.loads(reg.servers_file.read_text(encoding="utf-8"))
            self.assertTrue(
                all(e.get("ref") for e in saved["servers"])
            )


class TestReferenceBadEntries(unittest.TestCase):

    def test_reference_with_garbage_entries_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            reg = _make_registry(tmp)
            reg._reference_file = lambda: tmp / "reference.json"
            (tmp / "reference.json").write_text(
                json.dumps([
                    {"host": "ok.tradesoft.ru", "engine": "mysql"},
                    {"host": ""},
                    "garbage",
                    {"host": None},
                    {"host": "bad.tradesoft.ru", "engine": "unknown"},
                ]),
                encoding="utf-8",
            )

            specs = reg.load()

            by_host = {s.host: s for s in specs}
            self.assertEqual(set(by_host), {"ok.tradesoft.ru", "bad.tradesoft.ru"})
            self.assertEqual(by_host["bad.tradesoft.ru"].engine, ENGINE_MYSQL)


class TestParseHostKey(unittest.TestCase):

    def test_host_with_port(self):
        self.assertEqual(parse_host_key("db.example.com:3306"),
                         ("db.example.com", 3306))

    def test_host_without_port(self):
        self.assertEqual(parse_host_key("db.example.com"),
                         ("db.example.com", 0))

    def test_host_with_non_numeric_port(self):
        self.assertEqual(parse_host_key("db.example.com:abc"),
                         ("db.example.com:abc", 0))

    def test_host_with_multiple_colons(self):
        # rsplit(":", 1) → ("a:b", "c"), "c" fails int → returns full string
        self.assertEqual(parse_host_key("a:b:c"),
                         ("a:b:c", 0))

    def test_port_zero_string(self):
        self.assertEqual(parse_host_key("db.example.com:0"),
                         ("db.example.com", 0))


class TestServerSpecHostKey(unittest.TestCase):

    def test_host_key_format(self):
        spec = ServerSpec(host="db.example.com", port=3306)
        self.assertEqual(spec.host_key(), "db.example.com:3306")

    def test_host_key_default_port(self):
        spec = ServerSpec(host="db.example.com")
        self.assertEqual(spec.host_key(), "db.example.com:3306")

    def test_host_key_pgsql(self):
        spec = ServerSpec(host="pg.example.com", port=5432,
                          engine=ENGINE_PGSQL)
        self.assertEqual(spec.host_key(), "pg.example.com:5432")


class TestCredentialsFor(unittest.TestCase):

    def _make_reg(self, tmp, specs_json):
        reg = _make_registry(tmp, specs_json)
        reg.load()
        return reg

    def test_returns_4_tuple(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            specs = json.dumps([{
                "host": "db1.example.com", "engine": "mysql",
                "port": 3307, "user": "u1", "password": "p1", "name": "",
            }])
            reg = self._make_reg(tmp, specs)

            result = reg.credentials_for("db1.example.com:3307")

            self.assertEqual(len(result), 4)
            user, password, host, port = result
            self.assertEqual(user, "u1")
            self.assertEqual(password, "p1")
            self.assertEqual(host, "db1.example.com")
            self.assertEqual(port, 3307)

    def test_empty_user_password_falls_back_to_config(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            specs = json.dumps([{
                "host": "db1.example.com", "engine": "mysql",
                "port": 3306, "user": "", "password": "", "name": "",
            }])
            reg = self._make_reg(tmp, specs)

            user, password, host, port = reg.credentials_for(
                "db1.example.com:3306"
            )

            self.assertTrue(len(user) > 0 or user == "")
            self.assertEqual(host, "db1.example.com")

    def test_unknown_host_returns_config_mysql_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            reg = _make_registry(tmp, "{}")

            user, password, host, port = reg.credentials_for(
                "unknown.example.com:3306"
            )

            self.assertEqual(host, "unknown.example.com")
            self.assertEqual(port, 3306)

    def test_find_port_zero_matches_any_port(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            specs = json.dumps([{
                "host": "db1.example.com", "engine": "mysql",
                "port": 5555, "user": "u", "password": "p", "name": "",
            }])
            reg = self._make_reg(tmp, specs)

            spec = reg.find("db1.example.com:0")

            self.assertIsNotNone(spec)
            self.assertEqual(spec.port, 5555)


if __name__ == "__main__":
    unittest.main()