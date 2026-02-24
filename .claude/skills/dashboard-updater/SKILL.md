---
name: dashboard-updater
description: Maintains dashboard.md and system_logs.md as the single source of truth for all pipeline activity. Updates Pending Tasks, Pending Approvals, Active Plans, Recent LinkedIn Posts, and Completed Tasks tables. Called by every other skill at key status transitions. Always runs as the LAST step of a Silver Cycle.
---

# Dashboard Updater Skill

## Purpose

`dashboard.md` is the human-readable control panel for the entire AI Employee Vault.
This skill keeps it accurate across all status transitions — from task arrival through
planning, approval, execution, and completion.

`system_logs.md` receives a timestamped audit trail of every action.

**Silver Tier pipeline position:** Step 6 of 6 (called by all other skills)

```
Every other skill calls dashboard-updater at key transitions.
dashboard-updater is also the final step of the full Silver Cycle.
```

---

## dashboard.md Structure

The dashboard must always contain these sections in order:

```markdown
# Dashboard

> AI Employee Vault — Task Automation Pipeline
> Last updated: YYYY-MM-DD HH:MM UTC

---

## Watcher Status
## Pending Tasks
## Pending Approvals
## Active Plans
## Recent LinkedIn Posts
## Completed Tasks
```

---

## Instructions

### Operation A — Update Pending Tasks

**Called by:** `multi-watcher-orchestration` (on new task arrival)

Locate the `## Pending Tasks` table. Add a row:
```markdown
| <task-name> | <category> | <source> | <received-timestamp> | pending |
```

Table header (create if missing):
```markdown
| Task | Category | Source | Received | Status |
|------|----------|--------|----------|--------|
```

If no pending tasks exist, show:
```markdown
| — | — | — | — | No pending tasks |
```

Remove a task's row when its status advances to `processing` or beyond.

---

### Operation B — Update Pending Approvals

**Called by:** `human-approval-workflow` (Phase A — on approval file creation)

Locate `## Pending Approvals`. Add a row:
```markdown
| <APPROVAL_filename> | <action-type> | <priority> | <created-timestamp> |
```

Table header:
```markdown
| File | Action | Priority | Submitted |
|------|--------|----------|-----------|
```

**Remove** the row when `human-approval-workflow` confirms the file reached `Approved/` or `Rejected/`.

If no pending approvals:
```markdown
| — | — | — | No pending approvals |
```

---

### Operation C — Update Active Plans

**Called by:** `plan-creation-workflow` (on plan file creation)

Locate `## Active Plans`. Add a row:
```markdown
| [Plan_<slug>.md](plans/Plan_<slug>.md) | <category> | <date> | <source-task> |
```

Table header:
```markdown
| Plan | Category | Generated | Source Task |
|------|----------|-----------|-------------|
```

Plans remain in Active Plans until their source task reaches `done/`.
They are never deleted from the table — completed plans stay visible.

---

### Operation D — Update Recent LinkedIn Posts

**Called by:** `linkedin-business-poster` (on approval creation) and `mcp-action-handler` (on post success)

Locate `## Recent LinkedIn Posts`. Add or update a row:
```markdown
| <N> | <post-title-or-first-15-words> | <status> | <date> |
```

Status values: `pending approval` → `posted` → (stays in table permanently)

Table header:
```markdown
| # | Topic | Status | Date |
|---|-------|--------|------|
```

---

### Operation E — Update Completed Tasks

**Called by:** `mcp-action-handler` and `plan-creation-workflow` (non-sensitive tasks that complete directly)

Locate `## Completed Tasks`. Add a row:
```markdown
| <task-name> | <category> | <completed-timestamp> | <cycle> |
```

Table header:
```markdown
| Task | Category | Completed | Cycle |
|------|----------|-----------| ------|
```

Completed tasks are **never removed** from this table — it is a permanent log.

---

### Operation F — Update Watcher Status

**Called by:** `multi-watcher-orchestration` (once per cycle)

Update the `## Watcher Status` table with the current scan result:

```markdown
| Watcher | Status | Last Scan | Items Found |
|---------|--------|-----------|-------------|
| inbox | active | <HH:MM> | <N> |
| gmail | active / skipped | <HH:MM> | <N> |
| linkedin | active / skipped | <HH:MM> | <N> |
| whatsapp | active / skipped | <HH:MM> | <N> |
```

---

### Operation G — Append to system_logs.md

**Called by:** every skill at every status transition.

Append to `## Activity Logs` section:
```markdown
- [<ISO-8601-UTC>] [<skill-name>] <event description>
```

Examples:
```markdown
- [2026-02-22T08:00:01Z] [multi-watcher-orchestration] 3 new items queued
- [2026-02-22T08:00:05Z] [plan-creation-workflow] Plan created: Plan_Eng_curriculm.md
- [2026-02-22T08:00:06Z] [human-approval-workflow] Approval created: APPROVAL_post_linkedin_20260222T080006.md
- [2026-02-22T08:01:00Z] [mcp-action-handler] Email sent — source: client_inquiry.md
- [2026-02-22T08:01:02Z] [dashboard-updater] Dashboard refreshed — 2 completed, 1 pending approval
```

**Script reference:** `agents/task_agent.py` → `update_system_logs()`

---

### Operation H — Silver Cycle Summary Block

**Called by:** `run_silver.ps1` at the end of every cycle.

Append a summary block to `system_logs.md`:
```markdown
---
## Silver Cycle Run — <YYYY-MM-DD HH:MM UTC>

| Metric | Count |
|--------|-------|
| New items found | <N> |
| Plans created | <N> |
| Approvals created | <N> |
| Approvals executed | <N> |
| Tasks completed | <N> |
| LinkedIn posts queued | <N> |
| Errors | <N> |

SILVER CYCLE COMPLETE
---
```

---

### Operation I — Update Recent Audit Summary

**Called by:** `dashboard-updater` itself, at the end of every Silver Cycle run.

Read the last 10 audit entries from `Logs/` using the Python helper:

```python
from audit_logger import get_recent_actions, format_audit_table
entries = get_recent_actions(10)
table_md = format_audit_table(entries)
```

Replace the entire `## Recent Audit Summary` section in `dashboard.md` with:

```markdown
## Recent Audit Summary

> Last 10 actions logged to `Logs/YYYY-MM-DD.json`. Updated each Silver Cycle by `dashboard-updater`.
> Full log: `python -c "from audit_logger import get_recent_actions, format_audit_table; print(format_audit_table(get_recent_actions(20)))"`

| Timestamp (UTC) | Action Type | Actor | Target | Approval | Result |
|-----------------|-------------|-------|--------|----------|--------|
| <row> | ... | ... | ... | ... | ... |
```

If no log files exist yet, show: `_No audit entries recorded yet._`

After updating the section, log this operation itself:
```python
log_action(
    action_type="dashboard_update",
    actor="claude",
    target="dashboard.md",
    parameters={"operation": "audit_table_refresh", "entries_shown": len(entries)},
    approval_status="n_a",
    result="success",
)
```

---

## Update Rules

1. **Always update the "Last updated" timestamp** at the top of `dashboard.md`
2. **Never delete completed task rows** — the completed table is an append-only log
3. **Write atomically** — read the full file, apply all changes, write it back once
4. **Preserve all markdown formatting** — tables must remain valid markdown
5. **Handle missing sections gracefully** — create any missing section header before inserting rows
6. **Always call `log-action`** for every dashboard write (Operation I handles this automatically)

---

## Script References

- `agents/task_agent.py` → `update_dashboard()` — Bronze row-insertion logic (reuse/extend)
- `agents/task_agent.py` → `update_system_logs()` — log append logic (reuse/extend)
- `dashboard.md` — target file
- `system_logs.md` — audit log target
