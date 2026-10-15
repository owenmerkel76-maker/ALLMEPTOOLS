# ROBMEPTOOLS unified extension installer (no network access)
# Usage: powershell -ExecutionPolicy Bypass -File .\INSTALL_WINDOWS.ps1 -ExtensionsRoot "C:\Your\pyRevit\Extensions"
[CmdletBinding()]
param([string]$ExtensionsRoot)
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'ROBMEPTOOLS.extension'
if (-not (Test-Path -LiteralPath (Join-Path $source 'ROBMEPTOOLS.tab'))) {
    throw 'The unified ROBMEPTOOLS.extension is missing from this folder.'
}
if (Get-Process -Name Revit -ErrorAction SilentlyContinue) {
    throw 'Close all Revit instances before installing to protect your in-use tools.'
}
if ([string]::IsNullOrWhiteSpace($ExtensionsRoot)) {
    Write-Host 'Enter the FOLDER registered in pyRevit Settings > Custom Extensions.'
    Write-Host 'It must be the parent folder that contains *.extension directories.'
    $ExtensionsRoot = Read-Host 'pyRevit custom extensions folder'
}
if ([string]::IsNullOrWhiteSpace($ExtensionsRoot)) { throw 'Installation cancelled: no path provided.' }
$ExtensionsRoot = [Environment]::ExpandEnvironmentVariables($ExtensionsRoot.Trim('"').Trim())
if ($ExtensionsRoot -match '(?i)\.extension[\\/]?$') {
    throw 'Provide the PARENT directory, not a path ending in .extension.'
}
# Older installations may have a Windows Scheduled Task running every 15 minutes.
# Refuse to install until user disables it; don't silently change scheduled tasks.
if (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue) {
    $legacyTasks = @(Get-ScheduledTask -ErrorAction SilentlyContinue |
        Where-Object { $_.TaskName -like 'ROBMEPTOOLS Auto Update *' -and $_.State -ne 'Disabled' })
    if ($legacyTasks.Count -gt 0) {
        $names = ($legacyTasks | ForEach-Object { $_.TaskName }) -join ', '
        throw "Existing ROBMEPTOOLS auto-update task(s) are still active: $names. In Windows Task Scheduler, disable the old ROBMEPTOOLS Auto Update task(s) before installing. Otherwise the old release may overwrite your new merged ribbon."
    }
}
New-Item -ItemType Directory -Path $ExtensionsRoot -Force | Out-Null
$root = (Resolve-Path -LiteralPath $ExtensionsRoot).Path
$target = Join-Path $root 'ROBMEPTOOLS.extension'
$backup = $null
if (Test-Path -LiteralPath $target) {
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
    $backup = Join-Path $root ("ROBMEPTOOLS_BACKUP_" + $stamp)
    Move-Item -LiteralPath $target -Destination $backup
    Write-Host "Backed up prior extension at: $backup"
}
try {
    Copy-Item -LiteralPath $source -Destination $target -Recurse -Force
    if (-not (Test-Path -LiteralPath (Join-Path $target 'ROBMEPTOOLS.tab\Hangers.panel\Auto Hanger.pushbutton\script.py'))) {
        throw 'Installation verification failed: Auto Hanger missing.'
    }
    Write-Host "Installed unified ROBMEPTOOLS to: $target"
    Write-Host 'Open Revit, run pyRevit > Reload, and look for the ROBMEPTOOLS tab.'
    Write-Host 'Remove/disable old standalone ROBMEPHANGERS, STEELTOOLS, ROOFDECKTOOLS, and ScheduleNumber2025 extensions separately if you want only one ribbon. This installer never deletes them.'
}
catch {
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
    if ($backup) { Move-Item -LiteralPath $backup -Destination $target }
    throw
}
