"""
error_recovery.py — Shared error recovery utilities for AI Employee Vault.

Provides three primitives:
  with_retry()      — exponential backoff for transient errors
  queue_for_later() — move failed task to needs_action/ with RETRY_ prefix
  graceful_degrade()— queue action locally + create Pending_Approval/ alert

Import from any watcher, agent, or skill:
    from skills.error_recovery import with_retry, queue_for_later, graceful_degrade
"""

import json
import time
import shutil
import functools
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Optional

VAULT_ROOT = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Exponential backoff
# ---------------------------------------------------------------------------

def with_retry(
    fn: Callable,
    *args,
    max_retries: int = 5,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
    on_retry: Optional[Callable[[int, Exception, float], None]] = None,
    **kwargs,
) -> Any:
    """
    Call fn(*args, **kwargs) with exponential backoff.

    Delays between attempts: base_delay * (backoff_factor ** attempt)
    Default schedule (base=1, factor=2): 1s → 2s → 4s → 8s → 16s

    Args:
        fn: Callable to retry.
        max_retries: Maximum number of retry attempts (not counting first try).
        base_delay: Initial wait in seconds.
        backoff_factor: Multiplier applied per attempt.
        retryable_exceptions: Tuple of exception types to catch and retry.
        on_retry: Optional callback(attempt, exc, delay) called before each sleep.
        *args / **kwargs: Passed through to fn.

    Returns:
        Return value of fn on success.

    Raises:
        Last caught exception if all attempts exhausted.
    """
    last_exc: Exception = RuntimeError("with_retry called with max_retries=0")
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except retryable_exceptions as exc:  # type: ignore[misc]
            last_exc = exc
            if attempt == max_retries:
                break
            delay = base_delay * (backoff_factor ** attempt)
            if on_retry:
                on_retry(attempt + 1, exc, delay)
            else:
                _log(f"attempt {attempt + 1}/{max_retries} failed: {exc!r} — retrying in {delay:.1f}s")
            time.sleep(delay)
    raise last_exc


def retry(
    max_retries: int = 5,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
):
    """
    Decorator version of with_retry.

    Usage:
        @retry(max_retries=5, base_delay=1.0)
        def call_external_api():
            ...
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return with_retry(
                fn,
                *args,
                max_retries=max_retries,
                base_delay=base_delay,
                backoff_factor=backoff_factor,
                retryable_exceptions=retryable_exceptions,
                **kwargs,
            )
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Queue failed task for later retry
# ---------------------------------------------------------------------------

def queue_for_later(
    task_path: Path,
    error: str,
    retry_after_hours: float = 1.0,
    retry_count: int = 0,
    max_retries: int = 3,
    extra_meta: Optional[dict] = None,
) -> Optional[Path]:
    """
    Move (copy) a failed task into needs_action/ with a RETRY_ prefix so that
    the next Silver Cycle picks it up after the cooldown period.

    Args:
        task_path: Path to the original task .md file.
        error: Human-readable description of why it failed.
        retry_after_hours: How many hours to wait before retrying.
        retry_count: How many times this task has already been retried.
        max_retries: Abandon the task if retry_count >= max_retries.
        extra_meta: Additional fields to merge into the .meta.json sidecar.

    Returns:
        Path to the new RETRY_*.md file, or None if max_retries exceeded.
    """
    task_path = Path(task_path)

    if retry_count >= max_retries:
        _log(
            f"ABANDONED {task_path.name} — exceeded max retries ({max_retries}). "
            f"Manual intervention required."
        )
        _write_abandoned_notice(task_path, error, retry_count)
        return None

    needs_action = VAULT_ROOT / "needs_action"
    needs_action.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    retry_after = now + timedelta(hours=retry_after_hours)
    ts = now.strftime("%Y%m%dT%H%M%S")

    new_name = f"RETRY_{ts}_{task_path.name}"
    new_path = needs_action / new_name

    # Copy the original file (or create a stub if it no longer exists)
    if task_path.exists():
        shutil.copy2(task_path, new_path)
    else:
        new_path.write_text(
            f"# Retry Task\n\nOriginal: `{task_path.name}`\nError: {error}\n",
            encoding="utf-8",
        )

    # Write metadata sidecar
    meta: dict = {
        "name": new_name,
        "original_task": task_path.name,
        "status": "pending",
        "retry_count": retry_count + 1,
        "max_retries": max_retries,
        "retry_after": retry_after.isoformat(),
        "retry_queued_at": now.isoformat(),
        "retry_reason": error,
        "size": new_path.stat().st_size,
    }
    if extra_meta:
        meta.update(extra_meta)

    meta_path = new_path.with_suffix(new_path.suffix + ".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    _log(
        f"Queued {task_path.name} → {new_name} "
        f"(retry #{retry_count + 1}/{max_retries}, after {retry_after.strftime('%Y-%m-%d %H:%M UTC')})"
    )
    return new_path


def _write_abandoned_notice(task_path: Path, error: str, retry_count: int) -> Path:
    """Write an ALERT into Pending_Approval when a task is permanently abandoned."""
    pending_dir = VAULT_ROOT / "Pending_Approval"
    pending_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%S")
    name = f"ALERT_abandoned_{ts}_{task_path.stem}.md"
    path = pending_dir / name
    path.write_text(
        f"---\ntype: alert\naction: task_abandoned\nstatus: pending\n"
        f"timestamp: {now.isoformat()}\npriority: high\n---\n\n"
        f"# ALERT: Task Permanently Abandoned\n\n"
        f"**Task:** `{task_path.name}`\n"
        f"**Retries exhausted:** {retry_count}\n"
        f"**Final error:** {error}\n\n"
        f"This task has been retried {retry_count} times and has not succeeded.\n"
        f"Manual intervention is required.\n\n"
        f"**Instructions:** Investigate `needs_action/`, fix the root cause, then move this file to `Rejected/`.\n",
        encoding="utf-8",
    )
    # Sidecar
    meta_path = path.with_suffix(path.suffix + ".meta.json")
    meta_path.write_text(
        json.dumps({
            "name": name,
            "action": "task_abandoned",
            "original_task": task_path.name,
            "status": "pending_approval",
            "created_at": now.isoformat(),
            "priority": "high",
        }, indent=2),
        encoding="utf-8",
    )
    _log(f"Abandoned-task alert written: {name}")
    return path


# ---------------------------------------------------------------------------
# Graceful degradation on critical failure
# ---------------------------------------------------------------------------

def graceful_degrade(
    failed_action: str,
    error: str,
    deferred_payload: dict,
    priority: str = "high",
    actor: str = "claude",
    service_name: Optional[str] = None,
) -> Path:
    """
    On a critical / non-transient failure:
      1. Append the failed action to deferred_queue.json (no data loss).
      2. Create ALERT_critical_failure_*.md in Pending_Approval/ for human review.

    Args:
        failed_action: Short slug of what was attempted, e.g. "send_email", "post_linkedin".
        error: Exception message or human-readable error description.
        deferred_payload: Full payload of the failed action (will be pretty-printed in the alert).
        priority: "high" | "medium" | "low" — controls urgency label in the alert.
        actor: Who triggered the action ("claude", "gmail-watcher", etc.).
        service_name: Optional name of the failing service, e.g. "Odoo", "email-mcp".

    Returns:
        Path to the created Pending_Approval/ alert file.
    """
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%S")
    service_label = service_name or failed_action

    # --- 1. Append to deferred queue (persistent, survives restarts) ---
    queue_path = VAULT_ROOT / "deferred_queue.json"
    queue: list = []
    if queue_path.exists():
        try:
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            queue = []

    entry_id = f"deferred_{ts}"
    entry = {
        "id": entry_id,
        "action": failed_action,
        "service": service_label,
        "error": error,
        "actor": actor,
        "payload": deferred_payload,
        "queued_at": now.isoformat(),
        "status": "deferred",          # deferred | retried | resolved | dismissed
    }
    queue.append(entry)
    queue_path.write_text(json.dumps(queue, indent=2), encoding="utf-8")
    _log(f"Deferred action '{failed_action}' added to deferred_queue.json (id={entry_id})")

    # --- 2. Create Pending_Approval/ alert for human notification ---
    pending_dir = VAULT_ROOT / "Pending_Approval"
    pending_dir.mkdir(parents=True, exist_ok=True)

    notif_name = f"ALERT_critical_failure_{ts}.md"
    notif_path = pending_dir / notif_name

    payload_json = json.dumps(deferred_payload, indent=2)
    risk_irreversibility = "Low" if failed_action.startswith("read") else "High"
    risk_service = "High" if service_name else "Medium"

    notif_content = f"""---
type: alert
action: critical_failure
failed_action: {failed_action}
service: {service_label}
actor: {actor}
timestamp: {now.isoformat()}
priority: {priority}
status: pending
deferred_entry_id: {entry_id}
---

# ALERT: Critical System Failure — Action Required

## What Failed

| Field | Value |
|-------|-------|
| **Action** | `{failed_action}` |
| **Service** | `{service_label}` |
| **Actor** | `{actor}` |
| **Error** | `{error}` |
| **Time** | {now.strftime("%Y-%m-%d %H:%M:%S UTC")} |
| **Deferred ID** | `{entry_id}` |

## What Was Attempted

```json
{payload_json}
```

## Current State

The failed action has been safely saved to `deferred_queue.json` (entry `{entry_id}`).
**No data was lost.** The action is queued locally and will not be retried automatically.

## Risk Assessment

| Risk | Level | Notes |
|------|-------|-------|
| Data Loss | Low | Action preserved in deferred_queue.json |
| Service Impact | {risk_service} | `{service_label}` is unavailable |
| Irreversibility | {risk_irreversibility} | Action was not executed |
| Financial | Low | No payment involved |

**Overall Risk:** {priority.capitalize()}

## Human Instructions

1. **Investigate:** Check if `{service_label}` is restored
2. **Retry:** To re-attempt the action, move this file to `Approved/`
3. **Dismiss:** To abandon it, move this file to `Rejected/` and update `deferred_queue.json`
4. **Manual fix:** Resolve the underlying issue and delete this file when done
"""

    notif_path.write_text(notif_content, encoding="utf-8")

    # Sidecar meta
    meta_path = notif_path.with_suffix(notif_path.suffix + ".meta.json")
    meta_path.write_text(
        json.dumps({
            "name": notif_name,
            "action": "critical_failure_alert",
            "failed_action": failed_action,
            "service": service_label,
            "status": "pending_approval",
            "created_at": now.isoformat(),
            "priority": priority,
            "deferred_entry_id": entry_id,
        }, indent=2),
        encoding="utf-8",
    )

    _log(f"Critical-failure alert created: {notif_name}")
    return notif_path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    try:
        print(f"[error-recovery {ts}] {msg}", flush=True)
    except UnicodeEncodeError:
        print(
            f"[error-recovery {ts}] {msg}".encode("ascii", errors="replace").decode("ascii"),
            flush=True,
        )
