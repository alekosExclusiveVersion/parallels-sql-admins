param(
    [Parameter(Mandatory = $true)]
    [string]$Path
)

$ErrorActionPreference = 'Stop'

$file = [IO.Path]::GetFullPath($Path)

Write-Host "Sign step ($file): start"
if ([string]::IsNullOrEmpty($env:CERT_PFX_B64)) {
    Write-Host "CERT_PFX_B64 not set - $file stays unsigned"
    exit 0
}
if (-not (Test-Path $file)) {
    Write-Error "File not found: $file"
    exit 1
}

$pfx = Join-Path $env:RUNNER_TEMP 'codesign.pfx'
[IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:CERT_PFX_B64))
Write-Host "Sign step: pfx written ($((Get-Item $pfx).Length) bytes)"

$flags = [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::DefaultKeySet
$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(
    $pfx, $env:CERT_PFX_PASSWORD, $flags)
Write-Host "Sign step: cert loaded ($($cert.Subject))"

$kit = Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\bin' -Directory |
    Where-Object { $_.Name -match '^\d+\.' } |
    Sort-Object Name -Descending | Select-Object -First 1
$signtool = Join-Path $kit.FullName 'x64\signtool.exe'
if (-not (Test-Path $signtool)) {
    $signtool = Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\bin' -Recurse -Filter signtool.exe |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $signtool) {
    Write-Error 'signtool not found in Windows Kits'
    exit 1
}
Write-Host "Sign step: signtool = $signtool"

$sigArgs = @(
    'sign', '/f', $pfx, '/p', $env:CERT_PFX_PASSWORD,
    '/fd', 'SHA256', '/tr', 'http://timestamp.digicert.com',
    '/td', 'SHA256', '/v', $file
)
Write-Host 'Sign step: signing...'
& $signtool @sigArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Sign step: signed'

$sig = Get-AuthenticodeSignature $file
if ($null -eq $sig.SignerCertificate) {
    Write-Error "No signer: $($sig.Status) ($($sig.StatusMessage))"
    exit 1
}
if ($sig.Status -in @('HashMismatch', 'InvalidSignature', 'NotSupported')) {
    Write-Error "Signature status: $($sig.Status) ($($sig.StatusMessage))"
    exit 1
}
$chain = New-Object System.Security.Cryptography.X509Certificates.X509Chain
$chain.ChainPolicy.ExtraStore.Add($cert)
$chain.ChainPolicy.VerificationFlags = [System.Security.Cryptography.X509Certificates.X509VerificationFlags]::AllowUnknownCertificateAuthority
$chain.ChainPolicy.RevocationMode = [System.Security.Cryptography.X509Certificates.X509RevocationMode]::NoCheck
if (-not $chain.Build($sig.SignerCertificate)) {
    Write-Error ("Chain validation failed: " + (($chain.ChainStatus | ForEach-Object { $_.Status }) -join ', '))
    exit 1
}
Write-Host "Signed OK: $($sig.SignerCertificate.Subject)"