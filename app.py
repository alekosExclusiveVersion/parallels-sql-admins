import os
import shutil
import sys
import traceback
from pathlib import Path


if getattr(sys, "frozen", False):
    base = (
        Path(os.environ.get("HOME", str(Path.home())))
        / "Library" / "Application Support" / "Parallels SQL Admin"
    )
    base.mkdir(parents=True, exist_ok=True)

    os.chdir(base)

    for name in ("config.ini", "servers.txt"):
        dst = base / name
        src = Path(sys._MEIPASS) / name
        if not dst.exists() and src.exists():
            shutil.copy(src, dst)

from PySide6.QtWidgets import QApplication

from gui.application import App
from gui.icons import app_icon
from gui import styles as theme_styles
from common.logger import logger
from common.version import APP_VERSION


def main() -> int:

    qt_app = QApplication(sys.argv)

    qt_app.setStyle("Fusion")

    theme_styles.bootstrap()
    qt_app.setPalette(theme_styles.build_palette())

    qt_app.setWindowIcon(app_icon())

    logger.session_start(f"Parallels SQL Admins v{APP_VERSION}")

    window = App()

    window.show()

    rc = qt_app.exec()

    # Явно удаляем Python-обёртки Qt-виджетов до выхода из интерпретатора:
    # иначе PySide6 при atexit удаляет C++-объекты повторно и падает
    # с SIGSEGV (известная проблема PySide6 6.11 в frozen-сборках).
    window.close()
    window.deleteLater()
    qt_app.processEvents()
    del window

    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        # В windowed-сборке PyInstaller traceback уходит в /dev/null,
        # поэтому пишем его в файл рядом с конфигом.
        try:
            crash_dir = (
                Path(os.environ.get("HOME", str(Path.home())))
                / "Library" / "Application Support" / "Parallels SQL Admin"
            )
            crash_dir.mkdir(parents=True, exist_ok=True)
            with open(crash_dir / "crash.log", "w") as f:
                f.write(traceback.format_exc())
        except Exception:
            pass
        sys.exit(1)
