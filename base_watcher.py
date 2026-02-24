# base_watcher.py - Template for all watchers
import json
import time
import logging
from pathlib import Path
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from audit_logger import log_action
from skills.error_recovery import with_retry, graceful_degrade

# Transient network/API errors that trigger automatic retry
_TRANSIENT_EXCEPTIONS = (
    ConnectionRefusedError,
    ConnectionResetError,
    TimeoutError,
    OSError,   # covers most socket-level errors
)


class BaseWatcher(ABC):
    def __init__(self, vault_path: str, check_interval: int = 60):
        self.vault_path = Path(vault_path)
        self.needs_action = self.vault_path / "needs_action"
        self.needs_action.mkdir(parents=True, exist_ok=True)
        self.check_interval = check_interval
        self.logger = logging.getLogger(self.__class__.__name__)
        self._seen_ids: set[str] = set()

    @abstractmethod
    def check_for_updates(self) -> list:
        """Return list of new items to process"""
        pass

    @abstractmethod
    def create_action_file(self, item) -> Path:
        """Create .md file in Needs_Action folder"""
        pass

    def write_meta(self, task_path: Path, meta_extra: dict = None) -> Path:
        """Write a .meta.json sidecar for a task file already on disk."""
        meta = {
            "name": task_path.name,
            "size": task_path.stat().st_size,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        }
        if meta_extra:
            meta.update(meta_extra)

        meta_path = task_path.with_suffix(task_path.suffix + ".meta.json")
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return meta_path

    def run(self):
        actor = self.__class__.__name__.lower().replace("watcher", "-watcher")
        self.logger.info(f"Starting {self.__class__.__name__}")
        while True:
            try:
                log_action(
                    action_type="watcher_scan",
                    actor=actor,
                    target="needs_action/",
                    parameters={"source": actor},
                    approval_status="n_a",
                    result="pending",
                )

                # Wrap check_for_updates with automatic exponential backoff
                # (max 5 retries: 1→2→4→8→16s) for transient network errors.
                items = with_retry(
                    self.check_for_updates,
                    max_retries=5,
                    base_delay=1.0,
                    retryable_exceptions=_TRANSIENT_EXCEPTIONS,
                    on_retry=lambda attempt, exc, delay: log_action(
                        action_type="retry_attempt",
                        actor=actor,
                        target="check_for_updates",
                        parameters={"attempt": attempt, "wait_seconds": delay, "error": str(exc)},
                        result="pending",
                    ),
                )

                for item in items:
                    self.create_action_file(item)

                log_action(
                    action_type="watcher_scan",
                    actor=actor,
                    target="needs_action/",
                    parameters={"source": actor, "items_found": len(items)},
                    approval_status="n_a",
                    result="success",
                )

            except _TRANSIENT_EXCEPTIONS as e:
                # All 5 retries exhausted — defer via graceful_degrade so no
                # scan is silently dropped and the human is notified.
                self.logger.error(f"All retries exhausted: {e}")
                log_action(
                    action_type="transient_error_exhausted",
                    actor=actor,
                    target="check_for_updates",
                    parameters={"source": actor, "total_attempts": 6},
                    result="fail",
                    error=str(e),
                )
                graceful_degrade(
                    failed_action="watcher_scan",
                    error=str(e),
                    deferred_payload={"watcher": actor, "interval": self.check_interval},
                    priority="medium",
                    actor=actor,
                    service_name=actor,
                )

            except Exception as e:
                # Non-transient or unexpected error — log and continue loop
                self.logger.error(f"Error: {e}")
                log_action(
                    action_type="error",
                    actor=actor,
                    target="needs_action/",
                    parameters={"source": actor},
                    approval_status="n_a",
                    result="fail",
                    error=str(e),
                )

            time.sleep(self.check_interval)
