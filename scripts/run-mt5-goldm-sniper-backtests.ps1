param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TerminalPath = "C:\Program Files\MetaTrader 5\terminal64.exe",
    [string]$MetaEditorPath = "C:\Program Files\MetaTrader 5\MetaEditor64.exe",
    [string]$TerminalDataPath = "",
    [string]$Symbol = "GOLD.i#",
    [int]$ExecutionDelayMs = 100,
    [int]$Model = 4,
    [string]$ExpertParameters = "GoldMSniperParity_GOLD_i.set",
    [string]$BacktestFrom = "2026.05.01",
    [string]$BacktestTo = "2026.08.01",
    [string]$BacktestName = "backtest_2026_may_jul",
    [string]$OosFrom = "2026.08.01",
    [string]$OosTo = "2026.08.12",
    [string]$OosName = "oos_2026_aug_01_11",
    [ValidateSet('Development', 'Validation', 'Diagnostic', 'BlindOos')]
    [string]$BacktestPurpose = 'Diagnostic',
    [ValidateSet('Development', 'Validation', 'Diagnostic', 'BlindOos')]
    [string]$OosPurpose = 'Diagnostic',
    [switch]$CloseRunningTerminal
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot 'goldm-research-guard.ps1')
Stop-GoldMLegacyTerminalResearch -Label 'run-mt5-goldm-sniper-backtests.ps1'

Assert-GoldMResearchRange -FromDate $BacktestFrom -ToDate $BacktestTo -Purpose $BacktestPurpose -Label $BacktestName
Assert-GoldMResearchRange -FromDate $OosFrom -ToDate $OosTo -Purpose $OosPurpose -Label $OosName

function Resolve-TerminalDataPath {
    param([string]$ExplicitPath)

    if ($ExplicitPath) {
        return (Resolve-Path -LiteralPath $ExplicitPath).Path
    }

    $root = Join-Path $env:APPDATA "MetaQuotes\Terminal"
    $candidate = Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
        Where-Object {
            (Test-Path -LiteralPath (Join-Path $_.FullName "origin.txt")) -and
            ((Get-Content -Raw -LiteralPath (Join-Path $_.FullName "origin.txt")) -like "*MetaTrader 5*")
        } |
        Select-Object -First 1
    if ($candidate) {
        return $candidate.FullName
    }
    throw "MetaTrader terminal data path was not found."
}

function New-TesterConfig {
    param(
        [string]$Path,
        [string]$ReportPath,
        [string]$FromDate,
        [string]$ToDate
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
Expert=bot-ea\GoldMSniperParity
ExpertParameters=$ExpertParameters
Symbol=$Symbol
Period=M15
Model=$Model
ExecutionMode=$ExecutionDelayMs
Optimization=0
FromDate=$FromDate
ToDate=$ToDate
ForwardMode=0
Deposit=100
Currency=USD
Leverage=1:1000
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
if (-not (Test-Path -LiteralPath $MetaEditorPath)) {
    throw "MetaEditor not found at $MetaEditorPath"
}

$dataPath = Resolve-TerminalDataPath -ExplicitPath $TerminalDataPath
$runningTerminals = Get-Process terminal64 -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $TerminalPath }
if ($runningTerminals -and -not $CloseRunningTerminal) {
    throw "MetaTrader is already running. Close it or pass -CloseRunningTerminal."
}
if ($runningTerminals) {
    foreach ($terminal in $runningTerminals) {
        Write-Output "closing_terminal_pid=$($terminal.Id)"
        $terminal.CloseMainWindow() | Out-Null
        if (-not $terminal.WaitForExit(15000)) {
            Stop-Process -Id $terminal.Id -Force
        }
    }
}

$sourceExpert = Join-Path $RepoRoot "mt5\Experts\bot-ea\GoldMSniperParity.mq5"
$sourceSet = Join-Path $RepoRoot "mt5\Profiles\Tester\$ExpertParameters"
$expertDir = Join-Path $dataPath "MQL5\Experts\bot-ea"
$profileDir = Join-Path $dataPath "MQL5\Profiles\Tester"
$runRoot = Join-Path $RepoRoot "data\backtests\goldm_sniper_signal_v1"
$configDir = Join-Path $runRoot "configs"
$reportDir = Join-Path $runRoot "reports"
$compileDir = Join-Path $runRoot "compile"
New-Item -ItemType Directory -Force -Path $expertDir, $profileDir, $configDir, $reportDir, $compileDir | Out-Null

$targetExpert = Join-Path $expertDir "GoldMSniperParity.mq5"
$targetSet = Join-Path $profileDir $ExpertParameters
Copy-Item -LiteralPath $sourceExpert -Destination $targetExpert -Force
Copy-Item -LiteralPath $sourceSet -Destination $targetSet -Force

$compileLog = Join-Path $compileDir "GoldMSniperParity.compile.log"
$compile = Start-Process -FilePath $MetaEditorPath -ArgumentList @(
    "/compile:$targetExpert",
    "/log:$compileLog"
) -Wait -PassThru -WindowStyle Hidden
$targetEx5 = [System.IO.Path]::ChangeExtension($targetExpert, ".ex5")
if (-not (Test-Path -LiteralPath $targetEx5)) {
    throw "Compile did not produce $targetEx5. See $compileLog"
}
$compileText = Get-Content -Raw -LiteralPath $compileLog
if ($compileText -notmatch "Result: 0 errors, 0 warnings") {
    throw "Compile was not clean. See $compileLog"
}
Write-Output "compiled=$targetEx5"
Write-Output "compile_log=$compileLog"
Write-Output "metaeditor_exit_code=$($compile.ExitCode)"

$tests = @(
    @{
        Name = $BacktestName
        From = $BacktestFrom
        To = $BacktestTo
    },
    @{
        Name = $OosName
        From = $OosFrom
        To = $OosTo
    }
)

foreach ($test in $tests) {
    $configPath = Join-Path $configDir "$($test.Name).ini"
    $reportPath = Join-Path $reportDir "$($test.Name).html"
    New-TesterConfig -Path $configPath -ReportPath $reportPath -FromDate $test.From -ToDate $test.To
    Write-Output "starting_test=$($test.Name)"
    Write-Output "config=$configPath"
    $process = Start-Process -FilePath $TerminalPath -ArgumentList "/config:$configPath" -Wait -PassThru -WindowStyle Hidden
    Write-Output "terminal_exit_code=$($process.ExitCode)"
    if (Test-Path -LiteralPath $reportPath) {
        Write-Output "completed_report=$reportPath"
    } else {
        Write-Output "missing_report=$reportPath"
    }
}

Write-Output "terminal_data_path=$dataPath"
