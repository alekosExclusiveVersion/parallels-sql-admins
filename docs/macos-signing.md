# Подпись и нотаризация macOS-сборки

DMG (`ParallelsSQLAdmin-macos-<version>.dmg`, drag-to-Applications) собирается
скриптом `scripts/build-macos-dmg.sh`, проверяется `scripts/verify-macos-dmg.sh`.

Bundle ID зафиксирован: `com.alekos.parallels-sql-admin` (spec `BUNDLE_ID`).
Не менять без согласования — от него зависит профиль нотаризации.

## Режимы

| Режим | Как | Gatekeeper |
|---|---|---|
| Локальный (ad-hoc) | `./scripts/build-macos-dmg.sh --skip-notarize` без `APPLE_TEAM_ID` | будет предупреждение, для внутреннего использования ок |
| Релизный (Developer ID) | `APPLE_TEAM_ID` + сертификат (локально из keychain, в CI из секретов) + нотаризация | чисто, без предупреждений |

## 1. Сертификат (один раз)

На Mac с Apple Developer Program:

1. Xcode → Settings → Accounts → Manage Certificates → `+` → `Developer ID Application`.
2. Экспорт в `.p12` (Keychain Access → правый клик → Export, задать пароль).
3. Локально: оставить в login keychain — `codesign` подхватит по имени
   (`APPLE_SIGN_IDENTITY`, по умолчанию `Developer ID Application`).

## 2. Нотаризация: учетные данные

Вариант A (простой): Apple ID + app-specific password
(appleid.apple.com → Sign-In and Security → App-Specific Passwords):

- `APPLE_ID`, `APPLE_APP_PASSWORD`, `APPLE_TEAM_ID`.

Вариант B (рекомендуется для CI): App Store Connect API key
(Users and Access → Integrations → App Store Connect API → Team Keys):

- `APPLE_API_KEY_ID`, `APPLE_API_ISSUER`, `APPLE_API_KEY_B64` (`.p8` в base64), `APPLE_TEAM_ID`.

## 3. Секреты GitHub Actions

Репозиторий → Settings → Secrets and variables → Actions:

- `APPLE_CERT_P12_B64` — `.p12` в base64: `base64 -i cert.p12 | pbcopy`
- `APPLE_CERT_PASSWORD` — пароль `.p12`
- `APPLE_TEAM_ID` — Team ID (10 символов)
- Плюс вариант A или B из раздела 2.

Без секретов джоба собирает ad-hoc DMG без подписи/нотаризации
(сборка и нестрогая проверка всё равно валидируются); на push тэга
без полного комплекта секретов — явная ошибка: релиз без подписи
уходить не должен.

## 4. Локальная сборка

```bash
# selftest без сети/сборки
scripts/build-macos-dmg.sh --selftest

# внутренний прогон без подписи/нотаризации
scripts/build-macos-dmg.sh --skip-sign --skip-notarize

# релизный прогон (сертификат в keychain + env для notarytool)
APPLE_TEAM_ID=XXXXXXXXXX APPLE_ID=you@example.com APPLE_APP_PASSWORD=xxxx \
  scripts/build-macos-dmg.sh

# только проверка готового dmg
scripts/verify-macos-dmg.sh release/ParallelsSQLAdmin-macos-4.33.3.dmg
scripts/verify-macos-dmg.sh release/ParallelsSQLAdmin-macos-4.33.3.dmg --expect-signed
```

## 5. Проверки (`verify-macos-dmg.sh`)

`hdiutil verify` → состав (`.app` + symlink `Applications`) → версия и bundle id
из `Info.plist` против `common.version.APP_VERSION` → `codesign --verify --deep --strict` →
`spctl -a -t exec` → `stapler validate` → smoke-запуск `.app` на 8 сек.

Сборщик перед подписью вырезает из бандла Qt-хелперы Assistant/Designer/Linguist
(prune-шаг): их `Contents/Info.plist` и `Resources` — симлинки наружу, что бракует
любая `--deep`-валидация. Приложение их не использует.

Для ad-hoc сборок `spctl`/`stapler` — SKIP (не FAIL); с флагом `--expect-signed` — строгий FAIL.

## 6. Ограничения

- Сборка под архитектуру хоста (`target_arch=None`): на Apple Silicon — arm64.
  Intel-Mac требует отдельной x86_64-сборки или `universal2` — в v1 не делаем.
- Нотаризация занимает минуты; в CI `notarytool submit --wait --timeout 30m`.
- Срок действия Developer ID: по истечении обновить сертификат и секрет `APPLE_CERT_P12_B64`.
