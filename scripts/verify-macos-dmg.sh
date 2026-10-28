#!/bin/bash
# Проверка macOS-дистрибутива: hdiutil verify, состав, подпись, Gatekeeper, stapler, версия, smoke.
# Использование: scripts/verify-macos-dmg.sh <dmg> [--expect-signed]
# Коды выхода: 0 — все проверки прошли; 1 — есть FAIL.
set -uo pipefail

DMG="${1:-}"
EXPECT_SIGNED=0
[[ "${2:-}" == "--expect-signed" ]] && EXPECT_SIGNED=1

[[ -n "$DMG" ]] || { echo "Usage: $(basename "$0") <dmg> [--expect-signed]" >&2; exit 2; }
[[ -f "$DMG" ]] || { echo "ERROR: file not found: $DMG" >&2; exit 2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_NAME="Parallels SQL Admin"
BUNDLE_ID="com.alekos.parallels-sql-admin"
EXPECTED_VER="$(cd "$REPO_ROOT" && python3 -c 'from common.version import APP_VERSION; print(APP_VERSION)')"

PASS=0; FAIL=0
ok() { echo "PASS: $1"; PASS=$((PASS+1)); }
bad() { echo "FAIL: $1${2:+ — $2}"; FAIL=$((FAIL+1)); }

echo "DMG: $DMG (expect version $EXPECTED_VER)"

# 1. Целостность образа
if hdiutil verify "$DMG" >/dev/null 2>&1; then ok "hdiutil verify"; else bad "hdiutil verify"; fi

# 2. Монтирование и состав
MNT="$(mktemp -d -t psa-dmg.XXXXXX)"
cleanup() { hdiutil detach "$MNT" >/dev/null 2>&1 || true; rmdir "$MNT" 2>/dev/null || true; }
trap cleanup EXIT
if hdiutil attach -nobrowse -readonly -mountpoint "$MNT" "$DMG" >/dev/null 2>&1; then
    ok "hdiutil attach"
else
    bad "hdiutil attach"; echo "RESULT: $PASS pass, $FAIL fail"; exit 1
fi

APP="$MNT/$APP_NAME.app"
[[ -d "$APP" ]] && ok ".app inside dmg" || bad ".app inside dmg"
[[ -L "$MNT/Applications" ]] && ok "Applications symlink" || bad "Applications symlink"

# 3. Версия и bundle id
if [[ -d "$APP" ]]; then
    PLIST_VER="$(/usr/bin/plutil -extract CFBundleShortVersionString raw "$APP/Contents/Info.plist" 2>/dev/null || echo MISSING)"
    [[ "$PLIST_VER" == "$EXPECTED_VER" ]] && ok "version $PLIST_VER" || bad "version" "got $PLIST_VER, want $EXPECTED_VER"
    PLIST_ID="$(/usr/bin/plutil -extract CFBundleIdentifier raw "$APP/Contents/Info.plist" 2>/dev/null || echo MISSING)"
    [[ "$PLIST_ID" == "$BUNDLE_ID" ]] && ok "bundle id $PLIST_ID" || bad "bundle id" "got $PLIST_ID, want $BUNDLE_ID"
    [[ -x "$APP/Contents/MacOS/$APP_NAME" ]] && ok "executable present" || bad "executable present"
fi

# 4. Подпись
if [[ -d "$APP" ]]; then
# Хелперы с симлинками вырезаны сборщиком (prune), поэтому --deep --strict
# здесь проходит и соответствует требованиям нотаризации.
    if codesign --verify --deep --strict "$APP" 2>/dev/null; then
        SIG="$(codesign -dv "$APP" 2>&1 | grep -m1 'Authority=' || echo 'Authority=ad-hoc/unknown')"
        ok "codesign verify ($SIG)"
    else
        bad "codesign verify"
    fi
    # Gatekeeper
    if spctl -a -t exec "$APP" 2>/dev/null; then
        ok "spctl accept"
    else
        if [[ "$EXPECT_SIGNED" == "1" ]]; then bad "spctl accept"; else echo "SKIP: spctl accept (ad-hoc build, use --expect-signed for release)"; fi
    fi
    # Stapler (нотаризация пришита к .app внутри dmg обычно отсутствует — тикет на самом dmg)
    if xcrun stapler validate "$APP" >/dev/null 2>&1; then ok "stapler validate (.app)"; else echo "SKIP: stapler validate (.app) — ticket is on dmg, not app"; fi
fi

# 5. Smoke: запуск бинаря напрямую на 8 сек (как CI smoke-test).
# Не через `open` — LaunchServices держит образ занятым и detach потом виснет.
SMOKE_PID=""
if [[ -d "$APP" ]]; then
    # Чистим возможные остатки прошлых прогонов (single-instance лок),
    # иначе новый экземпляр может сразу выйти и дать ложный FAIL.
    pkill -f "$APP_NAME.app/Contents/MacOS" 2>/dev/null || true
    sleep 1
    "$APP/Contents/MacOS/$APP_NAME" >/dev/null 2>&1 &
    SMOKE_PID=$!
    sleep 8
    if kill -0 "$SMOKE_PID" 2>/dev/null; then
        ok "smoke: app alive after 8s"
    else
        bad "smoke: app exited early"
        SMOKE_PID=""
        CRASHLOG="$HOME/Library/Logs/DiagnosticReports"
        ls -t "$CRASHLOG" 2>/dev/null | head -3 || true
    fi
    if [[ -n "$SMOKE_PID" ]]; then
        kill "$SMOKE_PID" 2>/dev/null || true
        wait "$SMOKE_PID" 2>/dev/null || true
        sleep 2
        kill -9 "$SMOKE_PID" 2>/dev/null || true
        wait "$SMOKE_PID" 2>/dev/null || true
    fi
    # Добиваем возможные остатки, держащие точку монтирования
    pkill -f "$APP_NAME.app/Contents/MacOS" 2>/dev/null || true
    sleep 1
fi

if hdiutil detach "$MNT" >/dev/null 2>&1; then
    ok "hdiutil detach"
else
    sleep 3
    if hdiutil detach "$MNT" -force >/dev/null 2>&1; then
        ok "hdiutil detach (forced)"
    else
        bad "hdiutil detach" "image busy — check hdiutil info"
    fi
fi
trap - EXIT; rmdir "$MNT" 2>/dev/null || true

# 6. Stapler на самом dmg (имеет смысл только для нотаризованных)
if xcrun stapler validate "$DMG" >/dev/null 2>&1; then
    ok "stapler validate (dmg)"
else
    if [[ "$EXPECT_SIGNED" == "1" ]]; then bad "stapler validate (dmg)"; else echo "SKIP: stapler validate (dmg) — not notarized (ad-hoc)"; fi
fi

echo "RESULT: $PASS pass, $FAIL fail"
[[ "$FAIL" == "0" ]]
