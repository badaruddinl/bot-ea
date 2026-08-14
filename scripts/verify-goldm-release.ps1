param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$PythonExecutable = "py",
    [string]$MetaEditorPath = "C:\Program Files\MetaTrader 5\MetaEditor64.exe",
    [switch]$SkipEaCompile
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([string]$Label, [scriptblock]$Command)
    Write-Output "verify=$Label"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

Set-Location -LiteralPath $RepoRoot
$previousPythonPath = $env:PYTHONPATH
$sourcePath = Join-Path $RepoRoot "src"
$env:PYTHONPATH = if ($previousPythonPath) {
    "$sourcePath$([System.IO.Path]::PathSeparator)$previousPythonPath"
} else {
    $sourcePath
}

Invoke-Checked "git_diff_check" { git diff --check }
Invoke-Checked "python_compileall" { & $PythonExecutable -m compileall -q src tests }
Invoke-Checked "python_tests" {
    & $PythonExecutable -m unittest `
        tests.test_goldm_mt5_log_bridge `
        tests.test_goldm_trade_lifecycle `
        tests.test_goldm_telegram_approval `
        tests.test_mock_mt5_adapter `
        tests.test_mt5_execution_runtime
}

if (-not $SkipEaCompile) {
    if (-not (Test-Path -LiteralPath $MetaEditorPath)) {
        throw "MetaEditor not found: $MetaEditorPath"
    }
    $sourceEa = Join-Path $RepoRoot "mt5\Experts\bot-ea\GoldMSniperParity.mq5"
    if (-not (Test-Path -LiteralPath $sourceEa)) {
        throw "EA source not found: $sourceEa"
    }
    $verifyRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("bot-ea-verify-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $verifyRoot | Out-Null
    try {
        $stagedEa = Join-Path $verifyRoot "GoldMSniperParity.mq5"
        $compileLog = Join-Path $verifyRoot "compile.log"
        Copy-Item -LiteralPath $sourceEa -Destination $stagedEa
        $process = Start-Process -FilePath $MetaEditorPath -ArgumentList @(
            "/compile:$stagedEa",
            "/log:$compileLog"
        ) -Wait -PassThru -WindowStyle Hidden
        if (-not (Test-Path -LiteralPath ([System.IO.Path]::ChangeExtension($stagedEa, ".ex5")))) {
            throw "EA compile produced no EX5. Log: $compileLog"
        }
        $result = Get-Content -LiteralPath $compileLog -Raw
        if ($result -notmatch "Result:\s+0 errors,\s+0 warnings") {
            throw "EA compile is not clean. Log: $compileLog"
        }
        Write-Output "verify=ea_compile_0_errors_0_warnings"
        Write-Output "metaeditor_exit_code=$($process.ExitCode)"
    }
    finally {
        if (Test-Path -LiteralPath $verifyRoot) {
            Remove-Item -LiteralPath $verifyRoot -Recurse -Force
        }
    }
}

Write-Output "RELEASE_VERIFY_OK"
