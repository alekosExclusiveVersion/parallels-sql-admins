#!/usr/bin/env python3
"""Безопасная замена пароля сервера в Parallels SQL Admin.

Запуск:
    python3 tools/rotate_server_password.py <host> [port]

Пароль вводится интерактивно (не попадает в историю команд и не печатается).
"""

import getpass
import sys
from pathlib import Path

APP = Path.home() / "Library/Application Support/Parallels SQL Admin"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import common.config as C

cfg = C.load_config(APP / "config.ini")
object.__setattr__(cfg.advanced, "servers_file", str(APP / "servers.json"))
C.config = cfg

from common.server_registry import ServerRegistry, ServerSpec, client_for

host = sys.argv[1] if len(sys.argv) > 1 else "ext4.tradesoft.ru"
port = int(sys.argv[2]) if len(sys.argv) > 2 else 3306

sr = ServerRegistry()
sr.ensure_key()
specs = sr.load()
old = next((s for s in specs if s.host == host and s.port == port), None)
if old is None:
    print(f"Сервер {host}:{port} не найден в реестре")
    sys.exit(1)

new_password = getpass.getpass(f"Новый пароль для {host}:{port}: ")
if not new_password:
    print("Пароль пустой — отмена")
    sys.exit(1)

new_spec = ServerSpec(
    host=old.host,
    port=old.port,
    engine=old.engine,
    user=old.user or cfg.mysql.user,
    password=new_password,
    name=old.name,
    ref=old.ref,
)
sr.update(f"{old.host}:{old.port}", new_spec)
print(f"Пароль для {host}:{port} обновлён в хранилище")

# Проверка подключения без вывода пароля
try:
    cli = client_for(new_spec.host_key())
    rows = cli.query(new_spec.host_key(), "SELECT 1", params=())
    print("Проверка подключения: OK")
except Exception as exc:
    print(f"Проверка подключения: FAIL ({type(exc).__name__})")
    sys.exit(2)
PY
chmod +x /Users/aleksei/Work/scripts/parallels-sql-admins/tools/rotate_server_password.py
python3 -m py_compile /Users/aleksei/Work/scripts/parallels-sql-admins/tools/rotate_server_password.py && echo "syntax OK"