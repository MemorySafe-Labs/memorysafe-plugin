"""Find the assistants on this computer, and connect each one to the same MemorySafe store.

The store is already shared: every host's launcher resolves the same data root, so one
SQLite file serves Claude Desktop, Claude Code and Codex. What was not shared was the
install. A user who installed the Claude Desktop extension still had to find, read and
follow a separate route for Claude Code and another for Codex, and nothing told them
which of their assistants were connected. Installing once has to be enough.

So this module answers two questions for every assistant it knows: is it on this
computer, and is MemorySafe connected to it. It connects one only through that
assistant's own installer (`claude plugin ...`, `codex plugin ...`), never by writing
its configuration by hand: 0.3.x's setup_assistants.py did that, and the result was the
double registrations `migrate` now exists to remove.

Claude Desktop is found and reported but never connected from here. Its extensions are
installed only after the user confirms them inside Claude Desktop; that confirmation is
the host's safety boundary, not a gap for us to route around.

Nothing here reads memory content. Connecting reaches the network, through the
assistant's installer, only when the user asks for it: `memorysafe connect --apply`, the
dashboard's Connect button, or the dashboard's one-time question "connect your other
assistants too?". A yes to that question is remembered (read_auto_connect), and then an
assistant installed later is connected when the dashboard service next starts. Nothing
is ever connected before that yes. Each assistant is connected automatically at most
once: one it has tried, or found connected, is settled, so an assistant the user has
since disabled or removed MemorySafe from stays that way.
"""

from __future__ import annotations

import json
import os
import shutil
import shlex
import subprocess
import sys
import tempfile
import threading
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Mapping

from .device import read_private_json, utc_now, write_private_json
from .migrate import (
    PLUGIN_ID,
    claude_code_plugin_installed,
    claude_config,
    claude_registration_present,
    codex_config,
    codex_plugin_installed,
    codex_registration_present,
)


MARKETPLACE_SOURCE = "MemorySafe-Labs/memorysafe-plugin"
MARKETPLACE_NAME = "memorysafe"
DESKTOP_DOWNLOAD = (
    "https://github.com/MemorySafe-Labs/memorysafe-plugin/releases/latest/download/memorysafe-claude-desktop.mcpb"
)
# The user's one answer to "connect your other assistants too?", kept in the state dir.
DECISION_FILE = "connect-decision.json"
# A connect runs the host's installer, which clones the marketplace from GitHub. Long
# enough for a slow network, short enough that a hung installer does not hold the
# dashboard's request forever.
CONNECT_TIMEOUT_SECONDS = 300
# Where Homebrew and hand-installed CLIs live on macOS and Linux, outside PATH when the
# process was started by launchd or from the Dock. A module constant so the tests can
# empty it: they must never find a real claude or codex on the machine running them.
_POSIX_BIN_DIRS = (Path("/opt/homebrew/bin"), Path("/usr/local/bin"))
# setup_app runs detached, with no console, and Windows gives every console program such
# a process starts a new visible window unless it is asked not to (claude_launcher too).
_CREATE_NO_WINDOW = 0x08000000
# One connect at a time. The start-up thread, the Connect buttons on two pages and the
# ask-once answer can all overlap, and two installers writing the same host's plugin
# records at once is how a half-written config happens. A caller that waits then finds
# the assistant connected and returns "already connected".
_CONNECT_LOCK = threading.Lock()

Runner = Callable[..., subprocess.CompletedProcess]


def _claude_cli_candidates(home: Path, env: Mapping[str, str], platform: str) -> list[Path]:
    # The native installer puts claude in ~/.local/bin and does not add it to PATH on
    # Windows (it prints a note and moves on), so a PATH lookup alone misses the most
    # common install. npm's global bin is the other route.
    if platform == "win32":
        appdata = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
        return [home / ".local" / "bin" / "claude.exe", appdata / "npm" / "claude.cmd"]
    return [
        home / ".local" / "bin" / "claude",
        home / ".claude" / "local" / "claude",
        *(folder / "claude" for folder in _POSIX_BIN_DIRS),
    ]


def _codex_cli_candidates(home: Path, env: Mapping[str, str], platform: str) -> list[Path]:
    if platform == "win32":
        appdata = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
        local = Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local")
        # The Codex desktop app (Microsoft Store, OpenAI.Codex) puts no codex on PATH and
        # no execution alias for it, but ships the full CLI twice: under a per-version
        # hash in %LOCALAPPDATA%\OpenAI\Codex\bin, and beside its plugin app server. Both
        # were codex-cli 0.155.0-alpha.9.2 with `plugin add` on the 19 Sep test machine.
        bundled = sorted(
            (local / "OpenAI" / "Codex" / "bin").glob("*/codex.exe"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return [
            appdata / "npm" / "codex.cmd",
            home / ".local" / "bin" / "codex.exe",
            *bundled,
            home / ".codex" / "plugins" / ".plugin-appserver" / "codex.exe",
        ]
    return [home / ".local" / "bin" / "codex", *(folder / "codex" for folder in _POSIX_BIN_DIRS)]


def find_cli(name: str, home: Path, env: Mapping[str, str], platform: str) -> str | None:
    found = shutil.which(name, path=env.get("PATH"))
    if found:
        return found
    candidates = _claude_cli_candidates if name == "claude" else _codex_cli_candidates
    for candidate in candidates(home, env, platform):
        if candidate.is_file():
            return str(candidate)
    return None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _claude_code_plugin_listed(home: Path) -> bool:
    """Installed, whether or not settings.json has switched it off."""

    installed = _read_json(home / ".claude" / "plugins" / "installed_plugins.json")
    plugins = installed.get("plugins") if isinstance(installed, dict) else None
    return isinstance(plugins, dict) and PLUGIN_ID in plugins


def _claude_code_marketplace_known(home: Path) -> bool:
    known = _read_json(home / ".claude" / "plugins" / "known_marketplaces.json")
    return isinstance(known, dict) and MARKETPLACE_NAME in known


def _codex_marketplace_known(home: Path) -> bool:
    # Codex records an added marketplace as a [marketplaces.<name>] table in config.toml.
    try:
        import tomllib

        with codex_config(home).open("rb") as handle:
            config = tomllib.load(handle)
    except (ImportError, OSError, ValueError):
        return False
    marketplaces = config.get("marketplaces")
    return isinstance(marketplaces, dict) and MARKETPLACE_NAME in marketplaces


def claude_desktop_dirs(home: Path, env: Mapping[str, str], platform: str) -> list[Path]:
    """Every folder Claude Desktop may keep its settings in, on this platform.

    The Microsoft Store build runs in an MSIX container. Its writes to %APPDATA%\\Claude
    land in the package's LocalCache instead, and a process outside the package sees
    only the real folder. The data root's own path goes through the same redirection
    (doctor.py's `real_path`), so both places have to be looked at.
    """

    if platform == "win32":
        dirs = [Path(env.get("APPDATA") or home / "AppData" / "Roaming") / "Claude"]
        packages = Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local") / "Packages"
        if packages.is_dir():
            dirs.extend(sorted(packages.glob("Claude_*/LocalCache/Roaming/Claude")))
        return dirs
    if platform == "darwin":
        return [home / "Library" / "Application Support" / "Claude"]
    return [Path(env.get("XDG_CONFIG_HOME") or home / ".config") / "Claude"]


def _desktop_extension_enabled(desktop: Path) -> bool:
    # An unpacked .mcpb is named local.mcpb.<author>.<name>. The author has changed
    # between releases ("memorysafe-beta" today), the name has not.
    extensions = desktop / "Claude Extensions"
    if not extensions.is_dir():
        return False
    for entry in extensions.iterdir():
        if not (entry.is_dir() and entry.name.endswith(".memorysafe")):
            continue
        settings = _read_json(desktop / "Claude Extensions Settings" / f"{entry.name}.json")
        # No settings file means Claude Desktop has not written one yet; only an explicit
        # false turns the extension off.
        if not (isinstance(settings, dict) and settings.get("isEnabled") is False):
            return True
    return False


def _desktop_config_registered(desktop: Path) -> bool:
    return claude_registration_present(desktop / "claude_desktop_config.json")


def _entry(agent_id: str, label: str) -> dict[str, Any]:
    return {
        "id": agent_id,
        "label": label,
        "present": False,
        "connected": False,
        # plugin, manual, extension or config: how MemorySafe reaches it today.
        "how": None,
        "can_connect": False,
        "command": None,
        # What the user has to do themselves, when connecting it is not automatic.
        "next_step": None,
    }


def _install_claude_cli_hint(platform: str) -> str:
    if platform == "win32":
        return "irm https://claude.ai/install.ps1 | iex"
    return "curl -fsSL https://claude.ai/install.sh | bash"


def _claude_code(home: Path, env: Mapping[str, str], platform: str) -> dict[str, Any]:
    entry = _entry("claude_code", "Claude Code")
    cli = find_cli("claude", home, env, platform)
    entry["command"] = cli
    # ~/.claude also exists when Claude Code only ever ran inside the Claude desktop app.
    # Its plugins load there too, but installing one still needs the claude command.
    entry["present"] = bool(cli) or (home / ".claude").is_dir() or claude_config(home).exists()
    if claude_code_plugin_installed(home):
        entry.update(connected=True, how="plugin")
    elif claude_registration_present(claude_config(home)):
        entry.update(connected=True, how="manual")
    elif entry["present"]:
        if cli:
            entry["can_connect"] = True
        else:
            entry["next_step"] = (
                "Claude Code runs here, but the claude command is not installed, and that is the only "
                f"way to add a plugin. Install it with  {_install_claude_cli_hint(platform)}  and connect again."
            )
    return entry


def _codex(home: Path, env: Mapping[str, str], platform: str) -> dict[str, Any]:
    entry = _entry("codex", "Codex")
    cli = find_cli("codex", home, env, platform)
    entry["command"] = cli
    entry["present"] = bool(cli) or (home / ".codex").is_dir()
    if codex_plugin_installed(home):
        entry.update(connected=True, how="plugin")
    elif codex_registration_present(codex_config(home)):
        entry.update(connected=True, how="manual")
    elif entry["present"]:
        if cli:
            entry["can_connect"] = True
        else:
            entry["next_step"] = (
                "Codex's settings are here but its codex command was not found, so its plugin cannot be added "
                "from here. In a terminal:  codex plugin marketplace add MemorySafe-Labs/memorysafe-plugin  "
                "then  codex plugin add memorysafe@memorysafe"
            )
    return entry


def _claude_desktop(home: Path, env: Mapping[str, str], platform: str) -> dict[str, Any]:
    entry = _entry("claude_desktop", "Claude Desktop")
    dirs = [path for path in claude_desktop_dirs(home, env, platform) if path.is_dir()]
    entry["present"] = bool(dirs)
    if any(_desktop_extension_enabled(path) for path in dirs):
        entry.update(connected=True, how="extension")
    elif any(_desktop_config_registered(path) for path in dirs):
        entry.update(connected=True, how="config")
    elif entry["present"]:
        entry["next_step"] = (
            "Claude Desktop asks you to confirm every extension, so this one step is yours: download "
            f"{DESKTOP_DOWNLOAD}, then in Claude open Settings > Extensions > Advanced settings > "
            "Install Extension..., choose the file, and leave the data folder empty. Don't double-click "
            "the file; Windows may open it in Notepad."
        )
    return entry


def inventory(
    home: Path | None = None, env: Mapping[str, str] | None = None, platform: str | None = None
) -> list[dict[str, Any]]:
    home = home or Path.home()
    env = os.environ if env is None else env
    platform = platform or sys.platform
    return [_claude_desktop(home, env, platform), _claude_code(home, env, platform), _codex(home, env, platform)]


def read_auto_connect(state_dir: Path) -> bool | None:
    """The user's answer to "connect the other assistants too?": True, False, or None if never asked.

    Installing into another assistant without asking crosses a line; asking every time
    is how a prompt gets dismissed unread. So the dashboard asks once and this remembers.
    """

    value = read_private_json(state_dir / DECISION_FILE).get("auto_connect")
    return value if isinstance(value, bool) else None


def write_auto_connect(state_dir: Path, enabled: bool) -> None:
    decision = read_private_json(state_dir / DECISION_FILE)
    decision.update(auto_connect=bool(enabled), decided_at=utc_now())
    write_private_json(state_dir / DECISION_FILE, decision)


def _settled(state_dir: Path) -> set[str]:
    value = read_private_json(state_dir / DECISION_FILE).get("settled")
    return {item for item in value if isinstance(item, str)} if isinstance(value, list) else set()


def _settle(state_dir: Path, agent_ids: list[str]) -> None:
    decision = read_private_json(state_dir / DECISION_FILE)
    decision["settled"] = sorted(_settled(state_dir) | set(agent_ids))
    write_private_json(state_dir / DECISION_FILE, decision)


def _connect_unsettled(
    state_dir: Path | None,
    skip: set[str],
    home: Path | None,
    env: Mapping[str, str] | None,
    platform: str | None,
    runner: Runner | None,
) -> list[dict[str, Any]]:
    agents = inventory(home, env, platform)
    targets = [
        agent["id"]
        for agent in agents
        if agent["can_connect"] and not agent["connected"] and agent["id"] not in skip
    ]
    if state_dir is not None:
        # Recorded before the installers run, so a service that dies mid-install does not
        # retry at every start.
        _settle(state_dir, [agent["id"] for agent in agents if agent["connected"]] + targets)
    return [connect(agent_id, home, env, platform, runner) for agent_id in targets]


def connect_all(
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    runner: Runner | None = None,
    state_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Connect every assistant that can be connected from here, one after another.

    Given the state dir, every assistant it finds connected or tries is settled, and
    auto_connect_on_start leaves it alone from then on.
    """

    return _connect_unsettled(state_dir, set(), home, env, platform, runner)


def auto_connect_on_start(
    state_dir: Path,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    runner: Runner | None = None,
) -> list[dict[str, Any]]:
    """Connect assistants installed since the user said yes. Nothing at all before that yes.

    Only assistants not yet settled. Found in review before release: a Claude Code plugin
    the user switched off (/plugin disable) reads as not connected, plan() answers that
    with `plugin enable`, and so every start switched it back on; an uninstall was undone
    the same way. A failed attempt is settled too: the panel keeps its Connect button, and
    a start does not reach GitHub for it again.
    """

    if read_auto_connect(state_dir) is not True:
        return []
    return _connect_unsettled(state_dir, _settled(state_dir), home, env, platform, runner)


def plan(agent: Mapping[str, Any], home: Path) -> list[list[str]]:
    """The installer commands that would connect this agent, in order. Empty when there are none."""

    cli = agent.get("command")
    if not agent.get("can_connect") or not cli:
        return []
    if agent["id"] == "claude_code":
        if _claude_code_plugin_listed(home):
            # Installed but switched off in settings.json: `install` would report it as
            # already there and change nothing.
            return [[cli, "plugin", "enable", PLUGIN_ID]]
        steps = [] if _claude_code_marketplace_known(home) else [[cli, "plugin", "marketplace", "add", MARKETPLACE_SOURCE]]
        return steps + [[cli, "plugin", "install", PLUGIN_ID]]
    if agent["id"] == "codex":
        steps = [] if _codex_marketplace_known(home) else [[cli, "plugin", "marketplace", "add", MARKETPLACE_SOURCE]]
        return steps + [[cli, "plugin", "add", PLUGIN_ID]]
    return []


def _process_command(argv: list[str], platform: str, env: Mapping[str, str]) -> list[str] | str:
    """How to start argv here. npm installs a .cmd, and a batch file needs cmd.exe to run it.

    Every argument is a constant from plan(), none comes from a request, and the path is
    quoted with /s so a username with a space in it survives. COMSPEC is not inherited by
    an MCP-spawned process on Windows (see CLAUDE.md), so cmd.exe comes from SYSTEMROOT.
    The path is joined as a Windows path whatever the host, so the test runs on CI too.
    """

    if platform != "win32" or not argv[0].lower().endswith((".cmd", ".bat")):
        return argv
    system_root = env.get("SYSTEMROOT") or env.get("SystemRoot") or r"C:\Windows"
    cmd = str(PureWindowsPath(system_root, "System32", "cmd.exe"))
    return f'"{cmd}" /d /s /c ""{argv[0]}" {" ".join(argv[1:])}"'


def command_line(argv: list[str], env: Mapping[str, str], platform: str) -> str:
    """argv as the user should type it: by name when that name works, else by full path.

    The CLI is found off PATH in exactly the cases this module exists for -- the Codex
    desktop app's bundled codex.exe, a claude the native installer left off PATH -- and
    telling that user to type `codex` gets "'codex' is not recognized".
    """

    cli = argv[0]
    name = (PureWindowsPath if platform == "win32" else PurePosixPath)(cli).stem
    if shutil.which(name, path=env.get("PATH")):
        shown = name
    elif platform == "win32":
        shown = f'"{cli}"' if " " in cli else cli
    else:
        shown = shlex.quote(cli)
    return " ".join([shown, *argv[1:]])


def _installer_env(cli: str, env: Mapping[str, str], platform: str) -> dict[str, str]:
    """This environment, with the CLI's own folder on PATH.

    A CLI found in a fallback folder was found there because PATH lacks it: a launchd job or
    an app started from the Dock gets /usr/bin:/bin:/usr/sbin:/sbin. npm's codex and claude
    are `#!/usr/bin/env node` scripts whose node sits in that same folder under Homebrew, so
    without it they exit 127 with "env: node: No such file or directory".
    """

    child = dict(env)
    separator = ";" if platform == "win32" else ":"
    folder = str((PureWindowsPath if platform == "win32" else PurePosixPath)(cli).parent)
    path = child.get("PATH", "")
    if folder not in path.split(separator):
        child["PATH"] = f"{folder}{separator}{path}" if path else folder
    return child


def _tail(text: str | bytes | None, limit: int = 600) -> str:
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    return (text or "").strip()[-limit:]


def connect(
    agent_id: str,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    runner: Runner | None = None,
) -> dict[str, Any]:
    """Connect one agent through its own installer, then check that it worked."""

    # Looked up per call, not bound as a default: a default would capture the real
    # subprocess.run at import, and a test replacing it would still run the installer.
    runner = runner or subprocess.run
    home = home or Path.home()
    env = os.environ if env is None else env
    platform = platform or sys.platform
    with _CONNECT_LOCK:
        return _connect(agent_id, home, env, platform, runner)


def _connect(agent_id: str, home: Path, env: Mapping[str, str], platform: str, runner: Runner) -> dict[str, Any]:
    agents = {agent["id"]: agent for agent in inventory(home, env, platform)}
    agent = agents.get(agent_id)
    if agent is None:
        return {"agent": agent_id, "ok": False, "steps": [], "message": "MemorySafe does not know that assistant."}
    if agent["connected"]:
        return {"agent": agent_id, "ok": True, "steps": [], "message": f"{agent['label']} is already connected."}
    steps: list[dict[str, Any]] = []
    commands = plan(agent, home)
    if not commands:
        return {"agent": agent_id, "ok": False, "steps": [], "message": agent["next_step"] or f"{agent['label']} was not found on this computer."}
    options = {"creationflags": _CREATE_NO_WINDOW} if platform == "win32" else {}
    for argv in commands:
        # Output goes to a file, not a pipe. On Windows, subprocess.run answers a timeout
        # by killing the child and then reading its pipes to the end, which waits for every
        # process holding them: node.exe under npm's codex.cmd, git.exe cloning the
        # marketplace. A pipe would let a hung clone outlast the timeout; a file cannot.
        with tempfile.TemporaryFile() as output:
            failure = ""
            try:
                returncode = runner(
                    _process_command(argv, platform, env),
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    timeout=CONNECT_TIMEOUT_SECONDS,
                    env=_installer_env(argv[0], env, platform),
                    **options,
                ).returncode
            except (OSError, subprocess.SubprocessError) as error:
                returncode, failure = None, str(error)
            output.seek(0)
            steps.append({"command": argv, "returncode": returncode, "output": _tail(output.read()) or failure})
        # Adding a marketplace that is already known fails on some versions and succeeds on
        # others; either way the install step after it decides. So only the outcome counts.
    after = {entry["id"]: entry for entry in inventory(home, env, platform)}[agent_id]
    if after["connected"]:
        return {"agent": agent_id, "ok": True, "steps": steps, "message": f"Connected. Restart {agent['label']} to use it."}
    manual = "  then  ".join(command_line(argv, env, platform) for argv in commands)
    return {
        "agent": agent_id,
        "ok": False,
        "steps": steps,
        "message": f"{agent['label']} did not confirm the install. Run it yourself in a terminal:  {manual}",
    }
