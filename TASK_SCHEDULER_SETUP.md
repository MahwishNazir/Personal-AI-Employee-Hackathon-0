# Windows Task Scheduler — Silver Cycle Setup

Runs the AI Employee Vault Silver Cycle twice daily (08:00 and 20:00),
equivalent to the Linux cron:

```
0  8 * * *  /path/to/run_silver.sh >> logs/silver-DATE.log 2>&1
0 20 * * *  /path/to/run_silver.sh >> logs/silver-DATE.log 2>&1
```

---

## Files

| File | Purpose |
|------|---------|
| `run_silver.bat` | Entry point called by Task Scheduler |
| `run_silver.ps1` | PowerShell core — builds log path, calls Claude CLI |
| `silver_prompt.txt` | The Silver Cycle prompt (reference copy) |
| `logs/silver-YYYYMMDD-HHMM.log` | Output log per run |

---

## Section 1 — Full Content of run_silver.bat

```bat
@echo off
set VAULT=D:\Hackathon_0\AI_Employee_Vault
set PS1=%VAULT%\run_silver.ps1
set PATH=C:\Program Files\nodejs;C:\Users\User\AppData\Roaming\npm;%PATH%
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
exit /b %ERRORLEVEL%
```

The `.bat` is the Task Scheduler target. It delegates to `run_silver.ps1`
which handles the multi-line Claude prompt, timestamped log file, and exit codes.

---

## Section 2 — Task Scheduler GUI Instructions

You will create **two tasks** — one for 8 AM, one for 8 PM.
Follow these steps for **each task** (repeat with different time/name for the second).

### Open Task Scheduler

1. Press `Win + R`, type `taskschd.msc`, press Enter.

---

### Create Task 1 — Morning Run (08:00)

#### General tab
1. Click **Action** → **Create Task…** (not "Create Basic Task")
2. **Name:** `AI Employee Vault — Silver Cycle Morning`
3. **Description:** `Runs Silver Cycle at 08:00. Processes needs_action/ via Claude Code.`
4. **Security options:**
   - Select: **Run whether user is logged on or not**
   - Check: **Run with highest privileges**
   - Configure for: **Windows 10** (or Windows 11)

#### Triggers tab
5. Click **New…**
6. **Begin the task:** On a schedule
7. **Settings:** Daily
8. **Start:** Set date to today, time = `8:00:00 AM`
9. **Recur every:** 1 days
10. **Enabled:** ✔ checked
11. Click **OK**

#### Actions tab
12. Click **New…**
13. **Action:** Start a program
14. **Program/script:**
    ```
    C:\Windows\System32\cmd.exe
    ```
15. **Add arguments:**
    ```
    /c "D:\Hackathon_0\AI_Employee_Vault\run_silver.bat"
    ```
16. **Start in:**
    ```
    D:\Hackathon_0\AI_Employee_Vault
    ```
17. Click **OK**

#### Conditions tab
18. Uncheck **"Start the task only if the computer is on AC power"**
    *(prevents the task skipping if you're on battery)*

#### Settings tab
19. Check **"Run task as soon as possible after a scheduled start is missed"**
20. Check **"If the task fails, restart every:"** → set to `5 minutes`, attempt `3` times
21. Set **"Stop the task if it runs longer than:"** → `2 hours`
22. **If the task is already running:** → `Do not start a new instance`
23. Click **OK**

#### Enter credentials
24. You will be prompted for your Windows password (needed for "Run whether logged on or not").
    Enter it and click **OK**.

---

### Create Task 2 — Evening Run (20:00)

Repeat **all steps above** with these differences:

| Setting | Value |
|---------|-------|
| Name | `AI Employee Vault — Silver Cycle Evening` |
| Trigger time | `8:00:00 PM` (20:00) |

Everything else is identical.

---

## Section 3 — Important Settings Summary

| Setting | Value | Why |
|---------|-------|-----|
| Run whether user is logged on or not | ✔ | Runs even if screen is locked |
| Run with highest privileges | ✔ | Prevents file permission errors |
| Start in (working directory) | `D:\Hackathon_0\AI_Employee_Vault` | Claude Code needs to be in vault root |
| Restart if fails | Every 5 min, 3 attempts | Recovers from transient errors |
| Stop if runs longer than | 2 hours | Prevents runaway processes |
| Don't start new instance if already running | ✔ | Prevents overlapping cycles |
| Run as soon as possible if missed | ✔ | Catches up if PC was off at trigger time |

---

## Section 4 — How to Test Immediately

### Option A — Run the .bat directly
Open a terminal and run:
```cmd
D:\Hackathon_0\AI_Employee_Vault\run_silver.bat
```
Then check `logs/` for a new `silver-YYYYMMDD-HHMM.log`.

### Option B — Trigger from Task Scheduler
1. In Task Scheduler, find your task in the task list.
2. Right-click → **Run**.
3. The **Last Run Result** column should show `0x0` (success) within a minute.
4. Check `D:\Hackathon_0\AI_Employee_Vault\logs\` for the new log file.

### Option C — PowerShell direct test
```powershell
cd D:\Hackathon_0\AI_Employee_Vault
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_silver.ps1
```

### Verify the log
```powershell
# List recent logs
Get-ChildItem D:\Hackathon_0\AI_Employee_Vault\logs\silver-*.log |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 3

# Tail the latest log
Get-Content (
    Get-ChildItem D:\Hackathon_0\AI_Employee_Vault\logs\silver-*.log |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 -ExpandProperty FullName
) -Wait
```

---

## Section 5 — Troubleshooting

### "claude is not recognized" / Last Run Result: 0x1

**Cause:** Task Scheduler runs with a minimal PATH that doesn't include npm.

**Fix:** The `run_silver.bat` already prepends the npm path. If it still fails:
1. Open `run_silver.bat` and verify this line matches your npm path:
   ```
   set PATH=C:\Program Files\nodejs;C:\Users\User\AppData\Roaming\npm;%PATH%
   ```
2. Find your actual npm path:
   ```cmd
   where claude
   ```
   Update the PATH line accordingly.

---

### "Execution Policy" error in log

**Cause:** PowerShell execution policy blocks scripts.

**Fix:** Already handled by `-ExecutionPolicy Bypass` in `run_silver.bat`.
If it still fails, run once as Administrator:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

---

### Task shows "Last Run Result: 0x41301" (task is running)

This is normal — it means the task is still executing. Wait for it to finish.

---

### Task shows "Last Run Result: 0x41306" (task is not running)

**Cause:** Task was terminated (ran longer than the stop limit, or manually stopped).

**Fix:** Check the log for where it stopped. Increase the "Stop if runs longer than" setting if Claude takes a long time.

---

### Claude hangs / never returns

**Cause:** `--print` mode should be non-interactive but large vaults can be slow.

**Fix:**
- Add `--max-budget-usd 1.00` to the claude command in `run_silver.ps1` to cap spend per run.
- The 2-hour stop limit in Task Scheduler will terminate it as a last resort.

---

### Logs directory is empty after scheduled run

**Cause:** Working directory not set correctly, so logs write somewhere unexpected.

**Fix:** Confirm the **Start in** field in the Action is:
```
D:\Hackathon_0\AI_Employee_Vault
```

---

### "Access denied" errors in log

**Cause:** Task not running with elevated privileges.

**Fix:** In the task's General tab, ensure **"Run with highest privileges"** is checked,
and the account used is in the Administrators group.

---

### Check task history

In Task Scheduler, click your task → **History** tab to see every run with timestamps,
duration, and result codes. Enable history if it's blank:
```
Action menu → Enable All Tasks History
```

---

## Quick Reference — Task Scheduler XML (import alternative)

Instead of the GUI, you can import a pre-built task. Save as `silver_morning.xml`:

```xml
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-02-22T08:00:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Actions>
    <Exec>
      <Command>C:\Windows\System32\cmd.exe</Command>
      <Arguments>/c "D:\Hackathon_0\AI_Employee_Vault\run_silver.bat"</Arguments>
      <WorkingDirectory>D:\Hackathon_0\AI_Employee_Vault</WorkingDirectory>
    </Exec>
  </Actions>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT5M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
    <StartWhenAvailable>true</StartWhenAvailable>
  </Settings>
  <Principals>
    <Principal>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
</Task>
```

Import via: Task Scheduler → **Action** → **Import Task…** → select the XML file.
Duplicate and change the time for the evening task.
