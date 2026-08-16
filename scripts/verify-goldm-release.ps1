param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [Parameter(Mandatory = $true)][string]$PythonExecutable,
    [Parameter(Mandatory = $true)][string]$MetaEditorPath,
    [switch]$SkipEaCompile,
    [switch]$SkipGitDiffCheck
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot "goldm-deployment-common.psm1") -Force

function Invoke-Checked {
    param([string]$Label, [scriptblock]$Command)
    Write-Output "verify=$Label"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

$RepoRoot = Resolve-GoldMDirectory -Path $RepoRoot -Label "release repository root"
[void](Assert-GoldMAbsolutePathInput -Path $PythonExecutable -Label "PythonExecutable")
[void](Assert-GoldMAbsolutePathInput -Path $MetaEditorPath -Label "MetaEditorPath")
$pythonRuntime = Assert-GoldMPythonRuntime -PythonExecutable $PythonExecutable
$PythonExecutable = [string]$pythonRuntime.Path
$MetaEditorPath = Assert-GoldMMetaEditorExecutable -MetaEditorPath $MetaEditorPath
Set-Location -LiteralPath $RepoRoot
$sourcePath = Join-Path $RepoRoot "src"
$sitePackages = Resolve-GoldMPythonSitePackagesDirectory `
    -PythonExecutable $PythonExecutable
# Run every Python verification in isolated mode.  The bootstrap explicitly
# inserts only the sealed source and repository roots; cwd, PYTHONHOME,
# PYTHONPATH, user-site, and user sitecustomize cannot shadow release code.
$isolatedModuleBootstrap = "import runpy,sys; sys.path[:0]=[sys.argv.pop(1),sys.argv.pop(1),sys.argv.pop(1)]; runpy.run_module(sys.argv.pop(1),run_name='__main__',alter_sys=True)"

if (-not $SkipGitDiffCheck) {
    Invoke-Checked "git_diff_check" { git diff --check }
}
else {
    if (Test-Path -LiteralPath (Join-Path $RepoRoot ".git")) {
        throw "SkipGitDiffCheck is only valid for an exported release tree without .git"
    }
    Write-Output "verify=immutable_export_no_git_diff"
}
Invoke-Checked "python_compileall" {
    & $PythonExecutable -I -S -B -c $isolatedModuleBootstrap `
        $sourcePath $RepoRoot $sitePackages compileall -q src tests
}
Invoke-Checked "python_tests" {
    & $PythonExecutable -I -S -B -c $isolatedModuleBootstrap `
        $sourcePath $RepoRoot $sitePackages unittest discover -s tests -p "test_*.py"
}

if (-not $SkipEaCompile) {
    if (-not (Test-Path -LiteralPath $MetaEditorPath)) {
        throw "MetaEditor not found: $MetaEditorPath"
    }
    $sourceEa = Join-Path $RepoRoot "mt5\Experts\bot-ea\GoldMSniperParity.mq5"
    if (-not (Test-Path -LiteralPath $sourceEa)) {
        throw "EA source not found: $sourceEa"
    }
    $sourceImporter = Join-Path $RepoRoot "mt5\Scripts\bot-ea\ImportGoldMOfflineTicks.mq5"
    if (-not (Test-Path -LiteralPath $sourceImporter)) {
        throw "offline importer source not found: $sourceImporter"
    }
    $verifyRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("bot-ea-verify-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $verifyRoot | Out-Null
    try {
        $stagedEa = Join-Path $verifyRoot "GoldMSniperParity.mq5"
        $compileLog = Join-Path $verifyRoot "compile.log"
        Copy-Item -LiteralPath $sourceEa -Destination $stagedEa
        $compileArgumentLine = ConvertTo-GoldMMetaEditorArgumentLine `
            -SourcePath $stagedEa `
            -LogPath $compileLog
        $process = Start-Process `
            -FilePath $MetaEditorPath `
            -ArgumentList $compileArgumentLine `
            -Wait `
            -PassThru `
            -WindowStyle Hidden
        # MetaEditor returns the number of successfully compiled source files.
        # This command compiles exactly one source, so clean success is 1.
        if ($process.ExitCode -ne 1) {
            throw "MetaEditor did not report one successful source (code=$($process.ExitCode)). Log: $compileLog"
        }
        if (-not (Test-Path -LiteralPath ([System.IO.Path]::ChangeExtension($stagedEa, ".ex5")))) {
            throw "EA compile produced no EX5. Log: $compileLog"
        }
        $result = Get-Content -LiteralPath $compileLog -Raw
        if ($result -notmatch "Result:\s+0 errors,\s+0 warnings") {
            throw "EA compile is not clean. Log: $compileLog"
        }
        Write-Output "verify=ea_compile_0_errors_0_warnings"
        Write-Output "metaeditor_exit_code=$($process.ExitCode)"

        $stagedImporter = Join-Path $verifyRoot "ImportGoldMOfflineTicks.mq5"
        $importerCompileLog = Join-Path $verifyRoot "importer-compile.log"
        Copy-Item -LiteralPath $sourceImporter -Destination $stagedImporter
        $importerArgumentLine = ConvertTo-GoldMMetaEditorArgumentLine `
            -SourcePath $stagedImporter `
            -LogPath $importerCompileLog
        $importerProcess = Start-Process `
            -FilePath $MetaEditorPath `
            -ArgumentList $importerArgumentLine `
            -Wait `
            -PassThru `
            -WindowStyle Hidden
        if ($importerProcess.ExitCode -ne 1) {
            throw "MetaEditor did not report one successful importer source (code=$($importerProcess.ExitCode)). Log: $importerCompileLog"
        }
        if (-not (Test-Path -LiteralPath ([System.IO.Path]::ChangeExtension($stagedImporter, ".ex5")))) {
            throw "offline importer compile produced no EX5. Log: $importerCompileLog"
        }
        $importerResult = Get-Content -LiteralPath $importerCompileLog -Raw
        if ($importerResult -notmatch "Result:\s+0 errors,\s+0 warnings") {
            throw "offline importer compile is not clean. Log: $importerCompileLog"
        }
        Write-Output "verify=offline_importer_compile_0_errors_0_warnings"
        Write-Output "importer_metaeditor_exit_code=$($importerProcess.ExitCode)"
    }
    finally {
        if (Test-Path -LiteralPath $verifyRoot) {
            Remove-Item -LiteralPath $verifyRoot -Recurse -Force
        }
    }
}

Write-Output "RELEASE_VERIFY_OK"
