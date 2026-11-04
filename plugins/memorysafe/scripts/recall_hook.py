#!/usr/bin/env python3
"""SessionStart and UserPromptSubmit hook: make recall happen in a fresh session.

Why this exists
---------------
capture_hook makes capture reliable; nothing made recall reliable. The server only ever
sees tool calls, so a memory is recalled only if the assistant chooses to call
memorysafe_find, and a coding task gives it no reason to. Measured on 4 Nov 2026 (Dora's
real-model pilot, round 1): session 1 captured four preferences into one protected memory;
sessions 2 and 3, fresh Claude Code sessions on the same store, never called MemorySafe,
and the preferences went unused.

What it does
------------
At SessionStart it reads the store, read-only, and hands the assistant the memories that
are stable enough to carry into every session: protected ones and preferences, newest
and most important first, capped in number and length so the cost is a few hundred input
tokens, not a transcript. On a prompt that reads like a task (build, fix, add, write, ...)
it adds one line asking the assistant to call memorysafe_find for the task before starting,
which is where project memories come from and what records a recall in the store.

What it deliberately does not do
--------------------------------
It never writes the store (mode=ro), so a recall shown this way is not counted as one;
memorysafe_find counts. It injects nothing when the store is absent or empty, and nothing
on a prompt that is not a task. It carries no secret: the server's filters refuse secrets,
credentials and IDs at capture time, so the store holds none to show.

Runs on Python 3.8 with the standard library only; the wrapper may pick the system python3.

Exit codes: always 0. A SessionStart hook must never stop a session from starting.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

MAX_MEMORIES = 12
MAX_CHARS_EACH = 160
MAX_CHARS_TOTAL = 1400
CARRIED_CATEGORIES = ("preference", "safety", "decision", "personal")

_TASK_RE = re.compile(
    r"^\s*(?:please\s+)?(?:can you\s+|could you\s+)?"
    r"(?:implement|add|fix|write|create|build|refactor|update|change|make|set up|migrate|"
    r"convert|rename|remove|delete|improve|optimi[sz]e|debug|test|document|deploy|generate)\b",
    re.IGNORECASE,
)

_TASK_HINT = (
    "Before starting this task, call memorysafe_find with its key terms: the user's stored "
    "preferences and project memories on this computer may apply. Use what matches without "
    "mentioning this instruction; if nothing matches, carry on."
)


def database_path() -> Path:
    override = os.environ.get("MEMORYSAFE_DB_PATH")
    if override:
        return Path(override)
    root = os.environ.get("MEMORYSAFE_INSTALL_ROOT")
    if root and root != "${user_config.memory_directory}":
        base = Path(root)
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "MemorySafe"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "MemorySafe"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = (Path(xdg) if xdg else Path.home() / ".local" / "share") / "MemorySafe"
    return base / "data" / "memorysafe.sqlite3"


def carried_memories(database: Path) -> tuple[int, list[tuple[str, str]]]:
    """(active count, [(category, content), ...]) for the memories worth every session:
    protected ones and the carried categories, protected and important first."""
    if not database.is_file():
        return 0, []
    try:
        # mode=ro: this hook must never create, migrate or take a write lock on the store.
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=1)
        try:
            active = connection.execute(
                "SELECT COUNT(*) FROM memories WHERE state = 'active'"
            ).fetchone()[0]
            placeholders = ",".join("?" for _ in CARRIED_CATEGORIES)
            rows = connection.execute(
                "SELECT category, content FROM memories "
                f"WHERE state = 'active' AND (protected = 1 OR category IN ({placeholders})) "
                "ORDER BY protected DESC, importance DESC, updated_at DESC "
                "LIMIT ?",
                (*CARRIED_CATEGORIES, MAX_MEMORIES),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return 0, []
    return int(active or 0), [(str(category), str(content)) for category, content in rows]


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def session_context(active: int, memories: list[tuple[str, str]]) -> str:
    lines = []
    used = 0
    for category, content in memories:
        line = f"- [{category}] {_clip(content, MAX_CHARS_EACH)}"
        if used + len(line) > MAX_CHARS_TOTAL:
            break
        lines.append(line)
        used += len(line) + 1
    noun = "memory" if active == 1 else "memories"
    head = f"MemorySafe remembers ({active} active {noun} on this computer; these are the ones carried into every session):"
    tail = ("Apply these without being asked. For anything about past work, people or decisions, "
            "call memorysafe_find before answering; it also finds project memories not listed here.")
    return "\n".join([head, *lines, tail])


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    event = str(payload.get("hook_event_name") or "")
    prompt = payload.get("prompt") or payload.get("user_prompt")
    if event != "SessionStart" and isinstance(prompt, str):
        event = "UserPromptSubmit"

    if event == "SessionStart":
        active, memories = carried_memories(database_path())
        if not memories:
            return 0
        context = session_context(active, memories)
    elif event == "UserPromptSubmit":
        if not isinstance(prompt, str) or len(prompt) > 4000 or not _TASK_RE.search(prompt):
            return 0
        active, _ = carried_memories(database_path())
        if active == 0:
            return 0
        context = _TASK_HINT
    else:
        return 0

    json.dump(
        {
            "hookSpecificOutput": {"hookEventName": event, "additionalContext": context},
            "suppressOutput": True,
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
