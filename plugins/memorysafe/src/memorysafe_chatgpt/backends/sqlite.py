"""The local edition's store: one SQLite file on this computer.

Everything here moved from storage.MemoryStore unchanged when the engine was split
from its storage (hosted milestone M1). The comments record why each pragma and
each close is there; read them before changing any of it.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path


def _display_path(path: Path) -> str:
    """Home-relative rendering of a database path, for display only."""
    try:
        return "~/" + str(path.resolve().relative_to(Path.home()))
    except ValueError:
        return str(path)


class SqliteBackend:
    """One SQLite file, shared by every assistant process on this computer."""

    settings_conflict_target = "key"

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        # Wait rather than fail when another client holds the database. One store can be
        # shared by Claude, ChatGPT and Codex at once, so contention is normal.
        connection.execute("PRAGMA busy_timeout = 30000")
        # Switching to WAL needs a brief exclusive lock, so it raises "database is locked"
        # if another client is mid-write. The mode is persisted in the file, so once any
        # connection has set it the rest inherit it — failing here would abort startup for
        # no reason. Verify instead of assuming.
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            # Without a checkpoint the WAL grows without bound and the main database
            # stays stale: copying memorysafe.sqlite3 on its own then silently loses
            # every memory still held in the sidecar. Folding it back in on open keeps
            # the main file a truthful copy of the store.
            connection.execute("PRAGMA wal_autocheckpoint = 200")
        except sqlite3.OperationalError:
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            if str(mode).lower() != "wal":
                raise
        return connection

    @contextmanager
    def session(self):
        """Open one connection for one operation, commit-or-rollback it, then close it.

        `with <sqlite3.Connection>:` only manages the transaction -- it commits on a
        clean exit and rolls back on an exception, but it leaves the connection OPEN.
        That was invisible on POSIX, where unlinking an open file is legal, but on
        Windows SQLite opens the database file without FILE_SHARE_DELETE: a connection
        left open here by e.g. `remember()` blocked doctor.py's support-bundle copy,
        `memorysafe migrate`, and a user backing up or moving their own store, minutes
        or even processes later. This wraps the same commit/rollback semantics in a
        `finally: connection.close()` so every operation still leaves nothing open,
        without introducing a pooled or cached connection -- a fresh connection per
        operation is still what lets several assistant processes write to this file
        at once.
        """
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    normalized_content TEXT NOT NULL,
                    category TEXT NOT NULL,
                    importance REAL NOT NULL,
                    confidence REAL NOT NULL,
                    protected INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT 'active',
                    source TEXT NOT NULL DEFAULT 'chatgpt',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE INDEX IF NOT EXISTS memories_active_category
                    ON memories(state, category);
                CREATE INDEX IF NOT EXISTS memories_normalized
                    ON memories(normalized_content);

                -- Near-duplicate detection asks for the most recent 250 in a category
                -- on every write. Without updated_at in the index that ordering sorts
                -- the whole table, so writes got slower as the store grew: 8 ms at a
                -- hundred memories, 21 ms at two thousand.
                CREATE INDEX IF NOT EXISTS memories_recent_by_category
                    ON memories(state, category, updated_at DESC);
                -- The lifecycle check reads the most recent active memories of every
                -- category on each new write; without this it sorted them every time.
                CREATE INDEX IF NOT EXISTS memories_recent_active
                    ON memories(state, updated_at DESC);


                CREATE TABLE IF NOT EXISTS decision_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision TEXT NOT NULL,
                    memory_id TEXT,
                    reason TEXT NOT NULL,
                    content_bytes INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL
                );

                -- Recall writes an event per search; the health summary reads them back.
                CREATE INDEX IF NOT EXISTS decision_events_decision
                    ON decision_events(decision, id DESC);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                -- Evidence-based replacement. Age never writes a row here.
                CREATE TABLE IF NOT EXISTS memory_relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    old_memory_id TEXT NOT NULL,
                    new_memory_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );
                CREATE INDEX IF NOT EXISTS memory_relations_status
                    ON memory_relations(status, id DESC);
                CREATE INDEX IF NOT EXISTS memory_relations_old
                    ON memory_relations(old_memory_id);
                """
            )
            event_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(decision_events)").fetchall()
            }
            if "source" not in event_columns:
                connection.execute(
                    "ALTER TABLE decision_events ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'"
                )
            memory_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(memories)").fetchall()
            }
            if "recall_count" not in memory_columns:
                # Existing stores start at zero rather than unknown: no recall was
                # recorded before this column existed, so zero is the honest value.
                connection.execute(
                    "ALTER TABLE memories ADD COLUMN recall_count INTEGER NOT NULL DEFAULT 0"
                )

    def storage_bytes(self) -> int:
        try:
            # WAL mode keeps recent commits in a sidecar file. Measuring only the main
            # database under-reports the store several times over once the WAL grows,
            # and it is the same oversight that makes a naive file copy lose memories.
            return sum(
                path.stat().st_size
                for path in (
                    self.database_path,
                    self.database_path.with_name(self.database_path.name + "-wal"),
                    self.database_path.with_name(self.database_path.name + "-shm"),
                )
                if path.exists()
            )
        except FileNotFoundError:
            return 0

    def location(self) -> str:
        # An empty store is ambiguous unless you can see which database is being read.
        # Shown home-relative so the path is legible without exposing the account name.
        return _display_path(self.database_path)

    def snapshot(self, keep: int = 5) -> Path | None:
        """Take a consistent copy of the store, keeping the last few.

        A corrupted database ended every operation with "database disk image is
        malformed" and nothing else: no repair, no earlier copy, no guidance. For a
        product whose whole promise is not losing things, one bad write was total loss.

        Uses SQLite's own backup API rather than copying the file, so a snapshot taken
        while the assistants are writing is still consistent.
        """

        directory = self.database_path.parent / "snapshots"
        directory.mkdir(parents=True, exist_ok=True)
        # Second precision let two snapshots in the same second collide and overwrite,
        # so the retained set was smaller than it claimed. Microseconds make each one
        # distinct without depending on a counter.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        target = directory / f"memorysafe-{stamp}.sqlite3"
        try:
            # Two connections here, not one: the source (this store) and the fresh
            # snapshot file being written. Both leaked on the old `with sqlite3.connect(...)
            # as x:` pattern, so both need an explicit close -- `self.session()` for the
            # source, `contextlib.closing()` for the destination (its own `with
            # destination:` still gives it the same commit/rollback semantics it had
            # before).
            with self.session() as source, closing(sqlite3.connect(target)) as destination:
                with destination:
                    source.backup(destination)
        except sqlite3.Error:
            return None

        # Keep the newest few. Snapshots that accumulate for ever are their own problem.
        existing = sorted(directory.glob("memorysafe-*.sqlite3"))
        for stale in existing[:-keep]:
            stale.unlink(missing_ok=True)
        return target

    def checkpoint(self) -> dict[str, int]:
        """Fold the write-ahead log back into the main database file.

        Call before copying, moving or backing up the store. Until this runs, the
        newest memories exist only in memorysafe.sqlite3-wal, and a copy of
        memorysafe.sqlite3 alone brings back an older, smaller store without saying so.
        """

        with self.session() as connection:
            busy, written, checkpointed = connection.execute(
                "PRAGMA wal_checkpoint(TRUNCATE)"
            ).fetchone()
        return {"busy": int(busy), "pages_written": int(written), "pages_checkpointed": int(checkpointed)}
