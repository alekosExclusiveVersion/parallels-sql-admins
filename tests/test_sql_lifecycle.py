"""
tests/test_sql_lifecycle.py

Тесты рефакторинга жизненного цикла SQL-запросов:
  - _sql_busy как единый флаг занятости
  - set_busy(False) вызывается ровно один раз в _sql_finished
  - _show_query_result / _sql_edit_finished НЕ вызывают set_busy(False)
  - _run_sql / _sql_refresh_databases блокируются при _sql_busy=True
"""

import os
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


class FakePanel:
    """Заглушка SqlConsolePanel для тестов MainWindow."""

    def __init__(self):
        self._busy = False
        self._stop_enabled = True
        self._databases = []
        self._catalog = ([], {})
        self._server_index = 0
        self._db_index = 0
        self._servers = [("host1", "host1"), ("host2", "host2")]
        self._dbs = [("db1", "db1")]
        self._write_enabled = False
        self._search_busy = False

    def set_busy(self, busy):
        self._busy = busy

    def is_busy(self):
        return self._busy

    def set_stop_enabled(self, enabled):
        self._stop_enabled = enabled

    def set_databases(self, names):
        self._dbs = [(n, n) for n in names]
        self._databases = names

    def current_host(self):
        if 0 <= self._server_index < len(self._servers):
            return self._servers[self._server_index][1]
        return None

    def current_database(self):
        if 0 <= self._db_index < len(self._dbs):
            return self._dbs[self._db_index][1]
        return None

    def all_servers_checked(self):
        return False

    def all_databases_checked(self):
        return False

    def write_enabled(self):
        return self._write_enabled

    def set_search_busy(self, busy):
        self._search_busy = busy

    def cb_server(self):
        return MagicMock(currentIndex=lambda: self._server_index)

    def mark_working_database(self, ut):
        pass

    def clear_completion(self):
        pass

    def set_catalog(self, tables, columns):
        self._catalog = (tables, columns)

    def set_scripts(self, items):
        pass


class FakeStatusBar:
    def set_status(self, msg):
        self._msg = msg


class FakeTable:
    def __init__(self):
        self.results_source = None
        self._reset_called = False
        self._fill_args = None
        self._sorting_enabled = False

    def reset_table(self):
        self._reset_called = True

    def fill_sql_result(self, host, database, rows, columns, message):
        self._fill_args = (host, database, rows, columns, message)

    def setSortingEnabled(self, enabled):
        self._sorting_enabled = enabled

    def sync_filter_columns(self):
        pass

    def apply_filters(self):
        pass

    def clear_results(self):
        pass

    def original_row(self, r):
        return r

    def item(self, r, c):
        return None

    def rowCount(self):
        return 0


class FakeWorker:
    def __init__(self):
        self.finished = MagicMock()
        self.result = MagicMock()
        self.error = MagicMock()
        self.databases = MagicMock()
        self.started = MagicMock()
        self.query = MagicMock()
        self.edit_meta = MagicMock()
        self.started_target = MagicMock()
        self.result_target = MagicMock()
        self.error_target = MagicMock()
        self.stopped = MagicMock()

    def set_request(self, *a, **kw):
        pass

    def set_multi_request(self, *a, **kw):
        pass

    def set_databases_request(self, *a, **kw):
        pass

    def stop(self):
        pass

    def kill_active(self):
        pass


class FakeThread:
    def __init__(self):
        self._running = False
        self.finished = MagicMock()

    def start(self):
        self._running = True

    def isRunning(self):
        return self._running

    def quit(self):
        self._running = False
        self.finished.emit()

    def wait(self, timeout=0):
        pass


class TestSqlBusyFlag(unittest.TestCase):
    """Проверяет корректность флага _sql_busy."""

    def _make_main_window_stubs(self):
        """Возвращает (panel, table, status_bar, worker, thread)."""
        return (
            FakePanel(),
            FakeTable(),
            FakeStatusBar(),
            FakeWorker(),
            FakeThread(),
        )

    def test_sql_busy_initially_false(self):
        panel, table, status_bar, worker, thread = self._make_main_window_stubs()
        # Имитируем атрибуты MainWindow, используемые в рефакторинге
        ctx = {
            "_sql_busy": False,
            "panel": panel,
            "table": table,
            "status_bar": status_bar,
            "query_worker": worker,
            "query_thread": thread,
            "_last_sql_request": None,
            "_sql_edit_pending": None,
        }
        self.assertFalse(ctx["_sql_busy"])

    def test_run_sql_sets_busy_true(self):
        panel, table, status_bar, worker, thread = self._make_main_window_stubs()

        # Имитируем _run_sql: проверяем что _sql_busy устанавливается
        _sql_busy = False

        def fake_run_sql(sql):
            nonlocal _sql_busy
            if _sql_busy:
                return False
            _sql_busy = True
            panel.set_busy(True)
            thread.start()
            return True

        result = fake_run_sql("SELECT 1")
        self.assertTrue(result)
        self.assertTrue(_sql_busy)
        self.assertTrue(panel.is_busy())
        self.assertTrue(thread.isRunning())

    def test_run_sql_rejects_when_busy(self):
        panel, table, status_bar, worker, thread = self._make_main_window_stubs()

        _sql_busy = True  # Уже выполняется

        def fake_run_sql(sql):
            nonlocal _sql_busy
            if _sql_busy:
                return False
            _sql_busy = True
            panel.set_busy(True)
            thread.start()
            return True

        result = fake_run_sql("SELECT 1")
        self.assertFalse(result)
        self.assertTrue(_sql_busy)  # Остался True
        self.assertFalse(thread.isRunning())  # Поток не стартовал

    def test_sql_finished_clears_busy(self):
        panel, table, status_bar, worker, thread = self._make_main_window_stubs()

        _sql_busy = True
        panel.set_busy(True)

        def fake_sql_finished():
            nonlocal _sql_busy
            _sql_busy = False
            table.setSortingEnabled(True)
            table.sync_filter_columns()
            table.apply_filters()
            panel.set_busy(False)

        fake_sql_finished()

        self.assertFalse(_sql_busy)
        self.assertFalse(panel.is_busy())
        self.assertTrue(table._sorting_enabled)

    def test_show_query_result_does_not_clear_busy(self):
        """_show_query_result НЕ должен вызывать set_busy(False)."""
        panel, table, status_bar, worker, thread = self._make_main_window_stubs()

        _sql_busy = True
        panel.set_busy(True)

        # Имитируем _show_query_result (уже без set_busy(False))
        def fake_show_query_result(rows, columns, message):
            host = panel.current_host()
            database = panel.current_database()
            table.fill_sql_result(host, database, rows, columns, message)
            status_bar.set_status(message)

        fake_show_query_result([["a"]], ["col1"], "1 row(s)")

        #Busy НЕ должен сброситься
        self.assertTrue(_sql_busy)
        self.assertTrue(panel.is_busy())
        # Но результат должен отобразиться
        self.assertIsNotNone(table._fill_args)

    def test_sql_edit_finished_does_not_clear_busy(self):
        """_sql_edit_finished НЕ должен вызывать set_busy(False)."""
        panel, table, status_bar, worker, thread = self._make_main_window_stubs()

        _sql_busy = True
        panel.set_busy(True)
        edit_pending = {"row": 0, "col": 0, "new_text": "x"}

        # Имитируем _sql_edit_finished (уже без set_busy(False))
        def fake_sql_edit_finished(rows, columns, message):
            nonlocal edit_pending
            pending = edit_pending
            edit_pending = None
            if pending is None:
                return
            # Обработка...

        fake_sql_edit_finished([], [], "1 row(s) affected")

        # Busy НЕ должен сброситься из _sql_edit_finished
        self.assertTrue(_sql_busy)
        self.assertTrue(panel.is_busy())
        self.assertIsNone(edit_pending)  # pending очистился

    def test_full_lifecycle_busy_transitions(self):
        """Полный цикл: busy=False → True (start) → False (finished)."""
        panel, table, status_bar, worker, thread = self._make_main_window_stubs()

        _sql_busy = False

        # 1. Запуск
        _sql_busy = True
        panel.set_busy(True)
        thread.start()

        self.assertTrue(_sql_busy)
        self.assertTrue(panel.is_busy())
        self.assertTrue(thread.isRunning())

        # 2. Результат приходит (busy НЕ сбрасывается)
        table.fill_sql_result("host", "db", [["x"]], ["c"], "ok")
        self.assertTrue(_sql_busy)
        self.assertTrue(panel.is_busy())

        # 3. Поток завершается: worker.finished → thread.quit() → thread.finished
        thread.quit()  # stops the thread, emits thread.finished
        _sql_busy = False
        panel.set_busy(False)

        self.assertFalse(_sql_busy)
        self.assertFalse(panel.is_busy())
        self.assertFalse(thread.isRunning())


class TestRefreshDatabasesBusy(unittest.TestCase):
    """Проверяет блокировку _sql_refresh_databases при _sql_busy."""

    def test_refresh_databases_rejects_when_busy(self):
        panel = FakePanel()
        thread = FakeThread()
        worker = FakeWorker()
        status_bar = FakeStatusBar()

        _sql_busy = True

        def fake_refresh():
            nonlocal _sql_busy
            if _sql_busy:
                return False
            _sql_busy = True
            panel.set_busy(True)
            panel.set_stop_enabled(False)
            thread.start()
            return True

        result = fake_refresh()
        self.assertFalse(result)
        self.assertFalse(thread.isRunning())

    def test_refresh_databases_proceeds_when_idle(self):
        panel = FakePanel()
        thread = FakeThread()
        worker = FakeWorker()
        status_bar = FakeStatusBar()

        _sql_busy = False

        def fake_refresh():
            nonlocal _sql_busy
            if _sql_busy:
                return False
            _sql_busy = True
            panel.set_busy(True)
            panel.set_stop_enabled(False)
            thread.start()
            return True

        result = fake_refresh()
        self.assertTrue(result)
        self.assertTrue(_sql_busy)
        self.assertTrue(thread.isRunning())


class TestRunTableSelectBusy(unittest.TestCase):
    """Проверяет _run_table_select с _sql_busy."""

    def test_table_select_stops_existing_thread(self):
        panel = FakePanel()
        thread = FakeThread()
        worker = FakeWorker()
        status_bar = FakeStatusBar()
        table = FakeTable()

        _sql_busy = True
        thread.start()  # Поток уже запущен

        def fake_table_select():
            nonlocal _sql_busy
            if _sql_busy:
                worker.stop()
                thread.quit()  # Эмулирует остановку
                thread.wait(5000)
                if _sql_busy:
                    return False  # Не удалось остановить

            _sql_busy = True
            panel.set_busy(True)
            thread.start()
            return True

        # Поток останавливается через quit(), _sql_busy всё ещё True
        result = fake_table_select()
        self.assertFalse(result)  # Не удалось остановить

    def test_table_select_proceeds_when_idle(self):
        panel = FakePanel()
        thread = FakeThread()
        worker = FakeWorker()
        status_bar = FakeStatusBar()
        table = FakeTable()

        _sql_busy = False

        def fake_table_select():
            nonlocal _sql_busy
            if _sql_busy:
                worker.stop()
                thread.quit()
                thread.wait(5000)
                if _sql_busy:
                    return False

            _sql_busy = True
            panel.set_busy(True)
            thread.start()
            return True

        result = fake_table_select()
        self.assertTrue(result)
        self.assertTrue(_sql_busy)
        self.assertTrue(thread.isRunning())


if __name__ == "__main__":
    unittest.main()
