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

## Code Style

- No comments unless asked
- Russian UI strings, English code/identifiers
- Follow existing patterns (signals/slots, WorkerHost, client_for dispatch)
