# base_watcher.py - Template for all watchers
import json
import time
import logging
from pathlib import Path
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from audit_logger import log_action


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
                items = self.check_for_updates()
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
            except Exception as e:
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
