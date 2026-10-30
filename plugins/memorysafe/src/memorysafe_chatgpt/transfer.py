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
  * The audit trail, recall counts and conflict decisions do not travel. The receiving store
    makes its own decisions: every imported memory goes through remember(), so exact and near
    duplicates merge, and a clear contradiction between two imported memories is decided the
    way it would have been if they had been written there, oldest first. The import result
    says how many of each happened, so nothing changes silently.

The file holds memory text in plain JSON. It is written readable by its owner only, and it is
the owner's to keep or delete.
"""

from __future__ import annotations

import json
import os
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
            "SELECT id, content, category, protected, source, created_at, updated_at "
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
    for number, item in ordered:
        category = item.get("category") if item.get("category") in CATEGORIES else "other"
        source = str(item.get("source") or "manual")[:40]
        try:
            written = store.remember(item["content"], category, source=source)
        except ValueError as error:
            counts["failed"] += 1
            failures.append({"position": number, "reason": str(error)})
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
            with store._session() as connection:
                connection.execute(
                    "UPDATE memories SET created_at = ?, updated_at = ? WHERE id = ? AND state = 'active'",
                    (created, updated, memory_id),
                )
        if written.get("lifecycle") == "superseded_previous":
            counts["replaced_older"] += 1
        elif written.get("lifecycle") == "needs_review":
            counts["needs_review"] += 1
    return {**counts, "total": len(memories), "failures": failures}
