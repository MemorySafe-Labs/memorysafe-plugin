from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .bootstrap_catalog import VERSION
from .server import main as run_mcp_server


PRODUCT = "MemorySafe Beta"
_RECORD_NAME = "dashboard.json"


def _dashboard_is_running(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def _dashboard_status(host: str, port: int) -> dict | None:
    """The version a MemorySafe dashboard on the port reports, and the PID serving it."""

    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/status", timeout=0.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("product") != PRODUCT:
        return None
    version = payload.get("version")
    if not isinstance(version, str):
        return None
    pid = payload.get("pid")
    # bool is an int subclass; a dashboard from before the PID was reported sends none.
    return {"version": version, "pid": pid if isinstance(pid, int) and not isinstance(pid, bool) else None}


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_dashboard_record(state_dir: Path) -> dict | None:
    try:
        record = json.loads((state_dir / _RECORD_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or not isinstance(record.get("pid"), int):
        return None
    return record


def _write_dashboard_record(state_dir: Path, pid: int) -> None:
    target = state_dir / _RECORD_NAME
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps({"pid": pid, "version": VERSION, "plugin_root": str(Path(__file__).resolve().parents[2])}),
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _replace_stale_dashboard(host: str, port: int, state_dir: Path) -> bool:
    """Stop a dashboard this launcher started from an older plugin. True once the port is free.

    A plugin update deletes the folder that dashboard was started from, but the process
    keeps the port and serves stale code whose lazy imports now point at nothing. Only
    a process this launcher recorded is ever stopped: the macOS installer's launchd agent
    restarts itself and would fight back.

    What proves the recorded process owns the port is the port's own answer: /api/status
    reports the PID serving it, and it must equal the recorded PID. A live recorded PID
    and a matching version are not enough, because after a reboot the PID can belong to
    an unrelated process while a launchd dashboard reports the recorded version. The
    version must also differ from this launcher's and match the record.
    """

    if os.name == "nt":
        # os.kill(pid, 0) terminates the process on Windows. Deferred to the Windows port.
        return False
    record = _read_dashboard_record(state_dir)
    if record is None or not _process_alive(record["pid"]):
        return False
    running = _dashboard_status(host, port)
    if (
        running is None
        or running["pid"] != record["pid"]
        or running["version"] == VERSION
        or running["version"] != record.get("version")
    ):
        return False
    try:
        os.kill(record["pid"], signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        # The recorded PID can outlive the process it named, same as in
        # _process_alive above; the gap here is the network round trip to
        # _dashboard_status, during which the process can exit or its PID
        # be reused by another user. Either way, leave the port alone rather
        # than let the exception stop the MCP server from starting.
        return False
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if not _dashboard_is_running(host, port):
            return True
        time.sleep(0.1)
    return False


def _start_dashboard() -> None:
    host = "127.0.0.1"
    port = int(os.environ.get("MEMORYSAFE_SETUP_PORT", "8765"))
    state_dir = Path(
        os.environ.get(
            "MEMORYSAFE_STATE_DIR",
            Path.home() / "Library" / "Application Support" / "MemorySafe" / "runtime-state",
        )
    ).expanduser()
    if _dashboard_is_running(host, port) and not _replace_stale_dashboard(host, port, state_dir):
        return

    log_dir = state_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = (log_dir / "claude-dashboard.log").open("ab")
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "memorysafe_chatgpt.setup_app"],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        log_file.close()
    try:
        _write_dashboard_record(state_dir, int(process.pid))
    except OSError:
        pass


def main() -> None:
    _start_dashboard()
    run_mcp_server()


if __name__ == "__main__":
    main()
