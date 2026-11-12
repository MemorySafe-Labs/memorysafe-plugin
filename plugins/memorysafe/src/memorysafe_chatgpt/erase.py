"""Permanent erase for the local store: one memory, or everything on this computer.

`forget` takes a memory out of recall and keeps the row, its history and every copy; that
is what it promises, and it is what makes it reversible. Until now it was also the only
thing the local store could do, so a person who wanted something gone for good had no way
to do it short of deleting files by hand, and the files the privacy policy named were not
all of them: the text also sat in the decision history ("Previous text: ..."), in the
evidence of every conflict it was part of, in the search log, in up to five snapshots, in
the write-ahead log and in the free pages SQLite leaves behind after a DELETE.

What erasing one memory removes, in one transaction:
  * the memory itself, in whatever state it is in (active, forgotten, superseded, ...);
  * the older versions it replaced, followed through the replacement records, because
    "I moved to Oak Avenue" erased while "I live on Elm Street" stays is not an erase;
  * every conflict and replacement record with any of those memories on either side
    (their reason and evidence quote the values);
  * every history entry about them, and every entry about another memory that names one
    of them;
  * the words of every past search. A search recorded its query and no memory id, so it
    cannot be tied to one memory; the count and size of each search stay, its words go.
    Searches made by this version record no words in the first place.
Then, outside the transaction, the file is rewritten without the freed pages (VACUUM), the
write-ahead log is emptied, every snapshot and dashboard export is deleted, and one fresh
snapshot is taken, so the backup still exists and no longer holds the text.

When the rewrite is refused (another program is using the file), the store is marked as
having an unfinished erase, in the same transaction that deleted the rows. While the mark
is there no snapshot is taken by anything, the dashboard's snapshot at start included: a
backup copies free pages, and would put the text back in the folder just emptied.
`finish` rewrites the file, clears the mark and takes the snapshot. Nobody has to remember
to run it: health and the doctor say an erase is waiting, the dashboard tries `finish` each
time it starts, and an uninstall's backup of such a store is written without the freed
pages. Separately, every store connection sets SQLite's secure_delete, so deleted text is
zeroed where it lay and does not wait for the rewrite.

What stays is a receipt: which memory id was erased, when, and how many rows of each kind
went with it. It holds no memory text. `receipts()` lists them.

What this cannot reach, and says so in every receipt: anything already sent to an
assistant's company in a conversation, session transcripts those assistants keep, export
files saved outside MemorySafe's own folders, and Time Machine or other backups of this
computer. Deleted blocks on the disk itself are the operating system's to reuse.

This is deliberately not an MCP tool. An assistant acting on a misread request, or on text
someone else put into the conversation, must not be able to erase for good; the person
does it from the command line or the dashboard, after a confirmation.

SQLite only. The hosted edition has its own erasure, on the person's account page.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .backends.sqlite import ERASE_UNFINISHED

NOT_COVERED = (
    "Not covered: what an assistant already received in a conversation and what its company "
    "keeps, session transcripts on this computer, export files saved outside MemorySafe's own "
    "folders, and backups of this computer such as Time Machine."
)
ERASE_ALL_PHRASE = "erase everything"
RECEIPTS_FILE = "erasure-receipts.json"
_LEGACY_RECALL = "Recalled % memories for: %"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sealed(receipt: dict[str, Any]) -> dict[str, Any]:
    """The receipt with a SHA-256 of its own canonical JSON, so a saved copy can be checked."""

    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {**receipt, "digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def _require_file(store: Any) -> Path:
    path = getattr(store, "database_path", None)
    if path is None:
        raise ValueError("Permanent erase here is for the store on this computer.")
    return Path(path)


def _ensure_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS erasures (
            receipt_id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            erased_at TEXT NOT NULL,
            receipt TEXT NOT NULL
        )
        """
    )


def clear_text_caches() -> int:
    """Empty the engine's text caches in this process; they are keyed by memory text."""

    cleared = 0
    for name in ("memorysafe_chatgpt.storage", "memorysafe_chatgpt.lifecycle"):
        module = sys.modules.get(name)
        if module is None:
            continue
        for value in list(vars(module).values()):
            clear = getattr(value, "cache_clear", None)
            if callable(clear) and hasattr(value, "cache_info"):
                clear()
                cleared += 1
    return cleared


def older_versions(
    connection: Any,
    memory_id: str,
    *,
    columns: str = "m.id",
    keep: Callable[[Any], bool] | None = None,
) -> list[Any]:
    """Every older version `memory_id` replaced, and what those replaced, newest first, as
    rows of `columns` (each row has `id`).

    Only replacement records are followed (a memory superseded by this one, and what that
    one superseded in turn). A memory that merely conflicted with it, or was kept beside
    it, is someone's separate fact and stays. `keep` refuses a row, and the walk does not
    go past it: the hosted edition uses it to stop at a teammate's memory. The one walk for
    both editions, so a local and a hosted erase take the same family.
    """

    found: list[Any] = []
    seen = {memory_id}
    frontier = [memory_id]
    while frontier:
        current = frontier.pop()
        rows = connection.execute(
            f"SELECT {columns} FROM memory_relations r JOIN memories m ON m.id = r.old_memory_id "
            "WHERE r.new_memory_id = ? AND r.decision = 'SUPERSEDE' AND m.state = 'superseded'",
            (current,),
        ).fetchall()
        for row in rows:
            old_id = str(row["id"])
            if old_id in seen or (keep is not None and not keep(row)):
                continue
            seen.add(old_id)
            found.append(row)
            frontier.append(old_id)
    return found


def _family(connection: sqlite3.Connection, memory_id: str) -> list[str]:
    """The memory and every older version it replaced, newest first."""

    return [memory_id] + [str(row["id"]) for row in older_versions(connection, memory_id)]


def _footprint(connection: sqlite3.Connection, ids: list[str]) -> dict[str, int]:
    marks = ",".join("?" for _ in ids)
    relations = connection.execute(
        f"SELECT COUNT(*) FROM memory_relations WHERE old_memory_id IN ({marks}) OR new_memory_id IN ({marks})",
        (*ids, *ids),
    ).fetchone()[0]
    own = connection.execute(
        f"SELECT COUNT(*) FROM decision_events WHERE memory_id IN ({marks})", ids
    ).fetchone()[0]
    naming = 0
    for memory_id in ids:
        naming += connection.execute(
            f"""
            SELECT COUNT(*) FROM decision_events
            WHERE (memory_id IS NULL OR memory_id NOT IN ({marks})) AND instr(reason, ?) > 0
            """,
            (*ids, memory_id),
        ).fetchone()[0]
    searches = connection.execute(
        "SELECT COUNT(*) FROM decision_events WHERE decision = 'RECALL' AND reason LIKE ?",
        (_LEGACY_RECALL,),
    ).fetchone()[0]
    return {
        "memories": len(ids),
        "older_versions_it_replaced": len(ids) - 1,
        "conflict_and_replacement_records": int(relations),
        "history_entries": int(own),
        "history_entries_of_other_memories_naming_it": int(naming),
        "past_searches_whose_words_are_removed": int(searches),
    }


def _delete_side_files(database: Path, export_dirs: tuple[Path, ...]) -> dict[str, int]:
    """Every snapshot and every dashboard export: each can hold the erased text."""

    removed = {"snapshots": 0, "exports": 0}
    for path in (database.parent / "snapshots").glob("memorysafe-*.sqlite3*"):
        try:
            path.unlink()
            removed["snapshots"] += 1
        except OSError:
            pass
    for folder in export_dirs:
        for path in Path(folder).glob("memorysafe-export-*.json"):
            try:
                path.unlink()
                removed["exports"] += 1
            except OSError:
                pass
    return removed


def unfinished(store: Any) -> bool:
    """Whether an erase on this store still waits for its file to be rewritten."""

    _require_file(store)
    with store._session() as connection:
        return bool(store._backend.erase_unfinished(connection))


def _mark_finished(store: Any) -> None:
    with store._session() as connection:
        connection.execute("DELETE FROM settings WHERE key = ?", (ERASE_UNFINISHED,))


def _compact(database: Path, attempts: int = 3, wait_seconds: int = 10) -> tuple[bool, str]:
    """Rewrite the file without its freed pages and empty the write-ahead log.

    A DELETE only marks pages free; the text stays readable in the file and in the log
    until both are rewritten. VACUUM needs the database to itself for a moment, and other
    assistants may be mid-call, so it is tried a few times and its failure is reported
    rather than hidden: the erase itself has already committed either way.
    """

    last = ""
    for _attempt in range(attempts):
        try:
            connection = sqlite3.connect(database, timeout=wait_seconds, isolation_level=None)
            try:
                connection.execute(f"PRAGMA busy_timeout = {int(wait_seconds) * 1000}")
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("VACUUM")
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                connection.close()
            return True, ""
        except sqlite3.Error as error:
            last = type(error).__name__
    return False, last


def erase_memory(
    store: Any,
    memory_id: str,
    confirm: bool = False,
    *,
    export_dirs: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Erase one memory and everything derived from it. confirm=False only says what would go."""

    database = _require_file(store)
    memory_id = memory_id.strip()
    with store._session() as connection:
        _ensure_table(connection)
        row = connection.execute(
            "SELECT id, state, protected, category, created_at FROM memories WHERE id = ?",
            (memory_id,),
        ).fetchone()
        if row is None:
            return {
                "memory_id": memory_id,
                "erased": False,
                "reason": "No memory with that ID was found on this computer. Nothing was changed.",
            }
        ids = _family(connection, memory_id)
        counts = _footprint(connection, ids)
        if not confirm:
            return {
                "memory_id": memory_id,
                "erased": False,
                "needs_confirmation": True,
                "would_delete": counts,
                "reason": (
                    "Nothing was changed. Erasing is permanent: the memory, the older versions "
                    "it replaced, their history and the words of past searches are deleted and "
                    "cannot be restored. Confirm to erase."
                ),
            }
        marks = ",".join("?" for _ in ids)
        for one in ids:
            connection.execute("DELETE FROM decision_events WHERE instr(reason, ?) > 0", (one,))
        connection.execute(f"DELETE FROM decision_events WHERE memory_id IN ({marks})", ids)
        connection.execute(
            f"DELETE FROM memory_relations WHERE old_memory_id IN ({marks}) OR new_memory_id IN ({marks})",
            (*ids, *ids),
        )
        connection.execute(f"DELETE FROM memories WHERE id IN ({marks})", ids)
        # The count is the first number in the sentence; keep it, drop the words.
        connection.execute(
            """
            UPDATE decision_events
            SET reason = substr(reason, 1, instr(reason, ' for: ') - 1) || '.'
            WHERE decision = 'RECALL' AND reason LIKE ?
            """,
            (_LEGACY_RECALL,),
        )
        erased_at = _now()
        receipt_id = str(uuid.uuid4())
        receipt = _sealed(
            {
                "receipt_id": receipt_id,
                "kind": "memory",
                "memory_id": memory_id,
                "memory_category": str(row["category"]),
                "memory_created_at": str(row["created_at"]),
                "memory_state_before": str(row["state"]),
                "was_protected": bool(row["protected"]),
                "erased_at": erased_at,
                "requested_by": "the person using this computer",
                "deleted": counts,
                "kept": "This receipt: which memory id was erased, when, and the counts. No memory text.",
                "not_covered": NOT_COVERED,
            }
        )
        connection.execute(
            "INSERT INTO erasures(receipt_id, memory_id, erased_at, receipt) VALUES (?, ?, ?, ?)",
            (receipt_id, memory_id, erased_at, json.dumps(receipt, ensure_ascii=False)),
        )
        # Set with the deletion, so a crash before the rewrite still leaves the mark.
        connection.execute(
            "INSERT OR REPLACE INTO settings(key, value, updated_at) VALUES (?, '1', ?)",
            (ERASE_UNFINISHED, erased_at),
        )

    clear_text_caches()
    compacted, failure = _compact(database)
    if compacted:
        _mark_finished(store)
    # The old snapshots and exports hold the text, so they go whether or not the rewrite
    # worked. A new snapshot is taken only of a rewritten file: SQLite's backup copies free
    # pages too, so a snapshot of a file that could not be rewritten would carry the erased
    # text straight back into the folder just emptied. `finish` takes it once the rewrite has.
    removed = _delete_side_files(database, export_dirs)
    fresh = store.snapshot() if compacted and hasattr(store, "snapshot") else None
    return {
        "memory_id": memory_id,
        "erased": True,
        "receipt": receipt,
        "file_rewritten": compacted,
        "file_rewrite_error": failure or None,
        "snapshots_deleted": removed["snapshots"],
        "exports_deleted": removed["exports"],
        "fresh_snapshot": bool(fresh),
        "reason": (
            "Erased for good. "
            + ("The store's file was rewritten so the text is no longer in it. "
               if compacted else
               "The rows are deleted, but the file could not be rewritten just now because another "
               "program was using it; run `memorysafe erase --finish` when the assistants are idle. ")
            + NOT_COVERED
        ),
    }


def finish(store: Any, *, export_dirs: tuple[Path, ...] = (), quick: bool = False) -> dict[str, Any]:
    """Rewrite the file and clear snapshots again, for an erase whose rewrite was refused.

    `quick` is one short try, for the dashboard, which does this at every start and must not
    be held up by an assistant that is mid-call; it tries again at the next start."""

    database = _require_file(store)
    compacted, failure = _compact(database, attempts=1, wait_seconds=2) if quick else _compact(database)
    removed = _delete_side_files(database, export_dirs) if compacted else {"snapshots": 0, "exports": 0}
    if compacted:
        _mark_finished(store)
        if hasattr(store, "snapshot"):
            store.snapshot()
    return {"file_rewritten": compacted, "file_rewrite_error": failure or None, **removed}


def receipts(store: Any, limit: int = 50) -> list[dict[str, Any]]:
    """This store's erasure receipts, newest first. None of them holds memory text."""

    _require_file(store)
    with store._session() as connection:
        _ensure_table(connection)
        rows = connection.execute(
            "SELECT receipt FROM erasures ORDER BY erased_at DESC, receipt_id LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
    return [json.loads(row["receipt"]) for row in rows]


def erase_everything(
    database: Path,
    phrase: str,
    *,
    export_dirs: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Delete this computer's whole store: the file, its log, every snapshot and export.

    For someone who moved to a hosted account and wants no copy left here, or who is done
    with MemorySafe on this computer. Needs the phrase typed out, because nothing brings it
    back. Leaves one receipt file with counts and no text beside where the store was.
    """

    database = Path(database)
    if phrase.strip().lower() != ERASE_ALL_PHRASE:
        return {
            "erased": False,
            "needs_confirmation": True,
            "reason": (
                f'Nothing was changed. This deletes every memory on this computer for good. '
                f'To go ahead, confirm with the words "{ERASE_ALL_PHRASE}".'
            ),
        }
    counts = {"memories": 0, "history_entries": 0, "conflict_and_replacement_records": 0}
    if database.is_file():
        try:
            connection = sqlite3.connect(database, timeout=10)
            try:
                for key, table in (("memories", "memories"), ("history_entries", "decision_events"),
                                   ("conflict_and_replacement_records", "memory_relations")):
                    counts[key] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            finally:
                connection.close()
        except sqlite3.Error:
            pass
    removed_files = 0
    for path in (database, database.with_name(database.name + "-wal"), database.with_name(database.name + "-shm")):
        try:
            path.unlink()
            removed_files += 1
        except FileNotFoundError:
            pass
    side = _delete_side_files(database, export_dirs)
    clear_text_caches()
    receipt = _sealed(
        {
            "receipt_id": str(uuid.uuid4()),
            "kind": "everything_on_this_computer",
            "erased_at": _now(),
            "requested_by": "the person using this computer",
            "deleted": {**counts, "store_files": removed_files, **side},
            "kept": "This receipt: when, and the counts. No memory text.",
            "not_covered": NOT_COVERED,
        }
    )
    target = database.parent / RECEIPTS_FILE
    try:
        existing = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else []
    except (OSError, ValueError):
        existing = []
    existing.append(receipt)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(existing, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    return {
        "erased": True,
        "receipt": receipt,
        "receipt_file": str(target),
        "reason": "Every memory on this computer was erased for good. " + NOT_COVERED,
    }
