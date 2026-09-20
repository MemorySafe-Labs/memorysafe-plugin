"""Find, and on request remove, the hand-written MemorySafe registrations the plugins replace.

Before the plugins, setup_assistants.py wrote a `memorysafe` server into ~/.claude.json
and ~/.codex/config.toml. With the plugin installed as well, every MemorySafe tool is
listed twice and every conversation pays for both copies. This never runs on its own:
~/.claude.json holds the user's entire Claude Code configuration, so the change is shown
first and made only with --apply, after a backup.

A manual entry is removed only when that same assistant has the MemorySafe plugin. The
plugin runtime in the data root is shared by every host, so finding it proves nothing
about the host whose manual entry was found: with only the Claude Code plugin installed,
Codex's manual entry is Codex's only registration.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:  # Python 3.10, the floor of the Windows pip runtime.
    tomllib = None  # type: ignore[assignment]


SERVER_NAME = "memorysafe"
# How both Claude Code and Codex name the marketplace plugin: name@marketplace.
PLUGIN_ID = "memorysafe@memorysafe"
# A TOML key: a bare key, a basic (double-quoted) string, or a literal (single-quoted) one.
_KEY = r"""(?:[A-Za-z0-9_-]+|"(?:[^"\\]|\\.)*"|'[^']*')"""
_DOTTED_KEY = rf"{_KEY}(?:\s*\.\s*{_KEY})*"
# Anything that starts with `[` and ends with `]` is not necessarily a table header: the
# tail of a multi-line array (`[1, 2]`) and a `[not a header]`-shaped line inside a
# multi-line string both have that shape without being one. Requiring the bracketed
# content to be a valid (possibly dotted) key sequence rules both out. Without this, a
# false header inside our own table closed the removal range early and left orphaned
# TOML behind (task 15 review, round 1).
_TABLE_HEADER = re.compile(rf"^\s*\[\[?\s*(?P<name>{_DOTTED_KEY})\s*\]\]?\s*(?:#.*)?$")


def claude_config(home: Path) -> Path:
    return home / ".claude.json"


def codex_config(home: Path) -> Path:
    return home / ".codex" / "config.toml"


def _is_ours(table: str) -> bool:
    return table == f"mcp_servers.{SERVER_NAME}" or table.startswith(f"mcp_servers.{SERVER_NAME}.")


def _normalize_table_name(name: str) -> str:
    # `[ mcp_servers . memorysafe ]` is valid TOML and must still compare equal to
    # "mcp_servers.memorysafe".
    return re.sub(r"\s*\.\s*", ".", name)


def _trim_end(lines: list[str], start: int, end: int) -> int:
    # Blank lines and comments just above the next table belong to that table.
    while end > start + 1 and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
        end -= 1
    return end


def _codex_ranges(lines: list[str]) -> list[tuple[int, int]]:
    """Line ranges of [mcp_servers.memorysafe] and its subtables.

    Parsing and re-serialising the TOML would lose the user's comments and ordering, so
    the tables are cut out as text and everything else is kept byte for byte.
    """

    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for index, line in enumerate(lines):
        match = _TABLE_HEADER.match(line)
        if match is None:
            continue
        ours = _is_ours(_normalize_table_name(match.group("name")))
        if start is not None and not ours:
            ranges.append((start, _trim_end(lines, start, index)))
            start = None
        elif start is None and ours:
            start = index
    if start is not None:
        ranges.append((start, _trim_end(lines, start, len(lines))))
    return ranges


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def claude_registration_present(path: Path) -> bool:
    config = _read_json(path)
    servers = config.get("mcpServers") if isinstance(config, dict) else None
    return isinstance(servers, dict) and SERVER_NAME in servers


def claude_project_registrations(path: Path) -> list[str]:
    """Projects in ~/.claude.json carrying their own memorysafe mcpServers entry.

    Claude Code registers MCP servers per project as well as for the user, and migrate
    only ever looked at the user-scope entry. A project entry survives every removal and
    keeps listing MemorySafe's tools a second time in that project, which is the same
    duplicate migrate exists to remove.
    """

    config = _read_json(path)
    projects = config.get("projects") if isinstance(config, dict) else None
    if not isinstance(projects, dict):
        return []
    return sorted(
        name
        for name, project in projects.items()
        if isinstance(project, dict)
        and isinstance(project.get("mcpServers"), dict)
        and SERVER_NAME in project["mcpServers"]
    )


def project_mcp_files(home: Path) -> list[Path]:
    """`.mcp.json` files registering MemorySafe, in the projects Claude Code knows about.

    Only those projects: scanning the disk for .mcp.json would read folders the user
    never pointed an assistant at.
    """

    config = _read_json(claude_config(home))
    projects = config.get("projects") if isinstance(config, dict) else None
    found = []
    for name in sorted(projects) if isinstance(projects, dict) else []:
        candidate = Path(name) / ".mcp.json"
        entry = _read_json(candidate)
        servers = entry.get("mcpServers") if isinstance(entry, dict) else None
        if isinstance(servers, dict) and SERVER_NAME in servers:
            found.append(candidate)
    return found


def remove_claude_project_registrations(path: Path) -> list[str]:
    """Drop memorysafe from every project's mcpServers. Returns the projects changed."""

    config = _read_json(path)
    projects = config.get("projects") if isinstance(config, dict) else None
    if not isinstance(projects, dict):
        return []
    changed = []
    for name, project in projects.items():
        servers = project.get("mcpServers") if isinstance(project, dict) else None
        if isinstance(servers, dict) and servers.pop(SERVER_NAME, None) is not None:
            changed.append(name)
    if not changed:
        return []
    _backup(path)
    _replace_text(path, json.dumps(config, indent=2))
    return sorted(changed)


def remove_project_mcp_file_entry(path: Path) -> bool:
    """Drop memorysafe from one project's .mcp.json, leaving that project's other servers."""

    config = _read_json(path)
    servers = config.get("mcpServers") if isinstance(config, dict) else None
    if not isinstance(servers, dict) or servers.pop(SERVER_NAME, None) is None:
        return False
    _backup(path)
    _replace_text(path, json.dumps(config, indent=2))
    return True


def codex_registration_present(path: Path) -> bool:
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, ValueError):
        return False
    return bool(_codex_ranges(lines))


def claude_code_plugin_installed(home: Path) -> bool:
    """True when Claude Code lists the MemorySafe plugin and settings do not disable it.

    Anything that cannot be read counts as not installed, except a settings file that
    does not exist: the answer decides whether an entry may be removed, and keeping a
    duplicate costs tokens while removing the only registration costs the store.
    """

    try:
        installed = json.loads((home / ".claude" / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    plugins = installed.get("plugins") if isinstance(installed, dict) else None
    if not isinstance(plugins, dict) or PLUGIN_ID not in plugins:
        return False
    try:
        settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return True
    except (OSError, ValueError):
        return False
    enabled = settings.get("enabledPlugins") if isinstance(settings, dict) else None
    # A plugin with no enabledPlugins entry is enabled; only an explicit false turns it off.
    return not (isinstance(enabled, dict) and enabled.get(PLUGIN_ID) is False)


def codex_plugin_installed(home: Path) -> bool:
    """True when config.toml has a [plugins."memorysafe@memorysafe"] table not set to enabled = false."""

    if tomllib is None:
        return False
    try:
        with codex_config(home).open("rb") as handle:
            config = tomllib.load(handle)
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return False
    plugins = config.get("plugins")
    entry = plugins.get(PLUGIN_ID) if isinstance(plugins, dict) else None
    return isinstance(entry, dict) and entry.get("enabled", True) is not False


def _backup(path: Path) -> None:
    shutil.copy2(path, path.with_name(path.name + ".memorysafe-backup"))


def _replace_text(path: Path, text: str) -> None:
    # A partial write would not lose MemorySafe's settings, it would lose all of the
    # user's; a rename in the same directory is atomic.
    temporary = path.with_name(path.name + ".memorysafe-tmp")
    temporary.write_text(text, encoding="utf-8")
    # The new file is created with the umask's mode. ~/.claude.json can be 0600, and the
    # rename would otherwise leave the user's configuration readable by other users.
    shutil.copymode(path, temporary)
    os.replace(temporary, path)


def remove_claude_registration(path: Path) -> bool:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    servers = config.get("mcpServers") if isinstance(config, dict) else None
    if not isinstance(servers, dict) or SERVER_NAME not in servers:
        return False
    del servers[SERVER_NAME]
    _backup(path)
    _replace_text(path, json.dumps(config, indent=2))
    return True


def remove_codex_registration(path: Path) -> bool:
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, ValueError):
        return False
    ranges = _codex_ranges(lines)
    if not ranges:
        return False
    removed = {index for start, end in ranges for index in range(start, end)}
    _backup(path)
    _replace_text(path, "".join(line for index, line in enumerate(lines) if index not in removed))
    return True


def _size(path: Path) -> int:
    total = 0
    for directory, _subdirectories, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(directory, name)).st_size
            except OSError:
                pass
    return total


def find_legacy(home: Path, data_root: Path) -> dict[str, Any]:
    old_runtime = data_root / "claude-runtime"
    agents = home / "Library" / "LaunchAgents"
    return {
        "claude_code": {
            "config": str(claude_config(home)),
            "registered": claude_registration_present(claude_config(home)),
            "plugin_installed": claude_code_plugin_installed(home),
            # Per-project registrations, which the user-scope check above never saw.
            "projects": claude_project_registrations(claude_config(home)),
            "project_files": [str(path) for path in project_mcp_files(home)],
        },
        "codex": {
            "config": str(codex_config(home)),
            "registered": codex_registration_present(codex_config(home)),
            "plugin_installed": codex_plugin_installed(home),
        },
        "old_runtime": {"path": str(old_runtime), "bytes": _size(old_runtime)} if old_runtime.is_dir() else None,
        "launch_agents": sorted(path.name for path in agents.glob("ca.memorysafe.*.plist")) if agents.is_dir() else [],
    }


def apply(home: Path) -> list[str]:
    """Remove each manual entry whose assistant also has the plugin. Returns the changed files."""

    changed = []
    if claude_code_plugin_installed(home):
        if remove_claude_registration(claude_config(home)):
            changed.append(str(claude_config(home)))
        # Same rule as the user-scope entry: only where that assistant has the plugin,
        # because otherwise the hand-written entry is that project's only way in.
        if remove_claude_project_registrations(claude_config(home)) and str(claude_config(home)) not in changed:
            changed.append(str(claude_config(home)))
        for project_file in project_mcp_files(home):
            if remove_project_mcp_file_entry(project_file):
                changed.append(str(project_file))
    if codex_plugin_installed(home) and remove_codex_registration(codex_config(home)):
        changed.append(str(codex_config(home)))
    return changed
