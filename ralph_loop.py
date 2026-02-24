#!/usr/bin/env python3
"""
ralph_loop.py — Ralph Wiggum Persistent Loop
============================================
Keeps running Claude Code in a loop until the task is truly complete.

Completion is detected by:
  (A) A file appearing in done/ that was not there before this loop started
  (B) Claude outputting exactly <TASK_COMPLETE> (or --completion-promise token)

Usage:
  python ralph_loop.py "Process all items in needs_action"
  python ralph_loop.py --max-iterations 10 --completion-promise DONE "Write CEO briefing"
  python ralph_loop.py --prompt-file silver_prompt.txt
  python ralph_loop.py --resume "Process all items in needs_action"   # resume last run with same prompt
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
VAULT = Path(__file__).parent.resolve()
RALPH_STATE_DIR = VAULT / "Ralph_State"
LOG_FILE = VAULT / "logs" / "ralph.log"
DONE_DIR = VAULT / "done"


# ── Helpers ──────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    """Write timestamped message to stdout and to logs/ralph.log."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    # Safe print: replace unencodable chars so Windows cp1252 console never crashes
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", errors="replace").decode("ascii"), flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def find_claude() -> str:
    """Locate the claude CLI executable (Windows-safe)."""
    # On Windows, shutil.which may return a bash-style path (/c/Users/...)
    # that is not usable by Python's subprocess. Prefer .cmd explicitly.
    if sys.platform == "win32":
        candidates = [
            os.path.expandvars(r"%APPDATA%\npm\claude.cmd"),
            r"C:\Users\User\AppData\Roaming\npm\claude.cmd",
            os.path.expandvars(r"%APPDATA%\npm\claude"),
            r"C:\Users\User\AppData\Roaming\npm\claude",
        ]
        for c in candidates:
            if Path(c).exists():
                return c

    # Unix / WSL — shutil.which is reliable
    found = shutil.which("claude")
    if found:
        return found

    raise FileNotFoundError(
        "claude CLI not found. Install it with: npm install -g @anthropic-ai/claude-code"
    )


def clean_env() -> dict:
    """Return a copy of the current environment with CLAUDECODE removed.

    Claude Code sets CLAUDECODE to prevent nested sessions. We intentionally
    unset it here so ralph_loop can spawn a fresh claude subprocess.
    """
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    return env


def task_id_from_prompt(prompt: str) -> str:
    """Stable 8-char hash identifier for a prompt."""
    return hashlib.md5(prompt.strip().encode("utf-8")).hexdigest()[:8]


def snapshot_done() -> set[str]:
    """Return the current set of filenames in done/."""
    if not DONE_DIR.exists():
        return set()
    return {p.name for p in DONE_DIR.iterdir() if p.is_file()}


# ── State management ─────────────────────────────────────────────────────────

def load_state(task_id: str) -> dict:
    state_file = RALPH_STATE_DIR / f"{task_id}.json"
    if state_file.exists():
        with open(state_file, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_state(task_id: str, state: dict) -> None:
    RALPH_STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = RALPH_STATE_DIR / f"{task_id}.json"
    with open(state_file, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False)


# ── Prompt builder ────────────────────────────────────────────────────────────

def build_iter_prompt(
    original_prompt: str,
    iteration: int,
    prev_output: str,
    completion_token: str,
) -> str:
    """Return the prompt to send for a given iteration."""
    if iteration == 1:
        # First pass: append the completion instruction
        return (
            original_prompt.rstrip()
            + f"\n\nWhen the task is fully complete, output exactly: {completion_token}"
        )

    # Subsequent passes: inject context about the incomplete state
    snippet = prev_output[-600:].strip() if prev_output else "(no output captured)"
    return f"""RALPH LOOP — CONTINUATION (Iteration {iteration})

You are resuming an incomplete task. You have NOT yet output `{completion_token}` \
and no new files have appeared in done/ since this loop started.

━━━ ORIGINAL TASK ━━━
{original_prompt.strip()}

━━━ YOUR PREVIOUS OUTPUT ENDED WITH ━━━
...{snippet}

━━━ INSTRUCTIONS ━━━
Continue working on the original task from where you left off.
Do NOT repeat work already completed. Focus on what remains.
When the task is FULLY complete, output exactly: {completion_token}
"""


# ── Core loop ─────────────────────────────────────────────────────────────────

def run_loop(
    prompt: str,
    max_iterations: int = 20,
    completion_token: str = "<TASK_COMPLETE>",
    resume: bool = False,
) -> int:
    """
    Run the Ralph Wiggum loop. Returns 0 on success, 1 on max-iterations reached.
    """
    task_id = task_id_from_prompt(prompt)
    claude_exe = find_claude()

    log("=" * 60)
    log(f"RALPH LOOP START  task_id={task_id}  max_iter={max_iterations}")
    log(f"Prompt (first 120 chars): {prompt[:120].replace(chr(10), ' ')}")
    log(f"Claude executable: {claude_exe}")
    log("=" * 60)

    # Load or initialise state
    if resume:
        state = load_state(task_id)
        start_iter = state.get("iteration", 0) + 1
        log(f"Resuming from iteration {start_iter}")
    else:
        state = {}
        start_iter = 1

    state.update({
        "task_id":          task_id,
        "task_prompt":      prompt,
        "start_time":       state.get("start_time", datetime.now().isoformat()),
        "max_iterations":   max_iterations,
        "completion_token": completion_token,
        "status":           "running",
        "iteration":        start_iter - 1,
        "iterations":       state.get("iterations", []),
    })
    save_state(task_id, state)

    # Baseline done/ snapshot (before any iterations this loop run)
    done_baseline: set[str] = snapshot_done()
    prev_output = ""

    for i in range(start_iter, max_iterations + 1):
        state["iteration"] = i
        save_state(task_id, state)

        log(f"--- Iteration {i}/{max_iterations} ---")

        iter_prompt = build_iter_prompt(prompt, i, prev_output, completion_token)
        done_before_iter = snapshot_done()

        # ── Invoke Claude ───────────────────────────────────────────────────
        try:
            result = subprocess.run(
                [claude_exe, "--print", "--dangerously-skip-permissions"],
                input=iter_prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=600,         # 10-minute safety net per iteration
                cwd=str(VAULT),
                env=clean_env(),     # strip CLAUDECODE to allow nested launch
            )
            output = (result.stdout or "") + (result.stderr or "")
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            log(f"  TIMEOUT: Iteration {i} exceeded 600s")
            output = ""
            exit_code = -1
        except Exception as exc:
            log(f"  ERROR running claude: {exc}")
            output = ""
            exit_code = -1

        prev_output = output

        # Log first 300 chars to ralph.log; full output appended below
        snippet = output[:300].replace("\n", " ").strip()
        log(f"  Exit={exit_code}  Output snippet: {snippet}")

        # Append full iteration output to log
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"\n{'─'*60}\nITER {i} FULL OUTPUT\n{'─'*60}\n{output}\n{'─'*60}\n")

        # ── Completion detection ────────────────────────────────────────────
        done_after_iter = snapshot_done()
        new_done_files  = done_after_iter - done_before_iter    # added this iteration
        total_new_files = done_after_iter - done_baseline       # added since loop start

        token_found   = completion_token in output
        files_arrived = bool(new_done_files)

        complete = token_found or files_arrived
        method   = ("token" if token_found else "done_file") if complete else None

        if token_found:
            log(f"  COMPLETE: token '{completion_token}' found in output")
        if files_arrived:
            log(f"  COMPLETE: {len(new_done_files)} new file(s) in done/ → {new_done_files}")

        # Record iteration in state (wrapped so a serialisation error never masks success)
        try:
            state["iterations"].append({
                "iteration":         i,
                "timestamp":         datetime.now().isoformat(),
                "output_length":     len(output),
                "exit_code":         exit_code,
                "complete":          complete,
                "completion_method": method,
                "new_done_files":    sorted(new_done_files),
            })

            if complete:
                state["status"]               = "complete"
                state["completion_method"]    = method
                state["total_new_done_files"] = sorted(total_new_files)
                save_state(task_id, state)
        except Exception as state_err:
            log(f"  WARNING: state save failed (task still complete): {state_err}")

        if complete:
            log(f"=== RALPH LOOP COMPLETE  iterations={i}  method={method} ===")
            return 0

        # Not done yet — pause briefly before next iteration
        if i < max_iterations:
            log(f"  Not complete. Pausing 3s before iteration {i + 1}…")
            time.sleep(3)

    # Max iterations reached without completion
    state["status"] = "max_iterations_reached"
    save_state(task_id, state)
    log(f"=== RALPH LOOP: MAX ITERATIONS ({max_iterations}) REACHED — task incomplete ===")
    log(f"    State saved to: Ralph_State/{task_id}.json")
    log(f"    Re-run with --resume to continue from iteration {max_iterations + 1}")
    return 1


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ralph Wiggum Loop — keeps Claude working until a task is truly done.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ralph_loop.py "Process all items in needs_action and create CEO briefing if Sunday"
  python ralph_loop.py --max-iterations 5 --completion-promise DONE "Send weekly digest"
  python ralph_loop.py --prompt-file silver_prompt.txt --max-iterations 3
  python ralph_loop.py --resume "Process all items in needs_action"
""",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="Task prompt (wrap in quotes)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=20,
        metavar="N",
        help="Maximum loop iterations before giving up (default: 20)",
    )
    parser.add_argument(
        "--completion-promise",
        default="<TASK_COMPLETE>",
        metavar="TOKEN",
        help="Output token that signals task completion (default: <TASK_COMPLETE>)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume the last run for this prompt (load state from Ralph_State/)",
    )
    parser.add_argument(
        "--prompt-file",
        metavar="PATH",
        help="Read prompt from a file instead of the CLI argument",
    )

    args = parser.parse_args()

    # Resolve prompt
    if args.prompt_file:
        pf = Path(args.prompt_file)
        if not pf.exists():
            parser.error(f"--prompt-file not found: {pf}")
        prompt = pf.read_text(encoding="utf-8").strip()
    elif args.prompt:
        prompt = args.prompt
    else:
        parser.print_help()
        sys.exit(1)

    exit_code = run_loop(
        prompt=prompt,
        max_iterations=args.max_iterations,
        completion_token=args.completion_promise,
        resume=args.resume,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
