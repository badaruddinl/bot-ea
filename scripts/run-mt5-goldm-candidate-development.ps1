param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string[]]$CandidateNames = @(
        "GoldMSniperParity_C1_OverlapFib.set",
        "GoldMSniperParity_C2_OverlapDecorrelated.set",
        "GoldMSniperParity_C3_ActiveUSDecorrelated.set",
        "GoldMSniperParity_C4_OverlapStrictTrend.set",
        "GoldMSniperParity_C5_OverlapVWAP.set"
    ),
    [string]$ResultName = "candidate-development-2022-2024.csv",
    [ValidateSet('Development', 'Validation')]
    [string]$PeriodSet = 'Development'
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot 'goldm-research-guard.ps1')

function Get-AgentLog {
    $terminalRoot = Join-Path $env:APPDATA "MetaQuotes\Terminal"
    $terminalData = Get-ChildItem -LiteralPath $terminalRoot -Directory |
        Where-Object {
            (Test-Path -LiteralPath (Join-Path $_.FullName "origin.txt")) -and
            ((Get-Content -Raw -LiteralPath (Join-Path $_.FullName "origin.txt")) -like "*MetaTrader 5*")
        } |
        Select-Object -First 1
    if (-not $terminalData) {
        throw "MetaTrader terminal data path was not found."
    }
    $testerRoot = Join-Path $env:APPDATA "MetaQuotes\Tester\$($terminalData.Name)"
    $log = Get-ChildItem -LiteralPath $testerRoot -Recurse -Filter "$(Get-Date -Format yyyyMMdd).log" -File |
        Sort-Object LastWriteTime |
        Select-Object -Last 1
    if (-not $log) {
        throw "MetaTrader local-agent log was not found under $testerRoot"
    }
    return $log.FullName
}

function Convert-PerformanceLine {
    param([string]$Line)

    $values = @{}
    foreach ($match in [regex]::Matches($Line, '(?<key>[A-Za-z0-9_]+)=(?<value>[^\s]+)')) {
        $values[$match.Groups['key'].Value] = $match.Groups['value'].Value
    }
    return $values
}

$segments = if ($PeriodSet -eq 'Validation') {
    @(
        @{ Name = 'v1'; From = '2024.02.28'; To = '2024.06.28' },
        @{ Name = 'v2'; From = '2024.06.28'; To = '2024.10.28' },
        @{ Name = 'v3'; From = '2024.10.28'; To = '2025.02.28' },
        @{ Name = 'v4'; From = '2025.02.28'; To = '2025.06.28' },
        @{ Name = 'v5'; From = '2025.06.28'; To = '2025.10.28' },
        @{ Name = 'v6'; From = '2025.10.28'; To = '2026.02.28' }
    )
} else {
    @(
        @{ Name = 'p1'; From = '2022.02.28'; To = '2022.06.28' },
        @{ Name = 'p2'; From = '2022.06.28'; To = '2022.10.28' },
        @{ Name = 'p3'; From = '2022.10.28'; To = '2023.02.28' },
        @{ Name = 'p4'; From = '2023.02.28'; To = '2023.06.28' },
        @{ Name = 'p5'; From = '2023.06.28'; To = '2023.10.28' },
        @{ Name = 'p6'; From = '2023.10.28'; To = '2024.02.28' }
    )
}

$runner = Join-Path $PSScriptRoot 'run-mt5-goldm-sniper-backtests.ps1'
$results = [System.Collections.Generic.List[object]]::new()
foreach ($candidate in $CandidateNames) {
    $candidateId = [System.IO.Path]::GetFileNameWithoutExtension($candidate) -replace '^GoldMSniperParity_', ''
    for ($index = 0; $index -lt $segments.Count; $index += 2) {
        $first = $segments[$index]
        $second = $segments[$index + 1]
        Assert-GoldMResearchRange -FromDate $first.From -ToDate $first.To -Purpose $PeriodSet -Label "$candidateId/$($first.Name)"
        Assert-GoldMResearchRange -FromDate $second.From -ToDate $second.To -Purpose $PeriodSet -Label "$candidateId/$($second.Name)"

        Write-Output "candidate=$candidateId segments=$($first.Name),$($second.Name)"
        & $runner -RepoRoot $RepoRoot -CloseRunningTerminal -ExpertParameters $candidate `
            -BacktestFrom $first.From -BacktestTo $first.To -BacktestName "dev_${candidateId}_$($first.Name)" `
            -OosFrom $second.From -OosTo $second.To -OosName "dev_${candidateId}_$($second.Name)" `
            -BacktestPurpose $PeriodSet -OosPurpose $PeriodSet |
            ForEach-Object { Write-Output "runner:$_" }

        $agentLog = Get-AgentLog
        $summaryLines = Select-String -LiteralPath $agentLog -Pattern 'SNIPER_PERFORMANCE' |
            Select-Object -Last 2
        if ($summaryLines.Count -ne 2) {
            throw "Expected two performance summaries after $candidateId $($first.Name)/$($second.Name)."
        }

        for ($offset = 0; $offset -lt 2; $offset++) {
            $segment = $segments[$index + $offset]
            $metrics = Convert-PerformanceLine -Line $summaryLines[$offset].Line
            $results.Add([pscustomobject]@{
                candidate = $candidateId
                segment = $segment.Name
                from = $segment.From
                to = $segment.To
                resolved = [int]$metrics.resolved
                totalR = [double]$metrics.totalR
                expectancyR = [double]$metrics.expectancyR
                p1 = [double]$metrics.P1
                p2 = [double]$metrics.P2
                p3 = [double]$metrics.P3
                averageMfeR = [double]$metrics.averageMFE_R
                averageMaeR = [double]$metrics.averageMAE_R
            })
        }
    }
}

$resultDir = Join-Path $RepoRoot 'data\backtests\goldm_sniper_signal_v1\candidate-matrix'
New-Item -ItemType Directory -Force -Path $resultDir | Out-Null
$resultPath = Join-Path $resultDir $ResultName
$results | Export-Csv -LiteralPath $resultPath -NoTypeInformation -Encoding UTF8
Write-Output "result=$resultPath"

$ranking = $results |
    Group-Object candidate |
    ForEach-Object {
        $trades = ($_.Group | Measure-Object resolved -Sum).Sum
        $totalR = ($_.Group | Measure-Object totalR -Sum).Sum
        [pscustomobject]@{
            candidate = $_.Name
            trades = $trades
            totalR = [math]::Round($totalR, 5)
            expectancyR = if ($trades -gt 0) { [math]::Round($totalR / $trades, 5) } else { 0.0 }
            positiveSegments = ($_.Group | Where-Object totalR -gt 0).Count
            worstSegmentR = [math]::Round(($_.Group | Measure-Object totalR -Minimum).Minimum, 5)
        }
    } |
    Sort-Object expectancyR -Descending
$ranking | Format-Table -AutoSize | Out-String | Write-Output
