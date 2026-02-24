---
name: log-action
description: Appends a structured JSON audit entry to Logs/YYYY-MM-DD.json for any action performed by Claude or a watcher. Every other Silver Tier skill MUST call this before and after any consequential action (file write, MCP call, approval, status transition, etc.).
---

# Log Action Skill

## Purpose

Every action in the AI Employee Vault — file writes, MCP calls, approval
lifecycle events, status transitions, dashboard updates — must be recorded
in an append-only structured audit log at:

```
Logs/YYYY-MM-DD.json     (one file per day, UTC)
```

This skill defines **when** and **how** to call the logger. The underlying
Python implementation lives in `audit_logger.py` at the vault root.

---

## When to Call This Skill

Call `log-action` **before starting** and **after completing** every action below.
A single post-action entry is acceptable for trivial local reads.

| action_type | Trigger | Notes |
|-------------|---------|-------|
| `watcher_scan` | Start of each source scan | Include `source` + `item_count` |
| `file_write` | After writing any file to disk | Include `path` + `size` |
| `plan_created` | After generating a `Plan_*.md` | Include `plan_path` + `category` + `sensitive` |
| `approval_created` | After writing to `Pending_Approval/` | Include `approval_file` + `action_type` + `priority` |
| `approval_approved` | When approval file found in `Approved/` | Include `filename` |
| `approval_rejected` | When approval file found in `Rejected/` | Include `filename` + `human_note` |
| `mcp_call` | Before executing any MCP action | Include `mcp_name` + `action` |
| `email_sent` | After email-mcp sends email | Include `to` + `subject` + `message_id` |
| `linkedin_post` | After posting to LinkedIn | Include first 60 chars of post |
| `status_transition` | On every `meta.json` status change | Include `from` + `to` status |
| `dashboard_update` | After each `dashboard.md` write | Include `operation` type |
| `dedup_skip` | When a task is skipped (already in `done/`) | Include `filename` |
| `error` | On any caught exception | Include error message |

---

## Log Entry Format

Each entry in `Logs/YYYY-MM-DD.json` is a JSON object:

```json
{
  "timestamp": "<ISO-8601-UTC>",
  "action_type": "<one of the types above>",
  "actor": "<see Actor Values below>",
  "target": "<filename | email address | URL | resource name>",
  "parameters": {
    "<key>": "<value>"
  },
  "approval_status": "<pending | approved | rejected | n_a>",
  "result": "<success | fail | skip>",
  "error": "<error message string or null>"
}
```

The file contains a **top-level JSON array** — each call appends one object.

### Actor Values

| actor | Use for |
|-------|---------|
| `claude` | Silver Cycle skills executing inside Claude |
| `watcher` | Bronze-tier `watcher.py` inbox monitor |
| `gmail-watcher` | `gmail_watcher.py` external watcher |
| `linkedin-watcher` | `linkedin_watcher.py` external watcher |
| `whatsapp-watcher` | `whatsapp_watcher.py` external watcher |
| `email-mcp` | email-mcp MCP server (Gmail API) |
| `linkedin-mcp` | LinkedIn Playwright automation |
| `task_agent` | Bronze-tier `agents/task_agent.py` |
| `task_analyzer` | Bronze-tier `skills/task_analyzer.py` |

---

## How Claude Skills Must Use This Skill

### Pattern A — Single post-action log (simple operations)

```
After writing plans/Plan_task.md:
  log_action(
    action_type="plan_created",
    actor="claude",
    target="plans/Plan_task.md",
    parameters={"source_task": "task.md", "category": "email-reply", "sensitive": True},
    approval_status="n_a",
    result="success",
  )
```

### Pattern B — Before + after log (external/MCP actions)

```
BEFORE sending email:
  log_action(
    action_type="mcp_call",
    actor="email-mcp",
    target="recipient@example.com",
    parameters={"action": "send_email", "subject": "Re: your query",
                "approval_file": "APPROVAL_send_email_20260225T080000.md"},
    approval_status="approved",
    result="pending",
  )

AFTER send completes:
  log_action(
    action_type="email_sent",
    actor="email-mcp",
    target="recipient@example.com",
    parameters={"message_id": "msg_abc123", "subject": "Re: your query"},
    approval_status="approved",
    result="success",   # or "fail"
    error=None,         # or error message on failure
  )
```

### Pattern C — Error logging

```
On exception during MCP action:
  log_action(
    action_type="error",
    actor="linkedin-mcp",
    target="LinkedIn feed",
    parameters={"exception": "TimeoutError", "approval_file": "APPROVAL_post_...md"},
    approval_status="approved",
    result="fail",
    error="Playwright timeout after 30s — LinkedIn selector not found",
  )
```

---

## Python Import Usage

Any Python module can call the logger directly:

```python
from audit_logger import log_action, log_file_write, log_status_transition, log_error

# Full call
log_action(
    action_type="file_write",
    actor="watcher",
    target="needs_action/report.pdf",
    parameters={"size": 4096, "source": "inbox"},
    approval_status="n_a",
    result="success",
)

# Convenience wrappers
log_file_write(actor="watcher", target="needs_action/task.md", size=512, source="inbox")
log_status_transition(actor="task_analyzer", target="task.md", old_status="pending", new_status="processing")
log_error(actor="task_agent", target="task.md", action_type="file_write", error_msg="PermissionError")
```

---

## Log File Location

```
Logs/
  2026-02-25.json     ← today's entries
  2026-02-24.json     ← yesterday's entries
  ...
```

The `Logs/` directory is **excluded from git and cloud sync** via `.gitignore`.
This ensures audit logs never leave the local machine unintentionally.

---

## Audit Table in dashboard.md

The `dashboard-updater` skill reads the last 10 entries via:

```python
from audit_logger import get_recent_actions, format_audit_table
entries = get_recent_actions(10)
table_md = format_audit_table(entries)
```

and writes them into the `## Recent Audit Summary` section of `dashboard.md`.

---

## Privacy & Security Rules

1. **Never log credentials, tokens, passwords, or PII** in `parameters`
2. Log email *subjects* and *recipients* only — never log email *body* content
3. Log first 60 characters of LinkedIn post text — not the full content
4. Log file *names* and *sizes* — not file *contents*
5. `Logs/` must stay local — never push to git or sync to cloud

---

## References

- `audit_logger.py` — Python implementation (importable, vault root)
- `dashboard-updater` SKILL.md → Operation I: Update Audit Table
- `.gitignore` — `Logs/` excluded from version control
- `system_logs.md` — Existing human-readable log (separate from structured audit)
