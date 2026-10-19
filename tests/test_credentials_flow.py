"""
tests/test_credentials_flow.py

Тесты запроса учётных данных сервера:

- ServerRegistry.needs_credentials() — когда нужен логин/пароль;
- ServerRegistry.set_credentials() — сохранение в servers.json vs сессия;
- is_auth_error() — распознавание ошибки входа по сообщению СУБД;
- ConnectionPool.close_host() — сброс соединений хоста после смены
  реквизитов (простаивающие закрываются, занятые — при release);
- reset_connections() — диспетчеризация по движку сервера.
"""

import json
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import common.server_registry as registry_module
from common.db_errors import is_auth_error
from common.mysql_client import MySQLClient
from common.server_registry import (
    ENGINE_MSSQL,
    ENGINE_MYSQL,
    ENGINE_PGSQL,
    ENGINE_SQLITE,
    ServerRegistry,
    reset_connections,
)


class _StubVault:
    unlocked = True
    meta = {"version": 1, "kind": "file_key"}

    def encrypt(self, value: str) -> str:
        return value

    def decrypt(self, value: str) -> str:
        return value


def _make_registry(tmp: Path, specs: list | None = None) -> ServerRegistry:
    reg = ServerRegistry()
    reg.servers_file = tmp / "servers.json"
    reg.key_file = tmp / "servers.key"
    reg.backups_dir = tmp / "backups"
    reg.vault = _StubVault()
    reg._reference_file = lambda: tmp / "reference.json"
    reg.servers_file.write_text(
        json.dumps({
            "meta": {"version": 1, "kind": "file_key"},
            "servers": specs or [],
        }),
        encoding="utf-8",
    )
    return reg


def _global_cfg(user: str = "", password: str = "", port: int = 3306):
    def section(default_port):
        return SimpleNamespace(
            user=user, password=password, port=default_port,
        )

    return SimpleNamespace(
        mysql=section(port),
        mssql=section(1433),
        pgsql=section(5432),
        sqlite=section(0),
        security=SimpleNamespace(backup_count=3),
    )


def _spec(host="db1.example.com", engine=ENGINE_MYSQL, user="", password=""):
    return {
        "host": host,
        "engine": engine,
        "port": 0,
        "user": user,
        "password": password,
        "name": "DB1",
    }


class TestNeedsCredentials(unittest.TestCase):

    def _check(self, specs, host_key, global_cfg, expected):
        with tempfile.TemporaryDirectory() as td:
            reg = _make_registry(Path(td), specs)
            with patch.object(registry_module, "config", global_cfg):
                self.assertIs(reg.needs_credentials(host_key), expected)

    def test_complete_credentials_not_needed(self):
        self._check(
            [_spec(user="u", password="p")],
            "db1.example.com:3306",
            _global_cfg(),
            False,
        )

    def test_empty_password_needs_credentials(self):
        self._check(
            [_spec(user="u", password="")],
            "db1.example.com:3306",
            _global_cfg(),
            True,
        )

    def test_empty_user_needs_credentials(self):
        self._check(
            [_spec(user="", password="p")],
            "db1.example.com:3306",
            _global_cfg(),
            True,
        )

    def test_both_empty_needs_credentials(self):
        self._check(
            [_spec()],
            "db1.example.com:3306",
            _global_cfg(),
            True,
        )

    def test_global_fallback_covers_missing(self):
        self._check(
            [_spec()],
            "db1.example.com:3306",
            _global_cfg(user="global", password="global-secret"),
            False,
        )

    def test_sqlite_never_needs_credentials(self):
        self._check(
            [_spec(engine=ENGINE_SQLITE)],
            "db1.example.com:0",
            _global_cfg(),
            False,
        )

    def test_unknown_host_never_needs_credentials(self):
        self._check(
            [_spec(user="u", password="p")],
            "unknown.example.com:3306",
            _global_cfg(),
            False,
        )

    def test_mssql_and_pgsql_engines(self):
        self._check(
            [_spec(engine=ENGINE_MSSQL)],
            "db1.example.com:1433",
            _global_cfg(),
            True,
        )
        self._check(
            [_spec(engine=ENGINE_PGSQL)],
            "db1.example.com:5432",
            _global_cfg(),
            True,
        )


class TestSetCredentials(unittest.TestCase):

    def test_persist_writes_to_servers_json(self):
        with tempfile.TemporaryDirectory() as td:
            reg = _make_registry(Path(td), [_spec()])
            with patch.object(registry_module, "config", _global_cfg()):
                saved = reg.set_credentials(
                    "db1.example.com:3306", "alice", "secret", persist=True,
                )

            self.assertTrue(saved)

            raw = json.loads(reg.servers_file.read_text(encoding="utf-8"))
            entry = [
                s for s in raw["servers"] if s["host"] == "db1.example.com"
            ][0]
            self.assertEqual(entry["user"], "alice")
            self.assertEqual(entry["password"], "secret")

    def test_without_persist_keeps_memory_only(self):
        with tempfile.TemporaryDirectory() as td:
            reg = _make_registry(Path(td), [_spec()])
            before = reg.servers_file.read_text(encoding="utf-8")

            saved = reg.set_credentials(
                "db1.example.com:3306", "alice", "secret", persist=False,
            )

            self.assertFalse(saved)
            self.assertEqual(
                reg.servers_file.read_text(encoding="utf-8"), before,
            )
            self.assertEqual(reg.find("db1.example.com:3306").user, "alice")

    def test_locked_vault_keeps_memory_only(self):
        with tempfile.TemporaryDirectory() as td:
            reg = _make_registry(Path(td), [_spec()])
            reg.load()
            reg.vault.unlocked = False

            saved = reg.set_credentials(
                "db1.example.com:3306", "alice", "secret", persist=True,
            )

            self.assertFalse(saved)
            self.assertEqual(
                reg.find("db1.example.com:3306").password, "secret",
            )

    def test_unknown_host_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            reg = _make_registry(Path(td), [_spec()])

            self.assertFalse(
                reg.set_credentials(
                    "unknown.example.com:3306", "alice", "secret",
                )
            )

    def test_credentials_become_complete(self):
        with tempfile.TemporaryDirectory() as td:
            reg = _make_registry(Path(td), [_spec()])
            with patch.object(registry_module, "config", _global_cfg()):
                self.assertTrue(
                    reg.needs_credentials("db1.example.com:3306")
                )
                reg.set_credentials(
                    "db1.example.com:3306", "alice", "secret",
                )
                self.assertFalse(
                    reg.needs_credentials("db1.example.com:3306")
                )


class TestIsAuthError(unittest.TestCase):

    def test_mysql_access_denied(self):
        self.assertTrue(is_auth_error(
            "Access denied for user 'koshkin'@'10.0.0.5' "
            "(using password: NO)"
        ))

    def test_mysql_error_code(self):
        self.assertTrue(is_auth_error(
            "(1045, \"Access denied for user 'root'@'localhost'\")"
        ))

    def test_mssql_login_failed(self):
        self.assertTrue(is_auth_error(
            "(18456, b\"Login failed for user 'sa'.\")"
        ))

    def test_mssql_message(self):
        self.assertTrue(is_auth_error("Login failed for user 'sa'."))

    def test_pgsql_password_authentication(self):
        self.assertTrue(is_auth_error(
            'password authentication failed for user "postgres"'
        ))

    def test_network_error_is_not_auth(self):
        self.assertFalse(is_auth_error(
            "Не удалось установить соединение с сервером. "
            "Проверьте адрес, порт и доступность сервера."
        ))
        self.assertFalse(is_auth_error("(2003, \"Can't connect\")"))

    def test_permission_error_is_not_auth(self):
        self.assertFalse(is_auth_error(
            "permission denied for table deals"
        ))
        self.assertFalse(is_auth_error(
            "Access denied; you need (at least one of) the SUPER privilege"
        ))

    def test_empty_message(self):
        self.assertFalse(is_auth_error(""))
        self.assertFalse(is_auth_error(None))


class _FakeConn:
    def __init__(self, host):
        self.host = host
        self.closed = False

    def close(self):
        self.closed = True

    def ping(self, reconnect=False):
        return None


class _ConnFactory:
    def __init__(self):
        self.opened = []

    def open(self, host, database=None):
        conn = _FakeConn(host)
        self.opened.append(conn)
        return conn


class TestPoolCloseHost(unittest.TestCase):

    def setUp(self):
        self.factory = _ConnFactory()
        self.client = MySQLClient()
        self.client._open_connection = self.factory.open

    def test_closes_idle_connections_of_host_only(self):
        with self.client.connect("h1", "db1"):
            pass
        with self.client.connect("h2", "db2"):
            pass

        conn_h1 = self.factory.opened[0]
        conn_h2 = self.factory.opened[1]

        affected = self.client.close_host("h1")

        self.assertEqual(affected, 1)
        self.assertTrue(conn_h1.closed)
        self.assertFalse(conn_h2.closed)

        with self.client.connect("h2", "db2") as reused:
            self.assertIs(reused, conn_h2)

    def test_in_use_connection_closed_on_release(self):
        with self.client.connect("h1", "db1") as conn:
            self.assertEqual(self.client.close_host("h1"), 1)
            self.assertFalse(conn.closed)

        self.assertTrue(conn.closed)
        self.assertEqual(self.client._pool.idle_count, 0)

    def test_other_hosts_untouched(self):
        with self.client.connect("h1", "db1"):
            pass
        with self.client.connect("h2", "db2"):
            pass

        self.assertEqual(self.client.close_host("h3"), 0)
        self.assertFalse(self.factory.opened[0].closed)
        self.assertFalse(self.factory.opened[1].closed)

    def test_matches_key_without_port(self):
        with self.client.connect("h1", "db1"):
            pass

        self.assertEqual(self.client.close_host("h1:3306"), 1)
        self.assertTrue(self.factory.opened[0].closed)

    def test_matches_key_with_port(self):
        with self.client.connect("h1:3306", "db1"):
            pass

        self.assertEqual(self.client.close_host("h1"), 1)
        self.assertTrue(self.factory.opened[0].closed)


class TestResetConnections(unittest.TestCase):

    def test_calls_client_close_host(self):
        calls = []

        class _Client:
            def close_host(self, host):
                calls.append(host)
                return 3

        with patch.object(
            registry_module, "client_for", lambda host: _Client(),
        ):
            self.assertEqual(reset_connections("h1:3306"), 3)

        self.assertEqual(calls, ["h1:3306"])

    def test_swallows_client_errors(self):
        class _Broken:
            def close_host(self, host):
                raise RuntimeError("boom")

        with patch.object(
            registry_module, "client_for", lambda host: _Broken(),
        ):
            self.assertEqual(reset_connections("h1:3306"), 0)


class _StatusBar:
    def __init__(self):
        self.text = ""

    def set_status(self, text):
        self.text = text


class _FakeSpec:
    def __init__(self, label, engine="mysql"):
        self.label = label
        self.user = ""
        self.engine = engine

    def display_name(self):
        return self.label


class _FakeRegistry:
    def __init__(self, needs=(), spec=None):
        self._needs = set(needs)
        self._spec = spec
        self.saved = []

    def needs_credentials(self, host_key):
        return host_key in self._needs

    def find(self, host_key):
        return self._spec

    def credentials_for(self, host_key):
        return "", "", host_key, 3306

    def set_credentials(self, host_key, user, password, persist=True):
        self.saved.append((host_key, user, password, persist))
        return bool(persist)


class _FakeDialog:
    Accepted = 1
    Rejected = 0

    result = Accepted
    remember_flag = True

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    def exec(self):
        return type(self).result

    def user(self):
        return "alice"

    def password(self):
        return "secret"

    def remember(self):
        return type(self).remember_flag


class _FakeWindow:
    def __init__(self):
        self.logs = []
        self.status_bar = _StatusBar()
        self._cred_retry_done = False
        self.panel = SimpleNamespace(current_host=lambda: "")
        self.vault_writable = True

    def append_log(self, level, message):
        self.logs.append((level, message))

    def _ensure_vault_for_write(self):
        return self.vault_writable


class TestMainWindowCredentials(unittest.TestCase):

    def setUp(self):
        from gui import main_window as mw

        self.mw = mw
        self.window = _FakeWindow()

        # Методы реального окна, которые вызываются внутри тестируемых.
        self.window._server_label = mw.MainWindow._server_label
        self.window._ensure_credentials = (
            mw.MainWindow._ensure_credentials.__get__(self.window)
        )
        self.window._skip_servers_without_credentials = (
            mw.MainWindow._skip_servers_without_credentials.__get__(
                self.window,
            )
        )
        self.window._prompt_credentials = (
            mw.MainWindow._prompt_credentials.__get__(self.window)
        )
        self.window._edit_server_credentials = (
            mw.MainWindow._edit_server_credentials.__get__(self.window)
        )

    def _patch(self, needs=(), spec=None):
        registry = _FakeRegistry(needs=needs, spec=spec)
        return patch.object(self.mw, "registry", registry), registry

    def test_skip_servers_without_credentials(self):
        ctx, registry = self._patch(
            needs={"b:3306"}, spec=_FakeSpec("B (b:3306)"),
        )
        with ctx:
            kept = self.mw.MainWindow._skip_servers_without_credentials(
                self.window, ["a:3306", "b:3306"], "Проверка",
            )

        self.assertEqual(kept, ["a:3306"])
        messages = " ".join(m for _, m in self.window.logs)
        self.assertIn("Проверка", messages)
        self.assertIn("B (b:3306)", messages)

    def test_skip_all_servers_have_credentials(self):
        ctx, _ = self._patch()
        with ctx:
            kept = self.mw.MainWindow._skip_servers_without_credentials(
                self.window, ["a:3306"], "Проверка",
            )

        self.assertEqual(kept, ["a:3306"])
        self.assertEqual(self.window.logs, [])

    def test_single_target_prompt_accepted(self):
        ctx, registry = self._patch(needs={"a:3306"})
        with ctx, patch.object(
            self.mw, "CredentialsDialog", _FakeDialog,
        ), patch.object(self.mw, "reset_connections") as reset:
            targets = self.mw.MainWindow._ensure_target_credentials(
                self.window, [("a:3306", "db1")],
            )

        self.assertEqual(targets, [("a:3306", "db1")])
        self.assertEqual(registry.saved, [("a:3306", "alice", "secret", True)])
        reset.assert_called_once_with("a:3306")

    def test_single_target_prompt_rejected(self):
        ctx, registry = self._patch(needs={"a:3306"})

        class _Rejected(_FakeDialog):
            result = _FakeDialog.Rejected

        with ctx, patch.object(
            self.mw, "CredentialsDialog", _Rejected,
        ), patch.object(self.mw, "reset_connections"):
            targets = self.mw.MainWindow._ensure_target_credentials(
                self.window, [("a:3306", "db1")],
            )

        self.assertEqual(targets, [])
        self.assertEqual(registry.saved, [])
        self.assertIn("учётные данные", self.window.status_bar.text)

    def test_multi_target_skips_without_prompt(self):
        ctx, _ = self._patch(
            needs={"b:3306"}, spec=_FakeSpec("B (b:3306)"),
        )
        with ctx, patch.object(self.mw, "CredentialsDialog") as dialog:
            targets = self.mw.MainWindow._ensure_target_credentials(
                self.window,
                [("a:3306", "db1"), ("b:3306", "db2")],
            )

        self.assertEqual(targets, [("a:3306", "db1")])
        dialog.assert_not_called()

    def test_retry_ignores_non_auth_error(self):
        with patch.object(
            self.mw.CopyableMessageBox, "question",
        ) as question:
            result = self.mw.MainWindow._offer_credentials_retry(
                self.window, "a:3306", "timeout expired",
            )

        self.assertFalse(result)
        question.assert_not_called()

    def test_retry_prompts_once_on_auth_error(self):
        self.window._ensure_credentials = lambda host, message="": True

        with patch.object(
            self.mw.CopyableMessageBox, "question",
            return_value=self.mw.QMessageBox.Yes,
        ) as question:
            first = self.mw.MainWindow._offer_credentials_retry(
                self.window, "a:3306",
                "Access denied for user 'koshkin'@'10.0.0.5'",
            )
            second = self.mw.MainWindow._offer_credentials_retry(
                self.window, "a:3306",
                "Access denied for user 'koshkin'@'10.0.0.5'",
            )

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(question.call_count, 1)

    def test_retry_declined_by_user(self):
        self.window._ensure_credentials = lambda host, message="": True

        with patch.object(
            self.mw.CopyableMessageBox, "question",
            return_value=self.mw.QMessageBox.No,
        ):
            result = self.mw.MainWindow._offer_credentials_retry(
                self.window, "a:3306", "Login failed for user 'sa'.",
            )

        self.assertFalse(result)
        self.assertTrue(self.window._cred_retry_done)

    def test_prompt_keeps_credentials_when_vault_locked(self):
        ctx, registry = self._patch(needs={"a:3306"})
        self.window.vault_writable = False

        with ctx, patch.object(
            self.mw, "CredentialsDialog", _FakeDialog,
        ), patch.object(self.mw, "reset_connections"):
            result = self.mw.MainWindow._prompt_credentials(
                self.window, "a:3306",
            )

        self.assertTrue(result)
        self.assertEqual(
            registry.saved, [("a:3306", "alice", "secret", False)],
        )

    def test_edit_server_credentials_prompts_always(self):
        ctx, registry = self._patch(
            needs=(), spec=_FakeSpec("DB1 (a:3306)"),
        )

        with ctx, patch.object(
            self.mw, "CredentialsDialog", _FakeDialog,
        ), patch.object(self.mw, "reset_connections"):
            self.mw.MainWindow._edit_server_credentials(
                self.window, "a:3306",
            )

        self.assertEqual(
            registry.saved, [("a:3306", "alice", "secret", True)],
        )

    def test_edit_server_credentials_ignores_unknown_host(self):
        ctx, registry = self._patch(needs=(), spec=None)

        with ctx, patch.object(self.mw, "CredentialsDialog") as dialog:
            self.mw.MainWindow._edit_server_credentials(
                self.window, "a:3306",
            )

        dialog.assert_not_called()
        self.assertEqual(registry.saved, [])

    def test_edit_server_credentials_ignores_sqlite(self):
        spec = _FakeSpec("Local", engine="sqlite")
        ctx, registry = self._patch(needs=(), spec=spec)

        with ctx, patch.object(self.mw, "CredentialsDialog") as dialog:
            self.mw.MainWindow._edit_server_credentials(
                self.window, "a:0",
            )

        dialog.assert_not_called()
        self.assertEqual(registry.saved, [])


class TestCredentialsMenu(unittest.TestCase):
    """Пункт «Учётные данные…» в контекстном меню дерева серверов."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        from gui.servers_tree import ServersTree

        self.tree = ServersTree()
        self.addCleanup(self.tree.deleteLater)
        self.addCleanup(self.tree.close)

    def _menu_actions(self, item, engine="mysql"):
        with patch("gui.servers_tree.registry") as reg:
            reg.engine.return_value = engine
            return self.tree._build_context_menu(item).actions()

    def test_credentials_action_present_and_emits_server(self):
        self.tree.set_servers([("DB1", "h1:3306", "mysql")])
        item = self.tree.topLevelItem(0)

        actions = self._menu_actions(item)
        matched = [
            a for a in actions if a.text() == "Учётные данные…"
        ]

        self.assertEqual(len(matched), 1)

        received = []
        self.tree.credentialsRequested.connect(received.append)
        matched[0].trigger()

        self.assertEqual(received, ["h1:3306"])

    def test_credentials_action_hidden_for_sqlite(self):
        self.tree.set_servers([("Local", "local.db", "sqlite")])
        item = self.tree.topLevelItem(0)

        texts = [
            a.text() for a in self._menu_actions(item, engine="sqlite")
        ]

        self.assertNotIn("Учётные данные…", texts)
        self.assertIn("Добавить сервер", texts)


if __name__ == "__main__":
    unittest.main()
