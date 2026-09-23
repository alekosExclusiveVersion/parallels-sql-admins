# Project Rules

## Versioning (SemVer-style)

`APP_VERSION` in `common/version.py` follows three-component scheme:

| Digit | Role | When to bump | Example |
|-------|------|-------------|---------|
| **1st** (major) | Major milestones | Global architectural changes, breaking changes, major rewrites | 3.x.x → 4.0.0 |
| **2nd** (minor) | Features | New functionality, new UI panels, new capabilities | 4.26.x → 4.27.0 |
| **3rd** (patch) | Fixes | Bug fixes, refactoring, CI fixes, performance improvements | 4.27.0 → 4.27.1 |

Rules:
- Bump the appropriate digit and reset all lower digits to 0 (e.g. 4.27.3 → 4.28.0 when adding a feature)
- Never skip digits
- Every commit that changes `APP_VERSION` must also update `CFBundleVersion` and `CFBundleShortVersionString` in the PyInstaller spec (handled automatically via `common.version.APP_VERSION`)

## Testing

- Framework: `unittest` (no pytest in CI)
- Run full suite: `QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -q`
- Qt widget tests must use `QT_QPA_PLATFORM=offscreen`
- tearDown must clean up Qt widgets: `widget.close()` + `widget.deleteLater()`

## Build

- macOS: `pyinstaller "Parallels SQL Admin.spec" --noconfirm`
- CI builds for Windows + Ubuntu (GitHub Actions)
- **Always rebuild** after every code change that affects the app (GUI, backend, common). Run `pyinstaller` and verify `CFBundleShortVersionString` in `dist/Parallels SQL Admin.app/Contents/Info.plist` before committing.

## Security

- **No secrets, keys, passwords, or encryption material** in the repository
- `servers.json` contains encrypted passwords — never commit unencrypted credentials
- `config.ini` may contain empty password fields — never populate them with real credentials
- `.env`, `*.key`, `*.pem`, `*.secret` files must never be committed
- If you accidentally stage a secret, remove it from the index before committing

## Read-only DB access (headless scripts)

Real server credentials live in the app data dir, **not** in the repo config:

- macOS data dir: `~/Library/Application Support/Parallels SQL Admin/`
- `servers.json` holds hosts + passwords encrypted with a Fernet key from `servers.key` (vault backend `file_key`, auto-unlock via `registry.ensure_key()`)
- Do **not** copy passwords or `servers.key` into repo files; scripts must read credentials through the app's own code

To run a script that connects with real credentials (same path the GUI uses):

```python
import sys
from pathlib import Path

APP = Path.home() / "Library/Application Support/Parallels SQL Admin"
sys.path.insert(0, "/path/to/parallels-sql-admins")

import common.config as C
cfg = C.load_config(APP / "config.ini")
object.__setattr__(cfg.advanced, "servers_file", str(APP / "servers.json"))
C.config = cfg

from common.server_registry import ServerRegistry

sr = ServerRegistry()
sr.ensure_key()
mysql_hosts = [s.host for s in sr.load() if s.engine == "mysql" and s.password]

from common.mysql_client import mysql

# read-only query with LIMIT
rows = mysql.query(host, "SELECT ... LIMIT 10", params=())
mysql.close_all()
```

Hints:
- `cfg.advanced` is a frozen dataclass — override `servers_file` only via `object.__setattr__`
- The repo `config.ini` points to `servers.txt`/repo `servers.json` with empty passwords — pointing at it yields "Access denied ... using password: NO"
- Domain for a database lives in that DB's `cfg_settings` table under key `csSiteDomain` (e.g. `www.autopolyus.ru`), not in Plesk `psa` (which does not exist on these hosts)
- Domain lookup (`search_databases`): for name masks the site is filled from `cfg_settings.csSiteDomain` per DB; for domain masks (containing a dot) DBs are matched by the same key (only DBs passing the `database_prefix`/`exclude_database_regex`/`ignore` filters are scanned, then `UNION ALL` per 50 DBs)

## Web-pricing monitoring (pricing_alert.py)

Stands alerts for the web-pricing subsystem: queries Grafana/ClickHouse
(`provider_logs`, `provider_runtime_logs`), compares the last `window_seconds`
with the same window a day ago and, on anomaly, notifies macOS banner, the
B24 chat and the Telegram room with Grafana dashboard links.

- Run: `/opt/homebrew/bin/python3 pricing_alert.py`; thresholds in
  `pricing_alert_config.json` (`increase_factor`, `runtime_abs_sec`,
  `errors_abs_pct`, `volume_drop`, `escalate_every_hours`, `window_seconds`).
- Triggers: provider avg runtime >= `runtime_abs_sec` and > `increase_factor`x
  norm; error share (status >=500) >= `errors_abs_pct` and > `increase_factor`x
  norm; request volume < `(1 - volume_drop)` of norm.
- Dedup: notify on incident start, then every `escalate_every_hours` while it
  lasts, and a recovery message when it clears. State in `logs/pricing_alert_state.json`.
- On first incident notify `detect_pricing_degradation.py` runs once (phase 2,
  MySQL scan) and lists up to 8 databases with "Превышено время ожидания"
  (metric `timeouts`, `DELTA` = multiplier vs baseline).
- Secrets come from macOS Keychain, never from the repo:
  Grafana `opencode.grafana.login`/`opencode.grafana.password`; Telegram
  `opencode.tg-alert-token`, `opencode.tg-alert-chat2` (supergroup
  `-1001616129406`), `opencode.tg-alert-thread` (topic 4385); B24 uses the
  ts-b24 webhook (no scope stored here).
- Scheduled by LaunchAgent `com.tradesoft.pricing-alert` (every 15 min,
  StartInterval 900); logs in `logs/pricing_alert.log`.
- Message layout: header with MSK time range, "Итог…" summary line with
  human-readable multipliers (×N = times slower than the day-ago norm),
  per-provider slow/error lists, top timeout databases, then links to Grafana
  panels 25 (runtime) and 27 (error %).

## Code Style

- No comments unless asked
- Russian UI strings, English code/identifiers
- Follow existing patterns (signals/slots, WorkerHost, client_for dispatch)

## Release

When `APP_VERSION` is bumped (the `chore: bump version to X.Y.Z` commit), a git
tag **must** be created and pushed so CI publishes a GitHub Release with build
artifacts:

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

CI (`.github/workflows/build.yml`) automatically builds Windows installer +
portable zip and Linux tar.gz, then attaches them to the GitHub Release.

Never push a tag without a corresponding version bump commit — the tag and
`APP_VERSION` must always match.

## GitHub Actions (CI)

Keep actions in `.github/workflows/build.yml` on **current major versions**
(targeting Node 24, not deprecated Node 20). GitHub forces Node-20 actions to
run on Node 24 and warns; relying on that shim risks silent CI breakage.

Current baseline (as of 4.29.x):

| Action | Version |
|--------|---------|
| `actions/checkout` | `@v7` |
| `actions/setup-python` | `@v7` |
| `actions/upload-artifact` | `@v7` |
| `softprops/action-gh-release` | `@v3` |

Before bumping an action, verify its latest release (tag + Node runtime) via the
GitHub API (`.../releases/latest`) and confirm a CI run passes after the change.
Treat deprecation annotations in workflow runs as a prompt to update.

## Commits

Format: `<type>(<scope>): <short summary>`

```
<type>(<scope>): <short summary — max 72 chars, imperative mood, no period>

<blank line>

<optional body — detailed description of what and why, wrapped at 80 chars>
```

### Type
| Type | When |
|------|------|
| `feat` | New feature |
| `fix` | Bug fix |
| `refactor` | Code restructure without behavior change |
| `chore` | Build, version bump, CI, config |
| `test` | Adding or updating tests |
| `docs` | Documentation only |

### Scope
Module or area affected: `mssql`, `pgsql`, `mysql`, `sql-console`, `servers-tree`, `tests`, `ci`, etc.

### Rules
- Summary is **imperative mood** ("add", not "added" / "adds")
- Summary has **no period** at the end
- Summary is **one line**, max 72 characters
- Body explains **what** and **why**, not **how** (code shows how)
- Reference issues: `Closes #123` in body
