@echo off
:: =============================================================================
:: run_silver.bat — AI Employee Vault Silver Cycle
::
:: Windows equivalent of Linux cron:
::   0  8 * * *  claude --print < silver_prompt.txt >> logs/silver-DATE.log
::   0 20 * * *  claude --print < silver_prompt.txt >> logs/silver-DATE.log
::
:: Called by TWO Windows Task Scheduler tasks:
::   Task 1 — triggers 08:00 daily
::   Task 2 — triggers 20:00 daily
::
:: Delegates the Claude call to PowerShell so the multi-line prompt and
:: log path are handled correctly (batch heredoc does not exist on Windows).
:: =============================================================================

:: ── Configuration ─────────────────────────────────────────────────────────────
set VAULT=D:\Hackathon_0\AI_Employee_Vault
set PS1=%VAULT%\run_silver.ps1

:: ── Ensure PATH includes Node / npm (claude CLI needs them) ───────────────────
set PATH=C:\Program Files\nodejs;C:\Users\User\AppData\Roaming\npm;%PATH%

:: ── Hand off to PowerShell script ─────────────────────────────────────────────
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
exit /b %ERRORLEVEL%
