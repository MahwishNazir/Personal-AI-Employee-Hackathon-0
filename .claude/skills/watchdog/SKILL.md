---
name: watchdog
description: >
  Monitor all long-running vault processes (inbox-watcher, Gmail, LinkedIn,
  WhatsApp watchers). Restart any that have died. Report current process health.
  Can be run by Claude as a diagnostic check or launched as a standalone daemon.
---

# Watchdog

## Purpose

Ensure all persistent vault processes are alive. If a process has crashed or
exited, restart it automatically after a short cooldown. Write process health to
`watchdog_status.json` for dashboard visibility.

**Pipeline position:** Can be invoked:
1. **As a Silver Cycle diagnostic** — check health and restart dead processes mid-cycle.
2. **As a standalone daemon** — run `python watchdog.py` in a terminal; it loops forever.
3. **On-demand** — invoked by Claude when a watcher appears to have stalled.

---

## Watched Processes

| Name | Script | Auto-start | Restart delay |
|------|--------|------------|---------------|
| `inbox-watcher` | `main.py` | Yes | 5s |
| `whatsapp-watcher` | `whatsapp_watcher.py` | No (needs prior `--login`) | 15s |
| `linkedin-watcher` | `linkedin_watcher.py` | No (needs prior `--login`) | 15s |
| `gmail-watcher` | `gmail_watcher.py` | No (needs prior `--auth`) | 10s |

**Auto-start** means the watchdog daemon will start the process automatically on
launch. Manual processes require a prior interactive login step and are only
restarted if they were already running when the watchdog started.

---

## Instructions (Claude Invocation)

### Step 1 — Read watchdog_status.json

```
Read vault_root/watchdog_status.json
```

If the file does not exist, the watchdog daemon is not running. Skip to Step 4.

### Step 2 — Assess Health

For each process in `watchdog_status.json`:
- If `alive: true` → OK, note PID.
- If `alive: false` → process is down. Note which ones.

### Step 3 — Log Health Check

Call **log-action**:
```
action_type : "watchdog_health_check"
actor       : "claude"
target      : "watchdog_status.json"
parameters  : {
  "alive": ["inbox-watcher", ...],
  "dead": ["gmail-watcher", ...]
}
result      : "success" | "fail"
```

### Step 4 — If Watchdog Daemon is NOT Running

Create `Pending_Approval/ALERT_watchdog_down_<timestamp>.md`:

```markdown
---
type: alert
action: watchdog_down
priority: high
status: pending
---

# ALERT: Watchdog Daemon Is Not Running

The process watchdog (watchdog.py) does not appear to be active.
No automatic process restarts are occurring.

## Affected Processes

Check whether these are running manually:
- main.py (inbox-watcher)
- gmail_watcher.py
- linkedin_watcher.py
- whatsapp_watcher.py

## How to Start the Watchdog

```bash
# Watch only the auto-start processes (recommended)
python watchdog.py

# Watch everything (requires prior login for social watchers)
python watchdog.py --all

# Watch specific processes
python watchdog.py --watch inbox-watcher gmail-watcher
```

## Human Instructions

Start the watchdog in a terminal, then move this file to `Rejected/` to dismiss.
```

### Step 5 — If Dead Processes Are Found

For each dead process, attempt to restart it by calling:

```bash
python watchdog.py --watch <process-name>
```

Or instruct the user to restart via the alert file. Log the restart attempt:

```
action_type : "watchdog_restart_attempted"
target      : "<process-name>"
parameters  : { "reason": "process found dead in watchdog_status.json" }
result      : "success" | "fail"
```

### Step 6 — Update system_logs.md

Append a one-liner:
```
[<timestamp>] WATCHDOG: inbox-watcher OK (PID 1234) | gmail-watcher: RESTARTED | linkedin-watcher: OK
```

---

## Standalone Daemon Usage

```bash
# Start watchdog (auto-start processes only — safe default)
python watchdog.py

# Watch all processes (including those needing prior login)
python watchdog.py --all

# Watch specific processes
python watchdog.py --watch inbox-watcher gmail-watcher

# Check current status (reads watchdog_status.json)
python watchdog.py --status

# List all watchable process names
python watchdog.py --list
```

The daemon runs `CHECK_INTERVAL = 30` seconds between health checks.
When a dead process is detected it waits `restart_delay` seconds (per process),
then restarts it with the original command and logs the restart count.

**watchdog_status.json** (updated every check):
```json
{
  "checked_at": "2026-02-25 09:00:00 UTC",
  "processes": {
    "inbox-watcher": {
      "alive": true,
      "pid": 12345,
      "restarts": 0,
      "description": "Core inbox watcher + task analyzer + agent chain"
    },
    "gmail-watcher": {
      "alive": false,
      "pid": null,
      "restarts": 2,
      "description": "Gmail API watcher (requires prior --auth)"
    }
  }
}
```

---

## Integration with Silver Cycle

Add this optional health check at the **start** of a Silver Cycle (before Skill 1):

```
Optional: Read watchdog_status.json. If any process is dead, create an alert
in Pending_Approval/ and log to system_logs.md. Do not halt the cycle.
```

This is already referenced in `company_handbook.md` Section 4.

---

## Psutil Advanced Features (when installed)

If `psutil` is installed (`pip install psutil`), the watchdog gains:
- **Stale process detection** — finds vault Python processes NOT started by this
  watchdog instance (useful after a watchdog restart).
- Accurate `alive` determination using OS-level process status.

Install: `pip install psutil`

Without psutil, the watchdog falls back to `subprocess.Popen.poll()` which is
sufficient for processes it has spawned itself.

---

## Output Contract

| Guarantee | Details |
|-----------|---------|
| watchdog_status.json | Updated after every 30s check cycle |
| Audit entries | `watchdog_health_check` logged every cycle |
| Restart logged | `watchdog_restart_attempted` logged per restart |
| No silent deaths | Dead processes → alert in Pending_Approval/ (Claude invocation) |
| Dashboard entry | system_logs.md updated with process health summary |
| Graceful shutdown | CTRL+C terminates all managed processes cleanly |
