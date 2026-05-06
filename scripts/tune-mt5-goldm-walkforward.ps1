param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TerminalPath = "C:\Program Files\MetaTrader 5\terminal64.exe",
    [string]$TerminalDataPath = "C:\Users\badaruddinl\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075",
    [double]$Deposit = 5.0,
    [string]$Leverage = "1:1000",
    [int]$ExecutionDelayMs = 100,
    [int]$TopToValidate = 4,
    [int]$TopToOos = 2,
    [int]$MinScreenTrades = 15,
    [int]$MinTotalScreenTrades = 50,
    [int]$MinValidationTrades = 10,
    [int]$MinTotalValidationTrades = 40,
    [double]$MinScreenProfitFactor = 1.05,
    [double]$MinValidationProfitFactor = 1.05,
    [string]$ResultName = "walkforward_5usd_tuning",
    [string]$OnlyVariantRegex = "",
    [switch]$SkipInstall,
    [switch]$CloseRunningTerminal,
    [switch]$ForceRerun
)

$ErrorActionPreference = "Stop"

function New-TesterConfig {
    param(
        [string]$Path,
        [string]$SetFileName,
        [string]$Period,
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
Expert=bot-ea\GoldMHighRiskMicroScalper
ExpertParameters=$SetFileName
Symbol=GOLDm#
Period=$Period
Model=4
ExecutionMode=$ExecutionDelayMs
Optimization=0
FromDate=$FromDate
ToDate=$ToDate
ForwardMode=0
Deposit=$Deposit
Currency=USD
Leverage=$Leverage
UseLocal=1
UseRemote=0
UseCloud=0
Visual=0
ShutdownTerminal=1
"@
    Set-Content -LiteralPath $Path -Value $content -Encoding ASCII
}

function Read-NewLines {
    param([string]$Path, [int]$StartLine)
    if(-not (Test-Path -LiteralPath $Path)) {
        return @()
    }
    $lines = Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue
    if(-not $lines -or $StartLine -ge $lines.Count) {
        return @()
    }
    return $lines[$StartLine..($lines.Count - 1)]
}

function Get-RegexLast {
    param([string]$Text, [string]$Pattern, [int]$Group = 1)
    $matches = [regex]::Matches($Text, $Pattern)
    if($matches.Count -eq 0) {
        return ""
    }
    return $matches[$matches.Count - 1].Groups[$Group].Value
}

function Get-DiagnosticValue {
    param([string]$Line, [string]$Name)
    $match = [regex]::Match($Line, "$Name=([0-9]+)")
    if($match.Success) {
        return [int64]$match.Groups[1].Value
    }
    return 0
}

function Get-PerformanceValue {
    param([string]$Line, [string]$Name)
    $match = [regex]::Match($Line, "$Name=([-0-9.]+)")
    if($match.Success) {
        return [double]$match.Groups[1].Value
    }
    return $null
}

function Merge-Overrides {
    param(
        [hashtable]$Base,
        [hashtable]$Specific
    )

    $merged = @{}
    foreach($key in $Base.Keys) {
        $merged[$key] = $Base[$key]
    }
    foreach($key in $Specific.Keys) {
        $merged[$key] = $Specific[$key]
    }
    return $merged
}

function Test-CompletedResultRow {
    param([object]$Row)

    return (
        $Row.TerminalExitCode -eq "0" -and
        $null -ne $Row.FinalBalance -and
        "$($Row.FinalBalance)" -ne "" -and
        $null -ne $Row.OnTester -and
        "$($Row.OnTester)" -ne "" -and
        $null -ne $Row.TotalOpened -and
        "$($Row.TotalOpened)" -ne "" -and
        $null -ne $Row.ClosedByEa -and
        "$($Row.ClosedByEa)" -ne "" -and
        "$($Row.DataNotes)" -notmatch "no history data"
    )
}

function Get-DoubleValue {
    param([object]$Value, [double]$Default = 0.0)
    if($null -eq $Value -or "$Value" -eq "") {
        return $Default
    }
    return [double]$Value
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
    foreach($line in $BaselineLines) {
        if($line -match '^([^=]+)=') {
            $name = $Matches[1]
            if($Overrides.ContainsKey($name)) {
                $output.Add("$name=$($Overrides[$name])")
                $seen[$name] = $true
                continue
            }
            $seen[$name] = $true
        }
        $output.Add($line)
    }
    foreach($name in ($Overrides.Keys | Sort-Object)) {
        if(-not $seen.ContainsKey($name)) {
            $output.Add("$name=$($Overrides[$name])")
        }
    }

    Set-Content -LiteralPath $RepoSetPath -Value $output -Encoding ASCII
    Copy-Item -LiteralPath $RepoSetPath -Destination $TerminalSetPath -Force
}

function Invoke-Mt5Backtest {
    param(
        [string]$Stage,
        [string]$Sample,
        [object]$Candidate,
        [string]$FromDate,
        [string]$ToDate
    )

    $key = "$Stage|$Sample|$($Candidate.Name)|$($Candidate.SetHash)"
    if($completed.ContainsKey($key)) {
        return $null
    }

    $beforeLines = 0
    if(Test-Path -LiteralPath $testerLogPath) {
        $beforeLines = (Get-Content -LiteralPath $testerLogPath -ErrorAction SilentlyContinue).Count
    }

    $configPath = Join-Path $configDir "$Stage`_$Sample`_$($Candidate.Name).ini"
    New-TesterConfig -Path $configPath -SetFileName $Candidate.SetFileName -Period $Candidate.Period -FromDate $FromDate -ToDate $ToDate

    $startedAt = Get-Date
    "running stage=$Stage sample=$Sample variant=$($Candidate.Name) period=$($Candidate.Period) from=$FromDate to=$ToDate" |
        Set-Content -LiteralPath $progressPath -Encoding ASCII
    Write-Host "running stage=$Stage sample=$Sample variant=$($Candidate.Name) period=$($Candidate.Period) from=$FromDate to=$ToDate"

    $process = Start-Process -FilePath $TerminalPath -ArgumentList "/config:$configPath" -Wait -PassThru -WindowStyle Hidden

    $newLines = Read-NewLines -Path $testerLogPath -StartLine $beforeLines
    $joined = $newLines -join "`n"
    $diagLine = Get-RegexLast -Text $joined -Pattern "diagnostic summary[^\r\n]*" -Group 0
    $perfLine = Get-RegexLast -Text $joined -Pattern "performance summary[^\r\n]*" -Group 0
    $finalBalance = Get-RegexLast -Text $joined -Pattern "final balance\s+([-0-9.]+)\s+USD"
    $onTester = Get-RegexLast -Text $joined -Pattern "OnTester result\s+([-0-9.]+)"
    $elapsed = Get-RegexLast -Text $joined -Pattern "Test passed in\s+([0-9:.]+)"
    $dataNotes = ([regex]::Matches($joined, "history data begins from[^\r\n]*|history ticks synchronized from[^\r\n]*|real ticks begin from[^\r\n]*|no history data[^\r\n]*|not enough money[^\r\n]*") |
        ForEach-Object { $_.Value } |
        Select-Object -Unique) -join " | "

    $final = if($finalBalance -ne "") { [double]$finalBalance } else { $null }
    $openedBuy = Get-DiagnosticValue -Line $diagLine -Name "openedBuy"
    $openedSell = Get-DiagnosticValue -Line $diagLine -Name "openedSell"
    $totalOpened = $openedBuy + $openedSell
    $closed = Get-DiagnosticValue -Line $diagLine -Name "closed"
    $pf = Get-PerformanceValue -Line $perfLine -Name "profitFactor"
    $winRate = Get-PerformanceValue -Line $perfLine -Name "winRate"
    $avgWin = Get-PerformanceValue -Line $perfLine -Name "averageWin"
    $avgLoss = Get-PerformanceValue -Line $perfLine -Name "averageLoss"
    $maxLossStreak = Get-PerformanceValue -Line $perfLine -Name "maxConsecutiveLosses"

    $result = [pscustomobject]@{
        Stage = $Stage
        Sample = $Sample
        Variant = $Candidate.Name
        SetHash = $Candidate.SetHash
        Period = $Candidate.Period
        From = $FromDate
        To = $ToDate
        Deposit = $Deposit
        FinalBalance = $final
        NetProfit = if($null -ne $final) { [math]::Round($final - $Deposit, 2) } else { $null }
        OnTester = if($onTester -ne "") { [double]$onTester } else { $null }
        ProfitFactor = $pf
        WinRate = $winRate
        AverageWin = $avgWin
        AverageLoss = $avgLoss
        MaxConsecutiveLosses = $maxLossStreak
        OpenedBuy = $openedBuy
        OpenedSell = $openedSell
        TotalOpened = $totalOpened
        ClosedByEa = $closed
        TerminalExitCode = $process.ExitCode
        Elapsed = $elapsed
        StartedAt = $startedAt.ToString("s")
        FinishedAt = (Get-Date).ToString("s")
        DataNotes = $dataNotes
    }

    if(Test-Path -LiteralPath $csvPath) {
        $result | Export-Csv -LiteralPath $csvPath -NoTypeInformation -Append
    } else {
        $result | Export-Csv -LiteralPath $csvPath -NoTypeInformation
    }
    if(Test-CompletedResultRow -Row $result) {
        $completed[$key] = $true
    }

    if($totalOpened -eq 0) {
        "no_orders stage=$Stage sample=$Sample variant=$($Candidate.Name); moving on" |
            Set-Content -LiteralPath $progressPath -Encoding ASCII
    } else {
        "finished stage=$Stage sample=$Sample variant=$($Candidate.Name) final=$finalBalance trades=$totalOpened pf=$pf" |
            Set-Content -LiteralPath $progressPath -Encoding ASCII
    }

    return $result
}

if(-not (Test-Path -LiteralPath $TerminalPath)) {
    throw "MetaTrader terminal not found at $TerminalPath"
}

$runningTerminals = Get-Process terminal64 -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $TerminalPath }
if($runningTerminals -and -not $CloseRunningTerminal) {
    throw "MetaTrader is already running from $TerminalPath. Close it or rerun with -CloseRunningTerminal."
}
if($runningTerminals -and $CloseRunningTerminal) {
    foreach($terminal in $runningTerminals) {
        $terminal.CloseMainWindow() | Out-Null
        if(-not $terminal.WaitForExit(15000)) {
            Stop-Process -Id $terminal.Id -Force
        }
    }
}

if(-not $SkipInstall) {
    & (Join-Path $PSScriptRoot "install-mt5-goldm-scalper.ps1") -RepoRoot $RepoRoot -TerminalDataPath $TerminalDataPath | Out-Host
}

$testerProfileDir = Join-Path $TerminalDataPath "MQL5\Profiles\Tester"
$testerLogDir = Join-Path $TerminalDataPath "Tester\logs"
$testerLogPath = Join-Path $testerLogDir "$(Get-Date -Format yyyyMMdd).log"
$runRoot = Join-Path $RepoRoot "data\backtests\goldm_high_risk_scalper\$ResultName"
$configDir = Join-Path $runRoot "configs"
$setDir = Join-Path $runRoot "sets"
$resultDir = Join-Path $runRoot "results"
New-Item -ItemType Directory -Force -Path $testerProfileDir, $testerLogDir, $configDir, $setDir, $resultDir | Out-Null
$csvPath = Join-Path $resultDir "walkforward_results.csv"
$summaryPath = Join-Path $resultDir "summary.md"
$progressPath = Join-Path $resultDir "progress.txt"

if($ForceRerun -and (Test-Path -LiteralPath $csvPath)) {
    Remove-Item -LiteralPath $csvPath -Force
}
if(Test-Path -LiteralPath $csvPath) {
    $header = Get-Content -LiteralPath $csvPath -TotalCount 1
    if($header -notmatch '(^|,)"?SetHash"?(,|$)') {
        $legacyCsvPath = Join-Path $resultDir ("walkforward_results_legacy_{0}.csv" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
        Move-Item -LiteralPath $csvPath -Destination $legacyCsvPath -Force
    }
}

$baselineSetPath = Join-Path $RepoRoot "mt5\Profiles\Tester\GoldMHighRiskMicroScalper_GOLDm.set"
$baselineLines = Get-Content -LiteralPath $baselineSetPath

$commonMinedOverrides = @{
    InpSignalModel = "2"
    InpMinedRuleMode = "3"
    InpMinedRawSequence = "UDUDUDUD"
    InpRSIPeriod = "14"
    InpUseMinedRSIFilter = "true"
    InpMinedMinRSI = "50.0"
    InpMinedMaxRSI = "100.0"
    InpUseMinedHourMask = "false"
    InpMinedAllowedHours = ""
    InpMinedMinATR = "0.0"
    InpMinedMaxATR = "0.0"
    InpUseSpreadAtrGate = "true"
    InpMaxSpreadATRMult = "0.25"
    InpMinAtrSpreadRatio = "4.0"
    InpMaxPositions = "1"
    InpAllowAveraging = "false"
    InpMaxTotalOpenLot = "2.0"
}

$candidates = @(
    @{
        Name = "m1_active_adaptive"
        Period = "M1"
        Overrides = @{
            InpTimeframeEntry = "1"
            InpConfirmTimeframe = "5"
            InpTrendMATimeframe = "1"
        }
    },
    @{
        Name = "m1_trail_loose_sl6"
        Period = "M1"
        Overrides = @{
            InpTimeframeEntry = "1"
            InpConfirmTimeframe = "5"
            InpTrendMATimeframe = "1"
            InpTrailBackMin = "1.60"
            InpTrailBackMax = "4.50"
            InpTrailBackATRMult = "0.38"
            InpEmergencySLMin = "6.00"
            InpEmergencySLMax = "14.00"
            InpEmergencySLATRMult = "2.00"
            InpMaxHoldSeconds = "1500"
        }
    },
    @{
        Name = "m1_later_lock4_sl7"
        Period = "M1"
        Overrides = @{
            InpTimeframeEntry = "1"
            InpConfirmTimeframe = "5"
            InpTrendMATimeframe = "1"
            InpLockStartMin = "4.00"
            InpLockStartMax = "10.00"
            InpLockStartATRMult = "0.80"
            InpTrailBackMin = "2.00"
            InpTrailBackMax = "6.00"
            InpTrailBackATRMult = "0.45"
            InpEmergencySLMin = "7.00"
            InpEmergencySLMax = "18.00"
            InpEmergencySLATRMult = "2.40"
            InpMaxHoldSeconds = "1800"
        }
    },
    @{
        Name = "m1_later_lock4_sl6_mid"
        Period = "M1"
        Overrides = @{
            InpTimeframeEntry = "1"
            InpConfirmTimeframe = "5"
            InpTrendMATimeframe = "1"
            InpLockStartMin = "4.00"
            InpLockStartMax = "10.00"
            InpLockStartATRMult = "0.80"
            InpTrailBackMin = "2.00"
            InpTrailBackMax = "6.00"
            InpTrailBackATRMult = "0.45"
            InpEmergencySLMin = "6.00"
            InpEmergencySLMax = "14.00"
            InpEmergencySLATRMult = "2.00"
            InpMaxHoldSeconds = "1800"
        }
    },
    @{
        Name = "m1_later_lock4_sl5p5_h1500"
        Period = "M1"
        Overrides = @{
            InpTimeframeEntry = "1"
            InpConfirmTimeframe = "5"
            InpTrendMATimeframe = "1"
            InpLockStartMin = "4.00"
            InpLockStartMax = "10.00"
            InpLockStartATRMult = "0.80"
            InpTrailBackMin = "2.00"
            InpTrailBackMax = "6.00"
            InpTrailBackATRMult = "0.45"
            InpEmergencySLMin = "5.50"
            InpEmergencySLMax = "12.00"
            InpEmergencySLATRMult = "1.80"
            InpMaxHoldSeconds = "1500"
        }
    },
    @{
        Name = "m1_later_lock3p5_sl6"
        Period = "M1"
        Overrides = @{
            InpTimeframeEntry = "1"
            InpConfirmTimeframe = "5"
            InpTrendMATimeframe = "1"
            InpLockStartMin = "3.50"
            InpLockStartMax = "9.00"
            InpLockStartATRMult = "0.70"
            InpTrailBackMin = "1.80"
            InpTrailBackMax = "5.50"
            InpTrailBackATRMult = "0.42"
            InpEmergencySLMin = "6.00"
            InpEmergencySLMax = "14.00"
            InpEmergencySLATRMult = "2.00"
            InpMaxHoldSeconds = "1500"
        }
    },
    @{
        Name = "m5_uudddudd_short_h4"
        Period = "M5"
        Overrides = @{
            InpTimeframeEntry = "5"
            InpConfirmTimeframe = "15"
            InpTrendMATimeframe = "5"
            InpMinedRuleMode = "4"
            InpMinedRawSequence = "UUDDDUDD"
            InpUseMinedRSIFilter = "true"
            InpMinedMinRSI = "50.0"
            InpMinedMaxRSI = "100.0"
            InpLockStartMin = "2.50"
            InpLockStartMax = "8.00"
            InpLockStartATRMult = "0.55"
            InpTrailBackMin = "1.30"
            InpTrailBackMax = "4.50"
            InpTrailBackATRMult = "0.28"
            InpEmergencySLMin = "8.00"
            InpEmergencySLMax = "18.00"
            InpEmergencySLATRMult = "1.60"
            InpMaxHoldSeconds = "1500"
            InpCooldownAfterEntrySeconds = "60"
            InpCooldownAfterCloseSeconds = "15"
        }
    },
    @{
        Name = "m5_udud_rsi50_runner"
        Period = "M5"
        Overrides = @{
            InpTimeframeEntry = "5"
            InpConfirmTimeframe = "15"
            InpTrendMATimeframe = "5"
            InpMinedRuleMode = "3"
            InpMinedRawSequence = "UDUD"
            InpRSIPeriod = "14"
            InpUseMinedRSIFilter = "true"
            InpMinedMinRSI = "50.0"
            InpMinedMaxRSI = "100.0"
            InpLockStartMin = "6.00"
            InpLockStartMax = "16.00"
            InpLockStartATRMult = "0.70"
            InpTrailBackMin = "2.50"
            InpTrailBackMax = "9.00"
            InpTrailBackATRMult = "0.35"
            InpEmergencySLMin = "10.00"
            InpEmergencySLMax = "28.00"
            InpEmergencySLATRMult = "1.80"
            InpMaxHoldSeconds = "5400"
            InpCooldownAfterEntrySeconds = "60"
            InpCooldownAfterCloseSeconds = "15"
        }
    },
    @{
        Name = "m5_ududud_rsi50_runner"
        Period = "M5"
        Overrides = @{
            InpTimeframeEntry = "5"
            InpConfirmTimeframe = "15"
            InpTrendMATimeframe = "5"
            InpMinedRuleMode = "3"
            InpMinedRawSequence = "UDUDUD"
            InpRSIPeriod = "14"
            InpUseMinedRSIFilter = "true"
            InpMinedMinRSI = "50.0"
            InpMinedMaxRSI = "100.0"
            InpLockStartMin = "7.00"
            InpLockStartMax = "18.00"
            InpLockStartATRMult = "0.75"
            InpTrailBackMin = "3.00"
            InpTrailBackMax = "10.00"
            InpTrailBackATRMult = "0.40"
            InpEmergencySLMin = "12.00"
            InpEmergencySLMax = "32.00"
            InpEmergencySLATRMult = "2.00"
            InpMaxHoldSeconds = "7200"
            InpCooldownAfterEntrySeconds = "60"
            InpCooldownAfterCloseSeconds = "15"
        }
    },
    @{
        Name = "m15_udu_swing_guard"
        Period = "M15"
        Overrides = @{
            InpTimeframeEntry = "15"
            InpConfirmTimeframe = "30"
            InpTrendMATimeframe = "15"
            InpMinedRuleMode = "3"
            InpMinedRawSequence = "UDU"
            InpRSIPeriod = "14"
            InpUseMinedRSIFilter = "true"
            InpMinedMinRSI = "50.0"
            InpMinedMaxRSI = "100.0"
            InpLockStartMin = "12.00"
            InpLockStartMax = "35.00"
            InpLockStartATRMult = "0.80"
            InpTrailBackMin = "5.00"
            InpTrailBackMax = "18.00"
            InpTrailBackATRMult = "0.45"
            InpEmergencySLMin = "20.00"
            InpEmergencySLMax = "60.00"
            InpEmergencySLATRMult = "2.00"
            InpMaxHoldSeconds = "14400"
            InpCooldownAfterEntrySeconds = "180"
            InpCooldownAfterCloseSeconds = "60"
        }
    }
)

if($OnlyVariantRegex) {
    $candidates = $candidates | Where-Object { $_.Name -match $OnlyVariantRegex }
}

foreach($candidate in $candidates) {
    $setFileName = "GoldMHighRiskMicroScalper_GOLDm_wf_$($candidate.Name).set"
    $repoSetPath = Join-Path $setDir $setFileName
    $terminalSetPath = Join-Path $testerProfileDir $setFileName
    $candidate["Overrides"] = Merge-Overrides -Base $commonMinedOverrides -Specific $candidate.Overrides
    Write-CandidateSet -BaselineLines $baselineLines -Overrides $candidate.Overrides -RepoSetPath $repoSetPath -TerminalSetPath $terminalSetPath
    $candidate["SetFileName"] = $setFileName
    $candidate["SetHash"] = (Get-FileHash -Algorithm SHA256 -LiteralPath $repoSetPath).Hash.Substring(0, 12)
}

$completed = @{}
if(Test-Path -LiteralPath $csvPath) {
    $candidateHashes = @{}
    foreach($candidate in $candidates) {
        $candidateHashes[$candidate.Name] = $candidate.SetHash
    }
    Import-Csv -LiteralPath $csvPath | ForEach-Object {
        if(
            (Test-CompletedResultRow -Row $_) -and
            $candidateHashes.ContainsKey($_.Variant) -and
            $_.SetHash -eq $candidateHashes[$_.Variant]
        ) {
            $completed["$($_.Stage)|$($_.Sample)|$($_.Variant)|$($_.SetHash)"] = $true
        }
    }
}

$screenWindows = @(
    @{ Sample = "s2025_01"; From = "2025.01.01"; To = "2025.02.01" },
    @{ Sample = "s2025_03"; From = "2025.03.01"; To = "2025.04.01" },
    @{ Sample = "s2025_08"; From = "2025.08.01"; To = "2025.09.01" }
)
$validationWindows = @(
    @{ Sample = "v2025_02"; From = "2025.02.01"; To = "2025.03.01" },
    @{ Sample = "v2025_04"; From = "2025.04.01"; To = "2025.05.01" },
    @{ Sample = "v2025_09"; From = "2025.09.01"; To = "2025.10.01" }
)
$oosWindows = @(
    @{ Sample = "oos2025_11"; From = "2025.11.01"; To = "2025.12.01" },
    @{ Sample = "oos2026_q1"; From = "2026.01.01"; To = "2026.04.01" },
    @{ Sample = "oos2026_apr"; From = "2026.04.01"; To = "2026.05.06" }
)

function Get-StageRank {
    param(
        [object[]]$Rows,
        [string]$Stage,
        [object[]]$Candidates,
        [object[]]$Windows,
        [int]$MinTradesPerWindow,
        [int]$MinTotalTrades,
        [double]$MinProfitFactor,
        [int]$Top
    )

    $rankRows = New-Object System.Collections.Generic.List[object]
    foreach($candidate in $Candidates) {
        $candidateRows = @($Rows | Where-Object {
            $_.Stage -eq $Stage -and
            $_.Variant -eq $candidate.Name -and
            $_.SetHash -eq $candidate.SetHash -and
            (Test-CompletedResultRow -Row $_)
        })

        $selectedRows = @()
        $allWindowsPassed = $true
        foreach($window in $Windows) {
            $sampleRows = @($candidateRows | Where-Object { $_.Sample -eq $window.Sample })
            if($sampleRows.Count -eq 0) {
                $allWindowsPassed = $false
                break
            }

            $row = $sampleRows[$sampleRows.Count - 1]
            if((Get-DoubleValue -Value $row.TotalOpened) -lt $MinTradesPerWindow) {
                $allWindowsPassed = $false
            }
            $selectedRows += $row
        }

        if(-not $allWindowsPassed) {
            continue
        }

        $net = ($selectedRows | ForEach-Object { Get-DoubleValue -Value $_.NetProfit } | Measure-Object -Sum).Sum
        $trades = ($selectedRows | ForEach-Object { Get-DoubleValue -Value $_.TotalOpened } | Measure-Object -Sum).Sum
        $pf = ($selectedRows | ForEach-Object { Get-DoubleValue -Value $_.ProfitFactor } | Measure-Object -Average).Average
        if($trades -lt $MinTotalTrades -or $net -le 0 -or $pf -lt $MinProfitFactor) {
            continue
        }

        $rankRows.Add([pscustomobject]@{
            Variant = $candidate.Name
            Windows = $selectedRows.Count
            Net = [math]::Round($net, 2)
            Trades = [int]$trades
            AvgPF = [math]::Round($pf, 4)
        })
    }

    return $rankRows |
        Sort-Object @{ Expression = "Net"; Descending = $true }, @{ Expression = "Trades"; Descending = $true } |
        Select-Object -First $Top
}

$screenResults = @()
foreach($candidate in $candidates) {
    foreach($window in $screenWindows) {
        $result = Invoke-Mt5Backtest -Stage "screen" -Sample $window.Sample -Candidate $candidate -FromDate $window.From -ToDate $window.To
        if($null -ne $result) {
            $screenResults += $result
        }
    }
}

$allRows = if(Test-Path -LiteralPath $csvPath) { Import-Csv -LiteralPath $csvPath } else { @() }
$screenRank = Get-StageRank `
    -Rows $allRows `
    -Stage "screen" `
    -Candidates $candidates `
    -Windows $screenWindows `
    -MinTradesPerWindow $MinScreenTrades `
    -MinTotalTrades $MinTotalScreenTrades `
    -MinProfitFactor $MinScreenProfitFactor `
    -Top $TopToValidate

$validateCandidates = foreach($rank in $screenRank) {
    $candidates | Where-Object { $_.Name -eq $rank.Variant } | Select-Object -First 1
}

foreach($candidate in $validateCandidates) {
    foreach($window in $validationWindows) {
        $null = Invoke-Mt5Backtest -Stage "validation" -Sample $window.Sample -Candidate $candidate -FromDate $window.From -ToDate $window.To
    }
}

$allRows = if(Test-Path -LiteralPath $csvPath) { Import-Csv -LiteralPath $csvPath } else { @() }
$validationRank = Get-StageRank `
    -Rows $allRows `
    -Stage "validation" `
    -Candidates $candidates `
    -Windows $validationWindows `
    -MinTradesPerWindow $MinValidationTrades `
    -MinTotalTrades $MinTotalValidationTrades `
    -MinProfitFactor $MinValidationProfitFactor `
    -Top $TopToOos

$oosCandidates = foreach($rank in $validationRank) {
    $candidates | Where-Object { $_.Name -eq $rank.Variant } | Select-Object -First 1
}

foreach($candidate in $oosCandidates) {
    foreach($window in $oosWindows) {
        $null = Invoke-Mt5Backtest -Stage "oos" -Sample $window.Sample -Candidate $candidate -FromDate $window.From -ToDate $window.To
    }
}

$allRows = if(Test-Path -LiteralPath $csvPath) { Import-Csv -LiteralPath $csvPath } else { @() }
$summary = New-Object System.Collections.Generic.List[string]
$summary.Add("# GOLDm Walk-Forward Tuning")
$summary.Add("")
$summary.Add("Deposit: $Deposit USD")
$summary.Add("Model: Every tick based on real ticks")
$summary.Add("Execution delay: $ExecutionDelayMs ms")
$summary.Add("")
$summary.Add("## Screen Rank")
$summary.Add("")
$summary.Add("| Variant | Windows | Net | Trades | Avg PF |")
$summary.Add("|---|---:|---:|---:|---:|")
foreach($row in $screenRank) {
    $summary.Add(('| `{0}` | {1} | {2} | {3} | {4} |' -f $row.Variant, $row.Windows, $row.Net, $row.Trades, $row.AvgPF))
}
$summary.Add("")
$summary.Add("## Validation Rank")
$summary.Add("")
$summary.Add("| Variant | Windows | Net | Trades | Avg PF |")
$summary.Add("|---|---:|---:|---:|---:|")
foreach($row in $validationRank) {
    $summary.Add(('| `{0}` | {1} | {2} | {3} | {4} |' -f $row.Variant, $row.Windows, $row.Net, $row.Trades, $row.AvgPF))
}
$summary.Add("")
$summary.Add("## OOS Rows")
$summary.Add("")
$summary.Add("| Variant | Sample | Final | Net | Trades | PF | Win Rate | Avg Win | Avg Loss |")
$summary.Add("|---|---|---:|---:|---:|---:|---:|---:|---:|")
foreach($row in ($allRows | Where-Object { $_.Stage -eq "oos" })) {
    $summary.Add(('| `{0}` | `{1}` | {2} | {3} | {4} | {5} | {6} | {7} | {8} |' -f $row.Variant, $row.Sample, $row.FinalBalance, $row.NetProfit, $row.TotalOpened, $row.ProfitFactor, $row.WinRate, $row.AverageWin, $row.AverageLoss))
}
$summary.Add("")
$summary.Add("Rows with `TotalOpened=0` are treated as failed/no-order samples and are not promoted.")
Set-Content -LiteralPath $summaryPath -Value $summary -Encoding ASCII

"complete finished=$(Get-Date -Format s)" | Set-Content -LiteralPath $progressPath -Encoding ASCII
Get-Content -LiteralPath $summaryPath
