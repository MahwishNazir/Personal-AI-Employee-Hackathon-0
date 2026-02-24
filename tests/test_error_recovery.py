"""
tests/test_error_recovery.py — Unit tests for skills/error_recovery.py

Run from the vault root:
    python -m pytest tests/test_error_recovery.py -v
    # or without pytest:
    python tests/test_error_recovery.py
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, call

# ── Make sure `skills/` is importable from project root ──────────────────────
VAULT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(VAULT_ROOT))

# Patch VAULT_ROOT in the module to use a temp dir during tests
import skills.error_recovery as er


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

class TempVault:
    """Context manager that gives error_recovery a throwaway vault directory."""

    def __enter__(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        # Patch VAULT_ROOT inside the module
        self._orig = er.VAULT_ROOT
        er.VAULT_ROOT = self.root
        # Create needed sub-dirs
        (self.root / "needs_action").mkdir()
        (self.root / "Pending_Approval").mkdir()
        return self

    def __exit__(self, *_):
        er.VAULT_ROOT = self._orig
        self._td.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
#  with_retry
# ─────────────────────────────────────────────────────────────────────────────

class TestWithRetry(unittest.TestCase):

    def test_success_on_first_attempt(self):
        """Function that succeeds immediately — no delay, returns value."""
        result = er.with_retry(lambda: 42, max_retries=5, base_delay=0)
        self.assertEqual(result, 42)

    def test_success_after_retries(self):
        """Function fails twice then succeeds — returns correct value."""
        call_count = {"n": 0}

        def flaky():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ConnectionError("boom")
            return "ok"

        result = er.with_retry(flaky, max_retries=5, base_delay=0)
        self.assertEqual(result, "ok")
        self.assertEqual(call_count["n"], 3)

    def test_raises_after_max_retries(self):
        """Function always fails — should raise after max_retries+1 attempts."""
        call_count = {"n": 0}

        def always_fail():
            call_count["n"] += 1
            raise TimeoutError("timeout")

        with self.assertRaises(TimeoutError):
            er.with_retry(always_fail, max_retries=3, base_delay=0)

        self.assertEqual(call_count["n"], 4)   # 1 initial + 3 retries

    def test_only_catches_specified_exceptions(self):
        """Non-retryable exceptions bubble up immediately."""
        call_count = {"n": 0}

        def raises_value_error():
            call_count["n"] += 1
            raise ValueError("not retryable")

        with self.assertRaises(ValueError):
            er.with_retry(
                raises_value_error,
                max_retries=5,
                base_delay=0,
                retryable_exceptions=(ConnectionError,),
            )
        self.assertEqual(call_count["n"], 1)   # no retries

    def test_on_retry_callback_called(self):
        """on_retry callback is called once per retry (not on first attempt)."""
        call_count = {"n": 0}
        retry_log = []

        def flaky():
            call_count["n"] += 1
            if call_count["n"] <= 2:
                raise ConnectionError("x")
            return "done"

        er.with_retry(
            flaky,
            max_retries=5,
            base_delay=0,
            on_retry=lambda attempt, exc, delay: retry_log.append(attempt),
        )
        self.assertEqual(retry_log, [1, 2])

    def test_backoff_delays(self):
        """Sleep is called with correct exponential delays."""
        attempts = []

        def always_fail():
            raise ConnectionError("x")

        with patch("skills.error_recovery.time.sleep") as mock_sleep:
            with self.assertRaises(ConnectionError):
                er.with_retry(always_fail, max_retries=4, base_delay=1.0, backoff_factor=2.0)

        delays = [c.args[0] for c in mock_sleep.call_args_list]
        # Expect: 1, 2, 4, 8
        self.assertEqual(delays, [1.0, 2.0, 4.0, 8.0])

    def test_args_and_kwargs_forwarded(self):
        """Positional and keyword arguments are passed through to the function."""
        def add(a, b, *, mult=1):
            return (a + b) * mult

        result = er.with_retry(add, 3, 4, mult=2, max_retries=1, base_delay=0)
        self.assertEqual(result, 14)


# ─────────────────────────────────────────────────────────────────────────────
#  @retry decorator
# ─────────────────────────────────────────────────────────────────────────────

class TestRetryDecorator(unittest.TestCase):

    def test_decorator_success(self):
        @er.retry(max_retries=3, base_delay=0)
        def fn():
            return "hello"

        self.assertEqual(fn(), "hello")

    def test_decorator_retries_and_succeeds(self):
        count = {"n": 0}

        @er.retry(max_retries=5, base_delay=0)
        def fn():
            count["n"] += 1
            if count["n"] < 3:
                raise OSError("retry me")
            return count["n"]

        result = fn()
        self.assertEqual(result, 3)

    def test_decorator_raises_on_exhaustion(self):
        @er.retry(max_retries=2, base_delay=0)
        def fn():
            raise TimeoutError("always")

        with self.assertRaises(TimeoutError):
            fn()

    def test_decorator_preserves_function_name(self):
        @er.retry(max_retries=1, base_delay=0)
        def my_special_function():
            return 1

        self.assertEqual(my_special_function.__name__, "my_special_function")


# ─────────────────────────────────────────────────────────────────────────────
#  queue_for_later
# ─────────────────────────────────────────────────────────────────────────────

class TestQueueForLater(unittest.TestCase):

    def test_creates_retry_file(self):
        """RETRY_*.md is created in needs_action/ with correct content."""
        with TempVault() as v:
            orig = v.root / "needs_action" / "EMAIL_abc.md"
            orig.write_text("# Original task", encoding="utf-8")

            new_path = er.queue_for_later(orig, error="timeout", retry_after_hours=1)

            self.assertIsNotNone(new_path)
            self.assertTrue(new_path.exists())
            self.assertTrue(new_path.name.startswith("RETRY_"))
            self.assertIn("EMAIL_abc.md", new_path.name)

    def test_creates_meta_sidecar(self):
        """RETRY_ file must have a .meta.json sidecar with correct fields."""
        with TempVault() as v:
            orig = v.root / "needs_action" / "TASK_001.md"
            orig.write_text("task content", encoding="utf-8")

            new_path = er.queue_for_later(orig, error="rate limit", retry_count=0, max_retries=3)

            meta_path = new_path.with_suffix(new_path.suffix + ".meta.json")
            self.assertTrue(meta_path.exists())

            meta = json.loads(meta_path.read_text())
            self.assertEqual(meta["original_task"], "TASK_001.md")
            self.assertEqual(meta["status"], "pending")
            self.assertEqual(meta["retry_count"], 1)
            self.assertEqual(meta["max_retries"], 3)
            self.assertIn("retry_after", meta)
            self.assertIn("retry_reason", meta)

    def test_retry_after_is_one_hour_ahead(self):
        """retry_after must be approximately 1 hour from now."""
        with TempVault() as v:
            orig = v.root / "needs_action" / "TASK_002.md"
            orig.write_text("x", encoding="utf-8")

            before = datetime.now(timezone.utc)
            new_path = er.queue_for_later(orig, error="err", retry_after_hours=1.0)
            after = datetime.now(timezone.utc)

            meta = json.loads(
                new_path.with_suffix(new_path.suffix + ".meta.json").read_text()
            )
            retry_after = datetime.fromisoformat(meta["retry_after"])

            self.assertGreaterEqual(retry_after, before + timedelta(hours=1))
            self.assertLessEqual(retry_after, after + timedelta(hours=1, seconds=2))

    def test_returns_none_when_max_retries_exceeded(self):
        """Returns None and creates an ALERT when retry_count >= max_retries."""
        with TempVault() as v:
            orig = v.root / "needs_action" / "TASK_003.md"
            orig.write_text("x", encoding="utf-8")

            result = er.queue_for_later(orig, error="fail", retry_count=3, max_retries=3)

            self.assertIsNone(result)
            # Should have created an ALERT in Pending_Approval/
            alerts = list((v.root / "Pending_Approval").glob("ALERT_abandoned_*.md"))
            self.assertEqual(len(alerts), 1)

    def test_stub_created_when_original_missing(self):
        """If the original file no longer exists, a stub is written instead."""
        with TempVault() as v:
            fake_path = v.root / "needs_action" / "MISSING_TASK.md"
            # Do NOT create the file

            new_path = er.queue_for_later(fake_path, error="original gone")

            self.assertIsNotNone(new_path)
            self.assertTrue(new_path.exists())
            content = new_path.read_text()
            self.assertIn("MISSING_TASK.md", content)

    def test_extra_meta_merged(self):
        """extra_meta fields appear in the sidecar JSON."""
        with TempVault() as v:
            orig = v.root / "needs_action" / "TASK_004.md"
            orig.write_text("x", encoding="utf-8")

            new_path = er.queue_for_later(
                orig, error="err",
                extra_meta={"source": "gmail", "gmail_id": "abc123"},
            )
            meta = json.loads(
                new_path.with_suffix(new_path.suffix + ".meta.json").read_text()
            )
            self.assertEqual(meta["source"], "gmail")
            self.assertEqual(meta["gmail_id"], "abc123")

    def test_no_retry_file_created_when_max_exceeded(self):
        """When max retries exceeded, no RETRY_ file should be created."""
        with TempVault() as v:
            orig = v.root / "needs_action" / "TASK_005.md"
            orig.write_text("x", encoding="utf-8")

            er.queue_for_later(orig, error="fail", retry_count=5, max_retries=3)

            retry_files = list((v.root / "needs_action").glob("RETRY_*"))
            self.assertEqual(len(retry_files), 0)


# ─────────────────────────────────────────────────────────────────────────────
#  graceful_degrade
# ─────────────────────────────────────────────────────────────────────────────

class TestGracefulDegrade(unittest.TestCase):

    def test_creates_alert_file(self):
        """ALERT_critical_failure_*.md is created in Pending_Approval/."""
        with TempVault() as v:
            alert = er.graceful_degrade(
                failed_action="send_email",
                error="ECONNREFUSED",
                deferred_payload={"to": "user@example.com", "subject": "Test"},
            )
            self.assertTrue(alert.exists())
            self.assertTrue(alert.name.startswith("ALERT_critical_failure_"))

    def test_alert_meta_sidecar(self):
        """Alert .meta.json has correct fields."""
        with TempVault() as v:
            alert = er.graceful_degrade(
                failed_action="post_linkedin",
                error="Playwright timeout",
                deferred_payload={"post_text": "Hello world"},
                priority="medium",
                actor="linkedin-watcher",
            )
            meta_path = alert.with_suffix(alert.suffix + ".meta.json")
            self.assertTrue(meta_path.exists())
            meta = json.loads(meta_path.read_text())
            self.assertEqual(meta["failed_action"], "post_linkedin")
            self.assertEqual(meta["status"], "pending_approval")
            self.assertEqual(meta["priority"], "medium")
            self.assertIn("deferred_entry_id", meta)

    def test_deferred_queue_written(self):
        """deferred_queue.json is created and contains the entry."""
        with TempVault() as v:
            er.graceful_degrade(
                failed_action="send_email",
                error="timeout",
                deferred_payload={"to": "a@b.com"},
            )
            queue_path = v.root / "deferred_queue.json"
            self.assertTrue(queue_path.exists())
            queue = json.loads(queue_path.read_text())
            self.assertEqual(len(queue), 1)
            self.assertEqual(queue[0]["action"], "send_email")
            self.assertEqual(queue[0]["status"], "deferred")
            self.assertIn("payload", queue[0])
            self.assertEqual(queue[0]["payload"]["to"], "a@b.com")

    def test_deferred_queue_appends(self):
        """Multiple calls append entries rather than overwriting."""
        with TempVault() as v:
            er.graceful_degrade("send_email", "err1", {"to": "a@b.com"})
            er.graceful_degrade("post_linkedin", "err2", {"text": "hello"})

            queue = json.loads((v.root / "deferred_queue.json").read_text())
            self.assertEqual(len(queue), 2)
            actions = {e["action"] for e in queue}
            self.assertEqual(actions, {"send_email", "post_linkedin"})

    def test_alert_contains_payload(self):
        """The alert .md file contains the pretty-printed payload."""
        with TempVault() as v:
            alert = er.graceful_degrade(
                failed_action="send_email",
                error="ECONNREFUSED",
                deferred_payload={"to": "boss@corp.com", "subject": "Urgent"},
            )
            content = alert.read_text()
            self.assertIn("boss@corp.com", content)
            self.assertIn("Urgent", content)

    def test_service_name_used_in_alert(self):
        """service_name overrides failed_action as the display label."""
        with TempVault() as v:
            alert = er.graceful_degrade(
                failed_action="odoo_write",
                error="503",
                deferred_payload={},
                service_name="Odoo ERP",
            )
            content = alert.read_text()
            self.assertIn("Odoo ERP", content)

    def test_deferred_queue_survives_corrupt_json(self):
        """If deferred_queue.json is corrupt, it is reset rather than crashing."""
        with TempVault() as v:
            (v.root / "deferred_queue.json").write_text("NOT JSON", encoding="utf-8")

            # Should not raise
            er.graceful_degrade("act", "err", {})

            queue = json.loads((v.root / "deferred_queue.json").read_text())
            self.assertEqual(len(queue), 1)

    def test_alert_includes_human_instructions(self):
        """Alert file must contain the human instruction section."""
        with TempVault() as v:
            alert = er.graceful_degrade("act", "err", {})
            content = alert.read_text()
            self.assertIn("Human Instructions", content)
            self.assertIn("Approved/", content)
            self.assertIn("Rejected/", content)


# ─────────────────────────────────────────────────────────────────────────────
#  Integration: full escalation path
# ─────────────────────────────────────────────────────────────────────────────

class TestEscalationPath(unittest.TestCase):
    """Simulate the full handle-transient-error → queue-for-later → graceful-degrade chain."""

    def test_retry_exhaustion_feeds_queue_for_later(self):
        """
        with_retry exhausts → caller invokes queue_for_later →
        RETRY_ file created with correct retry_count.
        """
        with TempVault() as v:
            orig = v.root / "needs_action" / "EMAIL_xyz.md"
            orig.write_text("# task", encoding="utf-8")

            always_fail = MagicMock(side_effect=ConnectionError("nope"))

            with self.assertRaises(ConnectionError):
                er.with_retry(always_fail, max_retries=5, base_delay=0)

            # Caller now calls queue_for_later
            new_path = er.queue_for_later(orig, error="ConnectionError: nope", retry_count=0)
            self.assertIsNotNone(new_path)

            meta = json.loads(new_path.with_suffix(new_path.suffix + ".meta.json").read_text())
            self.assertEqual(meta["retry_count"], 1)

    def test_max_retries_exceeded_triggers_graceful_degrade(self):
        """
        queue_for_later called at max_retries returns None →
        caller invokes graceful_degrade.
        """
        with TempVault() as v:
            orig = v.root / "needs_action" / "EMAIL_xyz.md"
            orig.write_text("# task", encoding="utf-8")

            result = er.queue_for_later(
                orig, error="persistent error",
                retry_count=3, max_retries=3,
            )
            self.assertIsNone(result)

            # Should also have created a Pending_Approval ALERT from _write_abandoned_notice
            alerts = list((v.root / "Pending_Approval").glob("ALERT_abandoned_*.md"))
            self.assertEqual(len(alerts), 1)


# ─────────────────────────────────────────────────────────────────────────────
#  Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Patch time.sleep to make tests fast (no real waiting)
    with patch("skills.error_recovery.time.sleep"):
        result = unittest.main(verbosity=2, exit=False)
    sys.exit(0 if result.result.wasSuccessful() else 1)
