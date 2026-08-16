param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TerminalPath = "C:\Program Files\MetaTrader 5\terminal64.exe",
    [string]$TerminalDataPath = "",
    [double]$Deposit = 5.0,
    [string]$Leverage = "1:1000",
    [int]$ExecutionDelayMs = 100,
    [switch]$SkipInstall,
    [switch]$CloseRunningTerminal,
    [int]$TopToValidate = 4,
    [string]$ScreenFrom = "2026.03.01",
    [string]$ScreenTo = "2026.04.01",
    [string]$InSampleFrom = "2026.01.01",
    [string]$InSampleTo = "2026.04.01",
    [string]$OosFrom = "2026.04.01",
    [string]$OosTo = "2026.05.01",
    [string]$LatestFrom = "2026.05.01",
    [string]$LatestTo = "2026.05.06",
    [string]$OnlyVariantRegex = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot 'goldm-research-guard.ps1')

Assert-GoldMResearchRange -FromDate $ScreenFrom -ToDate $ScreenTo -Purpose Diagnostic -Label 'legacy tuning/screen'
Assert-GoldMResearchRange -FromDate $InSampleFrom -ToDate $InSampleTo -Purpose Diagnostic -Label 'legacy tuning/in-sample'
Assert-GoldMResearchRange -FromDate $OosFrom -ToDate $OosTo -Purpose Diagnostic -Label 'legacy tuning/oos'
Assert-GoldMResearchRange -FromDate $LatestFrom -ToDate $LatestTo -Purpose Diagnostic -Label 'legacy tuning/latest'

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
        [string]$SetFileName,
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
ExpertParameters=$SetFileName
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
ShutdownTerminal=1
"@
    Set-Content -LiteralPath $Path -Value $content -Encoding ASCII
}

function Get-SetValue {
    param(
        [string[]]$Lines,
        [string]$Name
    )

    foreach ($line in $Lines) {
        if ($line -match ("^" + [regex]::Escape($Name) + "=(.*)$")) {
            return $Matches[1]
        }
    }
    return $null
}

function Write-CandidateSet {
    param(
        [string[]]$BaselineLines,
        [hashtable]$Overrides,
        [string]$RepoSetPath,
        [string]$TerminalSetPath
    )

    $output = New-Object System.Collections.Generic.List[string]
    $seen = @{}
    foreach ($line in $BaselineLines) {
        if ($line -match '^([^=]+)=') {
            $name = $Matches[1]
            if ($Overrides.ContainsKey($name)) {
                $output.Add("$name=$($Overrides[$name])")
                $seen[$name] = $true
                continue
            }
            $seen[$name] = $true
        }
        $output.Add($line)
    }
    foreach ($name in ($Overrides.Keys | Sort-Object)) {
        if (-not $seen.ContainsKey($name)) {
            $output.Add("$name=$($Overrides[$name])")
        }
    }

    Set-Content -LiteralPath $RepoSetPath -Value $output -Encoding ASCII
    Copy-Item -LiteralPath $RepoSetPath -Destination $TerminalSetPath -Force
}

function Convert-DiagnosticLine {
    param([string]$Line)

    $values = @{}
    if (-not $Line) {
        return $values
    }

    foreach ($match in [regex]::Matches($Line, '([A-Za-z]+)=([0-9]+)')) {
        $values[$match.Groups[1].Value] = [int64]$match.Groups[2].Value
    }
    return $values
}

function Read-NewTesterLines {
    param(
        [string]$LogPath,
        [int]$StartLine
    )

    if (-not (Test-Path -LiteralPath $LogPath)) {
        return @()
    }

    $lines = Get-Content -LiteralPath $LogPath -ErrorAction SilentlyContinue
    if (-not $lines -or $StartLine -ge $lines.Count) {
        return @()
    }
    return $lines[$StartLine..($lines.Count - 1)]
}

function Invoke-Mt5Backtest {
    param(
        [string]$VariantName,
        [string]$SetFileName,
        [string]$Stage,
        [string]$FromDate,
        [string]$ToDate,
        [string]$ConfigPath,
        [string]$TesterLogPath
    )

    Assert-GoldMResearchRange -FromDate $FromDate -ToDate $ToDate -Purpose Diagnostic -Label "$Stage/$VariantName"

    $beforeLines = 0
    if (Test-Path -LiteralPath $TesterLogPath) {
        $beforeLines = (Get-Content -LiteralPath $TesterLogPath -ErrorAction SilentlyContinue).Count
    }

    New-TesterConfig `
        -Path $ConfigPath `
        -SetFileName $SetFileName `
        -FromDate $FromDate `
        -ToDate $ToDate `
        -DepositValue $Deposit `
        -LeverageValue $Leverage `
        -DelayMs $ExecutionDelayMs

    Write-Host "running stage=$Stage variant=$VariantName from=$FromDate to=$ToDate"
    $process = Start-Process -FilePath $TerminalPath -ArgumentList "/config:$ConfigPath" -Wait -PassThru -WindowStyle Hidden

    $newLines = Read-NewTesterLines -LogPath $TesterLogPath -StartLine $beforeLines
    $joined = $newLines -join "`n"

    $balanceMatches = [regex]::Matches($joined, 'final balance\s+([-0-9.]+)\s+USD')
    $testerMatches = [regex]::Matches($joined, 'OnTester result\s+([-0-9.]+)')
    $diagMatches = [regex]::Matches($joined, 'diagnostic summary[^\r\n]*')
    $passedMatches = [regex]::Matches($joined, 'Test passed in\s+([0-9:.]+)')

    $finalBalance = $null
    if ($balanceMatches.Count -gt 0) {
        $finalBalance = [double]$balanceMatches[$balanceMatches.Count - 1].Groups[1].Value
    }

    $onTester = $null
    if ($testerMatches.Count -gt 0) {
        $onTester = [double]$testerMatches[$testerMatches.Count - 1].Groups[1].Value
    }

    $diagLine = $null
    if ($diagMatches.Count -gt 0) {
        $diagLine = $diagMatches[$diagMatches.Count - 1].Value
    }
    $diag = Convert-DiagnosticLine -Line $diagLine

    $elapsed = ""
    if ($passedMatches.Count -gt 0) {
        $elapsed = $passedMatches[$passedMatches.Count - 1].Groups[1].Value
    }

    $openedBuy = if ($diag.ContainsKey("openedBuy")) { $diag["openedBuy"] } else { 0 }
    $openedSell = if ($diag.ContainsKey("openedSell")) { $diag["openedSell"] } else { 0 }
    $closed = if ($diag.ContainsKey("closed")) { $diag["closed"] } else { 0 }
    $canOpenOk = if ($diag.ContainsKey("canOpenOk")) { $diag["canOpenOk"] } else { 0 }
    $canOpenBlocked = if ($diag.ContainsKey("canOpenBlocked")) { $diag["canOpenBlocked"] } else { 0 }

    [pscustomobject]@{
        Stage = $Stage
        Variant = $VariantName
        From = $FromDate
        To = $ToDate
        Deposit = $Deposit
        FinalBalance = $finalBalance
        NetProfit = if ($null -ne $finalBalance) { [math]::Round($finalBalance - $Deposit, 2) } else { $null }
        OnTester = $onTester
        OpenedBuy = $openedBuy
        OpenedSell = $openedSell
        TotalOpened = $openedBuy + $openedSell
        ClosedByEa = $closed
        CanOpenOk = $canOpenOk
        CanOpenBlocked = $canOpenBlocked
        Elapsed = $elapsed
        TerminalExitCode = $process.ExitCode
    }
}

if (-not (Test-Path -LiteralPath $TerminalPath)) {
    throw "MetaTrader terminal not found at $TerminalPath"
}

$dataPath = Resolve-TerminalDataPath -ExplicitPath $TerminalDataPath
$testerProfileDir = Join-Path $dataPath "MQL5\Profiles\Tester"
$testerLogDir = Join-Path $dataPath "Tester\logs"
$testerLogPath = Join-Path $testerLogDir "$(Get-Date -Format yyyyMMdd).log"

$runningTerminals = Get-Process terminal64 -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $TerminalPath }
if ($runningTerminals -and -not $CloseRunningTerminal) {
    throw "MetaTrader is already running from $TerminalPath. Close it or rerun with -CloseRunningTerminal."
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

$baselineSetPath = Join-Path $RepoRoot "mt5\Profiles\Tester\GoldMHighRiskMicroScalper_GOLDm.set"
$baselineLines = Get-Content -LiteralPath $baselineSetPath

$runRoot = Join-Path $RepoRoot "data\backtests\goldm_high_risk_scalper\tuning"
$configDir = Join-Path $runRoot "configs"
$setDir = Join-Path $runRoot "sets"
$resultDir = Join-Path $runRoot "results"
New-Item -ItemType Directory -Force -Path $configDir, $setDir, $resultDir, $testerProfileDir, $testerLogDir | Out-Null

$candidates = @(
    @{
        Name = "baseline_micro"
        Overrides = @{}
    },
    @{
        Name = "md_aggressive_thresholds"
        Overrides = @{
            InpTrendThreshold = "60"
            InpRangeThreshold = "65"
            InpTrendAddThreshold = "65"
            InpRangeAddThreshold = "70"
            InpCooldownAfterEntrySeconds = "3"
            InpCooldownAfterCloseSeconds = "2"
        }
    },
    @{
        Name = "balanced_aggressive"
        Overrides = @{
            InpTrendThreshold = "65"
            InpRangeThreshold = "70"
            InpTrendAddThreshold = "70"
            InpRangeAddThreshold = "75"
            InpCooldownAfterEntrySeconds = "3"
            InpCooldownAfterCloseSeconds = "2"
        }
    },
    @{
        Name = "tight_spread_aggressive"
        Overrides = @{
            InpMaxSpread = "0.25"
            InpTrendThreshold = "60"
            InpRangeThreshold = "65"
            InpTrendAddThreshold = "65"
            InpRangeAddThreshold = "70"
            InpCooldownAfterEntrySeconds = "3"
            InpCooldownAfterCloseSeconds = "2"
        }
    },
    @{
        Name = "wide_spread_aggressive"
        Overrides = @{
            InpMaxSpread = "0.35"
            InpTrendThreshold = "60"
            InpRangeThreshold = "65"
            InpTrendAddThreshold = "65"
            InpRangeAddThreshold = "70"
            InpCooldownAfterEntrySeconds = "3"
            InpCooldownAfterCloseSeconds = "2"
        }
    },
    @{
        Name = "fast_exit_aggressive"
        Overrides = @{
            InpTrendThreshold = "60"
            InpRangeThreshold = "65"
            InpTrendAddThreshold = "65"
            InpRangeAddThreshold = "70"
            InpMaxHoldSeconds = "60"
            InpLockStartMin = "0.08"
            InpTrailBackMin = "0.03"
            InpCooldownAfterEntrySeconds = "3"
            InpCooldownAfterCloseSeconds = "2"
        }
    },
    @{
        Name = "looser_trail_aggressive"
        Overrides = @{
            InpTrendThreshold = "60"
            InpRangeThreshold = "65"
            InpTrendAddThreshold = "65"
            InpRangeAddThreshold = "70"
            InpTrailBackMin = "0.05"
            InpTrailBackMax = "0.10"
            InpCooldownAfterEntrySeconds = "3"
            InpCooldownAfterCloseSeconds = "2"
        }
    },
    @{
        Name = "risk_gate_aggressive"
        Overrides = @{
            InpTrendThreshold = "60"
            InpRangeThreshold = "65"
            InpTrendAddThreshold = "65"
            InpRangeAddThreshold = "70"
            InpCooldownAfterEntrySeconds = "3"
            InpCooldownAfterCloseSeconds = "2"
            InpMaxDailyLossPercent = "90.0"
            InpMaxEquityDrawdownStop = "90.0"
            InpMaxBasketFloatingLossPercent = "90.0"
        }
    },
    @{
        Name = "dense_entries_aggressive"
        Overrides = @{
            InpTrendThreshold = "60"
            InpRangeThreshold = "65"
            InpTrendAddThreshold = "65"
            InpRangeAddThreshold = "70"
            InpCooldownAfterEntrySeconds = "1"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.15"
        }
    },
    @{
        Name = "maxpos5_aggressive"
        Overrides = @{
            InpTrendThreshold = "60"
            InpRangeThreshold = "65"
            InpTrendAddThreshold = "65"
            InpRangeAddThreshold = "70"
            InpMaxPositions = "5"
            InpCooldownAfterEntrySeconds = "2"
            InpCooldownAfterCloseSeconds = "1"
        }
    },
    @{
        Name = "fast_lock_aggressive"
        Overrides = @{
            InpTrendThreshold = "60"
            InpRangeThreshold = "65"
            InpTrendAddThreshold = "65"
            InpRangeAddThreshold = "70"
            InpLockStartMin = "0.06"
            InpLockStartMax = "0.16"
            InpTrailBackMin = "0.02"
            InpTrailBackMax = "0.06"
            InpMaxHoldSeconds = "60"
            InpCooldownAfterEntrySeconds = "2"
            InpCooldownAfterCloseSeconds = "1"
        }
    },
    @{
        Name = "survival_to_margin"
        Overrides = @{
            InpTrendThreshold = "65"
            InpRangeThreshold = "70"
            InpTrendAddThreshold = "70"
            InpRangeAddThreshold = "75"
            InpMaxDailyLossPercent = "95.0"
            InpMaxEquityDrawdownStop = "95.0"
            InpMaxBasketFloatingLossPercent = "95.0"
            InpMaxConsecutiveLoss = "999"
            InpPauseAfterLossMinutes = "0"
        }
    },
    @{
        Name = "di_confirmed_dense"
        Overrides = @{
            InpUseDIDirectionFilter = "true"
            InpMinDIDifference = "0.0"
            InpTrendThreshold = "60"
            InpRangeThreshold = "65"
            InpTrendAddThreshold = "65"
            InpRangeAddThreshold = "70"
            InpCooldownAfterEntrySeconds = "1"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.15"
        }
    },
    @{
        Name = "di_adx_rising_dense"
        Overrides = @{
            InpUseDIDirectionFilter = "true"
            InpMinDIDifference = "0.0"
            InpUseAdxRisingFilter = "true"
            InpTrendThreshold = "60"
            InpRangeThreshold = "65"
            InpTrendAddThreshold = "65"
            InpRangeAddThreshold = "70"
            InpCooldownAfterEntrySeconds = "1"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.15"
        }
    },
    @{
        Name = "spread_atr_loose_dense"
        Overrides = @{
            InpUseSpreadAtrGate = "true"
            InpMaxSpreadATRMult = "0.25"
            InpMinAtrSpreadRatio = "4.0"
            InpTrendThreshold = "60"
            InpRangeThreshold = "65"
            InpTrendAddThreshold = "65"
            InpRangeAddThreshold = "70"
            InpCooldownAfterEntrySeconds = "1"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.15"
        }
    },
    @{
        Name = "cost_lock_mild_dense"
        Overrides = @{
            InpUseCostAwareProfitLock = "true"
            InpLockStartSpreadMult = "0.70"
            InpTrailBackSpreadMult = "0.30"
            InpTrendThreshold = "60"
            InpRangeThreshold = "65"
            InpTrendAddThreshold = "65"
            InpRangeAddThreshold = "70"
            InpCooldownAfterEntrySeconds = "1"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.15"
        }
    },
    @{
        Name = "reverse_debounce_dense"
        Overrides = @{
            InpReverseCloseMinSeconds = "10"
            InpReverseCloseOppositeScore = "75"
            InpWeakSignalCloseScore = "35"
            InpTrendThreshold = "60"
            InpRangeThreshold = "65"
            InpTrendAddThreshold = "65"
            InpRangeAddThreshold = "70"
            InpCooldownAfterEntrySeconds = "1"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.15"
        }
    },
    @{
        Name = "range_active_dense"
        Overrides = @{
            InpRangeADXOn = "20.0"
            InpBandProximityATRMult = "0.20"
            InpRangeThreshold = "55"
            InpRangeAddThreshold = "60"
            InpTrendThreshold = "60"
            InpTrendAddThreshold = "65"
            InpCooldownAfterEntrySeconds = "1"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.15"
        }
    },
    @{
        Name = "combined_v2_dense"
        Overrides = @{
            InpUseDIDirectionFilter = "true"
            InpMinDIDifference = "0.0"
            InpUseSpreadAtrGate = "true"
            InpMaxSpreadATRMult = "0.25"
            InpMinAtrSpreadRatio = "4.0"
            InpUseCostAwareProfitLock = "true"
            InpLockStartSpreadMult = "0.70"
            InpTrailBackSpreadMult = "0.30"
            InpReverseCloseMinSeconds = "10"
            InpReverseCloseOppositeScore = "75"
            InpWeakSignalCloseScore = "35"
            InpBandProximityATRMult = "0.15"
            InpTrendThreshold = "60"
            InpRangeThreshold = "60"
            InpTrendAddThreshold = "65"
            InpRangeAddThreshold = "65"
            InpCooldownAfterEntrySeconds = "1"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.15"
        }
    },
    @{
        Name = "pullback_dense"
        Overrides = @{
            InpTrendEntryMode = "1"
            InpTrendPullbackATRMult = "0.15"
            InpTrendThreshold = "60"
            InpRangeThreshold = "65"
            InpTrendAddThreshold = "65"
            InpRangeAddThreshold = "70"
            InpCooldownAfterEntrySeconds = "1"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.15"
        }
    },
    @{
        Name = "break_or_pullback_dense"
        Overrides = @{
            InpTrendEntryMode = "2"
            InpTrendPullbackATRMult = "0.15"
            InpTrendThreshold = "65"
            InpRangeThreshold = "65"
            InpTrendAddThreshold = "70"
            InpRangeAddThreshold = "70"
            InpCooldownAfterEntrySeconds = "1"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.15"
        }
    },
    @{
        Name = "tight_sl_dense"
        Overrides = @{
            InpEmergencySLMin = "0.30"
            InpEmergencySLMax = "0.80"
            InpEmergencySLATRMult = "0.80"
            InpMaxHoldSeconds = "45"
            InpTrendThreshold = "60"
            InpRangeThreshold = "65"
            InpTrendAddThreshold = "65"
            InpRangeAddThreshold = "70"
            InpCooldownAfterEntrySeconds = "1"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.15"
        }
    },
    @{
        Name = "pullback_tight_sl"
        Overrides = @{
            InpTrendEntryMode = "1"
            InpTrendPullbackATRMult = "0.15"
            InpEmergencySLMin = "0.30"
            InpEmergencySLMax = "0.80"
            InpEmergencySLATRMult = "0.80"
            InpMaxHoldSeconds = "45"
            InpTrendThreshold = "60"
            InpRangeThreshold = "65"
            InpTrendAddThreshold = "65"
            InpRangeAddThreshold = "70"
            InpCooldownAfterEntrySeconds = "1"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.15"
        }
    },
    @{
        Name = "rsi_relaxed_range"
        Overrides = @{
            InpRSIOversold = "40.0"
            InpRSIOverbought = "60.0"
            InpRangeADXOn = "20.0"
            InpBandProximityATRMult = "0.20"
            InpRangeThreshold = "55"
            InpRangeAddThreshold = "60"
            InpTrendThreshold = "60"
            InpTrendAddThreshold = "65"
            InpCooldownAfterEntrySeconds = "1"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.15"
        }
    },
    @{
        Name = "goldrush_momo_session"
        Overrides = @{
            InpSignalModel = "1"
            InpRSIPeriod = "14"
            InpTrendMATimeframe = "1"
            InpTrendMAFast = "50"
            InpTrendMASlow = "200"
            InpRSIMomentumBuy = "52.0"
            InpRSIMomentumSell = "48.0"
            InpUseSessionFilter = "true"
            InpSession1StartHour = "7"
            InpSession1EndHour = "11"
            InpSession2StartHour = "13"
            InpSession2EndHour = "17"
            InpUseAtrTakeProfit = "true"
            InpTakeProfitMin = "0.12"
            InpTakeProfitMax = "0.55"
            InpTakeProfitATRMult = "1.20"
            InpEmergencySLMin = "0.10"
            InpEmergencySLMax = "0.45"
            InpEmergencySLATRMult = "0.90"
            InpUseClosedBarBreakout = "true"
            InpMicroStructureBars = "8"
            InpTrendThreshold = "70"
            InpTrendAddThreshold = "75"
            InpMaxSpread = "0.25"
            InpCooldownAfterEntrySeconds = "3"
            InpCooldownAfterCloseSeconds = "2"
            InpMaxHoldSeconds = "180"
            InpReverseCloseMinSeconds = "20"
        }
    },
    @{
        Name = "goldrush_momo_allhours"
        Overrides = @{
            InpSignalModel = "1"
            InpRSIPeriod = "14"
            InpTrendMATimeframe = "1"
            InpTrendMAFast = "50"
            InpTrendMASlow = "200"
            InpRSIMomentumBuy = "52.0"
            InpRSIMomentumSell = "48.0"
            InpUseSessionFilter = "false"
            InpUseAtrTakeProfit = "true"
            InpTakeProfitMin = "0.12"
            InpTakeProfitMax = "0.55"
            InpTakeProfitATRMult = "1.20"
            InpEmergencySLMin = "0.10"
            InpEmergencySLMax = "0.45"
            InpEmergencySLATRMult = "0.90"
            InpUseClosedBarBreakout = "true"
            InpMicroStructureBars = "8"
            InpTrendThreshold = "70"
            InpTrendAddThreshold = "75"
            InpMaxSpread = "0.25"
            InpCooldownAfterEntrySeconds = "3"
            InpCooldownAfterCloseSeconds = "2"
            InpMaxHoldSeconds = "180"
            InpReverseCloseMinSeconds = "20"
        }
    },
    @{
        Name = "momo_fast_ema_session"
        Overrides = @{
            InpSignalModel = "1"
            InpRSIPeriod = "14"
            InpTrendMATimeframe = "1"
            InpTrendMAFast = "20"
            InpTrendMASlow = "50"
            InpRSIMomentumBuy = "51.0"
            InpRSIMomentumSell = "49.0"
            InpUseSessionFilter = "true"
            InpSession1StartHour = "7"
            InpSession1EndHour = "11"
            InpSession2StartHour = "13"
            InpSession2EndHour = "17"
            InpUseAtrTakeProfit = "true"
            InpTakeProfitMin = "0.10"
            InpTakeProfitMax = "0.40"
            InpTakeProfitATRMult = "0.90"
            InpEmergencySLMin = "0.10"
            InpEmergencySLMax = "0.35"
            InpEmergencySLATRMult = "0.70"
            InpTrendThreshold = "65"
            InpTrendAddThreshold = "70"
            InpMaxSpread = "0.25"
            InpCooldownAfterEntrySeconds = "2"
            InpCooldownAfterCloseSeconds = "1"
            InpMaxHoldSeconds = "120"
            InpReverseCloseMinSeconds = "15"
        }
    },
    @{
        Name = "mined_rsi14_revert_h10"
        Overrides = @{
            InpSignalModel = "2"
            InpMinedRuleMode = "0"
            InpRSIPeriod = "14"
            InpRSIOversold = "30.0"
            InpBollingerPeriod = "20"
            InpBollingerDeviation = "2.0"
            InpTrendThreshold = "95"
            InpTrendAddThreshold = "100"
            InpRangeThreshold = "100"
            InpRangeAddThreshold = "100"
            InpMaxSpread = "0.25"
            InpUseSpreadAtrGate = "true"
            InpMaxSpreadATRMult = "0.25"
            InpMinAtrSpreadRatio = "4.0"
            InpUseAtrTakeProfit = "true"
            InpTakeProfitMin = "0.10"
            InpTakeProfitMax = "0.40"
            InpTakeProfitATRMult = "0.70"
            InpEmergencySLMin = "0.20"
            InpEmergencySLMax = "0.70"
            InpEmergencySLATRMult = "0.80"
            InpMaxHoldSeconds = "600"
            InpReverseCloseMinSeconds = "600"
            InpReverseCloseOppositeScore = "101"
            InpWeakSignalCloseScore = "101"
            InpCooldownAfterEntrySeconds = "3"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.10"
        }
    },
    @{
        Name = "mined_rsi14_revert_h20"
        Overrides = @{
            InpSignalModel = "2"
            InpMinedRuleMode = "0"
            InpRSIPeriod = "14"
            InpRSIOversold = "30.0"
            InpBollingerPeriod = "20"
            InpBollingerDeviation = "2.0"
            InpTrendThreshold = "95"
            InpTrendAddThreshold = "100"
            InpRangeThreshold = "100"
            InpRangeAddThreshold = "100"
            InpMaxSpread = "0.25"
            InpUseSpreadAtrGate = "true"
            InpMaxSpreadATRMult = "0.25"
            InpMinAtrSpreadRatio = "4.0"
            InpUseAtrTakeProfit = "true"
            InpTakeProfitMin = "0.15"
            InpTakeProfitMax = "0.70"
            InpTakeProfitATRMult = "1.10"
            InpEmergencySLMin = "0.30"
            InpEmergencySLMax = "0.90"
            InpEmergencySLATRMult = "1.00"
            InpMaxHoldSeconds = "1200"
            InpReverseCloseMinSeconds = "1200"
            InpReverseCloseOppositeScore = "101"
            InpWeakSignalCloseScore = "101"
            InpCooldownAfterEntrySeconds = "3"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.10"
        }
    },
    @{
        Name = "mined_core_ema9_20_h10"
        Overrides = @{
            InpSignalModel = "2"
            InpMinedRuleMode = "1"
            InpEMAFast = "9"
            InpEMASlow = "20"
            InpRSIPeriod = "14"
            InpRSIMomentumBuy = "52.0"
            InpUseSessionFilter = "true"
            InpSession1StartHour = "7"
            InpSession1EndHour = "11"
            InpSession2StartHour = "13"
            InpSession2EndHour = "17"
            InpTrendThreshold = "95"
            InpTrendAddThreshold = "100"
            InpRangeThreshold = "100"
            InpRangeAddThreshold = "100"
            InpMaxSpread = "0.25"
            InpUseSpreadAtrGate = "true"
            InpMaxSpreadATRMult = "0.20"
            InpMinAtrSpreadRatio = "5.0"
            InpUseAtrTakeProfit = "true"
            InpTakeProfitMin = "0.12"
            InpTakeProfitMax = "0.45"
            InpTakeProfitATRMult = "0.80"
            InpEmergencySLMin = "0.20"
            InpEmergencySLMax = "0.70"
            InpEmergencySLATRMult = "0.80"
            InpMaxHoldSeconds = "600"
            InpReverseCloseMinSeconds = "600"
            InpReverseCloseOppositeScore = "101"
            InpWeakSignalCloseScore = "101"
            InpCooldownAfterEntrySeconds = "2"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.10"
        }
    },
    @{
        Name = "mined_core_ema9_20_h20"
        Overrides = @{
            InpSignalModel = "2"
            InpMinedRuleMode = "1"
            InpEMAFast = "9"
            InpEMASlow = "20"
            InpRSIPeriod = "14"
            InpRSIMomentumBuy = "52.0"
            InpUseSessionFilter = "true"
            InpSession1StartHour = "7"
            InpSession1EndHour = "11"
            InpSession2StartHour = "13"
            InpSession2EndHour = "17"
            InpTrendThreshold = "95"
            InpTrendAddThreshold = "100"
            InpRangeThreshold = "100"
            InpRangeAddThreshold = "100"
            InpMaxSpread = "0.25"
            InpUseSpreadAtrGate = "true"
            InpMaxSpreadATRMult = "0.20"
            InpMinAtrSpreadRatio = "5.0"
            InpUseAtrTakeProfit = "true"
            InpTakeProfitMin = "0.20"
            InpTakeProfitMax = "0.80"
            InpTakeProfitATRMult = "1.20"
            InpEmergencySLMin = "0.30"
            InpEmergencySLMax = "0.90"
            InpEmergencySLATRMult = "1.00"
            InpMaxHoldSeconds = "1200"
            InpReverseCloseMinSeconds = "1200"
            InpReverseCloseOppositeScore = "101"
            InpWeakSignalCloseScore = "101"
            InpCooldownAfterEntrySeconds = "2"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.10"
        }
    },
    @{
        Name = "mined_raw9up_h10"
        Overrides = @{
            InpSignalModel = "2"
            InpMinedRuleMode = "2"
            InpTrendThreshold = "95"
            InpTrendAddThreshold = "100"
            InpRangeThreshold = "100"
            InpRangeAddThreshold = "100"
            InpMaxSpread = "0.25"
            InpUseSpreadAtrGate = "true"
            InpMaxSpreadATRMult = "0.25"
            InpMinAtrSpreadRatio = "4.0"
            InpUseAtrTakeProfit = "true"
            InpTakeProfitMin = "0.10"
            InpTakeProfitMax = "0.40"
            InpTakeProfitATRMult = "0.70"
            InpEmergencySLMin = "0.20"
            InpEmergencySLMax = "0.70"
            InpEmergencySLATRMult = "0.80"
            InpMaxHoldSeconds = "600"
            InpReverseCloseMinSeconds = "600"
            InpReverseCloseOppositeScore = "101"
            InpWeakSignalCloseScore = "101"
            InpCooldownAfterEntrySeconds = "2"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.10"
        }
    },
    @{
        Name = "mined_rsi14_revert_h10_lockonly"
        Overrides = @{
            InpSignalModel = "2"
            InpMinedRuleMode = "0"
            InpRSIPeriod = "14"
            InpRSIOversold = "30.0"
            InpBollingerPeriod = "20"
            InpBollingerDeviation = "2.0"
            InpTrendThreshold = "95"
            InpTrendAddThreshold = "100"
            InpRangeThreshold = "100"
            InpRangeAddThreshold = "100"
            InpMaxSpread = "0.25"
            InpUseSpreadAtrGate = "true"
            InpMaxSpreadATRMult = "0.25"
            InpMinAtrSpreadRatio = "4.0"
            InpUseAtrTakeProfit = "false"
            InpUseDynamicProfitLock = "true"
            InpLockStartMin = "0.08"
            InpLockStartMax = "0.30"
            InpLockStartATRMult = "0.15"
            InpTrailBackMin = "0.03"
            InpTrailBackMax = "0.10"
            InpTrailBackATRMult = "0.06"
            InpEmergencySLMin = "0.30"
            InpEmergencySLMax = "0.90"
            InpEmergencySLATRMult = "1.00"
            InpMaxHoldSeconds = "600"
            InpReverseCloseMinSeconds = "600"
            InpReverseCloseOppositeScore = "101"
            InpWeakSignalCloseScore = "101"
            InpCooldownAfterEntrySeconds = "3"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.10"
        }
    },
    @{
        Name = "mined_core_ema9_20_h10_lockonly"
        Overrides = @{
            InpSignalModel = "2"
            InpMinedRuleMode = "1"
            InpEMAFast = "9"
            InpEMASlow = "20"
            InpRSIPeriod = "14"
            InpRSIMomentumBuy = "52.0"
            InpUseSessionFilter = "true"
            InpSession1StartHour = "7"
            InpSession1EndHour = "11"
            InpSession2StartHour = "13"
            InpSession2EndHour = "17"
            InpTrendThreshold = "95"
            InpTrendAddThreshold = "100"
            InpRangeThreshold = "100"
            InpRangeAddThreshold = "100"
            InpMaxSpread = "0.25"
            InpUseSpreadAtrGate = "true"
            InpMaxSpreadATRMult = "0.20"
            InpMinAtrSpreadRatio = "5.0"
            InpUseAtrTakeProfit = "false"
            InpUseDynamicProfitLock = "true"
            InpLockStartMin = "0.08"
            InpLockStartMax = "0.30"
            InpLockStartATRMult = "0.15"
            InpTrailBackMin = "0.03"
            InpTrailBackMax = "0.10"
            InpTrailBackATRMult = "0.06"
            InpEmergencySLMin = "0.30"
            InpEmergencySLMax = "0.90"
            InpEmergencySLATRMult = "1.00"
            InpMaxHoldSeconds = "600"
            InpReverseCloseMinSeconds = "600"
            InpReverseCloseOppositeScore = "101"
            InpWeakSignalCloseScore = "101"
            InpCooldownAfterEntrySeconds = "2"
            InpCooldownAfterCloseSeconds = "1"
            InpMinDistanceBetweenEntryMin = "0.05"
            InpMinDistanceBetweenEntryATRMult = "0.10"
        }
    },
    @{
        Name = "mined_seq7up_h20_runner"
        Overrides = @{
            InpSignalModel = "2"
            InpMinedRuleMode = "3"
            InpMinedRawSequence = "UUUUUUU"
            InpTrendThreshold = "95"
            InpTrendAddThreshold = "100"
            InpRangeThreshold = "100"
            InpRangeAddThreshold = "100"
            InpMaxPositions = "1"
            InpAllowAveraging = "false"
            InpMaxTotalOpenLot = "0.10"
            InpMaxSpread = "0.25"
            InpUseSpreadAtrGate = "true"
            InpMaxSpreadATRMult = "0.25"
            InpMinAtrSpreadRatio = "4.0"
            InpUseAtrTakeProfit = "false"
            InpUseDynamicProfitLock = "true"
            InpLockStartMin = "2.00"
            InpLockStartMax = "8.00"
            InpLockStartATRMult = "0.60"
            InpTrailBackMin = "0.80"
            InpTrailBackMax = "3.00"
            InpTrailBackATRMult = "0.25"
            InpEmergencySLMin = "3.00"
            InpEmergencySLMax = "10.00"
            InpEmergencySLATRMult = "1.40"
            InpMaxHoldSeconds = "1200"
            InpReverseCloseMinSeconds = "1200"
            InpReverseCloseOppositeScore = "101"
            InpWeakSignalCloseScore = "101"
            InpCooldownAfterEntrySeconds = "10"
            InpCooldownAfterCloseSeconds = "3"
            InpMinDistanceBetweenEntryMin = "0.50"
            InpMinDistanceBetweenEntryATRMult = "0.25"
        }
    },
    @{
        Name = "mined_seq7up_h20_runner_stack"
        Overrides = @{
            InpSignalModel = "2"
            InpMinedRuleMode = "3"
            InpMinedRawSequence = "UUUUUUU"
            InpTrendThreshold = "95"
            InpTrendAddThreshold = "100"
            InpRangeThreshold = "100"
            InpRangeAddThreshold = "100"
            InpMaxPositions = "3"
            InpAllowAveraging = "true"
            InpMaxTotalOpenLot = "0.30"
            InpMaxSpread = "0.25"
            InpUseSpreadAtrGate = "true"
            InpMaxSpreadATRMult = "0.25"
            InpMinAtrSpreadRatio = "4.0"
            InpUseAtrTakeProfit = "false"
            InpUseDynamicProfitLock = "true"
            InpLockStartMin = "2.00"
            InpLockStartMax = "8.00"
            InpLockStartATRMult = "0.60"
            InpTrailBackMin = "0.80"
            InpTrailBackMax = "3.00"
            InpTrailBackATRMult = "0.25"
            InpEmergencySLMin = "3.00"
            InpEmergencySLMax = "10.00"
            InpEmergencySLATRMult = "1.40"
            InpMaxHoldSeconds = "1200"
            InpReverseCloseMinSeconds = "1200"
            InpReverseCloseOppositeScore = "101"
            InpWeakSignalCloseScore = "101"
            InpCooldownAfterEntrySeconds = "5"
            InpCooldownAfterCloseSeconds = "2"
            InpMinDistanceBetweenEntryMin = "0.80"
            InpMinDistanceBetweenEntryATRMult = "0.30"
        }
    },
    @{
        Name = "mined_alt8_long_h20_runner"
        Overrides = @{
            InpSignalModel = "2"
            InpMinedRuleMode = "3"
            InpMinedRawSequence = "UDUDUDUD"
            InpTrendThreshold = "95"
            InpTrendAddThreshold = "100"
            InpRangeThreshold = "100"
            InpRangeAddThreshold = "100"
            InpMaxPositions = "1"
            InpAllowAveraging = "false"
            InpMaxTotalOpenLot = "0.10"
            InpMaxSpread = "0.25"
            InpUseSpreadAtrGate = "true"
            InpMaxSpreadATRMult = "0.25"
            InpMinAtrSpreadRatio = "4.0"
            InpUseAtrTakeProfit = "false"
            InpUseDynamicProfitLock = "true"
            InpLockStartMin = "1.50"
            InpLockStartMax = "6.00"
            InpLockStartATRMult = "0.45"
            InpTrailBackMin = "0.70"
            InpTrailBackMax = "2.50"
            InpTrailBackATRMult = "0.22"
            InpEmergencySLMin = "3.00"
            InpEmergencySLMax = "9.00"
            InpEmergencySLATRMult = "1.30"
            InpMaxHoldSeconds = "1200"
            InpReverseCloseMinSeconds = "1200"
            InpReverseCloseOppositeScore = "101"
            InpWeakSignalCloseScore = "101"
            InpCooldownAfterEntrySeconds = "10"
            InpCooldownAfterCloseSeconds = "3"
            InpMinDistanceBetweenEntryMin = "0.50"
            InpMinDistanceBetweenEntryATRMult = "0.25"
        }
    },
    @{
        Name = "adaptive_alt8_rsi50_wide_runner"
        Overrides = @{
            InpSignalModel = "2"
            InpMinedRuleMode = "3"
            InpMinedRawSequence = "UDUDUDUD"
            InpRSIPeriod = "14"
            InpUseMinedRSIFilter = "true"
            InpMinedMinRSI = "50.0"
            InpMinedMaxRSI = "100.0"
            InpUseMinedHourMask = "false"
            InpTrendThreshold = "95"
            InpTrendAddThreshold = "100"
            InpRangeThreshold = "100"
            InpRangeAddThreshold = "100"
            InpMaxPositions = "1"
            InpAllowAveraging = "false"
            InpMaxTotalOpenLot = "2.0"
            InpMaxSpread = "0.25"
            InpUseSpreadAtrGate = "true"
            InpMaxSpreadATRMult = "0.25"
            InpMinAtrSpreadRatio = "4.0"
            InpUseAtrTakeProfit = "false"
            InpUseDynamicProfitLock = "true"
            InpLockStartMin = "3.00"
            InpLockStartMax = "8.00"
            InpLockStartATRMult = "0.60"
            InpTrailBackMin = "1.20"
            InpTrailBackMax = "3.50"
            InpTrailBackATRMult = "0.30"
            InpEmergencySLMin = "5.00"
            InpEmergencySLMax = "12.00"
            InpEmergencySLATRMult = "1.80"
            InpMaxHoldSeconds = "1200"
            InpReverseCloseMinSeconds = "1200"
            InpReverseCloseOppositeScore = "101"
            InpWeakSignalCloseScore = "101"
            InpCooldownAfterEntrySeconds = "10"
            InpCooldownAfterCloseSeconds = "3"
            InpMinDistanceBetweenEntryMin = "0.50"
            InpMinDistanceBetweenEntryATRMult = "0.25"
            InpUseAdaptiveTradePause = "true"
            InpAdaptiveLossStreak = "3"
            InpAdaptivePauseMinutes = "30"
        }
    },
    @{
        Name = "mined_alt8_short_h20_runner"
        Overrides = @{
            InpSignalModel = "2"
            InpMinedRuleMode = "4"
            InpMinedRawSequence = "UDUDUUUD"
            InpTrendThreshold = "95"
            InpTrendAddThreshold = "100"
            InpRangeThreshold = "100"
            InpRangeAddThreshold = "100"
            InpMaxPositions = "1"
            InpAllowAveraging = "false"
            InpMaxTotalOpenLot = "0.10"
            InpMaxSpread = "0.25"
            InpUseSpreadAtrGate = "true"
            InpMaxSpreadATRMult = "0.25"
            InpMinAtrSpreadRatio = "4.0"
            InpUseAtrTakeProfit = "false"
            InpUseDynamicProfitLock = "true"
            InpLockStartMin = "1.50"
            InpLockStartMax = "6.00"
            InpLockStartATRMult = "0.45"
            InpTrailBackMin = "0.70"
            InpTrailBackMax = "2.50"
            InpTrailBackATRMult = "0.22"
            InpEmergencySLMin = "3.00"
            InpEmergencySLMax = "9.00"
            InpEmergencySLATRMult = "1.30"
            InpMaxHoldSeconds = "1200"
            InpReverseCloseMinSeconds = "1200"
            InpReverseCloseOppositeScore = "101"
            InpWeakSignalCloseScore = "101"
            InpCooldownAfterEntrySeconds = "10"
            InpCooldownAfterCloseSeconds = "3"
            InpMinDistanceBetweenEntryMin = "0.50"
            InpMinDistanceBetweenEntryATRMult = "0.25"
        }
    },
    @{
        Name = "mined_core_ema_h20_runner_wide"
        Overrides = @{
            InpSignalModel = "2"
            InpMinedRuleMode = "1"
            InpEMAFast = "9"
            InpEMASlow = "20"
            InpRSIPeriod = "14"
            InpRSIMomentumBuy = "52.0"
            InpUseSessionFilter = "true"
            InpSession1StartHour = "7"
            InpSession1EndHour = "11"
            InpSession2StartHour = "13"
            InpSession2EndHour = "17"
            InpTrendThreshold = "95"
            InpTrendAddThreshold = "100"
            InpRangeThreshold = "100"
            InpRangeAddThreshold = "100"
            InpMaxPositions = "1"
            InpAllowAveraging = "false"
            InpMaxTotalOpenLot = "0.10"
            InpMaxSpread = "0.25"
            InpUseSpreadAtrGate = "true"
            InpMaxSpreadATRMult = "0.20"
            InpMinAtrSpreadRatio = "5.0"
            InpUseAtrTakeProfit = "false"
            InpUseDynamicProfitLock = "true"
            InpLockStartMin = "2.00"
            InpLockStartMax = "8.00"
            InpLockStartATRMult = "0.60"
            InpTrailBackMin = "0.80"
            InpTrailBackMax = "3.00"
            InpTrailBackATRMult = "0.25"
            InpEmergencySLMin = "3.00"
            InpEmergencySLMax = "10.00"
            InpEmergencySLATRMult = "1.40"
            InpMaxHoldSeconds = "1200"
            InpReverseCloseMinSeconds = "1200"
            InpReverseCloseOppositeScore = "101"
            InpWeakSignalCloseScore = "101"
            InpCooldownAfterEntrySeconds = "10"
            InpCooldownAfterCloseSeconds = "3"
            InpMinDistanceBetweenEntryMin = "0.50"
            InpMinDistanceBetweenEntryATRMult = "0.25"
        }
    }
)

if ($OnlyVariantRegex) {
    $candidates = @($candidates | Where-Object { $_.Name -match $OnlyVariantRegex })
    if ($candidates.Count -eq 0) {
        throw "No tuning candidates matched regex '$OnlyVariantRegex'."
    }
}

$allResults = New-Object System.Collections.Generic.List[object]

foreach ($candidate in $candidates) {
    $setFileName = "GoldMHighRiskMicroScalper_GOLDm_tune_$($candidate.Name).set"
    $repoSetPath = Join-Path $setDir $setFileName
    $terminalSetPath = Join-Path $testerProfileDir $setFileName
    Write-CandidateSet `
        -BaselineLines $baselineLines `
        -Overrides $candidate.Overrides `
        -RepoSetPath $repoSetPath `
        -TerminalSetPath $terminalSetPath

    $configPath = Join-Path $configDir "$($candidate.Name)_screen.ini"
    $result = Invoke-Mt5Backtest `
        -VariantName $candidate.Name `
        -SetFileName $setFileName `
        -Stage "screen" `
        -FromDate $ScreenFrom `
        -ToDate $ScreenTo `
        -ConfigPath $configPath `
        -TesterLogPath $testerLogPath
    $allResults.Add($result)
}

$screenCsv = Join-Path $resultDir "screen_results.csv"
$allResults | Export-Csv -LiteralPath $screenCsv -NoTypeInformation -Encoding UTF8

$top = $allResults |
    Where-Object { $null -ne $_.FinalBalance -and $_.TotalOpened -gt 0 } |
    Sort-Object @{ Expression = "FinalBalance"; Descending = $true }, @{ Expression = "OnTester"; Descending = $true } |
    Select-Object -First $TopToValidate

foreach ($row in $top) {
    $candidate = $candidates | Where-Object { $_.Name -eq $row.Variant } | Select-Object -First 1
    $setFileName = "GoldMHighRiskMicroScalper_GOLDm_tune_$($candidate.Name).set"

    $isConfigPath = Join-Path $configDir "$($candidate.Name)_insample.ini"
    $isResult = Invoke-Mt5Backtest `
        -VariantName $candidate.Name `
        -SetFileName $setFileName `
        -Stage "insample" `
        -FromDate $InSampleFrom `
        -ToDate $InSampleTo `
        -ConfigPath $isConfigPath `
        -TesterLogPath $testerLogPath
    $allResults.Add($isResult)

    $oosConfigPath = Join-Path $configDir "$($candidate.Name)_oos.ini"
    $oosResult = Invoke-Mt5Backtest `
        -VariantName $candidate.Name `
        -SetFileName $setFileName `
        -Stage "oos" `
        -FromDate $OosFrom `
        -ToDate $OosTo `
        -ConfigPath $oosConfigPath `
        -TesterLogPath $testerLogPath
    $allResults.Add($oosResult)

    $latestConfigPath = Join-Path $configDir "$($candidate.Name)_latest.ini"
    $latestResult = Invoke-Mt5Backtest `
        -VariantName $candidate.Name `
        -SetFileName $setFileName `
        -Stage "latest" `
        -FromDate $LatestFrom `
        -ToDate $LatestTo `
        -ConfigPath $latestConfigPath `
        -TesterLogPath $testerLogPath
    $allResults.Add($latestResult)
}

$allCsv = Join-Path $resultDir "all_results.csv"
$allResults | Export-Csv -LiteralPath $allCsv -NoTypeInformation -Encoding UTF8

$summaryPath = Join-Path $resultDir "summary.md"
$summary = New-Object System.Collections.Generic.List[string]
$summary.Add("# GoldM High-Risk Micro Scalper Tuning")
$summary.Add("")
$summary.Add("Deposit: $Deposit USD")
$summary.Add("Leverage: $Leverage")
$summary.Add("Model: Every tick based on real ticks")
$summary.Add("Execution delay: $ExecutionDelayMs ms")
$summary.Add("Screen: $ScreenFrom to $ScreenTo")
$summary.Add("In-sample: $InSampleFrom to $InSampleTo")
$summary.Add("OOS: $OosFrom to $OosTo")
$summary.Add("Latest: $LatestFrom to $LatestTo")
$summary.Add("")
$summary.Add("## Screen Results")
$summary.Add("")
$summary.Add("| Variant | Final Balance | Net | Trades | OnTester |")
$summary.Add("|---|---:|---:|---:|---:|")
foreach ($row in ($allResults | Where-Object Stage -eq "screen" | Sort-Object FinalBalance -Descending)) {
    $summary.Add("| $($row.Variant) | $($row.FinalBalance) | $($row.NetProfit) | $($row.TotalOpened) | $($row.OnTester) |")
}
$summary.Add("")
$summary.Add("## Validation Results")
$summary.Add("")
$summary.Add("| Stage | Variant | Final Balance | Net | Trades | OnTester |")
$summary.Add("|---|---|---:|---:|---:|---:|")
foreach ($row in ($allResults | Where-Object { $_.Stage -ne "screen" } | Sort-Object Variant, Stage)) {
    $summary.Add("| $($row.Stage) | $($row.Variant) | $($row.FinalBalance) | $($row.NetProfit) | $($row.TotalOpened) | $($row.OnTester) |")
}
$summary | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Output "screen_results=$screenCsv"
Write-Output "all_results=$allCsv"
Write-Output "summary=$summaryPath"
Write-Output "terminal_data_path=$dataPath"
