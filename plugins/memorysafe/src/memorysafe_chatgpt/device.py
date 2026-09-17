from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_state_dir() -> Path:
    configured = os.environ.get("MEMORYSAFE_STATE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "runtime-state"


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        # Windows ACLs often reject Unix mode bits; privacy still holds via user profile paths.
        pass


def _lock_exclusive(handle: TextIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock(handle: TextIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _chmod(path.parent, 0o700)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            dir=path.parent,
            prefix=f".{path.name}.",
            encoding="utf-8",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        _chmod(temporary, 0o600)
        temporary.replace(path)
        _chmod(path, 0o600)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_private_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def ensure_device_identity(state_dir: Path | None = None) -> dict[str, str]:
    directory = (state_dir or default_state_dir()).expanduser().resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    _chmod(directory, 0o700)
    identity_file = directory / "device.json"
    lock_file = directory / ".device.lock"
    with lock_file.open("a+", encoding="utf-8") as lock:
        _chmod(lock_file, 0o600)
        _lock_exclusive(lock)
        try:
            existing = read_private_json(identity_file)
            installation_id = str(existing.get("installation_id", ""))
            try:
                uuid.UUID(installation_id)
            except (ValueError, AttributeError):
                installation_id = str(uuid.uuid4())

            identity = {
                "schema_version": "1",
                "installation_id": installation_id,
                "created_at": str(existing.get("created_at") or utc_now()),
                "platform": platform.system().lower() or "unknown",
                "architecture": platform.machine().lower() or "unknown",
                "surface_mode": "desktop-hosted",
            }
            write_private_json(identity_file, identity)
            return identity
        finally:
            _unlock(lock)


def masked_device_id(identity: dict[str, str]) -> str:
    value = identity.get("installation_id", "")
    return f"MS-{value.split('-')[0].upper()}" if value else "MS-UNAVAILABLE"
