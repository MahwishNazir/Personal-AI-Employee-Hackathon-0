# SKILL: ralph-loop

## Purpose
Run a long, multi-step task through the Ralph Wiggum Persistent Loop so it
completes autonomously — without human babysitting — even if it takes many
Claude iterations.

## When to invoke this skill
- A task in `needs_action/` has a type of `multi-step-autonomous` or is flagged
  with `"ralph": true` in its `.meta.json`.
- A user explicitly asks for a "persistent loop" or "keep going until done".
- The Silver Cycle detects a task that cannot be completed in a single pass
  (e.g. write + review + revise + send).

## How to invoke

### From the CLI (Git Bash)
```bash
./ralph-loop "Your task description here"
./ralph-loop --max-iterations 10 "Process all items in needs_action"
./ralph-loop --completion-promise DONE "Write and send weekly digest"
./ralph-loop --resume "Process all items in needs_action"   # resume incomplete run
```

### From Windows (Command Prompt / Task Scheduler)
```bat
ralph-loop.bat "Your task description here"
ralph-loop.bat --max-iterations 10 --completion-promise "<TASK_COMPLETE>" "Process all items"
```

### Via the orchestrator
```bash
python orchestrator.py ralph "Process all items in needs_action"
python orchestrator.py ralph --max-iterations 5 "Write CEO briefing"
python orchestrator.py weekly-audit
```

### Programmatically from another skill or agent
```python
from ralph_loop import run_loop

exit_code = run_loop(
    prompt="Process all items in needs_action and create CEO briefing",
    max_iterations=20,
    completion_token="<TASK_COMPLETE>",
    resume=False,
)
```

## Completion detection
The loop declares success when EITHER condition is met:
1. **Token** — Claude outputs the exact string `<TASK_COMPLETE>` (or the value
   passed to `--completion-promise`) anywhere in its response.
2. **Done-file** — One or more new files appear in `done/` compared to the
   snapshot taken when this loop started.

## Flags
| Flag | Default | Description |
|------|---------|-------------|
| `--max-iterations N` | 20 | Hard cap on loop iterations |
| `--completion-promise TOKEN` | `<TASK_COMPLETE>` | Override the completion token |
| `--resume` | false | Continue from last saved state in `Ralph_State/` |
| `--prompt-file PATH` | — | Read prompt from a file |

## State
Each run persists a state JSON file at:
```
Ralph_State/<8-char-hash-of-prompt>.json
```
Fields: `task_id`, `task_prompt`, `start_time`, `iteration`, `status`,
`completion_method`, `iterations` (array of per-iteration records).

Status values: `running` → `complete` | `max_iterations_reached`

## Logging
All activity is appended to `logs/ralph.log`:
- Iteration start/end timestamps
- Completion detection events
- Full Claude output per iteration

## Constraints
- NEVER call ralph-loop for tasks that require human approval — route those
  through `human-approval-workflow` first.
- NEVER set `--max-iterations` above 50 on a production system.
- If the loop hits `max_iterations_reached`, log the state and notify the
  human via `dashboard.md` (add a row in Pending Tasks with status `stalled`).

## Example: Sunday CEO Briefing
```bash
python orchestrator.py weekly-audit
```
This builds a date-aware prompt, checks if today is Sunday, generates
`plans/CEO_Briefing_YYYY-MM-DD.md`, and loops until `<TASK_COMPLETE>` is seen.
