$ErrorActionPreference = 'Stop'

function Get-ManagedHash([string]$Path) {
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-ManagedPath([string]$Root, [string]$Relative) {
    $parts = $Relative.Split('/')
    if (-not $Relative -or $Relative -match '[\\:\x00-\x1f]' -or $Relative.StartsWith('/') -or
        ($parts | Where-Object { $_ -eq '' -or $_ -eq '.' -or $_ -eq '..' -or
            $_.TrimEnd(' ', '.') -ne $_ -or $_ -match '^(?i:con|prn|aux|nul|clock\$|com[1-9]|lpt[1-9])(?:\.|$)' -or
            $_ -in @('.git', '__pycache__') })) { throw "Unsafe managed path: $Relative" }
    $path = $Root
    foreach ($part in $parts) {
        $path = Join-Path $path $part
        if ((Test-Path -LiteralPath $path) -and
            ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Managed path is a link or junction: $Relative"
        }
    }
    $path
}

function Copy-ManagedAtomic([string]$Source, [string]$Destination) {
    $parent = Split-Path -Parent $Destination
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $temporary = Join-Path $parent ('.robmep-' + [Guid]::NewGuid().ToString('N'))
    try {
        [IO.File]::Copy($Source, $temporary, $false)
        if (Test-Path -LiteralPath $Destination) { [IO.File]::Replace($temporary, $Destination, [NullString]::Value) }
        else { [IO.File]::Move($temporary, $Destination) }
    } finally {
        if (Test-Path -LiteralPath $temporary) { [IO.File]::Delete($temporary) }
    }
}

function Write-ManagedJson([string]$Path, $Value) {
    $parent = Split-Path -Parent $Path
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $temporary = Join-Path $parent ('.robmep-' + [Guid]::NewGuid().ToString('N'))
    try {
        $encoding = New-Object Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 20), $encoding)
        if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($temporary, $Path, [NullString]::Value) }
        else { [IO.File]::Move($temporary, $Path) }
    } finally {
        if (Test-Path -LiteralPath $temporary) { [IO.File]::Delete($temporary) }
    }
}

function Invoke-ManagedUpdate {
    param([string]$ExtensionRoot, [string]$PayloadRoot, [string]$WorkDirectory,
          [scriptblock]$BeforeWrite = {})
    $ExtensionRoot = [IO.Path]::GetFullPath($ExtensionRoot)
    $manifestPath = Get-ManagedPath $PayloadRoot 'update-manifest.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $properties = @($manifest.files.PSObject.Properties)
    if ($manifest.schema -ne 1 -or $properties.Count -eq 0 -or $properties.Count -gt 500 -or $manifest.restart_required) {
        throw 'Unsupported manifest or release requiring a closed-Revit manual installation.'
    }
    $wanted = @{}
    foreach ($property in $properties) {
        $relative = $property.Name
        if ($relative -eq 'update-manifest.json' -or $wanted.ContainsKey($relative) -or
            $property.Value -cnotmatch '^[0-9a-f]{64}$' -or $relative -match '\.(dll|exe|pyd)$') {
            throw "Invalid checksum/path or compiled update: $relative"
        }
        $source = Get-ManagedPath $PayloadRoot $relative
        if (-not (Test-Path -LiteralPath $source -PathType Leaf) -or (Get-ManagedHash $source) -ne $property.Value) {
            throw "Source checksum mismatch: $relative"
        }
        $wanted[$relative] = $property.Value
    }
    $wanted['update-manifest.json'] = Get-ManagedHash $manifestPath
    $statePath = Join-Path $WorkDirectory 'installed-state.json'
    $state = if (Test-Path -LiteralPath $statePath) { Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json } else { $null }
    if ($state -and $state.extension_root -ne $ExtensionRoot) { throw 'Update state belongs to another installed folder.' }
    $oldFiles = @{}
    if ($state) { foreach ($property in $state.files.PSObject.Properties) { $oldFiles[$property.Name] = $property.Value } }
    $operations = @()
    foreach ($relative in ($wanted.Keys | Sort-Object)) {
        $destination = Get-ManagedPath $ExtensionRoot $relative
        if (Test-Path -LiteralPath $destination -PathType Container) { throw "Expected a file, found a folder: $relative" }
        $actual = if (Test-Path -LiteralPath $destination -PathType Leaf) { Get-ManagedHash $destination } else { $null }
        if ($actual -eq $wanted[$relative]) { continue }
        if ($null -ne $actual) {
            $known = if ($oldFiles.ContainsKey($relative)) { @($oldFiles[$relative]) }
                     elseif ($manifest.previous_hashes.PSObject.Properties[$relative]) { @($manifest.previous_hashes.PSObject.Properties[$relative].Value) }
                     else { @() }
            if ($actual -notin $known) { throw "Local edits preserved; update stopped at: $relative" }
        }
        $operations += [PSCustomObject]@{ relative = $relative; action = 'copy'; old_hash = $actual }
    }
    foreach ($relative in ($oldFiles.Keys | Sort-Object)) {
        if ($wanted.ContainsKey($relative)) { continue }
        $destination = Get-ManagedPath $ExtensionRoot $relative
        if (Test-Path -LiteralPath $destination) {
            if (-not (Test-Path -LiteralPath $destination -PathType Leaf) -or (Get-ManagedHash $destination) -ne $oldFiles[$relative]) {
                throw "Locally edited obsolete file preserved: $relative"
            }
            $operations += [PSCustomObject]@{ relative = $relative; action = 'remove'; old_hash = $oldFiles[$relative] }
        }
    }
    & $BeforeWrite
    $backup = $null
    if ($operations.Count) {
        $backup = Join-Path $WorkDirectory ('backups\' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ-') + [Guid]::NewGuid().ToString('N'))
        [IO.Directory]::CreateDirectory($backup) | Out-Null
        Write-ManagedJson (Join-Path $backup 'restore.json') @{ extension_root = $ExtensionRoot; operations = $operations; previous_state = $state }
        foreach ($item in $operations) {
            if ($null -ne $item.old_hash) {
                $destination = Get-ManagedPath $backup $item.relative
                [IO.Directory]::CreateDirectory((Split-Path -Parent $destination)) | Out-Null
                [IO.File]::Copy((Get-ManagedPath $ExtensionRoot $item.relative), $destination, $false)
            }
        }
    }
    $applied = @()
    try {
        foreach ($item in $operations) {
            & $BeforeWrite
            $destination = Get-ManagedPath $ExtensionRoot $item.relative
            $actual = if (Test-Path -LiteralPath $destination -PathType Leaf) { Get-ManagedHash $destination } else { $null }
            if ($actual -ne $item.old_hash) { throw "File changed during update; preserving: $($item.relative)" }
            $applied += $item
            if ($item.action -eq 'copy') {
                Copy-ManagedAtomic (Get-ManagedPath $PayloadRoot $item.relative) $destination
                if ((Get-ManagedHash $destination) -ne $wanted[$item.relative]) { throw "Installed checksum mismatch: $($item.relative)" }
            } else { [IO.File]::Delete($destination) }
        }
        & $BeforeWrite
        Write-ManagedJson $statePath @{ schema = 1; extension_root = $ExtensionRoot; files = $wanted; build = $manifest.build }
    } catch {
        $failure = $_
        $rollbackErrors = @()
        [array]::Reverse($applied)
        foreach ($item in $applied) {
            try {
                $destination = Get-ManagedPath $ExtensionRoot $item.relative
                if ($null -ne $item.old_hash) { Copy-ManagedAtomic (Get-ManagedPath $backup $item.relative) $destination }
                elseif (Test-Path -LiteralPath $destination) { [IO.File]::Delete($destination) }
            } catch { $rollbackErrors += $item.relative }
        }
        if ($rollbackErrors.Count) { throw "Rollback incomplete for $($rollbackErrors -join ', '). Backup: $backup" }
        throw $failure
    }
    [PSCustomObject]@{ changed = [bool]$operations.Count; file_count = $operations.Count; backup = $backup; build = $manifest.build }
}

Export-ModuleMember -Function Get-ManagedHash, Get-ManagedPath, Invoke-ManagedUpdate
