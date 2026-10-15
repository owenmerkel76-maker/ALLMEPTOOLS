param([string]$Root, [string]$Case)
$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $repository 'installer/Install-Location.psm1') -Force
function Assert($condition, [string]$message) { if (-not $condition) { throw $message } }
$linked = Join-Path $Root 'Desktop/PY REVIT'
[IO.Directory]::CreateDirectory($linked) | Out-Null
$expected = Join-Path $linked 'ROBMEPTOOLS.extension'
switch ($Case) {
    'empty' {
        $location = Resolve-ToolInstallLocation $linked
        Assert ($location.FreshInstall -and $location.ExtensionDirectory -eq $expected) 'Empty linked root did not select a fresh child extension.'
        $manifest = [PSCustomObject]@{files=[PSCustomObject]@{'ROBMEPTOOLS.tab/AutoDim.panel/AutoDim Smart.pushbutton/engines/duct_engine.py'='fixture'}; bootstrap_files=@('startup.py')}
        $files = @(Get-ToolInstallFiles $manifest $location.FreshInstall)
        Assert ($files.Count -eq $manifest.files.PSObject.Properties.Name.Count + 1) 'Fresh installation omitted tool files.'
        Assert ($files -contains 'ROBMEPTOOLS.tab/AutoDim.panel/AutoDim Smart.pushbutton/engines/duct_engine.py') 'Fresh installation omitted Duct AutoDim.'
        Assert ($files -contains 'update-manifest.json') 'Fresh installation omitted its manifest.'
    }
    'existing' {
        $custom = Join-Path $linked 'CustomName.extension'
        [IO.Directory]::CreateDirectory((Join-Path $custom 'ROBMEPTOOLS.tab')) | Out-Null
        foreach ($inputPath in @($linked, $custom)) {
            $location = Resolve-ToolInstallLocation $inputPath
            Assert (-not $location.FreshInstall -and $location.ExtensionDirectory -eq $custom) 'Existing linked extension was redirected.'
        }
        $manifest = [PSCustomObject]@{files=[PSCustomObject]@{'ROBMEPTOOLS.tab/AutoDim.panel/AutoDim Smart.pushbutton/engines/duct_engine.py'='fixture'}; bootstrap_files=@('startup.py')}
        $files = @(Get-ToolInstallFiles $manifest $false)
        Assert ($files.Count -eq $manifest.bootstrap_files.Count) 'Existing install did not retain bootstrap behavior.'
    }
    'ambiguous' {
        foreach ($name in @('one.extension', 'two.extension')) {
            [IO.Directory]::CreateDirectory((Join-Path $linked "$name/ROBMEPTOOLS.tab")) | Out-Null
        }
        $failed = $false
        try { $null = Resolve-ToolInstallLocation $linked } catch { $failed = $_.Exception.Message -like '*More than one*' }
        Assert $failed 'Ambiguous extensions were silently selected.'
    }
    'conflict' {
        [IO.Directory]::CreateDirectory($expected) | Out-Null
        $extra = Join-Path $expected 'custom.txt'
        [IO.File]::WriteAllText($extra, 'keep me')
        $failed = $false
        try { $null = Resolve-ToolInstallLocation $linked } catch { $failed = $_.Exception.Message -like '*unrecognized files*' }
        Assert $failed 'Unrecognized existing target was accepted as empty.'
        Assert ([IO.File]::ReadAllText($extra) -eq 'keep me') 'Existing target files were changed.'
    }
    'empty-extension' {
        [IO.Directory]::CreateDirectory($expected) | Out-Null
        $location = Resolve-ToolInstallLocation $expected
        Assert ($location.FreshInstall -and $location.ExtensionDirectory -eq $expected) 'Empty extension target was nested again.'
    }
    default { throw "Unknown test case: $Case" }
}
Write-Output "PASS: installer $Case"
