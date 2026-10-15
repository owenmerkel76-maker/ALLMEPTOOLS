param([string]$ExtensionDirectory = '', [switch]$RunUpdate, [switch]$RepairTask, [string]$ReportPath = '', [int]$WaitSeconds = 90)
$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot
$payloadRoot = Join-Path $packageRoot 'ROBMEPTOOLS.extension'
Import-Module (Join-Path $PSScriptRoot 'Install-Location.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'Scheduled-Task.psm1') -Force
Import-Module (Join-Path $payloadRoot 'updater/Git-Location.psm1') -Force
Import-Module (Join-Path $payloadRoot 'updater/Update-Core.psm1') -Force
$script:checks = @()
if (-not $ExtensionDirectory) { $ExtensionDirectory = Join-Path $env:USERPROFILE 'Desktop/PY REVIT' }
if (-not $ReportPath) { $ReportPath = Join-Path $env:USERPROFILE 'Desktop/MEPTOOLS-update-check.txt' }

function Record([string]$Status, [string]$Name, [string]$Detail) {
    $script:checks += [PSCustomObject]@{ Status = $Status; Name = $Name; Detail = $Detail }
    $color = if ($Status -eq 'PASS') { 'Green' } elseif ($Status -eq 'FAIL') { 'Red' } else { 'Yellow' }
    Write-Host "$Status - ${Name}: $Detail" -ForegroundColor $color
}

function Check-Git([string]$Executable, [string]$Arguments, [string]$Directory) {
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $Executable
    $info.Arguments = $Arguments
    $info.WorkingDirectory = $Directory
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.EnvironmentVariables['GIT_TERMINAL_PROMPT'] = '0'
    $info.EnvironmentVariables['GCM_INTERACTIVE'] = 'Never'
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $info
    try {
        $null = $process.Start()
        $output = $process.StandardOutput.ReadToEndAsync()
        $errors = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(30000)) {
            $process.Kill()
            throw 'Git timed out. Check your network connection and Git sign-in.'
        }
        $null = $errors.Result  # Never include credential-helper output in the report.
        if ($process.ExitCode -ne 0) { throw 'Command-line Git could not read this repository without prompting. GitHub Desktop sign-in alone may not provide these credentials. Rerun setup to check GitHub access.' }
        return $output.Result.Trim()
    } finally { $process.Dispose() }
}

function Check-InstalledFiles([string]$Root) {
    $manifestPath = Join-Path $Root 'update-manifest.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.schema -ne 1 -or -not $manifest.files.PSObject.Properties.Name.Count) { throw 'Installed manifest is missing or unsupported.' }
    $required = 'ROBMEPTOOLS.tab/Annotation.panel/AutoDim Smart.pushbutton/engines/duct_engine.py'
    if (-not $manifest.files.PSObject.Properties[$required]) { throw 'The installed manifest does not include Duct AutoDim.' }
    foreach ($file in $manifest.files.PSObject.Properties) {
        $path = Get-ManagedPath $Root $file.Name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or (Get-ManagedHash $path) -ne $file.Value) {
            throw "Missing or changed tool file: $($file.Name). Rerun setup; preserve any local edits."
        }
    }
    return $manifest.files.PSObject.Properties.Name.Count
}

$root = $null
$work = $null
$taskName = $null
$git = $null
$settings = $null
try {
    $location = Resolve-ToolInstallLocation $ExtensionDirectory
    if ($location.FreshInstall) { throw 'The tool is not installed. Run Setup Auto Updates.cmd first.' }
    $root = $location.ExtensionDirectory
    $count = Check-InstalledFiles $root
    Record PASS 'Installed tool' "$root; $count file checksums verified"
    $normalized = $root.Replace('\', '/').TrimEnd('/').ToLowerInvariant()
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $digest = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalized)) } finally { $sha.Dispose() }
    $id = ([BitConverter]::ToString($digest).Replace('-', '').ToLowerInvariant()).Substring(0, 16)
    $work = Join-Path $env:LOCALAPPDATA "ROBMEPTOOLS/updates/$id"
    $taskName = 'ROBMEPTOOLS Auto Update ' + $id
    $settings = Get-Content -LiteralPath (Join-Path $work 'settings.json') -Raw | ConvertFrom-Json
    if ($settings.scheduled_updates -eq $false) { throw 'Scheduled updates are disabled. Rerun setup or enable scheduled updates in the Update Tool button settings.' }
    Record PASS 'Update settings' 'Scheduled updates enabled'
} catch { Record FAIL 'Installed tool / settings' $_.Exception.Message }

try {
    if ($settings.git_path -and (Test-Path -LiteralPath $settings.git_path -PathType Leaf)) { $git = $settings.git_path }
    else { $git = Find-ToolGit }
    if (-not $git) { throw 'Git was not found. Rerun setup and select git.exe.' }
    $version = Check-Git $git '--version' $env:USERPROFILE
    if ($version -notmatch '^git version ') { throw 'The selected executable did not identify itself as Git.' }
    Record PASS 'Git executable' "$git ($version)"
    if (-not $work) { throw 'Install the tool before testing its updater cache.' }
    $cache = Join-Path $work 'repository'
    $origin = Check-Git $git 'remote get-url origin' $cache
    if ($origin -ne 'https://github.com/owenmerkel76-maker/MEPTOOL.git') { throw 'Unexpected updater repository. Rerun setup; the cache was left unchanged.' }
    if (Check-Git $git 'status --porcelain' $cache) { throw 'The updater cache has local edits. It was left unchanged.' }
    $head = Check-Git $git 'ls-remote --exit-code origin refs/heads/main' $cache
    if ($head -notmatch '^([0-9a-f]{40})\s+refs/heads/main$') { throw 'GitHub did not return the main branch.' }
    Record PASS 'GitHub access' ('Read main without prompts: ' + $Matches[1].Substring(0, 12))
} catch { Record FAIL 'Git / GitHub access' $_.Exception.Message }

try {
    if (-not $taskName) { throw 'Install the tool before checking the scheduled task.' }
    $task = Find-ToolUpdateTask $taskName
    if (-not $task -and $RepairTask) {
        if (@($script:checks | Where-Object Status -eq 'FAIL').Count) { throw 'Fix the installation or GitHub access failure before repairing the task.' }
        if (Get-Process -Name Revit -ErrorAction SilentlyContinue) { throw 'Close Revit and rerun this check to repair the task.' }
        Write-Host "Recreating missing Windows task: $taskName"
        $task = Register-ToolUpdateTask $taskName $root
    }
    if (-not $task) { throw "Task '$taskName' was not found. Run Check Auto Updates.cmd to repair it." }
    if (-not $task.Settings.Enabled -or $task.State -eq 'Disabled') { throw 'The scheduled update task is disabled.' }
    $runner = Join-Path $root 'updater/Update-Background.ps1'
    $expectedArgs = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -ExtensionRoot "{1}"' -f $runner, $root
    if (@($task.Actions).Count -ne 1 -or $task.Actions[0].Arguments -ne $expectedArgs -or
        (Split-Path -Leaf $task.Actions[0].Execute) -ine 'powershell.exe') { throw 'The task runs a different command or folder. Rerun setup.' }
    if (-not @($task.Triggers | Where-Object { $_.Repetition.Interval -eq 'PT15M' }).Count -or
        -not @($task.Triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' }).Count) { throw 'The task is missing its 15-minute timer or sign-in trigger. Rerun setup.' }
    if ($task.Principal.LogonType -ne 'Interactive' -or $task.Principal.RunLevel -ne 'Limited') { throw 'The task uses unexpected permissions. Rerun setup.' }
    $interface = if ($task.Backend -eq 'COM') { 'Windows COM interface' } else { 'PowerShell interface' }
    Record PASS 'Windows task' "$($task.TaskPath)$taskName; enabled, every 15 minutes and at sign-in; $interface"
} catch { Record FAIL 'Windows task' ("Expected '$taskName': " + $_.Exception.Message) }

if ($RunUpdate) {
    if (Get-Process -Name Revit -ErrorAction SilentlyContinue) {
        Record WAIT 'Actual scheduled update' 'Close Revit and run Check Auto Updates.cmd again.'
    } elseif ($task -and $task.State -eq 'Running') {
        Record WAIT 'Actual scheduled update' 'The scheduled update is already running. Let it finish, then run this check again.'
    } elseif (@($script:checks | Where-Object Status -eq 'FAIL').Count) {
        Record WAIT 'Actual scheduled update' 'Fix the failed checks above before running an update.'
    } else {
        try {
            Write-Host 'Running the actual scheduled update. This can take up to 90 seconds...'
            $requested = [DateTime]::UtcNow
            Start-ToolUpdateTask $task
            $deadline = [DateTime]::UtcNow.AddSeconds($WaitSeconds)
            $fresh = $null
            $resultPath = Join-Path $work 'last-check.json'
            do {
                if (Test-Path -LiteralPath $resultPath) {
                    $candidate = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
                    # PowerShell 7 decodes ISO dates as DateTime; converting
                    # them back to strings loses the fractional seconds.
                    $candidateStart = if ($candidate.started_utc -is [DateTime]) { $candidate.started_utc.ToUniversalTime() }
                                      else { [DateTime]::Parse($candidate.started_utc).ToUniversalTime() }
                    if ($candidate.schema -eq 1 -and $candidate.extension_root -eq $root -and
                        $candidateStart -ge $requested) { $fresh = $candidate }
                }
                if (-not $fresh) { Start-Sleep -Milliseconds 500 }
            } while (-not $fresh -and [DateTime]::UtcNow -lt $deadline)
            if (-not $fresh) { throw 'The scheduled task did not produce a new update result in time. Check Windows Task Scheduler and rerun setup.' }
            if ($fresh.status -eq 'deferred') { Record WAIT 'Actual scheduled update' 'Revit opened; update safely deferred. Close Revit and rerun this check.' }
            elseif ($fresh.status -ne 'success') { throw "Scheduled updater reported $($fresh.status): $($fresh.message)" }
            else {
                if ($fresh.commit -notmatch '^[0-9a-f]{40}$' -or
                    $fresh.manifest_sha256 -ne (Get-ManagedHash (Join-Path $root 'update-manifest.json'))) { throw 'The completed update result does not match the installed manifest.' }
                $null = Check-InstalledFiles $root
                Record PASS 'Actual scheduled update' "Completed and verified; commit $($fresh.commit.Substring(0, 12)); changed files: $($fresh.changed_files)"
            }
        } catch { Record FAIL 'Actual scheduled update' $_.Exception.Message }
    }
} else { Record WAIT 'Actual scheduled update' 'Not run. Use Check Auto Updates.cmd with Revit closed to verify the real task.' }

$complete = -not @($script:checks | Where-Object { $_.Status -ne 'PASS' }).Count
$summary = if ($complete) { 'ALL CHECKS PASSED - automatic updates worked on this PC.' } else { 'NOT YET VERIFIED - see failed or waiting checks below.' }
$lines = @('MEPTOOLS automatic-update check', ('Time: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')), $summary, '')
$lines += $script:checks | ForEach-Object { "$($_.Status) - $($_.Name): $($_.Detail)" }
$lines += @('', 'This verifies tool installation and updates. Open Revit to confirm the ROBMEPTOOLS ribbon; model dimension behavior is a separate check.')
try {
    [IO.Directory]::CreateDirectory((Split-Path -Parent ([IO.Path]::GetFullPath($ReportPath)))) | Out-Null
    [IO.File]::WriteAllLines($ReportPath, [string[]]$lines, (New-Object Text.UTF8Encoding($false)))
    Write-Host "`n$summary`nReport saved to: $ReportPath"
} catch { Write-Host "Could not save the report: $($_.Exception.Message)" -ForegroundColor Red; exit 1 }
if (-not $complete) { exit 1 }
exit 0
