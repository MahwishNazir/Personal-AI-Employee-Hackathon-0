---
name: human-in-the-loop
description: Intercepts any sensitive or external write action (send email, post on social media, make payments, MCP write calls) and creates an approval request file in /Pending_Approval/ instead of executing directly. Always apply before any external action.
---

# Human-in-the-Loop (HITL) Approval Skill

## Core Rule

For **ANY** sensitive or external write action, Claude **MUST NEVER** execute the action directly.

**Sensitive actions include (but are not limited to):**
- Sending emails or replying to messages
- Posting on LinkedIn, Twitter/X, Facebook, Instagram, or any social platform
- Making payments, transferring money, or recording financial transactions
- Updating accounting records or invoices
- Scheduling meetings or sending calendar invites on behalf of someone
- Any action performed via an MCP server that interacts with the real world (file writes to external systems, API calls that create/update/delete data)

**Instead, ALWAYS create an approval request file in `/Pending_Approval/`.**

---

## Why This Matters

Human oversight prevents:
- Accidental or unauthorized actions in production systems
- Compliance violations (financial, legal, communications)
- Reputation damage from premature or incorrect public posts
- Irreversible mistakes that cannot be undone after execution

This skill enforces a clear human checkpoint before any consequence-bearing action is taken.

---

## Approval File Format

Create a Markdown file in `/Pending_Approval/` named:

```
APPROVAL_[action-type]_[timestamp-or-id].md
```

Examples: `APPROVAL_send_email_20260221T143000.md`, `APPROVAL_post_linkedin_001.md`

**File content template:**

```markdown
---
type: approval-request
action: send_email / post_linkedin / make_payment / etc.
requested_by: Claude
timestamp: [ISO datetime, e.g. 2026-02-21T14:30:00Z]
priority: high / medium / low
status: pending
---

## Proposed Action
[Clear one-sentence summary of what Claude wants to do]

## Details / Draft Content
[Full draft of email body, post text, payment amount & recipient, etc.]

## Reason / Context
[Why this action is needed, referencing Company_Handbook.md rules or the Needs_Action/ item that triggered this]

## Risk Level
[Low / Medium / High — brief explanation of what could go wrong if executed incorrectly]

## Human Instructions
- Review the draft above
- If OK → move this file to /Approved/
- If not OK → move this file to /Rejected/ and add a note explaining why
- Claude will check these folders in future runs and act only on /Approved/ files
```

---

## File Movement Rules

| Folder | Who moves files | What Claude does |
|---|---|---|
| `/Pending_Approval/` | Claude creates; human reviews | Lists in Dashboard.md "Pending Approvals" section |
| `/Approved/` | Human moves here to approve | Executes the action via MCP or other means in the next cycle |
| `/Rejected/` | Human moves here to reject | Logs the rejection, updates Dashboard.md, does NOT retry without new instructions |

**Claude must never move approval files itself.** Claude only:
1. Creates files in `/Pending_Approval/`
2. Reads from `/Approved/` to trigger execution
3. Reads from `/Rejected/` to learn and avoid repeating

After successful execution of an approved action:
- Move the original task file to `/Done/`
- Log the outcome in `/Logs/` with timestamp and result

---

## Dashboard Integration

After creating any approval request, update `Dashboard.md` to include a **Pending Approvals** section:

```markdown
## Pending Approvals

| File | Action | Priority | Timestamp |
|------|--------|----------|-----------|
| APPROVAL_send_email_20260221T143000.md | send_email | high | 2026-02-21T14:30:00Z |
```

Remove entries from this table once the file has been moved to `/Approved/` or `/Rejected/`.

---

## Integration Notes

- **Priority:** This skill has the **highest priority** — always apply it before any MCP tool call or external write action, regardless of what other skills or agents are active.
- **Reference:** Check `Company_Handbook.md` for additional rules on what constitutes a "sensitive" action in this organization's context.
- **No exceptions:** Even if an action seems minor or routine, if it writes to an external system or sends a communication, the approval flow applies.

---

## Trigger Examples

1. **Drafting a client email reply**
   A task in `Needs_Action/` asks Claude to reply to a client inquiry. Claude drafts the reply and creates `APPROVAL_send_email_[timestamp].md` in `/Pending_Approval/` with the full draft body — it does not send the email.

2. **Preparing a LinkedIn sales post**
   Claude is asked to write and publish a post promoting a new service. Claude creates `APPROVAL_post_linkedin_[timestamp].md` with the full post text, hashtags, and target audience notes — it does not publish the post.

3. **Recording a bank transfer**
   An invoice is marked paid and needs a matching entry in the accounting system. Claude creates `APPROVAL_make_payment_[timestamp].md` detailing the amount, sender, recipient, and reference — it does not write to the accounting system.
