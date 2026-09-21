"""Who is serving the dashboard on this computer, written by the process that is.

The launcher replaces a dashboard it started from an older plugin, and only that one:
it compares the PID in this record with the PID the port itself reports through
/api/status. A live recorded PID and a matching version are not enough, because after
a reboot the PID can belong to an unrelated process while a launchd dashboard reports
the recorded version.

The record therefore has to name the process that answers /api/status. The launcher
cannot know it. On Windows `runtime/<key>/Scripts/python.exe` is a venv shim that
re-execs the real interpreter, so the PID `Popen` returns is the shim's and the port is
bound by its child. The two never matched, the comparison never passed, and an upgraded
install went on serving the old dashboard for ever -- three releases of it on the
machine where this was found, with nothing to say so but one line in the doctor.

So `setup_app` writes this once it is bound, where os.getpid() is by definition the
process that will answer. The launcher writes it too, before that happens, so a
dashboard that dies during startup still leaves a trace; the serving process overwrites
it with the truth a moment later.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .bootstrap_catalog import VERSION


NAME = "dashboard.json"


def write(state_dir: Path, pid: int) -> None:
    """Record who is serving. Atomic, so a reader never sees half a record."""

    target = state_dir / NAME
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps({"pid": int(pid), "version": VERSION, "plugin_root": str(Path(__file__).resolve().parents[2])}),
        encoding="utf-8",
    )
    os.replace(temporary, target)


def read(state_dir: Path) -> dict[str, Any] | None:
    """The record, or None if there is not a usable one."""

    try:
        record = json.loads((state_dir / NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or not isinstance(record.get("pid"), int):
        return None
    return record
