---
name: graceful-degrade
description: >
  On a critical or unrecoverable failure (e.g. Odoo down, email-mcp unreachable,
  max retries exceeded), save the failed action to deferred_queue.json and
  create an ALERT_critical_failure_*.md in Pending_Approval/ for human review.
  No data is lost. No action is silently dropped.
---

# Graceful Degrade

## Purpose

When a critical external service is unavailable and all retries are exhausted,
this skill ensures:
1. **No data loss** — the failed action is serialised to `deferred_queue.json`.
2. **Human visibility** — an ALERT file appears in `Pending_Approval/` so you
   are notified immediately and can decide to retry, dismiss, or fix manually.
3. **Pipeline continuity** — the rest of the Silver Cycle continues; only the
   failed action is deferred, not the entire run.

**Pipeline position:** Terminal escalation path. Called after `handle-transient-error`
exhausts retries on a critical action, OR when a catastrophic error occurs that
cannot be safely retried (auth failure, disk full, service permanently down).

---

## When To Invoke This Skill

Invoke `graceful-degrade` when ANY of the following are true:
- `handle-transient-error` exhausted all 5 retries **and** the action is critical
  (payment, email send, external write, Odoo API call, MCP server call).
- `queue-for-later` would be invoked but `retry_count >= max_retries` (task abandoned).
- A service is confirmed down (HTTP 503 + retry-after > 1 hour, Odoo maintenance page, etc.).
- A critical file or credential is missing (gmail_token.json, linkedin session).
- Any failure that would cause data loss if not explicitly preserved.

**Do NOT invoke** for:
- Transient errors still within retry budget (use `handle-transient-error`).
- Tasks with remaining retries (use `queue-for-later`).
- Validation or logic errors that require a code fix (investigate directly).

---

## Instructions

### Step 1 — Log the Critical Failure

Call the **log-action** skill with:
```
action_type     : "critical_failure"
actor           : <current actor>
target          : <failed service or action, e.g. "email-mcp", "odoo_api">
parameters      : {
  "failed_action" : "<action slug>",
  "service"       : "<service name>",
  "error"         : "<full error message>",
  "payload_size"  : <byte count of deferred payload>
}
result          : "fail"
```

### Step 2 — Append to deferred_queue.json

Read `deferred_queue.json` at vault root (create if absent). Append a new entry:

```json
{
  "id": "deferred_<YYYYMMDDTHHMMSS>",
  "action": "<action slug, e.g. send_email>",
  "service": "<service name, e.g. email-mcp>",
  "error": "<error message>",
  "actor": "<actor>",
  "payload": {
    // Full action payload — everything needed to re-attempt the action
    // e.g. for send_email: { "to": "...", "subject": "...", "body": "..." }
    // e.g. for post_linkedin: { "post_text": "...", "source_task": "..." }
  },
  "queued_at": "<ISO timestamp UTC>",
  "status": "deferred"    // deferred | retried | resolved | dismissed
}
```

Write the updated array back to `deferred_queue.json` atomically.

**Privacy rule:** Never include passwords, OAuth tokens, or PII beyond what is
necessary to re-execute the action (e.g. email address is OK; auth tokens are NOT).

### Step 3 — Create the ALERT File in Pending_Approval/

Create `Pending_Approval/ALERT_critical_failure_<YYYYMMDDTHHMMSS>.md`:

```markdown
---
type: alert
action: critical_failure
failed_action: <action slug>
service: <service name>
actor: <actor>
timestamp: <ISO timestamp>
priority: high
status: pending
deferred_entry_id: deferred_<timestamp>
---

# ALERT: Critical System Failure — Action Required

## What Failed

| Field | Value |
|-------|-------|
| **Action** | `<action slug>` |
| **Service** | `<service name>` |
| **Error** | `<error message>` |
| **Time** | <human-readable timestamp> |
| **Deferred ID** | `deferred_<timestamp>` |

## What Was Attempted

```json
<pretty-printed payload>
```

## Current State

The action is saved in `deferred_queue.json` (entry `deferred_<timestamp>`).
No data was lost. Nothing was executed. The pipeline is continuing normally.

## Risk Assessment

| Risk | Level | Notes |
|------|-------|-------|
| Data Loss | Low | Action preserved in deferred_queue.json |
| Service Impact | High | <service> is unavailable |
| Irreversibility | N/A | Action was NOT executed |

## Human Instructions

1. Check whether `<service>` has recovered.
2. **To retry:** Move this file to `Approved/` — system will re-attempt.
3. **To dismiss:** Move this file to `Rejected/`, update `status` in `deferred_queue.json`.
4. **To fix manually:** Resolve the root cause and delete this file.
```

Also write the `.meta.json` sidecar:
```json
{
  "name": "ALERT_critical_failure_<timestamp>.md",
  "action": "critical_failure_alert",
  "failed_action": "<action slug>",
  "service": "<service name>",
  "status": "pending_approval",
  "created_at": "<ISO timestamp>",
  "priority": "high",
  "deferred_entry_id": "deferred_<timestamp>"
}
```

### Step 4 — Log Alert Creation

Call the **log-action** skill with:
```
action_type     : "graceful_degrade_alert_created"
actor           : <current actor>
target          : "Pending_Approval/ALERT_critical_failure_<timestamp>.md"
parameters      : { "deferred_entry_id": "deferred_<timestamp>", "service": "<service>" }
approval_status : "pending"
result          : "success"
```

### Step 5 — Continue the Pipeline

Do NOT halt the Silver Cycle. Log a warning to `system_logs.md`:

```
⚠️ [<timestamp>] GRACEFUL DEGRADE: <action> on <service> deferred. Alert in Pending_Approval/. Pipeline continuing.
```

Then return control to the calling skill or Silver Cycle step.

---

## Retry Path (when human approves)

When the human moves the ALERT file to `Approved/`, the `human-approval-workflow`
skill (Skill 3) detects it and calls `mcp-action-handler` (Skill 4) to re-execute
the deferred action using the payload stored in `deferred_queue.json`.

After successful re-execution, update the `deferred_queue.json` entry:
```json
{ "status": "resolved", "resolved_at": "<ISO timestamp>" }
```

---

## Python Utility

```python
from skills.error_recovery import graceful_degrade

alert_path = graceful_degrade(
    failed_action="send_email",
    error="email-mcp: ECONNREFUSED (port 3001)",
    deferred_payload={
        "to": "ceo@company.com",
        "subject": "Weekly Report",
        "body": "..."
    },
    priority="high",
    actor="claude",
    service_name="email-mcp",
)
print(f"Alert created: {alert_path}")
```

---

## Service-Specific Guidance

| Service | Typical error | Recommended priority |
|---------|--------------|---------------------|
| email-mcp (Node.js) | `ECONNREFUSED :3001` | high |
| Gmail API | `HttpError 503` | medium |
| LinkedIn Playwright | Session expired | medium |
| Odoo API | `ConnectionRefusedError` | high |
| WhatsApp Playwright | QR expired | medium |
| Local file system | `PermissionError`, disk full | high |

---

## Output Contract

| Guarantee | Details |
|-----------|---------|
| No data loss | Failed payload always written to deferred_queue.json |
| Human notified | ALERT file always created in Pending_Approval/ |
| Audit trail | Two log entries: critical_failure + graceful_degrade_alert_created |
| Pipeline continues | Skill never halts the Silver Cycle |
| Retry path available | Human approval → mcp-action-handler re-executes |
| Privacy maintained | Tokens and passwords never written to alert or queue files |
