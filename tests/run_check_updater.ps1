param([string]$Root, [string]$Case, [string]$NativeGit)
$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent $PSScriptRoot
$env:USERPROFILE = $Root
$env:LOCALAPPDATA = Join-Path $Root 'localappdata'
$extension = Join-Path $Root 'Desktop/PY REVIT/ROBMEPTOOLS.extension'
[IO.Directory]::CreateDirectory($extension) | Out-Null
$required = 'ROBMEPTOOLS.tab/Annotation.panel/AutoDim Smart.pushbutton/engines/duct_engine.py'
$engine = Join-Path $extension $required
[IO.Directory]::CreateDirectory((Split-Path -Parent $engine)) | Out-Null
[IO.File]::WriteAllText($engine, 'tool fixture')
Import-Module (Join-Path $repository 'ROBMEPTOOLS.extension/updater/Update-Core.psm1') -Force
$manifest = @{ schema = 1; build = 'check fixture'; files = @{ $required = (Get-ManagedHash $engine) } }
[IO.File]::WriteAllText((Join-Path $extension 'update-manifest.json'), ($manifest | ConvertTo-Json -Depth 10))
$normalized = $extension.Replace('\', '/').TrimEnd('/').ToLowerInvariant()
$sha = [Security.Cryptography.SHA256]::Create()
try { $digest = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalized)) } finally { $sha.Dispose() }
$id = ([BitConverter]::ToString($digest).Replace('-', '').ToLowerInvariant()).Substring(0, 16)
$work = Join-Path $env:LOCALAPPDATA "ROBMEPTOOLS/updates/$id"
[IO.Directory]::CreateDirectory($work) | Out-Null
$git = Join-Path $Root 'Git with spaces/git.exe'
[IO.Directory]::CreateDirectory((Split-Path -Parent $git)) | Out-Null
Copy-Item -LiteralPath $NativeGit -Destination $git
$env:MEP_CHECK_CASE = $Case
[IO.File]::WriteAllText($git, @'
#!/bin/sh
if [ "$MEP_CHECK_CASE" = auth ] && [ "$1" = ls-remote ]; then
    echo 'credential secret that must never appear in reports' >&2
    exit 1
fi
if [ "$1" = --version ]; then echo 'git version 2.47.0'; exit 0; fi
if [ "$1" = remote ]; then echo 'https://github.com/owenmerkel76-maker/MEPTOOL.git'; exit 0; fi
if [ "$1" = status ]; then exit 0; fi
if [ "$1" = ls-remote ]; then printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa	refs/heads/main
'; exit 0; fi
exit 1
'@ + "`n")
[IO.Directory]::CreateDirectory((Join-Path $work 'repository/.git')) | Out-Null
$settings = @{ scheduled_updates = $true; git_path = $git }
[IO.File]::WriteAllText((Join-Path $work 'settings.json'), ($settings | ConvertTo-Json))
$expectedName = 'ROBMEPTOOLS Auto Update ' + $id
function global:Get-ScheduledTask {
    [CmdletBinding()]param($TaskName, $TaskPath)
    if ($Case -like 'com-*') { throw 'The system cannot find the file specified.' }
    if ($Case -in @('missing-task', 'repair', 'repair-failed') -and
        -not (Test-Path -LiteralPath (Join-Path $env:USERPROFILE 'task-registered.txt'))) {
        if ($TaskName) { throw 'The system cannot find the file specified.' }
        return
    }
    if ($Case -eq 'lookup-fallback' -and $TaskName) { throw 'The system cannot find the file specified.' }
    $runner = Join-Path $extension 'updater/Update-Background.ps1'
    $argsText = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -ExtensionRoot "{1}"' -f $runner, $extension
    if ($Case -eq 'wrong-folder') { $argsText = 'different installation' }
    [PSCustomObject]@{
        TaskName = $expectedName
        TaskPath = if ($Case -eq 'lookup-fallback') { '\Custom\' } else { [string][char]92 }
        Settings = @{ Enabled = $true }; State = 'Ready'
        Actions = @(@{ Execute = 'powershell.exe'; Arguments = $argsText })
        Triggers = @(@{ Repetition = @{ Interval = 'PT15M' } }, @{ CimClass = @{ CimClassName = 'MSFT_TaskLogonTrigger' } })
        Principal = @{ LogonType = 'Interactive'; RunLevel = 'Limited' }
    }
}
function global:Get-Process {
    [CmdletBinding()]param($Name, $Id)
    if ($Case -eq 'revit-open' -and $Name -eq 'Revit') { [PSCustomObject]@{ Id = 123 } }
}
function global:Start-ScheduledTask {
    [CmdletBinding()]param($InputObject)
    if ($InputObject.TaskName -ne $expectedName -or
        ($Case -eq 'lookup-fallback' -and $InputObject.TaskPath -ne '\Custom\')) { throw 'The checker started a different task or lost its registered location.' }
    [IO.File]::WriteAllText((Join-Path $env:USERPROFILE 'task-started.txt'), 'started')
    if ($Case -eq 'timeout') { return }
    $status = @{ schema = 1; extension_root = $extension; started_utc = [DateTime]::UtcNow.ToString('o');
        status = 'success'; commit = ('a' * 40); changed_files = 0;
        manifest_sha256 = (Get-ManagedHash (Join-Path $extension 'update-manifest.json')) }
    if ($Case -eq 'failed-update') { $status.status = 'failed'; $status.message = 'GitHub could not be read; installed tool kept.' }
    if ($Case -eq 'bad-proof') { $status.manifest_sha256 = 'wrong manifest' }
    if ($Case -eq 'stale') { $status.started_utc = [DateTime]::UtcNow.AddDays(-1).ToString('o') }
    [IO.File]::WriteAllText((Join-Path $work 'last-check.json'), ($status | ConvertTo-Json))
}
if ($Case -eq 'changed-file') { [IO.File]::WriteAllText($engine, 'local edit') }
$report = Join-Path $Root 'report.txt'
function global:New-ScheduledTaskAction { param($Execute, $Argument) return @{} }
function global:New-ScheduledTaskTrigger { param([switch]$Once, $At, $RepetitionInterval, [switch]$AtLogOn, $User) return @{} }
function global:New-ScheduledTaskPrincipal { param($UserId, $LogonType, $RunLevel) return @{} }
function global:New-ScheduledTaskSettingsSet { param([switch]$StartWhenAvailable, $MultipleInstances, $ExecutionTimeLimit,
    [switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries) return @{} }
function global:Register-ScheduledTask {
    [CmdletBinding()]param($TaskName, $TaskPath, $Action, $Trigger, $Principal, $Settings, $Description, [switch]$Force)
    if ($Case -in @('repair-failed', 'com-repair')) { throw 'PowerShell task registration failed.' }
    if ($TaskName -ne $expectedName -or $TaskPath -ne [string][char]92) { throw 'Repair used the wrong task name or root folder.' }
    [IO.File]::WriteAllText((Join-Path $env:USERPROFILE 'task-registered.txt'), 'registered')
}
if ($Case -like 'com-*') {
    $global:mepFixtureCase = $Case
    $global:mepFixtureName = $expectedName
    function New-FixtureDefinition {
        $actions = New-Object Collections.ArrayList
        Add-Member -InputObject $actions -MemberType ScriptMethod -Name Create -Value {
            param($Type)
            $entry = [PSCustomObject]@{ Type = $Type; Path = ''; Arguments = '' }
            $null = $this.Add($entry)
            return $entry
        }
        $triggers = New-Object Collections.ArrayList
        Add-Member -InputObject $triggers -MemberType ScriptMethod -Name Create -Value {
            param($Type)
            $entry = [PSCustomObject]@{ Type = $Type; Enabled = $false; StartBoundary = ''; UserId = ''; Repetition = [PSCustomObject]@{ Interval = '' } }
            $null = $this.Add($entry)
            return $entry
        }
        return [PSCustomObject]@{
            RegistrationInfo = [PSCustomObject]@{ Description = '' }
            Principal = [PSCustomObject]@{ UserId = ''; LogonType = 3; RunLevel = 0 }
            Settings = [PSCustomObject]@{ Enabled = $true; StartWhenAvailable = $false; MultipleInstances = 0; ExecutionTimeLimit = ''; DisallowStartIfOnBatteries = $true; StopIfGoingOnBatteries = $true }
            Actions = $actions; Triggers = $triggers
        }
    }
    $definition = New-FixtureDefinition
    $action = $definition.Actions.Create(0)
    $action.Path = 'powershell.exe'
    $runner = Join-Path $extension 'updater/Update-Background.ps1'
    $action.Arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -ExtensionRoot "{1}"' -f $runner, $extension
    if ($Case -eq 'com-wrong-folder') { $action.Arguments = 'a different tool folder' }
    $timer = $definition.Triggers.Create(1)
    $timer.Repetition.Interval = 'PT15M'
    $null = $definition.Triggers.Create(9)
    $global:mepFixtureComTask = [PSCustomObject]@{
        Name = $expectedName; Path = ([string][char]92 + $expectedName); State = 3; Enabled = $true; Definition = $definition
    }
    if ($Case -eq 'com-disabled') { $global:mepFixtureComTask.Enabled = $false; $global:mepFixtureComTask.State = 1 }
    Add-Member -InputObject $global:mepFixtureComTask -MemberType ScriptMethod -Name Run -Value {
        param($Parameters)
        Start-ScheduledTask -InputObject ([PSCustomObject]@{ TaskName = $this.Name; TaskPath = [string][char]92 })
    }
    $folder = [PSCustomObject]@{}
    Add-Member -InputObject $folder -MemberType ScriptMethod -Name GetTask -Value {
        param($Name)
        if ($Name -ne $global:mepFixtureName) { throw 'Unexpected COM task name.' }
        if ($global:mepFixtureCase -eq 'com-repair' -and -not (Test-Path (Join-Path $env:USERPROFILE 'task-registered.txt'))) {
            throw (New-Object Runtime.InteropServices.COMException('Task not found', -2147024894))
        }
        return $global:mepFixtureComTask
    }
    Add-Member -InputObject $folder -MemberType ScriptMethod -Name RegisterTaskDefinition -Value {
        param($Name, $Definition, $Flags, $User, $Password, $Logon, $Security)
        if ($Name -ne $global:mepFixtureName -or $Flags -ne 6 -or $Logon -ne 3 -or $null -ne $Password) { throw 'Unsafe COM registration parameters.' }
        if ($Definition.Principal.RunLevel -ne 0 -or $Definition.Settings.MultipleInstances -ne 2) { throw 'COM task privileges or concurrency policy changed.' }
        if ($Definition.Settings.DisallowStartIfOnBatteries -or $Definition.Settings.StopIfGoingOnBatteries) { throw 'Battery settings changed.' }
        $global:mepFixtureComTask.Definition = $Definition
        [IO.File]::WriteAllText((Join-Path $env:USERPROFILE 'task-registered.txt'), 'registered')
        return $global:mepFixtureComTask
    }
    $global:mepFixtureFolder = $folder
    $global:mepFixtureService = [PSCustomObject]@{}
    Add-Member -InputObject $global:mepFixtureService -MemberType ScriptMethod -Name Connect -Value {}
    Add-Member -InputObject $global:mepFixtureService -MemberType ScriptMethod -Name GetFolder -Value {
        param($Path)
        if ($Path -ne [string][char]92) { throw 'COM query used the wrong task root.' }
        return $global:mepFixtureFolder
    }
    Add-Member -InputObject $global:mepFixtureService -MemberType ScriptMethod -Name NewTask -Value { param($Flags) return (New-FixtureDefinition) }
    function global:New-Object {
        [CmdletBinding()]param([Parameter(Position=0)][string]$TypeName, [Parameter(Position=1)][object[]]$ArgumentList, [string]$ComObject)
        if ($ComObject -eq 'Schedule.Service') {
            if ($global:mepFixtureCase -eq 'com-unavailable') { throw 'The Task Scheduler service could not be connected.' }
            return $global:mepFixtureService
        }
        Microsoft.PowerShell.Utility\New-Object @PSBoundParameters
    }
}
if ($Case -in @('repair', 'repair-failed', 'com-repair')) {
    # Substitute only the Windows identity API; retain real registration logic.
    $package = Join-Path $Root 'package'
    [IO.Directory]::CreateDirectory($package) | Out-Null
    Copy-Item -LiteralPath (Join-Path $repository 'installer') -Destination $package -Recurse
    Copy-Item -LiteralPath (Join-Path $repository 'ROBMEPTOOLS.extension') -Destination $package -Recurse
    $modulePath = Join-Path $package 'installer/Scheduled-Task.psm1'
    $source = [IO.File]::ReadAllText($modulePath).Replace('[Security.Principal.WindowsIdentity]::GetCurrent().Name', "'test-user'")
    [IO.File]::WriteAllText($modulePath, $source)
    & (Join-Path $package 'installer/Check-Updater.ps1') -ExtensionDirectory $extension -ReportPath $report -RepairTask -RunUpdate -WaitSeconds 1
} else {
    & (Join-Path $repository 'installer/Check-Updater.ps1') -ExtensionDirectory $extension -ReportPath $report -RunUpdate -WaitSeconds 1
}
$exitCode = $LASTEXITCODE
function Assert($condition, [string]$message) { if (-not $condition) { throw $message } }
$text = Get-Content -LiteralPath $report -Raw
$taskStarted = Test-Path -LiteralPath (Join-Path $env:USERPROFILE 'task-started.txt')
if ($Case -in @('success', 'repair', 'lookup-fallback', 'com-read', 'com-repair')) {
    Assert ($exitCode -eq 0 -and $text -like '*ALL CHECKS PASSED*' -and $taskStarted) 'Successful check did not verify the actual task.'
} else {
    Assert ($exitCode -eq 1 -and $text -like '*NOT YET VERIFIED*' -and $text -notlike '*ALL CHECKS PASSED*') "Incorrect success claim for $Case"
}
if ($Case -in @('repair', 'com-repair')) { Assert (Test-Path -LiteralPath (Join-Path $env:USERPROFILE 'task-registered.txt')) 'Missing task was not repaired.' }
if ($Case -in @('com-read', 'com-repair')) { Assert ($text -like '*Windows COM interface*') 'The checker did not use the alternate Windows interface.' }
if ($Case -in @('auth', 'missing-task', 'wrong-folder', 'changed-file', 'revit-open', 'com-unavailable', 'com-wrong-folder', 'com-disabled')) {
    Assert (-not $taskStarted) "Scheduled update ran despite $Case"
}
Assert ($text -notlike '*credential secret*') 'Credential helper output leaked into the report.'
Write-Output "PASS: checker $Case"
