"""
tests/test_query_worker.py

Тесты для backend/query_worker.py — отслеживание активного соединения,
прерывание выполняющегося запроса через KILL, выполнение скриптов
из нескольких операторов и остановка между ними.
"""

import csv
import os
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

import backend.query_worker as qw

from PySide6.QtCore import Qt


class FakeCursor:
    description = None
    rowcount = 5

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql):
        time.sleep(0.3)


class FakeConn:
    def __init__(self):
        self._cursor = FakeCursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def thread_id(self):
        return 4242

    def cursor(self):
        return self._cursor


class FakeResultCursor:
    """Курсор с результирующим набором DictCursor-стиля."""

    def __init__(self, columns, rows, rowcount=None):
        self.description = [(c,) for c in columns]
        self._rows = rows
        self.rowcount = len(rows) if rowcount is None else rowcount
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql):
        self.executed.append(sql)

    def fetchmany(self, size):
        out, self._rows = self._rows[:size], self._rows[size:]
        return out


class FakeMySQL:
    def __init__(self):
        self.killed = []
        self.conn = FakeConn()

    def connect(self, host, database=None):
        return self.conn

    def connection_id(self, conn):
        return conn.thread_id()

    def list_databases(self, host):
        return ["db1"]

    def kill_connection(self, host, connection_id):
        self.killed.append((host, connection_id))


class ScriptConn:
    """Соединение, выдающее курсоры из очереди в порядке запросов."""

    def __init__(self, cursors):
        self._q = list(cursors)
        self._id = 7

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def thread_id(self):
        return self._id

    def cursor(self):
        return self._q.pop(0)


class TestQueryWorkerKill(unittest.TestCase):
    def setUp(self):
        self.fake = FakeMySQL()
        patcher = patch.object(qw, "client_for", lambda host: self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_kill_active_sends_kill_for_running_query(self):
        worker = qw.QueryWorker()
        worker.set_request("host1", "db1", "SELECT sleep(10)", 1000)

        thread = threading.Thread(
            target=worker._execute_sql,
            args=("host1", "db1", ["SELECT sleep(10)"], 1000),
        )
        thread.start()

        time.sleep(0.05)
        worker.kill_active()
        thread.join(timeout=5)

        self.assertEqual(self.fake.killed, [("host1", 4242)])
        self.assertEqual(worker.active_connections(), [])

    def test_kill_active_without_active_query_is_noop(self):
        worker = qw.QueryWorker()
        worker.set_request("host1", "db1", "SELECT 1", 1000)
        worker.kill_active()
        self.assertEqual(self.fake.killed, [])

    def test_active_connections_cleared_after_execution(self):
        worker = qw.QueryWorker()
        worker.set_request("host1", "db1", "UPDATE t SET a = 1", 1000)

        worker._execute_sql("host1", "db1", ["UPDATE t SET a = 1"], 1000)

        self.assertEqual(worker.active_connections(), [])


class TestQueryWorkerMulti(unittest.TestCase):
    def setUp(self):
        self.fake = FakeMySQL()
        patcher = patch.object(qw, "client_for", lambda host: self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_multi_runs_targets_in_parallel(self):
        worker = qw.QueryWorker()
        worker.set_multi_request(
            [("h1", "db1"), ("h2", "db2")],
            "SELECT sleep(1)",
            1000,
        )

        started = []
        results = []
        worker.started_target.connect(
            lambda i, n, h, d: started.append((h, d)),
            Qt.ConnectionType.DirectConnection,
        )
        worker.result_target.connect(
            lambda h, d, rows, columns, message: results.append((h, d)),
            Qt.ConnectionType.DirectConnection,
        )

        t0 = time.monotonic()
        worker._run_multi()
        elapsed = time.monotonic() - t0

        self.assertEqual(sorted(started), [("h1", "db1"), ("h2", "db2")])
        self.assertEqual(sorted(results), [("h1", "db1"), ("h2", "db2")])
        # Каждый оператор спит 0.3 c: параллельно — ~0.3, последовательно — 0.6.
        self.assertLess(elapsed, 0.55)

    def test_multi_expands_all_databases(self):
        worker = qw.QueryWorker()
        worker.set_multi_request(
            [("h1", qw.ALL_DATABASES)],
            "SELECT 1",
            1000,
        )

        results = []
        worker.result_target.connect(
            lambda h, d, rows, columns, message: results.append((h, d)),
            Qt.ConnectionType.DirectConnection,
        )

        worker._run_multi()

        self.assertEqual(results, [("h1", "db1")])

    def test_kill_active_kills_all_parallel_connections(self):
        worker = qw.QueryWorker()
        worker.set_multi_request(
            [("h1", "db1"), ("h2", "db2")],
            "SELECT sleep(10)",
            1000,
        )

        thread = threading.Thread(target=worker._run_multi)
        thread.start()

        deadline = time.monotonic() + 5
        while (
            len(worker.active_connections()) < 2
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)

        worker.kill_active()
        thread.join(timeout=5)

        self.assertEqual(
            sorted(self.fake.killed),
            [("h1", 4242), ("h2", 4242)],
        )
        self.assertEqual(worker.active_connections(), [])


class TestQueryWorkerScript(unittest.TestCase):
    def setUp(self):
        self.fake = FakeMySQL()
        patcher = patch.object(qw, "client_for", lambda host: self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_set_request_splits_script_into_statements(self):
        worker = qw.QueryWorker()
        worker.set_request(
            "h", "db",
            "SELECT 1; -- comment\nSELECT 2;\nUPDATE t SET a=1",
            1000,
        )
        self.assertEqual(worker._statements, [
            "SELECT 1",
            "SELECT 2",
            "UPDATE t SET a=1",
        ])

    def test_set_request_empty_and_comments_only(self):
        worker = qw.QueryWorker()
        worker.set_request("h", "db", "  -- just a comment\n# another", 1000)
        self.assertEqual(worker._statements, [])

    def test_execute_runs_all_statements_and_merges_rows(self):
        cursors = [
            FakeResultCursor(["id", "name"], [{"id": 1, "name": "a"}]),
            FakeResultCursor(["id", "name"], [{"id": 2, "name": "b"}]),
            FakeResultCursor(["id", "name"], [], rowcount=2),
        ]

        class ScriptConn:
            def __init__(self):
                self._q = list(cursors)
                self._id = 7

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def thread_id(self):
                return self._id

            def cursor(self):
                return self._q.pop(0)

        self.fake.conn = ScriptConn()
        worker = qw.QueryWorker()
        worker.set_request("h", "db", "SELECT 1; SELECT 2; UPDATE t SET a=1", 1000)

        rows, columns, message = worker._execute_sql(
            "h", "db", worker._statements, 1000,
        )

        self.assertEqual(columns, ["id", "name"])
        self.assertEqual(rows, [[1, "a"], [2, "b"]])
        self.assertIn("row(s)", message)
        self.assertEqual(
            [cur.executed for cur in cursors][:2],
            [["SELECT 1"], ["SELECT 2"]],
        )

    def test_execute_stops_between_statements(self):
        cursors = [
            FakeResultCursor(["id"], [{"id": 1}]),
            FakeResultCursor(["id"], [{"id": 2}]),
        ]

        class ScriptConn:
            def __init__(self):
                self._q = list(cursors)
                self._id = 7

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def thread_id(self):
                return self._id

            def cursor(self):
                return self._q.pop(0)

        self.fake.conn = ScriptConn()
        worker = qw.QueryWorker()
        worker.set_request("h", "db", "SELECT 1; SELECT 2", 1000)

        worker._stop = True

        rows, columns, message = worker._execute_sql(
            "h", "db", worker._statements, 1000,
        )

        self.assertEqual(rows, [])
        self.assertEqual(cursors[1].executed, [])
        self.assertIn("No statements executed", message)

    def test_combine_skips_mismatched_columns(self):
        per_statement = [
            (["id"], [["1"]], "1 row(s) of 1"),
            (["other"], [["x"]], "1 row(s) of 1"),
            ([], [], "3 row(s) affected"),
        ]
        rows, columns, message = qw.QueryWorker._combine_results(
            per_statement, 1.5,
        )

        self.assertEqual(columns, ["id"])
        self.assertEqual(rows, [["1"]])
        self.assertIn("skipped", message)
        self.assertIn("row(s) affected", message)


class TestQueryWorkerExport(unittest.TestCase):
    def setUp(self):
        self.fake = FakeMySQL()
        patcher = patch.object(qw, "client_for", lambda host: self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_run_export_writes_all_rows_to_csv(self):
        cursors = [
            FakeResultCursor(
                ["id", "name"],
                [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}],
            ),
        ]
        self.fake.conn = ScriptConn(cursors)

        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)

        try:
            worker = qw.QueryWorker()
            worker.set_export_request(
                [("host1", "db1")],
                "SELECT id, name FROM t",
                path,
            )

            events = []
            worker.export_done.connect(lambda n, p: events.append((n, p)))

            worker._run_export()

            with open(path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))

            self.assertEqual(
                rows,
                [
                    ["Server", "Database", "id", "name"],
                    ["host1", "db1", "1", "a"],
                    ["host1", "db1", "2", "b"],
                ],
            )
            self.assertEqual(events, [(2, path)])
        finally:
            os.unlink(path)

    def test_run_export_multi_targets_writes_each_row(self):
        self.fake.conn = ScriptConn([
            FakeResultCursor(["id"], [{"id": 1}]),
            FakeResultCursor(["id"], [{"id": 2}]),
        ])

        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)

        try:
            worker = qw.QueryWorker()
            worker.set_export_request(
                [("h1", "db1"), ("h2", "db2")],
                "SELECT id FROM t",
                path,
            )

            worker._run_export()

            with open(path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))

            self.assertEqual(
                rows,
                [
                    ["Server", "Database", "id"],
                    ["h1", "db1", "1"],
                    ["h2", "db2", "2"],
                ],
            )
        finally:
            os.unlink(path)

    def test_run_export_skips_affected_statements(self):
        self.fake.conn = ScriptConn([
            FakeResultCursor(["id"], [{"id": 1}]),
            FakeCursor(),
        ])

        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)

        try:
            worker = qw.QueryWorker()
            worker.set_export_request(
                [("h1", "db1")],
                "SELECT id FROM t; UPDATE t SET a=1",
                path,
            )

            events = []
            worker.export_done.connect(lambda n, p: events.append((n, p)))

            worker._run_export()

            with open(path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))

            self.assertEqual(
                rows,
                [
                    ["Server", "Database", "id"],
                    ["h1", "db1", "1"],
                ],
            )
            self.assertEqual(events, [(1, path)])
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
