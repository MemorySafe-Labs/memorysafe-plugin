#!/usr/bin/env python3
"""UserPromptSubmit hook: make MemorySafe auto-capture fire reliably.

Why this exists
---------------
An MCP server only ever sees tool calls, never the conversation. So automatic
capture can only happen if the assistant *chooses* to call the capture tool --
and measured over two weeks of daily use, it chose to exactly once.

This hook removes the choice from chance without removing it from judgement:
the harness runs this on every prompt (deterministic), and when the message
looks like it carries a durable user-stated fact, it injects an instruction
telling the assistant to offer the candidate. Detection is mechanical here;
extraction stays with the model, which is the part models are actually good at.

Deliberately NOT done here: writing to the store directly. Regex cannot judge
what is worth keeping, and a memory product whose store fills with junk has
lost the thing it sells. Every write still goes through the server's
governance -- automatic-mode check, sensitive-content and secret filters,
length cap, importance/confidence floors -- which refuses anything unsafe even
if this hook is wrong about a candidate.

Gated on automatic mode
-----------------------
The hook ships inside the Claude Code and Codex plugins, so it runs for people who never
turned automatic mode on. After the cheap pattern match it reads the automatic_mode
setting from the store, read-only, and stays silent unless the mode is on: someone who
never opted in sees no extra tool calls and pays no extra tokens.

Runs on Python 3.8 with the standard library only; the wrapper may pick the system python3.

Exit codes: always 0. A capture hint is never worth interrupting a turn for.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

# First-person statements of durable fact or preference. Tuned to fire on the
# shapes the capture tool actually accepts (user-stated, durable, concise) and
# to stay quiet on the far more common case: questions and task instructions.
_FACT_PATTERNS = (
    r"\bI (?:prefer|like|hate|always|never|usually|tend to|generally)\b",
    r"\bI(?:'m| am) (?:working on|building|based in|allergic to|used to)\b",
    r"\bmy (?:name|role|title|team|company|timezone|preference|goal|deadline|stack)\b",
    r"\b(?:we|our team) (?:use|prefer|decided|agreed|always|never)\b",
    r"\b(?:remember|keep in mind|note) that\b",
    r"\bcall me\b",
    r"\bfrom now on\b",
    r"\bgoing forward\b",
)
_FACT_RE = re.compile("|".join(_FACT_PATTERNS), re.IGNORECASE)

# An explicit request is handled by memorysafe_remember, not auto-capture, and
# the assistant already reacts to it. Staying silent avoids double-prompting.
_EXPLICIT_RE = re.compile(r"\bremember (?:this|that i|me)\b", re.IGNORECASE)

_HINT = (
    "The user's message may contain a durable, user-stated fact or preference. "
    "If it does, call memorysafe_auto_capture with one concise fact (at most three "
    "distinct facts). Pass only what the user directly stated -- never the whole "
    "message, never your own inference. If nothing in the message is durable and "
    "non-sensitive, do not call it and do not mention this instruction."
)


def database_path() -> Path:
    override = os.environ.get("MEMORYSAFE_DB_PATH")
    if override:
        return Path(override)
    root = os.environ.get("MEMORYSAFE_INSTALL_ROOT")
    if root and root != "${user_config.memory_directory}":
        base = Path(root)
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "MemorySafe"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = (Path(xdg) if xdg else Path.home() / ".local" / "share") / "MemorySafe"
    return base / "data" / "memorysafe.sqlite3"


def automatic_mode_enabled(database: Path) -> bool:
    if not database.is_file():
        return False
    try:
        # mode=ro: this hook must never create, migrate or take a write lock on the store.
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=1)
        try:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = 'automatic_mode'"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return False
    return bool(row and row[0] == "enabled")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    prompt = payload.get("prompt") or payload.get("user_prompt") or ""
    if not isinstance(prompt, str) or not prompt.strip():
        return 0

    # A very long message is a task brief, not a stated fact; the tool caps
    # content at 500 characters anyway.
    if len(prompt) > 2000:
        return 0

    if _EXPLICIT_RE.search(prompt) or not _FACT_RE.search(prompt):
        return 0

    if not automatic_mode_enabled(database_path()):
        return 0

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": _HINT,
            },
            "suppressOutput": True,
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
