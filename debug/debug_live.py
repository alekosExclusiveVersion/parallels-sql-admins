import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Этот скрипт выполняет РЕАЛЬНЫЕ подключения к серверам из servers.txt.
# Запускается только при явном DBG_LIVE=1 — защита от случайного запуска.
if os.environ.get("DBG_LIVE") != "1":
    print("ABORT: set DBG_LIVE=1 to run a REAL live check against servers.txt")
    raise SystemExit(1)

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

# Эмулируем ввод пароля как в LoginDialog
from common.mysql_session import session

session.user = os.environ.get("DBG_USER", "demo_user")
session.password = os.environ.get("DBG_PASSWORD", "dummy_password")

from gui.main_window import MainWindow

w = MainWindow()
w.show()

# Ловим сигналы воркера для диагностики
w.worker.result.connect(lambda *a: print("SIGNAL result:", a[:2]))
w.worker.finished.connect(lambda: print("SIGNAL finished"))
w.worker.status.connect(lambda s: print("SIGNAL status:", s))
w.worker.progress.connect(lambda c, t: print("SIGNAL progress:", c, t))

w.server_list.selectAll()
w._run_check()


def done():
    print("=== LIVE CHECK (real DB) ===")
    print("rows:", w.table.rowCount(), "cols:", w.table.columnCount())
    print("headers:", [w.table.horizontalHeaderItem(c).text() if w.table.horizontalHeaderItem(c) else "?" for c in range(w.table.columnCount())])
    for r in range(w.table.rowCount()):
        vals = [w.table.item(r, c).text() if w.table.item(r, c) else "" for c in range(w.table.columnCount())]
        print(f"  row {r}: {vals} hidden={w.table.isRowHidden(r)}")
    # Закрываем окно ДО выхода, чтобы closeEvent остановил потоки:
    # иначе живые QThread падают в _Py_Finalize (SIGABRT).
    w.close()
    app.quit()


QTimer.singleShot(15000, done)
app.exec()
