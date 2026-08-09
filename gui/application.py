from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow

from gui.main_window import MainWindow
from common.version import APP_VERSION


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Parallels SQL Admins v{APP_VERSION}")
        self.setMinimumSize(1200, 700)

        self.ui = MainWindow(self)
        self.setCentralWidget(self.ui)

        self.ui.build_menu(self.menuBar())

    def closeEvent(self, event: QCloseEvent) -> None:
        """Останавливает фоновые потоки до закрытия окна.

        closeEvent вызывается только у верхнеуровневого виджета (App),
        а не у центрального (MainWindow), поэтому останавливаем потоки здесь.
        """
        self.ui.shutdown()
        event.accept()
