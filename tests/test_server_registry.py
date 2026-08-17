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
            self.assertEqual(old.name, "p7ru1")
            custom = by_host["custom-only.tradesoft.ru"]
            self.assertEqual(custom.name, "Мой сервер")
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


if __name__ == "__main__":
    unittest.main()