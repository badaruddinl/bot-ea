param(
    [Parameter(Mandatory = $true)]
    [string]$ExecutablePath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
    throw "Autologon executable is missing"
}
$signature = Get-AuthenticodeSignature -LiteralPath $ExecutablePath
if ($signature.Status -ne 'Valid') {
    throw "Autologon Authenticode signature is not valid: $($signature.Status)"
}
if ($null -eq $signature.SignerCertificate -or
    $signature.SignerCertificate.Subject -notmatch '(^|,)\s*CN=Microsoft Corporation(,|$)') {
    throw "Autologon signer is not Microsoft Corporation"
}
$item = Get-Item -LiteralPath $ExecutablePath
if ($item.VersionInfo.ProductName -notmatch 'Autologon') {
    throw "Executable product name is not Autologon"
}

[ordered]@{
    schema_version = 1
    status = "VALID"
    path = $item.FullName
    sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    signer_subject = $signature.SignerCertificate.Subject
    product_name = $item.VersionInfo.ProductName
    file_version = $item.VersionInfo.FileVersion
    production_real_orders = "DISABLED"
} | ConvertTo-Json -Compress
