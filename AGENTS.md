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
