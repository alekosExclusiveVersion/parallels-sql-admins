"""
tests/test_logger.py

Тесты для common/logger.py: запись в run/errors/actions,
ротация по размеру и периодическая чистка старых файлов.
"""

import logging
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from common.logger import AppLogger
from common.config import config


class AppLoggerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        for logger_name in ("parallel-admin", "parallel-admin-actions"):
            lg = logging.getLogger(logger_name)
            for h in list(lg.handlers):
                lg.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass

    def _make(self, **kwargs):
        return AppLogger(log_dir=self.tmp, **kwargs)

    def test_info_writes_to_run_log(self):
        app = self._make()
        app.info("test info message")
        content = (self.tmp / config.logging.run).read_text(encoding="utf-8")
        self.assertIn("test info message", content)

    def test_error_writes_to_errors_log(self):
        app = self._make()
        app.error("test error message")
        content = (self.tmp / config.logging.errors).read_text(
            encoding="utf-8"
        )
        self.assertIn("test error message", content)

    def test_action_writes_to_actions_and_run(self):
        app = self._make()
        app.action("Test action")
        self.assertTrue(app.actions_path.exists())
        content = app.actions_path.read_text(encoding="utf-8")
        self.assertIn("Test action", content)
        run_content = (self.tmp / config.logging.run).read_text(
            encoding="utf-8"
        )
        self.assertIn("ACTION | Test action", run_content)

    def test_session_markers(self):
        app = self._make()
        app.session_start("v9.9.9")
        app.session_end()
        content = app.actions_path.read_text(encoding="utf-8")
        self.assertIn("=== SESSION START v9.9.9 ===", content)
        self.assertIn("=== SESSION END", content)

    def test_rotation_by_size(self):
        app = self._make(max_bytes=2000, backups=3)
        for i in range(30):
            app.info(f"rotation line {i:04d} " + "x" * 300)
        self.assertTrue((self.tmp / config.logging.run).exists())
        self.assertTrue((self.tmp / (config.logging.run + ".1")).exists())

    def test_cleanup_removes_old_actions_files(self):
        app = self._make(retention_days=1)
        stem = config.logging.actions
        old = self.tmp / f"{stem}-20200101-000000.log"
        old.write_text("old")
        old_time = (datetime.now() - timedelta(days=2)).timestamp()
        os.utime(old, (old_time, old_time))

        fresh = self.tmp / f"{stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        fresh.write_text("fresh")

        app.cleanup()

        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())

    def test_cleanup_keeps_old_when_retention_zero(self):
        app = self._make(retention_days=0)
        stem = config.logging.actions
        old = self.tmp / f"{stem}-20200101-000000.log"
        old.write_text("old")
        old_time = (datetime.now() - timedelta(days=2)).timestamp()
        os.utime(old, (old_time, old_time))

        app.cleanup()

        self.assertTrue(old.exists())


if __name__ == "__main__":
    unittest.main()
