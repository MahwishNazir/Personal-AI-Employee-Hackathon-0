#!/usr/bin/env python3
"""
orchestrator.py — AI Employee Vault Unified Orchestrator
=========================================================
Dispatches high-level commands to the right subsystem.

Commands:
  silver              Run a single Silver Cycle (all 6 Agent Skills)
  ralph  <PROMPT>     Run the Ralph Wiggum persistent loop for a task
  weekly-audit        Run the Sunday CEO briefing + needs_action sweep via Ralph Loop
  status              Print current dashboard and pending items

Usage:
  python orchestrator.py silver
  python orchestrator.py ralph "Process all items in needs_action"
  python orchestrator.py ralph --max-iterations 5 "Write CEO briefing"
  python orchestrator.py weekly-audit
  python orchestrator.py status
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
VAULT = Path(__file__).parent.resolve()
SILVER_PROMPT = VAULT / "silver_prompt.txt"
LOGS_DIR = VAULT / "logs"
LOG_FILE = LOGS_DIR / "ralph.log"
VENV_PYTHON_WIN = VAULT / "venv" / "Scripts" / "python.exe"
VENV_PYTHON_NIX = VAULT / "venv" / "bin" / "python"

WEEKLY_AUDIT_PROMPT = """\
Today is {date}. It is {day_of_week}.

You are the AI Employee. Run the full Silver Cycle (all 6 Agent Skills), then:

1. Sweep needs_action/ — process every pending item completely.
2. Move all completed items to done/ with .meta.json sidecars.
3. If today is Sunday, generate a CEO Briefing:
   - File: plans/CEO_Briefing_{date}.md
   - Contents: executive summary of the week, completed tasks, pending approvals,
     LinkedIn activity, and recommended actions for next week.
   - Format: markdown with sections: Summary, Completed, Pending, Risks, Next Week.
4. Update dashboard.md and system_logs.md to reflect all changes.
5. Append a one-paragraph audit summary to logs/weekly_audit.log.

When ALL of the above are complete, output exactly: <TASK_COMPLETE>
"""


def log(msg: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] [orchestrator] {msg}"
    print(line, flush=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def find_python() -> str:
    if VENV_PYTHON_WIN.exists():
        return str(VENV_PYTHON_WIN)
    if VENV_PYTHON_NIX.exists():
        return str(VENV_PYTHON_NIX)
    return sys.executable


def cmd_silver() -> int:
    """Run a single Silver Cycle via the existing run_silver.bat / run_silver.ps1."""
    log("Dispatching Silver Cycle…")
    if sys.platform == "win32":
        script = VAULT / "run_silver.bat"
        result = subprocess.run([str(script)], cwd=str(VAULT))
    else:
        script = VAULT / "run_silver.ps1"
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            cwd=str(VAULT),
        )
    log(f"Silver Cycle finished with exit code {result.returncode}")
    return result.returncode


def cmd_ralph(prompt: str, max_iterations: int, completion_token: str, resume: bool) -> int:
    """Delegate to ralph_loop.py."""
    log(f"Dispatching Ralph Loop — max_iter={max_iterations}")
    python = find_python()
    ralph = VAULT / "ralph_loop.py"

    cmd = [python, str(ralph), "--max-iterations", str(max_iterations),
           "--completion-promise", completion_token]
    if resume:
        cmd.append("--resume")
    cmd.append(prompt)

    result = subprocess.run(cmd, cwd=str(VAULT))
    log(f"Ralph Loop finished with exit code {result.returncode}")
    return result.returncode


def cmd_weekly_audit(max_iterations: int) -> int:
    """Build the weekly audit prompt and run it through the Ralph Loop."""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    day_name = now.strftime("%A")

    prompt = WEEKLY_AUDIT_PROMPT.format(date=date_str, day_of_week=day_name)
    log(f"Starting weekly audit — {day_name} {date_str} — max_iter={max_iterations}")

    python = find_python()
    ralph = VAULT / "ralph_loop.py"
    result = subprocess.run(
        [python, str(ralph),
         "--max-iterations", str(max_iterations),
         "--completion-promise", "<TASK_COMPLETE>",
         prompt],
        cwd=str(VAULT),
    )
    log(f"Weekly audit finished with exit code {result.returncode}")
    return result.returncode


def cmd_status() -> int:
    """Print a quick status snapshot from dashboard.md."""
    dashboard = VAULT / "dashboard.md"
    if dashboard.exists():
        print(dashboard.read_text(encoding="utf-8")[:3000])
    else:
        print("dashboard.md not found.")

    needs = VAULT / "needs_action"
    done = VAULT / "done"
    pending = [f for f in needs.iterdir() if f.is_file() and not f.name.endswith(".meta.json")] \
              if needs.exists() else []
    done_files = [f for f in done.iterdir() if f.is_file() and not f.name.endswith(".meta.json")] \
                 if done.exists() else []

    print(f"\nneeds_action/ : {len(pending)} item(s)")
    print(f"done/         : {len(done_files)} item(s)")
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Employee Vault — Unified Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # silver
    sub.add_parser("silver", help="Run a single Silver Cycle (6 Agent Skills)")

    # ralph
    p_ralph = sub.add_parser("ralph", help="Run the Ralph Wiggum persistent loop")
    p_ralph.add_argument("prompt", help="Task prompt")
    p_ralph.add_argument("--max-iterations", type=int, default=20)
    p_ralph.add_argument("--completion-promise", default="<TASK_COMPLETE>")
    p_ralph.add_argument("--resume", action="store_true")

    # weekly-audit
    p_audit = sub.add_parser("weekly-audit", help="Run the Sunday CEO briefing + sweep")
    p_audit.add_argument("--max-iterations", type=int, default=15)

    # status
    sub.add_parser("status", help="Print dashboard and pending item counts")

    args = parser.parse_args()

    if args.command == "silver":
        sys.exit(cmd_silver())
    elif args.command == "ralph":
        sys.exit(cmd_ralph(
            prompt=args.prompt,
            max_iterations=args.max_iterations,
            completion_token=args.completion_promise,
            resume=args.resume,
        ))
    elif args.command == "weekly-audit":
        sys.exit(cmd_weekly_audit(max_iterations=args.max_iterations))
    elif args.command == "status":
        sys.exit(cmd_status())


if __name__ == "__main__":
    main()
