# CLAUDE.md

## Project Overview
**AI Employee Vault** — A file-based task automation pipeline. Files dropped into `inbox/` or captured by external watchers (WhatsApp, LinkedIn, Gmail) are automatically detected, analyzed, planned, and completed by a chain of agents.

## Pipeline Flow
```
inbox/            ─┐
whatsapp_watcher  ─┤→ needs_action/ (pending) → analyzer (processing) → agent (complete) → done/
linkedin_watcher  ─┤                                                   ↘ plans/<name>.plan.md
gmail_watcher     ─┘                                                   ↘ dashboard.md updated
                                                                       ↘ system_logs.md updated
```

## Project Structure
```
├── main.py                  # Entry point — starts inbox watcher with chained callbacks
├── watcher.py               # Polls inbox/ every 2s, copies new files to needs_action/
├── base_watcher.py          # Abstract base class for all external watchers
├── whatsapp_watcher.py      # WhatsApp Web watcher (Playwright, 30s interval)
├── linkedin_watcher.py      # LinkedIn notifications watcher (Playwright, 60s interval)
├── gmail_watcher.py         # Gmail API watcher (OAuth 2.0, 120s interval)
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
├── dashboard.md             # Task status overview (tables)
├── system_logs.md           # Timestamped activity log
└── company_handbook.md      # Reference document
```

## Watchers

| Watcher | Source | Interval | Auth | Type Tag |
|---------|--------|----------|------|----------|
| `watcher.py` | Local `inbox/` folder | 2s | None | — |
| `whatsapp_watcher.py` | WhatsApp Web | 30s | Playwright persistent session (QR scan) | `whatsapp` |
| `linkedin_watcher.py` | LinkedIn notifications | 60s | Playwright persistent session (login) | `linkedin` |
| `gmail_watcher.py` | Gmail API | 120s | Google OAuth 2.0 | `email` |

All external watchers extend `BaseWatcher` and implement:
- `check_for_updates()` — returns a list of new items
- `create_action_file(item)` — writes `.md` + `.meta.json` into `needs_action/`

## Key Conventions
- **Status flow:** `pending` → `processing` → `complete`
- **Metadata sidecars:** Every task file has a `<filename>.meta.json` companion
- **Module pattern:** Each skill/agent exposes a `run()` function returning an `int` (count of items processed)
- **Watcher pattern:** External watchers extend `BaseWatcher` with `check_for_updates()` + `create_action_file()`
- **Callbacks:** `watcher.watch()` accepts a single callable or a list of callables via `on_cycle`

## Running

```bash
# Core pipeline (inbox watcher + analyzer + agent)
python main.py

# External watchers (run separately)
python whatsapp_watcher.py --login   # first time: scan QR
python whatsapp_watcher.py           # then watch

python linkedin_watcher.py --login   # first time: log in
python linkedin_watcher.py           # then watch

python gmail_watcher.py --auth       # first time: OAuth consent
python gmail_watcher.py              # then watch
```

## Tech
- Python 3.11+
- Core pipeline: stdlib only
- External watchers: `playwright`, `google-auth`, `google-auth-oauthlib`, `google-api-python-client`
