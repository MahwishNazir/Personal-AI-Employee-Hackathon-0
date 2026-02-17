"""
task_analyzer.py - Task Analysis Skill

Scans the 'needs_action' folder for tasks with status 'pending'.
For each pending task:
  1. Reads the task file content
  2. Analyzes it (word count, line count, key phrases, category)
  3. Updates the .meta.json status to 'processing'
  4. Appends a summary entry to logs/summary.md
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────
VAULT_DIR = Path(__file__).parent.parent       # Root of the vault
NEEDS_ACTION_DIR = VAULT_DIR / "needs_action"
LOGS_DIR = VAULT_DIR / "logs"
SUMMARY_FILE = LOGS_DIR / "summary.md"


def find_pending_tasks() -> list[tuple[Path, Path]]:
    """
    Find all task files in needs_action/ that have a companion
    .meta.json with status 'pending'.

    Returns a list of (task_file, meta_file) tuples.
    """
    pairs = []
    for meta_path in NEEDS_ACTION_DIR.glob("*.meta.json"):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("status") == "pending":
            # Derive the task file path by stripping '.meta.json'
            task_name = meta_path.name.replace(".meta.json", "")
            task_path = NEEDS_ACTION_DIR / task_name
            if task_path.exists():
                pairs.append((task_path, meta_path))
    return pairs


def analyze_content(text: str) -> dict:
    """
    Perform a basic analysis of the task file content.

    Returns a dict with:
        - word_count:  total number of words
        - line_count:  total number of lines
        - char_count:  total characters (excluding leading/trailing whitespace)
        - key_phrases: up to 5 notable phrases (sentences or fragments)
        - category:    a rough category based on keywords
    """
    lines = text.splitlines()
    words = text.split()

    # Extract key phrases: first 5 non-empty lines, trimmed
    key_phrases = [line.strip() for line in lines if line.strip()][:5]

    # Simple keyword-based categorization
    category = _categorize(text)

    return {
        "word_count": len(words),
        "line_count": len(lines),
        "char_count": len(text.strip()),
        "key_phrases": key_phrases,
        "category": category,
    }


def _categorize(text: str) -> str:
    """
    Assign a rough category to the task based on keyword matching.
    Returns the first matching category or 'general'.
    """
    lower = text.lower()
    categories = {
        "bug/fix":       ["bug", "fix", "error", "issue", "broken", "crash"],
        "feature":       ["feature", "add", "implement", "create", "build", "new"],
        "documentation": ["doc", "readme", "write up", "summary", "notes"],
        "research":      ["research", "investigate", "explore", "analyze", "study"],
        "urgent":        ["urgent", "asap", "critical", "immediately", "deadline"],
    }
    for category, keywords in categories.items():
        if any(kw in lower for kw in keywords):
            return category
    return "general"


def update_meta_status(meta_path: Path, new_status: str, analysis: dict) -> dict:
    """
    Update the .meta.json file: set the new status and attach analysis results.
    Returns the updated metadata dict.
    """
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["status"] = new_status
    meta["analyzed_at"] = datetime.now(timezone.utc).isoformat()
    meta["analysis"] = analysis
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def append_summary(task_name: str, meta: dict, analysis: dict) -> None:
    """
    Append a markdown summary entry to logs/summary.md.
    Creates the file with a header if it doesn't exist yet.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Create summary file with header if it doesn't exist
    if not SUMMARY_FILE.exists():
        SUMMARY_FILE.write_text("# Task Summaries\n\n", encoding="utf-8")

    # Build the summary entry
    entry = (
        f"## {task_name}\n"
        f"- **Status:** {meta['status']}\n"
        f"- **Category:** {analysis['category']}\n"
        f"- **Size:** {meta['size']} bytes\n"
        f"- **Words:** {analysis['word_count']} | "
        f"**Lines:** {analysis['line_count']} | "
        f"**Chars:** {analysis['char_count']}\n"
        f"- **Received:** {meta['timestamp']}\n"
        f"- **Analyzed:** {meta['analyzed_at']}\n"
        f"- **Key phrases:**\n"
    )
    for phrase in analysis["key_phrases"]:
        entry += f"  - {phrase}\n"
    entry += "\n---\n\n"

    # Append to the summary log
    with open(SUMMARY_FILE, "a", encoding="utf-8") as f:
        f.write(entry)


def run() -> int:
    """
    Main entry point for the task analyzer skill.

    Finds all pending tasks, analyzes each one, updates metadata
    to 'processing', and logs a summary. Returns the number of
    tasks processed.
    """
    pending = find_pending_tasks()

    if not pending:
        print("[analyzer] No pending tasks found.")
        return 0

    print(f"[analyzer] Found {len(pending)} pending task(s).\n")

    for task_path, meta_path in pending:
        task_name = task_path.name
        print(f"[analyzer] Analyzing: {task_name}")

        # Step 1: Read the task file content
        content = task_path.read_text(encoding="utf-8")

        # Step 2: Analyze the content
        analysis = analyze_content(content)

        # Step 3: Update .meta.json status to 'processing'
        meta = update_meta_status(meta_path, "processing", analysis)

        # Step 4: Append summary to logs/summary.md
        append_summary(task_name, meta, analysis)

        print(f"           Category:   {analysis['category']}")
        print(f"           Words:      {analysis['word_count']}")
        print(f"           Status:     {meta['status']}")
        print(f"           Summary -> {SUMMARY_FILE}\n")

    print(f"[analyzer] Done. Processed {len(pending)} task(s).")
    return len(pending)


# ── Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    run()
