function Get-DesktopGitRoots([string]$Path) {
    if (-not $Path) { return }
    if ((Split-Path -Leaf $Path) -ieq 'GitHubDesktop.exe') { $Path = Split-Path -Parent $Path }
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { return }
    Join-Path $Path 'resources/app/git'
    foreach ($version in Get-ChildItem -LiteralPath $Path -Directory -Filter 'app-*' |
        Sort-Object LastWriteTime -Descending) {
        Join-Path $version.FullName 'resources/app/git'
    }
}

function Resolve-ToolGitPath([string]$Path) {
    if (-not $Path) { return }
    $roots = @($Path) + @(Get-DesktopGitRoots $Path)
    foreach ($root in $roots) {
        foreach ($candidate in @($root, (Join-Path $root 'cmd/git.exe'), (Join-Path $root 'bin/git.exe'))) {
            if ((Split-Path -Leaf $candidate) -ieq 'git.exe' -and
                (Test-Path -LiteralPath $candidate -PathType Leaf)) {
                return [IO.Path]::GetFullPath($candidate)
            }
        }
    }
}

function Get-ToolGitDiskRoots {
    foreach ($drive in [IO.DriveInfo]::GetDrives()) {
        if ($drive.IsReady -and $drive.DriveType -eq [IO.DriveType]::Fixed) { $drive.RootDirectory.FullName }
    }
}

function Get-ToolGitInstallRoots {
    foreach ($key in @('HKCU:\Software\GitForWindows', 'HKLM:\Software\GitForWindows',
                       'HKLM:\Software\WOW6432Node\GitForWindows')) {
        $entry = Get-ItemProperty -LiteralPath $key -ErrorAction SilentlyContinue
        if ($entry.InstallPath) { $entry.InstallPath }
    }
    foreach ($key in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Git_is1',
                       'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Git_is1',
                       'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Git_is1')) {
        $entry = Get-ItemProperty -LiteralPath $key -ErrorAction SilentlyContinue
        if ($entry.InstallLocation) { $entry.InstallLocation }
    }
    foreach ($parent in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
        if ($parent) {
            Join-Path $parent 'Git'
            Join-Path $parent 'Programs/Git'
            Join-Path $parent 'GitHubDesktop'
        }
    }
    # Include standard installations on other local disks without recursively
    # scanning the disk or touching disconnected network drives.
    foreach ($diskRoot in Get-ToolGitDiskRoots) {
        foreach ($relative in @('Git', 'Program Files/Git', 'Program Files (x86)/Git', 'Programs/Git')) {
            Join-Path $diskRoot $relative
        }
    }
}

function Find-ToolGit([string]$ExplicitPath = '') {
    if ($ExplicitPath) {
        $resolved = Resolve-ToolGitPath $ExplicitPath
        if (-not $resolved) { throw "Git was not found at: $ExplicitPath. Select git.exe inside Git\cmd, or the GitHub Desktop installation containing its bundled Git." }
        return $resolved
    }
    $command = Get-Command git.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { return $command.Source }
    foreach ($root in Get-ToolGitInstallRoots) {
        $resolved = Resolve-ToolGitPath $root
        if ($resolved) { return $resolved }
    }
}

Export-ModuleMember -Function Resolve-ToolGitPath, Find-ToolGit
