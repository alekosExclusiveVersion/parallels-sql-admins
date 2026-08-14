"""
common/paths.py

Кроссплатформенный каталог данных приложения.

- macOS:   ~/Library/Application Support/Parallels SQL Admin
- Windows: %APPDATA%\\Parallels SQL Admin
- Linux:   $XDG_CONFIG_HOME/parallels-sql-admin или ~/.config/parallels-sql-admin
"""

import os
import sys
from pathlib import Path

_APP_DIR_NAME = "Parallels SQL Admin"


def app_data_dir() -> Path:
    """Каталог данных приложения (создаётся при необходимости).

    В frozen-сборке сюда же выполняется os.chdir() (app.py), поэтому
    относительные пути config.ini (logs, servers.json) резолвятся
    из этого каталога на всех платформах.
    """
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(
            os.environ.get("APPDATA")
            or (Path.home() / "AppData" / "Roaming")
        )
    else:
        base = Path(
            os.environ.get("XDG_CONFIG_HOME")
            or (Path.home() / ".config")
        )

    data_dir = base / _APP_DIR_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
