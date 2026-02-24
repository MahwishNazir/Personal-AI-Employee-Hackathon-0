---
name: queue-for-later
description: >
  Move a failed task back into needs_action/ with a RETRY_ prefix and a 1-hour
  cooldown. Called after handle-transient-error exhausts all retries on a
  non-critical task. Preserves all original content and adds retry metadata.
---

# Queue For Later

## Purpose

Safely re-queue a failed task so it will be picked up automatically on the next
Silver Cycle after a cooldown period. The original file content is preserved;
retry metadata is added to the .meta.json sidecar so the next processor knows
this is a retry attempt and can track the retry count against max_retries.

**Pipeline position:** Called by Claude (or a watcher) after `handle-transient-error`
exhausts all retries. Never the first response to a failure.

---

## When To Invoke This Skill

Invoke `queue-for-later` when ALL of the following are true:
1. `handle-transient-error` has exhausted all 5 retries.
2. The failed action is **not** a critical system action (use `graceful-degrade` instead for critical ones).
3. The task retry count is **below** max_retries (default 3). If at or above max_retries, invoke `graceful-degrade` instead and create an ALERT.

Typical use cases:
- Gmail send failed after retries (temporary quota issue)
- LinkedIn Playwright scrape timeout after retries
- Plan file generation failed due to transient I/O error

---

## Instructions

### Step 1 — Check Retry Count

Read the task's `.meta.json` sidecar and inspect `retry_count` (default 0 if absent).

- If `retry_count >= max_retries` (default 3): **do not re-queue**.
  Instead invoke `graceful-degrade` to alert the human and defer to deferred_queue.json.
- Otherwise: proceed to Step 2.

### Step 2 — Create the RETRY_ File

Create a new file in `needs_action/` with this naming pattern:

```
needs_action/RETRY_<YYYYMMDDTHHMMSS>_<original_filename>
```

Content: copy the original task file verbatim. If the original no longer exists, write a stub:

```markdown
# Retry Task

**Original:** `<original_filename>`
**Queued at:** <ISO timestamp>
**Retry reason:** <error message>
```

### Step 3 — Write the .meta.json Sidecar

Write `needs_action/RETRY_<timestamp>_<original_filename>.meta.json` with:

```json
{
  "name": "RETRY_<timestamp>_<original>",
  "original_task": "<original_filename>",
  "status": "pending",
  "retry_count": <previous_retry_count + 1>,
  "max_retries": 3,
  "retry_after": "<ISO timestamp 1 hour from now>",
  "retry_queued_at": "<ISO timestamp now>",
  "retry_reason": "<error message>",
  "size": <byte count>
}
```

**Important:** Set `retry_after` to exactly **1 hour from now** in ISO 8601 UTC.
The next processor should check `retry_after` and skip this file if the time has
not elapsed yet.

### Step 4 — Log the Queue Action

Call the **log-action** skill with:
```
action_type : "task_queued_for_retry"
actor       : <current actor>
target      : "needs_action/RETRY_<timestamp>_<original>"
parameters  : {
  "original_task": "<original>",
  "retry_count": <N>,
  "max_retries": 3,
  "retry_after": "<ISO timestamp>",
  "reason": "<error>"
}
result      : "success"
```

### Step 5 — Update Dashboard

Call the **dashboard-updater** skill (or note in system_logs.md) with a one-line
entry: `"RETRY queued: <original_task> (attempt <N>/3, after <HH:MM UTC>)"`

---

## Retry Cooldown Enforcement

When the `plan-creation-workflow` skill processes `needs_action/` items, it MUST
check the `retry_after` field on any `RETRY_*` file. If `retry_after` is in the
future, **skip** the file and leave it with status `pending` until the next cycle.

Example check (Python):
```python
from datetime import datetime, timezone
import json

meta = json.loads(meta_path.read_text())
retry_after = datetime.fromisoformat(meta.get("retry_after", "1970-01-01T00:00:00+00:00"))
if retry_after > datetime.now(timezone.utc):
    continue  # Not ready yet — skip this cycle
```

---

## Python Utility

```python
from skills.error_recovery import queue_for_later
from pathlib import Path

new_path = queue_for_later(
    task_path=Path("needs_action/EMAIL_abc123.md"),
    error="Gmail API quota exceeded after 5 retries",
    retry_after_hours=1.0,
    retry_count=meta.get("retry_count", 0),
    max_retries=3,
)

if new_path is None:
    # Max retries exceeded — graceful_degrade() was called automatically
    pass
```

---

## Output Contract

| Guarantee | Details |
|-----------|---------|
| File preserved | Original task content is never destroyed |
| Sidecar written | `RETRY_*.meta.json` always created alongside the task file |
| Retry count tracked | `retry_count` increments on every queue-for-later call |
| Max retries enforced | After 3 retries → graceful-degrade invoked + ALERT created |
| Audit entry | One `task_queued_for_retry` log entry per invocation |
| Cooldown respected | `retry_after` field prevents premature re-processing |
