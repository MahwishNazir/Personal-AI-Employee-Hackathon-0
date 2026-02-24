# =============================================================================
# register_weekly_audit_task.ps1 — Register Weekly Audit with Task Scheduler
#
# Run this ONCE as Administrator:
#   powershell -ExecutionPolicy Bypass -File register_weekly_audit_task.ps1
# =============================================================================

$VAULT      = "D:\Hackathon_0\AI_Employee_Vault"
$TASK_NAME  = "AI_Employee_WeeklyAudit"
$SCRIPT     = "$VAULT\run_weekly_audit.ps1"

# Remove old task if it exists
if (Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false
    Write-Host "Removed existing task: $TASK_NAME"
}

# Action: run PowerShell with the audit script
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$SCRIPT`"" `
    -WorkingDirectory $VAULT

# Trigger: every Sunday at 09:00
$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Sunday `
    -At "09:00"

# Settings
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

# Principal: run as current user
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive

Register-ScheduledTask `
    -TaskName  $TASK_NAME `
    -Action    $action `
    -Trigger   $trigger `
    -Settings  $settings `
    -Principal $principal `
    -Description "AI Employee Vault — Weekly audit with CEO briefing (Ralph Loop)"

Write-Host ""
Write-Host "Task registered: $TASK_NAME"
Write-Host "Schedule: Every Sunday at 09:00"
Write-Host ""
Write-Host "To run manually right now:"
Write-Host "  Start-ScheduledTask -TaskName '$TASK_NAME'"
Write-Host ""
Write-Host "To view/manage:"
Write-Host "  Get-ScheduledTask -TaskName '$TASK_NAME' | Format-List"
Write-Host "  taskschd.msc"
