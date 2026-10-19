"""
debug_password_trace.py

Диагностика гипотезы: "пустые результаты Check из-за того, что пароль
не передаётся из сессии или сбрасывается".

Что делает:
1. Эмулирует вход как LoginDialog (session.user / session.password).
2. Оборачивает pymysql.connect, чтобы логировать ВСЕ реальные аргументы
   (host/user/password/database) в момент каждого подключения.
3. Запускает CheckWorker в QThread (как в MainWindow).
4. Снимает session до/во время/после запуска.

Запуск:  python3 debug/debug_password_trace.py
"""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import sys

import pymysql

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

# --- эмуляция LoginDialog -------------------------------------------
from common.mysql_session import session

session.user = os.environ.get("DBG_USER", "demo_user")
session.password = os.environ.get("DBG_PASSWORD", "dummy_password")

# --- перехват реального connect --------------------------------------
_original_connect = pymysql.connect
_calls = []


def traced_connect(*args, **kwargs):
    # маскируем пароль в логе, но фиксируем факт его наличия/пустоты
    pwd = kwargs.get("password")
    has_pwd = bool(pwd)
    _calls.append(
        {
            "host": kwargs.get("host"),
            "user": "<SET>" if kwargs.get("user") else "<EMPTY>",
            "has_password": has_pwd,
            "database": kwargs.get("database"),
        }
    )
    print(
        f"[connect] host={kwargs.get('host')} "
        f"user={'<SET>' if kwargs.get('user') else '<EMPTY>'} "
        f"password={'<SET>' if has_pwd else '<EMPTY>'} db={kwargs.get('database')}",
        flush=True,
    )
    raise RuntimeError(
        f"FAKE: connect called for {kwargs.get('host')} "
        f"(password={'SET' if has_pwd else 'EMPTY'})"
    )


pymysql.connect = traced_connect

# --- MainWindow --------------------------------------------------------
from gui.main_window import MainWindow

w = MainWindow()
w.show()

w.worker.result.connect(lambda *a: print("SIGNAL result:", a[:2], flush=True))
w.worker.finished.connect(lambda: print("SIGNAL finished", flush=True))
w.worker.status.connect(lambda s: print("SIGNAL status:", s, flush=True))


def check_session(tag):
    print(
        f"[session:{tag}] "
        f"user={'<SET>' if session.user else '<EMPTY>'} "
        f"password={'<SET>' if session.password else '<EMPTY>'}",
        flush=True,
    )


check_session("before-check")

w.server_list.selectAll()
w._run_check()


def done():
    check_session("after-check")
    print("=== CONNECT CALLS ===", flush=True)
    if not _calls:
        print("  (pymysql.connect НЕ вызывался вообще)", flush=True)
    for c in _calls:
        print(
            f"  host={c['host']} user={c['user']} "
            f"password={'SET' if c['has_password'] else 'EMPTY'} "
            f"db={c['database']}",
            flush=True,
        )
    pymysql.connect = _original_connect
    app.quit()


QTimer.singleShot(10000, done)
app.exec()
