"""skills/route_cross_domain.py

Cross-domain task router for AI Employee Vault.

Classifies every needs_action/ task as personal, business, or both, then
applies rules CD-1 → CD-6 to determine routing and plan structure.

Public API
----------
classify_domain(content, meta)          -> (domain, signals)
apply_cross_domain_rules(domain, signals, meta) -> rule_action dict
process_task(task_path, vault_root)     -> result dict
run(vault_root)                         -> int  (tasks processed)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# Signal tables
# ──────────────────────────────────────────────────────────────────────────────

BUSINESS_SIGNALS: dict[str, list[str]] = {
    "finance": [
        "invoice", "payment", "bank", "transfer", "balance", "odoo",
        "budget", "revenue", "profit", "expense", "refund", "receipt",
        "purchase order", "po #", "statement of work", "sow",
    ],
    "operations": [
        "client", "vendor", "supplier", "contract", "project", "deadline",
        "milestone", "deliverable", "scope",
    ],
    "hr": [
        "employee", "salary", "payroll", "leave request", "onboard",
        "offboard", "performance review",
    ],
    "sales_crm": [
        "lead", "prospect", "deal", "proposal", "quote", "crm",
        "b2b", "pipeline", "opportunity",
    ],
    "communication": [
        "board meeting", "standup", "sprint", "retrospective",
        "stakeholder", "investor",
    ],
}

PERSONAL_SIGNALS: dict[str, list[str]] = {
    "family": [
        "family", "kids", "school", "spouse", "parent", "children",
        "birthday", "wedding", "anniversary", "baby",
    ],
    "health": [
        "doctor", "appointment", "health", "medicine", "hospital",
        "clinic", "prescription", "therapy",
    ],
    "lifestyle": [
        "vacation", "holiday", "grocery", "home repair", "hobby",
        "personal", "friends", "dinner", "party",
    ],
    "personal_finance": [
        "personal loan", "rent", "utilities", "electricity",
        "gas bill", "subscription",
    ],
}

MONETARY_PATTERN = re.compile(
    r"(\$|£|€|USD|GBP|PKR|rs\.|₹|\d[\d,]*\s*(?:dollars?|pounds?|euros?|rupees?))",
    re.IGNORECASE,
)

URGENT_KEYWORDS = [
    "urgent", "asap", "immediately", "deadline", "critical", "emergency",
]

# Invoice / contract trigger words for CD-4
INVOICE_CONTRACT_WORDS = [
    "invoice", "contract", "purchase order", "po #",
    "statement of work", "sow", "agreement",
]


# ──────────────────────────────────────────────────────────────────────────────
# Domain classification
# ──────────────────────────────────────────────────────────────────────────────

def _match_signals(
    text: str,
    signal_table: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Return matched categories → keyword hits."""
    text_lower = text.lower()
    matched: dict[str, list[str]] = {}
    for category, keywords in signal_table.items():
        hits = [kw for kw in keywords if kw in text_lower]
        if hits:
            matched[category] = hits
    return matched


def classify_domain(content: str, meta: dict) -> tuple[str, dict]:
    """
    Classify a task as 'personal', 'business', or 'both'.

    Parameters
    ----------
    content : str
        Full text of the task file.
    meta : dict
        Parsed .meta.json sidecar.

    Returns
    -------
    (domain, signals)
        domain  — 'personal' | 'business' | 'both'
        signals — {
            'business': {category: [keywords]},
            'personal': {category: [keywords]},
            'monetary': bool,
            'urgent':   bool,
            'source':   str,
        }
    """
    # Enrich text with any subject/sender metadata
    full_text = content
    for field in ("subject", "sender", "title", "body_preview", "notification_text"):
        full_text += " " + meta.get(field, "")

    biz = _match_signals(full_text, BUSINESS_SIGNALS)
    per = _match_signals(full_text, PERSONAL_SIGNALS)
    monetary = bool(MONETARY_PATTERN.search(full_text))
    urgent = any(kw in full_text.lower() for kw in URGENT_KEYWORDS)

    if biz and per:
        domain = "both"
    elif biz:
        domain = "business"
    elif per:
        domain = "personal"
    else:
        domain = "personal"  # default — people tasks

    signals: dict = {
        "business": biz,
        "personal": per,
        "monetary": monetary,
        "urgent": urgent,
        "source": meta.get("source", "inbox"),
    }
    return domain, signals


# ──────────────────────────────────────────────────────────────────────────────
# Cross-domain rule engine
# ──────────────────────────────────────────────────────────────────────────────

def _rule_cd1(domain: str, signals: dict) -> bool:
    """CD-1: WhatsApp payment request."""
    return (
        signals["source"] == "whatsapp"
        and signals["monetary"]
        and bool(signals["business"].get("finance"))
    )


def _rule_cd2(domain: str, signals: dict) -> bool:
    """CD-2: WhatsApp personal + money mention."""
    return (
        signals["source"] == "whatsapp"
        and signals["monetary"]
        and bool(signals["personal"])
    )


def _rule_cd3(domain: str, signals: dict) -> bool:
    """CD-3: LinkedIn contact message."""
    return signals["source"] == "linkedin"


def _rule_cd4(domain: str, signals: dict) -> bool:
    """CD-4: Gmail invoice or contract."""
    finance_hits = signals["business"].get("finance", [])
    ops_hits = signals["business"].get("operations", [])
    all_hits = finance_hits + ops_hits
    return (
        signals["source"] == "email"
        and any(w in all_hits for w in INVOICE_CONTRACT_WORDS)
    )


def _rule_cd5(domain: str, signals: dict) -> bool:
    """CD-5: Dual-domain conflict."""
    return domain == "both"


def _rule_cd6(domain: str, signals: dict) -> bool:
    """CD-6: Urgent business or cross-domain task."""
    return signals["urgent"] and domain in ("both", "business")


# Ordered rule table — (rule_id, check_fn, action_defaults)
_RULES: list[tuple[str, object, dict]] = [
    ("CD-1", _rule_cd1, {
        "sensitive": True,
        "priority": "high",
        "route": "human-approval-workflow",
        "domain_override": "business",
        "odoo_check": True,
        "bank_balance_check": True,
        "description": "WhatsApp payment — Odoo invoice check + bank balance required",
    }),
    ("CD-2", _rule_cd2, {
        "sensitive": True,
        "priority": "normal",
        "route": "human-approval-workflow",
        "domain_override": "both",
        "description": "WhatsApp personal + monetary — dual plan, human approval required",
    }),
    ("CD-3", _rule_cd3, {
        "sensitive": False,
        "priority": "normal",
        "route": "plan-creation-workflow",
        "contact_lookup": True,
        "description": "LinkedIn contact — check if known business contact",
    }),
    ("CD-4", _rule_cd4, {
        "sensitive": True,
        "priority": "normal",
        "route": "human-approval-workflow",
        "domain_override": "business",
        "odoo_check": True,
        "description": "Gmail invoice/contract — Odoo cross-check required before any action",
    }),
    ("CD-5", _rule_cd5, {
        "sensitive": False,    # each split plan sets its own sensitivity
        "priority": "normal",
        "route": "split",
        "split_plans": True,
        "description": "Dual domain — split into PERSONAL and BUSINESS plans",
    }),
    ("CD-6", _rule_cd6, {
        "sensitive": True,
        "priority": "high",
        "route": "human-approval-workflow",
        "description": "Urgent business task — immediate escalation required",
    }),
]


def apply_cross_domain_rules(domain: str, signals: dict, meta: dict) -> dict:
    """
    Evaluate CD-1 → CD-6 in order. First match wins.

    Returns a rule_action dict containing routing instructions and flags.
    """
    for rule_id, check_fn, defaults in _RULES:
        if check_fn(domain, signals):  # type: ignore[operator]
            action: dict = {
                "rule_applied": rule_id,
                "sensitive": defaults.get("sensitive", False),
                "priority": defaults.get("priority", "normal"),
                "route": defaults["route"],
                "description": defaults["description"],
                "domain": defaults.get("domain_override", domain),
            }
            for flag in ("odoo_check", "bank_balance_check", "contact_lookup", "split_plans"):
                if flag in defaults:
                    action[flag] = defaults[flag]
            return action

    # No rule matched — default routing
    default_sensitive = (domain == "business" and signals["monetary"])
    return {
        "rule_applied": "none",
        "domain": domain,
        "sensitive": default_sensitive,
        "priority": "high" if signals["urgent"] else "normal",
        "route": (
            "human-approval-workflow"
            if default_sensitive
            else "plan-creation-workflow"
        ),
        "description": "Default routing — no cross-domain rule matched",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Plan generation
# ──────────────────────────────────────────────────────────────────────────────

def _all_signal_keywords(signals: dict) -> list[str]:
    kws: list[str] = []
    for hits in signals["business"].values():
        kws.extend(hits)
    for hits in signals["personal"].values():
        kws.extend(hits)
    return kws


def _build_checklist(domain: str, rule_action: dict, signals: dict) -> str:
    items = [
        "- [ ] Read and confirm task content understood",
        f"- [ ] Confirmed domain: **{domain}**",
        f"- [ ] Cross-domain rule applied: **{rule_action['rule_applied']}** — {rule_action['description']}",
    ]

    if rule_action.get("odoo_check"):
        items += [
            "- [ ] Query Odoo for matching open invoice (read-only — no write without approval)",
            "- [ ] Record Odoo invoice number, amount, and status in Agent Notes below",
        ]

    if rule_action.get("bank_balance_check"):
        items += [
            "- [ ] Check current bank account balance (read-only)",
            "- [ ] Record available balance in Agent Notes",
            "- [ ] Confirm available balance covers the requested payment amount",
        ]

    if rule_action.get("contact_lookup"):
        items += [
            "- [ ] Search done/ and needs_action/ for prior interactions with this sender",
            "- [ ] Classify as: known client (→ business) or new contact (→ personal/networking)",
            "- [ ] Update domain classification in Agent Notes",
        ]

    if rule_action.get("split_plans"):
        items += [
            "- [ ] Process PERSONAL plan items independently",
            "- [ ] Process BUSINESS plan items independently",
        ]

    if signals.get("monetary"):
        items.append(
            "- [ ] Confirm monetary amounts match expected values before any action"
        )

    if rule_action["sensitive"]:
        items.append("- [ ] Route to human-approval-workflow ⚠️ (REQUIRED before any external action)")

    if rule_action["priority"] == "high":
        items.append("- [ ] ⚡ Flag as HIGH PRIORITY in dashboard immediately")

    items += [
        "- [ ] Execute approved action via mcp-action-handler",
        "- [ ] Update dashboard via dashboard-updater",
        "- [ ] Move task file to done/",
    ]
    return "\n".join(items)


def _generate_plan_content(
    task_name: str,
    content: str,
    meta: dict,
    domain: str,
    signals: dict,
    rule_action: dict,
    label_prefix: str = "",
) -> str:
    ts = datetime.now(timezone.utc).isoformat()
    sensitive_label = "Yes ⚠️" if rule_action["sensitive"] else "No ✅"
    kw_list = ", ".join(_all_signal_keywords(signals)) or "none"
    checklist = _build_checklist(domain, rule_action, signals)
    key_phrases = "\n".join(
        f"- {line.strip()}"
        for line in content.splitlines()[:6]
        if line.strip()
    )
    preview = content[:1200] + ("..." if len(content) > 1200 else "")

    odoo_note = (
        "\nOdoo invoice verification is required before any action is taken."
        if rule_action.get("odoo_check") else ""
    )
    bank_note = (
        "\nBank balance check is required before payment approval."
        if rule_action.get("bank_balance_check") else ""
    )
    split_note = (
        "\nThis task spans personal and business domains and has been split into two plans."
        if rule_action.get("split_plans") else ""
    )

    title = f"{label_prefix}{task_name}" if label_prefix else task_name

    return f"""# Plan: {title}

**Category:** cross-domain-routed
**Source:** {meta.get("source", "inbox")}
**Domain:** {domain.upper()}
**Domain Signals:** {kw_list}
**Cross-Domain Rule:** {rule_action["rule_applied"]} — {rule_action["description"]}
**Priority:** {rule_action["priority"]}
**Sensitive:** {sensitive_label}
**Generated:** {ts}
**Cycle:** Silver

---

## Summary

This task was classified as **{domain}** domain by the Route Cross-Domain Task skill.{odoo_note}{bank_note}{split_note}

## Checklist

{checklist}

## Key Information Extracted

{key_phrases}

## Original Content

```
{preview}
```

## Agent Notes

<!-- Cross-domain rule: {rule_action["rule_applied"]} -->
<!-- Route: {rule_action["route"]} -->
<!-- Priority: {rule_action["priority"]} -->
<!-- Odoo check needed: {rule_action.get("odoo_check", False)} -->
<!-- Bank balance check needed: {rule_action.get("bank_balance_check", False)} -->
"""


# ──────────────────────────────────────────────────────────────────────────────
# Per-task processor
# ──────────────────────────────────────────────────────────────────────────────

def process_task(task_path: str, vault_root: str = ".") -> dict:
    """
    Full pipeline for a single task file.

    Returns a result dict:
        task, domain, rule, priority, sensitive, plans, route
    """
    root = Path(vault_root)
    task_file = Path(task_path)
    meta_file = Path(str(task_file) + ".meta.json")
    plans_dir = root / "plans"
    plans_dir.mkdir(exist_ok=True)

    content = task_file.read_text(encoding="utf-8", errors="replace")
    meta: dict = {}
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}

    domain, signals = classify_domain(content, meta)
    rule_action = apply_cross_domain_rules(domain, signals, meta)
    effective_domain = rule_action.get("domain", domain)

    base_slug = re.sub(r"[^\w\-]", "_", task_file.name)[:60]
    created_plans: list[str] = []

    if rule_action.get("split_plans"):
        # Dual domain → two independent plans
        for label, sub_domain in [("PERSONAL ", "personal"), ("BUSINESS ", "business")]:
            prefix_slug = f"{label.strip()}_{base_slug}"
            plan_path = plans_dir / f"Plan_{prefix_slug}.md"
            plan_content = _generate_plan_content(
                task_file.name, content, meta,
                sub_domain, signals, rule_action,
                label_prefix=label,
            )
            plan_path.write_text(plan_content, encoding="utf-8")
            created_plans.append(str(plan_path.relative_to(root)))
    else:
        plan_path = plans_dir / f"Plan_{base_slug}.md"
        plan_content = _generate_plan_content(
            task_file.name, content, meta,
            effective_domain, signals, rule_action,
        )
        plan_path.write_text(plan_content, encoding="utf-8")
        created_plans.append(str(plan_path.relative_to(root)))

    # Update meta.json
    meta.update({
        "status": "processing",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "domain": effective_domain,
        "domain_signals": _all_signal_keywords(signals),
        "cross_domain_rule": rule_action["rule_applied"],
        "priority": rule_action["priority"],
        "sensitive": rule_action["sensitive"],
        "plans": created_plans,
        "route": rule_action["route"],
    })
    meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return {
        "task": task_file.name,
        "domain": effective_domain,
        "rule": rule_action["rule_applied"],
        "priority": rule_action["priority"],
        "sensitive": rule_action["sensitive"],
        "plans": created_plans,
        "route": rule_action["route"],
        "description": rule_action["description"],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Batch runner
# ──────────────────────────────────────────────────────────────────────────────

def run(vault_root: str = ".") -> int:
    """
    Process all pending tasks in needs_action/.

    Returns the count of tasks processed (0 = nothing to do, not an error).
    """
    root = Path(vault_root)
    needs_action = root / "needs_action"

    if not needs_action.exists():
        print("[route-cross-domain-task] needs_action/ not found — skipping.")
        return 0

    processed = 0
    for meta_file in sorted(needs_action.glob("*.meta.json")):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        if meta.get("status") != "pending":
            continue

        # meta file is <task_file>.meta.json → strip ".meta.json"
        task_file = Path(str(meta_file)[: -len(".meta.json")])
        if not task_file.exists():
            print(f"[route-cross-domain-task] WARNING: task file missing for {meta_file.name}")
            continue

        try:
            result = process_task(str(task_file), vault_root)
            print(
                f"[route-cross-domain-task] {result['task']}"
                f" → domain={result['domain']}"
                f", rule={result['rule']}"
                f", priority={result['priority']}"
                f", route={result['route']}"
            )
            processed += 1
        except Exception as exc:
            print(f"[route-cross-domain-task] ERROR processing {task_file.name}: {exc}")

    print(f"[route-cross-domain-task] Done — {processed} task(s) processed.")
    return processed


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    vault = sys.argv[1] if len(sys.argv) > 1 else "."
    result = run(vault)
    sys.exit(0)
