from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .bootstrap_catalog import VERSION
# The window opener lives with the dashboard tool that normally calls it; a first start
# wants the same window, not a second way of making one.
from .server import _open_dashboard_window, main as run_mcp_server


PRODUCT = "MemorySafe Beta"
_RECORD_NAME = "dashboard.json"
_OPENED_NAME = "dashboard-opened.json"
# How long a first start waits for the dashboard it just spawned to answer before
# giving up on showing it. Off the MCP server's path, in a thread of its own.
_FIRST_OPEN_TIMEOUT_SECONDS = 20.0


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


def _is_a_first_start(state_dir: Path) -> bool:
    """Has this computer ever had a MemorySafe dashboard started for it?

    The dashboard is where an install proves itself and where the other assistants get
    connected, so someone who never opens it never sees either. Opening it once removes
    the "now type this address" step from every guide. Once, though: a dashboard that
    reappears on every start is spam.

    Two records have to be absent. `dashboard-opened.json` is this feature's own, written
    before the window is attempted so a failure to open is not retried forever.
    `dashboard.json` is older than this feature and is written every time a launcher
    starts a dashboard, which is what keeps an existing install from getting a window the
    first time it updates to a version that has this: it has started one before.
    """

    if (state_dir / _OPENED_NAME).exists():
        return False
    return _read_dashboard_record(state_dir) is None


def _mark_dashboard_opened(state_dir: Path) -> None:
    target = state_dir / _OPENED_NAME
    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "version": VERSION}),
            encoding="utf-8",
        )
        os.replace(temporary, target)
    except OSError:
        # Not being able to record it is not a reason to skip the window; the worst
        # case is one more window on the next start.
        pass


def _open_dashboard_when_ready(host: str, port: int) -> None:
    """Wait for the dashboard just spawned to answer, then show it.

    A first start has a runtime to build, and the window must not appear before there is
    a page behind it. Nothing here may raise: this runs while the MCP server is serving.
    """

    deadline = time.monotonic() + _FIRST_OPEN_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _dashboard_status(host, port) is not None:
            try:
                _open_dashboard_window(f"http://{host}:{port}/dashboard")
            except Exception:
                pass
            return
        time.sleep(0.25)


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


def _open_the_window_in_the_background(host: str, port: int) -> None:
    """Start the window thread. A seam of its own, so tests need not patch threading.

    Patching threading.Thread reaches every thread in the process, including the one
    subprocess.run uses to read a child's output, so doing that in one test module
    broke six unrelated tests in another. Patching this function reaches only this.

    Daemon, because waiting for a browser must never hold up the MCP server this
    launcher is about to run.
    """

    threading.Thread(target=_open_dashboard_when_ready, args=(host, port), daemon=True).start()

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
    # Read before a record is written for the dashboard started below, which would
    # otherwise make every start look like one that had come before.
    first_start = _is_a_first_start(state_dir)
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
    if first_start:
        # Marked before the attempt, not after it: whatever happens next, this computer
        # has had its one window.
        _mark_dashboard_opened(state_dir)
        # In a thread, because waiting for the page would hold up the MCP server this
        # launcher is about to run, and the host is timing that.
        _open_the_window_in_the_background(host, port)


def main() -> None:
    _start_dashboard()
    run_mcp_server()


if __name__ == "__main__":
    main()
