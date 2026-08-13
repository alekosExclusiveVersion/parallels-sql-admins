"""Визуальная проверка нового фильтр-бара Results.

Запуск (macOS): python3 debug/debug_filter_visual.py
Рендерит окно в файл docs/screenshots/filter_visual.png.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "minimal")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow

# Не ходим в сеть: авто-обновление списка БД при старте выключено,
# иначе рендер ждёт таймаутов подключения.
MainWindow._sql_refresh_databases = lambda self: None  # type: ignore

OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs", "screenshots", "filter_visual.png",
)


def main():
    app = QApplication.instance() or QApplication(sys.argv)

    window = MainWindow()
    window.resize(1280, 800)
    window.show()

    # Заполняем таблицу данными как при Check
    table = window.table
    table.clear_results()
    table.results_source = "check"
    table._update_only_errors_visibility()

    rows = [
        ["Check", "srv1.ru", "db_alpha", "RU", "10", "OK", "all good"],
        ["Check", "srv1.ru", "db_beta", "RU", "20", "ERROR", "connection boom"],
        ["Check", "srv2.ru", "db_gamma", "US", "30", "WARNING", "slow query"],
        ["Check", "srv2.ru", "db_delta", "FR", "40", "OK", "ok"],
    ]
    for r in rows:
        table.add_row(r, status_col=5)

    table.sync_filter_columns()
    table.apply_filters()

    # Заполняем пример фильтра для наглядности
    table.filter_header._edits[1].setText("srv")

    app.processEvents()

    img = QImage(window.size(), QImage.Format_ARGB32)
    img.fill(0)
    window.render(img)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    ok = img.save(OUT)
    print(f"Saved: {OUT} ({'OK' if ok else 'FAILED'})")
    window.close()


if __name__ == "__main__":
    main()
