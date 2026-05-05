param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TerminalPath = "C:\Program Files\MetaTrader 5\terminal64.exe",
    [string]$TerminalDataPath = "",
    [int]$ExecutionDelayMs = 100,
    [double]$Deposit = 100.0,
    [string]$Leverage = "1:1000",
    [switch]$SkipInstall,
    [switch]$CloseRunningTerminal
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

function New-TesterConfig {
    param(
        [string]$Path,
        [string]$ReportPath,
        [string]$FromDate,
        [string]$ToDate,
        [double]$DepositValue,
        [string]$LeverageValue,
        [int]$DelayMs
    )

    $content = @"
[Common]
NewsEnable=1

[Experts]
AllowLiveTrading=0
AllowDllImport=0
Enabled=1
Account=0
Profile=0

[Tester]
Expert=bot-ea\GoldMHighRiskMicroScalper
ExpertParameters=GoldMHighRiskMicroScalper_GOLDm.set
Symbol=GOLDm#
Period=M1
Model=4
ExecutionMode=$DelayMs
Optimization=0
FromDate=$FromDate
ToDate=$ToDate
ForwardMode=0
Deposit=$DepositValue
Currency=USD
Leverage=$LeverageValue
UseLocal=1
UseRemote=0
UseCloud=0
Visual=0
Report=$ReportPath
ReplaceReport=1
ShutdownTerminal=1
"@
    Set-Content -LiteralPath $Path -Value $content -Encoding ASCII
}

if (-not (Test-Path -LiteralPath $TerminalPath)) {
    throw "MetaTrader terminal not found at $TerminalPath"
}

$dataPath = Resolve-TerminalDataPath -ExplicitPath $TerminalDataPath

$runningTerminals = Get-Process terminal64 -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $TerminalPath }
if ($runningTerminals -and -not $CloseRunningTerminal) {
    throw "MetaTrader is already running from $TerminalPath. Close it or rerun with -CloseRunningTerminal so the command-line tester can consume the config."
}
if ($runningTerminals -and $CloseRunningTerminal) {
    foreach ($terminal in $runningTerminals) {
        Write-Output "closing_terminal_pid=$($terminal.Id)"
        $terminal.CloseMainWindow() | Out-Null
        if (-not $terminal.WaitForExit(15000)) {
            Stop-Process -Id $terminal.Id -Force
        }
    }
}

if (-not $SkipInstall) {
    & (Join-Path $PSScriptRoot "install-mt5-goldm-scalper.ps1") -RepoRoot $RepoRoot -TerminalDataPath $dataPath
}

$runRoot = Join-Path $RepoRoot "data\backtests\goldm_high_risk_scalper"
$configDir = Join-Path $runRoot "configs"
$reportDir = Join-Path $runRoot "reports"
New-Item -ItemType Directory -Force -Path $configDir, $reportDir | Out-Null

$tests = @(
    @{
        Name = "backtest_2026_q1"
        From = "2026.01.01"
        To = "2026.04.01"
        Report = (Join-Path $reportDir "backtest_2026_q1.html")
    },
    @{
        Name = "oos_2026_april"
        From = "2026.04.01"
        To = "2026.05.01"
        Report = (Join-Path $reportDir "oos_2026_april.html")
    }
)

foreach ($test in $tests) {
    $configPath = Join-Path $configDir "$($test.Name).ini"
    New-TesterConfig `
        -Path $configPath `
        -ReportPath $test.Report `
        -FromDate $test.From `
        -ToDate $test.To `
        -DepositValue $Deposit `
        -LeverageValue $Leverage `
        -DelayMs $ExecutionDelayMs

    Write-Output "starting_test=$($test.Name)"
    Write-Output "config=$configPath"
    Write-Output "report=$($test.Report)"

    $process = Start-Process -FilePath $TerminalPath -ArgumentList "/config:$configPath" -Wait -PassThru -WindowStyle Hidden
    Write-Output "terminal_exit_code=$($process.ExitCode)"

    if (Test-Path -LiteralPath $test.Report) {
        Write-Output "completed_report=$($test.Report)"
    } else {
        Write-Output "missing_report=$($test.Report)"
    }
}

Write-Output "terminal_data_path=$dataPath"
