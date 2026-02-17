# AI Employee Vault

A file-based task automation pipeline that acts as your personal AI employee. Drop a file into the inbox and watch it get analyzed, planned, and completed — all automatically.

## How It Works

```
inbox/ → watcher (pending) → analyzer (processing) → agent (complete) → done/
```

1. **Watcher** — Polls `inbox/` every 2 seconds. New files are copied to `needs_action/` with a `.meta.json` sidecar (status: `pending`).
2. **Analyzer** — Picks up pending tasks, performs content analysis (word count, category detection, key phrase extraction), updates status to `processing`, and logs a summary.
3. **Agent** — Picks up processing tasks, generates a markdown plan in `plans/`, marks the task `complete`, moves it to `done/`, and updates the dashboard and system logs.

## Quick Start

```bash
# Clone the repo
git clone https://github.com/MahwishNazir/Personal-AI-Employee-Hackathon-0.git
cd Personal-AI-Employee-Hackathon-0

# Run the pipeline
python main.py
```

Then drop any file into the `inbox/` folder. Within ~6 seconds it will flow through the entire pipeline.

## Project Structure

```
├── main.py                  # Entry point — starts watcher with chained callbacks
├── watcher.py               # Polls inbox/ for new files
├── skills/
│   └── task_analyzer.py     # Analyzes pending tasks (categorization, key phrases)
├── agents/
│   └── task_agent.py        # Completes tasks (plan generation, move to done)
├── inbox/                   # Drop files here to trigger the pipeline
├── needs_action/            # Files currently being processed
├── done/                    # Completed tasks with metadata
├── plans/                   # Auto-generated plan files (.plan.md)
├── logs/
│   └── summary.md           # Analysis summaries
├── dashboard.md             # Task status overview
├── system_logs.md           # Timestamped activity log
└── company_handbook.md      # Reference document
```

## Task Categories

The analyzer automatically categorizes tasks based on content keywords:

| Category | Keywords |
|----------|----------|
| bug/fix | bug, fix, error, issue, broken, crash |
| feature | feature, add, implement, create, build, new |
| documentation | doc, readme, write up, summary, notes |
| research | research, investigate, explore, analyze, study |
| urgent | urgent, asap, critical, immediately, deadline |
| general | (default) |

## Requirements

- Python 3.11+
- No third-party dependencies — runs entirely on the standard library

## License

This project was built for Hackathon 0.
