"""
tests/test_servers_tree.py

Тесты двухфазной загрузки для дерева серверов:
- имена БД (SHOW DATABASES) показываются сразу, размеры и таблицы
  приходят одним запросом (server_catalog) и дописываются к узлам;
- кэш таблиц сервера позволяет раскрывать БД без отдельного запроса;
- refresh_sizes обновляет данные без сброса дерева.
"""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import backend.db_sizes_worker as dw
from common.mysql_client import mysql
from common.server_registry import registry
from gui.servers_tree import ServersTree, _ENGINE_ROLE


class FakeSizesMySQL:
    def __init__(self):
        self.databases = ["ar_a", "ar_b"]
        self.sizes = {"ar_a": 1000, "ar_b": 2000}
        self.tables = {
            "ar_a": [("t1", 600), ("t2", 400)],
            "ar_b": [("t3", 2000)],
        }

    def list_all_databases(self, server):
        return list(self.databases)

    def server_catalog(self, server):
        return dict(self.sizes), {
            db: list(t) for db, t in self.tables.items()
        }

    def database_table_sizes(self, server, database):
        return list(self.tables.get(database, []))


class TestDbSizesWorker(unittest.TestCase):
    def setUp(self):
        # Реестр серверов не должен трогать реальные файлы в тестах.
        self._tmp = Path(tempfile.mkdtemp())
        registry.servers_file = self._tmp / "servers.json"
        registry.key_file = self._tmp / "servers.key"
        registry._loaded = False

        self.fake = FakeSizesMySQL()
        self.patcher = patch.object(mysql, "list_all_databases",
                                    self.fake.list_all_databases)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _patch_catalog(self, side_effect=None, table_effect=None):
        patchers = [
            patch.object(mysql, "server_catalog",
                         side_effect if side_effect
                         else self.fake.server_catalog),
            patch.object(mysql, "database_table_sizes",
                         table_effect if table_effect
                         else self.fake.database_table_sizes),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def _make_worker(self):
        worker = dw.DbSizesWorker()
        self.addCleanup(worker.stop)
        return worker

    def _wait_until(self, events, count, timeout=3.0):
        deadline = time.monotonic() + timeout
        while len(events) < count and time.monotonic() < deadline:
            time.sleep(0.01)
        return len(events)

    def _direct(self, signal, handler):
        signal.connect(handler, Qt.ConnectionType.DirectConnection)

    def test_request_databases_emits_names_sizes_tables(self):
        self._patch_catalog()
        worker = self._make_worker()
        events = []

        self._direct(
            worker.databases_names,
            lambda s, n: events.append(("names", s, n)),
        )
        self._direct(
            worker.databases,
            lambda s, d: events.append(("sizes", s, d)),
        )
        self._direct(
            worker.server_tables,
            lambda s, t: events.append(("tables", s, t)),
        )

        worker.request_databases(["srv1"])
        self._wait_until(events, 3)

        kinds = [e[0] for e in events]
        self.assertEqual(kinds[:3], ["names", "sizes", "tables"])
        self.assertEqual(events[0][2], ["ar_a", "ar_b"])
        self.assertEqual(events[1][2], {"ar_a": 1000, "ar_b": 2000})
        self.assertEqual(events[2][2], self.fake.tables)

    def test_catalog_failure_still_shows_names(self):
        def boom(server):
            raise RuntimeError("boom")

        self._patch_catalog(side_effect=boom)
        worker = self._make_worker()
        events = []

        self._direct(
            worker.databases_names,
            lambda s, n: events.append(("names", s, n)),
        )
        self._direct(worker.error, lambda *a: events.append(("error", a)))

        worker.request_databases(["srv1"])
        self._wait_until(events, 2)

        self.assertEqual(events[0][0], "names")
        self.assertTrue(any(e[0] == "error" for e in events))

    def test_refresh_sizes_emits_sizes_and_tables(self):
        self._patch_catalog()
        worker = self._make_worker()
        events = []

        self._direct(
            worker.databases,
            lambda s, d: events.append(("sizes", s)),
        )
        self._direct(
            worker.server_tables,
            lambda s, t: events.append(("tables", s)),
        )

        worker.refresh_sizes(["srv1"])
        self._wait_until(events, 2)

        self.assertEqual([e[0] for e in events], ["sizes", "tables"])

    def test_request_tables_fallback(self):
        self._patch_catalog()
        worker = self._make_worker()
        events = []

        self._direct(worker.tables, lambda *a: events.append(("tables", a)))

        worker.request_tables("srv1", "ar_b")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][1], ("srv1", "ar_b", [("t3", 2000)]))

    def test_stop_prevents_processing(self):
        worker = self._make_worker()
        events = []
        self._direct(
            worker.databases_names,
            lambda *a: events.append(("names", a)),
        )
        worker.stop()
        worker.request_databases(["srv1"])
        self.assertEqual(events, [])

    def test_mssql_server_uses_mssql_client(self):
        from common.mssql_client import mssql
        from common.server_registry import ServerSpec

        spec = ServerSpec(host="mssql1", engine="mssql")

        with patch.object(registry, "find", return_value=spec):
            with patch.object(
                mssql,
                "list_all_databases",
                return_value=["ar_a"],
            ), patch.object(
                mssql,
                "server_catalog",
                return_value=({"ar_a": 1000}, {}),
            ):
                worker = self._make_worker()
                events = []

                self._direct(
                    worker.databases_names,
                    lambda s, n: events.append(("names", s, n)),
                )
                self._direct(
                    worker.databases,
                    lambda s, d: events.append(("sizes", s, d)),
                )
                self._direct(
                    worker.server_tables,
                    lambda s, t: events.append(("tables", s, t)),
                )

                worker.request_databases(["mssql1"])
                self._wait_until(events, 3)

        self.assertEqual(events[0], ("names", "mssql1", ["ar_a"]))
        self.assertEqual(events[1], ("sizes", "mssql1", {"ar_a": 1000}))
        self.assertEqual(events[2], ("tables", "mssql1", {}))


class TestServersTree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_apply_databases_then_sizes_in_place(self):
        tree = ServersTree()
        tree.set_servers(["srv1"])
        srv = tree.topLevelItem(0)

        tree.apply_databases("srv1", ["ar_a", "ar_b"])

        self.assertEqual(srv.childCount(), 2)
        self.assertEqual(tree.db_name(srv.child(0)), "ar_a")
        self.assertEqual(srv.child(0).text(0), "ar_a")
        self.assertEqual(srv.child(0).child(0).text(0), "…")

        tree.apply_sizes("srv1", {"ar_a": 1000, "ar_b": 2000})

        self.assertIn("srv1", srv.text(0))
        self.assertEqual(srv.child(0).text(0), "ar_a  (1000.0 B)")
        self.assertEqual(srv.child(1).text(0), "ar_b  (2.0 KB)")
        # узлы не пересоздавались — placeholder таблиц сохранён
        self.assertEqual(srv.child(0).childCount(), 1)
        self.assertEqual(srv.child(0).child(0).text(0), "…")

    def test_db_node_carries_its_server_key(self):
        """Регрессия: узел БД хранит host-ключ сервера в _SERVER_ROLE,
        поэтому контекстное меню (drop/detach) разрешает сервер из самого
        узла и не зависит от item.parent()."""
        tree = ServersTree()
        tree.set_servers([("Name", "h1:1433", "mssql")])
        srv = tree.topLevelItem(0)

        tree.apply_databases("h1:1433", ["ar_a"])

        db = srv.child(0)
        self.assertEqual(tree.db_name(db), "ar_a")
        # узел БД несёт host-ключ сервера на самом себе
        self.assertEqual(ServersTree.db_server_name(db), "h1:1433")
        # даже если родитель по какой-то причине не несёт host (баг дерева),
        # контекстное меню берёт ключ с узла БД и не теряет сервер
        srv.setData(0, Qt.UserRole, "")
        self.assertEqual(
            ServersTree.db_server_name(db) or ServersTree.server_name(db.parent()),
            "h1:1433",
        )

    def test_db_expand_uses_tables_cache(self):
        tree = ServersTree()
        tree.set_servers(["srv1"])
        srv = tree.topLevelItem(0)

        requests = []
        tree.tablesRequested.connect(
            lambda s, d: requests.append((s, d))
        )

        tree.apply_databases("srv1", ["ar_a", "ar_b"])
        tree.apply_server_tables("srv1", {
            "ar_a": [("t1", 600), ("t2", 400)],
            "ar_b": [("t3", 2000)],
        })

        db = srv.child(0)
        db.setExpanded(True)

        self.assertEqual(requests, [], "запросов к таблицам быть не должно")
        self.assertEqual(db.childCount(), 2)
        self.assertEqual(tree.table_name(db.child(0)), "t1")
        self.assertEqual(db.child(0).text(0), "t1  (600.0 B)")

    def test_db_expand_without_cache_requests_tables(self):
        tree = ServersTree()
        tree.set_servers(["srv1"])
        srv = tree.topLevelItem(0)

        requests = []
        tree.tablesRequested.connect(
            lambda s, d: requests.append((s, d))
        )

        tree.apply_databases("srv1", ["ar_a"])
        db = srv.child(0)
        db.setExpanded(True)

        self.assertEqual(requests, [("srv1", "ar_a")])

    def test_apply_sizes_without_names_builds_children(self):
        tree = ServersTree()
        tree.set_servers(["srv1"])
        srv = tree.topLevelItem(0)

        tree.apply_sizes("srv1", {"ar_a": 1000})

        self.assertEqual(srv.childCount(), 1)
        self.assertEqual(tree.db_name(srv.child(0)), "ar_a")
        self.assertEqual(srv.child(0).text(0), "ar_a  (1000.0 B)")

    def test_apply_databases_no_databases(self):
        tree = ServersTree()
        tree.set_servers(["srv1"])
        srv = tree.topLevelItem(0)

        tree.apply_databases("srv1", [])

        self.assertEqual(srv.childCount(), 1)
        self.assertEqual(srv.child(0).text(0), "Нет БД")

    def test_set_servers_with_display_name(self):
        tree = ServersTree()
        tree.set_servers([("Prod", "db1.example.com")])

        srv = tree.topLevelItem(0)

        # host скрыт из списка: показывается только имя
        self.assertEqual(srv.text(0), "Prod")
        self.assertEqual(tree.display_name(srv), "Prod")
        self.assertEqual(tree.server_name(srv), "db1.example.com")
        # host доступен подсказкой при наведении
        self.assertEqual(srv.toolTip(0), "db1.example.com")

    def test_set_servers_without_name_shows_host(self):
        tree = ServersTree()
        tree.set_servers([("db1.example.com", "db1.example.com")])

        srv = tree.topLevelItem(0)

        self.assertEqual(srv.text(0), "db1.example.com")
        self.assertEqual(srv.toolTip(0), "")

    def test_set_servers_stores_engine(self):
        tree = ServersTree()
        tree.set_servers([("M", "h1", "mssql")])

        item = tree.topLevelItem(0)
        self.assertEqual(item.data(0, _ENGINE_ROLE), "mssql")

    def test_set_servers_engine_icon_mssql(self):
        tree = ServersTree()
        tree.set_servers([("M", "h1", "mssql")])

        item = tree.topLevelItem(0)
        self.assertEqual(tree._server_icon_key(item), "server")

    def test_set_servers_engine_icon_mysql(self):
        tree = ServersTree()
        tree.set_servers([("M", "h1", "mysql")])

        item = tree.topLevelItem(0)
        self.assertEqual(tree._server_icon_key(item), "dns")

    def test_set_servers_engine_icon_pgsql(self):
        tree = ServersTree()
        tree.set_servers([("P", "h1", "pgsql")])

        item = tree.topLevelItem(0)
        self.assertEqual(tree._server_icon_key(item), "account_tree")

    def test_set_servers_engine_icon_fallback(self):
        tree = ServersTree()
        tree.set_servers([("O", "h1", "oracle"), ("P", "h2")])

        self.assertEqual(tree._server_icon_key(tree.topLevelItem(0)), "server")
        self.assertEqual(tree._server_icon_key(tree.topLevelItem(1)), "server")

    def test_server_icon_non_null_per_engine(self):
        tree = ServersTree()
        tree.set_servers([
            ("M", "h1", "mysql"),
            ("S", "h2", "mssql"),
            ("P", "h3", "pgsql"),
            ("O", "h4", "oracle"),
        ])
        for i in range(4):
            item = tree.topLevelItem(i)
            qicon = tree._server_icon(item)
            self.assertFalse(qicon.isNull(), f"icon null for row {i}")

    def test_set_servers_reset_sizes_keeps_engine_icon(self):
        tree = ServersTree()
        tree.set_servers([("M", "h1", "mssql")])

        item = tree.topLevelItem(0)
        tree.reset_sizes()

        self.assertEqual(tree._server_icon_key(item), "server")

    def test_retheme_icons_keeps_server_engine_key(self):
        tree = ServersTree()
        tree.set_servers([
            ("MySQL", "h1", "mysql"),
            ("MSSQL", "h2", "mssql"),
            ("Oracle", "h3", "oracle"),
        ])
        tree.apply_databases("h1", ["db_a"])
        tree.apply_server_tables("h1", {"db_a": [("t1", 100)]})

        def find(text):
            for i in range(tree.topLevelItemCount()):
                if tree.topLevelItem(i).text(0) == text:
                    return tree.topLevelItem(i)
            self.fail(f"узел {text} не найден")

        mysql, mssql, oracle = find("MySQL"), find("MSSQL"), find("Oracle")
        mysql.setExpanded(True)
        mysql.child(0).setExpanded(True)

        tree.retheme_icons()

        self.assertEqual(tree._server_icon_key(mysql), "dns")
        self.assertEqual(tree._server_icon_key(mssql), "server")
        self.assertEqual(tree._server_icon_key(oracle), "server")
        self.assertFalse(mysql.icon(0).isNull())
        self.assertFalse(mysql.child(0).icon(0).isNull())

    def test_apply_sizes_keeps_display_name(self):
        tree = ServersTree()
        tree.set_servers([("Prod", "db1")])
        srv = tree.topLevelItem(0)

        tree.apply_sizes("db1", {"ar_a": 1000})

        self.assertTrue(
            srv.text(0).startswith("Prod  (1000.0 B)")
        )
        self.assertEqual(tree.server_name(srv), "db1")

    def test_apply_databases_keeps_display_name(self):
        tree = ServersTree()
        tree.set_servers([("Prod", "db1")])
        srv = tree.topLevelItem(0)

        tree.apply_databases("db1", ["ar_a"])

        self.assertEqual(srv.text(0), "Prod")
        self.assertEqual(tree.server_name(srv), "db1")

    # ----------------------------------------------------------
    # Сортировка серверов, БД и таблиц
    # ----------------------------------------------------------

    def test_auto_sorting_is_disabled(self):
        tree = ServersTree()
        self.assertFalse(tree.isSortingEnabled())

    def test_servers_keep_insertion_order(self):
        # Группировка по движку/алфавиту выполняется наверху
        # (MainWindow._load_servers → sort_server_labels), дерево сохраняет
        # переданный порядок.
        tree = ServersTree()
        tree.set_servers([
            ("Zeta", "z.example.com"),
            ("Alpha", "a.example.com"),
            ("Mid", "m.example.com"),
        ])

        texts = [
            tree.topLevelItem(i).text(0)
            for i in range(tree.topLevelItemCount())
        ]

        self.assertEqual(texts, ["Zeta", "Alpha", "Mid"])

    def test_databases_are_sorted(self):
        tree = ServersTree()
        tree.set_servers(["srv1"])
        tree.apply_databases("srv1", ["ar_b", "ar_a", "ar_c"])

        srv = tree.topLevelItem(0)
        dbs = [
            tree.db_name(srv.child(i))
            for i in range(srv.childCount())
        ]

        self.assertEqual(dbs, ["ar_a", "ar_b", "ar_c"])

    def test_tables_are_sorted(self):
        tree = ServersTree()
        tree.set_servers(["srv1"])
        tree.apply_databases("srv1", ["ar_a"])
        srv = tree.topLevelItem(0)
        db_item = srv.child(0)

        tree.apply_tables("srv1", "ar_a", [
            ("t2", 100),
            ("t1", 200),
            ("t3", 50),
        ])

        tables = [
            db_item.child(i).text(0)
            for i in range(db_item.childCount())
        ]

        self.assertEqual(tables, sorted(tables))

    def test_placeholder_does_not_break_sorting_after_sizes(self):
        tree = ServersTree()
        tree.set_servers(["srv1"])
        tree.apply_databases("srv1", ["ar_b", "ar_a"])
        tree.apply_sizes("srv1", {"ar_a": 1000, "ar_b": 2000})

        srv = tree.topLevelItem(0)
        dbs = [
            tree.db_name(srv.child(i))
            for i in range(srv.childCount())
        ]

        self.assertEqual(dbs, ["ar_a", "ar_b"])
        # размеры дописаны к отсортированным узлам
        self.assertTrue(srv.child(0).text(0).startswith("ar_a  ("))


if __name__ == "__main__":
    unittest.main()
