"""Smoke-тест новой фильтрации Results (сквозной + колоночные contains).

Запуск: python3 debug/debug_filter_smoke.py
Работает без отображения окна (QT_QPA_PLATFORM=offscreen).
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow

# Не ходим в сеть: авто-обновление списка БД при старте выключено.
MainWindow._sql_refresh_databases = lambda self: None  # type: ignore


def cell_text(window, row, col):
    item = window.table.item(row, col)
    return item.text() if item else ""


def count_visible(window):
    return sum(
        1
        for row in range(window.table.rowCount())
        if not window.table.isRowHidden(row)
    )


def main():
    app = QApplication.instance() or QApplication(sys.argv)

    window = MainWindow()
    window.show()

    # Заполняем таблицу тестовыми данными (как в Check)
    table = window.table
    table.clear_results()
    table.results_source = "check"
    table._update_only_errors_visibility()

    rows = [
        ["Check", "srv1", "db_alpha", "RU", "10", "OK", "fine"],
        ["Check", "srv1", "db_beta", "RU", "20", "ERROR", "boom"],
        ["Check", "srv2", "db_gamma", "US", "30", "WARNING", "warn"],
        ["Check", "srv2", "db_delta", "FR", "40", "OK", "ok"],
    ]
    for r in rows:
        table.add_row(r, status_col=5)

    table.sync_filter_columns()
    table.apply_filters()

    assert table.columnCount() == 7, "ожидается 7 колонок"
    assert len(table.filter_header._edits) == 7, "ожидается 7 полей фильтра"

    # 1) Без фильтров — все строки видимы
    assert count_visible(window) == 4, f"ожидалось 4, получено {count_visible(window)}"

    # 2) Сквозной поиск "srv2" — строки 3,4
    window.result_search.setText("srv2")
    table.apply_filters()
    assert count_visible(window) == 2, f"сквозной srv2: {count_visible(window)}"

    # 3) Сквозной поиск по значению в Message "boom" — строка 2
    window.result_search.setText("boom")
    table.apply_filters()
    assert count_visible(window) == 1, f"сквозной boom: {count_visible(window)}"

    # 4) Колоночный фильтр: Server == "srv1" (index 1) — строки 1,2
    window.result_search.clear()
    table.apply_filters()
    table.filter_header._edits[1].setText("srv1")
    table.apply_filters()
    assert count_visible(window) == 2, f"колонка Server srv1: {count_visible(window)}"

    # 5) OR внутри поколоночной группы: Server=srv1 ИЛИ Status=ERROR.
    # Обе колонки дают строки 0,1, поэтому итог — 2 строки.
    table.filter_header._edits[5].setText("ERROR")
    table.apply_filters()
    assert count_visible(window) == 2, f"OR srv1|ERROR: {count_visible(window)}"

    # 6) AND между группами: общий srv1 И поколоночный Status=ERROR.
    # Сбрасываем Server, чтобы проверить именно связь двух групп.
    table.filter_header._edits[1].clear()
    window.result_search.setText("srv1")
    table.apply_filters()
    assert count_visible(window) == 1, f"AND srv1&ERROR: {count_visible(window)}"

    # 7) Только ошибки применяется поверх результата AND как дополнительный
    # фильтр. Строка уже имеет статус ERROR и остаётся видимой.
    window.chk_only_errors.setChecked(True)
    table.apply_filters()
    assert count_visible(window) == 1, f"только ошибки: {count_visible(window)}"
    visible_rows = [
        row for row in range(window.table.rowCount())
        if not window.table.isRowHidden(row)
    ]
    assert len(visible_rows) == 1, f"видимых строк: {visible_rows}"
    assert cell_text(window, visible_rows[0], 5) == "ERROR", (
        f"статус видимой строки: {cell_text(window, visible_rows[0], 5)}"
    )

    # 8) Пустой общий фильтр отключает только свою группу: поколоночный
    # фильтр продолжает работать самостоятельно.
    window.chk_only_errors.setChecked(False)
    window.result_search.clear()
    table.filter_header.clear_filters()
    table.filter_header._edits[1].setText("srv2")
    table.apply_filters()
    assert count_visible(window) == 2, f"колонка srv2: {count_visible(window)}"

    print("ALL FILTER SMOKE TESTS PASSED")
    window.close()


if __name__ == "__main__":
    main()
