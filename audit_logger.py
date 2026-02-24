"""
audit_logger.py — Append-only structured audit log for the AI Employee Vault.

Every action (file write, MCP call, email, LinkedIn post, approval, status
transition, etc.) is appended as a JSON object to:

    Logs/YYYY-MM-DD.json   (one file per day, UTC)

Log entry schema
────────────────
  timestamp        str   ISO-8601 UTC timestamp
  action_type      str   e.g. "file_write", "mcp_call", "approval_created"
  actor            str   "claude" | "watcher" | "email-mcp" | "task_agent" | ...
  target           str   filename, email address, URL, or resource name
  parameters       dict  action-specific key-value pairs (never contains secrets)
  approval_status  str   "pending" | "approved" | "rejected" | "n_a"
  result           str   "success" | "fail" | "skip"
  error            str?  error message on failure, None otherwise

Usage
─────
    from audit_logger import log_action, get_recent_actions, format_audit_table

    log_action(
        action_type="file_write",
        actor="watcher",
        target="needs_action/report.pdf",
        parameters={"size": 4096, "source": "inbox"},
        approval_status="n_a",
        result="success",
    )

    recent = get_recent_actions(10)
    md_table = format_audit_table(recent)
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Configuration ──────────────────────────────────────────────────────────
VAULT_ROOT = Path(__file__).parent
LOGS_DIR = VAULT_ROOT / "Logs"  # capital L — distinct from existing logs/ dir

# Valid actor identifiers (informational — not enforced at runtime)
ACTOR_CLAUDE = "claude"
ACTOR_WATCHER = "watcher"
ACTOR_GMAIL_WATCHER = "gmail-watcher"
ACTOR_LINKEDIN_WATCHER = "linkedin-watcher"
ACTOR_WHATSAPP_WATCHER = "whatsapp-watcher"
ACTOR_EMAIL_MCP = "email-mcp"
ACTOR_LINKEDIN_MCP = "linkedin-mcp"
ACTOR_TASK_AGENT = "task_agent"
ACTOR_TASK_ANALYZER = "task_analyzer"


# ── Core logging function ───────────────────────────────────────────────────

def log_action(
    action_type: str,
    actor: str,
    target: str,
    parameters: Optional[dict] = None,
    approval_status: str = "n_a",
    result: str = "success",
    error: Optional[str] = None,
) -> dict:
    """
    Append one structured audit entry to Logs/YYYY-MM-DD.json.

    Creates Logs/ and today's JSON file if they don't exist yet.
    The file contains a top-level JSON array; each call appends one object.

    Args:
        action_type:      Category of the action being logged.
        actor:            Who/what is performing the action.
        target:           The primary resource affected (filename, email, URL).
        parameters:       Action-specific metadata dict (never include secrets).
        approval_status:  Whether this action required/has human approval.
        result:           "success" | "fail" | "skip"
        error:            Error message string if result == "fail", else None.

    Returns:
        The dict that was written to the log file.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    log_file = LOGS_DIR / f"{now.strftime('%Y-%m-%d')}.json"

    entry = {
        "timestamp": now.isoformat(),
        "action_type": action_type,
        "actor": actor,
        "target": target,
        "parameters": parameters or {},
        "approval_status": approval_status,
        "result": result,
        "error": error,
    }

    # Load existing entries (start fresh on any parse error)
    entries: list = []
    if log_file.exists():
        try:
            raw = json.loads(log_file.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                entries = raw
        except (json.JSONDecodeError, OSError):
            entries = []

    entries.append(entry)
    log_file.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return entry


# ── Query helpers ───────────────────────────────────────────────────────────

def get_recent_actions(n: int = 10) -> list:
    """
    Return the N most recent audit entries across all daily log files,
    sorted newest-first by timestamp.

    Reads files in reverse chronological order and stops once enough
    entries have been collected to avoid loading the entire log history.
    """
    if not LOGS_DIR.exists():
        return []

    # Daily files are named YYYY-MM-DD.json — sort descending = newest first
    log_files = sorted(LOGS_DIR.glob("*.json"), reverse=True)
    all_entries: list = []

    for log_file in log_files:
        try:
            raw = json.loads(log_file.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                all_entries.extend(raw)
        except (json.JSONDecodeError, OSError):
            continue
        # Over-fetch slightly so the sort below is correct across file boundaries
        if len(all_entries) >= n * 3:
            break

    all_entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return all_entries[:n]


def get_actions_for_date(date_str: str) -> list:
    """
    Return all audit entries for a specific date (format: YYYY-MM-DD).
    Returns empty list if the file doesn't exist or is unreadable.
    """
    log_file = LOGS_DIR / f"{date_str}.json"
    if not log_file.exists():
        return []
    try:
        raw = json.loads(log_file.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except (json.JSONDecodeError, OSError):
        return []


# ── Dashboard rendering ─────────────────────────────────────────────────────

def format_audit_table(entries: list) -> str:
    """
    Render a list of audit entries as a GitHub-flavoured Markdown table
    suitable for embedding in dashboard.md.

    Columns: Timestamp (UTC) | Action Type | Actor | Target | Approval | Result
    """
    if not entries:
        return "_No audit entries recorded yet._"

    rows = [
        "| Timestamp (UTC) | Action Type | Actor | Target | Approval | Result |",
        "|-----------------|-------------|-------|--------|----------|--------|",
    ]
    for e in entries:
        # Trim to YYYY-MM-DD HH:MM:SS (no microseconds, no tz suffix)
        ts = e.get("timestamp", "")[:19].replace("T", " ")
        action = e.get("action_type", "")
        actor = e.get("actor", "")
        target = e.get("target", "")
        # Truncate long targets so the table stays readable
        if len(target) > 45:
            target = target[:42] + "..."
        approval = e.get("approval_status", "")
        result = e.get("result", "")
        rows.append(
            f"| {ts} | {action} | {actor} | {target} | {approval} | {result} |"
        )
    return "\n".join(rows)


# ── Convenience wrappers ────────────────────────────────────────────────────

def log_file_write(actor: str, target: str, size: int = 0, source: str = "") -> dict:
    """Shorthand for logging a file-write action."""
    return log_action(
        action_type="file_write",
        actor=actor,
        target=target,
        parameters={"size": size, "source": source},
        approval_status="n_a",
        result="success",
    )


def log_status_transition(actor: str, target: str, old_status: str, new_status: str) -> dict:
    """Shorthand for logging a meta.json status change."""
    return log_action(
        action_type="status_transition",
        actor=actor,
        target=target,
        parameters={"from": old_status, "to": new_status},
        approval_status="n_a",
        result="success",
    )


def log_error(actor: str, target: str, action_type: str, error_msg: str) -> dict:
    """Shorthand for logging a caught exception."""
    return log_action(
        action_type=action_type,
        actor=actor,
        target=target,
        parameters={},
        approval_status="n_a",
        result="fail",
        error=error_msg,
    )


# ── Entry point (diagnostic) ────────────────────────────────────────────────
if __name__ == "__main__":
    # Quick smoke-test: write one entry and print the table
    entry = log_action(
        action_type="diagnostic",
        actor="claude",
        target="audit_logger.py",
        parameters={"note": "self-test"},
        approval_status="n_a",
        result="success",
    )
    print(f"[audit_logger] Entry written: {entry['timestamp']}")
    recent = get_recent_actions(5)
    print(format_audit_table(recent))
