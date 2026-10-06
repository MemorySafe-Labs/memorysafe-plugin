"""Where a MemoryStore keeps its rows.

The engine in storage.py decides everything -- what merges, what supersedes, what
is recalled, what is protected. A backend only opens a transaction and owns the
schema, so the local SQLite file and the hosted Postgres database run the same
decisions. There is one engine and not two because a second copy of the decisions
would drift: a memory merged or superseded here would then not be on the other
backend. The hosted edition's Postgres backend implements this protocol and lives
outside this package; nothing here imports it.
"""

from __future__ import annotations

import sqlite3
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol, Sequence


class Backend(Protocol):
    #: The ON CONFLICT target that is the settings table's primary key. SQLite keys
    #: settings by name alone; Postgres keys them by user and name.
    settings_conflict_target: str
    #: The SQLite file, or None for a backend that has no file on this computer.
    database_path: Path | None

    def initialize(self) -> None: ...

    def session(self) -> AbstractContextManager[Any]: ...

    def storage_bytes(self) -> int: ...

    def location(self) -> str: ...

    def snapshot(self, keep: int) -> Path | None: ...

    def checkpoint(self) -> dict[str, int]: ...


def insert_returning_id(connection: Any, sql: str, params: Sequence[Any]) -> int:
    """Run an INSERT and return the new row's integer id, on either backend.

    SQLite reports it as cursor.lastrowid; Postgres has no such thing and must be
    asked with RETURNING. SQLite only learned RETURNING in 3.35, and a local
    install can run on an older library, so the SQLite path keeps lastrowid.
    """

    if isinstance(connection, sqlite3.Connection):
        return int(connection.execute(sql, params).lastrowid)
    return int(connection.execute(f"{sql} RETURNING id", params).fetchone()[0])
