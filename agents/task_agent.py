"""
task_agent.py - Task Completion Agent

Scans 'needs_action' for tasks with status 'processing'.
For each processing task:
  1. Reads the task file content and analysis metadata
  2. Generates a plan file in plans/<task_name>.plan.md
  3. Marks the .meta.json status as 'complete'
  4. Moves both files from needs_action/ to done/
  5. Updates dashboard.md (removes from Pending, adds to Completed)
  6. Appends an entry to system_logs.md
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from audit_logger import log_action, ACTOR_TASK_AGENT

# ── Configuration ──────────────────────────────────────────────────────────
VAULT_DIR = Path(__file__).parent.parent       # Root of the vault
NEEDS_ACTION_DIR = VAULT_DIR / "needs_action"
DONE_DIR = VAULT_DIR / "done"
PLANS_DIR = VAULT_DIR / "plans"
DASHBOARD_FILE = VAULT_DIR / "dashboard.md"
SYSTEM_LOGS_FILE = VAULT_DIR / "system_logs.md"


def find_processing_tasks() -> list[tuple[Path, Path, dict]]:
    """
    Find all task files in needs_action/ that have a companion
    .meta.json with status 'processing'.

    Returns a list of (task_file, meta_file, meta_dict) tuples.
    """
    results = []
    for meta_path in NEEDS_ACTION_DIR.glob("*.meta.json"):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("status") == "processing":
            task_name = meta_path.name.replace(".meta.json", "")
            task_path = NEEDS_ACTION_DIR / task_name
            if task_path.exists():
                results.append((task_path, meta_path, meta))
    return results


def generate_plan(task_name: str, content: str, meta: dict) -> Path:
    """
    Generate a markdown plan file based on the task content and analysis
    metadata. Writes to plans/<task_name>.plan.md.
    """
    PLANS_DIR.mkdir(parents=True, exist_ok=True)

    analysis = meta.get("analysis", {})
    category = analysis.get("category", "general")
    key_phrases = analysis.get("key_phrases", [])
    word_count = analysis.get("word_count", 0)

    phrases_md = "\n".join(f"  - {p}" for p in key_phrases) if key_phrases else "  - (none)"

    plan_content = (
        f"# Plan: {task_name}\n\n"
        f"**Category:** {category}\n"
        f"**Word count:** {word_count}\n"
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n\n"
        f"## Source Key Phrases\n{phrases_md}\n\n"
        f"## Action Items\n"
        f"1. Review the task content ({word_count} words, category: {category})\n"
        f"2. Address the core request described in the task\n"
        f"3. Validate results and update stakeholders\n\n"
        f"## Original Content\n```\n{content}\n```\n"
    )

    plan_path = PLANS_DIR / f"{task_name}.plan.md"
    plan_path.write_text(plan_content, encoding="utf-8")
    return plan_path


def mark_complete(meta_path: Path, meta: dict) -> dict:
    """Update .meta.json status to 'complete' and add completed_at timestamp."""
    meta["status"] = "complete"
    meta["completed_at"] = datetime.now(timezone.utc).isoformat()
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def move_to_done(task_path: Path, meta_path: Path) -> tuple[Path, Path]:
    """Move both the task file and its .meta.json from needs_action/ to done/."""
    DONE_DIR.mkdir(parents=True, exist_ok=True)
    new_task = DONE_DIR / task_path.name
    new_meta = DONE_DIR / meta_path.name
    shutil.move(str(task_path), str(new_task))
    shutil.move(str(meta_path), str(new_meta))
    return new_task, new_meta


def update_dashboard(task_name: str, category: str, completed_at: str) -> None:
    """
    Update dashboard.md:
      - Remove the task from the Pending Tasks table if present
      - Add a row to the Completed Tasks table
    """
    if not DASHBOARD_FILE.exists():
        DASHBOARD_FILE.write_text(
            "# Dashboard\n\n## Pending Tasks\n\n## Completed Tasks\n",
            encoding="utf-8",
        )

    text = DASHBOARD_FILE.read_text(encoding="utf-8")

    # Remove the task from Pending Tasks table (any row mentioning this task)
    lines = text.splitlines()
    lines = [l for l in lines if task_name not in l]
    text = "\n".join(lines) + "\n"

    # Format timestamp for readability
    short_time = completed_at[:16].replace("T", " ") + " UTC"

    # Add row to Completed Tasks table
    row = f"| {task_name} | {category} | {short_time} |"
    marker = "## Completed Tasks"
    if marker in text:
        # Find the table header and insert after the header row
        idx = text.find(marker)
        after_marker = text[idx + len(marker):]
        # Find the end of the table header (after |---|---|---|)
        header_end = after_marker.find("|\n") + 1
        if header_end > 0:
            # Find the second header_end (after the separator row)
            second = after_marker[header_end + 1:].find("|\n") + header_end + 2
            insert_pos = idx + len(marker) + second
            text = text[:insert_pos] + "\n" + row + text[insert_pos:]
        else:
            text = text.replace(marker, marker + "\n" + row, 1)
    else:
        text += f"\n{marker}\n{row}\n"

    DASHBOARD_FILE.write_text(text, encoding="utf-8")


def update_system_logs(task_name: str, category: str) -> None:
    """Append a timestamped log entry under '## Activity Logs' in system_logs.md."""
    if not SYSTEM_LOGS_FILE.exists():
        SYSTEM_LOGS_FILE.write_text(
            "# System Logs\n\n## Activity Logs\n",
            encoding="utf-8",
        )

    now = datetime.now(timezone.utc).isoformat()
    entry = f"- [{now}] Task completed: **{task_name}** (category: {category})\n"

    text = SYSTEM_LOGS_FILE.read_text(encoding="utf-8")
    marker = "## Activity Logs"
    if marker in text:
        text = text.replace(marker, marker + "\n" + entry, 1)
    else:
        text += f"\n{marker}\n{entry}"

    SYSTEM_LOGS_FILE.write_text(text, encoding="utf-8")


def run() -> int:
    """
    Main entry point for the task agent.

    Finds all processing tasks, generates plans, marks them complete,
    moves them to done/, and updates dashboard + logs.
    Returns the number of tasks completed.
    """
    processing = find_processing_tasks()

    if not processing:
        print("[agent] No processing tasks found.")
        return 0

    print(f"[agent] Found {len(processing)} processing task(s).\n")

    for task_path, meta_path, meta in processing:
        task_name = task_path.name
        print(f"[agent] Completing: {task_name}")

        # Step 1: Read task content
        content = task_path.read_text(encoding="utf-8")

        # Step 2: Generate plan
        plan_path = generate_plan(task_name, content, meta)
        print(f"         Plan -> {plan_path}")
        log_action(
            action_type="plan_created",
            actor=ACTOR_TASK_AGENT,
            target=str(plan_path.relative_to(VAULT_DIR)),
            parameters={"source_task": task_name,
                        "category": meta.get("analysis", {}).get("category", "general")},
            approval_status="n_a",
            result="success",
        )

        # Step 3: Mark complete
        meta = mark_complete(meta_path, meta)
        completed_at = meta["completed_at"]
        category = meta.get("analysis", {}).get("category", "general")

        # Step 4: Move to done/
        new_task, new_meta = move_to_done(task_path, meta_path)
        print(f"         Moved -> {DONE_DIR}")

        # Step 5: Update dashboard
        update_dashboard(task_name, category, completed_at)

        # Step 6: Log to system_logs.md
        update_system_logs(task_name, category)

        # Audit log — task completed
        log_action(
            action_type="status_transition",
            actor=ACTOR_TASK_AGENT,
            target=f"done/{task_name}",
            parameters={"from": "processing", "to": "complete", "category": category},
            approval_status="n_a",
            result="success",
        )

        print(f"         Status: {meta['status']}\n")

    print(f"[agent] Done. Completed {len(processing)} task(s).")
    return len(processing)


# ── Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    run()
