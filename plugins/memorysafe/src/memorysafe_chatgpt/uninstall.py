"""Everything MemorySafe put on this computer, and how to take it back off.

There was no uninstaller. Removing MemorySafe from a Windows machine by hand on 19 Sep
meant finding seven separate things: the Claude Desktop extension and its settings file,
the Claude Code plugin and its marketplace, the Codex plugin and its marketplace, the data
root with the private runtime, two plugin caches, the MCP logs, and any hand-written
registration left over from 0.3.x. Nothing in any assistant knows the data root exists, so
"remove the plugin" leaves hundreds of megabytes behind. A product that cannot be removed
is a product people are stuck with.

This is the same inventory `connect` builds, read backwards:

- A plugin leaves through its own host's installer (`claude plugin uninstall`,
  `codex plugin remove`), never by editing that host's configuration.
- Claude Desktop is reported with its one manual step and never touched from here, because
  it asks the user to confirm what its extensions do.
- Hand-written registrations are removed with `migrate`'s functions, each backed up first.
- Memories are never deleted without `--purge`, and a `--purge` copies the database out
  first and says where it went. Nothing here is guesswork about what a file is for: every
  path removed is one MemorySafe itself created.
"""

from __future__ import annotations

import errno
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping

from . import agents, legacy_autostart
from .migrate import (
    PLUGIN_ID,
    claude_config,
    claude_project_registrations,
    claude_registration_present,
    codex_config,
    codex_registration_present,
    project_mcp_files,
    remove_claude_project_registrations,
    remove_claude_registration,
    remove_codex_registration,
    remove_project_mcp_file_entry,
)

# Where a purge puts the memories before deleting them. In the home directory, not in the
# data root that is about to go, and not on the Desktop, which may be synced to a cloud.
BACKUP_PREFIX = "memorysafe-memories-"


def _size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for directory, _subdirectories, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(directory, name)).st_size
            except OSError:
                pass
    return total


def _item(
    kind: str,
    label: str,
    detail: str,
    *,
    paths: list[Path] | None = None,
    commands: list[list[str]] | None = None,
    manual: str | None = None,
    purge_only: bool = False,
    registration: str | None = None,
) -> dict[str, Any]:
    paths = paths or []
    return {
        "kind": kind,
        "label": label,
        "detail": detail,
        # Which hand-written registration this is, for apply: never parsed back out of
        # the text above, which is written for a person to read.
        "registration": registration,
        "paths": [str(path) for path in paths],
        "bytes": sum(_size(path) for path in paths),
        "commands": commands or [],
        # Set when this computer's owner has to do it themselves, in their assistant.
        "manual": manual,
        # Memories are only ever removed by an explicit --purge.
        "purge_only": purge_only,
    }


def _plugin_items(home: Path, env: Mapping[str, str], platform: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    found = {entry["id"]: entry for entry in agents.inventory(home, env, platform)}

    desktop = found["claude_desktop"]
    if desktop["connected"]:
        items.append(
            _item(
                "extension",
                "Claude Desktop",
                "the MemorySafe extension",
                manual="In Claude Desktop: Settings > Extensions > MemorySafe > uninstall. Claude Desktop "
                "asks you to confirm what its extensions do, so this one step is yours.",
            )
        )

    for agent_id, label, cli_name, remove, marketplace_known in (
        ("claude_code", "Claude Code", "claude", ["plugin", "uninstall", PLUGIN_ID], agents._claude_code_marketplace_known),
        ("codex", "Codex", "codex", ["plugin", "remove", PLUGIN_ID], agents._codex_marketplace_known),
    ):
        entry = found[agent_id]
        if entry["how"] != "plugin":
            continue
        cli = entry["command"] or agents.find_cli(cli_name, home, env, platform)
        if not cli:
            items.append(
                _item(
                    "plugin",
                    label,
                    "the MemorySafe plugin",
                    manual=f"{label}'s own command was not found, so its plugin cannot be removed from here. "
                    f"In a terminal: {cli_name} {' '.join(remove)}",
                )
            )
            continue
        commands = [[cli, *remove]]
        if marketplace_known(home):
            commands.append([cli, "plugin", "marketplace", "remove", agents.MARKETPLACE_NAME])
        items.append(_item("plugin", label, "the MemorySafe plugin and its marketplace", commands=commands))
    return items


def _registration_items(home: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if claude_registration_present(claude_config(home)):
        items.append(
            _item("registration", "Claude Code", f"hand-written entry in {claude_config(home)}", registration="claude_user")
        )
    projects = claude_project_registrations(claude_config(home))
    if projects:
        items.append(
            _item(
                "registration",
                "Claude Code",
                f"hand-written entry in {len(projects)} project(s) in {claude_config(home)}",
                registration="claude_projects",
            )
        )
    for path in project_mcp_files(home):
        items.append(_item("registration", "Claude Code", f"hand-written entry in {path}", registration=f"file:{path}"))
    if codex_registration_present(codex_config(home)):
        items.append(
            _item("registration", "Codex", f"hand-written entry in {codex_config(home)}", registration="codex")
        )
    return items


def _file_items(home: Path, env: Mapping[str, str], platform: str, data_root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    runtime = [data_root / name for name in ("runtime", "python", "tools", "cache", "bin", "claude-runtime")]
    present = [path for path in runtime if path.exists()]
    if present:
        items.append(_item("files", "Private runtime", f"Python, uv and packages in {data_root}", paths=present))
    state = data_root / "runtime-state"
    if state.exists():
        items.append(_item("files", "Local state", f"device id, logs, support bundles in {state}", paths=[state]))

    caches = [home / ".claude" / "plugins" / "cache" / agents.MARKETPLACE_NAME,
              home / ".codex" / "plugins" / "cache" / agents.MARKETPLACE_NAME]
    logs: list[Path] = []
    cache_root = (
        Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local") / "claude-cli-nodejs"
        if platform == "win32"
        else home / ".cache" / "claude-cli-nodejs"
    )
    if cache_root.is_dir():
        logs = sorted(cache_root.glob("*/mcp-logs-plugin-memorysafe-memorysafe"))
    leftovers = [path for path in [*caches, *logs] if path.exists()]
    if leftovers:
        items.append(_item("files", "Host caches", "plugin copies and MCP logs kept by the assistants", paths=leftovers))

    launch_agents = home / "Library" / "LaunchAgents"
    plists = sorted(launch_agents.glob("ca.memorysafe.*.plist")) if launch_agents.is_dir() else []
    if plists:
        items.append(_item("files", "Background services", "launchd agents from the ChatGPT connector", paths=plists))

    if platform == "win32":
        roaming = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
        start_menu = roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        # The 0.3.x installer wrote "MemorySafe Dashboard Service.cmd"; looking only for .lnk missed it.
        legacy = [
            *(path for path in (start_menu / "MemorySafe",) if path.exists()),
            *legacy_autostart.find(home, env, platform),
        ]
        if legacy:
            items.append(_item("files", "Start Menu", "shortcuts from a 0.3.x install", paths=legacy))

    data = data_root / "data"
    if data.exists():
        items.append(
            _item("memories", "Your memories", f"the store and its snapshots in {data}", paths=[data], purge_only=True)
        )
    return items


def inventory(
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    data_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Everything of MemorySafe's on this computer, in the order it should be removed."""

    home = home or Path.home()
    env = os.environ if env is None else env
    platform = platform or agents.sys.platform
    data_root = data_root or default_data_root(home, env, platform)
    return [
        *_plugin_items(home, env, platform),
        *_registration_items(home),
        *_file_items(home, env, platform, data_root),
    ]


def default_data_root(home: Path, env: Mapping[str, str], platform: str) -> Path:
    """The same root every launcher resolves. Mirrors cli._resolve_database."""

    configured = env.get("MEMORYSAFE_INSTALL_ROOT")
    if configured:
        return Path(configured)
    if platform == "win32":
        return Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local") / "MemorySafe"
    if platform == "darwin":
        return home / "Library" / "Application Support" / "MemorySafe"
    xdg = env.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else home / ".local" / "share") / "MemorySafe"


def back_up_memories(home: Path, data_root: Path) -> Path | None:
    """Copy the store out before a purge deletes it. Returns where it went.

    Never a copy of the one file. The store keeps its newest saves in a write-ahead log
    beside it for as long as any assistant has it open, so the file alone could be missing
    them, and the purge then deleted the log. And after an erase whose rewrite was refused,
    the file's freed pages may still hold the erased text. SQLite writes the copy instead
    (VACUUM INTO): every row that exists now, nothing that was deleted. The copy is checked
    before this returns; if it cannot be made or does not check out, this raises and the
    caller leaves the store where it is.
    """

    database = data_root / "data" / "memorysafe.sqlite3"
    if not database.is_file():
        return None
    from datetime import datetime

    target = home / f"{BACKUP_PREFIX}{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
    if not _readable(database):
        # Not a store SQLite can read: damaged, or not ours. Its bytes are all there is to
        # keep, so they are kept as they are, the log and its index with them. Asked
        # read-only, before anything opens the file for writing: a writer may clear away a
        # log it cannot make sense of.
        _raw_copy(database, target)
        return target
    pending = _erase_unfinished(database)
    try:
        _sqlite_copy(database, target, without_freed_pages=True)
    except sqlite3.Error as error:
        _discard(target)
        if pending:
            raise OSError(
                "an erase is still waiting for the store's file to be rewritten, and a copy without "
                f"the erased text could not be made ({type(error).__name__}); run "
                "`memorysafe erase --finish` and try again"
            ) from error
        try:
            # A SQLite too old for VACUUM INTO. Its backup takes the log's contents too.
            _sqlite_copy(database, target, without_freed_pages=False)
        except sqlite3.Error as second:
            _discard(target)
            raise OSError(f"a complete copy of the store could not be made ({type(second).__name__})") from second
    return target


def _erase_unfinished(database: Path) -> bool:
    """Whether a permanent erase still waits for this store's file to be rewritten. A file
    that cannot be read as a store carries no such mark."""

    from .backends.sqlite import ERASE_UNFINISHED

    try:
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=2)
        try:
            row = connection.execute("SELECT 1 FROM settings WHERE key = ?", (ERASE_UNFINISHED,)).fetchone()
        finally:
            connection.close()
    except (sqlite3.Error, OSError):
        return False
    return row is not None


def _rows(connection: sqlite3.Connection) -> int:
    return int(connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0])


def _readable(database: Path) -> bool:
    try:
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=2)
        try:
            _rows(connection)
        finally:
            connection.close()
    except (sqlite3.Error, OSError):
        return False
    return True


def _sqlite_copy(database: Path, target: Path, *, without_freed_pages: bool) -> None:
    """Have SQLite write `target` from the store, then check it: sound, and holding as many
    memories as the store did. Raises sqlite3.Error when either step fails."""

    from .backends.sqlite import ERASE_UNFINISHED

    source = sqlite3.connect(database, timeout=10)
    try:
        before = _rows(source)
        if without_freed_pages:
            source.execute("VACUUM INTO ?", (str(target),))
        else:
            destination = sqlite3.connect(target)
            try:
                source.backup(destination)
            finally:
                destination.close()
        after = _rows(source)
    finally:
        source.close()
    copy = sqlite3.connect(target)
    try:
        # The copy has nothing left to rewrite.
        copy.execute("DELETE FROM settings WHERE key = ?", (ERASE_UNFINISHED,))
        copy.commit()
        sound = str(copy.execute("PRAGMA quick_check").fetchone()[0])
        held = _rows(copy)
    finally:
        copy.close()
    # An assistant may save while the copy is written; the copy holds the store as it was
    # at one moment in between.
    if sound != "ok" or not min(before, after) <= held <= max(before, after):
        raise sqlite3.DatabaseError("the copy does not hold what the store holds")


def _raw_copy(database: Path, target: Path) -> None:
    shutil.copy2(database, target)
    for suffix in ("-wal", "-shm"):
        sidecar = database.with_name(database.name + suffix)
        if sidecar.is_file():
            shutil.copy2(sidecar, target.with_name(target.name + suffix))


def _discard(target: Path) -> None:
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            target.with_name(target.name + suffix).unlink()
        except OSError:
            pass


# How hard to try before calling a path stuck, and how long to wait between tries.
#
# Windows refuses a delete for a moment after a file has been touched -- a process
# closing its handles, or the virus scanner reading what was just written -- and the
# same removal succeeds a moment later. Measured on this machine on 20 September, with
# every MemorySafe process already stopped: three `--apply` runs in a row each freed
# more than 100 MB and then stopped on a different file, and a plain retry loop cleared
# what was left in a few passes. Nothing was read-only and nothing held a handle.
_REMOVE_ATTEMPTS = 6
_REMOVE_BACKOFF_SECONDS = 0.4


def _is_busy(error: OSError) -> bool:
    """Is this Windows saying "not right now" rather than "no"?

    ERROR_ACCESS_DENIED (5) and ERROR_SHARING_VIOLATION (32) are what a locked file
    raises. Only these are worth retrying: a path that is genuinely not ours stays not
    ours, and retrying it six times only makes the uninstall slower.
    """

    if getattr(error, "winerror", None) in (5, 32):
        return True
    return error.errno in (errno.EACCES, errno.EBUSY, errno.EPERM)


def remove_path(target: Path) -> None:
    """Delete a file or a tree, waiting out a lock that is about to clear.

    Raises the last error if it never clears, so the caller still reports it. An error
    that is not a lock is raised at once.
    """

    for attempt in range(_REMOVE_ATTEMPTS):
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
            return
        except OSError as error:
            if not _is_busy(error) or attempt == _REMOVE_ATTEMPTS - 1:
                raise
            time.sleep(_REMOVE_BACKOFF_SECONDS * (attempt + 1))


def apply(
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    data_root: Path | None = None,
    purge: bool = False,
    runner: agents.Runner | None = None,
) -> dict[str, Any]:
    """Remove what this computer's owner can have removed from here. Memories only on purge."""

    runner = runner or subprocess.run
    home = home or Path.home()
    env = os.environ if env is None else env
    platform = platform or agents.sys.platform
    data_root = data_root or default_data_root(home, env, platform)
    done: list[str] = []
    failed: list[str] = []
    manual: list[str] = []
    backup: Path | None = None
    # Set when something could not be removed because it was in use. The remedy is
    # the user's to apply -- MemorySafe cannot close the assistant running it.
    busy = False

    for item in inventory(home, env, platform, data_root):
        if item["manual"]:
            manual.append(item["manual"])
            continue
        if item["purge_only"] and not purge:
            continue
        if item["kind"] == "memories" and purge:
            try:
                backup = back_up_memories(home, data_root)
            except OSError as error:
                failed.append(f"{item['label']}: could not be backed up ({error}); left in place")
                continue
        for argv in item["commands"]:
            try:
                result = runner(
                    agents._process_command(argv, platform, env),
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=agents.CONNECT_TIMEOUT_SECONDS,
                    env=agents._installer_env(argv[0], env, platform),
                )
                if result.returncode != 0:
                    # A marketplace that is already gone is not a failure worth reporting.
                    failed.append(f"{item['label']}: {agents.command_line(argv, env, platform)}")
            except (OSError, subprocess.SubprocessError) as error:
                failed.append(f"{item['label']}: {error}")
        for path in item["paths"]:
            try:
                remove_path(Path(path))
            except OSError as error:
                failed.append(f"{path}: {error}")
                # What the person has to do about it differs, so say which this was.
                if _is_busy(error):
                    busy = True
        if item["registration"]:
            _remove_registration(home, item["registration"])
        if not item["commands"] and not item["paths"] and item["kind"] != "registration":
            continue
        done.append(f"{item['label']}: {item['detail']}")

    # An empty data root left behind looks like a half-finished uninstall.
    for directory in (data_root, home / ".claude" / "plugins" / "cache", home / ".codex" / "plugins" / "cache"):
        try:
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        except OSError:
            pass
    return {
        "removed": done,
        "failed": failed,
        "manual": manual,
        "memories_backup": str(backup) if backup else None,
        "still_in_use": busy,
    }


def _remove_registration(home: Path, registration: str) -> None:
    """Take out the hand-written entry this item names, each file backed up first."""

    if registration == "claude_user":
        remove_claude_registration(claude_config(home))
    elif registration == "claude_projects":
        remove_claude_project_registrations(claude_config(home))
    elif registration == "codex":
        remove_codex_registration(codex_config(home))
    elif registration.startswith("file:"):
        remove_project_mcp_file_entry(Path(registration[len("file:"):]))
