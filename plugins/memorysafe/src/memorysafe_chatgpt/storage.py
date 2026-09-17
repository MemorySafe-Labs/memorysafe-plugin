from __future__ import annotations

import math
import re
import unicodedata
import sqlite3
import uuid
from collections import Counter
from functools import lru_cache
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .token_metrics import count_text_tokens, tokenizer_metadata
from .lifecycle import consider_incoming, record_relation


# The numbers here used to be hand-entered constants with no derivation anywhere in
# the repository, and they silently went stale the moment a tool description changed.
# They are now measured from the live server on every call, and the comparison they
# rest on is written down in token_metrics.break_even_facts so it can be argued with.
AVERAGE_FACT_TOKENS = 60


def token_benchmark(
    average_fact_tokens: int = AVERAGE_FACT_TOKENS,
    facts_stored: int = 0,
) -> dict[str, Any]:
    """Measure the fixed context cost of running MemorySafe, and when it pays for itself."""

    from .token_metrics import (
        RECALLED_PER_TURN,
        break_even_facts,
        fixed_overhead_tokens,
        tokenizer_metadata,
    )

    overhead = fixed_overhead_tokens()
    fixed = overhead["fixed_overhead_tokens"]

    def _savings(count: int) -> float:
        baseline = count * average_fact_tokens
        governed = fixed + RECALLED_PER_TURN * average_fact_tokens
        if baseline <= 0:
            return 0.0
        return round(max(0.0, 100.0 * (1.0 - governed / baseline)), 1)

    def _compare(count: int) -> dict[str, Any]:
        avg = max(1, int(average_fact_tokens))
        n = max(0, int(count))
        without = n * avg
        with_ms = fixed + RECALLED_PER_TURN * avg
        saved = max(0, without - with_ms)
        paying_off = without >= with_ms and without > 0
        percent = round(100.0 * saved / without, 1) if paying_off else 0.0
        extra = max(0, with_ms - without)
        return {
            "facts_stored": n,
            "average_fact_tokens": avg,
            "facts_recalled_per_turn": RECALLED_PER_TURN,
            "fixed_overhead_tokens": fixed,
            "without_memorysafe_tokens": without,
            "with_memorysafe_tokens": with_ms,
            "tokens_saved_per_turn": saved,
            "tokens_extra_per_turn": extra,
            "percent_saved": percent,
            "paying_off": paying_off,
        }

    return {
        "kind": "measured_input_payload_model",
        "tokenizer": tokenizer_metadata()["tokenizer"],
        "tool_schema_tokens": overhead["tool_schema_tokens"],
        "instruction_tokens": overhead["instruction_tokens"],
        "fixed_overhead_tokens": fixed,
        "average_fact_tokens": average_fact_tokens,
        "recalled_per_turn": RECALLED_PER_TURN,
        "break_even_facts": break_even_facts(average_fact_tokens),
        "savings_at_80_facts": _savings(80),
        "savings_at_160_facts": _savings(160),
        "live_compare": _compare(facts_stored),
        "chatgpt_live_usage_available": False,
        "model": (
            "Baseline restates every stored fact each turn (N x average). MemorySafe costs "
            "the fixed overhead plus the facts actually recalled. Break-even at "
            "N = overhead / average + recalled_per_turn."
        ),
        "note": (
            "Measured live from this server's tool definitions and instructions, not a stored "
            "constant. It models input payload only: it says nothing about answer quality and "
            "is not anyone's billed usage."
        ),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@lru_cache(maxsize=8192)
def _normalize(content: str) -> str:
    """Fold text to comparable words, in any language.

    This matched [a-z0-9] only. Portuguese broke at every accent — "submissão" became
    "submiss o" and "coração" became "cora o" — and Japanese, Russian, Arabic and Greek
    normalised to nothing at all, so those memories were refused as containing no
    letters. Accents are folded as well, so "submissao" finds "submissão": people do not
    reliably type their own accents into a search box.
    """

    folded = unicodedata.normalize("NFKD", content.casefold())
    stripped = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[^\W_]+", stripped, flags=re.UNICODE))


# Words that carry no retrieval signal. Left in, they were the whole false-positive
# problem: "what is the capital of Portugal" shares "is" and "of" with a memory about
# who holds equity, which scored 0.244 against a 0.12 bar and came back as a hit.
_STOPWORDS = frozenset("""
a an and any are as at be been by can did do does for from get give had has have how i
if in into is it its many me much my of on or our should so some tell that the their
them then there these they this to was we were what when where which who whom why will
with would you your about actually just really please
""".split())


def _stem(token: str) -> str:
    """Enough stemming to match patent/patents and incorporation/incorporated.

    Both were real misses. A full stemmer is not worth the dependency or the surprises;
    these three suffixes cover the plural-and-tense mismatches that actually occurred.
    """

    # Longest first, and "ated" before "ation": stripping only "ation" turned
    # incorporation into "incorpor" while incorporated became "incorporat", so the two
    # never met and "what is my incorporation number" matched the NEQ instead.
    for suffix in ("ations", "ation", "ated", "ing", "ed", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


_DATE_HINT = re.compile(
    r"\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}"
    r"|\b20\d{2}\b|\b\d{1,2}/\d{1,2}\b|\b\d{1,2}(?:st|nd|rd|th)\b",
    re.IGNORECASE,
)
_AMOUNT_HINT = re.compile(
    r"[$€£]\s?\d|\b(?:cad|usd|eur)\s?\$?\d|\b\d[\d,]*\s?(?:k|m)\b|\b\d{1,3}(?:,\d{3})+\b|\b\d+\s?%",
    re.IGNORECASE,
)
_PERSON_HINT = re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b")


def _question_shape(query: str) -> str | None:
    """What kind of answer the question is asking for.

    Every near-miss in the benchmark was a tie: two memories matched the same single
    word and the ranking fell to length and importance, which is arbitrary. The
    question word says what the answer should look like — "when" wants a date, "how
    much" wants an amount — and the memory that has one is almost always the right one.
    """

    lowered = query.casefold()
    if lowered.startswith("when") or " when " in lowered:
        return "date"
    if "how much" in lowered or "how many" in lowered or "how big" in lowered:
        return "amount"
    if lowered.startswith("who") or " who " in lowered:
        return "person"
    return None


def _shape_bonus(shape: str | None, content: str) -> float:
    if shape == "date" and _DATE_HINT.search(content):
        return 1.0
    if shape == "amount" and _AMOUNT_HINT.search(content):
        return 1.0
    if shape == "person" and _PERSON_HINT.search(content):
        return 1.0
    return 0.0


def _content_terms(text: str) -> set[str]:
    """The words worth matching on: no stopwords, lightly stemmed."""

    return {_stem(t) for t in _normalize(text).split() if t not in _STOPWORDS and len(t) > 1}


MERGE_THRESHOLD = 0.88


def _similarity(left: str, right: str, minimum: float = 0.0) -> float:
    """Blended token/sequence similarity, in [0, 1].

    SequenceMatcher is quadratic and dominates the cost of every write: the duplicate
    check runs it against up to 250 candidates. The token overlap is cheap and bounds
    the result, because the sequence term cannot exceed 1.0 -- so a pair whose best
    possible score falls short of `minimum` is rejected without ever building the
    matcher. Callers that want the true score leave `minimum` at zero.
    """
    if not left or not right:
        return 0.0
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    if (0.6 * jaccard) + 0.4 < minimum:
        return 0.0
    sequence = SequenceMatcher(None, left, right).ratio()
    return (0.6 * jaccard) + (0.4 * sequence)


def _display_path(path: Path) -> str:
    """Home-relative rendering of a database path, for display only."""
    try:
        return "~/" + str(path.resolve().relative_to(Path.home()))
    except ValueError:
        return str(path)


def _days_since(timestamp: str | None) -> int | None:
    """Whole days between an ISO-8601 event timestamp and now, or None if unreadable.

    Timestamps written by this module carry an explicit offset, but a store may have been
    written by an older build that stored a naive string; treat those as UTC rather than
    raising. A clock skewed backwards must not report a negative age, so clamp at zero.
    """
    if not timestamp:
        return None
    try:
        moment = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - moment).days)


def _why_protected(category: str, importance: float, source: str) -> str:
    """Say what earned this memory its protection, not merely that it has some.

    Every protected memory carried the same sentence — "High-value memory protected
    from normal cleanup" — which records that a decision happened without saying why
    this memory got it. A reason that is identical for every case explains nothing, and
    a guarantee you cannot interrogate is only a claim.
    """

    if category == "safety":
        return "Safety-relevant, so it is never dropped automatically."
    if category == "decision":
        return "This records a decision, and decisions stay until they are reversed."
    if category == "preference":
        return "A stated preference about how you want to work."
    if category == "project":
        return "Ongoing project detail that later work is likely to depend on."
    if category == "personal":
        return "Durable context about you rather than a passing remark."
    asked = "you asked for it directly" if source == "manual" else "it scored above the threshold"
    return f"Kept because {asked} (importance {importance:.2f})."


class MemoryStore:
    """Small single-user SQLite store for the private beta connector."""

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

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

    def _initialize(self) -> None:
        with self._connect() as connection:
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

    def explain(self, memory_id: str) -> dict[str, Any]:
        """Why this memory is held, and on whose decision.

        Protection was a bare boolean everywhere a user could see it. The reason existed
        — every decision is logged with one — but only in a table reachable by SQL, so
        "protected" was something the product asserted rather than something it could
        account for. A guarantee nobody can inspect is a claim.
        """

        with self._connect() as connection:
            memory = connection.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
            if memory is None:
                return {"memory_id": memory_id, "found": False}
            events = connection.execute(
                """
                SELECT decision, reason, created_at, source FROM decision_events
                WHERE memory_id = ? ORDER BY id
                """,
                (memory_id,),
            ).fetchall()

        history = [
            {
                "decision": str(row["decision"]),
                "reason": str(row["reason"]),
                "at": str(row["created_at"]),
                "source": str(row["source"]),
            }
            for row in events
        ]
        protecting = next(
            (event for event in reversed(history) if event["decision"] == "PROTECT"), None
        )
        return {
            "memory_id": memory_id,
            "found": True,
            "content": str(memory["content"]),
            "protected": bool(memory["protected"]),
            "protected_because": protecting["reason"] if protecting else None,
            "protected_since": protecting["at"] if protecting else None,
            "recall_count": int(memory["recall_count"] or 0),
            "state": str(memory["state"]),
            "history": history,
            "relations": self._relations_for(memory_id),
            "note": (
                "Age never revokes protection. A protected memory leaves active recall "
                "only when later evidence supersedes it, or when someone asks for it to "
                "be forgotten. Forget removes it from recall; it does not permanently "
                "erase the row or its history."
            ),
        }

    def _pruned_recall_count(self, connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT value FROM settings WHERE key = 'recall_events_pruned'"
        ).fetchone()
        try:
            return int(row[0]) if row else 0
        except (TypeError, ValueError):
            return 0

    def _recall_summary(self, recall_events: int, recalled_bytes: int, total: int) -> dict[str, Any]:
        """What the store actually gave back, and what it never did.

        Storing is cost; recall is the return. A memory that has never been read has
        earned nothing, and saying so plainly is more useful than a health score that
        only ever rates how tidy the shelf looks.
        """

        with self._connect() as connection:
            # Pruning trims the log, not the history. Without adding the pruned tally
            # back, the reported total silently stopped at the cap while the real number
            # kept climbing — a counter that lies once it matters most.
            recall_events += self._pruned_recall_count(connection)
            used = int(
                connection.execute(
                    "SELECT COUNT(*) FROM memories WHERE state = 'active' AND COALESCE(recall_count, 0) > 0"
                ).fetchone()[0]
            )
            top = connection.execute(
                """
                SELECT content, recall_count FROM memories
                WHERE state = 'active' AND COALESCE(recall_count, 0) > 0
                ORDER BY recall_count DESC, updated_at DESC LIMIT 3
                """
            ).fetchall()
            last = connection.execute(
                "SELECT created_at FROM decision_events WHERE decision = 'RECALL' ORDER BY id DESC LIMIT 1"
            ).fetchone()

        never_used = max(0, total - used)
        return {
            "times_memory_was_consulted": recall_events,
            "memories_ever_recalled": used,
            "memories_never_recalled": never_used,
            "content_bytes_recalled": recalled_bytes,
            "average_bytes_per_recall": (
                round(recalled_bytes / recall_events) if recall_events else 0
            ),
            "last_recall_at": str(last["created_at"]) if last else None,
            "most_used": [
                {"content": str(r["content"]), "recall_count": int(r["recall_count"])} for r in top
            ],
            "note": (
                "Recall is the benefit. Memories that are never recalled are pure cost — "
                "this is the number that says whether MemorySafe is earning its context."
            ),
        }

    def _prune_recall_events(self, connection: sqlite3.Connection, keep: int = 2000) -> None:
        """Keep the recall log from growing for ever.

        One row is written per search. Nothing removed them, so a year of ordinary use
        would leave hundreds of thousands of rows that only the health summary reads.
        The durable per-memory counter lives on the memory itself, and the running total
        is kept in settings, so pruning loses no reported number.
        """

        total = connection.execute(
            "SELECT COUNT(*) FROM decision_events WHERE decision = 'RECALL'"
        ).fetchone()[0]
        if total <= keep:
            return
        connection.execute(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES ('recall_events_pruned', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = CAST(
                CAST(settings.value AS INTEGER) + ? AS TEXT
            ), updated_at = excluded.updated_at
            """,
            (str(total - keep), _now(), total - keep),
        )
        connection.execute(
            """
            DELETE FROM decision_events
            WHERE decision = 'RECALL' AND id NOT IN (
                SELECT id FROM decision_events WHERE decision = 'RECALL'
                ORDER BY id DESC LIMIT ?
            )
            """,
            (keep,),
        )

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
            with self._connect() as source, sqlite3.connect(target) as destination:
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

        with self._connect() as connection:
            busy, written, checkpointed = connection.execute(
                "PRAGMA wal_checkpoint(TRUNCATE)"
            ).fetchone()
        return {"busy": int(busy), "pages_written": int(written), "pages_checkpointed": int(checkpointed)}

    def _record_event(
        self,
        connection: sqlite3.Connection,
        decision: str,
        memory_id: str | None,
        reason: str,
        content_bytes: int = 0,
        source: str = "manual",
    ) -> None:
        connection.execute(
            """
            INSERT INTO decision_events(
                decision, memory_id, reason, content_bytes, source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (decision, memory_id, reason, content_bytes, source, _now()),
        )

    def automatic_mode_enabled(self) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = 'automatic_mode'"
            ).fetchone()
        return bool(row and row["value"] == "enabled")

    def set_automatic_mode(self, enabled: bool) -> dict[str, Any]:
        value = "enabled" if enabled else "disabled"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO settings(key, value, updated_at)
                VALUES ('automatic_mode', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (value, _now()),
            )
        return {
            "enabled": enabled,
            "reason": (
                "Automatic mode is on for chats where MemorySafe is selected."
                if enabled
                else "Automatic mode is off. Memories are saved only after an explicit request."
            ),
        }

    def record_automatic_skip(self, reason: str, content: str = "") -> None:
        with self._connect() as connection:
            self._record_event(
                connection,
                "SKIP_AUTO",
                None,
                reason,
                len(content.encode("utf-8")),
                source="automatic",
            )

    # Importance and confidence used to be supplied by the calling model, which meant
    # the model graded its own input and the health score reported that grade — 60% of
    # a score that consequently never moved. They are derived here instead, from things
    # this process can actually observe: what kind of memory it is, whether the user
    # asked for it outright, and whether it has come up before.
    _CATEGORY_IMPORTANCE = {
        "safety": 0.95,
        "decision": 0.95,
        "preference": 0.85,
        "project": 0.85,
        "personal": 0.80,
        "task": 0.70,
        "other": 0.60,
    }

    @classmethod
    def score_memory(cls, category: str, source: str, repeated: bool = False) -> tuple[float, float]:
        """Derive (importance, confidence) from observable signals, never self-report."""

        importance = cls._CATEGORY_IMPORTANCE.get(category, 0.60)
        if repeated:
            # Saying the same thing twice is evidence of importance, and it is evidence
            # the server has and the model does not.
            importance = min(1.0, importance + 0.05)
        # An outright request is stronger evidence than a volunteered capture.
        confidence = 0.95 if source == "manual" else 0.85
        return round(importance, 2), confidence

    def remember(
        self,
        content: str,
        category: str,
        importance: float | None = None,
        confidence: float | None = None,
        source: str = "manual",
    ) -> dict[str, Any]:
        clean_content = " ".join(content.split())
        if not clean_content:
            raise ValueError("Memory content cannot be empty.")
        if len(clean_content) > 10_000:
            raise ValueError("Memory content is limited to 10,000 characters.")

        normalized = _normalize(clean_content)
        if not normalized:
            raise ValueError("Memory content must include letters or numbers.")

        content_bytes = len(clean_content.encode("utf-8"))
        timestamp = _now()
        if importance is None or confidence is None:
            derived_importance, derived_confidence = self.score_memory(category, source)
            importance = derived_importance if importance is None else importance
            confidence = derived_confidence if confidence is None else confidence
        must_protect = category in {"decision", "safety"} or importance >= 0.8

        with self._connect() as connection:
            exact = connection.execute(
                """
                SELECT * FROM memories
                WHERE state = 'active' AND normalized_content = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (normalized,),
            ).fetchone()
            if exact:
                protected = bool(exact["protected"] or must_protect)
                new_importance = max(float(exact["importance"]), importance)
                new_confidence = max(float(exact["confidence"]), confidence)
                connection.execute(
                    """
                    UPDATE memories
                    SET importance = ?, confidence = ?, protected = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (new_importance, new_confidence, int(protected), timestamp, exact["id"]),
                )
                self._record_event(
                    connection,
                    "MERGE",
                    exact["id"],
                    "Exact duplicate merged into the existing memory.",
                    content_bytes,
                    source,
                )
                return {
                    "decision": "MERGE",
                    "memory_id": exact["id"],
                    "content": exact["content"],
                    "category": exact["category"],
                    "importance": new_importance,
                    "confidence": new_confidence,
                    "protected": protected,
                    "reason": "This matched an existing memory, so MemorySafe kept one copy.",
                }

            candidates = connection.execute(
                """
                SELECT * FROM memories
                WHERE state = 'active' AND category = ?
                ORDER BY updated_at DESC LIMIT 250
                """,
                (category,),
            ).fetchall()
            # Only a merge consumes this result, so anything that cannot reach the
            # merge threshold is worth nothing and is skipped inside _similarity.
            closest = None
            closest_score = 0.0
            for row in candidates:
                score = _similarity(normalized, row["normalized_content"], minimum=MERGE_THRESHOLD)
                if score > closest_score:
                    closest, closest_score = row, score
            if closest is not None and closest_score >= MERGE_THRESHOLD:
                protected = bool(closest["protected"] or must_protect)
                new_importance = max(float(closest["importance"]), importance)
                new_confidence = max(float(closest["confidence"]), confidence)
                replacement = clean_content if len(clean_content) >= len(closest["content"]) else closest["content"]
                connection.execute(
                    """
                    UPDATE memories
                    SET content = ?, normalized_content = ?, importance = ?, confidence = ?,
                        protected = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        replacement,
                        _normalize(replacement),
                        new_importance,
                        new_confidence,
                        int(protected),
                        timestamp,
                        closest["id"],
                    ),
                )
                self._record_event(
                    connection,
                    "MERGE",
                    closest["id"],
                    f"Near duplicate merged (similarity {closest_score:.2f}).",
                    content_bytes,
                    source,
                )
                return {
                    "decision": "MERGE",
                    "memory_id": closest["id"],
                    "content": replacement,
                    "category": category,
                    "importance": new_importance,
                    "confidence": new_confidence,
                    "protected": protected,
                    "reason": "This was very similar to an existing memory, so MemorySafe merged them.",
                }

            memory_id = f"MS-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"
            decision = "PROTECT" if must_protect else "STORE"
            protection_reason = _why_protected(category, importance, source)
            reason = (
                protection_reason
                if must_protect
                else "Useful distinct memory stored."
            )
            connection.execute(
                """
                INSERT INTO memories(
                    id, content, normalized_content, category, importance, confidence,
                    protected, state, source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    memory_id,
                    clean_content,
                    normalized,
                    category,
                    importance,
                    confidence,
                    int(must_protect),
                    source,
                    timestamp,
                    timestamp,
                ),
            )
            self._record_event(
                connection,
                decision,
                memory_id,
                reason,
                content_bytes,
                source,
            )
            others = connection.execute(
                """
                SELECT * FROM memories
                WHERE state = 'active' AND id != ?
                ORDER BY updated_at DESC LIMIT 2000
                """,
                (memory_id,),
            ).fetchall()
            lifecycle = self._apply_incoming_lifecycle(
                connection,
                new_id=memory_id,
                new_content=clean_content,
                others=others,
                source=source,
                timestamp=timestamp,
            )

        result = {
            "decision": decision,
            "memory_id": memory_id,
            "content": clean_content,
            "category": category,
            "importance": importance,
            "confidence": confidence,
            "protected": must_protect,
            "reason": reason,
        }
        result.update(lifecycle)
        if lifecycle.get("replaced_memory_id"):
            result["reason"] = (
                f"{reason} Replaced {lifecycle['replaced_memory_id']}: "
                f"{lifecycle['lifecycle_reason']}"
            )
        elif lifecycle.get("conflict_id"):
            result["reason"] = (
                f"{reason} Possible conflict with an existing memory; marked for review "
                f"(conflict {lifecycle['conflict_id']})."
            )
        return result

    def find(self, query: str, limit: int, record: bool = True) -> list[dict[str, Any]]:
        query_normalized = _normalize(query)
        query_terms = _content_terms(query)
        shape = _question_shape(query)
        if query_normalized and not query_terms:
            # Nothing but stopwords: no basis to return anything.
            query_normalized = ""
        with self._connect() as connection:
            if query_terms:
                # Previously this took the top 1000 by protection, importance and
                # recency and scored only those. Past a thousand memories anything
                # ranked below the cut became permanently unfindable — still stored,
                # still counted, still "protected", and impossible to recall. Narrow by
                # the words actually being searched for instead of by rank, so the
                # candidate set can never silently exclude the answer.
                clause = " OR ".join("normalized_content LIKE ?" for _ in query_terms)
                rows = connection.execute(
                    f"SELECT * FROM memories WHERE state = 'active' AND ({clause})",
                    [f"%{term}%" for term in sorted(query_terms)],
                ).fetchall()
            else:
                # Browsing with no query: rank order is the right answer, and a cap is
                # honest because the caller asked for "recent and important".
                rows = connection.execute(
                    """
                    SELECT * FROM memories
                    WHERE state = 'active'
                    ORDER BY protected DESC, importance DESC, updated_at DESC
                    LIMIT 1000
                    """
                ).fetchall()

        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            if query_normalized:
                content_terms = _content_terms(row["normalized_content"])
                match = (
                    len(query_terms & content_terms) / len(query_terms | content_terms)
                    if (query_terms | content_terms)
                    else 0.0
                )
                # Languages without spaces — Japanese, Chinese — put a whole sentence in
                # one token, so a term never matches by equality and the memory becomes
                # storable but unfindable. Fall back to substring containment, long
                # enough not to make "cat" match "category".
                matched = set(query_terms & content_terms)
                normalized_row = str(row["normalized_content"])
                for term in query_terms - matched:
                    if len(term) >= 3 and term in normalized_row:
                        matched.add(term)
                coverage = len(matched) / len(query_terms) if query_terms else 0.0
                # Relevance has to clear the bar on its own. Importance used to be inside
                # the threshold test, and at a typical importance of 0.85 its term alone
                # (0.1 * 0.85 = 0.085) exceeded the 0.08 cut — so every stored memory was
                # returned for every query, relevant or not. Importance now only breaks
                # ties between memories that already matched.
                relevance = (0.55 * match) + (0.35 * coverage)
                if relevance < 0.12:
                    continue
                # Only a tiebreak: too small to pull an irrelevant memory over the bar,
                # big enough to separate two memories that matched equally well.
                score = (
                    relevance
                    + (0.1 * float(row["importance"]))
                    + (0.08 * _shape_bonus(shape, str(row["content"])))
                )
            else:
                score = float(row["importance"])
            scored.append((score, row))

        scored.sort(key=lambda item: (item[0], item[1]["updated_at"]), reverse=True)
        if record and scored[:limit]:
            # Recall is the benefit. Storing memories nobody ever reads back is cost with
            # no return, and until now nothing recorded whether a memory was ever used —
            # so neither the dashboard nor the user could tell the difference.
            surfaced = scored[:limit]
            recalled_bytes = sum(len(str(row["content"]).encode("utf-8")) for _, row in surfaced)
            with self._connect() as connection:
                self._record_event(
                    connection,
                    "RECALL",
                    None,
                    f"Recalled {len(surfaced)} memories for: {query.strip() or 'recent memories'}",
                    content_bytes=recalled_bytes,
                    source="recall",
                )
                connection.executemany(
                    "UPDATE memories SET recall_count = COALESCE(recall_count, 0) + 1 WHERE id = ?",
                    [(row["id"],) for _, row in surfaced],
                )
                self._prune_recall_events(connection)
        return [
            {
                "memory_id": row["id"],
                "content": row["content"],
                "category": row["category"],
                "importance": float(row["importance"]),
                "confidence": float(row["confidence"]),
                "protected": bool(row["protected"]),
                "match_score": round(score, 3),
                "updated_at": row["updated_at"],
            }
            for score, row in scored[:limit]
        ]

    def forget(self, memory_id: str) -> dict[str, Any]:
        timestamp = _now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE id = ?",
                (memory_id,),
            ).fetchone()
            if row is None:
                return {
                    "memory_id": memory_id,
                    "forgotten": False,
                    "reason": "No memory with that ID was found.",
                }
            if row["state"] == "deleted":
                return {
                    "memory_id": memory_id,
                    "forgotten": True,
                    "reason": "That memory was already forgotten.",
                }
            connection.execute(
                "UPDATE memories SET state = 'deleted', deleted_at = ?, updated_at = ? WHERE id = ?",
                (timestamp, timestamp, memory_id),
            )
            self._record_event(
                connection,
                "FORGET",
                memory_id,
                "User requested that this memory be forgotten.",
            )
            # A conflict is a question about two memories. Once one of them has left
            # recall the question cannot be answered and cannot be acted on, but it
            # stayed 'open' forever and kept counting against the review queue --
            # pointing at rows the user can no longer see in normal recall.
            closed = connection.execute(
                """
                UPDATE memory_relations
                SET status = 'closed',
                    resolved_at = ?,
                    reason = reason || ' Closed automatically: one side was forgotten.'
                WHERE status = 'open'
                  AND (old_memory_id = ? OR new_memory_id = ?)
                """,
                (timestamp, memory_id, memory_id),
            ).rowcount
        return {
            "memory_id": memory_id,
            "forgotten": True,
            "conflicts_closed": int(closed or 0),
            "reason": (
                "The memory was removed from active recall. It was not permanently erased; "
                "its content and decision history remain inspectable."
            ),
        }

    def _apply_incoming_lifecycle(
        self,
        connection: sqlite3.Connection,
        *,
        new_id: str,
        new_content: str,
        others: list[sqlite3.Row],
        source: str,
        timestamp: str,
    ) -> dict[str, Any]:
        empty = {
            "lifecycle": "none",
            "replaced_memory_id": None,
            "conflict_id": None,
            "lifecycle_reason": None,
        }
        verdict = consider_incoming(new_content, others)
        if verdict is None:
            return empty
        old = verdict["old"]
        old_id = str(old["id"])
        if verdict["action"] == "contradict":
            connection.execute(
                "UPDATE memories SET state = 'superseded', updated_at = ? WHERE id = ?",
                (timestamp, old_id),
            )
            relation_id = record_relation(
                connection,
                old_memory_id=old_id,
                new_memory_id=new_id,
                decision="SUPERSEDE",
                status="resolved",
                reason=verdict["reason"],
                evidence=verdict["evidence"],
                confidence=verdict["confidence"],
                source=source,
                created_at=timestamp,
            )
            self._record_event(
                connection,
                "SUPERSEDE",
                old_id,
                f"{verdict['reason']} Evidence: {verdict['evidence']}. Replaced by {new_id}.",
                source=source,
            )
            return {
                "lifecycle": "superseded_previous",
                "replaced_memory_id": old_id,
                "conflict_id": relation_id,
                "lifecycle_reason": verdict["reason"],
            }
        relation_id = record_relation(
            connection,
            old_memory_id=old_id,
            new_memory_id=new_id,
            decision="REVIEW",
            status="open",
            reason=verdict["reason"],
            evidence=verdict["evidence"],
            confidence=verdict["confidence"],
            source=source,
            created_at=timestamp,
        )
        self._record_event(
            connection,
            "REVIEW",
            old_id,
            f"{verdict['reason']} Evidence: {verdict['evidence']}. New memory {new_id}.",
            source=source,
        )
        return {
            "lifecycle": "needs_review",
            "replaced_memory_id": None,
            "conflict_id": relation_id,
            "lifecycle_reason": verdict["reason"],
        }

    def _relations_for(self, memory_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM memory_relations
                WHERE old_memory_id = ? OR new_memory_id = ?
                ORDER BY id
                """,
                (memory_id, memory_id),
            ).fetchall()
        return [
            {
                "conflict_id": int(row["id"]),
                "old_memory_id": str(row["old_memory_id"]),
                "new_memory_id": str(row["new_memory_id"]),
                "decision": str(row["decision"]),
                "status": str(row["status"]),
                "reason": str(row["reason"]),
                "evidence": str(row["evidence"]),
                "confidence": float(row["confidence"]),
                "source": str(row["source"]),
                "created_at": str(row["created_at"]),
                "resolved_at": row["resolved_at"],
            }
            for row in rows
        ]

    def inspect_memory(self, memory_id: str) -> dict[str, Any]:
        """Any state: active, superseded, or forgotten. Not limited to recall."""
        return self.explain(memory_id)

    def review_conflicts(self, include_resolved: bool = False) -> dict[str, Any]:
        with self._connect() as connection:
            if include_resolved:
                rows = connection.execute(
                    "SELECT * FROM memory_relations ORDER BY id DESC LIMIT 50"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM memory_relations WHERE status = 'open' ORDER BY id DESC"
                ).fetchall()
            items = []
            for row in rows:
                old = connection.execute(
                    "SELECT id, content, state, protected FROM memories WHERE id = ?",
                    (row["old_memory_id"],),
                ).fetchone()
                new = connection.execute(
                    "SELECT id, content, state, protected FROM memories WHERE id = ?",
                    (row["new_memory_id"],),
                ).fetchone()
                items.append(
                    {
                        "conflict_id": int(row["id"]),
                        "decision": str(row["decision"]),
                        "status": str(row["status"]),
                        "reason": str(row["reason"]),
                        "evidence": str(row["evidence"]),
                        "confidence": float(row["confidence"]),
                        "source": str(row["source"]),
                        "created_at": str(row["created_at"]),
                        "old": None
                        if old is None
                        else {
                            "memory_id": str(old["id"]),
                            "content": str(old["content"]),
                            "state": str(old["state"]),
                            "protected": bool(old["protected"]),
                        },
                        "new": None
                        if new is None
                        else {
                            "memory_id": str(new["id"]),
                            "content": str(new["content"]),
                            "state": str(new["state"]),
                            "protected": bool(new["protected"]),
                        },
                    }
                )
        return {"count": len(items), "conflicts": items}

    def resolve_conflict(
        self, conflict_id: int, action: str, confirm: bool = False
    ) -> dict[str, Any]:
        """action: supersede | keep_both | restore. Destructive actions need confirm=True."""

        action = action.strip().lower()
        if action not in {"supersede", "keep_both", "restore"}:
            return {
                "resolved": False,
                "reason": "Action must be supersede, keep_both, or restore.",
            }
        if not confirm:
            return {
                "resolved": False,
                "needs_confirmation": True,
                "reason": (
                    "Nothing was changed. Call again with confirm=true after the user "
                    "agrees. supersede removes the older memory from recall; restore "
                    "puts a superseded memory back; keep_both leaves both active."
                ),
            }
        timestamp = _now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM memory_relations WHERE id = ?", (conflict_id,)
            ).fetchone()
            if row is None:
                return {"resolved": False, "reason": "No conflict with that ID was found."}
            old_id = str(row["old_memory_id"])
            new_id = str(row["new_memory_id"])
            if action == "supersede":
                connection.execute(
                    "UPDATE memories SET state = 'superseded', updated_at = ? WHERE id = ?",
                    (timestamp, old_id),
                )
                connection.execute(
                    """
                    UPDATE memory_relations
                    SET decision = 'SUPERSEDE', status = 'resolved', resolved_at = ?
                    WHERE id = ?
                    """,
                    (timestamp, conflict_id),
                )
                self._record_event(
                    connection,
                    "SUPERSEDE",
                    old_id,
                    f"User confirmed supersession. Replaced by {new_id}.",
                )
                return {
                    "resolved": True,
                    "action": "supersede",
                    "old_memory_id": old_id,
                    "new_memory_id": new_id,
                    "reason": "The older memory was removed from active recall and kept for inspection.",
                }
            if action == "keep_both":
                # Only un-supersede. Forgetting is a direct instruction from the user and
                # resolving an unrelated-looking conflict must never quietly undo it --
                # this revived two deleted memories, left their deleted_at set, and put
                # them back into recall without anyone asking. memorysafe_restore is the
                # explicit, confirmed path back from forgotten.
                connection.execute(
                    """
                    UPDATE memories SET state = 'active', updated_at = ?
                    WHERE id IN (?, ?) AND state = 'superseded'
                    """,
                    (timestamp, old_id, new_id),
                )
                connection.execute(
                    """
                    UPDATE memory_relations
                    SET decision = 'KEEP_BOTH', status = 'resolved', resolved_at = ?
                    WHERE id = ?
                    """,
                    (timestamp, conflict_id),
                )
                self._record_event(
                    connection,
                    "KEEP_BOTH",
                    old_id,
                    f"User kept both memories active. Other id {new_id}.",
                )
                return {
                    "resolved": True,
                    "action": "keep_both",
                    "old_memory_id": old_id,
                    "new_memory_id": new_id,
                    "reason": "Both memories remain in active recall.",
                }
            # Same guard as keep_both: this restores a memory that was superseded by
            # the conflict, never one the user chose to forget.
            connection.execute(
                """
                UPDATE memories SET state = 'active', updated_at = ?
                WHERE id = ? AND state = 'superseded'
                """,
                (timestamp, old_id),
            )
            connection.execute(
                """
                UPDATE memory_relations
                SET decision = 'RESTORE', status = 'restored', resolved_at = ?
                WHERE id = ?
                """,
                (timestamp, conflict_id),
            )
            self._record_event(
                connection,
                "RESTORE",
                old_id,
                f"User restored this memory to active recall. It had been replaced by {new_id}.",
            )
        return {
            "resolved": True,
            "action": "restore",
            "old_memory_id": old_id,
            "new_memory_id": new_id,
            "reason": "The older memory is back in active recall.",
        }

    def restore(self, memory_id: str, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            return {
                "restored": False,
                "needs_confirmation": True,
                "memory_id": memory_id,
                "reason": "Nothing was changed. Call again with confirm=true after the user agrees.",
            }
        timestamp = _now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
            if row is None:
                return {
                    "restored": False,
                    "memory_id": memory_id,
                    "reason": "No memory with that ID was found.",
                }
            if row["state"] == "active":
                return {
                    "restored": True,
                    "memory_id": memory_id,
                    "reason": "That memory is already in active recall.",
                }
            connection.execute(
                "UPDATE memories SET state = 'active', deleted_at = NULL, updated_at = ? WHERE id = ?",
                (timestamp, memory_id),
            )
            connection.execute(
                """
                UPDATE memory_relations
                SET decision = 'RESTORE', status = 'restored', resolved_at = ?
                WHERE old_memory_id = ? AND status IN ('open', 'resolved')
                """,
                (timestamp, memory_id),
            )
            self._record_event(
                connection,
                "RESTORE",
                memory_id,
                "User restored this memory to active recall.",
            )
        return {
            "restored": True,
            "memory_id": memory_id,
            "reason": "The memory is back in active recall.",
        }

    def health(self) -> dict[str, Any]:
        with self._connect() as connection:
            memories = connection.execute(
                "SELECT * FROM memories WHERE state = 'active'"
            ).fetchall()
            events = connection.execute(
                """
                SELECT decision, source, COUNT(*) AS count, SUM(content_bytes) AS bytes
                FROM decision_events
                GROUP BY decision, source
                """
            ).fetchall()
            last_automatic_event = connection.execute(
                """
                SELECT decision, reason, created_at
                FROM decision_events
                WHERE source = 'automatic'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            # Liveness is tracked separately from the health score on purpose. Every term
            # in the score measures the quality of what is already stored, so a store that
            # has stopped receiving anything keeps its score -- or improves it, since a
            # small tidy set scores well. Nothing in the score can fall when capture dies,
            # which is exactly when the user most needs to be told.
            last_capture_event = connection.execute(
                """
                SELECT created_at
                FROM decision_events
                WHERE decision IN ('STORE', 'PROTECT', 'MERGE')
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            superseded_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM memories WHERE state = 'superseded'"
                ).fetchone()[0]
            )
            open_reviews = int(
                connection.execute(
                    "SELECT COUNT(*) FROM memory_relations WHERE status = 'open'"
                ).fetchone()[0]
            )
            # The governance trail. Every number above this line -- counts, recall,
            # tokens -- is something any memory product can show. This is the part
            # that is only true of MemorySafe: a fact replaced by a later one, the
            # evidence for it written down, and a human able to reverse it. It was
            # being computed and shown nowhere.
            governance_rows = connection.execute(
                """
                SELECT r.id, r.decision, r.status, r.reason, r.evidence, r.created_at,
                       o.content AS old_content, n.content AS new_content
                FROM memory_relations r
                LEFT JOIN memories o ON o.id = r.old_memory_id
                LEFT JOIN memories n ON n.id = r.new_memory_id
                -- A conflict where both sides have been forgotten is not a live
                -- governance decision, it is litter from a deleted pair.
                WHERE o.state != 'deleted' OR n.state != 'deleted'
                ORDER BY r.id DESC
                LIMIT 8
                """
            ).fetchall()

        total = len(memories)
        protected = sum(bool(row["protected"]) for row in memories)
        active_bytes = sum(len(row["content"].encode("utf-8")) for row in memories)
        average_importance = (
            sum(float(row["importance"]) for row in memories) / total if total else 0.0
        )
        average_confidence = (
            sum(float(row["confidence"]) for row in memories) / total if total else 0.0
        )
        high_value = [row for row in memories if float(row["importance"]) >= 0.8]
        protected_high_value = sum(bool(row["protected"]) for row in high_value)
        protection_coverage = protected_high_value / len(high_value) if high_value else 1.0
        normalized_counts = Counter(row["normalized_content"] for row in memories)
        duplicates = sum(count - 1 for count in normalized_counts.values() if count > 1)
        duplicate_cleanliness = 1 - (duplicates / total) if total else 1.0
        quality = (average_importance + average_confidence) / 2 if total else 1.0
        health_score = round(
            100 * ((0.6 * quality) + (0.3 * protection_coverage) + (0.1 * duplicate_cleanliness))
        )

        decisions: Counter[str] = Counter()
        recall_events = 0
        recalled_bytes = 0
        for row in events:
            if row["decision"] == "RECALL":
                # Recall is not a governance decision and does not belong beside
                # STORE/PROTECT/FORGET; counting it there would inflate the governance
                # story with reads.
                recall_events += int(row["count"])
                recalled_bytes += int(row["bytes"] or 0)
                continue
            decisions[row["decision"]] += int(row["count"])
        raw_attempts = sum(decisions.get(name, 0) for name in ("STORE", "PROTECT", "MERGE"))
        # A MERGE is the only event that proves an incoming remember request was
        # consolidated instead of creating another active copy. Comparing all-time
        # attempts with the current active count also counted forgotten/superseded
        # memories as duplicates, which overstated what deduplication accomplished.
        saved_count = decisions.get("MERGE", 0)
        saved_bytes = sum(
            int(row["bytes"] or 0) for row in events if row["decision"] == "MERGE"
        )
        automatic_captures = sum(
            int(row["count"])
            for row in events
            if row["source"] == "automatic"
            and row["decision"] in {"STORE", "PROTECT", "MERGE"}
        )
        automatic_skips = sum(
            int(row["count"])
            for row in events
            if row["source"] == "automatic" and row["decision"] == "SKIP_AUTO"
        )
        automatic_mode = self.automatic_mode_enabled()
        automatic_evaluated = automatic_captures + automatic_skips
        if not automatic_mode:
            automatic_status = "Automatic capture is off. Nothing is saved without an explicit request."
        elif automatic_evaluated == 0:
            automatic_status = (
                "Automatic capture is on, but no candidate has reached MemorySafe yet. "
                "Select MemorySafe in the chat where you want automatic capture."
            )
        else:
            automatic_status = (
                f"Automatic capture is on and has evaluated {automatic_evaluated} "
                f"candidate{'s' if automatic_evaluated != 1 else ''}."
            )

        last_capture_at = str(last_capture_event["created_at"]) if last_capture_event else None
        days_since_last_capture = _days_since(last_capture_at)
        if last_capture_at is None:
            capture_freshness = "never"
            capture_status = "Nothing has ever been captured. MemorySafe is empty, not healthy."
        elif days_since_last_capture is None:
            capture_freshness = "unknown"
            capture_status = f"Last capture timestamp could not be read ({last_capture_at})."
        elif days_since_last_capture >= 7:
            capture_freshness = "stale"
            capture_status = (
                f"No memory captured in {days_since_last_capture} days. "
                "Capture only runs when the assistant calls it, so silence usually means "
                "nothing is asking MemorySafe to remember -- not that it refused."
            )
        elif days_since_last_capture >= 2:
            capture_freshness = "quiet"
            capture_status = f"Last capture was {days_since_last_capture} days ago."
        else:
            capture_freshness = "active"
            capture_status = (
                "Captured today."
                if days_since_last_capture == 0
                else "Last capture was yesterday."
            )

        # Open conflicts are the one governance number the score cannot express. The
        # formula rates the quality of what is stored; an unresolved conflict is a
        # question nobody has answered yet, and it can sit open indefinitely while the
        # score stays at 92. Say so in words, the way capture_freshness does.
        if open_reviews == 0:
            governance_status = "No conflicts are waiting for a decision."
        elif open_reviews == 1:
            governance_status = (
                "1 conflict is open and waiting for a decision. Until it is resolved both "
                "memories stay in recall, so a superseded fact can still be returned."
            )
        else:
            governance_status = (
                f"{open_reviews} conflicts are open and waiting for a decision. Until they "
                "are resolved both sides stay in recall, so superseded facts can still be "
                "returned. Call memorysafe_review_conflicts to see them."
            )

        ranked_memories = sorted(
            memories,
            key=lambda row: (
                bool(row["protected"]),
                float(row["importance"]),
                row["updated_at"],
            ),
            reverse=True,
        )
        active_memory_tokens = sum(count_text_tokens(row["content"]) for row in memories)
        top_context_tokens = sum(
            count_text_tokens(row["content"]) for row in ranked_memories[:6]
        )
        tokenization = tokenizer_metadata()

        try:
            # WAL mode keeps recent commits in a sidecar file. Measuring only the main
            # database under-reports the store several times over once the WAL grows,
            # and it is the same oversight that makes a naive file copy lose memories.
            database_bytes = sum(
                path.stat().st_size
                for path in (
                    self.database_path,
                    self.database_path.with_name(self.database_path.name + "-wal"),
                    self.database_path.with_name(self.database_path.name + "-shm"),
                )
                if path.exists()
            )
        except FileNotFoundError:
            database_bytes = 0

        # Break-even depends on how big this user's memories actually are, so use the
        # observed average rather than a stored assumption. A store of one-line
        # preferences pays off at a different point than one full of meeting notes.
        live_average = round(active_memory_tokens / total) if total else 0

        return {
            "memory_health": health_score,
            "active_memories": total,
            "superseded_memories": superseded_count,
            "open_reviews": open_reviews,
            "protected_memories": protected,
            "average_importance": round(average_importance, 3),
            "average_confidence": round(average_confidence, 3),
            "active_content_bytes": active_bytes,
            "database_bytes": database_bytes,
            "decision_counts": dict(decisions),
            "recall": self._recall_summary(recall_events, recalled_bytes, total),
            "automatic_mode": automatic_mode,
            "automatic_captures": automatic_captures,
            "automatic_skips": automatic_skips,
            "automatic_candidates_evaluated": automatic_evaluated,
            "automatic_status": automatic_status,
            "automatic_last_event_at": (
                str(last_automatic_event["created_at"]) if last_automatic_event else None
            ),
            "automatic_last_decision": (
                str(last_automatic_event["decision"]) if last_automatic_event else None
            ),
            "automatic_last_reason": (
                str(last_automatic_event["reason"]) if last_automatic_event else None
            ),
            "comparison": {
                "raw_remember_requests": raw_attempts,
                "memories_with_memorysafe": total,
                "duplicate_copies_avoided": saved_count,
                "content_bytes_avoided": saved_bytes,
                "note": "Duplicate avoidance counts confirmed MERGE decisions only. Task quality and retrieval speed are not claimed until measured by an evaluation.",
            },
            "live_token_metrics": {
                "kind": "live_local",
                "tokenizer": tokenization["tokenizer"],
                "exact": tokenization["exact"],
                "active_memory_tokens": active_memory_tokens,
                "top_context_tokens": top_context_tokens,
                "average_memory_tokens": round(active_memory_tokens / total) if total else 0,
                "counted_memories": total,
                "chatgpt_live_usage_available": False,
                "note": f"{tokenization['note']} These are not ChatGPT billed-token totals.",
            },
            "token_benchmark": token_benchmark(
                live_average or AVERAGE_FACT_TOKENS,
                facts_stored=total,
            ),
            "last_capture_at": last_capture_at,
            "days_since_last_capture": days_since_last_capture,
            "capture_freshness": capture_freshness,
            "capture_status": capture_status,
            "governance_status": governance_status,
            "governance_events": [
                {
                    "conflict_id": int(row["id"]),
                    "decision": str(row["decision"]),
                    "status": str(row["status"]),
                    "reason": str(row["reason"] or ""),
                    "evidence": str(row["evidence"] or ""),
                    "created_at": str(row["created_at"] or ""),
                    "replaced": str(row["old_content"] or ""),
                    "kept": str(row["new_content"] or ""),
                }
                for row in governance_rows
            ],
            "formula": "60% average importance/confidence + 30% protection of high-value memories + 10% duplicate cleanliness.",
            "formula_note": (
                "The score rates the quality of what is stored. It deliberately says nothing "
                "about whether anything is still arriving -- read capture_freshness for that."
            ),
            # An empty store is ambiguous unless you can see which database is being read.
            # Shown home-relative so the path is legible without exposing the account name.
            "database_path": _display_path(self.database_path),
        }
