from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow

from gui.main_window import MainWindow
from common.version import APP_VERSION

_CHECK_UPDATES_DELAY_MS = 4000
_CHECK_UPDATES_INTERVAL_MS = 24 * 60 * 60 * 1000


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Parallels SQL Admins v{APP_VERSION}")
        self.setMinimumSize(1200, 700)

        self.ui = MainWindow(self)
        self.setCentralWidget(self.ui)

        self.ui.build_menu(self.menuBar())

        self._updates_timer = QTimer(self)
        self._updates_timer.setInterval(_CHECK_UPDATES_INTERVAL_MS)
        self._updates_timer.timeout.connect(self._check_updates)
        self._updates_timer.start()
        QTimer.singleShot(_CHECK_UPDATES_DELAY_MS, self._check_updates)

    def _check_updates(self) -> None:
        from gui.update_dialog import maybe_show_update

        maybe_show_update(self)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Останавливает фоновые потоки до закрытия окна.

        closeEvent вызывается только у верхнеуровневого виджета (App),
        а не у центрального (MainWindow), поэтому останавливаем потоки здесь.
        """
        self.ui.shutdown()
        event.accept()
