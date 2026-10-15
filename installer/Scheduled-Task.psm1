function Connect-ToolScheduler {
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    return $service
}

function Test-MissingToolTask($Exception) {
    while ($null -ne $Exception) {
        if ($Exception.HResult -eq -2147024894) { return $true } # 0x80070002: task not found
        $Exception = $Exception.InnerException
    }
    return $false
}

function Convert-ToolComTask($RegisteredTask) {
    $definition = $RegisteredTask.Definition
    $actions = @()
    foreach ($action in $definition.Actions) {
        if ($action.Type -eq 0) { $actions += [PSCustomObject]@{ Execute = $action.Path; Arguments = $action.Arguments } }
        else { $actions += [PSCustomObject]@{ Execute = ''; Arguments = '' } }
    }
    $triggers = @()
    foreach ($trigger in $definition.Triggers) {
        $class = if ($trigger.Type -eq 9) { 'MSFT_TaskLogonTrigger' } else { 'COM_TaskTrigger' }
        $triggers += [PSCustomObject]@{ Repetition = @{ Interval = $trigger.Repetition.Interval }; CimClass = @{ CimClassName = $class } }
    }
    $state = switch ([int]$RegisteredTask.State) { 1 { 'Disabled' }; 3 { 'Ready' }; 4 { 'Running' }; default { 'Unknown' } }
    $logon = if ($definition.Principal.LogonType -eq 3) { 'Interactive' } else { [string]$definition.Principal.LogonType }
    $level = if ($definition.Principal.RunLevel -eq 0) { 'Limited' } else { 'Highest' }
    return [PSCustomObject]@{
        TaskName = $RegisteredTask.Name
        TaskPath = $RegisteredTask.Path.Substring(0, $RegisteredTask.Path.Length - $RegisteredTask.Name.Length)
        Settings = @{ Enabled = [bool]$RegisteredTask.Enabled -and [bool]$definition.Settings.Enabled }
        State = $state; Actions = $actions; Triggers = $triggers
        Principal = @{ LogonType = $logon; RunLevel = $level }
        Backend = 'COM'; ComTask = $RegisteredTask
    }
}

function Find-ToolComTask([string]$Name) {
    $service = Connect-ToolScheduler
    $folder = $service.GetFolder([string][char]92)
    try { $registered = $folder.GetTask($Name) }
    catch {
        if (Test-MissingToolTask $_.Exception) { return }
        throw
    }
    if ($registered.Name -ne $Name) { throw 'Windows returned a different task than requested.' }
    return Convert-ToolComTask $registered
}

function Find-ToolUpdateTask([string]$Name) {
    try { $tasks = @(Get-ScheduledTask -TaskName $Name -ErrorAction Stop) }
    catch {
        # Some Windows providers fail an exact query even when enumeration
        # succeeds. Use returned TaskPath instead of assuming its location.
        try { $tasks = @(Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.TaskName -eq $Name }) }
        catch {
            $providerError = $_.Exception.Message
            try { return Find-ToolComTask $Name }
            catch {
                throw "Both Windows task interfaces failed. PowerShell: $providerError COM: $($_.Exception.Message)"
            }
        }
    }
    if (-not $tasks.Count) { return }
    if ($tasks.Count -ne 1) { throw "More than one task named '$Name' was found. Select or remove the duplicate in Task Scheduler." }
    if ($tasks[0].TaskName -ne $Name -or -not $tasks[0].TaskPath) { throw "Windows returned incomplete registration details for '$Name'." }
    return $tasks[0]
}

function Register-ToolComTask([string]$Name, [string]$ExtensionRoot, [string]$User, [string]$Executable, [string]$Arguments) {
    $service = Connect-ToolScheduler
    $definition = $service.NewTask(0)
    $definition.RegistrationInfo.Description = 'Updates ROBMEPTOOLS every 15 minutes while signed in; waits until Revit is closed.'
    $definition.Principal.UserId = $User
    $definition.Principal.LogonType = 3  # interactive user; no stored password
    $definition.Principal.RunLevel = 0  # limited privileges
    $definition.Settings.Enabled = $true
    $definition.Settings.StartWhenAvailable = $true
    $definition.Settings.MultipleInstances = 2  # ignore a second instance
    $definition.Settings.ExecutionTimeLimit = 'PT5M'
    $definition.Settings.DisallowStartIfOnBatteries = $false
    $definition.Settings.StopIfGoingOnBatteries = $false
    $timer = $definition.Triggers.Create(1)
    $timer.Enabled = $true
    $timer.StartBoundary = (Get-Date).AddMinutes(1).ToString('yyyy-MM-ddTHH:mm:ss')
    $timer.Repetition.Interval = 'PT15M'
    $logon = $definition.Triggers.Create(9)
    $logon.Enabled = $true
    $logon.UserId = $User
    $action = $definition.Actions.Create(0)
    $action.Path = $Executable
    $action.Arguments = $Arguments
    $folder = $service.GetFolder([string][char]92)
    $null = $folder.RegisterTaskDefinition($Name, $definition, 6, $User, $null, 3, $null)
    $registered = $folder.GetTask($Name)
    return Convert-ToolComTask $registered
}

function Register-ToolUpdateTask([string]$Name, [string]$ExtensionRoot) {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $runner = Join-Path $ExtensionRoot 'updater/Update-Background.ps1'
    $arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -ExtensionRoot "{1}"' -f $runner, $ExtensionRoot
    $executable = Join-Path $PSHOME 'powershell.exe'
    try {
        $action = New-ScheduledTaskAction -Execute $executable -Argument $arguments
        $timer = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
        $logon = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
        $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        $null = Register-ScheduledTask -TaskName $Name -TaskPath ([string][char]92) -Action $action -Trigger @($timer, $logon) -Principal $principal -Settings $settings -Description 'Updates ROBMEPTOOLS every 15 minutes while signed in; waits until Revit is closed.' -Force -ErrorAction Stop
    } catch {
        $providerError = $_.Exception.Message
        try { return Register-ToolComTask $Name $ExtensionRoot $currentUser $executable $arguments }
        catch { throw "Task registration failed through both Windows interfaces. PowerShell: $providerError COM: $($_.Exception.Message)" }
    }
    $task = Find-ToolUpdateTask $Name
    if (-not $task) { throw "Windows did not retain task '$Name' after registration. Check Task Scheduler permissions and run setup again." }
    return $task
}

function Start-ToolUpdateTask($Task) {
    if ($Task.Backend -eq 'COM') { $null = $Task.ComTask.Run($null) }
    else { Start-ScheduledTask -InputObject $Task -ErrorAction Stop }
}

Export-ModuleMember -Function Find-ToolUpdateTask, Register-ToolUpdateTask, Start-ToolUpdateTask
