"""Where a 0.3.x install left something that starts its old dashboard at login.

That item starts before any assistant does, so it takes port 8765 first and the old
dashboard is what the person sees, reading a database the new version has already moved
on. Nothing says so: the new dashboard just never appears.

Windows' 0.3.x installer wrote `MemorySafe Dashboard Service.cmd` into the Startup
folder. The cleanup looked for `.lnk`, never matched, and `uninstall --apply` reported
success while leaving a working autostart behind (reported on 0.4.10 against a
hand-installed 0.3.7). The macOS installer wrote a launchd agent that restarts itself,
so stopping the process is not enough there.

Matching is by name with any extension, so a `.cmd`, `.lnk`, `.bat` or `.vbs` all count.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Mapping

STARTUP_ITEM_STEM = "MemorySafe Dashboard Service"
MAC_SETUP_AGENT = "ca.memorysafe.beta.setup.plist"
# What a retired item is renamed to, so it can be put back by renaming it again.
RETIRED_SUFFIX = ".memorysafe-retired"


def start_menu(home: Path, env: Mapping[str, str]) -> Path:
    roaming = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
    return roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def find(home: Path, env: Mapping[str, str] | None = None, platform: str | None = None) -> list[Path]:
    """Every old start-at-login item that is still active, oldest convention first."""

    env = env or {}
    platform = platform or sys.platform
    if platform == "win32":
        startup = start_menu(home, env) / "Startup"
        if not startup.is_dir():
            return []
        return sorted(
            path
            for path in startup.glob(f"{STARTUP_ITEM_STEM}.*")
            if path.is_file() and not path.name.endswith(RETIRED_SUFFIX)
        )
    if platform == "darwin":
        agent = home / "Library" / "LaunchAgents" / MAC_SETUP_AGENT
        return [agent] if agent.is_file() else []
    return []


def remedy(items: list[Path], platform: str | None = None) -> str:
    """What the person should do about them, in words they can follow."""

    platform = platform or sys.platform
    if not items:
        return ""
    if platform == "win32":
        names = ", ".join(f"'{path}'" for path in items)
        return (
            f"An old 0.3.x start-up item is starting it every time you sign in: {names}. Delete it "
            "(or add .memorysafe-retired to its name), then sign out and back in."
        )
    if platform == "darwin":
        return (
            "An old 0.3.x background service restarts it at every login (ca.memorysafe.beta.setup). "
            "Stop it with: launchctl bootout gui/$(id -u)/ca.memorysafe.beta.setup  and move "
            f"{items[0]} somewhere safe, then restart your assistant. Leave ca.memorysafe.beta.tunnel "
            "alone if you use the ChatGPT connection."
        )
    return ""
