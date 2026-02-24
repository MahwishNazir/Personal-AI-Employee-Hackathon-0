---
name: handle-transient-error
description: >
  Retry a failed action with exponential backoff (max 5 retries, delays 1→2→4→8→16s).
  For network, API, rate-limit, and other transient failures only.
  Always call this skill BEFORE escalating to queue-for-later or graceful-degrade.
---

# Handle Transient Error

## Purpose

Provide a structured, logged retry loop whenever an external call fails with a
transient error. This skill prevents unnecessary escalation by giving flaky
services a fair chance to recover before treating the failure as permanent.

**Pipeline position:** Inline — invoked mid-skill whenever an action raises a
transient exception. Not a standalone Silver Cycle step.

---

## When To Invoke This Skill

**MUST invoke** for any of these error signatures:
- HTTP 429 (rate-limited), 500, 502, 503, 504 from any external API
- `ConnectionRefusedError`, `TimeoutError`, `socket.timeout`
- Gmail API quota exceeded (`googleapiclient.errors.HttpError` with status 429/500)
- LinkedIn Playwright timeout (`playwright._impl._errors.TimeoutError`)
- Email MCP connection error (Node.js ECONNREFUSED / ETIMEDOUT)
- Any `requests.exceptions.ConnectionError` or `urllib3` retry-related error

**Do NOT invoke** for permanent errors — fix the root cause instead:
- HTTP 400 Bad Request (malformed payload)
- HTTP 401 Unauthorized / 403 Forbidden (credential refresh needed)
- File-not-found (`FileNotFoundError`)
- Python logic errors (`TypeError`, `AttributeError`, `AssertionError`)
- JSON parse errors

---

## Instructions

### Step 1 — Log the Initial Failure

Call the **log-action** skill with:
```
action_type : "transient_error_detected"
actor       : <current actor, e.g. "claude", "gmail-watcher">
target      : <what was being called, e.g. "gmail_api.messages.list">
parameters  : { "error": "<error message>", "attempt": 1, "max_retries": 5 }
result      : "fail"
```

### Step 2 — Retry with Exponential Backoff

Attempt the failed action up to **5 more times** (6 total attempts) using these
wait intervals between attempts:

| Attempt | Wait before retry |
|---------|-------------------|
| 1 → 2   | 1 second          |
| 2 → 3   | 2 seconds         |
| 3 → 4   | 4 seconds         |
| 4 → 5   | 8 seconds         |
| 5 → 6   | 16 seconds        |
| 6 fails | Escalate          |

Before each wait, log:
```
action_type : "retry_attempt"
parameters  : { "attempt": <N>, "wait_seconds": <W>, "last_error": "<msg>" }
result      : "pending"
```

### Step 3a — On Success (any attempt)

Log:
```
action_type : "transient_error_resolved"
parameters  : { "resolved_on_attempt": <N>, "total_wait_seconds": <sum> }
result      : "success"
```
Continue the normal workflow — no further escalation needed.

### Step 3b — On Exhaustion (all 6 attempts failed)

Log:
```
action_type : "transient_error_exhausted"
parameters  : { "total_attempts": 6, "final_error": "<last error message>" }
result      : "fail"
```

Then escalate — choose the appropriate skill:
- **Queued tasks, non-critical:** invoke `queue-for-later` with the task path and error message.
- **Critical actions (payments, system writes, integrations):** invoke `graceful-degrade`.

---

## Python Utility (for watchers and agents)

The `skills/error_recovery.py` module provides two ready-to-use patterns:

### Functional — wrap a single call

```python
from skills.error_recovery import with_retry

result = with_retry(
    gmail_api.messages().list,
    userId="me",
    labelIds=["INBOX"],
    max_retries=5,
    base_delay=1.0,
    retryable_exceptions=(HttpError, TimeoutError),
)
```

### Decorator — annotate a function

```python
from skills.error_recovery import retry

@retry(max_retries=5, base_delay=1.0, retryable_exceptions=(ConnectionError, TimeoutError))
def fetch_linkedin_notifications():
    ...
```

Both log automatically and raise the final exception if all retries fail, allowing
the caller to invoke `queue_for_later()` or `graceful_degrade()`.

---

## Output Contract

| Guarantee | Details |
|-----------|---------|
| Audit entries | At least 1 log entry per attempt (via log-action) |
| No silent swallowing | Every exception is logged before the next retry |
| On success | Workflow continues normally; no extra files created |
| On exhaustion | Escalation skill invoked; at least one RETRY_ or ALERT file created |
| Max wait | Total backoff capped at 1+2+4+8+16 = **31 seconds** across 5 retries |
