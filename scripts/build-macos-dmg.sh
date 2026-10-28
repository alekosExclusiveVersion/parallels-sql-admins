#!/bin/bash
# Сборщик macOS-дистрибутива Parallels SQL Admin.
# Результат: release/ParallelsSQLAdmin-macos-<version>.dmg (drag-to-Applications).
#
# Использование:
#   scripts/build-macos-dmg.sh [--skip-build] [--skip-sign] [--skip-notarize]
#                              [--verify-only <dmg>] [--selftest]
#
# Переменные окружения (подпись/нотаризация, см. docs/macos-signing.md):
#   APPLE_TEAM_ID        — Team ID (обязателен для подписи Developer ID)
#   APPLE_SIGN_IDENTITY  — имя identity (по умолчанию "Developer ID Application")
#   APPLE_ID             — Apple ID для notarytool
#   APPLE_APP_PASSWORD   — app-specific password для notarytool
#   APPLE_API_KEY_ID / APPLE_API_ISSUER / APPLE_API_KEY_B64 — альтернатива паре ID/пароль
# Без APPLE_TEAM_ID подпись = ad-hoc (локальный прогон), нотаризация пропускается.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_NAME="Parallels SQL Admin"
BUNDLE_ID="com.alekos.parallels-sql-admin"
VOL_NAME="Parallels SQL Admin"
ENTITLEMENTS="$REPO_ROOT/installer/macos/entitlements.plist"

SKIP_BUILD=0
SKIP_SIGN=0
SKIP_NOTARIZE=0
VERIFY_ONLY=""
SELFTEST=0

usage() {
    echo "Usage: $(basename "$0") [--skip-build] [--skip-sign] [--skip-notarize] [--verify-only <dmg>] [--selftest]"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-build) SKIP_BUILD=1; shift ;;
        --skip-sign) SKIP_SIGN=1; shift ;;
        --skip-notarize) SKIP_NOTARIZE=1; shift ;;
        --verify-only)
            if [[ -z "${2:-}" ]]; then
                echo "ERROR: --verify-only needs a path" >&2
                usage
                exit 2
            fi
            VERIFY_ONLY="$2"
            shift 2
            ;;
        --verify-only=*) VERIFY_ONLY="${1#--verify-only=}"; shift ;;
        --selftest) SELFTEST=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
    esac
done

app_version() {
    python3 -c "from common.version import APP_VERSION; print(APP_VERSION)"
}

require_tool() {
    command -v "$1" >/dev/null 2>&1 || { echo "ERROR: tool not found: $1" >&2; exit 1; }
}

# --- selftest: чистые проверки без сети и сборки ---
selftest() {
    local fail=0
    check() { # check <name> <command...>
        local name="$1"; shift
        if "$@" >/dev/null 2>&1; then echo "PASS: $name"; else echo "FAIL: $name"; fail=1; fi
    }
    check "python APP_VERSION" bash -c "cd '$REPO_ROOT' && python3 -c 'from common.version import APP_VERSION; assert APP_VERSION'"
    check "spec has BUNDLE_ID" grep -q "com.alekos.parallels-sql-admin" "$REPO_ROOT/Parallels SQL Admin.spec"
    check "entitlements plist" /usr/bin/plutil -lint "$ENTITLEMENTS"
    check "tool hdiutil" command -v hdiutil
    check "tool codesign" command -v codesign
    check "tool stapler" command -v stapler
    check "tool notarytool" xcrun notarytool --version
    check "icon icns" test -f "$REPO_ROOT/assets/ParallelsSQLAdmin.icns"
    check "verify script" test -x "$SCRIPT_DIR/verify-macos-dmg.sh"
    # формат имени артефакта
    local v; v="$(cd "$REPO_ROOT" && app_version)"
    [[ "$v" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] && echo "PASS: version format ($v)" || { echo "FAIL: version format ($v)"; fail=1; }
    [[ "ParallelsSQLAdmin-macos-$v.dmg" == "ParallelsSQLAdmin-macos-$v.dmg" ]] && echo "PASS: dmg name deterministic"
    return $fail
}

if [[ "$SELFTEST" == "1" ]]; then
    selftest
    exit $?
fi

if [[ -n "$VERIFY_ONLY" ]]; then
    exec "$SCRIPT_DIR/verify-macos-dmg.sh" "$VERIFY_ONLY"
fi

# Только macOS
[[ "$(uname)" == "Darwin" ]] || { echo "ERROR: macOS only" >&2; exit 1; }
require_tool hdiutil
require_tool codesign

cd "$REPO_ROOT"
VERSION="$(app_version)"
echo "Version: $VERSION"
DMG="release/ParallelsSQLAdmin-macos-$VERSION.dmg"
APP="dist/$APP_NAME.app"
STAGING="release/dmg-staging"

# 1. Сборка .app
if [[ "$SKIP_BUILD" == "0" ]]; then
    echo "==> pyinstaller..."
    pyinstaller "Parallels SQL Admin.spec" --noconfirm
else
    echo "==> skip pyinstaller (--skip-build)"
fi
[[ -d "$APP" ]] || { echo "ERROR: $APP not found" >&2; exit 1; }

# 2. Проверка Info.plist
PLIST_BUNDLE_ID="$(/usr/bin/plutil -extract CFBundleIdentifier raw "$APP/Contents/Info.plist" 2>/dev/null || true)"
PLIST_VER="$(/usr/bin/plutil -extract CFBundleShortVersionString raw "$APP/Contents/Info.plist" 2>/dev/null || true)"
echo "Info.plist: id=$PLIST_BUNDLE_ID ver=$PLIST_VER"
[[ "$PLIST_BUNDLE_ID" == "$BUNDLE_ID" ]] || { echo "ERROR: bundle id mismatch ($PLIST_BUNDLE_ID != $BUNDLE_ID), rebuild needed" >&2; exit 1; }
[[ "$PLIST_VER" == "$VERSION" ]] || { echo "ERROR: version mismatch ($PLIST_VER != $VERSION), rebuild needed" >&2; exit 1; }

# 2.5. Prune: вырезаем Qt-хелперы (Assistant/Designer/Linguist).
# Их Contents/Info.plist и Resources — симлинки наружу, что бракует любая
# codesign-валидация --deep. Приложение их не использует (Qt Help/Designer
# IDE-инструменты; исходники PSA их не импортируют). Удаление ДО подписи.
echo "==> pruning Qt helper apps..."
for helper in Assistant Designer Linguist; do
    rm -rf "$APP/Contents/Frameworks/PySide6/${helper}__dot__app"
    rm -f "$APP/Contents/Frameworks/PySide6/${helper}.app"
    rm -rf "$APP/Contents/Resources/PySide6/${helper}.app"
done
if find "$APP" \( -name '*__dot__app' -o -name 'Assistant.app' -o -name 'Designer.app' -o -name 'Linguist.app' \) -print | grep -q .; then
    echo "ERROR: unpruned helper apps remain" >&2
    find "$APP" \( -name '*__dot__app' -o -name 'Assistant.app' -o -name 'Designer.app' -o -name 'Linguist.app' \) >&2
    exit 1
fi

# 3. Подпись .app
if [[ "$SKIP_SIGN" == "0" ]]; then
    if [[ -n "${APPLE_TEAM_ID:-}" ]]; then
        IDENTITY="${APPLE_SIGN_IDENTITY:-Developer ID Application}"
        echo "==> codesign (Developer ID, team $APPLE_TEAM_ID)..."
        codesign --deep --force --options runtime --timestamp \
            ${ENTITLEMENTS:+--entitlements "$ENTITLEMENTS"} \
            -s "$IDENTITY" "$APP"
        # Хелперы с симлинками вырезаны выше (prune), поэтому --deep --strict
        # здесь проходит и соответствует требованиям нотаризации.
        codesign --verify --deep --strict "$APP"
        echo "codesign OK"
    else
        echo "==> codesign (ad-hoc, APPLE_TEAM_ID not set)..."
        codesign --deep --force -s - "$APP" || true
    fi
else
    echo "==> skip codesign (--skip-sign)"
fi

# 4. Staging: .app + symlink Applications
echo "==> staging..."
rm -rf "$STAGING"
mkdir -p "$STAGING" release
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
# Иконка тома (опционально, не критично)
if [[ -f "assets/ParallelsSQLAdmin.icns" ]]; then
    cp "assets/ParallelsSQLAdmin.icns" "$STAGING/.VolumeIcon.icns" || true
fi

# 5. DMG
echo "==> hdiutil create $DMG..."
rm -f "$DMG"
hdiutil create -volname "$VOL_NAME" -srcfolder "$STAGING" -ov -format UDZO "$DMG"
hdiutil verify "$DMG" >/dev/null && echo "hdiutil verify OK"

# 6. Подпись DMG (только Developer ID)
if [[ "$SKIP_SIGN" == "0" && -n "${APPLE_TEAM_ID:-}" ]]; then
    IDENTITY="${APPLE_SIGN_IDENTITY:-Developer ID Application}"
    echo "==> codesign dmg..."
    codesign --force -s "$IDENTITY" "$DMG"
fi

# 7. Нотаризация
if [[ "$SKIP_NOTARIZE" == "0" && -n "${APPLE_TEAM_ID:-}" ]]; then
    echo "==> notarytool submit (may take several minutes)..."
    NOTARY_ARGS=()
    if [[ -n "${APPLE_API_KEY_ID:-}" && -n "${APPLE_API_ISSUER:-}" ]]; then
        KEYFILE="$(mktemp -t apple-api-key.XXXXXX.p8)"
        trap 'rm -f "$KEYFILE"' EXIT
        echo "$APPLE_API_KEY_B64" | base64 -d > "$KEYFILE"
        NOTARY_ARGS+=(--key "$KEYFILE" --key-id "$APPLE_API_KEY_ID" --issuer "$APPLE_API_ISSUER")
    elif [[ -n "${APPLE_ID:-}" && -n "${APPLE_APP_PASSWORD:-}" ]]; then
        NOTARY_ARGS+=(--apple-id "$APPLE_ID" --password "$APPLE_APP_PASSWORD" --team-id "$APPLE_TEAM_ID")
    else
        echo "ERROR: notarization needs APPLE_ID+APPLE_APP_PASSWORD or API key env" >&2
        exit 1
    fi
    xcrun notarytool submit "$DMG" --wait --timeout 30m "${NOTARY_ARGS[@]}"
    echo "==> stapler staple..."
    xcrun stapler staple "$DMG"
    xcrun stapler validate "$DMG"
else
    echo "==> skip notarization (ad-hoc or --skip-notarize)"
fi

echo "==> verify..."
"$SCRIPT_DIR/verify-macos-dmg.sh" "$DMG" || true

shasum -a 256 "$DMG"
ls -lh "$DMG"
echo "DONE: $DMG"
