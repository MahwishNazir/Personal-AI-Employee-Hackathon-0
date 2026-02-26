# Company Handbook

## Rules

---

## Section 1 — Core Principles

1. **Human approval gates all external writes.** Never send email, post to
   LinkedIn, make payments, or call any external write API without a confirmed
   file in `Approved/`. This is non-negotiable.

2. **No silent failures.** Every error — transient or permanent — must be
   logged via `log-action` and escalated through the appropriate error-recovery
   skill. Swallowing exceptions without logging is forbidden.

3. **No data loss.** If an action cannot be executed, its full payload must be
   preserved in `deferred_queue.json` before returning. Never discard a task.

4. **Privacy by default.** Never log passwords, OAuth tokens, or full email
   bodies. Log subjects, senders, and first-60-char previews only.

5. **Audit everything.** Every consequential file write, status change, MCP
   call, or approval event must produce a `log-action` entry in `Logs/`.

---

## Section 2 — Error Handling (MANDATORY)

Every skill and watcher MUST follow this three-tier escalation ladder whenever
an action fails. Skipping any tier is a policy violation.

### Tier 1 — Handle_Transient_Error (always first)

**When:** Any network, API, rate-limit, or connection error.

**What to do:**
1. Invoke the `handle-transient-error` skill.
2. Retry the action up to **5 times** with exponential backoff (1→2→4→8→16s).
3. Log every attempt via `log-action`.
4. If the action succeeds on any retry → continue normally.
5. If all 5 retries fail → escalate to Tier 2 or Tier 3.

**Error types that trigger Tier 1:**
- HTTP 429, 500, 502, 503, 504
- `ConnectionRefusedError`, `TimeoutError`, `socket.timeout`
- Gmail API quota exceeded
- LinkedIn Playwright timeout
- Email MCP `ECONNREFUSED`

**Error types that do NOT trigger Tier 1 (fix the root cause instead):**
- HTTP 400, 401, 403 — bad request or auth failure
- `FileNotFoundError`, `TypeError`, `AttributeError`
- JSON parse errors

### Tier 2 — Queue_For_Later (non-critical tasks)

**When:** Tier 1 exhausted AND the failed task is non-critical (no payment,
no time-sensitive external write, no system-critical action).

**What to do:**
1. Check `retry_count` in the task's `.meta.json` sidecar.
2. If `retry_count < 3`: invoke `queue-for-later`.
   - Creates `RETRY_<timestamp>_<original>.md` in `needs_action/`.
   - Sets `retry_after` to 1 hour from now.
   - Increments `retry_count`.
3. If `retry_count >= 3`: treat as critical → escalate to Tier 3.

### Tier 3 — Graceful_Degrade (critical or exhausted tasks)

**When:** Tier 1 exhausted AND (action is critical OR task has exceeded max
retries OR service is confirmed permanently unavailable).

**What to do:**
1. Invoke `graceful-degrade`.
2. Append the full action payload to `deferred_queue.json`.
3. Create `ALERT_critical_failure_<timestamp>.md` in `Pending_Approval/`.
4. Log the alert creation via `log-action`.
5. Continue the Silver Cycle — do not halt.

---

## Section 3 — Sensitive Action Rules

| Action type | Required gate |
|-------------|--------------|
| Send email | `human-in-the-loop` → `human-approval-workflow` |
| Post to LinkedIn | `human-in-the-loop` → `human-approval-workflow` |
| Make payment | `human-in-the-loop` → `human-approval-workflow` |
| Delete files | `human-in-the-loop` → `human-approval-workflow` |
| Call Odoo API (write) | `human-in-the-loop` → `human-approval-workflow` |
| Call external webhooks | `human-in-the-loop` → `human-approval-workflow` |
| Read-only API calls | No approval needed |

Claude NEVER moves files to `Approved/` or `Rejected/` — only humans do.

---

## Section 4 — Process Health

All long-running watchers must be monitored by `watchdog.py`. If the watchdog
is not running:

1. At the start of each Silver Cycle, Claude reads `watchdog_status.json`.
2. If the file is absent or stale (>5 minutes old), Claude creates
   `ALERT_watchdog_down_<timestamp>.md` in `Pending_Approval/`.
3. Claude logs the alert via `log-action` and continues the cycle.

**Process restart authority:** Only the watchdog daemon (or a human) may restart
watchers. Claude may instruct the user to run `python watchdog.py` but must not
attempt to start background processes itself.

---

## Section 5 — deferred_queue.json Management

- Location: `vault_root/deferred_queue.json`
- Format: JSON array of deferred action entries.
- Status values: `deferred` | `retried` | `resolved` | `dismissed`
- Claude reads this file at the start of each Silver Cycle and logs how many
  entries have status `deferred` (unresolved).
- Human moves ALERT files to `Approved/` to trigger retry via `mcp-action-handler`.
- Human moves ALERT files to `Rejected/` to dismiss. Update entry status to
  `dismissed` manually.

---

## Section 6 — Communication Standards

- **Tone:** Professional, concise, factual.
- **LinkedIn posts:** 800–1300 characters, no markdown bold (`**`), no hashtag
  spam (max 3 relevant hashtags), genuine call-to-action.
- **Email replies:** Mirror the formality level of the incoming email.
- **Approval files:** Always include a Risk Assessment table and human-readable
  instructions. Never assume the human knows the technical context.

---

## Section 7 — File Naming Conventions

| File type | Pattern |
|-----------|---------|
| Task files | `<SOURCE>_<ID>_<slug>.md` |
| Retry files | `RETRY_<YYYYMMDDTHHMMSS>_<original>.md` |
| Plan files | `Plan_<original_slug>.md` |
| Approval requests | `APPROVAL_<action>_<YYYYMMDDTHHMMSS>.md` |
| Critical alerts | `ALERT_<type>_<YYYYMMDDTHHMMSS>.md` |
| Audit logs | `Logs/YYYY-MM-DD.json` |

All task files MUST have a `.meta.json` sidecar with the same base name.

---

## Section 9 — Cross-Domain Routing Rules

Every task that enters the pipeline belongs to a domain: **personal**, **business**, or **both**.
The `route-cross-domain-task` skill determines this before any plan is created.

### 9.1 Domain Classification

| Domain | Signal types |
|--------|-------------|
| `business` | Invoice, payment, Odoo, client, contract, vendor, CRM, HR, budget, revenue |
| `personal` | Family, health, school, grocery, vacation, friends, lifestyle |
| `both` | Business AND personal signals both present in same task |
| default | No signals matched → `personal` |

### 9.2 Cross-Domain Rules (CD-1 to CD-6)

Rules are checked in order. **First match wins.**

| Rule | Trigger | Required Action | Route |
|------|---------|----------------|-------|
| **CD-1** | WhatsApp + payment/invoice keyword + monetary pattern | 1. Check Odoo for open invoice (read-only). 2. Check bank balance (read-only). 3. Include both in plan. | `human-approval-workflow` IMMEDIATELY |
| **CD-2** | WhatsApp + personal signal + monetary pattern | Classify as `both`. Create dual plan. Flag sensitive. | `human-approval-workflow` |
| **CD-3** | LinkedIn message or connection request | Look up sender in done/ history. Known client → business. Unknown → personal. | `plan-creation-workflow` |
| **CD-4** | Gmail + invoice/contract/purchase order | Always classify `business`. Add Odoo cross-check step to plan. | `human-approval-workflow` |
| **CD-5** | Domain = `both` (business + personal signals both present) | Split into two plan files: `Plan_PERSONAL_<slug>.md` + `Plan_BUSINESS_<slug>.md`. Each routes independently. | `split` |
| **CD-6** | Urgent keywords (`urgent`, `asap`, `deadline`) + domain is `business` or `both` | Add ⚡ URGENT tag. Set `priority: high`. Escalate regardless of sensitivity. | `human-approval-workflow` |

### 9.3 WhatsApp Payment Protocol (CD-1 in detail)

This is the most critical cross-domain scenario:

```
WhatsApp message with payment/transfer request
    │
    ▼
Step 1 — Odoo invoice check (READ-ONLY)
    │  Found matching invoice → record invoice ID + amount in plan
    │  No invoice found     → note "no matching Odoo invoice" in plan
    ▼
Step 2 — Bank balance check (READ-ONLY)
    │  Record available balance in plan
    │  Confirm balance ≥ requested amount
    ▼
Step 3 — Create Plan with domain=business, sensitive=true
    ▼
Step 4 — Route to human-approval-workflow
    │
    └── Human MUST confirm before any payment is made
```

**Claude NEVER initiates a payment. Only humans approve payments.**

### 9.4 Dual-Domain (CD-5) Plan Splitting

When a task triggers Rule CD-5, two separate plan files are generated:

```
needs_action/task.md
    ├── plans/Plan_PERSONAL_task.md   → personal checklist → direct execute
    └── plans/Plan_BUSINESS_task.md   → business checklist → human-approval-workflow
```

Both plans are linked in the `.meta.json` under `"plans": [...]`. Each plan
routes and completes independently. The task file is not moved to `done/`
until **both** plans are complete.

### 9.5 Domain Labels in Dashboard

All dashboard tables include a **Domain** column:
- `P` = personal
- `B` = business
- `P+B` = both (split plan)

---

## Section 8 — Escalation Decision Tree (Quick Reference)

```
Action fails
    │
    ▼
Is it a transient error? (network, timeout, rate-limit)
    │ YES                          │ NO
    ▼                              ▼
handle-transient-error         Fix root cause or invoke graceful-degrade
    │
    ├── Retry succeeds → continue normally
    │
    └── All 5 retries fail
            │
            ▼
        Is the action critical?
            │ YES                           │ NO
            ▼                              ▼
        graceful-degrade              retry_count < 3?
        (→ deferred_queue.json         │ YES              │ NO
           + Pending_Approval/)        ▼                  ▼
                                  queue-for-later    graceful-degrade
                                  (→ RETRY_ file)    (task abandoned)
```
