param(
    [string]$MetaEditorPath = "C:\Program Files\MetaTrader 5\MetaEditor64.exe",
    [string]$EvidenceRoot = ".ci-evidence\mql5-build"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $MetaEditorPath -PathType Leaf)) {
    throw "MetaEditor64.exe is missing: $MetaEditorPath"
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$resolvedEvidence = [IO.Path]::GetFullPath((Join-Path $repoRoot $EvidenceRoot))
New-Item -ItemType Directory -Force -Path $resolvedEvidence | Out-Null

$profiles = @(
    @{ Id = "GOLDI"; Source = "mt5\Experts\bot-ea\GoldEngine-GOLDi.mq5" },
    @{ Id = "GOLDM"; Source = "mt5\Experts\bot-ea\GoldEngine-GOLDm.mq5" }
)

foreach ($profile in $profiles) {
    $source = Join-Path $repoRoot $profile.Source
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "$($profile.Id) source is missing: $source"
    }
    $log = Join-Path $resolvedEvidence "$($profile.Id).compile.log"
    $process = Start-Process -FilePath $MetaEditorPath -ArgumentList @(
        "/compile:$source",
        "/log:$log"
    ) -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -notin @(0, 1)) {
        throw "$($profile.Id) MetaEditor exit code is $($process.ExitCode)"
    }
    if (-not (Test-Path -LiteralPath $log -PathType Leaf)) {
        throw "$($profile.Id) compile log is missing"
    }
    $result = Get-Content -LiteralPath $log -Raw
    if ($result -notmatch 'Result:\s+0 errors, 0 warnings') {
        throw "$($profile.Id) compile was not warning-clean: $log"
    }
    Write-Output "$($profile.Id)=PASS log=$log"
}

Write-Output "production_real_orders=DISABLED"
