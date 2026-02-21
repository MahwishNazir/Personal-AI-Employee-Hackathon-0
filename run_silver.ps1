# =============================================================================
# run_silver.ps1 — AI Employee Vault Silver Cycle (PowerShell core)
#
# Called by run_silver.bat which is triggered by Windows Task Scheduler.
# Do not rename this file without updating run_silver.bat.
# =============================================================================

# ── Configuration ─────────────────────────────────────────────────────────────
$VAULT   = "D:\Hackathon_0\AI_Employee_Vault"
$LOGS    = "$VAULT\logs"
$CLAUDE  = "C:\Users\User\AppData\Roaming\npm\claude.cmd"

# ── Silver Cycle prompt (verbatim) ────────────────────────────────────────────
$PROMPT = @"
Process EVERY file in Needs_Action/ right now.
Follow this exact workflow: 1. For each item, create a detailed Plan_XXX.md in /Plans/ with checkboxes. 2. If the action is sensitive (email, LinkedIn post, money), create approval file in /Pending_Approval/. 3. Use all Agent Skills (human-in-the-loop, etc.). 4. Use MCP tools when approved. 5. Update Dashboard.md with clear summary. 6. When complete, move files to /Done/. Company_Handbook.md rules are highest priority. When finished, say "SILVER CYCLE COMPLETE".
"@

# ── Build timestamped log filename ────────────────────────────────────────────
$now      = Get-Date
$stamp    = $now.ToString("yyyyMMdd-HHmm")
$LOGFILE  = "$LOGS\silver-$stamp.log"

# ── Ensure logs directory exists ──────────────────────────────────────────────
if (-not (Test-Path $LOGS)) { New-Item -ItemType Directory -Path $LOGS | Out-Null }

# ── Helper: write to log and console ─────────────────────────────────────────
function Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    $line | Tee-Object -FilePath $LOGFILE -Append | Write-Host
}

# ── Header ────────────────────────────────────────────────────────────────────
"============================================================" | Out-File $LOGFILE -Encoding utf8
"SILVER CYCLE START"                                           | Out-File $LOGFILE -Append -Encoding utf8
"Date  : $($now.ToString('yyyy-MM-dd HH:mm:ss'))"             | Out-File $LOGFILE -Append -Encoding utf8
"Vault : $VAULT"                                               | Out-File $LOGFILE -Append -Encoding utf8
"Log   : $LOGFILE"                                             | Out-File $LOGFILE -Append -Encoding utf8
"============================================================" | Out-File $LOGFILE -Append -Encoding utf8

# ── Change to vault directory ─────────────────────────────────────────────────
Set-Location $VAULT
if (-not $?) {
    Log "ERROR: Cannot cd to vault: $VAULT"
    exit 1
}

# ── Verify claude CLI ─────────────────────────────────────────────────────────
if (-not (Test-Path $CLAUDE)) {
    Log "ERROR: Claude CLI not found at: $CLAUDE"
    Log "       Run: npm install -g @anthropic-ai/claude-code"
    exit 1
}

# ── Ensure Node + npm are on PATH ─────────────────────────────────────────────
$env:PATH = "C:\Program Files\nodejs;C:\Users\User\AppData\Roaming\npm;" + $env:PATH

# ── Run Claude Code ───────────────────────────────────────────────────────────
Log "Invoking Claude Code..."
Log "Prompt length: $($PROMPT.Trim().Length) chars"

try {
    # Pipe the prompt via stdin — claude --print reads from stdin when no
    # positional prompt arg is given.
    $result = $PROMPT | & $CLAUDE --print --dangerously-skip-permissions 2>&1
    $exitCode = $LASTEXITCODE

    # Write claude output to log
    $result | Out-File $LOGFILE -Append -Encoding utf8

} catch {
    Log "ERROR: $_"
    $exitCode = 1
}

# ── Footer ────────────────────────────────────────────────────────────────────
""                                                                      | Out-File $LOGFILE -Append -Encoding utf8
"============================================================"           | Out-File $LOGFILE -Append -Encoding utf8
"SILVER CYCLE END"                                                       | Out-File $LOGFILE -Append -Encoding utf8
"Exit  : $exitCode"                                                      | Out-File $LOGFILE -Append -Encoding utf8
"Date  : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"                     | Out-File $LOGFILE -Append -Encoding utf8
"============================================================"           | Out-File $LOGFILE -Append -Encoding utf8

Log "Done. Exit code: $exitCode. Log: $LOGFILE"
exit $exitCode
