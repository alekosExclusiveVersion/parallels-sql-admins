"""
common/updater.py

Проверка обновлений через GitHub Releases API и установка новой версии.

- При запуске (и раз в сутки) приложение сравнивает APP_VERSION с последним
  релизом (публичный репозиторий, токен не нужен);
- «Обновить сейчас» (Windows): скачивание Setup.exe с прогрессом, проверка
  Authenticode-подписи (издатель CN=Parallels SQL Admin, целостность) и запуск
  установщика; приложение закрывается (Inno Setup CloseApplications);
- «Не спрашивать до следующей версии» хранится в updates.json рядом с
  конфигом приложения;
- Сетевые/API-ошибки не показываются пользователю (молча в лог).
"""

from __future__ import annotations

import json
import os
import re
import ssl
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from common.logger import logger
from common.paths import app_data_dir
from common.version import APP_VERSION

REPO = "alekosExclusiveVersion/parallels-sql-admins"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases"
SETUP_ASSET_PREFIX = "ParallelsSQLAdmin-Setup-"
EXPECTED_PUBLISHER = "Parallels SQL Admin"

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(.*)$")

_SSL_CTX = ssl.create_default_context()


class CancelError(RuntimeError):
    """Отмена загрузки пользователем."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str | None
    html_url: str


def parse_version(text: str) -> tuple[int, int, int]:
    """'v4.24.7' / '4.24.6' -> (4, 24, 7). ValueError для мусора."""
    m = _VERSION_RE.match(text.strip())
    if not m:
        raise ValueError(f"не распознан номер версии: {text!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def version_newer(remote: str, current: str) -> bool:
    try:
        return parse_version(remote) > parse_version(current)
    except ValueError:
        return False


def _request_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"Parallels-SQL-Admin/{APP_VERSION}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))


def setup_download_url(version: str) -> str:
    """Детерминированный URL установщика для версии (формат с v4.24.8).

    Используется как запасной вариант, если ассет не нашёлся в ответе API.
    """
    v = version[1:] if version.startswith("v") else version
    return (
        f"https://github.com/{REPO}/releases/download/v{v}/"
        f"{SETUP_ASSET_PREFIX}{v}.exe"
    )


def fetch_latest(timeout: float = 10.0) -> UpdateInfo:
    data = _request_json(API_URL, timeout)
    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        raise ValueError("в ответе GitHub нет tag_name")
    version = tag[1:] if tag.startswith("v") else tag

    setup_url = None
    for asset in data.get("assets") or []:
        name = str(asset.get("name") or "")
        if name.startswith(SETUP_ASSET_PREFIX) and name.endswith(".exe"):
            setup_url = asset.get("browser_download_url")
            break

    if not setup_url:
        setup_url = setup_download_url(version)

    return UpdateInfo(
        version=version,
        url=setup_url,
        html_url=str(data.get("html_url") or RELEASES_URL),
    )


# ----------------------------------------------------------
# Состояние «не спрашивать до следующей версии»
# ----------------------------------------------------------

def _state_path() -> Path:
    return app_data_dir() / "updates.json"


def load_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    try:
        _state_path().write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def set_dont_ask_until(version: str) -> None:
    state = load_state()
    state["dont_ask_until"] = version
    save_state(state)


def should_notify(info: UpdateInfo) -> bool:
    """True, если для этой версии ещё не выбрано «не спрашивать»."""
    skip = str(load_state().get("dont_ask_until") or "")
    if not skip:
        return True
    try:
        return parse_version(info.version) > parse_version(skip)
    except ValueError:
        return True


# ----------------------------------------------------------
# Скачивание и установка
# ----------------------------------------------------------

def download(url: str, dest: Path, progress_cb=None) -> Path:
    req = urllib.request.Request(
        url, headers={"User-Agent": f"Parallels-SQL-Admin/{APP_VERSION}"}
    )
    with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as f:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)
    return dest


def verify_signature(exe: Path) -> bool:
    """Windows: проверка Authenticode-подписи (издатель + целостность).

    Статус NotTrusted/UnknownError допустим (самоподписанный корень);
    обязательны: подпись присутствует, издатель совпадает, хеш цел.
    """
    if os.name != "nt":
        return False
    script = (
        "$sig = Get-AuthenticodeSignature -FilePath '" + str(exe) + "'; "
        "if ($null -eq $sig.SignerCertificate) { exit 2 }; "
        "if ($sig.SignerCertificate.Subject -notlike 'CN="
        + EXPECTED_PUBLISHER + "*') { exit 3 }; "
        "if ($sig.Status -in @('HashMismatch','InvalidSignature','NotSupported')) "
        "{ exit 4 }; exit 0"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        logger.warning(f"Проверка подписи не пройдена (rc={result.returncode}): {exe.name}")
        return False
    return True


def install_update(info: UpdateInfo, progress_cb=None) -> Path:
    """Скачивает Setup.exe, проверяет подпись и запускает. Только Windows."""
    if os.name != "nt":
        raise RuntimeError("автоустановка доступна только на Windows")
    if not info.url:
        raise RuntimeError("в релизе нет Setup.exe")

    tmp = Path(tempfile.gettempdir()) / "ParallelsSQLAdmin-Setup-latest.exe"
    download(info.url, tmp, progress_cb)

    if not verify_signature(tmp):
        try:
            tmp.unlink()
        except OSError:
            pass
        raise RuntimeError("не удалось подтвердить подпись скачанного установщика")

    logger.info(f"Запуск установщика версии {info.version}: {tmp}")
    os.startfile(tmp)  # подпись проверена выше
    return tmp
