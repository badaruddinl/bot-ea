param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TerminalPath = "C:\Program Files\MetaTrader 5\terminal64.exe",
    [string]$TerminalDataPath = "C:\Users\badaruddinl\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075",
    [string]$FromDate = "2024.01.01",
    [string]$ToDate = "2026.05.06",
    [string]$Leverage = "1:1000",
    [int]$ExecutionDelayMs = 100,
    [double[]]$Deposits = @(5, 10, 20, 30, 50, 100, 200, 500, 1000),
    [string]$OnlyVariantRegex = "",
    [string]$ExtraSetPath = "",
    [string]$ExtraVariantName = "",
    [string]$ResultName = "stress_2024_deposit_matrix",
    [ValidateSet('Development', 'Validation', 'Diagnostic', 'BlindOos')]
    [string]$ResearchPurpose = 'Diagnostic',
    [switch]$ForceRerun,
    [switch]$CloseRunningTerminal
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot 'goldm-research-guard.ps1')
Stop-GoldMLegacyTerminalResearch -Label 'run-mt5-goldm-deposit-matrix.ps1'

Assert-GoldMResearchRange -FromDate $FromDate -ToDate $ToDate -Purpose $ResearchPurpose -Label $ResultName

function New-TesterConfig {
    param(
        [string]$Path,
        [string]$SetFileName,
        [string]$FromDate,
        [string]$ToDate,
        [double]$Deposit,
        [string]$Leverage,
        [int]$ExecutionDelayMs
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
    param(
        [string]$Path,
        [int]$StartLine
    )

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
    param(
        [string]$Text,
        [string]$Pattern,
        [int]$Group = 1
    )

    $matches = [regex]::Matches($Text, $Pattern)
    if($matches.Count -eq 0) {
        return ""
    }
    return $matches[$matches.Count - 1].Groups[$Group].Value
}

function Get-DiagnosticValue {
    param(
        [string]$Line,
        [string]$Name
    )

    $match = [regex]::Match($Line, "$Name=([0-9]+)")
    if($match.Success) {
        return [int64]$match.Groups[1].Value
    }
    return 0
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

$profileDir = Join-Path $TerminalDataPath "MQL5\Profiles\Tester"
New-Item -ItemType Directory -Force -Path $profileDir | Out-Null
$activeSet = Join-Path $RepoRoot "mt5\Profiles\Tester\GoldMHighRiskMicroScalper_GOLDm.set"
$repoCandidateSet = Join-Path $RepoRoot "data\backtests\goldm_high_risk_scalper\tuning\sets\GoldMHighRiskMicroScalper_GOLDm_tune_adaptive_alt8_rsi50_wide_runner.set"
$terminalCandidateSet = Join-Path $profileDir "GoldMHighRiskMicroScalper_GOLDm_tune_adaptive_alt8_rsi50_wide_runner.set"
if(Test-Path -LiteralPath $repoCandidateSet) {
    Copy-Item -LiteralPath $repoCandidateSet -Destination $terminalCandidateSet -Force
} elseif(Test-Path -LiteralPath $activeSet) {
    Copy-Item -LiteralPath $activeSet -Destination $terminalCandidateSet -Force
}
if($ExtraSetPath) {
    $resolvedExtraSetPath = (Resolve-Path -LiteralPath $ExtraSetPath).Path
    Copy-Item -LiteralPath $resolvedExtraSetPath -Destination (Join-Path $profileDir (Split-Path -Leaf $resolvedExtraSetPath)) -Force
}

$testerLogDir = Join-Path $TerminalDataPath "Tester\logs"
$testerLogPath = Join-Path $testerLogDir "$(Get-Date -Format yyyyMMdd).log"
$resultDir = Join-Path $RepoRoot "data\backtests\goldm_high_risk_scalper\$ResultName"
$configDir = Join-Path $resultDir "configs"
New-Item -ItemType Directory -Force -Path $testerLogDir, $resultDir, $configDir | Out-Null

$csvPath = Join-Path $resultDir "matrix_results.csv"
$progressPath = Join-Path $resultDir "progress.txt"

$variants = @(
    [pscustomobject]@{
        Name = "baseline_repo"
        SetFileName = "GoldMHighRiskMicroScalper_GOLDm.set"
    },
    [pscustomobject]@{
        Name = "adaptive_alt8_rsi50_wide_runner"
        SetFileName = "GoldMHighRiskMicroScalper_GOLDm_tune_adaptive_alt8_rsi50_wide_runner.set"
    }
)
if($ExtraSetPath) {
    $extraName = if($ExtraVariantName) { $ExtraVariantName } else { [System.IO.Path]::GetFileNameWithoutExtension($resolvedExtraSetPath) }
    $variants += [pscustomobject]@{
        Name = $extraName
        SetFileName = (Split-Path -Leaf $resolvedExtraSetPath)
    }
}
if($OnlyVariantRegex) {
    $variants = $variants | Where-Object { $_.Name -match $OnlyVariantRegex }
}

$completed = @{}
if($ForceRerun -and (Test-Path -LiteralPath $csvPath)) {
    Remove-Item -LiteralPath $csvPath -Force
}
if(Test-Path -LiteralPath $csvPath) {
    Import-Csv -LiteralPath $csvPath | ForEach-Object {
        $completed["$($_.Variant)|$($_.Deposit)|$($_.From)|$($_.To)"] = $true
    }
}

foreach($variant in $variants) {
    foreach($deposit in $Deposits) {
        $key = "$($variant.Name)|$deposit|$FromDate|$ToDate"
        if($completed.ContainsKey($key)) {
            continue
        }

        $startedAt = Get-Date
        "running variant=$($variant.Name) deposit=$deposit started=$($startedAt.ToString('s'))" |
            Set-Content -LiteralPath $progressPath -Encoding ASCII

        $beforeLines = 0
        if(Test-Path -LiteralPath $testerLogPath) {
            $beforeLines = (Get-Content -LiteralPath $testerLogPath -ErrorAction SilentlyContinue).Count
        }

        $configPath = Join-Path $configDir "$($variant.Name)_deposit_$deposit.ini"
        New-TesterConfig `
            -Path $configPath `
            -SetFileName $variant.SetFileName `
            -FromDate $FromDate `
            -ToDate $ToDate `
            -Deposit $deposit `
            -Leverage $Leverage `
            -ExecutionDelayMs $ExecutionDelayMs

        $process = Start-Process -FilePath $TerminalPath -ArgumentList "/config:$configPath" -Wait -PassThru -WindowStyle Hidden
        $newLines = Read-NewLines -Path $testerLogPath -StartLine $beforeLines
        $joined = $newLines -join "`n"
        $diagLine = Get-RegexLast -Text $joined -Pattern "diagnostic summary[^\r\n]*" -Group 0
        $finalBalance = Get-RegexLast -Text $joined -Pattern "final balance\s+([-0-9.]+)\s+USD"
        $onTester = Get-RegexLast -Text $joined -Pattern "OnTester result\s+([-0-9.]+)"
        $elapsed = Get-RegexLast -Text $joined -Pattern "Test passed in\s+([0-9:.]+)"
        $dataNotes = ([regex]::Matches($joined, "history data begins from[^\r\n]*|history ticks synchronized from[^\r\n]*|real ticks begin from[^\r\n]*|no history data[^\r\n]*|not enough money[^\r\n]*") |
            ForEach-Object { $_.Value } |
            Select-Object -Unique) -join " | "

        $final = if($finalBalance -ne "") { [double]$finalBalance } else { $null }
        $result = [pscustomobject]@{
            Variant = $variant.Name
            Deposit = $deposit
            From = $FromDate
            To = $ToDate
            FinalBalance = $final
            NetProfit = if($null -ne $final) { [math]::Round($final - $deposit, 2) } else { $null }
            OnTester = if($onTester -ne "") { [double]$onTester } else { $null }
            OpenedBuy = Get-DiagnosticValue -Line $diagLine -Name "openedBuy"
            OpenedSell = Get-DiagnosticValue -Line $diagLine -Name "openedSell"
            TotalOpened = (Get-DiagnosticValue -Line $diagLine -Name "openedBuy") + (Get-DiagnosticValue -Line $diagLine -Name "openedSell")
            ClosedByEa = Get-DiagnosticValue -Line $diagLine -Name "closed"
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

        "finished variant=$($variant.Name) deposit=$deposit final=$finalBalance trades=$($result.TotalOpened) elapsed=$elapsed" |
            Set-Content -LiteralPath $progressPath -Encoding ASCII
    }
}

"complete finished=$(Get-Date -Format s)" | Set-Content -LiteralPath $progressPath -Encoding ASCII
Import-Csv -LiteralPath $csvPath | Format-Table -AutoSize
