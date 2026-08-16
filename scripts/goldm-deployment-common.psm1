Set-StrictMode -Version Latest

function Assert-GoldMAbsolutePathInput {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    # Windows PowerShell 5.1/.NET Framework has no Path.IsPathFullyQualified.
    # A genuinely qualified file-system path has either a drive root (C:\) or
    # a complete UNC share root. IsPathRooted alone incorrectly accepts C:foo
    # and \foo, both of which depend on ambient current-drive state.
    $root = [System.IO.Path]::GetPathRoot($Path)
    $driveQualified = $root -match '^[A-Za-z]:[\\/]$'
    $uncQualified = $root -match '^\\\\[^\\/:*?"<>|]+\\[^\\/:*?"<>|]+[\\/]?$'
    # CPython 3.14 may expose sys.executable through the Windows extended-path
    # namespace (\\?\C:\...). Accept only the two explicit filesystem forms;
    # device paths such as \\.\ and other namespace providers remain rejected.
    $extendedDriveQualified = $root -match '^\\\\\?\\[A-Za-z]:[\\/]$'
    $extendedUncQualified = `
        $root -match '^\\\\\?\\UNC\\[^\\/:*?"<>|]+\\[^\\/:*?"<>|]+[\\/]?$'
    if (
        -not [System.IO.Path]::IsPathRooted($Path) -or
        (-not $driveQualified -and -not $uncQualified -and
            -not $extendedDriveQualified -and -not $extendedUncQualified)
    ) {
        throw "$Label must be an explicit absolute path"
    }
    try { [void][System.IO.Path]::GetFullPath($Path) }
    catch { throw "$Label is not a valid Windows file-system path" }
}

function Assert-GoldMNoReparsePath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    Assert-GoldMAbsolutePathInput -Path $Path -Label $Label
    $cursor = [System.IO.Path]::GetFullPath($Path)
    $volumeRoot = [System.IO.Path]::GetPathRoot($cursor)
    if (-not [string]::Equals(
        $cursor,
        $volumeRoot,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        $cursor = $cursor.TrimEnd('\')
    }
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Label cannot traverse a symbolic link, junction, mount point, or other reparse point: $cursor"
            }
        }
        if ([string]::Equals($cursor, $volumeRoot, [StringComparison]::OrdinalIgnoreCase)) {
            break
        }
        $parent = [System.IO.Directory]::GetParent($cursor)
        if (
            -not $parent -or
            [string]::Equals(
                $parent.FullName,
                $cursor,
                [StringComparison]::OrdinalIgnoreCase
            )
        ) {
            break
        }
        $cursor = $parent.FullName
    }
}

function Assert-GoldMPathWithinDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Directory,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $candidate = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetFullPath($Directory).TrimEnd('\')
    if (-not $candidate.StartsWith(
        ($root + '\'),
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "$Label must remain inside the dedicated directory: $root"
    }
    Assert-GoldMNoReparsePath -Path $root -Label "$Label root"
    Assert-GoldMNoReparsePath -Path $candidate -Label $Label
}

function Resolve-GoldMFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    Assert-GoldMNoReparsePath -Path $Path -Label $Label
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label does not exist or is not a file: $Path"
    }
    # Resolve-Path prefixes extended-length paths with a PowerShell provider
    # qualifier. Keep the canonical filesystem spelling so downstream absolute
    # path checks do not mistake a valid \\?\ path for a relative provider path.
    $resolved = (Get-Item -LiteralPath $Path -Force -ErrorAction Stop).FullName
    if ($resolved -match '^\\\\\?\\([A-Za-z]:\\.*)$') {
        return [string]$Matches[1]
    }
    if ($resolved -match '^\\\\\?\\UNC\\(.+)$') {
        return '\\' + [string]$Matches[1]
    }
    return $resolved
}

function Resolve-GoldMDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    Assert-GoldMNoReparsePath -Path $Path -Label $Label
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label does not exist or is not a directory: $Path"
    }
    $resolved = (Get-Item -LiteralPath $Path -Force -ErrorAction Stop).FullName
    if ($resolved -match '^\\\\\?\\([A-Za-z]:\\.*)$') {
        return [string]$Matches[1]
    }
    if ($resolved -match '^\\\\\?\\UNC\\(.+)$') {
        return '\\' + [string]$Matches[1]
    }
    return $resolved
}

function Get-GoldMFileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $exact = Resolve-GoldMFile -Path $Path -Label "SHA-256 input file"
    $stream = New-Object System.IO.FileStream(
        $exact,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digest = $algorithm.ComputeHash($stream)
        return ([System.BitConverter]::ToString($digest)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $algorithm.Dispose()
        $stream.Dispose()
    }
}

function Invoke-GoldMAtomicReplaceWithoutBackup {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$DestinationPath
    )
    $source = Resolve-GoldMFile -Path $SourcePath -Label "atomic replacement source"
    $destination = Resolve-GoldMFile `
        -Path $DestinationPath `
        -Label "atomic replacement destination"
    if (-not ("GoldM.Deployment.NativeFileOperations" -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace GoldM.Deployment {
    public static class NativeFileOperations {
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool ReplaceFile(
            string replacedFileName,
            string replacementFileName,
            string backupFileName,
            uint replaceFlags,
            IntPtr exclude,
            IntPtr reserved
        );

        public static bool ReplaceWithoutBackup(
            string replacedFileName,
            string replacementFileName
        ) {
            return ReplaceFile(
                replacedFileName,
                replacementFileName,
                null,
                0,
                IntPtr.Zero,
                IntPtr.Zero
            );
        }
    }
}
'@
    }
    if (-not [GoldM.Deployment.NativeFileOperations]::ReplaceWithoutBackup(
        $destination,
        $source
    )) {
        $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        $exception = New-Object System.ComponentModel.Win32Exception `
            -ArgumentList $errorCode, "Atomic file replacement failed (Win32=$errorCode)"
        throw $exception
    }
}

function Assert-GoldMStandardTerminalTopology {
    param(
        [Parameter(Mandatory = $true)][string]$TerminalExecutable,
        [Parameter(Mandatory = $true)][string]$TerminalDataPath
    )
    $exactExecutable = Resolve-GoldMFile -Path $TerminalExecutable -Label "terminal executable"
    $exactDataPath = Resolve-GoldMDirectory -Path $TerminalDataPath -Label "terminal data path"
    if (-not [string]::Equals(
        (Split-Path -Leaf $exactExecutable),
        "terminal64.exe",
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "TerminalExecutable must name the exact 64-bit MT5 terminal64.exe"
    }
    $installRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $exactExecutable)).TrimEnd('\')
    $dataRoot = [System.IO.Path]::GetFullPath($exactDataPath).TrimEnd('\')
    $installPrefix = $installRoot + '\'
    if (
        [string]::Equals($dataRoot, $installRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $dataRoot.StartsWith($installPrefix, [StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "Portable MT5 topology is unsupported; TerminalDataPath must be outside the terminal installation directory"
    }
    return [pscustomobject]@{
        LaunchMode = "standard"
        TerminalExecutable = $exactExecutable
        TerminalDataPath = $exactDataPath
    }
}

function Assert-GoldMMetaEditorExecutable {
    param([Parameter(Mandatory = $true)][string]$MetaEditorPath)
    Assert-GoldMAbsolutePathInput -Path $MetaEditorPath -Label "MetaEditorPath"
    $editor = Resolve-GoldMFile -Path $MetaEditorPath -Label "MetaEditor executable"
    if (-not [string]::Equals(
        (Split-Path -Leaf $editor),
        "MetaEditor64.exe",
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "MetaEditorPath must name the exact 64-bit MetaEditor64.exe"
    }
    return $editor
}

function ConvertTo-GoldMMetaEditorArgumentLine {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$LogPath
    )
    foreach ($binding in @(
        @($SourcePath, "MetaEditor source path"),
        @($LogPath, "MetaEditor log path")
    )) {
        $value = [string]$binding[0]
        Assert-GoldMAbsolutePathInput -Path $value -Label ([string]$binding[1])
        if ($value.Contains('"')) {
            throw "MetaEditor path contains an unsupported quote character"
        }
    }
    return ('/compile:"' + $SourcePath + '" /log:"' + $LogPath + '"')
}

function Assert-GoldMPythonInterpreter {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExecutable,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256
    )
    Assert-GoldMAbsolutePathInput -Path $PythonExecutable -Label "PythonExecutable"
    $python = Resolve-GoldMFile -Path $PythonExecutable -Label "Python interpreter"
    if (-not [string]::Equals(
        (Split-Path -Leaf $python),
        "python.exe",
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "PythonExecutable must name an explicit python.exe, not py.exe or a PATH alias"
    }
    if ($ExpectedSha256 -notmatch "^[0-9a-fA-F]{64}$") {
        throw "PythonSha256 must contain exactly 64 hexadecimal characters"
    }
    $actualSha256 = Get-GoldMFileSha256 -Path $python
    if (-not $actualSha256.Equals(
        $ExpectedSha256,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Python interpreter SHA-256 does not match the approved host prerequisite"
    }
    # Execute the interpreter only after its independently supplied digest has
    # matched. A rejected binary must never gain code execution in an elevated
    # deployment process merely so version/architecture can be probed.
    $runtime = Assert-GoldMPythonRuntime -PythonExecutable $python
    return [pscustomobject]@{
        Path = $python
        Sha256 = $actualSha256
        Version = [string]$runtime.Version
        Architecture = [string]$runtime.Architecture
    }
}

function Assert-GoldMPythonRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExecutable
    )
    if (-not [System.IO.Path]::IsPathRooted($PythonExecutable)) {
        throw "PythonExecutable must be an explicit absolute path to python.exe"
    }
    $python = Resolve-GoldMFile -Path $PythonExecutable -Label "Python interpreter"
    if (-not [string]::Equals(
        (Split-Path -Leaf $python),
        "python.exe",
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "PythonExecutable must name an explicit python.exe, not py.exe or a PATH alias"
    }
    $probeLines = @(& $python -I -S -B -c "import json,platform,struct,sys; print(json.dumps({'version':[sys.version_info.major,sys.version_info.minor],'bits':struct.calcsize('P')*8,'machine':platform.machine()}))" 2>&1)
    if ($LASTEXITCODE -ne 0 -or $probeLines.Count -ne 1) {
        throw "Python interpreter contract probe failed"
    }
    try { $probe = $probeLines[0] | ConvertFrom-Json }
    catch { throw "Python interpreter contract probe returned invalid JSON" }
    if (
        [int]$probe.version[0] -ne 3 -or
        [int]$probe.version[1] -ne 14 -or
        [int]$probe.bits -ne 64 -or
        [string]$probe.machine -notin @("AMD64", "x86_64")
    ) {
        throw "Python interpreter must be exactly CPython 3.14 64-bit AMD64"
    }
    return [pscustomobject]@{
        Path = $python
        Version = "3.14"
        Architecture = "AMD64"
    }
}

function Resolve-GoldMPythonSitePackagesDirectory {
    param([Parameter(Mandatory = $true)][string]$PythonExecutable)
    $python = Resolve-GoldMFile `
        -Path $PythonExecutable `
        -Label "Python site-packages interpreter"
    if (-not [string]::Equals(
        (Split-Path -Leaf $python),
        "python.exe",
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Python site-packages resolution requires an exact python.exe"
    }
    $pythonDirectory = Split-Path -Parent $python
    $environmentRoot = $pythonDirectory
    if ([string]::Equals(
        (Split-Path -Leaf $pythonDirectory),
        "Scripts",
        [StringComparison]::OrdinalIgnoreCase
    )) {
        $environmentRoot = Split-Path -Parent $pythonDirectory
    }
    $environmentRoot = Resolve-GoldMDirectory `
        -Path $environmentRoot `
        -Label "Python environment root"
    $sitePackages = Resolve-GoldMDirectory `
        -Path (Join-Path $environmentRoot "Lib\site-packages") `
        -Label "Python environment site-packages"
    [void](Assert-GoldMPathWithinDirectory `
        -Path $sitePackages `
        -Directory $environmentRoot `
        -Label "Python site-packages")
    return $sitePackages
}

function Enter-GoldMMaintenanceLock {
    param(
        [ValidateRange(0, 300)][int]$TimeoutSeconds = 0,
        [ValidatePattern('^[a-z0-9][a-z0-9_-]{1,63}$')][string]$Operation = "maintenance",
        [string]$RecoveryJournalSha256 = ""
    )

    # All GOLDM maintenance operations can address the same Scheduled Task,
    # SQLite database, EA files, and terminal even when launched from two
    # different repository clones.  A single machine-wide name therefore
    # closes that cross-clone race more safely than a path-derived lock.
    $name = "Global\GOLDM_DEPLOYMENT_MAINTENANCE_V1"
    $mutex = [System.Threading.Mutex]::new($false, $name)
    $acquired = $false
    try {
        try {
            $acquired = $mutex.WaitOne([TimeSpan]::FromSeconds($TimeoutSeconds))
        }
        catch [System.Threading.AbandonedMutexException] {
            # WaitOne grants ownership when it reports abandonment.  Record
            # that fact so the outer cleanup releases it, then refuse to cross
            # state potentially left halfway through a prior cutover.
            $acquired = $true
            throw "A prior GOLDM maintenance process exited while holding the machine-wide lock; inspect terminal, task, database, and rollback evidence before retrying"
        }
        if (-not $acquired) {
            throw "Another GOLDM bootstrap/deploy/update/backup/restore operation already holds the machine-wide maintenance lock"
        }

        $programData = [Environment]::GetFolderPath(
            [Environment+SpecialFolder]::CommonApplicationData
        )
        if (-not $programData) {
            throw "Cannot resolve the machine-wide ProgramData directory for the GOLDM maintenance journal"
        }
        $journalRoot = Join-Path $programData "GoldM\maintenance"
        [void](New-GoldMPrivateDirectory -Path $journalRoot)
        $journalPath = Join-Path $journalRoot "active-maintenance.json"
        $nestedLeaseId = [string]$env:GOLDM_MAINTENANCE_LEASE_ID

        if (Test-Path -LiteralPath $journalPath -PathType Leaf) {
            [void](Protect-GoldMPrivateFile -Path $journalPath)
            $existingSha256 = Get-GoldMFileSha256 -Path $journalPath
            $existing = $null
            try {
                $existing = Get-Content -LiteralPath $journalPath -Raw | ConvertFrom-Json
            }
            catch {
                # A corrupt marker is still authoritative crash evidence.  It
                # may be archived only by an explicit digest acknowledgement.
            }
            if (
                $existing -and
                [int]$existing.processId -eq $PID -and
                $nestedLeaseId -and
                [string]::Equals(
                    [string]$existing.leaseId,
                    $nestedLeaseId,
                    [StringComparison]::Ordinal
                )
            ) {
                return [pscustomobject]@{
                    Name = $name
                    Mutex = $mutex
                    JournalPath = $journalPath
                    JournalSha256 = $existingSha256
                    LeaseId = $nestedLeaseId
                    OwnsJournal = $false
                    Completed = $false
                }
            }
            if (-not $RecoveryJournalSha256) {
                throw "Unresolved GOLDM maintenance journal blocks all mutation. Inspect '$journalPath' and retry with -MaintenanceRecoveryJournalSha256 $existingSha256"
            }
            if (
                $RecoveryJournalSha256 -notmatch '^[0-9a-fA-F]{64}$' -or
                -not $existingSha256.Equals(
                    $RecoveryJournalSha256,
                    [StringComparison]::OrdinalIgnoreCase
                )
            ) {
                throw "MaintenanceRecoveryJournalSha256 does not match the unresolved journal"
            }
            $archiveName = "recovered-" + `
                [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssfffZ") + `
                "-" + $existingSha256.Substring(0, 12) + ".json"
            $archivePath = Join-Path $journalRoot $archiveName
            Move-Item -LiteralPath $journalPath -Destination $archivePath -ErrorAction Stop
            [void](Protect-GoldMPrivateFile -Path $archivePath)
        }
        elseif ($RecoveryJournalSha256) {
            throw "MaintenanceRecoveryJournalSha256 was supplied but no unresolved journal exists"
        }

        $leaseId = New-GoldMDeploymentNonce
        $journal = [ordered]@{
            schemaVersion = 1
            purpose = "GOLDM_MAINTENANCE_IN_PROGRESS"
            operation = $Operation
            leaseId = $leaseId
            processId = $PID
            startedAtUtc = [DateTime]::UtcNow.ToString("o")
            machine = [Environment]::MachineName
            user = [Environment]::UserName
        }
        $json = $journal | ConvertTo-Json -Depth 4
        $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($json)
        $stream = [System.IO.File]::Open(
            $journalPath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
        try {
            $stream.Write($bytes, 0, $bytes.Length)
            $stream.Flush($true)
        }
        finally {
            $stream.Dispose()
        }
        [void](Protect-GoldMPrivateFile -Path $journalPath)
        $journalSha256 = Get-GoldMFileSha256 -Path $journalPath
        $env:GOLDM_MAINTENANCE_LEASE_ID = $leaseId
        return [pscustomobject]@{
            Name = $name
            Mutex = $mutex
            JournalPath = $journalPath
            JournalSha256 = $journalSha256
            LeaseId = $leaseId
            OwnsJournal = $true
            Completed = $false
        }
    }
    catch {
        if ($acquired) {
            try { $mutex.ReleaseMutex() }
            catch { }
        }
        $mutex.Dispose()
        throw
    }
}

function Complete-GoldMMaintenanceLock {
    param([Parameter(Mandatory = $true)]$Lease)
    if (-not $Lease.Mutex) {
        throw "Invalid GOLDM maintenance lock lease"
    }
    if ([bool]$Lease.OwnsJournal) {
        if (-not (Test-Path -LiteralPath $Lease.JournalPath -PathType Leaf)) {
            throw "The active GOLDM maintenance journal disappeared before completion"
        }
        $actualSha256 = Get-GoldMFileSha256 -Path $Lease.JournalPath
        if (-not $actualSha256.Equals(
            [string]$Lease.JournalSha256,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "The active GOLDM maintenance journal changed unexpectedly"
        }
        Remove-Item -LiteralPath $Lease.JournalPath -Force -ErrorAction Stop
        if (Test-Path -LiteralPath $Lease.JournalPath) {
            throw "The completed GOLDM maintenance journal could not be removed"
        }
        if ([string]::Equals(
            [string]$env:GOLDM_MAINTENANCE_LEASE_ID,
            [string]$Lease.LeaseId,
            [StringComparison]::Ordinal
        )) {
            Remove-Item Env:GOLDM_MAINTENANCE_LEASE_ID -ErrorAction SilentlyContinue
        }
    }
    $Lease.Completed = $true
}

function Record-GoldMMaintenanceFailure {
    param(
        [Parameter(Mandatory = $true)]$Lease,
        [Parameter(Mandatory = $true)][System.Management.Automation.ErrorRecord]$ErrorRecord,
        [string]$EvidencePath = "",
        [string]$EvidenceSha256 = ""
    )
    if (-not [bool]$Lease.OwnsJournal -or [bool]$Lease.Completed) { return }
    if (-not (Test-Path -LiteralPath $Lease.JournalPath -PathType Leaf)) {
        throw "Cannot record failure because the maintenance journal is missing"
    }
    $actual = Get-GoldMFileSha256 -Path $Lease.JournalPath
    if (-not $actual.Equals([string]$Lease.JournalSha256, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Cannot record failure because the maintenance journal changed"
    }
    if ($EvidenceSha256 -and $EvidenceSha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw "Maintenance failure evidence SHA-256 is invalid"
    }
    $journal = Get-Content -LiteralPath $Lease.JournalPath -Raw | ConvertFrom-Json
    $journal | Add-Member -Force -NotePropertyName failure -NotePropertyValue ([ordered]@{
        failedAtUtc = [DateTime]::UtcNow.ToString("o")
        errorType = [string]$ErrorRecord.Exception.GetType().FullName
        disposition = "operation_failed_inspection_required"
        evidencePath = $EvidencePath
        evidenceSha256 = $EvidenceSha256
    })
    $temporary = $Lease.JournalPath + "." + [guid]::NewGuid().ToString("N") + ".tmp"
    try {
        Write-GoldMUtf8NoBomFile `
            -Value ($journal | ConvertTo-Json -Depth 8) `
            -Path $temporary
        [void](Protect-GoldMPrivateFile -Path $temporary)
        Invoke-GoldMAtomicReplaceWithoutBackup `
            -SourcePath $temporary `
            -DestinationPath $Lease.JournalPath
        [void](Protect-GoldMPrivateFile -Path $Lease.JournalPath)
        $Lease.JournalSha256 = Get-GoldMFileSha256 -Path $Lease.JournalPath
        Write-Warning "GOLDM maintenance failure journal: $($Lease.JournalPath) SHA256=$($Lease.JournalSha256)"
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        }
    }
}

function Exit-GoldMMaintenanceLock {
    param(
        [Parameter(Mandatory = $true)]$Lease,
        [System.Management.Automation.ErrorRecord]$PrimaryError
    )
    if (-not $Lease.Mutex) {
        throw "Invalid GOLDM maintenance lock lease"
    }
    $cleanupError = $null
    try {
        if ([bool]$Lease.OwnsJournal) {
            if (-not [bool]$Lease.Completed) {
                $cleanupError = "GOLDM maintenance did not complete; unresolved journal remains at '$($Lease.JournalPath)' with SHA256 '$($Lease.JournalSha256)'"
            }
            elseif (Test-Path -LiteralPath $Lease.JournalPath) {
                $cleanupError = "Completed GOLDM maintenance still has an active journal: '$($Lease.JournalPath)'"
            }
        }
    }
    catch {
        $cleanupError = [string]$_
    }
    finally {
        if (
            [bool]$Lease.OwnsJournal -and
            [string]::Equals(
                [string]$env:GOLDM_MAINTENANCE_LEASE_ID,
                [string]$Lease.LeaseId,
                [StringComparison]::Ordinal
            )
        ) {
            Remove-Item Env:GOLDM_MAINTENANCE_LEASE_ID -ErrorAction SilentlyContinue
        }
        try { $Lease.Mutex.ReleaseMutex() }
        finally { $Lease.Mutex.Dispose() }
    }
    if ($cleanupError) {
        if ($PrimaryError) {
            Write-Warning $cleanupError
            return
        }
        throw $cleanupError
    }
}

function Invoke-GoldMDeploymentHelper {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExecutable,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $python = Resolve-GoldMFile -Path $PythonExecutable -Label "deployment helper Python"
    $sourceRoot = Resolve-GoldMDirectory `
        -Path (Join-Path $RepoRoot "src") `
        -Label "sealed deployment helper source"
    $sitePackages = Resolve-GoldMPythonSitePackagesDirectory `
        -PythonExecutable $python
    # -S is essential: no .pth or sitecustomize code may execute before the
    # explicitly selected source and dependency roots are installed.  -I also
    # ignores PYTHONHOME/PYTHONPATH, user site, and cwd shadowing.
    $bootstrap = "import runpy,sys; sys.path[:0]=[sys.argv.pop(1),sys.argv.pop(1)]; runpy.run_module('goldm_signal.deployment',run_name='__main__',alter_sys=True)"
    $lines = @(
        & $python -I -S -B -c $bootstrap `
            $sourceRoot $sitePackages @Arguments 2>&1
    )
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "GOLDM deployment safety helper failed: $($lines -join [Environment]::NewLine)"
    }
    $jsonLine = ($lines | Where-Object { $_ -is [string] } | Select-Object -Last 1)
    if (-not $jsonLine) {
        throw "GOLDM deployment safety helper returned no JSON"
    }
    try {
        return $jsonLine | ConvertFrom-Json
    }
    catch {
        throw "GOLDM deployment safety helper returned invalid JSON"
    }
}

function Invoke-GoldMNativeChecked {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    Write-Output "step=$Label"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Write-GoldMUtf8NoBomFile {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value,
        [Parameter(Mandatory = $true)][string]$Path
    )
    Assert-GoldMAbsolutePathInput -Path $Path -Label "UTF-8 output path"
    Assert-GoldMNoReparsePath -Path $Path -Label "UTF-8 output path"
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText(
        [System.IO.Path]::GetFullPath($Path),
        $Value,
        $encoding
    )
}

function Install-GoldMOfflinePythonRelease {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExecutable,
        [Parameter(Mandatory = $true)][string]$ApplicationRoot,
        [Parameter(Mandatory = $true)][string]$WheelhousePath,
        [Parameter(Mandatory = $true)][string]$RequirementsLock
    )
    $python = Resolve-GoldMFile -Path $PythonExecutable -Label "release Python executable"
    $application = Resolve-GoldMDirectory -Path $ApplicationRoot -Label "immutable application root"
    $wheelhouse = Resolve-GoldMDirectory -Path $WheelhousePath -Label "offline wheelhouse"
    $lock = Resolve-GoldMFile -Path $RequirementsLock -Label "offline requirements lock"

    Invoke-GoldMNativeChecked "offline_hash_locked_dependencies" {
        & $python -I -B -m pip --isolated install `
            --disable-pip-version-check `
            --no-input `
            --no-index `
            --only-binary=:all: `
            --find-links $wheelhouse `
            --require-hashes `
            --requirement $lock
    }
    Invoke-GoldMNativeChecked "offline_release_dependency_check" {
        & $python -I -B -m pip --isolated check
    }
    $purelib = Resolve-GoldMPythonSitePackagesDirectory `
        -PythonExecutable $python
    $sourceRoot = Resolve-GoldMDirectory -Path (Join-Path $application "src") -Label "sealed release source"
    if (
        $sourceRoot.Contains([Environment]::NewLine) -or
        $purelib.Contains([Environment]::NewLine)
    ) {
        throw "Sealed release source path contains an unsupported newline"
    }
    $importBootstrap = "import sys; sys.path[:0]=[sys.argv[1],sys.argv[2]]; import bot_ea, goldm_signal; print('SEALED_SOURCE_IMPORT_OK')"
    Invoke-GoldMNativeChecked "sealed_source_import_check" {
        & $python -I -S -B -c $importBootstrap $sourceRoot $purelib
    }
}

function Get-GoldMReleaseIdFromTaskArguments {
    param([Parameter(Mandatory = $true)][string]$Arguments)
    $matches = [regex]::Matches(
        $Arguments,
        '(?<!\S)--release-id(?:=|\s+)"?([0-9a-f]{40})"?(?=\s|$)'
    )
    if ($matches.Count -ne 1) {
        return ""
    }
    return [string]$matches[0].Groups[1].Value
}

function New-GoldMDeploymentNonce {
    $bytes = New-Object byte[] 16
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return -join ($bytes | ForEach-Object { $_.ToString("x2") })
}

function Get-GoldMDeploymentNonceFromTaskArguments {
    param([Parameter(Mandatory = $true)][string]$Arguments)
    $matches = [regex]::Matches(
        $Arguments,
        '(?<!\S)--deployment-nonce(?:=|\s+)"?([0-9a-f]{32})"?(?=\s|$)'
    )
    if ($matches.Count -ne 1) {
        return ""
    }
    return [string]$matches[0].Groups[1].Value
}

function Get-GoldMDeploymentNonceSha256 {
    param([Parameter(Mandatory = $true)][string]$DeploymentNonce)
    if ($DeploymentNonce -notmatch '^[0-9a-f]{32}$') {
        throw "Deployment nonce must contain exactly 32 lowercase hexadecimal characters"
    }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha.ComputeHash(
            [System.Text.Encoding]::UTF8.GetBytes($DeploymentNonce)
        )
    }
    finally {
        $sha.Dispose()
    }
    return -join ($digest | ForEach-Object { $_.ToString("x2") })
}

function Get-GoldMWorkerBootstrapSource {
    # This versioned launcher uses only the CPython standard library until the
    # complete task-pinned release manifest has been verified.  Keep the
    # source deterministic: its UTF-8 bytes are embedded directly in the
    # Scheduled Task action and therefore belong to the task trust boundary.
    return @'
import hashlib,json,os,pathlib,runpy,stat,sys

def fail(message):
    raise SystemExit("sealed GOLDM worker bootstrap refused: " + message)

def reparse(path):
    try:
        value = pathlib.Path(path)
        info = value.lstat()
        attributes = getattr(info, "st_file_attributes", 0)
        junction = getattr(value, "is_junction", lambda: False)()
        return stat.S_ISLNK(info.st_mode) or bool(attributes & 0x400) or bool(junction)
    except OSError:
        fail("path identity cannot be inspected")

def exact_path(raw, label, directory):
    value = pathlib.Path(raw)
    if not value.is_absolute():
        fail(label + " is not absolute")
    cursor = value
    while True:
        if cursor.exists() and reparse(cursor):
            fail(label + " traverses a reparse point")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    try:
        resolved = value.resolve(strict=True)
    except OSError:
        fail(label + " does not exist")
    if directory and not resolved.is_dir():
        fail(label + " is not a directory")
    if not directory and not resolved.is_file():
        fail(label + " is not a regular file")
    return resolved

if len(sys.argv) < 15:
    fail("argument contract is incomplete")
release = exact_path(sys.argv[1], "release root", True)
app = exact_path(sys.argv[2], "application root", True)
manifest = exact_path(sys.argv[3], "release manifest", False)
expected_manifest_sha256 = sys.argv[4]
cli = list(sys.argv[5:])
if app != release / "app" or manifest != release / "release-tree-manifest.json":
    fail("release topology mismatch")
if pathlib.Path.cwd().resolve(strict=True) != app:
    fail("working directory mismatch")
expected_pythonw = release / ".venv" / "Scripts" / "pythonw.exe"
if pathlib.Path(sys.executable).resolve(strict=True) != expected_pythonw.resolve(strict=True):
    fail("interpreter mismatch")
if len(expected_manifest_sha256) != 64 or any(c not in "0123456789abcdef" for c in expected_manifest_sha256):
    fail("release manifest digest is invalid")
manifest_bytes = manifest.read_bytes()
if hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha256:
    fail("release manifest digest mismatch")
try:
    payload = json.loads(manifest_bytes.decode("utf-8"))
except (UnicodeDecodeError, ValueError):
    fail("release manifest JSON is invalid")
if not isinstance(payload, dict) or set(payload) != {"schemaVersion", "rootName", "files"}:
    fail("release manifest shape is invalid")
if payload["schemaVersion"] != 1 or payload["rootName"] != release.name or not isinstance(payload["files"], list):
    fail("release manifest identity is invalid")
declared = set()
for record in payload["files"]:
    if not isinstance(record, dict) or set(record) != {"path", "size", "sha256"}:
        fail("release manifest record is invalid")
    relative = record["path"]
    digest = record["sha256"]
    size = record["size"]
    if not isinstance(relative, str) or not relative or "\\" in relative:
        fail("release manifest path is invalid")
    relative_path = pathlib.PurePosixPath(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts or relative_path.as_posix() != relative:
        fail("release manifest path escapes its root")
    if relative in declared:
        fail("release manifest path is duplicated")
    if not isinstance(size, int) or size < 0 or not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        fail("release manifest file evidence is invalid")
    candidate = release.joinpath(*relative_path.parts)
    exact = exact_path(candidate, "release file", False)
    try:
        exact.relative_to(release)
    except ValueError:
        fail("release file escapes its root")
    if exact.stat().st_size != size or hashlib.sha256(exact.read_bytes()).hexdigest() != digest:
        fail("release file evidence mismatch")
    declared.add(relative)
observed = set()
excluded = {manifest.name, manifest.name + ".sha256"}
for current, directories, files in os.walk(release, topdown=True, followlinks=False):
    current_path = pathlib.Path(current)
    for name in list(directories):
        if reparse(current_path / name):
            fail("release tree contains a reparse directory")
    for name in files:
        candidate = current_path / name
        if reparse(candidate) or not candidate.is_file():
            fail("release tree contains a non-regular file")
        relative = candidate.relative_to(release).as_posix()
        if relative not in excluded:
            observed.add(relative)
if observed != declared:
    fail("release tree contains missing or unmanifested files")
source_root = exact_path(app / "src", "sealed application source", True)
site_packages = exact_path(
    release / ".venv" / "Lib" / "site-packages",
    "sealed release site-packages",
    True,
)
for import_root in (source_root, site_packages):
    try:
        import_root.relative_to(release)
    except ValueError:
        fail("sealed import root escapes its release")
sys.argv = ["goldm_signal.notify.cli"] + cli
sys.path[:0] = [str(source_root), str(site_packages)]
runpy.run_module("goldm_signal.notify.cli", run_name="__main__", alter_sys=True)
'@
}

function Get-GoldMWorkerBootstrapBase64 {
    $source = Get-GoldMWorkerBootstrapSource
    return [Convert]::ToBase64String(
        (New-Object System.Text.UTF8Encoding($false)).GetBytes($source)
    )
}

function New-GoldMWorkerArgumentLine {
    param(
        [Parameter(Mandatory = $true)][string]$ReleaseRoot,
        [Parameter(Mandatory = $true)][string]$ApplicationRoot,
        [Parameter(Mandatory = $true)][string]$ReleaseManifest,
        [Parameter(Mandatory = $true)][string]$ReleaseManifestSha256,
        [Parameter(Mandatory = $true)][string]$EnvFile,
        [Parameter(Mandatory = $true)][string]$DatabasePath,
        [Parameter(Mandatory = $true)][string]$ReleaseCommit,
        [Parameter(Mandatory = $true)][string]$DeploymentNonce,
        [Parameter(Mandatory = $true)][string]$RuntimeConfigSha256,
        [Parameter(Mandatory = $true)][string]$ProductionConfigSha256
    )
    foreach ($value in @($ReleaseRoot, $ApplicationRoot, $ReleaseManifest, $EnvFile, $DatabasePath)) {
        if ($value.Contains('"')) { throw "Worker task paths cannot contain quote characters" }
    }
    foreach ($digest in @($ReleaseManifestSha256, $RuntimeConfigSha256, $ProductionConfigSha256)) {
        if ($digest -cnotmatch '^[0-9a-f]{64}$') {
            throw "Worker task SHA-256 bindings must be lowercase hexadecimal"
        }
    }
    if ($ReleaseCommit -cnotmatch '^[0-9a-f]{40}$') {
        throw "Worker task release commit must be 40 lowercase hexadecimal characters"
    }
    if ($DeploymentNonce -cnotmatch '^[0-9a-f]{32}$') {
        throw "Worker task deployment nonce must be 32 lowercase hexadecimal characters"
    }
    $loader = "import base64,sys;exec(compile(base64.b64decode(sys.argv.pop(1)),'<goldm-sealed-worker>','exec'))"
    $bootstrap = Get-GoldMWorkerBootstrapBase64
    return "-I -S -B -c `"$loader`" $bootstrap `"$ReleaseRoot`" `"$ApplicationRoot`" `"$ReleaseManifest`" $ReleaseManifestSha256 --env-file `"$EnvFile`" --db `"$DatabasePath`" --release-id $ReleaseCommit --deployment-nonce $DeploymentNonce --release-manifest-sha256 $ReleaseManifestSha256 --runtime-config-sha256 $RuntimeConfigSha256 --production-config-sha256 $ProductionConfigSha256"
}

function Assert-GoldMWorkerTaskActionContract {
    param(
        [Parameter(Mandatory = $true)]$Action,
        [Parameter(Mandatory = $true)][string]$ExpectedEnvFile,
        [Parameter(Mandatory = $true)][string]$ExpectedDatabasePath,
        [Parameter(Mandatory = $true)][string]$ReleasesRoot,
        [Parameter(Mandatory = $true)][string]$HelperPythonExecutable,
        [Parameter(Mandatory = $true)][string]$HelperRepoRoot,
        [string]$RuntimeConfigVerificationFile = ""
    )

    $envFile = Resolve-GoldMFile -Path $ExpectedEnvFile -Label "worker environment file"
    $database = Resolve-GoldMFile -Path $ExpectedDatabasePath -Label "worker database"
    $trustedReleases = Resolve-GoldMDirectory `
        -Path $ReleasesRoot `
        -Label "trusted releases root"
    $execute = Resolve-GoldMFile `
        -Path ([string]$Action.Execute) `
        -Label "Scheduled Task worker executable"
    $workingDirectory = Resolve-GoldMDirectory `
        -Path ([string]$Action.WorkingDirectory) `
        -Label "Scheduled Task worker application root"
    if (-not [string]::Equals(
        (Split-Path -Leaf $execute),
        "pythonw.exe",
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Scheduled Task action must execute the sealed release pythonw.exe"
    }
    if (-not [string]::Equals(
        (Split-Path -Leaf $workingDirectory),
        "app",
        [StringComparison]::Ordinal
    )) {
        throw "Scheduled Task working directory must be the sealed release app directory"
    }

    $releaseRoot = Resolve-GoldMDirectory `
        -Path (Split-Path -Parent $workingDirectory) `
        -Label "Scheduled Task release root"
    $releaseParent = Resolve-GoldMDirectory `
        -Path (Split-Path -Parent $releaseRoot) `
        -Label "Scheduled Task release parent"
    if (-not [string]::Equals(
        $releaseParent,
        $trustedReleases,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Scheduled Task release must be one direct child of the trusted releases root"
    }
    $releaseName = Split-Path -Leaf $releaseRoot
    $releaseNameMatch = [regex]::Match(
        $releaseName,
        '^(?:bootstrap-)?\d{8}T\d{6}Z-([0-9a-f]{12})-[0-9a-f]{8}$',
        [System.Text.RegularExpressions.RegexOptions]::CultureInvariant
    )
    if (-not $releaseNameMatch.Success) {
        throw "Scheduled Task release directory identity is invalid"
    }
    $expectedPythonw = Resolve-GoldMFile `
        -Path (Join-Path $releaseRoot ".venv\Scripts\pythonw.exe") `
        -Label "sealed release pythonw.exe"
    if (-not [string]::Equals(
        $execute,
        $expectedPythonw,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Scheduled Task executable is outside its exact sealed release"
    }

    $arguments = [string]$Action.Arguments
    $loader = "import base64,sys;exec(compile(base64.b64decode(sys.argv.pop(1)),'<goldm-sealed-worker>','exec'))"
    $pattern = '^-I -S -B -c "' + [regex]::Escape($loader) + '" ' +
        '([A-Za-z0-9+/]+={0,2}) "([^"]+)" "([^"]+)" "([^"]+)" ' +
        '([0-9a-f]{64}) --env-file "([^"]+)" --db "([^"]+)" ' +
        '--release-id ([0-9a-f]{40}) --deployment-nonce ([0-9a-f]{32}) ' +
        '--release-manifest-sha256 ([0-9a-f]{64}) ' +
        '--runtime-config-sha256 ([0-9a-f]{64}) ' +
        '--production-config-sha256 ([0-9a-f]{64})$'
    $argumentMatch = [regex]::Match(
        $arguments,
        $pattern,
        [System.Text.RegularExpressions.RegexOptions]::CultureInvariant
    )
    if (-not $argumentMatch.Success) {
        throw "Scheduled Task worker arguments do not match the exact GOLDM CLI grammar"
    }
    if (-not [string]::Equals(
        $argumentMatch.Groups[1].Value,
        (Get-GoldMWorkerBootstrapBase64),
        [StringComparison]::Ordinal
    )) {
        throw "Scheduled Task worker bootstrap is not the reviewed stdlib-only verifier"
    }
    Assert-GoldMAbsolutePathInput `
        -Path $argumentMatch.Groups[6].Value `
        -Label "Scheduled Task environment argument"
    Assert-GoldMAbsolutePathInput `
        -Path $argumentMatch.Groups[7].Value `
        -Label "Scheduled Task database argument"
    $argumentEnv = [System.IO.Path]::GetFullPath($argumentMatch.Groups[6].Value)
    $argumentDatabase = [System.IO.Path]::GetFullPath($argumentMatch.Groups[7].Value)
    if (
        -not [string]::Equals($argumentEnv, $envFile, [StringComparison]::OrdinalIgnoreCase) -or
        -not [string]::Equals($argumentDatabase, $database, [StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "Scheduled Task worker env/database bindings do not match the explicit runtime files"
    }
    foreach ($binding in @(
        @($argumentMatch.Groups[2].Value, $releaseRoot, "release root"),
        @($argumentMatch.Groups[3].Value, $workingDirectory, "application root"),
        @($argumentMatch.Groups[4].Value, (Join-Path $releaseRoot "release-tree-manifest.json"), "release manifest")
    )) {
        if (-not [string]::Equals(
            [System.IO.Path]::GetFullPath([string]$binding[0]),
            [System.IO.Path]::GetFullPath([string]$binding[1]),
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Scheduled Task $($binding[2]) argument does not match its action topology"
        }
    }
    $releaseManifestSha256 = $argumentMatch.Groups[5].Value
    if (-not [string]::Equals(
        $releaseManifestSha256,
        $argumentMatch.Groups[10].Value,
        [StringComparison]::Ordinal
    )) {
        throw "Scheduled Task release manifest digest bindings disagree"
    }
    $releaseCommit = $argumentMatch.Groups[8].Value
    if (-not $releaseCommit.StartsWith(
        $releaseNameMatch.Groups[1].Value,
        [StringComparison]::Ordinal
    )) {
        throw "Scheduled Task release directory does not match its full release commit"
    }
    $deploymentNonce = $argumentMatch.Groups[9].Value
    $runtimeConfigSha256 = $argumentMatch.Groups[11].Value
    $productionConfigSha256 = $argumentMatch.Groups[12].Value
    $treeManifest = Resolve-GoldMFile `
        -Path (Join-Path $releaseRoot "release-tree-manifest.json") `
        -Label "sealed release tree manifest"
    $canonicalArguments = New-GoldMWorkerArgumentLine `
        -ReleaseRoot $releaseRoot `
        -ApplicationRoot $workingDirectory `
        -ReleaseManifest $treeManifest `
        -ReleaseManifestSha256 $releaseManifestSha256 `
        -EnvFile $envFile `
        -DatabasePath $database `
        -ReleaseCommit $releaseCommit `
        -DeploymentNonce $deploymentNonce `
        -RuntimeConfigSha256 $runtimeConfigSha256 `
        -ProductionConfigSha256 $productionConfigSha256
    if (-not [string]::Equals(
        $arguments,
        $canonicalArguments,
        [StringComparison]::Ordinal
    )) {
        throw "Scheduled Task worker arguments are not in exact canonical form"
    }
    [void](Invoke-GoldMDeploymentHelper `
        -PythonExecutable $HelperPythonExecutable `
        -RepoRoot $HelperRepoRoot `
        -Arguments @(
            "verify-tree-manifest",
            "--root", $releaseRoot,
            "--manifest", $treeManifest,
            "--expected-manifest-sha256", $releaseManifestSha256
        ))
    # The action path and the bytes used to verify its pinned digest are
    # deliberately separate.  During a sealed environment restore, the task
    # must remain bound to the canonical private destination while its old
    # digest is verified against the staged backup member before that member
    # replaces the destination.
    $runtimeConfigVerificationPath = $envFile
    if ($RuntimeConfigVerificationFile) {
        $runtimeConfigVerificationPath = Resolve-GoldMFile `
            -Path $RuntimeConfigVerificationFile `
            -Label "worker runtime environment verification file"
    }
    $actualRuntimeConfigSha256 = Get-GoldMFileSha256 `
        -Path $runtimeConfigVerificationPath
    if (-not [string]::Equals(
        $actualRuntimeConfigSha256,
        $runtimeConfigSha256,
        [StringComparison]::Ordinal
    )) {
        throw "Scheduled Task runtime environment digest does not match its private snapshot"
    }
    $productionContract = Invoke-GoldMDeploymentHelper `
        -PythonExecutable $HelperPythonExecutable `
        -RepoRoot $workingDirectory `
        -Arguments @("production-input-contract")
    if (-not [string]::Equals(
        [string]$productionContract.sha256,
        $productionConfigSha256,
        [StringComparison]::Ordinal
    )) {
        throw "Scheduled Task production EA input contract digest mismatch"
    }

    return [pscustomobject]@{
        Execute = $execute
        Arguments = $canonicalArguments
        WorkingDirectory = $workingDirectory
        ReleaseRoot = $releaseRoot
        ReleaseCommit = $releaseCommit
        DeploymentNonce = $deploymentNonce
        DeploymentNonceSha256 = Get-GoldMDeploymentNonceSha256 `
            -DeploymentNonce $deploymentNonce
        ReleaseTreeManifest = $treeManifest
        ReleaseTreeManifestSha256 = $releaseManifestSha256
        RuntimeConfigSha256 = $runtimeConfigSha256
        ProductionConfigSha256 = $productionConfigSha256
    }
}

function Get-GoldMWorkerProofAuthority {
    param([Parameter(Mandatory = $true)]$TaskActionContract)
    $releaseRoot = Resolve-GoldMDirectory `
        -Path ([string]$TaskActionContract.ReleaseRoot) `
        -Label "worker proof release root"
    $applicationRoot = Resolve-GoldMDirectory `
        -Path ([string]$TaskActionContract.WorkingDirectory) `
        -Label "worker proof application root"
    $python = Resolve-GoldMFile `
        -Path (Join-Path $releaseRoot ".venv\Scripts\python.exe") `
        -Label "worker proof Python"
    $pythonw = Resolve-GoldMFile `
        -Path (Join-Path $releaseRoot ".venv\Scripts\pythonw.exe") `
        -Label "worker proof pythonw"
    if (-not [string]::Equals(
        $pythonw,
        [string]$TaskActionContract.Execute,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Worker proof interpreter is not the task action's sealed pythonw sibling"
    }
    [void](Assert-GoldMPythonRuntime -PythonExecutable $python)
    $tree = Invoke-GoldMDeploymentHelper `
        -PythonExecutable $python `
        -RepoRoot $applicationRoot `
        -Arguments @(
            "verify-tree-manifest",
            "--root", $releaseRoot,
            "--manifest", [string]$TaskActionContract.ReleaseTreeManifest,
            "--expected-manifest-sha256", [string]$TaskActionContract.ReleaseTreeManifestSha256
        )
    if (-not [string]::Equals(
        [string]$tree.manifest_sha256,
        [string]$TaskActionContract.ReleaseTreeManifestSha256,
        [StringComparison]::Ordinal
    )) {
        throw "Worker proof release manifest is not exact"
    }
    $production = Invoke-GoldMDeploymentHelper `
        -PythonExecutable $python `
        -RepoRoot $applicationRoot `
        -Arguments @("production-input-contract")
    if (
        [int]$production.schema_version -ne 1 -or
        -not [string]::Equals(
            [string]$production.sha256,
            [string]$TaskActionContract.ProductionConfigSha256,
            [StringComparison]::Ordinal
        )
    ) {
        throw "Worker proof production contract is unsupported or mismatched"
    }
    return [pscustomobject]@{
        PythonExecutable = $python
        RepoRoot = $applicationRoot
        ReleaseCommit = [string]$TaskActionContract.ReleaseCommit
        ReleaseManifestSha256 = [string]$TaskActionContract.ReleaseTreeManifestSha256
        RuntimeConfigSha256 = [string]$TaskActionContract.RuntimeConfigSha256
        ProductionConfigSha256 = [string]$TaskActionContract.ProductionConfigSha256
        DeploymentNonceSha256 = [string]$TaskActionContract.DeploymentNonceSha256
    }
}

function Resolve-GoldMAccountSid {
    param([Parameter(Mandatory = $true)][string]$Identity)
    $value = $Identity.Trim()
    if (-not $value) {
        throw "Scheduled Task account identity cannot be empty"
    }
    try {
        if ($value -match '^S-1-(?:\d+-)+\d+$') {
            return (New-Object -TypeName System.Security.Principal.SecurityIdentifier -ArgumentList $value).Value
        }
        $account = New-Object -TypeName System.Security.Principal.NTAccount -ArgumentList $value
        return $account.Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value
    }
    catch {
        throw "Scheduled Task account identity cannot be resolved unambiguously to a SID: $value"
    }
}

function Wait-GoldMTelegramPollReadiness {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExecutable,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$DatabasePath,
        [Parameter(Mandatory = $true)][string]$EnvFile,
        [Parameter(Mandatory = $true)][string]$ExpectedReleaseId,
        [Parameter(Mandatory = $true)][string]$ExpectedDeploymentNonceSha256,
        [Parameter(Mandatory = $true)][string]$ExpectedReleaseManifestSha256,
        [Parameter(Mandatory = $true)][string]$ExpectedRuntimeConfigSha256,
        [Parameter(Mandatory = $true)][string]$ExpectedProductionConfigSha256,
        [Parameter(Mandatory = $true)][string]$NotBeforeUtc,
        [int]$TimeoutSeconds = 75,
        [double]$MaxAgeSeconds = 90.0
    )
    foreach ($digest in @(
        $ExpectedDeploymentNonceSha256,
        $ExpectedReleaseManifestSha256,
        $ExpectedRuntimeConfigSha256,
        $ExpectedProductionConfigSha256
    )) {
        if ($digest -cnotmatch '^[0-9a-f]{64}$') {
            throw "Expected readiness SHA-256 bindings must be 64 lowercase hex"
        }
    }
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $maxAgeText = $MaxAgeSeconds.ToString(
        [System.Globalization.CultureInfo]::InvariantCulture
    )
    do {
        try {
            return Invoke-GoldMDeploymentHelper `
                -PythonExecutable $PythonExecutable `
                -RepoRoot $RepoRoot `
                -Arguments @(
                    "telegram-readiness",
                    "--database", $DatabasePath,
                    "--env-file", $EnvFile,
                    "--expected-release-id", $ExpectedReleaseId,
                    "--expected-deployment-nonce-sha256", $ExpectedDeploymentNonceSha256,
                    "--expected-release-manifest-sha256", $ExpectedReleaseManifestSha256,
                    "--expected-runtime-config-sha256", $ExpectedRuntimeConfigSha256,
                    "--expected-production-config-sha256", $ExpectedProductionConfigSha256,
                    "--not-before-utc", $NotBeforeUtc,
                    "--max-age-seconds", $maxAgeText
                )
        }
        catch {
            $lastError = $_
        }
        Start-Sleep -Seconds 1
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Fresh exact Telegram poll readiness did not appear within $TimeoutSeconds seconds: $lastError"
}

function Stop-GoldMScheduledTaskAndWait {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [int]$TimeoutSeconds = 30
    )
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if ([string]$task.State -in @("Running", "Queued")) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    }
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $state = (Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop).State
        if ([string]$state -notin @("Running", "Queued")) {
            return $state
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Scheduled Task did not leave Running/Queued state within $TimeoutSeconds seconds: $TaskName"
}

function Get-GoldMExactWorkerProcesses {
    param([Parameter(Mandatory = $true)][string]$ExpectedExecute)
    Assert-GoldMAbsolutePathInput -Path $ExpectedExecute -Label "worker executable"
    $exactPath = [System.IO.Path]::GetFullPath($ExpectedExecute)
    $leaf = [System.IO.Path]::GetFileName($exactPath)
    if (-not [string]::Equals($leaf, "pythonw.exe", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Scheduled Task worker executable must be an exact pythonw.exe"
    }
    $escapedLeaf = $leaf.Replace("'", "''")
    $matches = @()
    foreach ($candidate in @(
        Get-CimInstance Win32_Process -Filter "Name = '$escapedLeaf'" -ErrorAction Stop
    )) {
        if (-not $candidate.ExecutablePath) {
            # An elevated maintenance process should be able to resolve this.
            # Treat missing identity as ambiguous rather than silently green.
            throw "Cannot resolve executable identity for running $leaf process PID=$($candidate.ProcessId)"
        }
        if ([string]::Equals(
            [System.IO.Path]::GetFullPath([string]$candidate.ExecutablePath),
            $exactPath,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            $matches += $candidate
        }
    }
    return $matches
}

function Disable-GoldMScheduledTaskAndWait {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [int]$TimeoutSeconds = 30
    )
    $definition = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if (@($definition.Actions).Count -ne 1) {
        throw "Scheduled Task must have exactly one action before maintenance: $TaskName"
    }
    $expectedExecute = [string]@($definition.Actions)[0].Execute
    # Disable first.  Stopping an enabled task leaves an AtLogOn trigger or a
    # Scheduler retry free to relaunch the worker while SQLite/files are being
    # mutated.  Only enter the maintenance window after both properties prove.
    Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
    # Stop unconditionally: some Scheduler versions expose Disabled as the
    # definition state while an already-running instance is still winding
    # down, so a state-gated stop alone is not a sufficient process barrier.
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        $workers = @(
            Get-GoldMExactWorkerProcesses -ExpectedExecute $expectedExecute
        )
        if (
            [string]$task.State -eq "Disabled" -and
            $task.Settings.Enabled -eq $false -and
            $workers.Count -eq 0
        ) {
            return $task
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    $workerPids = @($workers | ForEach-Object { [string]$_.ProcessId }) -join ","
    throw "Scheduled Task maintenance barrier failed: $TaskName (state=$($task.State), exact_worker_pids=$workerPids)"
}

function Start-GoldMScheduledTaskAndVerify {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$ExpectedExecute,
        [Parameter(Mandatory = $true)][string]$ExpectedArguments,
        [Parameter(Mandatory = $true)][string]$ExpectedWorkingDirectory,
        [int]$TimeoutSeconds = 30,
        [int]$StabilitySeconds = 5
    )
    Assert-GoldMScheduledTaskAction `
        -TaskName $TaskName `
        -ExpectedExecute $ExpectedExecute `
        -ExpectedArguments $ExpectedArguments `
        -ExpectedWorkingDirectory $ExpectedWorkingDirectory
    Enable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
    Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $state = (Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop).State
        if ($state -eq "Running") { break }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($state -ne "Running") {
        throw "Scheduled Task did not enter Running state: $TaskName (state=$state)"
    }
    Start-Sleep -Seconds $StabilitySeconds
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
    if ($task.State -ne "Running") {
        throw "Scheduled Task did not remain running: $TaskName (state=$($task.State), result=$($info.LastTaskResult))"
    }
    Assert-GoldMScheduledTaskAction `
        -TaskName $TaskName `
        -ExpectedExecute $ExpectedExecute `
        -ExpectedArguments $ExpectedArguments `
        -ExpectedWorkingDirectory $ExpectedWorkingDirectory
    return [pscustomobject]@{
        State = [string]$task.State
        LastTaskResult = [int]$info.LastTaskResult
    }
}

function Assert-GoldMScheduledTaskAction {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$ExpectedExecute,
        [Parameter(Mandatory = $true)][string]$ExpectedArguments,
        [Parameter(Mandatory = $true)][string]$ExpectedWorkingDirectory
    )
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if (@($task.Actions).Count -ne 1) {
        throw "Scheduled Task must have exactly one action: $TaskName"
    }
    $action = @($task.Actions)[0]
    if (-not [string]::Equals(
        [string]$action.Execute,
        $ExpectedExecute,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Scheduled Task action Execute mismatch for $TaskName"
    }
    # Python/module flags and the immutable release id are case-sensitive even
    # though Windows paths are not.  Require the argument string byte-for-byte.
    if (-not [string]::Equals(
        [string]$action.Arguments,
        $ExpectedArguments,
        [StringComparison]::Ordinal
    )) {
        throw "Scheduled Task action Arguments mismatch for $TaskName"
    }
    if (-not [string]::Equals(
        [string]$action.WorkingDirectory,
        $ExpectedWorkingDirectory,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Scheduled Task action WorkingDirectory mismatch for $TaskName"
    }
}

function Assert-GoldMScheduledTaskControlContract {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$ExpectedUserId,
        [switch]$RequireDisabled,
        [switch]$RequireEnabled
    )
    if ($RequireDisabled -and $RequireEnabled) {
        throw "Scheduled Task contract cannot require both Enabled and Disabled"
    }
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $expectedSid = Resolve-GoldMAccountSid -Identity $ExpectedUserId
    $principalSid = Resolve-GoldMAccountSid -Identity ([string]$task.Principal.UserId)
    if (-not [string]::Equals($principalSid, $expectedSid, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Scheduled Task principal is not the exact interactive operator account: $TaskName"
    }
    if ([string]$task.Principal.LogonType -notin @("Interactive", "InteractiveToken")) {
        throw "Scheduled Task principal must use Interactive logon: $TaskName"
    }
    if ([string]$task.Principal.RunLevel -ne "Highest") {
        throw "Scheduled Task principal must use Highest run level: $TaskName"
    }
    $triggers = @($task.Triggers)
    if ($triggers.Count -ne 1) {
        throw "Scheduled Task must have exactly one operator logon trigger: $TaskName"
    }
    $trigger = $triggers[0]
    if (
        [string]$trigger.CimClass.CimClassName -ne "MSFT_TaskLogonTrigger" -or
        $trigger.Enabled -ne $true -or
        -not [string]::Equals(
            (Resolve-GoldMAccountSid -Identity ([string]$trigger.UserId)),
            $expectedSid,
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "Scheduled Task trigger must be AtLogOn for the exact interactive operator account: $TaskName"
    }
    if (
        [string]$trigger.Delay -or
        [string]$trigger.StartBoundary -or
        [string]$trigger.EndBoundary -or
        [string]$trigger.ExecutionTimeLimit -or
        (
            $null -ne $trigger.Repetition -and
            (
                [string]$trigger.Repetition.Interval -or
                [string]$trigger.Repetition.Duration -or
                $trigger.Repetition.StopAtDurationEnd -eq $true
            )
        )
    ) {
        throw "Scheduled Task operator-logon trigger must be immediate, unbounded, and non-repeating: $TaskName"
    }
    if ([string]$task.Settings.MultipleInstances -ne "IgnoreNew") {
        throw "Scheduled Task must reject overlapping worker instances: $TaskName"
    }
    if (
        [int]$task.Settings.RestartCount -ne 255 -or
        [string]$task.Settings.RestartInterval -ne "PT1M" -or
        [string]$task.Settings.ExecutionTimeLimit -ne "PT0S" -or
        $task.Settings.RunOnlyIfIdle -ne $false -or
        $task.Settings.RunOnlyIfNetworkAvailable -ne $false -or
        $task.Settings.DisallowStartIfOnBatteries -ne $false -or
        $task.Settings.StopIfGoingOnBatteries -ne $false -or
        $task.Settings.StartWhenAvailable -ne $true
    ) {
        throw "Scheduled Task recovery and availability settings do not match the GOLDM worker contract: $TaskName"
    }
    if ($RequireDisabled) {
        if ([string]$task.State -ne "Disabled" -or $task.Settings.Enabled -ne $false) {
            throw "Scheduled Task must be atomically disabled at bootstrap: $TaskName"
        }
    }
    if ($RequireEnabled -and $task.Settings.Enabled -ne $true) {
        throw "Scheduled Task must remain enabled for automatic operator-logon recovery: $TaskName"
    }
    return $task
}

function Assert-GoldMScheduledTaskRunning {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$ExpectedExecute,
        [Parameter(Mandatory = $true)][string]$ExpectedArguments,
        [Parameter(Mandatory = $true)][string]$ExpectedWorkingDirectory
    )
    Assert-GoldMScheduledTaskAction `
        -TaskName $TaskName `
        -ExpectedExecute $ExpectedExecute `
        -ExpectedArguments $ExpectedArguments `
        -ExpectedWorkingDirectory $ExpectedWorkingDirectory
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
    if ([string]$task.State -ne "Running") {
        throw "Scheduled Task is not Running after readiness proof: $TaskName (state=$($task.State), result=$($info.LastTaskResult))"
    }
    return [pscustomobject]@{
        State = [string]$task.State
        LastTaskResult = [int]$info.LastTaskResult
    }
}

function Get-GoldMExactTerminalProcesses {
    param([Parameter(Mandatory = $true)][string]$TerminalExecutable)
    $exactPath = Resolve-GoldMFile -Path $TerminalExecutable -Label "terminal executable"
    $matches = @()
    foreach ($candidate in @(Get-CimInstance Win32_Process -Filter "Name = 'terminal64.exe'" -ErrorAction Stop)) {
        if (-not $candidate.ExecutablePath) {
            throw "Cannot resolve executable identity for running terminal64.exe process PID=$($candidate.ProcessId)"
        }
        if ([string]::Equals(
            [System.IO.Path]::GetFullPath([string]$candidate.ExecutablePath),
            [System.IO.Path]::GetFullPath($exactPath),
            [StringComparison]::OrdinalIgnoreCase
        )) {
            $matches += $candidate
        }
    }
    return @($matches)
}

function Stop-GoldMExactTerminalGracefully {
    param(
        [Parameter(Mandatory = $true)][string]$TerminalExecutable,
        [int]$TimeoutSeconds = 30
    )
    $matches = @(Get-GoldMExactTerminalProcesses -TerminalExecutable $TerminalExecutable)
    if ($matches.Count -gt 1) {
        throw "More than one process uses the exact MT5 executable; data-path ownership is ambiguous"
    }
    foreach ($candidate in $matches) {
        $process = Get-Process -Id ([int]$candidate.ProcessId) -ErrorAction Stop
        if (-not $process.CloseMainWindow()) {
            throw "Exact MT5 terminal has no closeable main window; refusing force-kill (PID=$($process.Id))"
        }
    }
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $remaining = @(Get-GoldMExactTerminalProcesses -TerminalExecutable $TerminalExecutable)
        if ($remaining.Count -eq 0) { return }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Exact MT5 terminal did not exit gracefully; no process was force-killed"
}

function Start-GoldMExactTerminal {
    param(
        [Parameter(Mandatory = $true)][string]$TerminalExecutable,
        [Parameter(Mandatory = $true)][string]$TerminalDataPath
    )
    $topology = Assert-GoldMStandardTerminalTopology `
        -TerminalExecutable $TerminalExecutable `
        -TerminalDataPath $TerminalDataPath
    # MT5 is an operator-facing desktop terminal.  Keep its main window
    # available so future deployments can request a graceful close.  No
    # /portable argument is ever accepted; the Python postflight proves that
    # this standard launch attached to the exact configured data directory.
    Start-Process -FilePath $topology.TerminalExecutable | Out-Null
}

function Install-GoldMFileAtomically {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256
    )
    if ($ExpectedSha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw "atomic cutover expected SHA-256 must be 64 lowercase hex"
    }
    $sourcePath = Resolve-GoldMFile -Path $Source -Label "cutover source"
    Assert-GoldMAbsolutePathInput -Path $Destination -Label "cutover destination"
    $destinationDirectory = Split-Path -Parent $Destination
    Assert-GoldMNoReparsePath -Path $destinationDirectory -Label "cutover destination directory"
    Assert-GoldMNoReparsePath -Path $Destination -Label "cutover destination"
    if (-not (Test-Path -LiteralPath $destinationDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
    }
    Assert-GoldMNoReparsePath -Path $destinationDirectory -Label "cutover destination directory"
    $temporary = Join-Path $destinationDirectory ("." + [System.IO.Path]::GetFileName($Destination) + "." + [guid]::NewGuid().ToString("N") + ".tmp")
    try {
        Copy-Item -LiteralPath $sourcePath -Destination $temporary -Force
        # The source may be runtime.env.  Privatize the staging file before
        # hashing or replacement so a failed operation cannot leave a readable
        # clear-text secret copy in a normally inherited directory.
        [void](Protect-GoldMPrivateFile -Path $temporary)
        $temporaryHash = Get-GoldMFileSha256 -Path $temporary
        if (-not [string]::Equals(
            $temporaryHash,
            $ExpectedSha256,
            [StringComparison]::Ordinal
        )) {
            throw "atomic cutover staged bytes do not match the trusted SHA-256: $Destination"
        }
        if (Test-Path -LiteralPath $Destination -PathType Leaf) {
            Assert-GoldMNoReparsePath -Path $Destination -Label "cutover destination"
            # The caller already owns an explicit sealed undo/rollback backup.
            # Do not create a second untracked copy beside the destination.
            Invoke-GoldMAtomicReplaceWithoutBackup `
                -SourcePath $temporary `
                -DestinationPath $Destination
        }
        else {
            [System.IO.File]::Move($temporary, $Destination)
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Copy-GoldMFileToPrivateStage {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$StageDirectory,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [string]$DestinationFileName = "runtime.env"
    )
    if ($DestinationFileName -cnotmatch '^[A-Za-z0-9._-]+$') {
        throw "private stage destination filename is not a safe flat member"
    }
    Assert-GoldMAbsolutePathInput -Path $StageDirectory -Label "private stage directory"
    $stageParent = Resolve-GoldMDirectory `
        -Path (Split-Path -Parent $StageDirectory) `
        -Label "private stage parent"
    Assert-GoldMNoReparsePath -Path $stageParent -Label "private stage parent"
    if (Test-Path -LiteralPath $StageDirectory) {
        throw "private stage directory must be a newly created leaf: $StageDirectory"
    }
    [void](New-GoldMPrivateDirectory -Path $StageDirectory)
    $stagedFile = Join-Path $StageDirectory $DestinationFileName
    Install-GoldMFileAtomically `
        -Source $Source `
        -Destination $stagedFile `
        -ExpectedSha256 $ExpectedSha256
    [void](Protect-GoldMPrivateFile -Path $stagedFile)
    $evidence = Get-GoldMFileEvidence -Path $stagedFile
    if (-not [string]::Equals(
        [string]$evidence.Sha256,
        $ExpectedSha256,
        [StringComparison]::Ordinal
    )) {
        throw "private staged file digest changed after installation"
    }
    return [pscustomobject]@{
        Exists = $true
        Path = [System.IO.Path]::GetFullPath($stagedFile)
        Sha256 = [string]$evidence.Sha256
        Length = [long]$evidence.Length
        StageDirectory = [System.IO.Path]::GetFullPath($StageDirectory)
    }
}

function Restore-GoldMFile {
    param(
        [Parameter(Mandatory = $true)][bool]$PreviouslyExisted,
        [Parameter(Mandatory = $true)][string]$BackupPath,
        [Parameter(Mandatory = $true)][string]$Destination,
        [string]$ExpectedSha256 = ""
    )
    if ($PreviouslyExisted) {
        Install-GoldMFileAtomically `
            -Source $BackupPath `
            -Destination $Destination `
            -ExpectedSha256 $ExpectedSha256
    }
    elseif (Test-Path -LiteralPath $Destination -PathType Leaf) {
        Assert-GoldMNoReparsePath -Path $Destination -Label "rollback destination"
        Remove-Item -LiteralPath $Destination -Force
    }
}

function Get-GoldMFileEvidence {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [pscustomobject]@{ Exists = $false; Sha256 = ""; Length = 0 }
    }
    Assert-GoldMNoReparsePath -Path $Path -Label "evidence file"
    $item = Get-Item -LiteralPath $Path
    return [pscustomobject]@{
        Exists = $true
        Sha256 = Get-GoldMFileSha256 -Path $Path
        Length = [long]$item.Length
    }
}

function Assert-GoldMFileMatchesEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Evidence,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $actual = Get-GoldMFileEvidence -Path $Path
    if ([bool]$actual.Exists -ne [bool]$Evidence.Exists) {
        throw "$Label existence does not match sealed evidence"
    }
    if (
        [bool]$Evidence.Exists -and
        -not [string]::Equals(
            [string]$actual.Sha256,
            [string]$Evidence.Sha256,
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "$Label SHA-256 does not match sealed evidence"
    }
    return $actual
}

function Write-GoldMSealedEvidence {
    param(
        [Parameter(Mandatory = $true)]$Payload,
        [Parameter(Mandatory = $true)][string]$OutputPath,
        [Parameter(Mandatory = $true)][string]$PythonExecutable,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )
    $temporary = $OutputPath + "." + [guid]::NewGuid().ToString("N") + ".tmp"
    try {
        Write-GoldMUtf8NoBomFile `
            -Value ($Payload | ConvertTo-Json -Depth 20) `
            -Path $temporary
        return Invoke-GoldMDeploymentHelper `
            -PythonExecutable $PythonExecutable `
            -RepoRoot $RepoRoot `
            -Arguments @("seal-json", "--input", $temporary, "--output", $OutputPath)
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function New-GoldMPrivateDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)
    Assert-GoldMAbsolutePathInput -Path $Path -Label "private directory"
    $fullPath = [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    $volumeRoot = [System.IO.Path]::GetPathRoot($fullPath).TrimEnd('\')
    if ([string]::Equals($fullPath, $volumeRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to replace ACLs on a filesystem root: $fullPath"
    }
    Assert-GoldMNoReparsePath -Path $fullPath -Label "private directory"
    New-Item -ItemType Directory -Path $fullPath -Force | Out-Null
    Assert-GoldMNoReparsePath -Path $fullPath -Label "private directory"
    $rawItem = Get-Item -LiteralPath $fullPath -Force -ErrorAction Stop
    if (($rawItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Private directory cannot be a symbolic link or reparse point: $fullPath"
    }
    $resolved = Resolve-GoldMDirectory -Path $fullPath -Label "private directory"
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $system = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-18")
    $administrators = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-32-544")
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in @($identity, $system, $administrators)) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            [System.Security.AccessControl.InheritanceFlags]"ContainerInherit, ObjectInherit",
            [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        [void]$acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $resolved -AclObject $acl
    $verified = Get-Acl -LiteralPath $resolved
    if (-not $verified.AreAccessRulesProtected) {
        throw "Private directory ACL still inherits permissions: $resolved"
    }
}

function Protect-GoldMPrivateFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    $rawItem = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (($rawItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Private file cannot be a symbolic link or reparse point: $Path"
    }
    $resolved = Resolve-GoldMFile -Path $Path -Label "private file"
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $system = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-18")
    $administrators = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-32-544")
    $acl = New-Object System.Security.AccessControl.FileSecurity
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in @($identity, $system, $administrators)) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        [void]$acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $resolved -AclObject $acl
    $verified = Get-Acl -LiteralPath $resolved
    if (-not $verified.AreAccessRulesProtected) {
        throw "Private file ACL still inherits permissions: $resolved"
    }
}

function Assert-GoldMReadOnlyFlatDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)
    $resolved = Resolve-GoldMDirectory -Path $Path -Label "read-only flat directory"
    foreach ($item in @(Get-ChildItem -LiteralPath $resolved -Force)) {
        if (
            $item.PSIsContainer -or
            ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
        ) {
            throw "Read-only flat directory contains a nested directory or reparse point: $($item.FullName)"
        }
        if (-not (Test-Path -LiteralPath $item.FullName -PathType Leaf)) {
            throw "Read-only flat directory contains a non-file entry: $($item.FullName)"
        }
    }
    return $resolved
}

function Copy-GoldMVerifiedWheelhouseToPrivateStage {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$DestinationPath,
        [Parameter(Mandatory = $true)][string]$ExpectedManifestSha256,
        [Parameter(Mandatory = $true)][string]$PythonExecutable,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )
    $source = Assert-GoldMReadOnlyFlatDirectory -Path $SourcePath
    Assert-GoldMAbsolutePathInput -Path $DestinationPath -Label "private wheelhouse stage"
    if (Test-Path -LiteralPath $DestinationPath) {
        throw "Private wheelhouse stage must be a newly created directory"
    }
    [void](New-GoldMPrivateDirectory -Path $DestinationPath)
    $destination = Resolve-GoldMDirectory `
        -Path $DestinationPath `
        -Label "private wheelhouse stage"
    foreach ($item in @(Get-ChildItem -LiteralPath $source -Force | Sort-Object Name)) {
        if ($item.PSIsContainer -or ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "External wheelhouse changed shape while it was being staged"
        }
        $target = Join-Path $destination $item.Name
        Copy-Item -LiteralPath $item.FullName -Destination $target -ErrorAction Stop
        [void](Protect-GoldMPrivateFile -Path $target)
    }
    $verified = Invoke-GoldMDeploymentHelper `
        -PythonExecutable $PythonExecutable `
        -RepoRoot $RepoRoot `
        -Arguments @(
            "verify-offline-wheelhouse",
            "--root", $destination,
            "--expected-manifest-sha256", $ExpectedManifestSha256
        )
    return [pscustomobject]@{
        Path = $destination
        ManifestSha256 = [string]$verified.manifest_sha256
        LockSha256 = [string]$verified.lock_sha256
    }
}

function Protect-GoldMDatabaseArtifacts {
    param([Parameter(Mandatory = $true)][string]$DatabasePath)
    foreach ($candidate in @(
        $DatabasePath,
        ($DatabasePath + "-wal"),
        ($DatabasePath + "-shm")
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            [void](Protect-GoldMPrivateFile -Path $candidate)
        }
    }
}

function Wait-GoldMSessionEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExecutable,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$LogDirectory,
        [Parameter(Mandatory = $true)][string]$CursorPath,
        [Parameter(Mandatory = $true)][string]$EnvFile,
        [int]$TimeoutSeconds = 45
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            return Invoke-GoldMDeploymentHelper `
                -PythonExecutable $PythonExecutable `
                -RepoRoot $RepoRoot `
                -Arguments @(
                    "session-evidence",
                    "--log-directory", $LogDirectory,
                    "--cursor", $CursorPath,
                    "--env-file", $EnvFile
                )
        }
        catch {
            $lastError = $_
        }
        Start-Sleep -Seconds 1
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Fresh EA session evidence did not appear within $TimeoutSeconds seconds: $lastError"
}

Export-ModuleMember -Function *-GoldM*
