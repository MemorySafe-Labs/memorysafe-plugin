#!/usr/bin/env python3
"""Build and publish MemorySafe's private Python runtime safely.

Multiple assistants can start the same MCP server at once.  A venv built directly
at the live path lets those processes overwrite each other, and a version marker
can survive beside a missing package.  This helper serializes builders, validates a
staged venv, then publishes it with directory renames so launchers see either the
old complete runtime or the new complete runtime.

Two builders share that lock and publish step. The pip builder is the original, and it
is still what the Windows launcher and install_windows.py call. The uv builder serves
the macOS and Linux plugins: uv brings its own Python, so nobody installs one first,
and the runtime holds only the hash-pinned dependencies -- the MemorySafe code runs
from the plugin folder -- so it is keyed by requirements.lock rather than by version.

Runs on Python 3.8 with the standard library only: the plugin's pending-mode proxy runs
it on whatever python3 the machine already has.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path


LOCK_TIMEOUT_SECONDS = 20 * 60
STALE_LOCK_SECONDS = 30 * 60
POLL_SECONDS = 0.25

# The pending-mode proxy turns these into a reason the limited-mode server explains.
EXIT_DOWNLOAD_FAILED = 2
EXIT_UV_CHECKSUM = 3
EXIT_UNWRITABLE = 4
READY_MARKER = "ready"
_VERIFY_IMPORTS = "import mcp, tiktoken, cryptography"
_FETCH_TOKENIZER = "import tiktoken; tiktoken.get_encoding('o200k_base')"
# tiktoken's download has no timeout of its own, and the build holds the runtime lock.
TOKENIZER_FETCH_TIMEOUT_SECONDS = 120


class BuildFailure(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def runtime_python(runtime_dir: Path) -> Path:
    if os.name == "nt":
        return runtime_dir / "Scripts" / "python.exe"
    return runtime_dir / "bin" / "python"


def runtime_is_ready(runtime_dir: Path, version: str, *, verify_import: bool = False) -> bool:
    python = runtime_python(runtime_dir)
    if not python.is_file() or not (runtime_dir / f"version-{version}").is_file():
        return False
    if not verify_import:
        return True
    completed = subprocess.run(
        [str(python), "-c", "import memorysafe_chatgpt.server, mcp, tiktoken"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def _lock_age(lock_dir: Path) -> float:
    try:
        return max(0.0, time.time() - lock_dir.stat().st_mtime)
    except OSError:
        return 0.0


def _acquire_lock(lock_dir: Path, is_ready) -> bool:
    """Return True for the builder, False when another builder completed it."""

    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            lock_dir.mkdir()
            owner = {"pid": os.getpid(), "created_at": time.time()}
            (lock_dir / "owner.json").write_text(json.dumps(owner), encoding="utf-8")
            return True
        except FileExistsError:
            if is_ready():
                return False
            if _lock_age(lock_dir) > STALE_LOCK_SECONDS:
                try:
                    shutil.rmtree(lock_dir)
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Another MemorySafe runtime build did not finish within "
                    f"{LOCK_TIMEOUT_SECONDS // 60} minutes: {lock_dir}"
                )
            time.sleep(POLL_SECONDS)


def _run(command: list, environment: dict | None = None) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, check=True, env=environment)


def _build_staged_runtime(plugin_dir: Path, staging: Path, version: str) -> None:
    _run([sys.executable, "-m", "venv", str(staging)])
    python = runtime_python(staging)
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--upgrade",
            "pip",
            "setuptools",
            "wheel",
        ]
    )
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            str(plugin_dir),
        ]
    )
    _run([str(python), "-c", "import memorysafe_chatgpt.server, mcp, tiktoken"])
    (staging / f"version-{version}").write_text("ready\n", encoding="utf-8")


def _publish(staging: Path, runtime_dir: Path) -> None:
    backup = runtime_dir.with_name(f".{runtime_dir.name}-previous-{uuid.uuid4().hex}")
    moved_old = False
    try:
        if runtime_dir.exists():
            os.replace(runtime_dir, backup)
            moved_old = True
        os.replace(staging, runtime_dir)
    except BaseException:
        if moved_old and not runtime_dir.exists() and backup.exists():
            os.replace(backup, runtime_dir)
        raise
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)


def install_runtime(plugin_dir: Path, runtime_dir: Path, version: str) -> bool:
    """Ensure a complete runtime exists. Return True only when this call built it."""

    plugin_dir = plugin_dir.expanduser().resolve()
    runtime_dir = runtime_dir.expanduser().resolve()
    if not (plugin_dir / "pyproject.toml").is_file():
        raise FileNotFoundError(f"MemorySafe package is missing: {plugin_dir / 'pyproject.toml'}")
    runtime_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_dir = runtime_dir.with_name(f".{runtime_dir.name}.install.lock")
    builder = _acquire_lock(lock_dir, lambda: runtime_is_ready(runtime_dir, version))
    if not builder:
        print(f"MemorySafe runtime {version} was completed by another process.")
        return False

    staging: Path | None = None
    try:
        if runtime_is_ready(runtime_dir, version, verify_import=True):
            print(f"MemorySafe runtime {version} is already ready.")
            return False
        staging = Path(
            tempfile.mkdtemp(prefix=f".{runtime_dir.name}-build-", dir=str(runtime_dir.parent))
        )
        _build_staged_runtime(plugin_dir, staging, version)
        _publish(staging, runtime_dir)
        staging = None
        print(f"MemorySafe runtime {version} is ready.")
        return True
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(lock_dir, ignore_errors=True)


def read_runtime_env(plugin_dir: Path) -> dict:
    values = {}
    for line in (plugin_dir / "scripts" / "runtime.env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def uv_runtime_is_ready(runtime_dir: Path) -> bool:
    return runtime_python(runtime_dir).is_file() and (runtime_dir / READY_MARKER).is_file()


def _uv_environment(data_root: Path) -> dict:
    environment = dict(os.environ)
    # Everything uv downloads stays inside the MemorySafe folder: removing that folder
    # removes it, and the user's own uv installation is never written to.
    environment["UV_PYTHON_INSTALL_DIR"] = str(data_root / "python")
    environment["UV_CACHE_DIR"] = str(data_root / "cache" / "uv")
    environment["MEMORYSAFE_INSTALL_ROOT"] = str(data_root)
    return environment


def _ensure_uv(plugin_dir: Path, data_root: Path) -> str:
    # POSIX only for now. The Windows port adds ensure_uv.ps1 and chooses by os.name.
    completed = subprocess.run(
        ["/bin/sh", str(plugin_dir / "scripts" / "ensure_uv")],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        env=_uv_environment(data_root),
        universal_newlines=True,
        check=False,
    )
    if completed.returncode != 0:
        raise BuildFailure(completed.returncode, f"ensure_uv exited with {completed.returncode}")
    return completed.stdout.strip()


def _build_staged_uv_runtime(uv: str, plugin_dir: Path, staging: Path, python_version: str, data_root: Path) -> None:
    environment = _uv_environment(data_root)
    # --relocatable: the venv is built in a staging folder and renamed into place, and
    # its scripts must not keep pointing at a folder that no longer exists.
    _run(
        [uv, "venv", "--python", python_version, "--managed-python", "--no-project", "--relocatable", str(staging)],
        environment,
    )
    python = runtime_python(staging)
    _run(
        [uv, "pip", "install", "--python", str(python), "--require-hashes", "-r", str(plugin_dir / "requirements.lock")],
        environment,
    )
    _run([str(python), "-c", _VERIFY_IMPORTS], environment)
    _fetch_tokenizer(python, data_root)
    (staging / READY_MARKER).write_text("ready\n", encoding="utf-8")


def _fetch_tokenizer(python: Path, data_root: Path) -> None:
    """Download tiktoken's o200k_base encoding now, into the data root. Best effort.

    Left to first use, tiktoken fetched it from openaipublic.blob.core.windows.net into the
    system temp folder, and fetched it again whenever that folder was cleared, while the
    install guide says nothing leaves this computer after the first start. The launcher
    points TIKTOKEN_CACHE_DIR at the same folder, so this copy is the one every start uses.
    A failure does not fail the build: offline, token counts fall back to a local estimate.
    """

    environment = _uv_environment(data_root)
    environment["TIKTOKEN_CACHE_DIR"] = str(data_root / "cache" / "tiktoken")
    command = [str(python), "-c", _FETCH_TOKENIZER]
    print("+ " + " ".join(command), flush=True)
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            env=environment,
            timeout=TOKENIZER_FETCH_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print("The tokenizer download timed out; token counts use a local estimate until it succeeds.", flush=True)
        return
    except OSError as error:
        print("The tokenizer download could not start (%s); continuing without it." % error, flush=True)
        return
    if completed.returncode != 0:
        print("The tokenizer download failed; token counts use a local estimate until it succeeds.", flush=True)


def install_uv_runtime(plugin_dir: Path, data_root: Path) -> bool:
    """Ensure the runtime for this plugin's lock exists. True only when this call built it."""

    plugin_dir = plugin_dir.expanduser().resolve()
    data_root = data_root.expanduser().resolve()
    settings = read_runtime_env(plugin_dir)
    runtime_parent = data_root / "runtime"
    try:
        runtime_parent.mkdir(parents=True, exist_ok=True)
        probe = runtime_parent / f".write-probe-{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        raise BuildFailure(EXIT_UNWRITABLE, f"Cannot write to {runtime_parent}: {error}")

    runtime_dir = runtime_parent / settings["RUNTIME_KEY"]
    lock_dir = runtime_parent / f".{runtime_dir.name}.install.lock"
    if not _acquire_lock(lock_dir, lambda: uv_runtime_is_ready(runtime_dir)):
        print(f"MemorySafe runtime {runtime_dir.name} was completed by another process.")
        return False

    staging: Path | None = None
    try:
        if uv_runtime_is_ready(runtime_dir):
            print(f"MemorySafe runtime {runtime_dir.name} is already ready.")
            return False
        uv = _ensure_uv(plugin_dir, data_root)
        staging = Path(tempfile.mkdtemp(prefix=f".{runtime_dir.name}-build-", dir=str(runtime_parent)))
        _build_staged_uv_runtime(uv, plugin_dir, staging, settings["PYTHON_VERSION"], data_root)
        _publish(staging, runtime_dir)
        staging = None
        print(f"MemorySafe runtime {runtime_dir.name} is ready.")
        return True
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(lock_dir, ignore_errors=True)


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build MemorySafe's private Python runtime.")
    parser.add_argument("--builder", choices=("pip", "uv"), default="pip")
    parser.add_argument("--plugin-dir", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.builder == "uv":
            if args.data_root is None:
                parser.error("--builder uv needs --data-root")
            install_uv_runtime(args.plugin_dir, args.data_root)
        else:
            if args.runtime_dir is None or args.version is None:
                parser.error("--builder pip needs --runtime-dir and --version")
            install_runtime(args.plugin_dir, args.runtime_dir, args.version)
    except BuildFailure as failure:
        print(f"MemorySafe runtime install failed: {failure}", file=sys.stderr)
        return failure.code
    except Exception as error:
        print(f"MemorySafe runtime install failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
