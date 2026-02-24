#!/usr/bin/env python3
"""
watchdog.py — AI Employee Vault process monitor.

Starts and continuously monitors all long-running vault processes.
Restarts any process that exits unexpectedly.

Usage:
    python watchdog.py                         # watch all processes
    python watchdog.py --watch inbox-watcher   # watch specific process(es)
    python watchdog.py --status                # print current status and exit
    python watchdog.py --list                  # list watchable processes and exit

Requires: psutil (pip install psutil)
"""

import argparse
import json
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime, timezone

# ── Try psutil; fall back gracefully if not installed ──────────────────────
try:
    import psutil  # type: ignore
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

VAULT_ROOT = Path(__file__).parent
STATUS_FILE = VAULT_ROOT / "watchdog_status.json"
CHECK_INTERVAL = 30  # seconds between health checks

# ── Process catalogue ───────────────────────────────────────────────────────
WATCHED_PROCESSES: list[dict] = [
    {
        "name": "inbox-watcher",
        "script": "main.py",
        "cmd": [sys.executable, str(VAULT_ROOT / "main.py")],
        "restart_delay": 5,
        "description": "Core inbox watcher + task analyzer + agent chain",
        "auto_start": True,
    },
    {
        "name": "whatsapp-watcher",
        "script": "whatsapp_watcher.py",
        "cmd": [sys.executable, str(VAULT_ROOT / "whatsapp_watcher.py")],
        "restart_delay": 15,
        "description": "WhatsApp Web Playwright watcher (requires prior --login)",
        "auto_start": False,     # needs interactive QR scan first; opt-in
    },
    {
        "name": "linkedin-watcher",
        "script": "linkedin_watcher.py",
        "cmd": [sys.executable, str(VAULT_ROOT / "linkedin_watcher.py")],
        "restart_delay": 15,
        "description": "LinkedIn notifications Playwright watcher (requires prior --login)",
        "auto_start": False,
    },
    {
        "name": "gmail-watcher",
        "script": "gmail_watcher.py",
        "cmd": [sys.executable, str(VAULT_ROOT / "gmail_watcher.py")],
        "restart_delay": 10,
        "description": "Gmail API watcher (requires prior --auth)",
        "auto_start": False,
    },
]


# ── Internal state ──────────────────────────────────────────────────────────
_procs: dict[str, subprocess.Popen] = {}           # name → Popen
_restart_counts: dict[str, int] = {}               # name → number of restarts


# ── Logging ─────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _log(msg: str) -> None:
    line = f"[watchdog {_ts()}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", errors="replace").decode("ascii"), flush=True)


# ── Process management ───────────────────────────────────────────────────────

def is_alive(name: str) -> bool:
    """Return True if the tracked process is still running."""
    p = _procs.get(name)
    if p is None:
        return False
    return p.poll() is None   # None → still running


def start_process(cfg: dict) -> subprocess.Popen:
    """Launch the process defined by cfg; return the Popen handle."""
    _log(f"Starting {cfg['name']} …")
    p = subprocess.Popen(
        cfg["cmd"],
        cwd=str(VAULT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _log(f"  → {cfg['name']} started (PID {p.pid})")
    return p


def stop_process(name: str) -> None:
    """Terminate a tracked process gracefully, then kill if needed."""
    p = _procs.get(name)
    if p is None or p.poll() is not None:
        return
    _log(f"Stopping {name} (PID {p.pid}) …")
    p.terminate()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _log(f"  {name} did not stop in time — killing.")
        p.kill()


def check_and_restart(cfg: dict) -> bool:
    """
    Ensure the process is alive. If not, wait restart_delay then restart it.
    Returns True if the process is alive after this call.
    """
    name = cfg["name"]

    if is_alive(name):
        return True

    existing = _procs.get(name)
    if existing is not None:
        exit_code = existing.poll()
        _log(f"Process '{name}' exited (code {exit_code}). Waiting {cfg['restart_delay']}s before restart …")
        time.sleep(cfg["restart_delay"])
    else:
        _log(f"Process '{name}' not started yet.")

    try:
        _procs[name] = start_process(cfg)
        _restart_counts[name] = _restart_counts.get(name, 0) + 1
        return True
    except Exception as exc:
        _log(f"ERROR: Failed to start '{name}': {exc}")
        return False


# ── Status reporting ─────────────────────────────────────────────────────────

def _build_status(watch_list: list[dict]) -> dict:
    return {
        "checked_at": _ts(),
        "processes": {
            cfg["name"]: {
                "alive": is_alive(cfg["name"]),
                "pid": _procs[cfg["name"]].pid if is_alive(cfg["name"]) else None,
                "restarts": _restart_counts.get(cfg["name"], 0),
                "description": cfg["description"],
            }
            for cfg in watch_list
        },
    }


def write_status(watch_list: list[dict]) -> None:
    status = _build_status(watch_list)
    STATUS_FILE.write_text(json.dumps(status, indent=2), encoding="utf-8")


def print_status_table(watch_list: list[dict]) -> None:
    """Pretty-print current watchdog status to stdout."""
    status = _build_status(watch_list)
    print(f"\nWatchdog status at {status['checked_at']}")
    print(f"{'Name':<22} {'Alive':<8} {'PID':<9} {'Restarts':<10} Description")
    print("-" * 80)
    for name, info in status["processes"].items():
        alive_str = "YES" if info["alive"] else "NO"
        pid_str = str(info["pid"]) if info["pid"] else "—"
        print(f"{name:<22} {alive_str:<8} {pid_str:<9} {info['restarts']:<10} {info['description']}")
    print()


# ── psutil helpers (optional, for advanced diagnostics) ─────────────────────

def find_stale_vault_processes() -> list[dict]:
    """
    Use psutil to detect vault Python processes NOT tracked by this watchdog.
    Useful when watchdog restarts and previous PIDs are unknown.
    """
    if not _PSUTIL:
        return []
    stale = []
    vault_scripts = {cfg["script"] for cfg in WATCHED_PROCESSES}
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmd = " ".join(proc.info["cmdline"] or [])
            for script in vault_scripts:
                if script in cmd:
                    stale.append({"pid": proc.info["pid"], "cmd": cmd})
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return stale


# ── Main loop ────────────────────────────────────────────────────────────────

def run(watch_list: list[dict]) -> None:
    """Start all processes and loop, restarting any that die."""
    _log(f"Watchdog starting. Monitoring: {[c['name'] for c in watch_list]}")

    if _PSUTIL:
        stale = find_stale_vault_processes()
        if stale:
            _log(f"Found {len(stale)} pre-existing vault process(es) — they will be tracked by PID after restart.")

    # Initial launch
    for cfg in watch_list:
        try:
            _procs[cfg["name"]] = start_process(cfg)
            time.sleep(1)   # stagger starts
        except Exception as exc:
            _log(f"ERROR: Could not start '{cfg['name']}': {exc}")

    _log("All processes started. Entering health-check loop (every {CHECK_INTERVAL}s) …")

    while True:
        time.sleep(CHECK_INTERVAL)
        _log("─── Health check ───")
        for cfg in watch_list:
            alive = is_alive(cfg["name"])
            if alive:
                _log(f"  {cfg['name']}: OK (PID {_procs[cfg['name']].pid})")
            check_and_restart(cfg)
        write_status(watch_list)


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="AI Employee Vault process watchdog",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--watch",
        nargs="*",
        metavar="NAME",
        help="Names of processes to watch (default: all auto_start processes).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Watch ALL processes including those that require prior login (whatsapp, linkedin, gmail).",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Read watchdog_status.json and print it, then exit.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all watchable processes and exit.",
    )
    args = parser.parse_args()

    # ── --list ──
    if args.list:
        print("\nWatchable processes:")
        for cfg in WATCHED_PROCESSES:
            auto = "[auto_start]" if cfg["auto_start"] else "[manual]"
            print(f"  {cfg['name']:<24} {auto:<14} {cfg['description']}")
        print()
        return 0

    # ── --status ──
    if args.status:
        if STATUS_FILE.exists():
            data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
            print(json.dumps(data, indent=2))
        else:
            print("watchdog_status.json not found — watchdog may not be running.")
        return 0

    # ── Determine which processes to watch ──
    if args.watch:
        names = set(args.watch)
        watch_list = [cfg for cfg in WATCHED_PROCESSES if cfg["name"] in names]
        unknown = names - {cfg["name"] for cfg in watch_list}
        if unknown:
            print(f"ERROR: Unknown process name(s): {', '.join(unknown)}")
            print("Run with --list to see valid names.")
            return 1
    elif args.all:
        watch_list = WATCHED_PROCESSES
    else:
        watch_list = [cfg for cfg in WATCHED_PROCESSES if cfg["auto_start"]]

    if not watch_list:
        print("No processes selected. Use --list to see options or --all to start everything.")
        return 1

    try:
        run(watch_list)
    except KeyboardInterrupt:
        _log("Watchdog interrupted by user. Stopping managed processes …")
        for cfg in watch_list:
            stop_process(cfg["name"])
        _log("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
