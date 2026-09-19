"""What the first-start runtime build is doing, told the same way everywhere.

A plugin's first start builds a private runtime in the background, and for that minute or
several nothing a person could look at worked: the dashboard address refused connections,
and every call -- the doctor's included -- answered "try again in a minute". A tester
downloaded the same extension three times in three minutes.

The builder (plugin/scripts/install_runtime.py) records each step here, and the bootstrap
proxy reads it back for the progress page, its doctor answer and the reply to a call that
waited too long. One module owns the record so those surfaces cannot disagree about it.

Standard library only, and parses as Python 3.8: the proxy imports this on whatever
python3 the machine already has, before the runtime exists.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, Optional, Tuple


# In the order the builder runs them. A step whose output already exists finishes at once.
STEPS: Tuple[Tuple[str, str], ...] = (
    ("uv", "Downloading the setup tool"),
    ("python", "Downloading Python and creating the runtime"),
    ("packages", "Installing packages"),
    ("verify", "Checking the install"),
    ("tokenizer", "Downloading tokenizer data"),
)
_STEP_NAMES = tuple(name for name, _label in STEPS)

# install_runtime.py's exit codes, named as degraded_server.py explains them.
FAILURE_REASONS: Dict[int, str] = {
    2: "download_failed",
    3: "uv_checksum_mismatch",
    4: "install_root_unwritable",
}
GENERIC_FAILURE = "runtime_build_failed"
# install_runtime.READY_MARKER: a runtime is complete once this file exists inside it.
READY_MARKER = "ready"


def failure_reason(exit_code: int) -> str:
    return FAILURE_REASONS.get(exit_code, GENERIC_FAILURE)


def record_path(data_root: str, key: str) -> str:
    # Beside the build lock, and keyed like the runtime, so an update's rebuild never reads
    # the previous key's record. Outside the lock, because the lock is deleted when the
    # build ends and a failure has to outlast it.
    return os.path.join(data_root, "runtime", "." + key + ".progress.json")


def _windows_process_alive(pid: int) -> bool:
    # Kept separate so process_alive's Windows branch is testable off Windows, where
    # ctypes.windll does not exist. The same probe as claude_launcher._windows_process_alive.
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
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


def process_alive(pid: int) -> bool:
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


class Reporter:
    """The build-lock holder's record of where it is. Every write is best effort.

    Keyed only by RUNTIME_KEY, not by lock ownership or PID. install_runtime's dead-lock
    takeover (_lock_is_stale) can, in its own rare documented double-clear race, leave two
    builders both writing this file with plain os.replace -- last write wins, so the step
    counter can briefly move backward or show a stale state. Harmless: it never corrupts
    the runtime or fails the build, because provisioning.read() treats the runtime's own
    ready marker, not this record, as authoritative for "ready". Not worth a lock: the
    triggering race is already accepted as harmless for the build itself.
    """

    def __init__(self, data_root: str, key: str) -> None:
        self._path = record_path(data_root, key)
        self._record: Dict[str, Any] = {
            "runtime_key": key,
            "pid": os.getpid(),
            "state": "building",
            "step": None,
            "step_number": 0,
            "total_steps": len(STEPS),
            "started_at": time.time(),
            "updated_at": None,
            "failure": None,
        }

    def step(self, name: str) -> bool:
        return self._write(state="building", step=name, step_number=_STEP_NAMES.index(name) + 1)

    def ready(self) -> bool:
        return self._write(state="ready")

    def failed(self, exit_code: int) -> bool:
        return self._write(state="failed", failure=failure_reason(exit_code))

    def _write(self, **fields: Any) -> bool:
        self._record.update(fields)
        self._record["updated_at"] = time.time()
        temporary = "%s.%d.tmp" % (self._path, os.getpid())
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(self._record, handle)
            os.replace(temporary, self._path)
        except OSError as error:
            # The build's exit code decides success, never this record. The builder's
            # stderr is the install log, so the reason is still on file.
            sys.stderr.write("memorysafe: could not record setup progress: %s\n" % error)
            try:
                os.remove(temporary)
            except OSError:
                pass
            return False
        return True


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _load_record(data_root: str, key: str) -> Optional[Dict[str, Any]]:
    try:
        with open(record_path(data_root, key), "r", encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _apply(status: Dict[str, Any], record: Dict[str, Any]) -> None:
    step = record.get("step")
    if step in _STEP_NAMES:
        status["step"] = step
        status["step_number"] = _STEP_NAMES.index(step) + 1
    state = record.get("state")
    if state == "failed":
        failure = record.get("failure")
        status["status"] = "failed"
        status["failure"] = failure if isinstance(failure, str) and failure else GENERIC_FAILURE
    elif state == "building":
        pid = record.get("pid")
        alive = isinstance(pid, int) and not isinstance(pid, bool) and process_alive(pid)
        status["status"] = "building" if alive else "interrupted"
    # A record that says ready while the runtime's marker is missing stays "unknown".


def read(
    data_root: str,
    key: str,
    fallback_started_at: Optional[float] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Where the build of this runtime key is.

    status is "ready" when the runtime's ready marker exists, whatever the record says;
    otherwise "building", "interrupted" (the record says building but its builder is
    dead), "failed", or "unknown" (no record, or one that does not parse).
    elapsed_seconds counts from the record's start, or from fallback_started_at when the
    record has none, and is never negative.
    """

    now = time.time() if now is None else now
    status: Dict[str, Any] = {
        "status": "unknown",
        "step": None,
        "step_number": 0,
        "total_steps": len(STEPS),
        "failure": None,
        "elapsed_seconds": None,
    }
    started = fallback_started_at
    if data_root and key:
        if os.path.isfile(os.path.join(data_root, "runtime", key, READY_MARKER)):
            status["status"] = "ready"
        else:
            record = _load_record(data_root, key)
            if record is not None:
                recorded = _number(record.get("started_at"))
                if recorded is not None:
                    started = recorded
                _apply(status, record)
    if started is not None:
        status["elapsed_seconds"] = max(0.0, now - started)
    return status


def format_elapsed(seconds: float) -> str:
    whole = int(seconds)
    if whole < 60:
        return "%ds" % whole
    return "%dm %ds" % (whole // 60, whole % 60)


def describe(status: Dict[str, Any]) -> str:
    """One plain sentence for the page, the doctor and the reply to a call that waited."""

    state = status.get("status")
    if state == "ready":
        return "MemorySafe's one-time setup is finished."
    if state == "failed":
        return "MemorySafe could not finish its one-time setup."
    if state == "interrupted":
        return (
            "MemorySafe's one-time setup stopped part-way. Quit your assistant completely "
            "and reopen it to resume."
        )
    sentence = "MemorySafe is installed and finishing its one-time setup"
    number = status.get("step_number") or 0
    if status.get("step") in _STEP_NAMES and number:
        label = STEPS[number - 1][1]
        sentence += ": step %d of %d, %s" % (number, len(STEPS), label[0].lower() + label[1:])
    elapsed = status.get("elapsed_seconds")
    if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool):
        sentence += " (%s so far)" % format_elapsed(elapsed)
    return sentence + "."
