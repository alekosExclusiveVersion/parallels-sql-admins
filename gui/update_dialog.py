"""
gui/update_dialog.py

Уведомление о новой версии и авто-обновление.

- Проверка GitHub Releases в фоновом потоке при старте и раз в сутки;
- Диалог: «Обновить сейчас» (Windows — скачивание с прогрессом, проверка
  подписи и запуск Setup.exe; остальные ОС — открыть страницу релиза),
  «Позже», «Не спрашивать до следующей версии».
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QVBoxLayout,
)

from common import updater
from common.config import config
from common.logger import logger
from common.version import APP_VERSION

_RC_LATER = 0
_RC_UPDATE = 1
_RC_SKIP = 2


class FetchThread(QThread):
    """Проверка последней версии на GitHub (не блокирует UI)."""

    found = Signal(str, str, str)  # version, setup_url, html_url
    no_update = Signal()
    failed = Signal(str)

    def run(self) -> None:
        try:
            info = updater.fetch_latest()
        except Exception as exc:
            logger.warning(f"Проверка обновлений не удалась: {exc}")
            self.failed.emit(str(exc))
            return
        if not updater.version_newer(info.version, APP_VERSION):
            self.no_update.emit()
            return
        if not updater.should_notify(info):
            self.no_update.emit()
            return
        self.found.emit(info.version, info.url or "", info.html_url)


class DownloadThread(QThread):
    """Скачивание и запуск установщика новой версии."""

    progress = Signal(int, int)  # done, total
    ok = Signal(str)             # путь к установщику
    failed = Signal(str)

    def __init__(self, info: updater.UpdateInfo, parent=None):
        super().__init__(parent)
        self._info = info
        self._cancelled = False

    def run(self) -> None:
        try:
            path = updater.install_update(self._info, self._on_progress)
        except updater.CancelError:
            return
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.ok.emit(str(path))

    def cancel(self) -> None:
        self._cancelled = True

    def _on_progress(self, done: int, total: int) -> None:
        if self._cancelled:
            raise updater.CancelError("загрузка отменена")
        self.progress.emit(done, total)


class UpdateDialog(QDialog):
    """«Доступна новая версия»: обновить / позже / не спрашивать."""

    def __init__(self, version: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Доступно обновление")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        label = QLabel(
            f"Доступна новая версия <b>{version}</b>.<br>"
            f"Установлена: {APP_VERSION}.<br><br>"
            "Обновить сейчас?"
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        buttons = QDialogButtonBox(self)
        b_update = buttons.addButton(
            "Обновить сейчас", QDialogButtonBox.AcceptRole
        )
        b_later = buttons.addButton("Позже", QDialogButtonBox.RejectRole)
        b_skip = buttons.addButton(
            "Не спрашивать до следующей версии",
            QDialogButtonBox.DestructiveRole,
        )
        b_update.clicked.connect(lambda: self.done(_RC_UPDATE))
        b_later.clicked.connect(lambda: self.done(_RC_LATER))
        b_skip.clicked.connect(lambda: self.done(_RC_SKIP))
        layout.addWidget(buttons)


def maybe_show_update(parent) -> None:
    """Запускает фоновую проверку обновлений (идемпотентна по конфигу)."""
    if not config.updates.enabled:
        return

    thread = FetchThread(parent)
    parent._update_fetch_thread = thread
    thread.found.connect(lambda v, u, h: _on_found(parent, v, u, h))
    thread.failed.connect(lambda _msg: None)
    thread.no_update.connect(lambda: None)
    thread.finished.connect(thread.deleteLater)
    thread.start()


def _on_found(parent, version: str, url: str, html_url: str) -> None:
    dialog = UpdateDialog(version, parent)
    rc = dialog.exec()

    if rc == _RC_SKIP:
        updater.set_dont_ask_until(version)
        return
    if rc != _RC_UPDATE:
        return

    if sys.platform != "win32" or not url:
        QDesktopServices.openUrl(QUrl(html_url or updater.RELEASES_URL))
        return

    _download_and_install(parent, version, url)


def _download_and_install(parent, version: str, url: str) -> None:
    info = updater.UpdateInfo(
        version=version,
        url=url,
        html_url=updater.RELEASES_URL,
    )

    progress = QProgressDialog(
        "Скачивание новой версии…", "Отмена", 0, 0, parent
    )
    progress.setWindowTitle("Обновление")
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)

    thread = DownloadThread(info, parent)
    parent._update_download_thread = thread

    def on_progress(done: int, total: int) -> None:
        if total > 0:
            progress.setMaximum(total)
        progress.setValue(done)

    def on_ok(path: str) -> None:
        progress.close()
        logger.info(f"Запущен установщик: {path}")
        parent.close()

    def on_failed(message: str) -> None:
        progress.close()
        logger.warning(f"Обновление не удалось: {message}")
        QMessageBox.warning(
            parent,
            "Обновление",
            f"Не удалось обновить приложение:\n{message}",
        )

    def on_cancel() -> None:
        thread.cancel()
        progress.close()

    thread.progress.connect(on_progress)
    thread.ok.connect(on_ok)
    thread.failed.connect(on_failed)
    progress.canceled.connect(on_cancel)
    thread.start()
