"""Move memories between MemorySafe stores: export the active ones to a file, import a file.

A store is one SQLite file on one computer. People change computers, run a second one, or
want their memories in another MemorySafe store; before this the only way was copying the
database file by hand, which drags every forgotten memory and the whole audit trail along.

What travels, and what does not:
  * Only ACTIVE memories are exported. A forgotten memory stays forgotten: exporting it would
    bring it back on the other side, which is the opposite of what the person asked for.
    Superseded and evicted memories stay behind for the same reason.
  * Each memory keeps its text, category, protection, source and its two dates. The dates
    matter: "the permit is pending", written in March, must not arrive looking new.
  * It also keeps its search words and how it has been used (how often it was recalled or
    said again, and when last). Use is what decides which memories a session carries and
    which of two equal matches comes first; without it, a store moved from Hosted to this
    computer, or the other way, would arrive with every memory looking equally unused. A
    file written before these fields existed imports as it always did.
  * The audit trail and conflict decisions do not travel. The receiving store
    makes its own decisions: every imported memory goes through remember(), so exact and near
    duplicates merge, and a clear contradiction between two imported memories is decided the
    way it would have been if they had been written there, oldest first. The import result
    says how many of each happened, so nothing changes silently.

The file holds memory text in plain JSON. It is written readable by its owner only, and it is
the owner's to keep or delete.
"""

from __future__ import annotations

import json
import re
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FORMAT = "memorysafe-export"
FORMAT_VERSION = 1
CATEGORIES = ("preference", "personal", "project", "decision", "task", "safety", "other")
# A store far past this is not a personal memory store; refuse rather than run for an hour.
MAX_IMPORT = 20_000


def export_active(store: Any) -> dict[str, Any]:
    """Every active memory, oldest first, as a dict ready for json.dumps."""

    from . import bootstrap_catalog

    with store._session() as connection:
        rows = connection.execute(
            "SELECT id, content, category, protected, source, created_at, updated_at, "
            "search_terms, recall_count, restated_count, last_used_at "
            "FROM memories WHERE state = 'active' ORDER BY created_at, id"
        ).fetchall()
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "exported_by": f"MemorySafe {bootstrap_catalog.VERSION}",
        "memories": [
            {
                "id": str(row["id"]),
                "content": str(row["content"]),
                "category": str(row["category"]),
                "protected": bool(row["protected"]),
                "source": str(row["source"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
                "keywords": str(row["search_terms"] or "").split(),
                "recall_count": int(row["recall_count"] or 0),
                "restated_count": int(row["restated_count"] or 0),
                "last_used_at": row["last_used_at"],
            }
            for row in rows
        ],
    }


def write_export(store: Any, path: Path) -> dict[str, Any]:
    """Write the export to `path`, readable by its owner only. Refuses to overwrite."""

    data = export_active(store)
    path = Path(path).expanduser()
    # O_EXCL: never replace an existing file, which could be another export someone kept.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    return {"path": str(path), "count": len(data["memories"])}


EXPORT_NAME = re.compile(r"memorysafe-export-\d{8}-\d{6}\.json")


def export_dir(state_dir: Path) -> Path:
    """Where the dashboard's "Move to Hosted" writes its export before the browser saves it."""
    return Path(state_dir) / "exports"


def write_dashboard_export(store: Any, state_dir: Path) -> dict[str, Any]:
    """An export under the install's own state folder, named by the time, for the dashboard to
    hand to the browser (which puts it in Downloads, where people look)."""
    from datetime import datetime

    folder = export_dir(state_dir)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"memorysafe-export-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    result = write_export(store, folder / name)
    return {**result, "file_name": name}


def find_dashboard_export(state_dir: Path, name: str) -> Path | None:
    """The export called `name` in this install's exports folder, if it is one (no other path)."""
    if not EXPORT_NAME.fullmatch(name):
        return None
    candidate = export_dir(state_dir) / name
    return candidate if candidate.is_file() else None


def read_export(path: Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    return parse_export(data)


def parse_export(data: Any) -> list[dict[str, Any]]:
    """The memories in an export, checked. Raises ValueError naming the first problem."""

    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("This is not a MemorySafe export file.")
    if data.get("format_version") != FORMAT_VERSION:
        raise ValueError(
            f"This export is format version {data.get('format_version')!r}; this MemorySafe reads "
            f"version {FORMAT_VERSION}. Update MemorySafe and try again."
        )
    memories = data.get("memories")
    if not isinstance(memories, list):
        raise ValueError("The export has no list of memories.")
    if len(memories) > MAX_IMPORT:
        raise ValueError(f"The export holds {len(memories)} memories; the limit is {MAX_IMPORT}.")
    checked = []
    for number, item in enumerate(memories, start=1):
        if not isinstance(item, dict) or not isinstance(item.get("content"), str) or not item["content"].strip():
            raise ValueError(f"Memory {number} in the export has no text.")
        checked.append(item)
    return checked


def _stamp(value: Any, now: str) -> str:
    """A stored date if it is a real one and not in the future; otherwise now."""

    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return now
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    stamp = parsed.isoformat(timespec="seconds")
    return now if parsed > datetime.fromisoformat(now) else stamp


def _count(value: Any) -> int:
    """A use count from a file: a whole number from 0 to a million, else 0."""

    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if 0 <= number <= 1_000_000 else 0


@contextmanager
def _held_open(store: Any):
    """Keep the store's file open for the length of an import, and close it after.

    Every save opens the file and closes it again. When the connection that closes is the
    only one, SQLite folds the write-ahead log into the file and deletes the log, and the
    next save makes it again: two saves' worth of that per memory, a few thousand times.
    On Windows, where making and deleting a file is slow, a few hundred memories took
    longer than the dashboard's request. One idle connection held here means no save is
    ever the last to close, so the log is folded in once, at the end. It holds no lock and
    no transaction. A store with no file on this computer has nothing to hold."""

    path = getattr(store, "database_path", None)
    if path is None or not Path(path).is_file():
        yield
        return
    connection = sqlite3.connect(path, timeout=30)
    try:
        try:
            connection.execute("PRAGMA schema_version").fetchone()  # opens the log with the file
        except sqlite3.Error:
            pass  # the saves below report a store that cannot be read
        yield
    finally:
        connection.close()


def import_memories(store: Any, memories: list[dict[str, Any]]) -> dict[str, Any]:
    """Write each memory through remember(), oldest first, keeping its dates and protection.

    Returns counts (stored, merged, replaced_older, needs_review, protected, failed) and the
    failures with their position in the file and the reason, never the text."""

    from . import storage

    now = storage._now()
    ordered = sorted(
        enumerate(memories, start=1),
        key=lambda pair: (_stamp(pair[1].get("created_at"), now), pair[0]),
    )
    counts = {"stored": 0, "merged": 0, "replaced_older": 0, "needs_review": 0, "protected": 0, "failed": 0}
    failures: list[dict[str, Any]] = []
    with _held_open(store):
        for number, item in ordered:
            category = item.get("category") if item.get("category") in CATEGORIES else "other"
            source = str(item.get("source") or "manual")[:40]
            try:
                keywords = item.get("keywords") if isinstance(item.get("keywords"), list) else None
                written = store.remember(item["content"], category, source=source, keywords=keywords)
            except ValueError as error:
                counts["failed"] += 1
                failures.append({"position": number, "reason": str(error)})
                continue
            if written.get("decision") == "FULL":
                # The receiving store is at its plan's limit. Every later memory would be told
                # the same, so each is counted, with the reason once per memory and no text.
                counts["failed"] += 1
                failures.append({"position": number, "reason": str(written.get("reason", "The store is full."))})
                continue
            memory_id = str(written.get("memory_id", ""))
            # Protection first: protect() stamps updated_at, and the original dates go on after it.
            if item.get("protected") is True and not written.get("protected"):
                if store.protect(memory_id, True, "Protected in the store it was imported from.").get("changed"):
                    counts["protected"] += 1
            if written.get("decision") == "MERGE":
                counts["merged"] += 1
            else:
                counts["stored"] += 1
                created = _stamp(item.get("created_at"), now)
                updated = max(created, _stamp(item.get("updated_at"), now))
                used = item.get("last_used_at")
                with store._session() as connection:
                    connection.execute(
                        "UPDATE memories SET created_at = ?, updated_at = ?, recall_count = ?, "
                        "restated_count = ?, last_used_at = ? WHERE id = ? AND state = 'active'",
                        (created, updated, _count(item.get("recall_count")), _count(item.get("restated_count")),
                         _stamp(used, now) if used else None, memory_id),
                    )
            if written.get("lifecycle") == "superseded_previous":
                counts["replaced_older"] += 1
            elif written.get("lifecycle") == "needs_review":
                counts["needs_review"] += 1
    return {**counts, "total": len(memories), "failures": failures}
