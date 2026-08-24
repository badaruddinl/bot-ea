param(
    [string]$SourceDirectory = "$env:ProgramFiles\MetaTrader 5",
    [string]$DestinationDirectory = "$env:ProgramFiles\MetaTrader 5 GOLDm"
)

$ErrorActionPreference = "Stop"
$programFilesRoot = [System.IO.Path]::GetFullPath($env:ProgramFiles).TrimEnd('\')
$source = [System.IO.Path]::GetFullPath($SourceDirectory).TrimEnd('\')
$destination = [System.IO.Path]::GetFullPath($DestinationDirectory).TrimEnd('\')
if (-not $source.StartsWith($programFilesRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Source must stay inside Program Files"
}
if (-not $destination.StartsWith($programFilesRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Destination must stay inside Program Files"
}
if ($source -eq $destination) {
    throw "Source and destination must be different"
}
$sourceExe = Join-Path $source "terminal64.exe"
if (-not (Test-Path -LiteralPath $sourceExe -PathType Leaf)) {
    throw "Source terminal not found: $sourceExe"
}
if (-not (Test-Path -LiteralPath $destination -PathType Container)) {
    New-Item -ItemType Directory -Path $destination | Out-Null
    $robocopyExit = (Start-Process -FilePath "robocopy.exe" -ArgumentList @(
        $source,
        $destination,
        "/E",
        "/COPY:DAT",
        "/DCOPY:DAT",
        "/R:2",
        "/W:2"
    ) -Wait -PassThru -WindowStyle Hidden).ExitCode
    if ($robocopyExit -ge 8) {
        throw "Robocopy failed with exit code $robocopyExit"
    }
}
$destinationExe = Join-Path $destination "terminal64.exe"
if (-not (Test-Path -LiteralPath $destinationExe -PathType Leaf)) {
    throw "Second terminal executable was not created: $destinationExe"
}
Start-Process -FilePath $destinationExe -WindowStyle Normal
Write-Output "GOLDM_MT5_PATH=$destinationExe"
Write-Output "The second terminal is open. Log in to the GOLDm real account once, then close/reopen it to verify saved credentials."
