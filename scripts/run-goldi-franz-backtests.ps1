param(
    [Parameter(Mandatory = $true)][string]$TerminalRoot,
    [Parameter(Mandatory = $true)][long]$AccountLogin,
    [Parameter(Mandatory = $true)][string]$AccountServer,
    [Parameter(Mandatory = $true)][string]$EvidenceRoot,
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$MetaEditorPath = "C:\Program Files\MetaTrader 5\MetaEditor64.exe",
    [ValidateSet(
        "Smoke",
        "Partial2025",
        "PartialNovFeb",
        "PartialJunCurrent",
        "Evidence",
        "Full",
        "Required"
    )][string]$Suite = "Smoke",
    [string]$BalanceCsv = "30,50,100",
    [string]$VariantCsv = "FULL",
    [string]$BatchId = (Get-Date -Format "yyyyMMddHHmmss"),
    [int]$TimeoutSeconds = 7200
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-File([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label is missing: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Resolve-Variant([string]$Name) {
    switch ($Name.ToUpperInvariant()) {
        "FULL" { return @{ Rsi = "true"; Stoch = "true"; Fib = "true" } }
        "PRICE_ONLY" { return @{ Rsi = "false"; Stoch = "false"; Fib = "false" } }
        "NO_STOCH" { return @{ Rsi = "true"; Stoch = "false"; Fib = "true" } }
        "NO_FIB_GATE" { return @{ Rsi = "true"; Stoch = "true"; Fib = "false" } }
        default { throw "Unsupported attribution variant: $Name" }
    }
}

function New-TesterConfig {
    param(
        [string]$Path,
        [string]$SetName,
        [string]$FromDate,
        [string]$ToDate,
        [int]$Balance
    )
    $lines = @(
        "[Common]",
        "Login=$AccountLogin",
        "Server=$AccountServer",
        "",
        "[Experts]",
        "AllowLiveTrading=1",
        "AllowDllImport=0",
        "Enabled=1",
        "",
        "[Tester]",
        "Expert=bot-ea\GoldIFranzShakeout",
        "ExpertParameters=$SetName",
        "Symbol=GOLD.i#",
        "Period=M1",
        "Model=4",
        "ExecutionMode=100",
        "Optimization=0",
        "FromDate=$FromDate",
        "ToDate=$ToDate",
        "ForwardMode=0",
        "Deposit=$Balance",
        "Currency=USD",
        "Leverage=1:1000",
        "UseLocal=1",
        "UseRemote=0",
        "UseCloud=0",
        "Visual=0",
        "ReplaceReport=1",
        "ShutdownTerminal=1"
    )
    [IO.File]::WriteAllLines($Path, $lines, [Text.Encoding]::ASCII)
}

function Get-RunMetrics {
    param(
        [string]$AuditPath,
        [string]$AgentLog,
        [int]$StartingBalance,
        [string]$RequestedFrom
    )
    $events = @()
    if (Test-Path -LiteralPath $AuditPath) {
        $events = @(Get-Content -LiteralPath $AuditPath | Where-Object { $_.Trim() } |
            ForEach-Object { $_ | ConvertFrom-Json })
    }
    $closed = @($events | Where-Object { $_.event_type -eq "POSITION_CLOSED" })
    $resultsR = @($closed | ForEach-Object { [double]$_.payload.result_r })
    $profits = @($closed | ForEach-Object { [double]$_.payload.profit_loss })
    $totalR = ($resultsR | Measure-Object -Sum).Sum
    if ($null -eq $totalR) { $totalR = 0.0 }
    $totalProfit = ($profits | Measure-Object -Sum).Sum
    if ($null -eq $totalProfit) { $totalProfit = 0.0 }
    $grossProfit = (@($profits | Where-Object { $_ -gt 0 }) | Measure-Object -Sum).Sum
    if ($null -eq $grossProfit) { $grossProfit = 0.0 }
    $grossLoss = [math]::Abs((@($profits | Where-Object { $_ -lt 0 }) | Measure-Object -Sum).Sum)
    $equityR = 0.0
    $peakR = 0.0
    $maximumDrawdownR = 0.0
    foreach ($resultR in $resultsR) {
        $equityR += $resultR
        $peakR = [math]::Max($peakR, $equityR)
        $maximumDrawdownR = [math]::Max($maximumDrawdownR, $peakR - $equityR)
    }
    $logText = Get-Content -LiteralPath $AgentLog -Raw
    $finalMatches = [regex]::Matches($logText, "final balance ([0-9.]+) USD")
    $finalBalance = if ($finalMatches.Count) {
        [double]$finalMatches[$finalMatches.Count - 1].Groups[1].Value
    } else { $null }
    $testBegins = [regex]::Matches($logText, "testing of .* from ([0-9.]+)")
    $actualFrom = if ($testBegins.Count) {
        $testBegins[$testBegins.Count - 1].Groups[1].Value
    } else { "" }
    $realTickBegins = [regex]::Matches($logText, "real ticks begin from ([0-9.]+)")
    $realTickFrom = if ($realTickBegins.Count) {
        $realTickBegins[$realTickBegins.Count - 1].Groups[1].Value
    } else { "" }
    $tickIntegrityOk = $logText -notmatch "(?i)real ticks absent|real ticks discarded|tick prices .*mismatch|tick volumes not matched"
    $coverageStart = if ($realTickFrom -and ($actualFrom -eq "" -or $realTickFrom -gt $actualFrom)) {
        $realTickFrom
    } else { $actualFrom }
    $ids = @($events | ForEach-Object { [string]$_.event_id })
    $modeMetrics = @{}
    foreach ($mode in @("HANDGUN_RANGE", "SNIPER_TREND")) {
        $modeClosed = @($closed | Where-Object { $_.mode -eq $mode })
        $modeR = @($modeClosed | ForEach-Object { [double]$_.payload.result_r })
        $modeMetrics[$mode] = @{
            setups = $modeClosed.Count
            expectancy_r = if ($modeR.Count) {
                (($modeR | Measure-Object -Sum).Sum / $modeR.Count)
            } else { 0.0 }
        }
    }
    return [ordered]@{
        starting_balance = $StartingBalance
        final_balance = $finalBalance
        profit_loss = if ($null -ne $finalBalance) {
            [math]::Round($finalBalance - $StartingBalance, 2)
        } else { $null }
        completed_setups = $closed.Count
        total_r = [math]::Round($totalR, 6)
        expectancy_r = if ($closed.Count) {
            [math]::Round($totalR / $closed.Count, 6)
        } else { 0.0 }
        profit_factor = if ($grossLoss -gt 0) {
            [math]::Round($grossProfit / $grossLoss, 6)
        } elseif ($grossProfit -gt 0) { 999.0 } else { 0.0 }
        maximum_drawdown_r = [math]::Round($maximumDrawdownR, 6)
        duplicate_event_ids = $ids.Count - @($ids | Sort-Object -Unique).Count
        handgun = $modeMetrics["HANDGUN_RANGE"]
        sniper = $modeMetrics["SNIPER_TREND"]
        actual_from = $actualFrom
        real_ticks_from = $realTickFrom
        tick_integrity_ok = $tickIntegrityOk
        coverage_ok = [bool]$coverageStart -and $coverageStart -le $RequestedFrom -and $tickIntegrityOk
        tester_passed = $logText -match "Test passed" -and
            $logText -match "FRANZ_READY authority=ENABLED" -and
            $logText -notmatch "FRANZ_INIT_REJECT"
        stop_out = $logText -match "(?i)stop out|margin call"
    }
}

$balances = @($BalanceCsv.Split(",", [StringSplitOptions]::RemoveEmptyEntries) |
    ForEach-Object { [int]$_.Trim() })
if ($balances.Count -eq 0 -or @($balances | Where-Object { $_ -le 0 }).Count) {
    throw "BalanceCsv must contain positive balances"
}
$variants = @($VariantCsv.Split(",", [StringSplitOptions]::RemoveEmptyEntries) |
    ForEach-Object { $_.Trim().ToUpperInvariant() })
foreach ($variant in $variants) { [void](Resolve-Variant $variant) }
$safeBatchId = $BatchId -replace "[^A-Za-z0-9_-]", "_"
if (-not $safeBatchId) { throw "BatchId must contain at least one safe character" }

$terminalPath = Assert-File (Join-Path $TerminalRoot "terminal64.exe") "Terminal"
$sourcePath = Assert-File (Join-Path $RepoRoot "mt5\Experts\bot-ea\GoldIFranzShakeout.mq5") "EA source"
$MetaEditorPath = Assert-File $MetaEditorPath "MetaEditor"
$running = @(Get-Process terminal64 -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and $_.Path -eq $terminalPath
    })
if ($running.Count) { throw "The exact Strategy Tester terminal is already running" }

New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
$compileLog = Join-Path $EvidenceRoot "GoldIFranzShakeout.compile.log"
$compile = Start-Process -FilePath $MetaEditorPath -ArgumentList @(
    "/compile:$sourcePath",
    "/log:$compileLog"
) -Wait -PassThru -WindowStyle Hidden
$compileText = Get-Content -LiteralPath $compileLog -Raw
if ($compileText -notmatch "Result: 0 errors, 0 warnings") {
    throw "MetaEditor compile was not clean: $compileLog"
}
$sourceBinary = Assert-File ([IO.Path]::ChangeExtension($sourcePath, ".ex5")) "EA binary"
$expertDir = Join-Path $TerminalRoot "MQL5\Experts\bot-ea"
$profileDir = Join-Path $TerminalRoot "MQL5\Profiles\Tester"
New-Item -ItemType Directory -Force -Path $expertDir, $profileDir | Out-Null
$targetBinary = Join-Path $expertDir "GoldIFranzShakeout.ex5"
Copy-Item -LiteralPath $sourceBinary -Destination $targetBinary -Force
$binaryHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourceBinary).Hash
if ($binaryHash -ne (Get-FileHash -Algorithm SHA256 -LiteralPath $targetBinary).Hash) {
    throw "Copied EX5 checksum mismatch"
}

$windows = switch ($Suite) {
    "Smoke" { @(@{ Name = "smoke"; From = "2026.08.04"; To = "2026.08.05" }) }
    "Partial2025" { @(@{ Name = "partial-2025"; From = "2025.01.01"; To = "2026.01.01" }) }
    "PartialNovFeb" { @(@{ Name = "partial-nov-feb"; From = "2025.11.01"; To = "2026.02.15" }) }
    "PartialJunCurrent" { @(@{ Name = "partial-jun-current"; From = "2026.06.01"; To = "2026.08.25" }) }
    "Evidence" { @(@{ Name = "evidence"; From = "2026.08.04"; To = "2026.08.20" }) }
    "Full" { @(@{ Name = "full"; From = "2020.01.01"; To = "2026.08.25" }) }
    default {
        @(
            @{ Name = "partial-2025"; From = "2025.01.01"; To = "2026.01.01" },
            @{ Name = "partial-nov-feb"; From = "2025.11.01"; To = "2026.02.15" },
            @{ Name = "partial-jun-current"; From = "2026.06.01"; To = "2026.08.25" },
            @{ Name = "full"; From = "2020.01.01"; To = "2026.08.25" }
        )
    }
}

$results = [Collections.Generic.List[object]]::new()
foreach ($window in $windows) {
    foreach ($balance in $balances) {
        foreach ($variant in $variants) {
            $settings = Resolve-Variant $variant
            $runId = "$safeBatchId-$($window.Name)-b$balance-$variant" `
                -replace "[^A-Za-z0-9_-]", "_"
            $setName = "$runId.set"
            $setPath = Join-Path $profileDir $setName
            [IO.File]::WriteAllLines($setPath, @(
                    "InpEnableTesterOrders=true",
                    "InpUseRSI=$($settings.Rsi)",
                    "InpUseStochasticReinforcement=$($settings.Stoch)",
                    "InpUseFibonacciEntryGate=$($settings.Fib)",
                    "InpRunId=$runId"
                ), [Text.Encoding]::ASCII)
            $configPath = Join-Path $EvidenceRoot "$runId.ini"
            New-TesterConfig -Path $configPath -SetName $setName `
                -FromDate $window.From -ToDate $window.To -Balance $balance
            $started = Get-Date
            $process = Start-Process -FilePath $terminalPath -ArgumentList @(
                "/portable",
                "/config:$configPath"
            ) -PassThru -WindowStyle Hidden
            if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
                Stop-Process -Id $process.Id -Force
                throw "$runId timed out after $TimeoutSeconds seconds"
            }
            $agentLog = Get-ChildItem -LiteralPath (Join-Path $TerminalRoot "Tester") `
                -Filter "*.log" -File -Recurse -ErrorAction SilentlyContinue |
                Where-Object { $_.DirectoryName -like "*Agent-*\logs" -and $_.LastWriteTime -ge $started } |
                Sort-Object LastWriteTime -Descending |
                Select-Object -First 1
            if (-not $agentLog) { throw "$runId produced no tester agent log" }
            $audit = Get-ChildItem -LiteralPath (Join-Path $TerminalRoot "Tester") `
                -Filter "audit.jsonl" -File -Recurse -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -like "*$runId*" } |
                Sort-Object LastWriteTime -Descending |
                Select-Object -First 1
            if (-not $audit) { throw "$runId produced no namespaced audit" }
            $copiedLog = Join-Path $EvidenceRoot "$runId.agent.log"
            $copiedAudit = Join-Path $EvidenceRoot "$runId.audit.jsonl"
            Copy-Item -LiteralPath $agentLog.FullName -Destination $copiedLog -Force
            Copy-Item -LiteralPath $audit.FullName -Destination $copiedAudit -Force
            $metrics = Get-RunMetrics -AuditPath $copiedAudit -AgentLog $copiedLog `
                -StartingBalance $balance -RequestedFrom $window.From
            $results.Add([pscustomobject]@{
                    run_id = $runId
                    window = $window.Name
                    from = $window.From
                    to = $window.To
                    variant = $variant
                    metrics = $metrics
                    terminal_exit_code = $process.ExitCode
                    agent_log = $copiedLog
                    audit = $copiedAudit
                })
        }
    }
}

$sourceCommitOutput = @(& git -c "safe.directory=$RepoRoot" -C $RepoRoot rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or $sourceCommitOutput.Count -eq 0) {
    throw "Cannot resolve source commit for $RepoRoot"
}
$summary = [ordered]@{
    schema_version = 1
    strategy = "GOLDI_FRANZ_SHAKEOUT"
    version = "0.1.0"
    source_commit = $sourceCommitOutput[0].Trim()
    source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash
    binary_sha256 = $binaryHash
    compile_exit_code = $compile.ExitCode
    real_orders = "DISABLED"
    results = @($results)
}
$summaryPath = Join-Path $EvidenceRoot "summary.json"
[IO.File]::WriteAllText(
    $summaryPath,
    ($summary | ConvertTo-Json -Depth 10),
    [Text.UTF8Encoding]::new($false)
)
$results | ForEach-Object {
    [pscustomobject]@{
        run = $_.run_id
        pnl = $_.metrics.profit_loss
        setups = $_.metrics.completed_setups
        expectancy_r = $_.metrics.expectancy_r
        pf = $_.metrics.profit_factor
        drawdown_r = $_.metrics.maximum_drawdown_r
        coverage = $_.metrics.coverage_ok
        passed = $_.metrics.tester_passed
    }
} | Format-Table -AutoSize
Write-Output "summary=$summaryPath"
Write-Output "real_orders=DISABLED"
