"""
tests/test_server_registry.py

Тесты реестра серверов: хранение/загрузка с шифрованием пароля в обоих
режимах защиты ключа (master_password / file_key), блокировка записи,
миграция из servers.txt, legacy-плоский формат, рееncryption (rekey),
резолв реквизитов по хосту, CRUD, построение SELECT с учётом синтаксиса СУБД.
"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from common.key_store import (
    BACKEND_FILE_KEY,
    BACKEND_MASTER_PASSWORD,
    VaultError,
    VaultLockedError,
    WrongMasterPasswordError,
)
from common.server_registry import (
    ENGINE_MSSQL,
    ENGINE_MYSQL,
    ENGINE_PGSQL,
    ServerSpec,
    build_select_sql,
    default_port,
    quote_ident,
    registry,
)
import common.server_registry as sreg


def fake_config(**overrides) -> SimpleNamespace:
    mysql = SimpleNamespace(
        user=overrides.get("user", "koshkin"),
        password=overrides.get("password", ""),
        port=3306,
    )
    mssql = SimpleNamespace(
        user=overrides.get("mssql_user", "sa"),
        password=overrides.get("mssql_password", ""),
        port=1433,
    )
    security = SimpleNamespace(
        backup_count=overrides.get("backup_count", 5),
        kdf_iterations=overrides.get("kdf_iterations", 1000),
    )
    advanced = SimpleNamespace(
        servers_file=str(overrides.get("servers_file", "servers.json")),
    )
    return SimpleNamespace(mysql=mysql, mssql=mssql, security=security, advanced=advanced)


class ServerRegistryTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())
        registry.servers_file = self._tmp / "servers.json"
        registry.key_file = self._tmp / "servers.key"
        registry.vault.lock()
        registry._loaded = False
        registry._specs = []
        registry.backups_dir = self._tmp / "backups"

        sreg.config = fake_config()
        registry.setup_vault(BACKEND_FILE_KEY)

    def _save(self, specs):
        registry.save(specs)

    def _reload(self):
        registry._loaded = False
        return registry.load()


class TestServerRegistryPersistence(ServerRegistryTestBase):

    def test_save_load_round_trip(self):
        self._save([
            ServerSpec(host="db1.example.com", engine=ENGINE_MYSQL,
                       user="u1", password="secret1"),
            ServerSpec(host="sql1.example.com", engine=ENGINE_MSSQL,
                       port=1433, user="sa", password="pass2"),
        ])

        specs = self._reload()
        self.assertEqual(len(specs), 2)

        by_host = {s.host: s for s in specs}
        self.assertEqual(by_host["db1.example.com"].user, "u1")
        self.assertEqual(by_host["db1.example.com"].password, "secret1")
        self.assertEqual(by_host["db1.example.com"].engine, ENGINE_MYSQL)
        self.assertEqual(by_host["sql1.example.com"].engine, ENGINE_MSSQL)
        self.assertEqual(by_host["sql1.example.com"].port, 1433)
        self.assertEqual(by_host["sql1.example.com"].password, "pass2")

    def test_password_encrypted_at_rest(self):
        self._save([
            ServerSpec(host="db1", engine=ENGINE_MYSQL,
                       user="u1", password="topsecret"),
        ])

        raw = registry.servers_file.read_text(encoding="utf-8")
        self.assertNotIn("topsecret", raw)
        self.assertIn("password", raw)
        self.assertIn("meta", raw)

    def test_file_key_round_trip_across_sessions(self):
        # Ключ живёт в servers.key; при «новой сессии» (vault сброшен)
        # он перечитывается из файла и пароль расшифровывается.
        self._save([ServerSpec(host="h1", user="u", password="pw")])

        registry.vault.lock()
        registry._loaded = False
        spec = registry.load()[0]
        self.assertEqual(spec.password, "pw")
        self.assertTrue(registry.key_file.exists())

    def test_corrupt_file_key_not_regenerated(self):
        # Повреждённый ключ — ошибка, а не новая генерация (защита от
        # молчаливой потери паролей).
        self._save([ServerSpec(host="h1", user="u", password="pw")])

        garbage = b"garbage-not-a-key"
        registry.key_file.write_bytes(garbage)
        registry.vault.lock()
        registry._loaded = False

        with self.assertRaises(VaultError):
            registry.load()

        self.assertEqual(registry.key_file.read_bytes(), garbage)

    def test_default_port_by_engine(self):
        self.assertEqual(default_port(ENGINE_MYSQL), 3306)
        self.assertEqual(default_port(ENGINE_MSSQL), 1433)

    def test_display_name(self):
        self.assertEqual(ServerSpec(host="h1").display_name(), "h1")
        self.assertEqual(
            ServerSpec(host="h1", name="Prod").display_name(),
            "Prod (h1)",
        )

    def test_ui_label_hides_host(self):
        self.assertEqual(ServerSpec(host="h1").ui_label(), "h1")
        self.assertEqual(
            ServerSpec(host="h1", name="Prod").ui_label(),
            "Prod",
        )


class TestMasterPassword(ServerRegistryTestBase):

    def setUp(self):
        super().setUp()
        registry.vault.lock()
        registry.setup_vault(BACKEND_MASTER_PASSWORD, "secret")

    def test_round_trip(self):
        self._save([ServerSpec(host="h", user="u", password="pw")])
        self.assertEqual(registry.find("h").password, "pw")

    def test_master_password_not_stored(self):
        self._save([ServerSpec(host="h", user="u", password="pw")])
        raw = registry.servers_file.read_text(encoding="utf-8")
        self.assertNotIn("secret", raw)
        self.assertNotIn("pw", raw)

    def test_wrong_password_raises(self):
        self._save([ServerSpec(host="h", user="u", password="pw")])
        registry.vault.lock()
        with self.assertRaises(WrongMasterPasswordError):
            registry.unlock_master("wrong")

    def test_needs_unlock_when_locked(self):
        self._save([ServerSpec(host="h", user="u", password="pw")])
        registry.vault.lock()
        self.assertTrue(registry.needs_unlock())

    def test_load_blocked_when_locked(self):
        self._save([ServerSpec(host="h", user="u", password="pw")])
        registry.vault.lock()
        registry._loaded = False
        with self.assertRaises(VaultLockedError):
            registry.load()

    def test_save_blocked_when_locked(self):
        # Защита от записи «пустых» паролей поверх нерасшифрованных данных.
        self._save([ServerSpec(host="h", user="u", password="pw")])
        registry.vault.lock()
        with self.assertRaises(VaultLockedError):
            registry.save([
                ServerSpec(host="h", user="u", password=""),
            ])


class TestRekey(ServerRegistryTestBase):

    def setUp(self):
        super().setUp()
        registry.setup_vault(BACKEND_FILE_KEY)

    def test_file_to_master(self):
        self._save([ServerSpec(host="h", user="u", password="pw")])

        registry.rekey(BACKEND_MASTER_PASSWORD, "newpass")

        raw = json.loads(registry.servers_file.read_text(encoding="utf-8"))
        self.assertEqual(raw["meta"]["kind"], BACKEND_MASTER_PASSWORD)

        registry.vault.lock()
        registry._loaded = False
        registry.unlock_master("newpass")
        self.assertEqual(registry.find("h").password, "pw")

    def test_master_to_file(self):
        registry.setup_vault(BACKEND_MASTER_PASSWORD, "old")
        self._save([ServerSpec(host="h", user="u", password="pw")])

        registry.rekey(BACKEND_FILE_KEY)

        raw = json.loads(registry.servers_file.read_text(encoding="utf-8"))
        self.assertEqual(raw["meta"]["kind"], BACKEND_FILE_KEY)

        registry.vault.lock()
        registry._loaded = False
        self.assertEqual(registry.find("h").password, "pw")


class TestLegacyFormat(ServerRegistryTestBase):

    def test_legacy_flat_list_loads_hosts_without_key(self):
        # Старый формат — список записей без меты. Без ключа пароли
        # недоступны, хосты загружаются.
        self._save([ServerSpec(host="h1", user="u", password="pw")])
        raw = json.loads(registry.servers_file.read_text(encoding="utf-8"))
        registry.servers_file.write_text(
            json.dumps(raw["servers"], ensure_ascii=False),
            encoding="utf-8",
        )

        registry.vault.lock()
        registry._loaded = False

        specs = registry.load()
        self.assertEqual([s.host for s in specs], ["h1"])
        self.assertEqual(specs[0].password, "")


class TestServerRegistryMigration(ServerRegistryTestBase):

    def test_migrate_from_servers_txt(self):
        txt = self._tmp / "servers.txt"
        txt.write_text(
            "p7ru1.example.com\np7ru2.example.com\n\n",
            encoding="utf-8",
        )

        with patch(
            "common.server_registry.config",
            fake_config(
                servers_file=str(registry.servers_file),
                user="koshkin",
                password="pw",
            ),
        ):
            specs = registry.load()

        self.assertEqual(len(specs), 2)
        self.assertEqual(specs[0].host, "p7ru1.example.com")
        self.assertEqual(specs[0].engine, ENGINE_MYSQL)
        self.assertEqual(specs[0].user, "koshkin")
        self.assertEqual(specs[0].password, "pw")

        # После миграции появился servers.json
        self.assertTrue(registry.servers_file.exists())


class TestServerRegistryLookup(ServerRegistryTestBase):

    def setUp(self):
        super().setUp()
        self._save([
            ServerSpec(host="m", engine=ENGINE_MYSQL, user="mu", password="mp"),
            ServerSpec(host="s", engine=ENGINE_MSSQL, user="su", password="sp"),
        ])

    def test_credentials_for_server(self):
        self.assertEqual(
            registry.credentials_for("m"),
            ("mu", "mp", 3306),
        )
        self.assertEqual(
            registry.credentials_for("s"),
            ("su", "sp", 1433),
        )

    def test_credentials_fallback_to_config(self):
        with patch(
            "common.server_registry.config",
            fake_config(user="global", password="gp"),
        ):
            self.assertEqual(
                registry.credentials_for("unknown"),
                ("global", "gp", 3306),
            )

    def test_credentials_fallback_empty_password_mysql(self):
        registry.add(
            ServerSpec(host="mempty", engine=ENGINE_MYSQL, user="mu", password="")
        )
        with patch(
            "common.server_registry.config",
            fake_config(user="global", password="gp"),
        ):
            self.assertEqual(
                registry.credentials_for("mempty"),
                ("mu", "gp", 3306),
            )

    def test_credentials_fallback_empty_password_mssql(self):
        registry.add(
            ServerSpec(host="sempty", engine=ENGINE_MSSQL, user="su", password="")
        )
        with patch(
            "common.server_registry.config",
            fake_config(password="gp", mssql_password="gps"),
        ):
            self.assertEqual(
                registry.credentials_for("sempty"),
                ("su", "gps", 1433),
            )

    def test_credentials_mysql_does_not_leak_mssql_password(self):
        registry.add(
            ServerSpec(host="m2", engine=ENGINE_MYSQL, user="mu2", password="")
        )
        with patch(
            "common.server_registry.config",
            fake_config(password="gp", mssql_password="gps"),
        ):
            self.assertEqual(
                registry.credentials_for("m2"),
                ("mu2", "gp", 3306),
            )

    def test_credentials_spec_password_wins_over_config(self):
        registry.add(
            ServerSpec(host="m3", engine=ENGINE_MYSQL, user="mu3", password="own")
        )
        with patch(
            "common.server_registry.config",
            fake_config(user="global", password="gp"),
        ):
            self.assertEqual(
                registry.credentials_for("m3"),
                ("mu3", "own", 3306),
            )

    def test_engine_lookup(self):
        self.assertEqual(registry.engine("m"), ENGINE_MYSQL)
        self.assertEqual(registry.engine("s"), ENGINE_MSSQL)
        self.assertEqual(registry.engine("unknown"), ENGINE_MYSQL)

    def test_add_update_remove(self):
        registry.add(ServerSpec(host="new", user="u", password="p"))
        self.assertIsNotNone(registry.find("new"))

        registry.update("new", ServerSpec(host="new2", user="u2", password="p2"))
        self.assertIsNone(registry.find("new"))
        self.assertEqual(registry.find("new2").user, "u2")

        self.assertTrue(registry.remove("new2"))
        self.assertFalse(registry.remove("new2"))


class TestServerRegistrySql(ServerRegistryTestBase):

    def test_quote_ident_mysql(self):
        self.assertEqual(quote_ident(ENGINE_MYSQL, "ar_ru"), "`ar_ru`")

    def test_quote_ident_mssql(self):
        self.assertEqual(quote_ident(ENGINE_MSSQL, "MyDB"), "[MyDB]")

    def test_quote_ident_pgsql(self):
        self.assertEqual(quote_ident(ENGINE_PGSQL, "users"), '"users"')
        self.assertEqual(
            quote_ident(ENGINE_PGSQL, 'weird"name'),
            '"weird""name"',
        )

    def test_build_select_mysql(self):
        sql = build_select_sql(ENGINE_MYSQL, "ar_ru", "users", 1000)
        self.assertEqual(sql, "SELECT * FROM `ar_ru`.`users` LIMIT 1000")

    def test_build_select_mssql(self):
        # Таблица без схемы → подставляется dbo: [db].[dbo].[table],
        # иначе [db].[users] интерпретируется как [db].[схема] и падает
        # с "Invalid object name".
        sql = build_select_sql(ENGINE_MSSQL, "MyDB", "users", 500)
        self.assertEqual(
            sql,
            "SELECT TOP 500 * FROM [MyDB].[dbo].[users]",
        )

    def test_build_select_mssql_with_schema(self):
        sql = build_select_sql(ENGINE_MSSQL, "MyDB", "sales.Orders", 100)
        self.assertEqual(
            sql,
            "SELECT TOP 100 * FROM [MyDB].[sales].[Orders]",
        )

    def test_build_select_mssql_escaped_bracket(self):
        sql = build_select_sql(ENGINE_MSSQL, "MyDB", "weird]name", 10)
        self.assertEqual(
            sql,
            "SELECT TOP 10 * FROM [MyDB].[dbo].[weird]]name]",
        )

    def test_build_select_pgsql(self):
        # Без схемы → public: "db"."public"."table", иначе "db"."table"
        # интерпретируется как "схема"."таблица" и падает
        # с "relation ... does not exist".
        sql = build_select_sql(ENGINE_PGSQL, "mydb", "users", 1000)
        self.assertEqual(
            sql,
            'SELECT * FROM "mydb"."public"."users" LIMIT 1000',
        )

    def test_build_select_pgsql_with_schema(self):
        sql = build_select_sql(ENGINE_PGSQL, "mydb", "sales.Orders", 100)
        self.assertEqual(
            sql,
            'SELECT * FROM "mydb"."sales"."Orders" LIMIT 100',
        )


if __name__ == "__main__":
    unittest.main()
