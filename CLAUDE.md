# CLAUDE.md

## Project Overview
**AI Employee Vault** — A file-based task automation pipeline. Files dropped into `inbox/` are automatically detected, analyzed, planned, and completed by a chain of agents.

## Pipeline Flow
```
inbox/ → watcher (pending) → analyzer (processing) → agent (complete) → done/
                                                    ↘ plans/<name>.plan.md
                                                    ↘ dashboard.md updated
                                                    ↘ system_logs.md updated
```

## Project Structure
```
├── main.py                  # Entry point — starts watcher with chained callbacks
├── watcher.py               # Polls inbox/ every 2s, copies new files to needs_action/
├── skills/
│   └── task_analyzer.py     # Analyzes pending tasks → sets status to "processing"
├── agents/
│   └── task_agent.py        # Completes processing tasks → moves to done/
├── inbox/                   # Drop files here to trigger the pipeline
├── needs_action/            # Intermediate: files being processed
├── done/                    # Completed tasks with .meta.json sidecars
├── plans/                   # Generated .plan.md files per task
├── logs/
│   └── summary.md           # Analyzer output summaries
├── dashboard.md             # Pending and completed task overview
├── system_logs.md           # Timestamped activity log
└── company_handbook.md      # Reference document
```

## Key Conventions
- **Status flow:** `pending` → `processing` → `complete`
- **Metadata sidecars:** Every task file has a `<filename>.meta.json` companion
- **Module pattern:** Each skill/agent exposes a `run()` function returning an `int` (count of items processed)
- **Callbacks:** `watcher.watch()` accepts a single callable or a list of callables via `on_cycle`
- **No external dependencies** — stdlib only (json, shutil, pathlib, etc.)

## Running
```bash
python main.py
```
Then drop any file into `inbox/` and watch it flow through the pipeline.

## Tech
- Python 3.11+
- No third-party packages required
