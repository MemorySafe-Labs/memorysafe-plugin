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


# subprocess exposes these only on Windows; spelled out so this module imports
# and its tests run on Linux.
_DETACHED_PROCESS = 0x00000008
_CREATE_NO_WINDOW = 0x08000000


def _windows_process_alive(pid: int) -> bool:
    # Kept separate so _process_alive's branch is testable on Linux: ctypes.windll
    # does not exist here, so the tests patch this function rather than ctypes.
    # STILL_ACTIVE means the handle refers to a live process rather than one that
    # has exited but not been reaped.
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _process_alive(pid: int) -> bool:
    if os.name == "nt":
        # os.kill(pid, 0) TERMINATES the target on Windows rather than probing it.
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _dashboard_spawn_options() -> dict:
    if os.name == "nt":
        return {"creationflags": _DETACHED_PROCESS | _CREATE_NO_WINDOW}
    return {"start_new_session": True}


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
        if os.name == "nt":
            # Windows has no SIGTERM to forward; TerminateProcess (what
            # Popen.terminate() calls) is the only stop signal available, and
            # taskkill is the documented way to reach it by PID without first
            # opening a handle ourselves. /T also takes any child the stale
            # dashboard spawned, since a bare TerminateProcess would not.
            # A non-zero exit (already gone, access denied) is left to the
            # polling loop below rather than raised, same as the POSIX branch.
            subprocess.run(
                ["taskkill", "/PID", str(record["pid"]), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_CREATE_NO_WINDOW,
            )
        else:
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


def _default_state_dir() -> Path:
    """The state dir this launcher falls back to when MEMORYSAFE_STATE_DIR is unset.

    Mirrors the three-way platform split in cli.py's _resolve_database: win32 ->
    %LOCALAPPDATA%, darwin -> ~/Library/Application Support, else XDG. This used to
    hardcode the darwin branch with no platform check at all, so a Windows run
    without MEMORYSAFE_STATE_DIR set landed under a macOS-only path.
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "MemorySafe" / "runtime-state"


def _start_dashboard() -> None:
    host = "127.0.0.1"
    port = int(os.environ.get("MEMORYSAFE_SETUP_PORT", "8765"))
    # os.environ.get(key, _default_state_dir()) evaluates the default argument before
    # the call runs, so it always ran _default_state_dir() -- including its win32
    # Path.home() fallback -- even when MEMORYSAFE_STATE_DIR was already set. `or`
    # short-circuits instead, so the fallback only runs when it is actually needed.
    state_dir = Path(
        os.environ.get("MEMORYSAFE_STATE_DIR") or _default_state_dir()
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
            close_fds=True,
            **_dashboard_spawn_options(),
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
