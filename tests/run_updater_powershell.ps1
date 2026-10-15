param([string]$Root, [string]$Case)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path (Split-Path -Parent $PSScriptRoot) 'ROBMEPTOOLS.extension/updater/Update-Core.psm1') -Force
$source = Join-Path $Root 'source'
$installed = Join-Path $Root 'Desktop/PY REVIT/CustomName.extension'
$work = Join-Path $Root 'work'
foreach ($path in @($source, $installed, $work)) { [IO.Directory]::CreateDirectory($path) | Out-Null }
function Assert($condition, [string]$message) { if (-not $condition) { throw $message } }
function Payload($files, $previous = @{}) {
    $digests = @{}
    foreach ($entry in $files.GetEnumerator()) {
        $path = Join-Path $source $entry.Key
        [IO.Directory]::CreateDirectory((Split-Path -Parent $path)) | Out-Null
        [IO.File]::WriteAllText($path, $entry.Value)
        $digests[$entry.Key] = Get-ManagedHash $path
    }
    $value = @{ schema = 1; build = 'test'; files = $digests; previous_hashes = $previous }
    [IO.File]::WriteAllText((Join-Path $source 'update-manifest.json'), ($value | ConvertTo-Json -Depth 10))
}
function Deploy([scriptblock]$before = {}) { Invoke-ManagedUpdate $installed $source $work -BeforeWrite $before }
switch ($Case) {
    'update' {
        [IO.File]::WriteAllText((Join-Path $installed 'settings.json'), 'custom settings')
        Payload @{ 'engine.py' = 'one' }
        $first = Deploy
        Assert $first.changed 'Initial update was not applied.'
        $second = Deploy
        Assert (-not $second.changed) 'Same payload was not a no-op.'
        Payload @{ 'engine.py' = 'two' }
        $third = Deploy
        Assert $third.changed 'Second release not applied.'
        Assert ([IO.File]::ReadAllText((Join-Path $installed 'engine.py')) -eq 'two') 'New engine missing.'
        Assert ([IO.File]::ReadAllText((Join-Path $installed 'settings.json')) -eq 'custom settings') 'Settings changed.'
        Assert ([IO.File]::ReadAllText((Join-Path $third.backup 'engine.py')) -eq 'one') 'Backup missing.'
    }
    'local-edit' {
        Payload @{ 'engine.py' = 'one' }
        $null = Deploy
        [IO.File]::WriteAllText((Join-Path $installed 'engine.py'), 'user edit')
        Payload @{ 'added.py' = 'new'; 'engine.py' = 'two' }
        $failed = $false
        try { $null = Deploy } catch { $failed = $_.Exception.Message -like '*Local edits preserved*' }
        Assert $failed 'Local edit was not detected.'
        Assert (-not (Test-Path -LiteralPath (Join-Path $installed 'added.py'))) 'Mutation occurred before local edit rejection.'
        Assert ([IO.File]::ReadAllText((Join-Path $installed 'engine.py')) -eq 'user edit') 'Local edit overwritten.'
    }
    'migration' {
        $old = Join-Path $installed 'engine.py'
        [IO.File]::WriteAllText($old, 'old release')
        Payload @{ 'engine.py' = 'new release' } @{ 'engine.py' = @((Get-ManagedHash $old)) }
        $result = Deploy
        Assert ([IO.File]::ReadAllText((Join-Path $result.backup 'engine.py')) -eq 'old release') 'Old release backup missing.'
        [IO.File]::WriteAllText((Join-Path $source 'engine.py'), 'corrupt')
        $failed = $false
        try { $null = Deploy } catch { $failed = $_.Exception.Message -like '*checksum mismatch*' }
        Assert $failed 'Corrupt payload accepted.'
        Assert ([IO.File]::ReadAllText($old) -eq 'new release') 'Corrupt payload changed installed engine.'
    }
    'obsolete' {
        Payload @{ 'old.py' = 'owned' }
        $null = Deploy
        [IO.File]::WriteAllText((Join-Path $installed 'extra.py'), 'custom')
        Payload @{ 'new.py' = 'new' }
        $null = Deploy
        Assert (-not (Test-Path -LiteralPath (Join-Path $installed 'old.py'))) 'Owned obsolete file not removed.'
        Assert ([IO.File]::ReadAllText((Join-Path $installed 'extra.py')) -eq 'custom') 'Extra file removed.'
    }
    'rollback' {
        Payload @{ 'a.py' = 'one'; 'b.py' = 'one' }
        $null = Deploy
        $stateHash = Get-ManagedHash (Join-Path $work 'installed-state.json')
        Payload @{ 'a.py' = 'two'; 'b.py' = 'two' }
        $script:checks = 0
        $failed = $false
        try {
            $null = Deploy { $script:checks++; if ($script:checks -eq 3) { throw 'simulated interruption' } }
        } catch { $failed = $_.Exception.Message -like '*simulated interruption*' }
        Assert $failed 'Failure injection did not run.'
        foreach ($name in @('a.py', 'b.py')) { Assert ([IO.File]::ReadAllText((Join-Path $installed $name)) -eq 'one') "Rollback failed for $name" }
        Assert ((Get-ManagedHash (Join-Path $work 'installed-state.json')) -eq $stateHash) 'Old state was lost.'
    }
    'paths' {
        foreach ($relative in @('../outside', '/absolute', 'a/nul', 'con.py', 'lib\evil', 'file:stream', 'a./file', '.git/config')) {
            $failed = $false
            try { $null = Get-ManagedPath $installed $relative } catch { $failed = $true }
            Assert $failed "Unsafe path accepted: $relative"
        }
    }
    'initialize' {
        Payload @{ 'engine.py' = 'one' }
        $null = Deploy
    }
    'revit-open' {
        [IO.Directory]::CreateDirectory((Join-Path $installed 'ROBMEPTOOLS.tab')) | Out-Null
        [IO.File]::WriteAllText((Join-Path $installed 'engine.py'), 'installed tool')
        $env:LOCALAPPDATA = Join-Path $Root 'localappdata'
        function global:Get-Process {
            [CmdletBinding()]param([string]$Name, [int]$Id)
            if ($Name -eq 'Revit') { [PSCustomObject]@{ ProcessName = 'Revit'; Id = 123 } }
        }
        & (Join-Path (Split-Path -Parent $PSScriptRoot) 'ROBMEPTOOLS.extension/updater/Update-Background.ps1') -ExtensionRoot $installed
        Assert ([IO.File]::ReadAllText((Join-Path $installed 'engine.py')) -eq 'installed tool') 'Open-Revit check changed the tool.'
        $log = @(Get-ChildItem -LiteralPath $env:LOCALAPPDATA -Recurse -Filter 'updates.log')
        Assert ($log.Count -eq 1 -and (Get-Content -LiteralPath $log[0].FullName -Raw) -like '*Revit is open*') 'Open-Revit deferral was not logged.'
        Assert (-not @(Get-ChildItem -LiteralPath $env:LOCALAPPDATA -Recurse -Filter 'update.lock').Count) 'Open-Revit check acquired a lock.'
        $statusFile = @(Get-ChildItem -LiteralPath $env:LOCALAPPDATA -Recurse -Filter 'last-check.json')
        $status = Get-Content -LiteralPath $statusFile[0].FullName -Raw | ConvertFrom-Json
        Assert ($status.status -eq 'deferred' -and $LASTEXITCODE -eq 0) 'Deferred update was reported as successful deployment or a failed task.'
    }
    default { throw "Unknown test case: $Case" }
}
Write-Output "PASS: PowerShell $Case"
