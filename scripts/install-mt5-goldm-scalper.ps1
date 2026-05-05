param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TerminalDataPath = "",
    [string]$MetaEditorPath = "C:\Program Files\MetaTrader 5\MetaEditor64.exe",
    [switch]$SkipCompile
)

$ErrorActionPreference = "Stop"

function Resolve-TerminalDataPath {
    param([string]$ExplicitPath)

    if ($ExplicitPath) {
        return (Resolve-Path -LiteralPath $ExplicitPath).Path
    }

    $root = Join-Path $env:APPDATA "MetaQuotes\Terminal"
    $candidates = Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
        Where-Object {
            (Test-Path -LiteralPath (Join-Path $_.FullName "origin.txt")) -and
            (Test-Path -LiteralPath (Join-Path $_.FullName "MQL5\Experts"))
        }

    $matched = $candidates | Where-Object {
        $origin = Get-Content -LiteralPath (Join-Path $_.FullName "origin.txt") -ErrorAction SilentlyContinue
        $origin -like "*MetaTrader 5*"
    } | Select-Object -First 1

    if ($matched) {
        return $matched.FullName
    }

    $fallback = $candidates | Select-Object -First 1
    if ($fallback) {
        return $fallback.FullName
    }

    throw "MetaTrader terminal data path was not found. Pass -TerminalDataPath explicitly."
}

$dataPath = Resolve-TerminalDataPath -ExplicitPath $TerminalDataPath
$sourceEa = Join-Path $RepoRoot "mt5\Experts\bot-ea\GoldMHighRiskMicroScalper.mq5"
$sourceSet = Join-Path $RepoRoot "mt5\Profiles\Tester\GoldMHighRiskMicroScalper_GOLDm.set"

$expertDir = Join-Path $dataPath "MQL5\Experts\bot-ea"
$testerProfileDir = Join-Path $dataPath "MQL5\Profiles\Tester"
$presetDir = Join-Path $dataPath "MQL5\Presets"
$logDir = Join-Path $RepoRoot "data\backtests\goldm_high_risk_scalper\compile"

New-Item -ItemType Directory -Force -Path $expertDir, $testerProfileDir, $presetDir, $logDir | Out-Null

$targetEa = Join-Path $expertDir "GoldMHighRiskMicroScalper.mq5"
$targetTesterSet = Join-Path $testerProfileDir "GoldMHighRiskMicroScalper_GOLDm.set"
$targetPresetSet = Join-Path $presetDir "GoldMHighRiskMicroScalper_GOLDm.set"

Copy-Item -LiteralPath $sourceEa -Destination $targetEa -Force
Copy-Item -LiteralPath $sourceSet -Destination $targetTesterSet -Force
Copy-Item -LiteralPath $sourceSet -Destination $targetPresetSet -Force

if (-not $SkipCompile) {
    if (-not (Test-Path -LiteralPath $MetaEditorPath)) {
        throw "MetaEditor not found at $MetaEditorPath"
    }

    $compileLog = Join-Path $logDir "GoldMHighRiskMicroScalper.compile.log"
    $arguments = @(
        "/compile:$targetEa",
        "/log:$compileLog"
    )
    $process = Start-Process -FilePath $MetaEditorPath -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
    $targetEx5 = [System.IO.Path]::ChangeExtension($targetEa, ".ex5")

    if (-not (Test-Path -LiteralPath $targetEx5)) {
        throw "EA compile did not produce $targetEx5. See $compileLog"
    }

    Write-Output "compiled=$targetEx5"
    Write-Output "compile_log=$compileLog"
    Write-Output "metaeditor_exit_code=$($process.ExitCode)"
}

Write-Output "installed_source=$targetEa"
Write-Output "tester_set=$targetTesterSet"
Write-Output "preset_set=$targetPresetSet"
Write-Output "terminal_data_path=$dataPath"
