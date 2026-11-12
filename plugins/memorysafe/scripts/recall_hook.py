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
are stable enough to carry into every session, capped in number and length so the cost is
a few hundred input tokens, not a transcript. On a prompt that reads like a task (build,
fix, add, write, ...) it adds one line asking the assistant to call memorysafe_find for the
task before starting, which is where project memories come from and what records a recall
in the store.

Which ones it carries
---------------------
A dozen lines out of hundreds is a choice, and the first version made it badly: protected
first, then importance, then the row's last change. Nearly every memory is protected, and
decisions score highest, so on a well-used store the twelve lines were the most recently
touched decisions ("On 6 October we released 0.4.14") and not one of the stated
preferences, which are the only memories that apply to every session whatever it is about. Now the kinds are taken in the order they apply everywhere: safety,
then how the person wants to work (preferences), then who they are (personal), then
decisions, then anything else protected. Within a kind, the ones that have come up most
and most recently go first (memorysafe_chatgpt.retention), and two lines saying the same
thing are carried once. Project memories still come from memorysafe_find, where the task
says which ones matter.

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
import struct
import sys
from pathlib import Path

MAX_MEMORIES = 12
MAX_CHARS_EACH = 160
MAX_CHARS_TOTAL = 1400
# The order the kinds are carried in: what applies to every session first.
CARRIED_CATEGORIES = ("safety", "preference", "personal", "decision")
# How many rows are read to choose from, shared between the kinds and between the most
# recently used and the most used of each (carried_memories).
MAX_CONSIDERED = 2000
MODE_FILE = "storage-mode.json"

_HOSTED_CONTEXT = (
    "MemorySafe: this person's memories are kept in their hosted MemorySafe account, not on this "
    "computer. For anything about their preferences, past work, people or decisions, call "
    "memorysafe_find before answering."
)

_TASK_RE = re.compile(
    r"^\s*(?:please\s+)?(?:can you\s+|could you\s+)?"
    r"(?:implement|add|fix|write|create|build|refactor|update|change|make|set up|migrate|"
    r"convert|rename|remove|delete|improve|optimi[sz]e|debug|test|document|deploy|generate)\b",
    re.IGNORECASE,
)

_TASK_HINT = (
    "Before starting this task, call memorysafe_find with its key terms: the user's stored "
    "preferences and project memories may apply. Use what matches without "
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


def connect_read_only(database: Path) -> sqlite3.Connection:
    """A read-only connection that never creates, migrates or write-locks the store:
    mode=ro, and on Apple's system Python, which refuses that form on some paths,
    mode=ro&immutable=1 (no locking at all). Same as capture_hook's."""
    uri = database.resolve().as_uri()
    try:
        return sqlite3.connect(f"{uri}?mode=ro", uri=True, timeout=1)
    except sqlite3.OperationalError:
        # immutable=1 reads the main file and ignores the write-ahead log, so while another
        # program is mid-write it shows the store as it was: a memory forgotten a moment ago
        # still active, automatic mode still on after it was switched off. Acting on that
        # would carry or save what the person just said not to. When the log holds anything,
        # this reader says it cannot read, and the hook stays silent for this one turn.
        if unseen_changes(database):
            raise sqlite3.OperationalError("the store has changes this reader cannot see")
        return sqlite3.connect(f"{uri}?mode=ro&immutable=1", uri=True, timeout=1)


def unseen_changes(database: Path) -> bool:
    """Whether the write-ahead log holds changes not yet in the main file.

    A checkpoint copies the log into the main file but does not shrink the log, so the log
    is almost never empty while an assistant has the store open, and "not empty" kept the
    immutable reader from ever running (found 11 Nov 2026). SQLite's index beside the log
    (-shm) says how far the log goes (mxFrame, byte 16 of its header) and how much of it is
    already in the main file (nBackfill, byte 96), in this machine's byte order. When the two
    match, the main file is current. When the index is missing, torn or unreadable, the log
    is taken to hold changes, as before."""
    wal = database.with_name(database.name + "-wal")
    try:
        if wal.stat().st_size == 0:
            return False
    except OSError:
        return False
    try:
        header = database.with_name(database.name + "-shm").read_bytes()[:136]
    except OSError:
        return True
    # Two copies of the header, written one after the other: equal means not mid-update.
    if len(header) < 136 or header[:48] != header[48:96] or header[12] != 1:
        return True
    written, copied = struct.unpack_from("=I", header, 16)[0], struct.unpack_from("=I", header, 96)[0]
    return written != copied


def state_dir(database: Path) -> Path:
    """Where this install keeps its setup records: MEMORYSAFE_STATE_DIR, else beside data/."""
    configured = os.environ.get("MEMORYSAFE_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    return database.parent.parent / "runtime-state"


def hosted_mode(database: Path) -> bool:
    """Whether the person chose to keep their memories in their hosted account.

    In that mode the file on this computer is the copy they left behind: carrying it into
    a session would hand the assistant memories the account may since have changed,
    forgotten or erased, labelled as current. Unreadable or missing means local, as in
    storage_mode.read_storage_mode."""
    try:
        record = json.loads((state_dir(database) / MODE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(record, dict) and record.get("mode") == "hosted"


def _from_src(name: str):
    """A stdlib-only module of memorysafe_chatgpt from the plugin's own src/, or None."""
    here = Path(__file__).resolve().parent
    for candidate in (here.parent / "src", here.parent.parent / "src"):
        if (candidate / "memorysafe_chatgpt" / f"{name}.py").is_file() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    try:
        return __import__(f"memorysafe_chatgpt.{name}", fromlist=[name])
    except Exception:  # noqa: BLE001 - any import failure means "do without it"
        return None


def _retention():
    """memorysafe_chatgpt.retention, or None; without it the order falls back to the newest."""
    return _from_src("retention")


# What is never carried, whatever kind of memory it is. Automatic capture refuses these
# shapes, but an explicit "remember this" has no filter (the person asked), so a store can
# hold a card number, a key or someone's phone number. Carried at session start it would be
# put into every conversation, in every project, and sent to the assistant's provider with
# the rest of it, by a session that never asked. It stays in the store and a search for it
# still finds it.
NEVER_CARRIED_SHAPES = frozenset({
    "credential", "payment_card", "government_id", "email_address", "phone_number",
    "street_address", "postal_code",
})
# Health and the other sensitive subjects are carried only as a safety note. "I am allergic
# to penicillin", saved as safety, is in every session because that is what a safety note is
# for. A diagnosis or a prescription mentioned in a personal fact or a decision is not: it
# would ride into every conversation about code or invoices, and to the assistant's provider.
CARRIED_ONLY_AS_SAFETY = frozenset({"sensitive_subject"})


def _too_private_to_carry(policy, content: str, category: str = "") -> bool:
    if policy is None:
        return False
    try:
        shape = policy.classify(content)
    except Exception:  # noqa: BLE001 - a filter that breaks must not silence the session
        return False
    return shape in NEVER_CARRIED_SHAPES or (shape in CARRIED_ONLY_AS_SAFETY and category != "safety")


def _words(text: str) -> frozenset:
    return frozenset(re.findall(r"[^\W_]+", text.casefold()))


# "don't" reads as "don" and "t". A negation on one side only is a different fact.
_NEGATIONS = frozenset({"not", "no", "never", "nor", "without", "cannot", "don", "doesn", "didn",
                        "isn", "aren", "wasn", "weren", "won", "shouldn", "mustn", "t"})


def _same_fact(words: frozenset, other: frozenset) -> bool:
    if not words or not other or (words & _NEGATIONS) != (other & _NEGATIONS):
        return False
    return len(words & other) >= 0.75 * max(len(words), len(other))


def carried_memories(database: Path, now=None) -> tuple[int, list[tuple[str, str]]]:
    """(active count, [(category, content), ...]) for the memories worth every session, in
    the order they should be carried: by kind, then by how they have been used."""
    if not database.is_file():
        return 0, []
    try:
        connection = connect_read_only(database)
        try:
            active = connection.execute(
                "SELECT COUNT(*) FROM memories WHERE state = 'active'"
            ).fetchone()[0]
            columns = {row[1] for row in connection.execute("PRAGMA table_info(memories)")}
            # Stores written before the use columns existed are read as never used since saved.
            extra = "".join(f", {name}" for name in ("recall_count", "last_used_at", "restated_count") if name in columns)
            placeholders = ",".join("?" for _ in CARRIED_CATEGORIES)
            connection.row_factory = sqlite3.Row
            # Each kind is read on its own, so one kind cannot crowd another out of the
            # window, and each is read twice: the most recently used, and the most used.
            # A window on updated_at alone, shared by every kind, lost the preference
            # saved months ago and recalled every week: a recall moves last_used_at and
            # recall_count, never updated_at.
            recent = "COALESCE(last_used_at, updated_at)" if "last_used_at" in columns else "updated_at"
            orders = [f"{recent} DESC"] + (["recall_count DESC, updated_at DESC"] if "recall_count" in columns else [])
            kinds = [("category = ?", (category,)) for category in CARRIED_CATEGORIES]
            kinds.append((f"protected = 1 AND category NOT IN ({placeholders})", tuple(CARRIED_CATEGORIES)))
            share = max(1, MAX_CONSIDERED // (len(kinds) * len(orders)))
            rows, taken = [], set()
            for where, values in kinds:
                for order in orders:
                    for row in connection.execute(
                        f"SELECT rowid AS row_key, category, content, importance, protected, created_at, updated_at{extra} "
                        f"FROM memories WHERE state = 'active' AND {where} ORDER BY {order} LIMIT ?",
                        (*values, share),
                    ):
                        if row["row_key"] not in taken:
                            taken.add(row["row_key"])
                            rows.append(row)
        finally:
            connection.close()
    except sqlite3.Error:
        return 0, []

    retention = _retention()
    if retention is not None:
        from datetime import datetime, timezone

        moment = now or datetime.now(timezone.utc)
        score = {id(row): retention.retention(row, moment) for row in rows}
    else:
        score = {id(row): -position for position, row in enumerate(rows)}

    def rank(row) -> tuple:
        category = str(row["category"])
        kind = CARRIED_CATEGORIES.index(category) if category in CARRIED_CATEGORIES else len(CARRIED_CATEGORIES)
        return (kind, -score[id(row)])

    chosen: list[tuple[str, str]] = []
    seen: list[frozenset] = []
    policy = _from_src("capture_policy")
    for row in sorted(rows, key=rank):
        if _too_private_to_carry(policy, str(row["content"]), str(row["category"])):
            continue
        words = _words(str(row["content"]))
        # One line per fact: a second memory that says nearly the same in nearly the same
        # words adds tokens and nothing else. Measured against the longer of the two, so a
        # memory that adds to a shorter one ("allergic to penicillin and peanuts") is
        # kept; never across a negation ("do not use semicolons"); and never for a safety
        # note, where a near repeat costs one line and a dropped one can cost much more.
        if str(row["category"]) != "safety" and any(_same_fact(words, other) for other in seen):
            continue
        seen.append(words)
        chosen.append((str(row["category"]), str(row["content"])))
        if len(chosen) == MAX_MEMORIES:
            break
    return int(active or 0), chosen


def active_count(database: Path) -> int:
    """How many memories are in recall; 0 when there is no store or it cannot be read."""
    if not database.is_file():
        return 0
    try:
        connection = connect_read_only(database)
        try:
            return int(connection.execute("SELECT COUNT(*) FROM memories WHERE state = 'active'").fetchone()[0] or 0)
        finally:
            connection.close()
    except sqlite3.Error:
        return 0


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

    database = database_path()
    hosted = hosted_mode(database)
    if event == "SessionStart":
        if hosted:
            context = _HOSTED_CONTEXT
        else:
            active, memories = carried_memories(database)
            if not memories:
                return 0
            context = session_context(active, memories)
    elif event == "UserPromptSubmit":
        if not isinstance(prompt, str) or len(prompt) > 4000 or not _TASK_RE.search(prompt):
            return 0
        if not hosted and active_count(database) == 0:
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
