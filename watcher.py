"""
watcher.py - Inbox Folder Monitor

Watches the 'inbox' folder for new files. When a new file appears,
it copies it to 'needs_action' and creates a companion .meta.json
file containing metadata (name, size, timestamp, status).

Uses a polling loop (no external dependencies). For production use,
consider replacing with the 'watchdog' library for event-driven monitoring.
"""

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from audit_logger import log_action, ACTOR_WATCHER

# ── Configuration ──────────────────────────────────────────────────────────
VAULT_DIR = Path(__file__).parent          # Root of the vault
INBOX_DIR = VAULT_DIR / "inbox"            # Where new files arrive
NEEDS_ACTION_DIR = VAULT_DIR / "needs_action"  # Where processed files go
POLL_INTERVAL = 2  # Seconds between each scan of the inbox

# Track files we've already processed so we don't copy them again
_seen_files: set[str] = set()


def ensure_directories() -> None:
    """Create inbox and needs_action folders if they don't exist."""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    NEEDS_ACTION_DIR.mkdir(parents=True, exist_ok=True)


def build_metadata(file_path: Path) -> dict:
    """
    Build a metadata dictionary for a given file.

    Returns dict with:
        - name:      original filename
        - size:      file size in bytes
        - timestamp: ISO-8601 UTC time of processing
        - status:    always 'pending' for newly detected files
    """
    stat = file_path.stat()
    return {
        "name": file_path.name,
        "size": stat.st_size,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }


def write_metadata(meta: dict, dest_path: Path) -> Path:
    """
    Write metadata to a .meta.json file alongside the copied file.

    Example: 'report.pdf' -> 'report.pdf.meta.json'
    """
    meta_path = dest_path.with_suffix(dest_path.suffix + ".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta_path


def process_file(file_path: Path) -> None:
    """
    Handle a single new file detected in the inbox:
      1. Copy the file to needs_action/
      2. Generate and write a .meta.json sidecar file
      3. Log the action to the console and audit log
    """
    dest_path = NEEDS_ACTION_DIR / file_path.name

    try:
        # Copy the file (preserving metadata like modification time)
        shutil.copy2(file_path, dest_path)

        # Create the companion metadata file
        meta = build_metadata(file_path)
        meta_path = write_metadata(meta, dest_path)

        print(f"[watcher] Processed: {file_path.name}")
        print(f"          -> Copied to:  {dest_path}")
        print(f"          -> Metadata:   {meta_path}")
        print(f"          -> Status:     {meta['status']}")

        log_action(
            action_type="file_write",
            actor=ACTOR_WATCHER,
            target=f"needs_action/{file_path.name}",
            parameters={"size": meta["size"], "source": "inbox"},
            approval_status="n_a",
            result="success",
        )
    except Exception as exc:
        log_action(
            action_type="file_write",
            actor=ACTOR_WATCHER,
            target=f"needs_action/{file_path.name}",
            parameters={"source": "inbox"},
            approval_status="n_a",
            result="fail",
            error=str(exc),
        )
        raise


def scan_inbox() -> None:
    """
    Scan the inbox directory for new files that haven't been processed yet.
    Skips directories and any files already seen this session.
    """
    for item in INBOX_DIR.iterdir():
        # Only process regular files (skip subdirectories)
        if not item.is_file():
            continue

        # Skip files we've already handled
        if item.name in _seen_files:
            continue

        # Mark as seen and process
        _seen_files.add(item.name)
        process_file(item)


def watch(on_cycle=None) -> None:
    """
    Main polling loop. Continuously scans the inbox folder at a fixed
    interval and processes any new files that appear.

    Args:
        on_cycle: Optional callback or list of callbacks invoked after each
                  scan cycle. Use this to hook in additional processing
                  (e.g. task analysis, task agent).

    Press Ctrl+C to stop the watcher gracefully.
    """
    ensure_directories()

    # Normalise on_cycle into a list of callables
    if on_cycle is None:
        callbacks = []
    elif callable(on_cycle):
        callbacks = [on_cycle]
    else:
        callbacks = list(on_cycle)

    # Pre-populate seen files so we don't re-process existing inbox contents
    for item in INBOX_DIR.iterdir():
        if item.is_file():
            _seen_files.add(item.name)
    print(f"[watcher] Skipping {len(_seen_files)} existing file(s) in inbox.")

    print(f"[watcher] Watching '{INBOX_DIR}' every {POLL_INTERVAL}s ...")
    print("[watcher] Press Ctrl+C to stop.\n")

    try:
        while True:
            scan_inbox()
            # Run post-scan hooks (e.g. analyzer, then agent)
            for cb in callbacks:
                cb()
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\n[watcher] Stopped.")


# ── Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    watch()
