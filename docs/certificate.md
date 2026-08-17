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

Публичный сертификат `docs/cert/codesign.cer` нужно установить в два хранилища:

- **Доверенные корневые центры сертификации** (Trusted Root)
- **Доверенные издатели** (Trusted Publishers)

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

## 4. Проверка

- Локально: правый клик по exe → Свойства → «Цифровые подписи» →
  издатель «<Название компании>», «Действительна».
- PowerShell: `Get-AuthenticodeSignature 'Parallels SQL Admin.exe'`
  → `Status: Valid`.
- В CI шаг `Sign executable (Windows)` завершается проверкой:
  сертификат импортируется в Trusted Root + Trusted Publishers раннера
  (как на машинах пользователей), затем `signtool verify /pa` и
  `Get-AuthenticodeSignature` → `Status: Valid`. При проблемах сборка падает.

## Файлы

- `codesign.cer` — публичная часть, для установки на ПК (хранить в
  `docs/cert/`).
- `codesign.pfx` — приватная часть, только в GitHub Secrets, в git не
  коммитить.