# =============================================================================
# run_weekly_audit.ps1 — AI Employee Vault Weekly Audit (via Ralph Loop)
#
# Runs every Sunday at 09:00 via Windows Task Scheduler.
# Invokes orchestrator.py weekly-audit which:
#   1. Runs a full Silver Cycle
#   2. Processes all items in needs_action/
#   3. Generates CEO_Briefing_YYYY-MM-DD.md if today is Sunday
#   4. Updates dashboard.md and system_logs.md
#   5. Loops via Ralph until <TASK_COMPLETE> is seen (max 15 iterations)
#
# To register the scheduled task, run (as Administrator):
#   powershell -ExecutionPolicy Bypass -File register_weekly_audit_task.ps1
# =============================================================================

# ── Configuration ─────────────────────────────────────────────────────────────
$VAULT   = "D:\Hackathon_0\AI_Employee_Vault"
$LOGS    = "$VAULT\logs"
$PYTHON  = "$VAULT\venv\Scripts\python.exe"

# Fall back to system python if venv not found
if (-not (Test-Path $PYTHON)) { $PYTHON = "python" }

# ── Timestamped log file ──────────────────────────────────────────────────────
$stamp   = (Get-Date).ToString("yyyyMMdd-HHmm")
$LOGFILE = "$LOGS\weekly_audit-$stamp.log"

# ── Ensure directories ────────────────────────────────────────────────────────
if (-not (Test-Path $LOGS))        { New-Item -ItemType Directory -Path $LOGS | Out-Null }
if (-not (Test-Path "$VAULT\Ralph_State")) {
    New-Item -ItemType Directory -Path "$VAULT\Ralph_State" | Out-Null
}

# ── Helper ────────────────────────────────────────────────────────────────────
function Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    $line | Tee-Object -FilePath $LOGFILE -Append | Write-Host
}

# ── Ensure PATH includes Node / npm ──────────────────────────────────────────
$env:PATH = "C:\Program Files\nodejs;C:\Users\User\AppData\Roaming\npm;" + $env:PATH

# ── Header ───────────────────────────────────────────────────────────────────
"=" * 60 | Out-File $LOGFILE -Encoding utf8
"WEEKLY AUDIT START" | Out-File $LOGFILE -Append -Encoding utf8
"Date  : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File $LOGFILE -Append -Encoding utf8
"Vault : $VAULT" | Out-File $LOGFILE -Append -Encoding utf8
"=" * 60 | Out-File $LOGFILE -Append -Encoding utf8

Set-Location $VAULT

Log "Python : $PYTHON"
Log "Invoking orchestrator.py weekly-audit …"

try {
    $result = & $PYTHON "$VAULT\orchestrator.py" weekly-audit --max-iterations 15 2>&1
    $exitCode = $LASTEXITCODE
    $result | Out-File $LOGFILE -Append -Encoding utf8
} catch {
    Log "ERROR: $_"
    $exitCode = 1
}

"=" * 60 | Out-File $LOGFILE -Append -Encoding utf8
"WEEKLY AUDIT END" | Out-File $LOGFILE -Append -Encoding utf8
"Exit  : $exitCode" | Out-File $LOGFILE -Append -Encoding utf8
"Date  : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File $LOGFILE -Append -Encoding utf8
"=" * 60 | Out-File $LOGFILE -Append -Encoding utf8

Log "Done. Exit code: $exitCode. Log: $LOGFILE"
exit $exitCode
