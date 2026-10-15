param([string]$Root, [string]$Case, [string]$NativeGit)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path (Split-Path -Parent $PSScriptRoot) 'ROBMEPTOOLS.extension/updater/Git-Location.psm1') -Force
function Assert($condition, [string]$message) { if (-not $condition) { throw $message } }
$script:gitRoot = Join-Path $Root 'D drive/Program Files/Git'
$script:gitFile = Join-Path $script:gitRoot 'cmd/git.exe'
[IO.Directory]::CreateDirectory((Split-Path -Parent $script:gitFile)) | Out-Null
[IO.File]::WriteAllText($script:gitFile, 'fixture executable')
function global:Get-Command { [CmdletBinding()]param($Name, $CommandType) }
function global:Get-ItemProperty { [CmdletBinding()]param($LiteralPath) }
switch ($Case) {
    'registry' {
        function global:Get-ItemProperty {
            [CmdletBinding()]param($LiteralPath)
            if ($LiteralPath -eq 'HKLM:\Software\GitForWindows') { [PSCustomObject]@{ InstallPath = $script:gitRoot } }
        }
        Assert ((Find-ToolGit) -eq $script:gitFile) 'Registered non-C-drive installation was not found.'
    }
    'uninstall-record' {
        function global:Get-ItemProperty {
            [CmdletBinding()]param($LiteralPath)
            if ($LiteralPath -eq 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Git_is1') {
                [PSCustomObject]@{ InstallLocation = $script:gitRoot }
            }
        }
        Assert ((Find-ToolGit) -eq $script:gitFile) 'Per-user Git installation record was ignored.'
    }
    'disk' {
        $module = Get-Module Git-Location
        & $module {
            param($DiskRoot)
            $script:testDiskRoot = $DiskRoot
            function script:Get-ToolGitDiskRoots { $script:testDiskRoot }
        } (Join-Path $Root 'D drive')
        Assert ((Find-ToolGit) -eq $script:gitFile) 'Program Files Git on a secondary drive was not found without PATH or registry.'
    }
    'explicit' {
        foreach ($path in @($script:gitRoot, $script:gitFile)) {
            Assert ((Find-ToolGit $path) -eq $script:gitFile) 'Explicit Git folder/executable with spaces was not resolved.'
        }
        $failed = $false
        try { $null = Find-ToolGit (Join-Path $Root 'missing/git.exe') } catch { $failed = $_.Exception.Message -like '*Git was not found at*' }
        Assert $failed 'Invalid selected executable did not give an actionable error.'
    }
    'missing' {
        $module = Get-Module Git-Location
        & $module { function script:Get-ToolGitInstallRoots {} }
        Assert (-not (Find-ToolGit)) 'Missing Git must allow the installer to open its file picker.'
    }
    'desktop' {
        $env:LOCALAPPDATA = Join-Path $Root 'Users/owenm/AppData/Local'
        $desktopRoot = Join-Path $env:LOCALAPPDATA 'GitHubDesktop'
        [IO.Directory]::CreateDirectory($desktopRoot) | Out-Null
        $desktopExe = Join-Path $desktopRoot 'GitHubDesktop.exe'
        [IO.File]::WriteAllText($desktopExe, 'Desktop app, not Git')
        $bundledGit = Join-Path $desktopRoot 'app-3.4.12/resources/app/git/cmd/git.exe'
        [IO.Directory]::CreateDirectory((Split-Path -Parent $bundledGit)) | Out-Null
        [IO.File]::WriteAllText($bundledGit, 'bundled Git')
        Assert ((Find-ToolGit) -eq $bundledGit) 'GitHub Desktop bundled Git was not found automatically.'
        Assert ((Find-ToolGit $desktopExe) -eq $bundledGit) 'The supplied GitHubDesktop.exe path did not resolve to actual git.exe.'
        Assert ((Find-ToolGit $desktopRoot) -eq $bundledGit) 'GitHub Desktop folder did not resolve to actual git.exe.'
    }
    'background-desktop' {
        $env:LOCALAPPDATA = Join-Path $Root 'localappdata'
        $bundled = Join-Path $env:LOCALAPPDATA 'GitHubDesktop/app-3.4.12/resources/app/git/cmd/git.exe'
        [IO.Directory]::CreateDirectory((Split-Path -Parent $bundled)) | Out-Null
        Copy-Item -LiteralPath $NativeGit -Destination $bundled
        $extension = Join-Path $Root 'Desktop/PY REVIT/ROBMEPTOOLS.extension'
        [IO.Directory]::CreateDirectory((Join-Path $extension 'ROBMEPTOOLS.tab')) | Out-Null
        $repository = Split-Path -Parent $PSScriptRoot
        Import-Module (Join-Path $repository 'ROBMEPTOOLS.extension/updater/Update-Core.psm1') -Force
        $normalized = $extension.Replace('\', '/').TrimEnd('/').ToLowerInvariant()
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $digest = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalized)) } finally { $sha.Dispose() }
        $id = ([BitConverter]::ToString($digest).Replace('-', '').ToLowerInvariant()).Substring(0, 16)
        $work = Join-Path $env:LOCALAPPDATA "ROBMEPTOOLS/updates/$id"
        [IO.Directory]::CreateDirectory($work) | Out-Null
        $settings = @{ scheduled_updates = $true; git_path = (Join-Path $env:LOCALAPPDATA 'GitHubDesktop/app-removed/resources/app/git/cmd/git.exe') }
        [IO.File]::WriteAllText((Join-Path $work 'settings.json'), ($settings | ConvertTo-Json))
        $remote = Join-Path $Root 'remote'
        $cache = Join-Path $work 'repository'
        & $NativeGit init -b main $remote | Out-Null
        $payload = Join-Path $remote 'ROBMEPTOOLS.extension'
        [IO.Directory]::CreateDirectory($payload) | Out-Null
        [IO.File]::WriteAllText((Join-Path $payload 'engine.py'), 'new tool')
        $manifest = @{ schema = 1; build = 'desktop recovery'; files = @{ 'engine.py' = (Get-ManagedHash (Join-Path $payload 'engine.py')) } }
        [IO.File]::WriteAllText((Join-Path $payload 'update-manifest.json'), ($manifest | ConvertTo-Json -Depth 10))
        & $NativeGit -C $remote add .
        & $NativeGit -C $remote -c user.name=Test -c user.email=test@example.com commit -m fixture | Out-Null
        & $NativeGit clone $remote $cache | Out-Null
        $url = 'https://github.com/owenmerkel76-maker/MEPTOOL.git'
        & $NativeGit -C $cache remote set-url origin $url
        # Route only fetch to the local fixture. Git remote get-url expands
        # insteadOf rules, so a persistent rewrite would rightly fail the
        # production repository identity check.
        $env:MEP_TEST_GIT = $NativeGit
        $env:MEP_TEST_REMOTE = $remote
        [IO.File]::WriteAllText($bundled, @'
#!/bin/sh
if [ "$1" = fetch ]; then
    exec "$MEP_TEST_GIT" -c "url.$MEP_TEST_REMOTE.insteadOf=https://github.com/owenmerkel76-maker/MEPTOOL.git" "$@"
fi
exec "$MEP_TEST_GIT" "$@"
'@ + "`n")
        function global:Get-Process { [CmdletBinding()]param($Name, $Id) }
        & (Join-Path $repository 'ROBMEPTOOLS.extension/updater/Update-Background.ps1') -ExtensionRoot $extension
        $log = Get-Content -LiteralPath (Join-Path $work 'updates.log') -Raw
        Assert (Test-Path -LiteralPath (Join-Path $extension 'engine.py')) "Background update failed after Desktop changed versions: $log"
        Assert ([IO.File]::ReadAllText((Join-Path $extension 'engine.py')) -eq 'new tool') 'Background update did not use rediscovered bundled Git.'
        Assert (-not (Test-Path -LiteralPath (Join-Path $work 'update.lock'))) 'Background recovery left an update lock.'
        $status = Get-Content -LiteralPath (Join-Path $work 'last-check.json') -Raw | ConvertFrom-Json
        Assert ($status.status -eq 'success' -and $LASTEXITCODE -eq 0) 'Successful background deployment did not produce a success result.'
        Assert ($status.manifest_sha256 -eq (Get-ManagedHash (Join-Path $extension 'update-manifest.json'))) 'Success result did not certify the installed manifest.'
        # Authentication/transport failure must produce a fresh failed result
        # and a failing process exit code without changing the installed tool.
        [IO.File]::WriteAllText($bundled, "#!/bin/sh`nexit 1`n")
        & (Join-Path $repository 'ROBMEPTOOLS.extension/updater/Update-Background.ps1') -ExtensionRoot $extension
        $status = Get-Content -LiteralPath (Join-Path $work 'last-check.json') -Raw | ConvertFrom-Json
        Assert ($status.status -eq 'failed' -and $LASTEXITCODE -eq 1) 'Git failure was reported as a successful scheduled task.'
        Assert ([IO.File]::ReadAllText((Join-Path $extension 'engine.py')) -eq 'new tool') 'Failed check changed installed files.'
    }
    default { throw "Unknown test case: $Case" }
}
Write-Output "PASS: Git location $Case"
