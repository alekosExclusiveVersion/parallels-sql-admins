"""
common/logger.py
Потокобезопасное логирование и вывод в консоль.

run.log / errors.log ротируются по размеру (max_bytes, backups);
actions.log создаётся на каждый запуск (actions-YYYYMMDD-HHMMSS.log);
cleanup() удаляет старые actions-файлы и ротационные бэкапы.
"""

from __future__ import annotations

import logging
import logging.handlers
import threading
from datetime import datetime
from pathlib import Path

from rich.console import Console

from common.config import config

_console = Console()
_lock = threading.Lock()


class AppLogger:
    def __init__(
        self,
        log_dir: Path | None = None,
        max_bytes: int | None = None,
        backups: int | None = None,
        retention_days: int | None = None,
    ) -> None:
        self.log_dir = log_dir or config.logging.directory
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.max_bytes = (
            config.logging.max_bytes if max_bytes is None else max_bytes
        )
        self.backups = config.logging.backups if backups is None else backups
        self.retention_days = (
            config.logging.retention_days
            if retention_days is None
            else retention_days
        )

        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"
        )

        self.logger = logging.getLogger("parallel-admin")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()

        run = logging.handlers.RotatingFileHandler(
            self.log_dir / config.logging.run,
            maxBytes=self.max_bytes,
            backupCount=self.backups,
            encoding="utf-8",
        )
        run.setFormatter(fmt)
        self.logger.addHandler(run)

        err = logging.handlers.RotatingFileHandler(
            self.log_dir / config.logging.errors,
            maxBytes=self.max_bytes,
            backupCount=self.backups,
            encoding="utf-8",
        )
        err.setLevel(logging.ERROR)
        err.setFormatter(fmt)
        self.logger.addHandler(err)

        self.actions_path = self.log_dir / self._actions_filename()
        actions = logging.FileHandler(self.actions_path, encoding="utf-8")
        actions.setLevel(logging.INFO)
        actions.setFormatter(fmt)

        self._actions_logger = logging.getLogger("parallel-admin-actions")
        self._actions_logger.setLevel(logging.INFO)
        self._actions_logger.handlers.clear()
        self._actions_logger.addHandler(actions)

        self._session_started_at: datetime | None = None

        self.cleanup()

    @staticmethod
    def _actions_filename() -> str:
        stem = config.logging.actions
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"{stem}-{stamp}.log"

    def _print(self, style: str, prefix: str, message: str) -> None:
        with _lock:
            _console.print(f"[{style}]{prefix}[/{style}] {message}")

    def info(self, message: str) -> None:
        self.logger.info(message)
        if config.logging.verbose:
            self._print("cyan", "INFO ", message)

    def success(self, message: str) -> None:
        self.logger.info(message)
        self._print("green", " OK  ", message)

    def warning(self, message: str) -> None:
        self.logger.warning(message)
        self._print("yellow", "WARN ", message)

    def error(self, message: str) -> None:
        self.logger.error(message)
        self._print("red", "ERR  ", message)

    def exception(self, exc: Exception) -> None:
        self.logger.exception(str(exc))
        self._print("red", "EXC  ", str(exc))

    def action(self, message: str) -> None:
        self._actions_logger.info(message)
        self.logger.info(f"ACTION | {message}")
        if config.logging.verbose:
            self._print("magenta", "ACT  ", message)

    def session_start(self, message: str) -> None:
        self._session_started_at = datetime.now()
        self._actions_logger.info(f"=== SESSION START {message} ===")
        self.logger.info(f"=== SESSION START {message} ===")

    def session_end(self) -> None:
        started = self._session_started_at
        duration = ""
        if started is not None:
            seconds = max(0, (datetime.now() - started).total_seconds())
            h, rem = divmod(int(seconds), 3600)
            m, s = divmod(rem, 60)
            duration = f" ({h:02}:{m:02}:{s:02})"
        self._actions_logger.info(f"=== SESSION END{duration} ===")
        self.logger.info(f"=== SESSION END{duration} ===")

    def cleanup(self) -> None:
        """Удаляет actions-файлы и ротационные бэкапы старше retention_days."""
        retention = self.retention_days
        if retention <= 0:
            return
        cutoff = datetime.now().timestamp() - retention * 86400
        for pattern in (
            f"{config.logging.actions}-*.log",
            f"{config.logging.run}.*",
            f"{config.logging.errors}.*",
        ):
            for path in self.log_dir.glob(pattern):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                except OSError:
                    pass


logger = AppLogger()


if __name__ == "__main__":
    logger.session_start("test session")
    logger.info("Logger initialized")
    logger.success("Success example")
    logger.action("Action example")
    logger.warning("Warning example")
    logger.error("Error example")
    logger.session_end()
