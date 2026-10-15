param([Parameter(Mandatory = $true)][string]$ExtensionRoot)
$ErrorActionPreference = 'Stop'
$ExtensionRoot = [IO.Path]::GetFullPath($ExtensionRoot).TrimEnd('\')
$normalized = $ExtensionRoot.Replace('\', '/').TrimEnd('/').ToLowerInvariant()
$sha = [Security.Cryptography.SHA256]::Create()
try { $digest = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalized)) }
finally { $sha.Dispose() }
$installId = ([BitConverter]::ToString($digest).Replace('-', '').ToLowerInvariant()).Substring(0, 16)
$work = Join-Path $env:LOCALAPPDATA "ROBMEPTOOLS\updates\$installId"
[IO.Directory]::CreateDirectory($work) | Out-Null
$lock = $null
$lockPath = Join-Path $work 'update.lock'
$startedUtc = [DateTime]::UtcNow.ToString('o')
$exitCode = 0
$checkResult = @{ schema = 1; extension_root = $ExtensionRoot; started_utc = $startedUtc }

function Write-CheckResult {
    $script:checkResult.completed_utc = [DateTime]::UtcNow.ToString('o')
    $path = Join-Path $work 'last-check.json'
    $temporary = Join-Path $work ('check-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [IO.File]::WriteAllText($temporary, ($script:checkResult | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding($false)))
        if (Test-Path -LiteralPath $path) { [IO.File]::Replace($temporary, $path, [NullString]::Value) }
        else { [IO.File]::Move($temporary, $path) }
    } finally {
        if (Test-Path -LiteralPath $temporary) { [IO.File]::Delete($temporary) }
    }
}

function Write-UpdateLog([string]$Message) {
    $log = Join-Path $work 'updates.log'
    if ((Test-Path -LiteralPath $log) -and (Get-Item -LiteralPath $log).Length -gt 262144) {
        Move-Item -LiteralPath $log -Destination ($log + '.previous') -Force
    }
    Add-Content -LiteralPath $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $Message)
}

function Assert-RevitClosed {
    if (Get-Process -Name Revit -ErrorAction SilentlyContinue) {
        throw 'Revit is open; update deferred until a later check.'
    }
}

function Invoke-BackgroundGit([string[]]$Arguments) {
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $script:settings.git_path
    # These fixed arguments contain no paths, spaces, secrets or shell code.
    $info.Arguments = $Arguments -join ' '
    $info.WorkingDirectory = $script:cache
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.EnvironmentVariables['GIT_TERMINAL_PROMPT'] = '0'
    $info.EnvironmentVariables['GCM_INTERACTIVE'] = 'Never'
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $info
    try {
        $process.Start() | Out-Null
        $output = $process.StandardOutput.ReadToEndAsync()
        $errorOutput = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(30000)) {
            $process.Kill()
            throw 'GitHub update timed out; installed tool kept.'
        }
        $text = $output.Result.Trim()
        $null = $errorOutput.Result
        if ($process.ExitCode -ne 0) { throw 'GitHub could not be read; installed tool kept. Rerun Setup Auto Updates.cmd to check sign-in.' }
        $text
    } finally { $process.Dispose() }
}

try {
    Assert-RevitClosed
    if (-not (Test-Path -LiteralPath (Join-Path $ExtensionRoot 'ROBMEPTOOLS.tab') -PathType Container)) { throw 'Configured extension folder was not found.' }
    $script:settings = Get-Content -LiteralPath (Join-Path $work 'settings.json') -Raw | ConvertFrom-Json
    if ($settings.scheduled_updates -eq $false) { throw 'Scheduled updates are disabled in the tool settings.' }
    if (-not $settings.git_path -or -not (Test-Path -LiteralPath $settings.git_path -PathType Leaf)) {
        # GitHub Desktop replaces its versioned app directory when it updates.
        Import-Module (Join-Path $PSScriptRoot 'Git-Location.psm1') -Force
        $currentGit = Find-ToolGit
        if (-not $currentGit) { throw 'Git executable was not found. Rerun Setup Auto Updates.cmd to select its current location.' }
        $script:settings | Add-Member -NotePropertyName git_path -NotePropertyValue $currentGit -Force
    }
    # Recover only a lock left by a process which no longer exists.
    if (Test-Path -LiteralPath $lockPath) {
        $owner = [IO.File]::ReadAllText($lockPath).Trim()
        if ($owner -notmatch '^\d+$' -or (Get-Process -Id ([int]$owner) -ErrorAction SilentlyContinue)) {
            throw 'Another updater is running or the lock needs inspection.'
        }
        [IO.File]::Delete($lockPath)
    }
    $lock = [IO.File]::Open($lockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    $bytes = [Text.Encoding]::ASCII.GetBytes([string]$PID)
    $lock.Write($bytes, 0, $bytes.Length)
    $lock.Flush()
    $script:cache = Join-Path $work 'repository'
    if (-not (Test-Path -LiteralPath (Join-Path $cache '.git') -PathType Container)) { throw 'Updater setup has not completed.' }
    $origin = Invoke-BackgroundGit @('remote', 'get-url', 'origin')
    if ($origin.TrimEnd('/') -ne 'https://github.com/owenmerkel76-maker/MEPTOOL.git') { throw 'Unexpected updater repository; installed tool kept.' }
    if (Invoke-BackgroundGit @('status', '--porcelain')) { throw 'Updater cache contains local edits; installed tool kept.' }
    $null = Invoke-BackgroundGit @('fetch', '--filter=blob:none', 'origin', 'main')
    $commit = Invoke-BackgroundGit @('rev-parse', '--verify', 'FETCH_HEAD^{commit}')
    if ($commit -cnotmatch '^[0-9a-f]{40}$') { throw 'Invalid GitHub revision; installed tool kept.' }
    $null = Invoke-BackgroundGit @('checkout', '--detach', $commit)
    $payload = Join-Path $cache 'ROBMEPTOOLS.extension'
    Import-Module (Join-Path $PSScriptRoot 'Update-Core.psm1') -Force
    $result = Invoke-ManagedUpdate -ExtensionRoot $ExtensionRoot -PayloadRoot $payload -WorkDirectory $work -BeforeWrite { Assert-RevitClosed }
    Write-UpdateLog "Build: $($result.build); changed files: $($result.file_count); backup: $($result.backup)"
    $checkResult.status = 'success'
    $checkResult.commit = $commit
    $checkResult.build = $result.build
    $checkResult.changed_files = $result.file_count
    $checkResult.manifest_sha256 = (Get-FileHash -LiteralPath (Join-Path $ExtensionRoot 'update-manifest.json') -Algorithm SHA256).Hash.ToLowerInvariant()
} catch {
    Write-UpdateLog $_.Exception.Message
    $checkResult.message = $_.Exception.Message
    if ($checkResult.message -eq 'Revit is open; update deferred until a later check.') { $checkResult.status = 'deferred' }
    elseif ($checkResult.message -eq 'Scheduled updates are disabled in the tool settings.') { $checkResult.status = 'disabled' }
    else { $checkResult.status = 'failed'; $exitCode = 1 }
} finally {
    if ($lock) {
        $lock.Dispose()
        [IO.File]::Delete($lockPath)
    }
    try { Write-CheckResult }
    catch { Write-UpdateLog 'Could not write the update check result.'; $exitCode = 1 }
}
exit $exitCode
