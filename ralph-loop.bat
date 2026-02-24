@echo off
:: =============================================================================
:: ralph-loop.bat — Windows wrapper for the Ralph Wiggum Persistent Loop
::
:: Usage:
::   ralph-loop.bat "Process all items in needs_action"
::   ralph-loop.bat --max-iterations 10 "Write CEO briefing"
::   ralph-loop.bat --completion-promise DONE --prompt-file silver_prompt.txt
::   ralph-loop.bat --resume "Process all items in needs_action"
:: =============================================================================

:: ── Configuration ─────────────────────────────────────────────────────────────
set VAULT=D:\Hackathon_0\AI_Employee_Vault

:: ── Prefer venv Python, fall back to system Python ───────────────────────────
set PYTHON=%VAULT%\venv\Scripts\python.exe
if not exist "%PYTHON%" (
    set PYTHON=python
)

:: ── Ensure supporting directories exist ──────────────────────────────────────
if not exist "%VAULT%\logs"        mkdir "%VAULT%\logs"
if not exist "%VAULT%\Ralph_State" mkdir "%VAULT%\Ralph_State"

:: ── Ensure Node + npm are on PATH (claude CLI needs them) ────────────────────
set PATH=C:\Program Files\nodejs;C:\Users\User\AppData\Roaming\npm;%PATH%

:: ── Execute ───────────────────────────────────────────────────────────────────
"%PYTHON%" "%VAULT%\ralph_loop.py" %*
exit /b %ERRORLEVEL%
