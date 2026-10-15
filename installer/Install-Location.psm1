function Test-ToolExtension([string]$Path) {
    return (Test-Path -LiteralPath (Join-Path $Path 'ROBMEPTOOLS.tab') -PathType Container)
}

function Get-ToolExtensionCandidates([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { return }
    if (Test-ToolExtension $Path) { $Path; return }
    foreach ($folder in Get-ChildItem -LiteralPath $Path -Directory) {
        if (Test-ToolExtension $folder.FullName) { $folder.FullName }
        elseif ($folder.Name -notlike '*.extension') {
            foreach ($child in Get-ChildItem -LiteralPath $folder.FullName -Directory) {
                if (Test-ToolExtension $child.FullName) { $child.FullName }
            }
        }
    }
}

function Resolve-ToolInstallLocation([string]$Path) {
    $Path = [IO.Path]::GetFullPath($Path)
    if ((Test-Path -LiteralPath $Path) -and -not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "Select a folder, not a file: $Path"
    }
    $candidates = @(Get-ToolExtensionCandidates $Path)
    if ($candidates.Count -gt 1) { throw 'More than one ROBMEPTOOLS extension was found. Select the specific extension folder Revit loads.' }
    if ($candidates.Count -eq 1) {
        return [PSCustomObject]@{ ExtensionDirectory = $candidates[0]; FreshInstall = $false }
    }
    $target = if ((Split-Path -Leaf $Path) -like '*.extension') { $Path }
              else { Join-Path $Path 'ROBMEPTOOLS.extension' }
    if (Test-Path -LiteralPath $target) {
        $item = Get-Item -LiteralPath $target -Force
        if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Installation target is a file, link or junction: $target"
        }
        if (@(Get-ChildItem -LiteralPath $target -Force).Count) {
            throw "Installation target contains unrecognized files; they were left unchanged: $target"
        }
    }
    return [PSCustomObject]@{ ExtensionDirectory = $target; FreshInstall = $true }
}

function Get-ToolInstallFiles($Manifest, [bool]$FreshInstall) {
    if ($FreshInstall) {
        $Manifest.files.PSObject.Properties.Name
        'update-manifest.json'
    } else { $Manifest.bootstrap_files }
}

Export-ModuleMember -Function Test-ToolExtension, Get-ToolExtensionCandidates, Resolve-ToolInstallLocation, Get-ToolInstallFiles
