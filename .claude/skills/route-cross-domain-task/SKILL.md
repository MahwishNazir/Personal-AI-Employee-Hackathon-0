---
name: route-cross-domain-task
description: Reads any needs_action/ task file, classifies it as personal, business, or both domains, applies cross-domain rules (e.g. WhatsApp payment → Odoo invoice check → bank balance), and generates domain-aware Plan files. Runs between multi-watcher-orchestration and plan-creation-workflow.
---

# Route Cross-Domain Task Skill

## Purpose

Not all tasks fit cleanly into "business" or "personal." A WhatsApp message might be
from a client about an invoice, or from a family member about a birthday. This skill
reads each task, classifies its domain, applies domain-specific routing rules, and
creates a correctly-scoped plan so downstream skills act in the right context.

**Silver Tier pipeline position:** Step 1.5 (after multi-watcher-orchestration, before plan-creation-workflow)

```
[multi-watcher-orchestration]
        ↓
[route-cross-domain-task]  ← YOU ARE HERE
        ↓
[plan-creation-workflow]
        ↓
[human-approval-workflow]  (if sensitive)
        ↓
[mcp-action-handler]       (if approved)
        ↓
[dashboard-updater]
```

---

## Domain Classification

### Business Signals (any match → domain includes "business")

| Signal type | Keywords / patterns |
|-------------|---------------------|
| Finance | invoice, payment, bank, transfer, balance, odoo, budget, revenue, profit, expense, refund, receipt, purchase order, statement of work |
| Operations | client, vendor, supplier, contract, project, deadline, milestone, deliverable |
| HR | employee, salary, payroll, leave request, onboard, offboard |
| Sales/CRM | lead, prospect, deal, proposal, quote, crm, b2b, pipeline |
| Communication | board meeting, standup, sprint, retrospective, stakeholder, investor |

### Personal Signals (any match → domain includes "personal")

| Signal type | Keywords / patterns |
|-------------|---------------------|
| Family | family, kids, school, spouse, parent, children, birthday, wedding, anniversary |
| Health | doctor, appointment, health, medicine, hospital, clinic, prescription |
| Lifestyle | vacation, holiday, grocery, home repair, hobby, personal, friends |
| Personal finance | personal loan, rent, utilities, electricity, gas bill |

### Domain Decision Table

| Business signals | Personal signals | Domain |
|-----------------|-----------------|--------|
| ≥ 1 | 0 | `business` |
| 0 | ≥ 1 | `personal` |
| ≥ 1 | ≥ 1 | `both` |
| 0 | 0 | `personal` (default) |

---

## Cross-Domain Rules (MANDATORY)

Rules are evaluated **CD-1 → CD-6 in order**. The first matching rule wins.

### Rule CD-1: WhatsApp Payment Request

**Trigger:** Source = `whatsapp` AND monetary pattern present AND business finance keywords match.

**Steps (in order):**
1. Check Odoo for an open invoice matching the contact/amount (read-only API call).
2. If invoice found → link it in the plan and flag for human approval.
3. Check current bank balance (read-only) and include in plan context.
4. Create `Plan_<slug>.md` with `domain = business`, `sensitive = true`.
5. Route **immediately** to `human-approval-workflow`.

**Do NOT process payment without confirmed human approval.**

---

### Rule CD-2: WhatsApp Personal Message with Money Mention

**Trigger:** Source = `whatsapp` AND personal signal present AND monetary pattern.

**Steps:**
1. Classify as `both` domain.
2. Flag as sensitive (monetary value).
3. Create dual plan: personal context + financial verification checklist.
4. Route to `human-approval-workflow`.

---

### Rule CD-3: LinkedIn Message from Contact

**Trigger:** Source = `linkedin` AND message type is connection_request or direct message.

**Steps:**
1. Check if sender appears in any existing `needs_action/` or `done/` files as a known client.
2. If known business contact → classify as `business`.
3. If unknown → classify as `personal` (networking default).
4. Create plan with LinkedIn-appropriate checklist.

---

### Rule CD-4: Gmail Invoice or Contract

**Trigger:** Source = `email` AND content contains: invoice, contract, purchase order, statement of work, agreement.

**Steps:**
1. Always classify as `business`.
2. Flag as sensitive.
3. Include Odoo cross-check step in plan: "Verify against Odoo records before acknowledging."
4. Route to `human-approval-workflow`.

---

### Rule CD-5: Dual-Domain Conflict

**Trigger:** Domain = `both` (both business and personal signals present).

**Steps:**
1. Split into **two** plan files:
   - `Plan_PERSONAL_<slug>.md` — personal action items only
   - `Plan_BUSINESS_<slug>.md` — business action items only
2. Update `.meta.json` with `"domain": "both"` and both plan paths.
3. Each plan routes independently through the pipeline.

---

### Rule CD-6: Urgent Business Task

**Trigger:** Urgent keywords present (`urgent`, `asap`, `immediately`, `deadline`, `critical`) AND domain is `both` or `business`.

**Steps:**
1. Add `"priority": "high"` to `.meta.json`.
2. Add ⚡ URGENT tag to plan title.
3. Route to `human-approval-workflow` regardless of sensitivity.

---

## Instructions

### Step 1 — Find pending tasks

Scan `needs_action/` for all `.meta.json` files where `"status": "pending"`.
For each, load the companion task file.

### Step 2 — Extract domain signals

Run keyword matching across the full task content and any metadata fields
(subject, sender, body_preview):

```python
from skills.route_cross_domain import classify_domain, apply_cross_domain_rules

domain, signals = classify_domain(content, meta)
rule_action = apply_cross_domain_rules(domain, signals, meta)
```

**Script reference:** `skills/route_cross_domain.py` → `classify_domain()` + `apply_cross_domain_rules()`

### Step 3 — Apply cross-domain rules

Evaluate CD-1 through CD-6 in order. First match wins. Record `rule_applied` in meta.

### Step 4 — Generate domain-aware plan(s)

Use the plan template from `plan-creation-workflow` SKILL.md with these added fields:

```markdown
**Domain:** personal | business | both
**Domain Signals:** [comma-separated matched keywords]
**Cross-Domain Rule:** CD-N — <rule name>
**Priority:** normal | high
```

For `both` domain (Rule CD-5), create **two** plan files.

### Step 5 — Update meta.json

```json
{
  "status": "processing",
  "domain": "personal|business|both",
  "domain_signals": ["keyword1", "keyword2"],
  "cross_domain_rule": "CD-1|...|none",
  "priority": "normal|high",
  "sensitive": true|false,
  "plans": ["plans/Plan_<slug>.md"],
  "route": "human-approval-workflow|plan-creation-workflow|split"
}
```

### Step 6 — Route

| Domain | Rule fired | Route to |
|--------|-----------|----------|
| `business` | CD-1 (payment) | `human-approval-workflow` IMMEDIATELY |
| `business` | CD-4 (invoice) | `human-approval-workflow` |
| `personal` | none | `plan-creation-workflow` → direct execute |
| `both` | CD-5 | Split plans → each routes independently |
| any | CD-6 (urgent) | `human-approval-workflow` |
| `personal`/`business` | none, not sensitive | `plan-creation-workflow` |

### Step 7 — Log and audit

```python
from audit_logger import log_action

log_action(
    action_type="cross_domain_route",
    actor="claude",
    target=f"needs_action/{filename}",
    parameters={
        "domain": domain,
        "rule": rule_action["rule_applied"],
        "plans": plan_paths,
        "priority": rule_action["priority"],
    },
    approval_status="n_a",
    result="success",
)
```

---

## Callable Entry Point

```python
from skills.route_cross_domain import run

count = run(vault_root=".")   # returns int — number of tasks processed
```

Or from the command line:
```bash
python skills/route_cross_domain.py [vault_root]
```

---

## Output Contract

For every task processed, this skill MUST produce:
1. One plan file (or two if `domain = both`)
2. `.meta.json` updated with `domain`, `domain_signals`, `cross_domain_rule`, `priority`, `sensitive`, `route`
3. One `log-action` audit entry
4. Routing decision recorded in each plan's "Agent Notes" section

---

## References

- `skills/route_cross_domain.py` — Domain classifier + rule engine (callable code)
- `company_handbook.md` — Section 9 (Cross-Domain Routing Rules)
- `.claude/skills/plan-creation-workflow/SKILL.md` — Plan template
- `CLAUDE.md` — Pipeline overview and key conventions
- `audit_logger.py` — `log_action()` signature
