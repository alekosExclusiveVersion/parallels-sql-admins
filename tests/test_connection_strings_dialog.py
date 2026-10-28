"""
tests/test_connection_strings_dialog.py

Экспорт строк подключения в файл: файл содержит пароли в открытом
виде, поэтому после записи права должны сужаться до владельца (0600).
"""

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QFileDialog

from common.server_registry import ServerSpec, registry
from gui.connection_strings_dialog import ConnectionStringsDialog
from gui.widgets.copyable_alert import CopyableMessageBox


class TestExportToFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        self._old_file = registry.servers_file
        self._old_specs = registry._specs
        self._old_loaded = registry._loaded

        registry.servers_file = Path(self._tmp.name) / "servers.json"
        registry._specs = [
            ServerSpec(
                host="db.example.com",
                port=3306,
                engine="mysql",
                user="dbuser",
                password="dbpass",
                name="example",
            )
        ]
        registry._loaded = True
        self.addCleanup(self._restore_registry)

        dialog = ConnectionStringsDialog()
        self.addCleanup(lambda: (dialog.close(), dialog.deleteLater()))
        self.dialog = dialog

    def _restore_registry(self):
        registry.servers_file = self._old_file
        registry._specs = self._old_specs
        registry._loaded = self._old_loaded

    def test_export_writes_owner_only_file(self):
        target = Path(self._tmp.name) / "connections.uri"

        with patch.object(
            QFileDialog, "getSaveFileName", return_value=(str(target), "")
        ), patch.object(CopyableMessageBox, "information", return_value=None):
            self.dialog._export_to_file()

        self.assertTrue(target.exists(), "файл экспорта не создан")
        self.assertIn(
            "mysql://dbuser:dbpass@db.example.com:3306",
            target.read_text(encoding="utf-8"),
        )

        if os.name != "nt":
            mode = stat.S_IMODE(target.stat().st_mode)
            self.assertEqual(mode, 0o600, f"права файла экспорта: {oct(mode)}")

    def test_export_cancelled_writes_nothing(self):
        target = Path(self._tmp.name) / "cancelled.uri"

        with patch.object(
            QFileDialog, "getSaveFileName", return_value=("", "")
        ):
            self.dialog._export_to_file()

        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
