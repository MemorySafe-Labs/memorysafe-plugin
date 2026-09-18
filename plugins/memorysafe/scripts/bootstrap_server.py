#!/usr/bin/env python3
"""Answer MCP startup immediately while the full MemorySafe server imports.

The Windows host gives its shared chat pool a short connection deadline.  The MCP
SDK and storage stack are intentionally kept out of this process, so initialize and
discovery never wait on those imports.  Calls that need MemorySafe are queued and
proxied as soon as the real child server finishes its private handshake.

Pending mode (MEMORYSAFE_RUNTIME_PENDING=1) is how the macOS and Linux plugins start
before their private runtime exists. Building it downloads uv, a Python and the pinned
packages, which takes longer than Codex's ten-second start window or Claude Code's
thirty. So this proxy answers the handshake from the catalog, builds the runtime in its
own process session, and starts the real server only once the build succeeds -- or the
limited-mode server when it fails, so the assistant can still say why.

Runs on Python 3.8 with the standard library only: in pending mode it runs on whatever
python3 the machine already has.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from memorysafe_chatgpt.bootstrap_catalog import (
    PROTOCOL_VERSION,
    RESOURCES,
    SERVER_INSTRUCTIONS,
    TOOLS,
    VERSION,
)


_CHILD_INITIALIZE_ID = "memorysafe-bootstrap-initialize"
SCRIPT_DIR = Path(__file__).resolve().parent
PENDING_DEADLINE_SECONDS = 40.0
# subprocess exposes these only on Windows, so reading them off the module would
# raise AttributeError on Linux - in CI and in any test that patches os.name.
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000


def _detached_spawn_options():
    # Its own session: the build must finish even if the host gives up on this
    # process, so the next start finds a runtime instead of starting over.
    # start_new_session is POSIX-only - on Windows it is accepted and ignored, so
    # the guarantee above silently did not hold there until these flags were added.
    if os.name == "nt":
        return {"creationflags": _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


SETUP_IN_PROGRESS_MESSAGE = (
    "MemorySafe is finishing its one-time setup. Nothing was saved; try again in a minute."
)
# install_runtime.py exit codes, named as degraded_server.py explains them.
_BUILD_FAILURE_REASONS = {
    2: "download_failed",
    3: "uv_checksum_mismatch",
    4: "install_root_unwritable",
}
_EXIT_UNWRITABLE = 4


def _log(message: object) -> None:
    sys.stderr.write(f"memorysafe-bootstrap: {message}\n")
    sys.stderr.flush()


def _result(request_id: object, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _json_command(raw: str, name: str) -> List[str]:
    try:
        command = json.loads(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a JSON array") from error
    if not isinstance(command, list) or not command or not all(
        isinstance(item, str) and item for item in command
    ):
        raise RuntimeError(f"{name} must be a non-empty JSON string array")
    return command


def _read_runtime_env() -> Dict[str, str]:
    values: Dict[str, str] = {}
    for line in (SCRIPT_DIR / "runtime.env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def _runtime_child_command() -> List[str]:
    override = os.environ.get("MEMORYSAFE_BOOTSTRAP_CHILD_COMMAND")
    if override:
        return _json_command(override, "MEMORYSAFE_BOOTSTRAP_CHILD_COMMAND")
    # os.path, not pathlib: pathlib picks WindowsPath vs PosixPath from the real os.name
    # at construction time, and this process cannot instantiate a WindowsPath on POSIX --
    # which is exactly what breaks a test that patches os.name to exercise this branch.
    runtime_dir = os.path.join(
        os.environ["MEMORYSAFE_INSTALL_ROOT"], "runtime", _read_runtime_env()["RUNTIME_KEY"]
    )
    if os.name == "nt":
        interpreter = os.path.join(runtime_dir, "Scripts", "python.exe")
    else:
        interpreter = os.path.join(runtime_dir, "bin", "python")
    return [interpreter, "-m", "memorysafe_chatgpt.claude_launcher"]


def _setup_in_progress_reply(message: Dict[str, Any]) -> Dict[str, Any]:
    if message.get("method") == "tools/call":
        return _result(
            message["id"],
            {"content": [{"type": "text", "text": SETUP_IN_PROGRESS_MESSAGE}], "isError": True},
        )
    return {
        "jsonrpc": "2.0",
        "id": message["id"],
        "error": {"code": -32603, "message": SETUP_IN_PROGRESS_MESSAGE},
    }


class BootstrapProxy:
    def __init__(self, pending: bool = False) -> None:
        self._stdout_lock = threading.Lock()
        self._child_stdin_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._child: Optional[subprocess.Popen] = None
        self._child_ready = False
        self._child_active = False
        self._closing = False
        self._initialize_params: Optional[Dict[str, Any]] = None
        self._initialized_notification: Optional[Dict[str, Any]] = None
        # (monotonic time queued, message), so pending mode can answer what waited too long.
        self._pending: List[Tuple[float, Dict[str, Any]]] = []
        self._deadline = float(
            os.environ.get("MEMORYSAFE_PENDING_DEADLINE_SECONDS", PENDING_DEADLINE_SECONDS)
        )
        if pending:
            threading.Thread(target=self._build_then_start, name="memorysafe-build", daemon=True).start()
            threading.Thread(
                target=self._expire_waiting_requests, name="memorysafe-deadline", daemon=True
            ).start()
        else:
            self._start_child(self._child_command())

    @staticmethod
    def _child_command() -> List[str]:
        override = os.environ.get("MEMORYSAFE_BOOTSTRAP_CHILD_COMMAND")
        if override:
            return _json_command(override, "MEMORYSAFE_BOOTSTRAP_CHILD_COMMAND")
        script = os.environ.get("MEMORYSAFE_BOOTSTRAP_CHILD")
        if script:
            return [sys.executable, script]
        return [sys.executable, "-m", "memorysafe_chatgpt.claude_launcher"]

    @staticmethod
    def _build_command() -> List[str]:
        override = os.environ.get("MEMORYSAFE_RUNTIME_BUILD_COMMAND")
        if override:
            return _json_command(override, "MEMORYSAFE_RUNTIME_BUILD_COMMAND")
        return [
            sys.executable,
            str(SCRIPT_DIR / "install_runtime.py"),
            "--plugin-dir",
            str(SCRIPT_DIR.parent),
            "--data-root",
            os.environ["MEMORYSAFE_INSTALL_ROOT"],
        ]

    def _build_then_start(self) -> None:
        log_path: Optional[Path] = None
        try:
            state_dir = Path(
                os.environ.get("MEMORYSAFE_STATE_DIR")
                or Path(os.environ["MEMORYSAFE_INSTALL_ROOT"]) / "runtime-state"
            )
            log_path = state_dir / "logs" / "claude-install.log"
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log = log_path.open("ab")
            except OSError as error:
                _log(f"cannot write the install log: {error}")
                code = _EXIT_UNWRITABLE
            else:
                try:
                    build = subprocess.Popen(
                        self._build_command(),
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        close_fds=True,
                        **_detached_spawn_options(),
                    )
                    code = build.wait()
                except Exception as error:
                    _log(f"could not run the runtime build: {error}")
                    code = 1
                finally:
                    log.close()

            if code == 0:
                command = _runtime_child_command()
                extra: Dict[str, str] = {}
            else:
                _log(f"runtime build exited with {code}; starting limited mode")
                command = [sys.executable, str(SCRIPT_DIR / "degraded_server.py")]
                extra = {
                    "MEMORYSAFE_DEGRADED_REASON": _BUILD_FAILURE_REASONS.get(code, "runtime_build_failed"),
                    "MEMORYSAFE_INSTALL_LOG": str(log_path),
                }
            self._start_child(command, extra)
            return
        except Exception as error:
            # Working out the state dir, choosing the real runtime's command and starting
            # it can each raise on their own (a missing MEMORYSAFE_INSTALL_ROOT, a
            # runtime.env without RUNTIME_KEY, a venv whose python vanished) -- none of
            # that is the exit-code path above. Left uncaught, one of these killed this
            # thread silently: _child_failed never ran, and the deadline thread then
            # answered every call with "still finishing setup" forever. A successful
            # build deserves the same explanation as a failed one here.
            _log(f"could not finish starting MemorySafe after the build: {error}")

        try:
            self._start_child(
                [sys.executable, str(SCRIPT_DIR / "degraded_server.py")],
                {
                    "MEMORYSAFE_DEGRADED_REASON": "runtime_build_failed",
                    "MEMORYSAFE_INSTALL_LOG": str(log_path) if log_path is not None else "",
                },
            )
        except Exception as error:
            self._child_failed(f"could not start MemorySafe after setup: {error}")

    def _start_child(self, command: List[str], extra_env: Optional[Dict[str, str]] = None) -> None:
        environment = os.environ.copy()
        environment.pop("MEMORYSAFE_RUNTIME_PENDING", None)
        environment.update(extra_env or {})
        child = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=environment,
            **({"creationflags": _CREATE_NO_WINDOW} if os.name == "nt" else {}),
        )
        # subprocess.Popen has no newline= parameter -- text mode leaves both pipes at
        # the default newline=None, which on Windows rewrites every "\n" this proxy
        # writes to \r\n before it reaches the child. Reconfigured to newline="" so a
        # \r is never inserted into a newline-delimited JSON-RPC message either way.
        child.stdin.reconfigure(newline="")
        child.stdout.reconfigure(newline="")
        with self._state_lock:
            closing = self._closing
            self._child = child
            params = self._initialize_params
        if closing:
            child.terminate()
            return
        threading.Thread(target=self._read_child, args=(child,), name="memorysafe-child", daemon=True).start()
        if params is not None:
            self._initialize_child(params)

    def _write_host(self, message: Dict[str, Any]) -> None:
        encoded = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        with self._stdout_lock:
            sys.stdout.write(encoded + "\n")
            sys.stdout.flush()

    def _write_child(self, message: Dict[str, Any]) -> bool:
        encoded = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        child = self._child
        try:
            with self._child_stdin_lock:
                if child is None or child.stdin is None or child.stdin.closed:
                    return False
                child.stdin.write(encoded + "\n")
                child.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            return False

    def _initialize_child(self, params: object) -> None:
        child_params = params if isinstance(params, dict) else {}
        self._write_child(
            {
                "jsonrpc": "2.0",
                "id": _CHILD_INITIALIZE_ID,
                "method": "initialize",
                "params": child_params,
            }
        )

    def _mark_child_ready(self) -> None:
        with self._state_lock:
            if self._child_ready or self._closing:
                return
            self._child_ready = True
        self._activate_child()

    def _activate_child(self) -> None:
        """Send initialized exactly once, then release queued real requests."""

        with self._state_lock:
            if (
                self._child_active
                or not self._child_ready
                or self._initialized_notification is None
                or self._closing
            ):
                return
            self._child_active = True
            initialized = self._initialized_notification
            pending = [message for _, message in self._pending]
            self._pending = []
        self._write_child(initialized)
        for message in pending:
            if not self._write_child(message):
                self._child_failed("the full server closed while startup requests were queued")
                break

    def _expire_waiting_requests(self) -> None:
        while True:
            time.sleep(0.1)
            now = time.monotonic()
            with self._state_lock:
                if self._child_active or self._closing:
                    return
                expired = [
                    message
                    for queued, message in self._pending
                    if message.get("id") is not None and now - queued >= self._deadline
                ]
                if not expired:
                    continue
                # Removed, not merely answered: a remember that timed out must never
                # quietly run once setup finishes.
                self._pending = [
                    (queued, message)
                    for queued, message in self._pending
                    if not (message.get("id") is not None and now - queued >= self._deadline)
                ]
            for message in expired:
                self._write_host(_setup_in_progress_reply(message))

    def _child_failed(self, reason: str) -> None:
        with self._state_lock:
            if self._closing:
                return
            self._closing = True
            pending = self._pending
            self._pending = []
        _log(reason)
        for _, message in pending:
            request_id = message.get("id")
            if request_id is not None:
                self._write_host(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32603,
                            "message": "MemorySafe's full server could not finish starting.",
                        },
                    }
                )

    def _read_child(self, child: subprocess.Popen) -> None:
        assert child.stdout is not None
        for raw in child.stdout:
            try:
                message = json.loads(raw)
            except ValueError:
                _log("ignored non-JSON output from the full server")
                continue
            if message.get("id") == _CHILD_INITIALIZE_ID:
                if "error" in message:
                    self._child_failed("the full server rejected its private initialize request")
                    return
                self._mark_child_ready()
                continue
            self._write_host(message)
        if not self._closing:
            self._child_failed(f"the full server exited with status {child.poll()}")

    def handle(self, message: Dict[str, Any]) -> None:
        method = message.get("method")
        request_id = message.get("id")

        if method == "initialize":
            raw = message.get("params", {})
            params = raw if isinstance(raw, dict) else {}
            with self._state_lock:
                self._initialize_params = params
                child = self._child
            # Whichever of this and _start_child runs second sees both the params and the
            # child, so the private initialize is sent exactly once.
            if child is not None:
                self._initialize_child(params)
            self._write_host(
                _result(
                    request_id,
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {}, "resources": {}},
                        "serverInfo": {"name": "memorysafe", "title": "MemorySafe", "version": VERSION},
                        "instructions": SERVER_INSTRUCTIONS,
                    },
                )
            )
            return
        if method == "tools/list":
            self._write_host(_result(request_id, {"tools": TOOLS}))
            return
        if method == "resources/list":
            self._write_host(_result(request_id, {"resources": RESOURCES}))
            return
        if method == "resources/templates/list":
            self._write_host(_result(request_id, {"resourceTemplates": []}))
            return
        if method == "prompts/list":
            self._write_host(_result(request_id, {"prompts": []}))
            return
        if method == "ping":
            self._write_host(_result(request_id, {}))
            return
        if method == "notifications/initialized":
            with self._state_lock:
                if self._initialized_notification is None:
                    self._initialized_notification = message
            self._activate_child()
            return

        with self._state_lock:
            active = self._child_active
            closing = self._closing
            if not active and not closing:
                self._pending.append((time.monotonic(), message))
                return
        if active:
            if not self._write_child(message) and request_id is not None:
                self._write_host(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32603, "message": "MemorySafe's full server stopped."},
                    }
                )
        elif request_id is not None:
            self._write_host(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32603, "message": "MemorySafe's full server did not start."},
                }
            )

    def close(self) -> None:
        with self._state_lock:
            self._closing = True
            child = self._child
        if child is None:
            return
        if child.stdin is not None and not child.stdin.closed:
            try:
                child.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()


def main() -> int:
    # Python opens stdout with newline=None on Windows, which rewrites every "\n" this
    # process writes to "\r\n" -- and stdout is the JSON-RPC channel every reply, from
    # every thread BootstrapProxy can start, travels over. Reconfigured first, before
    # anything else in this function runs, so nothing can write ahead of it.
    sys.stdout.reconfigure(newline="")
    pending = os.environ.get("MEMORYSAFE_RUNTIME_PENDING") == "1"
    try:
        proxy = BootstrapProxy(pending=pending)
    except Exception as error:
        _log(f"could not start the full server: {error}")
        return 1
    try:
        for raw in sys.stdin:
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            if isinstance(message, dict):
                proxy.handle(message)
    finally:
        proxy.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
