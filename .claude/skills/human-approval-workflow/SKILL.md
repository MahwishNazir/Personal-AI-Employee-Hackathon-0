---
name: human-approval-workflow
description: Manages the full approval lifecycle for sensitive tasks. Creates structured approval request files in Pending_Approval/, monitors Approved/ and Rejected/ for human decisions, executes approved actions via mcp-action-handler, and logs all outcomes. This skill is the mandatory gate before ANY external write action.
---

# Human Approval Workflow Skill

## Purpose

No external action — email, LinkedIn post, payment, calendar invite, or any MCP write —
may be executed without passing through this skill first.

This skill **extends** the `human-in-the-loop` skill with a full lifecycle:
creation → monitoring → execution → archival.

**Silver Tier pipeline position:** Step 3 of 6 (for sensitive tasks)

```
[plan-creation-workflow]
        ↓
[human-approval-workflow]  ← YOU ARE HERE
        ↓  (human moves file to Approved/)
[mcp-action-handler]
        ↓
[dashboard-updater]
```

---

## Phase A — Create Approval Request

### Trigger

Invoked when `plan-creation-workflow` flags a task as `"sensitive": true`.

### Approval file location and name

```
Pending_Approval/APPROVAL_<action-type>_<YYYYMMDDTHHMMSS>.md
```

Examples:
- `APPROVAL_post_linkedin_20260222T080000.md`
- `APPROVAL_send_email_20260222T200000.md`
- `APPROVAL_make_payment_20260222T143000.md`

### Approval file template

```markdown
---
type: approval-request
action: <send_email | post_linkedin | make_payment | send_message | other>
source_task: <filename from needs_action/>
plan_file: plans/Plan_<task-slug>.md
requested_by: Claude (Silver Cycle)
timestamp: <ISO-8601-UTC>
priority: <high | medium | low>
status: pending
---

# Approval Request — <action-type>

## Proposed Action
<One clear sentence: exactly what will happen if approved>

## Draft Content
<Full text of email / post / message / payment details — ready to send as-is>

## Context
<Why this action is needed — reference the source task and company_handbook.md rules>

## Risk Assessment
| Risk | Level | Notes |
|------|-------|-------|
| Irreversibility | <High/Med/Low> | <e.g. "Email cannot be unsent"> |
| Audience | <High/Med/Low> | <e.g. "Public LinkedIn post"> |
| Financial | <High/Med/Low> | <e.g. "No money involved"> |
| Reputation | <High/Med/Low> | <e.g. "Professional tone confirmed"> |

**Overall Risk:** <High | Medium | Low>

## Human Instructions
1. Review the draft content above carefully
2. Edit the draft directly in this file if changes are needed
3. **To approve:** Move this file to `Approved/`
4. **To reject:** Move this file to `Rejected/` — add a note explaining why

> Claude will NOT act until this file appears in `Approved/`.
> Claude will NOT retry rejected actions without new instructions.
```

### Companion meta file

Write `Pending_Approval/APPROVAL_<...>.md.meta.json`:
```json
{
  "name": "APPROVAL_<...>.md",
  "action": "<action-type>",
  "source_task": "<filename>",
  "plan": "plans/Plan_<task-slug>.md",
  "status": "pending_approval",
  "created_at": "<ISO-8601-UTC>",
  "priority": "<high|medium|low>"
}
```

### After creating the approval file

1. Call `dashboard-updater` → add row to **Pending Approvals** table
2. Update `needs_action/<task>.meta.json` → `"status": "awaiting_approval"`
3. Log to `system_logs.md`: `[APPROVAL CREATED] <filename> — <action-type>`
4. Write structured audit entry:
   ```python
   from audit_logger import log_action
   log_action(
       action_type="approval_created",
       actor="claude",
       target="Pending_Approval/<APPROVAL_filename>.md",
       parameters={"action_type": "<action>", "source_task": "<task>",
                   "priority": "<priority>"},
       approval_status="pending",
       result="success",
   )
   ```
5. **Stop processing this task** — do not proceed to mcp-action-handler

---

## Phase B — Monitor for Human Decision

### On each Silver Cycle run, before creating new approvals

Scan `Approved/` and `Rejected/` for any `APPROVAL_*.md` files.

#### If file found in Approved/

1. Read the file — use the (possibly human-edited) **Draft Content** section
2. Load companion `.meta.json` for action type and source task
3. Write audit entry before handing off:
   ```python
   log_action(
       action_type="approval_approved",
       actor="claude",
       target="Approved/<APPROVAL_filename>.md",
       parameters={"action_type": "<action>", "source_task": "<task>"},
       approval_status="approved",
       result="success",
   )
   ```
4. Call `mcp-action-handler` with the approved content
5. After execution: move approval file to `done/`
6. Update `needs_action/<source-task>.meta.json` → `"status": "complete"`
7. Move source task file to `done/`
8. Call `dashboard-updater` → move from Pending Approvals → Completed
9. Log to `system_logs.md`: `[APPROVED + EXECUTED] <filename>`

#### If file found in Rejected/

1. Read any human note in the file
2. Write audit entry:
   ```python
   log_action(
       action_type="approval_rejected",
       actor="claude",
       target="Rejected/<APPROVAL_filename>.md",
       parameters={"action_type": "<action>", "source_task": "<task>",
                   "human_note": "<note if present>"},
       approval_status="rejected",
       result="skip",
   )
   ```
3. Update `needs_action/<source-task>.meta.json` → `"status": "rejected"`
4. Move source task file to `done/` (with rejected status)
5. Call `dashboard-updater` → remove from Pending Approvals, log rejection
6. Log to `system_logs.md`: `[REJECTED] <filename> — <human note if present>`
7. **Do NOT retry** — require explicit new instructions to reprocess

---

## Phase C — Execution Handoff

When an approval is confirmed, call `mcp-action-handler` with:
```json
{
  "action": "<action-type>",
  "content": "<approved draft text>",
  "source_task": "<filename>",
  "approval_file": "Approved/APPROVAL_<...>.md"
}
```

---

## Priority Rules

| Priority | Condition | Effect |
|----------|-----------|--------|
| `high` | Contains "urgent", monetary value, or deadline | Process first in monitoring phase |
| `medium` | External communication (email, LinkedIn) | Normal queue |
| `low` | Low-risk writes (calendar, note) | Process last |

---

## What Claude Must NEVER Do

- Move files from `Pending_Approval/` to `Approved/` itself
- Execute an action before the file reaches `Approved/`
- Delete or overwrite a `Rejected/` file
- Re-create an approval for a rejected action without new user instructions
- Send, post, or pay anything in `--print` / automated mode without approval

---

## References

- `.claude/skills/human-in-the-loop/SKILL.md` — Core HITL rules (this skill extends them)
- `mcp-action-handler` skill — called after approval confirmed
- `dashboard-updater` skill — called after every phase transition
- `company_handbook.md` — Organisation-specific sensitivity rules
- `CLAUDE.md` — "Key Conventions" → status flow
