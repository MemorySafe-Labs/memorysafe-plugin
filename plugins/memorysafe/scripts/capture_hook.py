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

One exception, decided 4 Nov 2026 by the product owner after a real-model pilot in
which, in two rounds, the model ignored the capture hint and saved nothing: a PLAINLY STATED
PREFERENCE ("always use Black", "I prefer pytest", "from now on, no new
dependencies") is saved by this hook itself, without the model in the loop. It is
the one shape a pattern can judge, and it is the shape the product promises to
keep. The write goes through the same door as the tool: capture_policy.skip_reason
(secrets, contacts, IDs, health, length) and MemoryStore.remember with
source="automatic" (dedupe, merge, importance), so nothing this hook saves could
not have been saved by memorysafe_auto_capture. Everything else in a message is
still the model's to judge, through the hint below. The store code is imported
from the plugin's own src/ with the runtime Python; where that import fails
(system Python without the runtime), the hook falls back to the hint.

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

# A preference stated plainly enough that no judgement is needed: one short sentence,
# imperative or first person, about how the user wants things done. Questions and
# anything over PREFERENCE_MAX_CHARS are left to the model.
_CLEAR_PREFERENCE_RE = re.compile(
    r"^\s*(?:please\s+)?(?:"
    r"(?:always|never)\s+\w+"
    r"|i\s+(?:always|never)\s+(?:use|want|prefer|write|run)\b"
    r"|i\s+prefer\b"
    r"|(?:from now on|going forward)\b"
    r"|(?:do not|don't|never)\s+(?:add|use|install|write|create)\b"
    r"|(?:use|stick to|stick with)\s+\S+.*\b(?:for|when|instead of|not)\b"
    r")",
    re.IGNORECASE,
)
PREFERENCE_MAX_CHARS = 200
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

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
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "MemorySafe"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "MemorySafe"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = (Path(xdg) if xdg else Path.home() / ".local" / "share") / "MemorySafe"
    return base / "data" / "memorysafe.sqlite3"


def connect_read_only(database: Path) -> sqlite3.Connection:
    """A read-only connection that never creates, migrates or write-locks the store.

    mode=ro first. Apple's system Python (3.9, SQLite 3.51) refuses that form on some
    paths with "unable to open database file" while the plugin runtime accepts it, so
    the fallback adds immutable=1, which reads the file without locking at all (4 Nov
    2026). Raises sqlite3.Error when neither works."""
    uri = database.resolve().as_uri()
    try:
        return sqlite3.connect(f"{uri}?mode=ro", uri=True, timeout=1)
    except sqlite3.OperationalError:
        return sqlite3.connect(f"{uri}?mode=ro&immutable=1", uri=True, timeout=1)


def automatic_mode_enabled(database: Path) -> bool:
    if not database.is_file():
        return False
    try:
        connection = connect_read_only(database)
        try:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = 'automatic_mode'"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return False
    return bool(row and row[0] == "enabled")


def clear_preferences(prompt: str) -> list[str]:
    """The sentences of `prompt` that state a preference plainly, at most three."""
    found = []
    for sentence in _SENTENCE_SPLIT.split(prompt):
        sentence = " ".join(sentence.split())
        if not sentence or "?" in sentence or len(sentence) > PREFERENCE_MAX_CHARS:
            continue
        if _CLEAR_PREFERENCE_RE.match(sentence):
            found.append(sentence)
        if len(found) == 3:
            break
    return found


def _import_store():
    """(MemoryStore, capture_policy) from the plugin's own src/, or None.

    The shipped plugin has scripts/ and src/ side by side; the source tree has src/ two
    levels up. The runtime Python has the store's dependencies; a system Python may not,
    and then this hook keeps to the hint."""
    here = Path(__file__).resolve().parent
    for candidate in (here.parent / "src", here.parent.parent / "src"):
        if (candidate / "memorysafe_chatgpt" / "storage.py").is_file() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    try:
        from memorysafe_chatgpt import capture_policy
        from memorysafe_chatgpt.storage import MemoryStore
    except Exception:  # noqa: BLE001 - any import failure means "no store code here"
        return None
    return MemoryStore, capture_policy


def save_preferences(database: Path, sentences: list[str]) -> list[str]:
    """Save each plainly stated preference through the store's own governance; the
    contents actually saved (a merge counts; a policy refusal or a SKIP does not)."""
    loaded = _import_store()
    if loaded is None:
        return []
    MemoryStore, capture_policy = loaded
    saved = []
    try:
        store = MemoryStore(database)
        for sentence in sentences:
            if capture_policy.skip_reason(sentence, "preference", True) is not None:
                continue
            result = store.remember(sentence, "preference", source="automatic")
            if result.get("decision") != "SKIP":
                saved.append(str(result.get("content") or sentence))
    except Exception:  # noqa: BLE001 - a hook never fails a prompt; the model still gets the hint
        return saved
    return saved


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

    if _EXPLICIT_RE.search(prompt):
        return 0
    preferences = clear_preferences(prompt)
    if not preferences and not _FACT_RE.search(prompt):
        return 0

    database = database_path()
    if not automatic_mode_enabled(database):
        return 0

    context = _HINT
    if preferences:
        saved = save_preferences(database, preferences)
        if saved:
            listed = "; ".join(f'"{content}"' for content in saved)
            context = (
                f"MemorySafe saved automatically (automatic mode is on): {listed}. "
                "Do not save it again; apply it. "
            ) + (_HINT if _FACT_RE.search(prompt) else "")

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context.strip(),
            },
            "suppressOutput": True,
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
