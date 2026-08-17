# Подпись Windows-сборки

Самоподписанный code-signing сертификат для `Parallels SQL Admin.exe`.
Цель — убрать красный блок SmartScreen «Windows защитил ваш компьютер»
(«Неизвестный издатель») на машинах, где сертификат установлен как
доверенный.

## Как это работает

- CI (GitHub Actions, Windows-джоба) подписывает exe сертификатом из
  секрета `CERT_PFX_B64` (PFX в base64) + `CERT_PFX_PASSWORD`.
- Подпись SHA-256 + RFC 3161-штамп времени (`http://timestamp.digicert.com`) —
  сигнатура остаётся действительной после истечения срока сертификата.
  Шаги подписи имеют таймаут (5 мин) — зависший timestamp-сервер
  не сможет повесить сборку.
- SmartScreen-репутация у самоподписанного издателя не накапливается,
  поэтому при первом запуске возможно жёлтое предупреждение
  «приложение не распространено» → «Подробнее → Выполнить в любом случае».
  Красный блок появляться не должен, если сертификат доверенный.

## 1. Генерация сертификата (один раз, можно на любом Windows)

PowerShell от администратора:

```powershell
$cert = New-SelfSignedCertificate -Type CodeSigningCert `
  -Subject "CN=Parallels SQL Admin, O=<Название компании>" `
  -KeyUsage DigitalSignature -KeyExportPolicy Exportable `
  -NotAfter (Get-Date).AddYears(5)
$cert
```

Экспорт (укажите пароль — он понадобится для CI):

```powershell
$pwd = Read-Host -AsSecureString -Prompt 'Пароль PFX'
Export-PfxCertificate -Cert $cert -FilePath codesign.pfx -Password $pwd
Export-Certificate -Cert $cert -FilePath codesign.cer
```

Срок действия 5 лет; по истечении повторить генерацию и заменить секреты.

### Альтернатива: openssl (macOS/Linux)

```bash
openssl req -x509 -newkey rsa:3072 -keyout key.pem -out cert.pem -days 1825 -sha256 \
  -subj "/CN=Parallels SQL Admin/O=<Название компании>" \
  -addext "keyUsage=digitalSignature" -addext "extendedKeyUsage=codeSigning"
openssl pkcs12 -export -out codesign.pfx -inkey key.pem -in cert.pem
openssl x509 -in cert.pem -outform der -out codesign.cer
```

## 2. Секреты GitHub Actions

Репозиторий → Settings → Secrets and variables → Actions:

- `CERT_PFX_B64` — содержимое `codesign.pfx` в base64. В PowerShell:

  ```powershell
  [Convert]::ToBase64String([IO.File]::ReadAllBytes('codesign.pfx'))
  ```

- `CERT_PFX_PASSWORD` — пароль от PFX.

Пока секреты не заданы, сборки проходят без подписи (в логе будет
предупреждение). Подпись включается автоматически после добавления секретов.

## 3. Доверие на машинах пользователей

Публичный сертификат `codesign.cer` (в корне репозитория) нужно установить
в два хранилища:

- **Доверенные корневые центры сертификации** (Trusted Root)
- **Доверенные издатели** (Trusted Publishers)

### Автоматически: инсталлятор Setup.exe

`ParallelsSQLAdmin-Setup.exe` (собирается в CI, аттачится к релизу по тегу)
ставит приложение и **сам добавляет `codesign.cer` в системные хранилища**
Trusted Root и Trusted Publishers через `certutil` (один запрос UAC за
всю установку). Ничего вручную делать не нужно. После установки
`Parallels SQL Admin.exe` запускается без предупреждений SmartScreen.

- Повторная установка/обновление безопасны (`certutil -f` идемпотентен).
- Удаление приложения сертификат не трогает — доверие остаётся для
  будущих версий.
- Примечание: первая загрузка самого `Setup.exe` может показать жёлтое
  предупреждение «неизвестное приложение» (у самоподписанного издателя нет
  репутации SmartScreen) → один раз «Подробнее → Выполнить в любом случае».
  Далее — чисто.
- Примечание: установка сертификата в доверенные корневые — известный
  вектор злоумышленников, поэтому корпоративный AV/EDR может запросить
  подтверждение. При развёртывании согласуйте это с IT.

### Вручную (одна машина)

1. Правый клик по `codesign.cer` → «Установить сертификат».
2. Мастер: «Локальный компьютер» → «Поместить все сертификаты в следующее
   хранилище» → «Доверенные корневые центры сертификации».
3. Повторить для «Доверенные издатели» (или после шага 2 сделать то же для
   Trusted Publishers).

### GPO (для IT, в домене)

Политика: Computer Configuration → Windows Settings →
Security Settings → Public Key Policies:

- **Trusted Root Certification Authorities** → Import → `codesign.cer`
- **Trusted Publishers** → Import → `codesign.cer`

После применения GPO обновится на машинах автоматически
(`gpupdate /force` для немедленного применения).

### Portable zip

`ParallelsSQLAdmin-windows-vX.Y.Z.zip` остаётся для портативного
использования (без установки). На такой машине для отсутствия
предупреждений сертификат нужно установить вручную (см. выше) или
воспользоваться Setup.exe.

## 4. Проверка

- Локально: правый клик по exe → Свойства → «Цифровые подписи» →
  издатель «<Название компании>», «Действительна».
- PowerShell: `Get-AuthenticodeSignature 'Parallels SQL Admin.exe'`
  → `Status: Valid`.
- В CI шаг `Sign executable (Windows)` завершается проверкой: exe
  подписывается `signtool sign` (SHA-256 + RFC 3161-timestamp,
  `http://timestamp.digicert.com`), затем подпись валидируется через
  .NET-цепочку (`X509Chain`) с вашим сертификатом как якорем доверия —
  без записи в системные хранилища раннера. При проблемах сборка падает.

## Файлы

- `codesign.cer` — публичная часть, для установки на ПК (хранится в корне
  репозитория).
- `codesign.pfx` — приватная часть, только в GitHub Secrets, в git не
  коммитить.