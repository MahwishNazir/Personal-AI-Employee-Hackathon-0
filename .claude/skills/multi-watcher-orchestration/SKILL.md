---
name: multi-watcher-orchestration
description: Orchestrates all four input watchers (inbox, Gmail, LinkedIn, WhatsApp) each Silver Cycle. Scans every source for new items, normalises them into needs_action/ with .meta.json sidecars, and deduplicates across sources. Always the FIRST skill invoked in a Silver Cycle run.
---

# Multi-Watcher Orchestration Skill

## Purpose

Silver Tier adds three external input channels on top of the Bronze inbox watcher.
This skill coordinates all four so that every new item — regardless of source —
lands in `needs_action/` in a consistent format before any planning or action begins.

**Silver Tier pipeline position:** Step 1 of 6

```
[multi-watcher-orchestration]  ← YOU ARE HERE
        ↓
[plan-creation-workflow]
        ↓
[human-approval-workflow]  (if sensitive)
        ↓
[mcp-action-handler]       (if approved)
        ↓
[linkedin-business-poster] (if LinkedIn task)
        ↓
[dashboard-updater]
```

---

## Watcher Registry

| ID | Source | Script | Interval | Auth |
|----|--------|--------|----------|------|
| `inbox` | Local `inbox/` folder | `watcher.py` | 2 s | None |
| `gmail` | Gmail API | `gmail_watcher.py` | 120 s | OAuth 2.0 (`gmail_token.json`) |
| `linkedin` | LinkedIn notifications | `linkedin_watcher.py` | 60 s | Playwright session (`.linkedin_session/`) |
| `whatsapp` | WhatsApp Web | `whatsapp_watcher.py` | 30 s | Playwright session (`.whatsapp_session/`) |

---

## Instructions

### Step 0 — Log scan start (audit)

Before scanning any source, write one audit entry to mark the cycle beginning:

```python
from audit_logger import log_action
log_action(
    action_type="watcher_scan",
    actor="claude",
    target="needs_action/",
    parameters={"sources": ["inbox", "gmail", "linkedin", "whatsapp"], "phase": "start"},
    approval_status="n_a",
    result="pending",
)
```

---

### Step 1 — Scan inbox/ (Bronze watcher)

Check `inbox/` for any files not yet present in `needs_action/` or `done/`.
For each new file:
- Copy to `needs_action/<filename>`
- Write `needs_action/<filename>.meta.json`:
  ```json
  {
    "name": "<filename>",
    "size": <bytes>,
    "timestamp": "<ISO-8601-UTC>",
    "status": "pending",
    "source": "inbox"
  }
  ```

**Script reference:** `watcher.py` → `process_file()` + `build_metadata()`

### Step 2 — Scan Gmail (if gmail_token.json exists)

Run: `python gmail_watcher.py` (single poll, not continuous).
Each new email becomes a `.md` task file in `needs_action/` with `"source": "email"`.
Skip if `gmail_token.json` is missing — log warning to `logs/watcher-errors.log`.

**Script reference:** `gmail_watcher.py` → `check_for_updates()` + `create_action_file()`

### Step 3 — Scan LinkedIn (if .linkedin_session/ exists)

Run: `python linkedin_watcher.py` (single poll).
New notifications become `.md` task files with `"source": "linkedin"`.
Skip if session directory is missing.

**Script reference:** `linkedin_watcher.py` → `check_for_updates()` + `create_action_file()`

### Step 4 — Scan WhatsApp (if .whatsapp_session/ exists)

Run: `python whatsapp_watcher.py` (single poll).
New messages become `.md` task files with `"source": "whatsapp"`.
Skip if session directory is missing.

**Script reference:** `whatsapp_watcher.py` → `check_for_updates()` + `create_action_file()`

### Step 5 — Deduplication

Before passing items to `plan-creation-workflow`, verify no file in `needs_action/`
has a duplicate `name` already present in `done/`. If a duplicate is found, skip it
and log to `logs/summary.md`:
```
[SKIP] <filename> already in done/ — skipped by multi-watcher-orchestration
```

Also write a structured audit entry for each skip:
```python
log_action(
    action_type="dedup_skip",
    actor="claude",
    target=f"needs_action/{filename}",
    parameters={"reason": "already in done/"},
    approval_status="n_a",
    result="skip",
)
```

### Step 6 — Report and audit log

After scanning all sources, output a summary:
```
[multi-watcher-orchestration] Scan complete.
  inbox    : N new items
  gmail    : N new items  (or SKIPPED — token missing)
  linkedin : N new items  (or SKIPPED — session missing)
  whatsapp : N new items  (or SKIPPED — session missing)
  Total    : N items queued in needs_action/
```

Append this summary to `logs/summary.md` with a timestamp.

Then write the closing audit entry for this scan cycle:
```python
log_action(
    action_type="watcher_scan",
    actor="claude",
    target="needs_action/",
    parameters={
        "inbox": N, "gmail": N, "linkedin": N, "whatsapp": N,
        "total": N, "phase": "complete",
    },
    approval_status="n_a",
    result="success",
)
```

---

## Error Handling

| Condition | Action |
|-----------|--------|
| Watcher script not found | Log error, skip that source, continue with others |
| Auth token missing | Log warning, skip that source |
| Playwright not installed | Log warning, skip browser-based watchers |
| needs_action/ write fails | Log error, halt cycle with non-zero exit |

---

## File Naming Convention

All task files created by external watchers must follow:
```
<source>_<category>_<actor-slug>_<hash>.md
```
Example: `linkedin_message_John_Doe_a1b2c3d4.md`

inbox/ files retain their original filename.

---

## References

- `base_watcher.py` — `BaseWatcher` abstract class, `write_meta()` helper
- `CLAUDE.md` — Watcher table and pipeline flow diagram
- `README.md` — "How It Works" section (Step 1: Watcher)
