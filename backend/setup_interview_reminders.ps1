$ErrorActionPreference = "Stop"

$taskName = "CTJob Interview Reminders"
$batchPath = Join-Path $PSScriptRoot "run_reminder.bat"

if (-not (Test-Path $batchPath)) {
    throw "Reminder command was not found: $batchPath"
}

$action = New-ScheduledTaskAction `
    -Execute $env:ComSpec `
    -Argument ('/c "' + $batchPath + '"') `
    -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Send CTJob interview reminder emails for interviews within 24 hours." `
    -Force | Out-Null

Write-Output "Registered '$taskName' to check for interview reminders every 5 minutes."
