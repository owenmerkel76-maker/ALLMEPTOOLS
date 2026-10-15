param([string]$ExtensionDirectory = '', [string]$GitExecutable = '')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms

$repositoryUrl = 'https://github.com/owenmerkel76-maker/MEPTOOL.git'
$packageRoot = Split-Path -Parent $PSScriptRoot
$payloadRoot = Join-Path $packageRoot 'ROBMEPTOOLS.extension'
$installLock = $null
$installLockPath = $null

Import-Module (Join-Path $PSScriptRoot 'Install-Location.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'Scheduled-Task.psm1') -Force
Import-Module (Join-Path $payloadRoot 'updater/Git-Location.psm1') -Force

function Get-Hash([string]$path) {
    return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Resolve-ManagedPath([string]$root, [string]$relative) {
    if ($relative -match '[\\:\x00]' -or $relative.StartsWith('/') -or
        ($relative.Split('/') | Where-Object { $_ -eq '' -or $_ -eq '.' -or $_ -eq '..' -or $_.TrimEnd(' ', '.') -ne $_ })) {
        throw "Unsafe update path: $relative"
    }
    $path = $root
    foreach ($part in $relative.Split('/')) {
        $path = Join-Path $path $part
        if ((Test-Path -LiteralPath $path) -and
            ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Update path is a link or junction: $relative"
        }
    }
    return $path
}

function Invoke-Git([string[]]$gitArguments, [string]$directory) {
    Push-Location -LiteralPath $directory
    try {
        & $script:gitExecutable @gitArguments
        if ($LASTEXITCODE -ne 0) { throw 'GitHub sign-in or Git download failed. No tool files were installed.' }
    } finally { Pop-Location }
}

try {
    if (Get-Process -Name Revit -ErrorAction SilentlyContinue) {
        throw 'Close Revit before running Setup Auto Updates.cmd. Later background checks will wait automatically while Revit is open.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $payloadRoot 'update-manifest.json'))) {
        throw 'Extract the whole ZIP first, then run installer\Install-Updater.cmd.'
    }
    if (-not $ExtensionDirectory) {
        $preferredRoot = Join-Path $env:USERPROFILE 'Desktop\PY REVIT'
        $candidates = @(Get-ToolExtensionCandidates $preferredRoot)
        if ($candidates.Count -le 1) { $ExtensionDirectory = $preferredRoot }
        else {
            $browser = New-Object System.Windows.Forms.FolderBrowserDialog
            $browser.Description = 'Multiple copies found. Select the ROBMEPTOOLS.extension folder Revit loads.'
            $browser.ShowNewFolderButton = $false
            if (Test-Path -LiteralPath $preferredRoot) { $browser.SelectedPath = $preferredRoot }
            if ($browser.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { exit 0 }
            $ExtensionDirectory = $browser.SelectedPath
        }
    }
    $location = Resolve-ToolInstallLocation $ExtensionDirectory
    $ExtensionDirectory = $location.ExtensionDirectory
    $targetExisted = Test-Path -LiteralPath $ExtensionDirectory -PathType Container

    $script:gitExecutable = Find-ToolGit $GitExecutable
    if (-not $script:gitExecutable) {
        $gitBrowser = New-Object System.Windows.Forms.OpenFileDialog
        $gitBrowser.Title = 'Locate your existing Git installation: select git.exe inside Git\cmd or Git\bin'
        $gitBrowser.Filter = 'Git executable (git.exe)|git.exe'
        $gitBrowser.CheckFileExists = $true
        if (Test-Path -LiteralPath 'D:\' -PathType Container) { $gitBrowser.InitialDirectory = 'D:\' }
        if ($gitBrowser.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) {
            throw 'Git selection was cancelled. Rerun setup and select your existing git.exe, or install Git for Windows from https://git-scm.com/download/win if it is not installed.'
        }
        $script:gitExecutable = Find-ToolGit $gitBrowser.FileName
    }
    Write-Host "Using Git: $script:gitExecutable"
    $normalized = $ExtensionDirectory.Replace('\', '/').TrimEnd('/').ToLowerInvariant()
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $digest = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalized)) }
    finally { $sha.Dispose() }
    $installId = ([BitConverter]::ToString($digest).Replace('-', '').ToLowerInvariant()).Substring(0, 16)
    $work = Join-Path $env:LOCALAPPDATA "ROBMEPTOOLS\updates\$installId"
    [IO.Directory]::CreateDirectory($work) | Out-Null
    if (Test-Path -LiteralPath (Join-Path $work 'update.lock')) {
        throw 'Another Revit session is updating the tool. Wait for it to finish before running this installer.'
    }
    $installLockPath = Join-Path $work 'update.lock'
    $installLock = [IO.File]::Open($installLockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)

    $manifest = Get-Content -LiteralPath (Join-Path $payloadRoot 'update-manifest.json') -Raw | ConvertFrom-Json
    if ($manifest.schema -ne 1) { throw 'Unsupported installer manifest.' }
    $operations = @()
    foreach ($relative in (Get-ToolInstallFiles $manifest $location.FreshInstall)) {
        $source = Resolve-ManagedPath $payloadRoot $relative
        $destination = Resolve-ManagedPath $ExtensionDirectory $relative
        $property = $manifest.files.PSObject.Properties[$relative]
        $expected = if ($relative -eq 'update-manifest.json') { Get-Hash $source } else { $property.Value }
        if (-not $expected -or (Get-Hash $source) -ne $expected) { throw "Package checksum mismatch: $relative" }
        $existed = Test-Path -LiteralPath $destination -PathType Leaf
        if (Test-Path -LiteralPath $destination -PathType Container) { throw "Expected a file, found a folder: $relative" }
        if ($existed) {
            $actual = Get-Hash $destination
            if ($actual -eq $expected) { continue }
            $known = $manifest.previous_hashes.PSObject.Properties[$relative]
            if (-not $known -or $actual -notin $known.Value) {
                throw "Local edits preserved. Installer stopped at: $relative"
            }
        }
        $operations += [PSCustomObject]@{ Relative = $relative; Source = $source; Destination = $destination; Existed = $existed }
    }

    # Sign in through Git Credential Manager once. No token is written here.
    $cache = Join-Path $work 'repository'
    if (-not (Test-Path -LiteralPath (Join-Path $cache '.git') -PathType Container)) {
        if (Test-Path -LiteralPath $cache) { throw 'The updater cache is incomplete; it was left unchanged.' }
        $temporaryCache = Join-Path $work ('clone-' + [Guid]::NewGuid().ToString('N'))
        Invoke-Git @('clone', '--filter=blob:none', '--sparse', '--depth', '1', '--branch', 'main', $repositoryUrl, $temporaryCache) $work
        Invoke-Git @('sparse-checkout', 'set', 'ROBMEPTOOLS.extension') $temporaryCache
        [IO.Directory]::Move($temporaryCache, $cache)
    } else {
        $origin = & $script:gitExecutable -C $cache remote get-url origin
        if ($LASTEXITCODE -ne 0 -or $origin.TrimEnd('/') -ne $repositoryUrl) { throw 'Updater cache has an unexpected repository.' }
        $dirty = & $script:gitExecutable -C $cache status --porcelain
        if ($LASTEXITCODE -ne 0 -or $dirty) { throw 'Updater cache has local edits; it was left unchanged.' }
        Invoke-Git @('fetch', '--filter=blob:none', 'origin', 'main') $cache
    }

    $backup = Join-Path $work ('installer-backups\' + [Guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($backup) | Out-Null
    foreach ($item in $operations) {
        if ($item.Existed) {
            $backupFile = Resolve-ManagedPath $backup $item.Relative
            [IO.Directory]::CreateDirectory((Split-Path -Parent $backupFile)) | Out-Null
            [IO.File]::Copy($item.Destination, $backupFile, $false)
        }
    }
    $applied = @()
    $settingsFile = Join-Path $work 'settings.json'
    $previousSettings = if (Test-Path -LiteralPath $settingsFile) { [IO.File]::ReadAllBytes($settingsFile) } else { $null }
    if ($null -ne $previousSettings) { [IO.File]::WriteAllBytes((Join-Path $backup '_updater-settings.json'), $previousSettings) }
    try {
        foreach ($item in $operations) {
            $applied += $item
            [IO.Directory]::CreateDirectory((Split-Path -Parent $item.Destination)) | Out-Null
            [IO.File]::Copy($item.Source, $item.Destination, $true)
        }
        $settings = @{ auto_update = $false; scheduled_updates = $true; git_path = $script:gitExecutable }
        $encoding = New-Object Text.UTF8Encoding($false)
        $temporarySettings = Join-Path $work ('settings-' + [Guid]::NewGuid().ToString('N') + '.tmp')
        try {
            [IO.File]::WriteAllText($temporarySettings, ($settings | ConvertTo-Json), $encoding)
            if (Test-Path -LiteralPath $settingsFile) { [IO.File]::Replace($temporarySettings, $settingsFile, [NullString]::Value) }
            else { [IO.File]::Move($temporarySettings, $settingsFile) }
        } finally {
            if (Test-Path -LiteralPath $temporarySettings) { [IO.File]::Delete($temporarySettings) }
        }
        $taskName = 'ROBMEPTOOLS Auto Update ' + $installId
        $null = Register-ToolUpdateTask $taskName $ExtensionDirectory
    } catch {
        $installError = $_
        $rollbackErrors = @()
        [array]::Reverse($applied)
        foreach ($item in $applied) {
            try {
                if ($item.Existed) { [IO.File]::Copy((Resolve-ManagedPath $backup $item.Relative), $item.Destination, $true) }
                elseif (Test-Path -LiteralPath $item.Destination) { [IO.File]::Delete($item.Destination) }
            } catch { $rollbackErrors += $item.Relative }
        }
        # A failed first installation must remain eligible for a complete retry.
        # Remove only empty directories; preserve anything created by the user.
        if ($location.FreshInstall -and (Test-Path -LiteralPath $ExtensionDirectory -PathType Container)) {
            try {
                $directories = @(Get-ChildItem -LiteralPath $ExtensionDirectory -Directory -Recurse -Force |
                    Sort-Object { $_.FullName.Length } -Descending)
                foreach ($directory in $directories) {
                    if (-not @(Get-ChildItem -LiteralPath $directory.FullName -Force).Count) {
                        [IO.Directory]::Delete($directory.FullName)
                    }
                }
                if (-not $targetExisted -and -not @(Get-ChildItem -LiteralPath $ExtensionDirectory -Force).Count) {
                    [IO.Directory]::Delete($ExtensionDirectory)
                }
            } catch { $rollbackErrors += 'new installation directories' }
        }
        try {
            if ($null -ne $previousSettings) { [IO.File]::WriteAllBytes($settingsFile, $previousSettings) }
            elseif (Test-Path -LiteralPath $settingsFile) { [IO.File]::Delete($settingsFile) }
        } catch { $rollbackErrors += 'updater settings.json' }
        if ($rollbackErrors) { throw "Rollback incomplete: $($rollbackErrors -join ', '). Backup: $backup" }
        throw $installError
    }

    $resultMessage = if ($location.FreshInstall) { 'The complete tool is installed and auto updates are enabled for:' }
                     else { 'Auto updates set up for:' }
    [Windows.Forms.MessageBox]::Show("$resultMessage`n$ExtensionDirectory`n`nChecks run every 15 minutes while you are signed in. They wait while Revit is open. Your pyRevit folder link stays the same.`n`nYou can now reopen Revit.`n`nBackups and log: $work", 'ROBMEPTOOLS auto updates') | Out-Null
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'ROBMEPTOOLS updater setup', 'OK', 'Error') | Out-Null
    exit 1
} finally {
    if ($installLock) {
        $installLock.Dispose()
        [IO.File]::Delete($installLockPath)
    }
}
