---
name: mcp-action-handler
description: Executes real-world actions using MCP servers after human approval has been confirmed. Handles email sending via email-mcp, LinkedIn posting via Playwright, and browser automation. Logs all outcomes and moves completed approvals to done/. Only called by human-approval-workflow after an approval file is confirmed in Approved/.
---

# MCP Action Handler Skill

## Purpose

This skill is the **execution layer** of the Silver Cycle pipeline.
It only runs after `human-approval-workflow` has confirmed a file in `Approved/`.
It never creates its own approval requests — it only executes already-approved actions.

**Silver Tier pipeline position:** Step 4 of 6

```
[human-approval-workflow]  (provides approved content)
        ↓
[mcp-action-handler]  ← YOU ARE HERE
        ↓
[dashboard-updater]
```

---

## Available MCP Servers

### 1. email-mcp (Gmail)

**Config:** `email-mcp/mcp.json`
**Binary:** `node email-mcp/index.js`
**Auth:** `gmail_token.json` (OAuth 2.0)
**Capability:** Send emails via Gmail API

**Use for:** Approval actions of type `send_email`

**Invocation pattern:**
```json
{
  "tool": "send_email",
  "to": "<recipient>",
  "subject": "<subject>",
  "body": "<approved email body>",
  "html": false
}
```

**Failure handling:** If send fails, log error to `system_logs.md`, move approval back to `Pending_Approval/` with error note, notify via dashboard.

---

### 2. LinkedIn via Playwright

**Script:** `.claude/skills/linkedin-poster/linkedin_poster.py`
**Session:** `.linkedin_session/` (Playwright persistent context)
**Capability:** Post text content to LinkedIn feed

**Use for:** Approval actions of type `post_linkedin`

**Invocation pattern:**
```python
from .claude.skills.linkedin-poster.linkedin_poster import post_to_linkedin
success = post_to_linkedin(approved_post_text)
```

**Prerequisites:**
- `playwright` installed: `pip install playwright`
- Chromium installed: `python -m playwright install chromium`
- LinkedIn session saved: `python linkedin_watcher.py --login`

**Failure handling:** If Playwright fails, log error, do NOT retry automatically.
Create a new `APPROVAL_post_linkedin_retry_<timestamp>.md` with failure note for human review.

---

### 3. Browser MCP (General Automation)

**Use for:** Any web-based action not covered by specific MCP servers
(form submissions, web scraping, authenticated web actions)

**Invocation:** Via Playwright — launch browser with the relevant persistent session,
navigate to target URL, perform the action.

**Prerequisite:** Must document the exact URL and DOM selectors in the approval file
before human approves.

---

## Execution Protocol

### Step 1 — Read approved file

Parse the `Approved/APPROVAL_<...>.md`:
1. Extract `action` from YAML frontmatter
2. Extract **Draft Content** section (use human-edited version if modified)
3. Load companion `.meta.json` for `source_task` and `priority`

### Step 2 — Select MCP server

| Action type | MCP server | Script |
|-------------|-----------|--------|
| `send_email` | email-mcp | `email-mcp/index.js` |
| `post_linkedin` | Playwright | `linkedin_poster.py` → `post_to_linkedin()` |
| `send_whatsapp` | Playwright | `whatsapp_watcher.py` browser context |
| `browser_action` | Playwright | ad-hoc automation |

### Step 3 — Execute

Before running the action, write a pre-execution audit entry:
```python
from audit_logger import log_action
log_action(
    action_type="mcp_call",
    actor="<mcp-name>",           # e.g. "email-mcp" or "linkedin-mcp"
    target="<recipient or URL>",
    parameters={"action": "<action-type>", "approval_file": "<APPROVAL_...md>"},
    approval_status="approved",
    result="pending",
)
```

Run the action. Capture:
- Exit code / success boolean
- Response data (message ID, post URL, etc.)
- Timestamp of execution
- Any error messages

### Step 4 — Log result

Write to `system_logs.md`:
```
[MCP-ACTION] <action-type> | source: <task-name> | success: <true/false>
  Result: <message ID / post URL / error>
  Executed: <ISO-8601-UTC>
```

Then write a structured audit entry (use the correct `action_type` for the outcome):
```python
log_action(
    action_type="email_sent",     # or "linkedin_post" / "error" / etc.
    actor="<mcp-name>",
    target="<recipient or URL>",
    parameters={"message_id": "<id>", "subject": "<subject>"},  # never body content
    approval_status="approved",
    result="success",             # or "fail"
    error=None,                   # or error string on failure
)
```

**Privacy rule:** Never log email body content or full LinkedIn post text in `parameters`.
Log only: recipient, subject, message_id (email) or first 60 characters of post (LinkedIn).

### Step 5 — Archive

On **success:**
- Move `Approved/APPROVAL_<...>.md` → `done/APPROVAL_<...>.md`
- Move companion `.meta.json` → `done/`
- Update meta: `"status": "complete"`, add `"executed_at"`, `"result"`
- Update source task meta: `"status": "complete"`
- Move source task file → `done/`

On **failure:**
- Move `Approved/APPROVAL_<...>.md` → `Pending_Approval/APPROVAL_<...>_FAILED.md`
- Add failure details to the file
- Update meta: `"status": "failed"`, add `"error"`, `"failed_at"`
- Call `dashboard-updater` to show failed status

### Step 6 — Call dashboard-updater

Always call `dashboard-updater` after execution, passing:
- Task name
- Action type
- Status (complete / failed)
- Result summary

---

## Idempotency

Before executing any action, check `done/` for a completed approval with the same
`source_task` name. If found, skip and log:
```
[MCP-ACTION SKIP] Already executed for source: <task-name> — skipping duplicate
```

---

## Error Recovery

| Error | Recovery |
|-------|----------|
| MCP server not running | Start server, retry once, then fail gracefully |
| Auth token expired | Log error, do NOT retry, notify human via dashboard |
| Network timeout | Retry once after 10s, then fail gracefully |
| Playwright session missing | Log error with login instructions, do NOT retry |

---

## References

- `email-mcp/mcp.json` — MCP server configuration
- `email-mcp/index.js` — Gmail MCP server entry point
- `.claude/skills/linkedin-poster/linkedin_poster.py` → `post_to_linkedin()`
- `.claude/skills/human-approval-workflow/SKILL.md` — upstream skill
- `company_handbook.md` — Approved action types and constraints
