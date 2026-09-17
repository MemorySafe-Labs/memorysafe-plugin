"""Evidence-based memory lifecycle for the Agent beta connector.

This module is not the research continual-learning stack. It does not implement
MVI, ProtectScore, hard-quota eviction, age decay, embeddings, or any network
call. It only answers: should a new fact replace an existing active memory?

States used by the store:

- active      in normal recall
- superseded  removed from recall because a later memory replaced it
- deleted     removed from recall because the user asked to forget it

Forget is a soft deletion. Nothing here permanently erases a row.
"""

from __future__ import annotations

from functools import lru_cache
import re
from typing import Any


def _text():
    # Imported lazily: storage.remember() calls this module, so a top-level
    # import of storage here would be a cycle.
    from . import storage as _storage

    return _storage._content_terms, _storage._normalize, _storage._similarity


# Near-duplicates at or above this score are merged by storage.remember, not
# classified here. Kept in one place so tests can name the boundary.
MERGE_SIMILARITY = 0.88

_GENERIC_SUBJECTS = frozenset(
    """
    deadline due date dates close closes closing submission submit
    live lives living prefer prefers preferred preference work works working
    office address fact memory item note
    """.split()
)

_REPLACEMENT_LANGUAGE = re.compile(
    r"\b(?:no longer|not anymore|instead(?: of)?|changed (?:to|from)|"
    r"moved to|updated to|used to|now (?:live|lives|work|works|prefer)|"
    # A memory that says outright that it replaces something is the strongest
    # evidence this module can get, and none of it was recognised: "0.3.5 was
    # installed, replacing 0.3.4" sat open as an ambiguous review for six days.
    r"replac(?:es|ing)|replaced by|supersed(?:es|ing)|superseded by|"
    r"in place of|upgraded (?:to|from)|downgraded to|"
    r"rolled back to|switched (?:to|from)|renamed to|now called)\b",
    re.IGNORECASE,
)

# Version numbers are invisible to the text matcher: _normalize splits on
# non-word characters, so "0.3.4" becomes "0 3 4" and every piece is then
# dropped for being a single character. Two memories about different releases
# of the same product therefore share no distinctive term at all and score as
# faintly related prose. Read the version out of the raw text instead, and
# keep the raw string as the slot value so it is never folded away.
#
# Two dots are required, or an explicit v/version/release marker, so that
# ordinary decimals in a sentence ("similarity 0.87", "p=0.488") are not
# mistaken for releases.
_VERSION = re.compile(
    r"(?P<subject>[A-Za-z][\w\- ]{0,40}?)\s+"
    r"(?:(?P<triple>\d+\.\d+\.\d+(?:\.\d+)*)"
    r"|(?:v|version|release)\s*(?P<marked>\d+\.\d+(?:\.\d+)*))\b",
    re.IGNORECASE,
)

_LIVES_IN = re.compile(r"\bliv(?:e|es|ing)\s+in\s+(.+)$", re.IGNORECASE)
_WORKS_AT = re.compile(r"\bworks?\s+(?:at|for)\s+(.+)$", re.IGNORECASE)
_WORKS_AS = re.compile(r"\bworks?\s+as\s+(.+)$", re.IGNORECASE)
_PREFERS = re.compile(r"\bprefers?\s+(.+)$", re.IGNORECASE)
_IS_ROLE = re.compile(
    r"^(.+?)\s+(?:is|are)\s+(?:an?\s+|the\s+)?(.+)$",
    re.IGNORECASE,
)
# A title is a short noun phrase -- "Head of Operations", "strategic advisor".
# _IS_ROLE matches any "X is Y" sentence, so "Carla is satisfied that ..." and
# "Carla is recording ..." were read as two competing job titles for the same
# person and one silently superseded the other at confidence 0.86. Everything
# below exists to keep a clause from being mistaken for a title.
_MAX_TITLE_WORDS = 5
_CLAUSE_MARKERS = frozenset("that because when while since so if whether although".split())
# States and opinions, not roles. "Carla is satisfied with X" is not a job.
_STATE_WORDS = frozenset(
    """
    satisfied happy unhappy pleased worried concerned aware sure unsure confident
    frustrated keen ready willing able unable interested excited disappointed
    convinced certain uncertain comfortable uncomfortable available busy
    """.split()
)


def _looks_like_a_title(value: str) -> bool:
    words = value.split()
    if not words or len(words) > _MAX_TITLE_WORDS:
        return False
    if words[0] in _STATE_WORDS:
        return False
    # "is recording", "is building" -- an activity in progress, not a role.
    if words[0].endswith("ing") and len(words[0]) > 4:
        return False
    return not any(word in _CLAUSE_MARKERS for word in words)


_DEADLINE = re.compile(
    r"^(?P<subject>.+?)\s+(?:deadline|due(?: date)?|closes?|submission)\b.*?"
    r"(?P<value>\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    r"[a-z]*\s+20\d{2}|20\d{2}-\d{2}-\d{2}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:,\s*)?20\d{2}|"
    r"\d{1,2}/\d{1,2}/20\d{2})",
    re.IGNORECASE,
)
_BARE_DEADLINE = re.compile(
    r"^\s*deadlines?\s+(?:is|are|of)\s+(.+)$",
    re.IGNORECASE,
)
_VALUE_TOKEN = re.compile(
    r"\b\d+(?:[.,]\d+)?%?\b|[$€£]\s?\d|"
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b",
    re.IGNORECASE,
)


def _norm_slot(text: str) -> str:
    _, normalize, _ = _text()
    return normalize(text.strip().rstrip("."))


@lru_cache(maxsize=4096)
def extract_slots(content: str) -> tuple[tuple[str, str, str], ...]:
    """Return (kind, subject, value) slots. Empty subject means the clause is generic."""

    clean = " ".join(content.split())
    slots: list[tuple[str, str, str]] = []

    def add(kind: str, subject: str, value: str) -> None:
        value_n = _norm_slot(value)
        if not value_n:
            return
        slots.append((kind, _norm_slot(subject), value_n))

    def add_raw(kind: str, subject: str, value: str) -> None:
        """Store the value exactly as written. Normalising a version number
        destroys it -- "0.3.4" and "0.3.5" both fold to near-identical digit
        strings that then score as an elaboration of one another."""
        if not value.strip():
            return
        slots.append((kind, _norm_slot(subject), value.strip()))

    if match := _LIVES_IN.search(clean):
        add("lives_in", "", match.group(1))
    if match := _WORKS_AT.search(clean):
        add("works_at", "", match.group(1))
    if match := _WORKS_AS.search(clean):
        add("works_as", "", match.group(1))
    if match := _PREFERS.search(clean):
        add("prefers", "", match.group(1))
    if match := _DEADLINE.search(clean):
        add("deadline", match.group("subject"), match.group("value"))
    elif match := _BARE_DEADLINE.search(clean):
        add("deadline", "", match.group(1))
    if match := _VERSION.search(clean):
        add_raw("version", match.group("subject"), match.group("triple") or match.group("marked"))
    if match := _IS_ROLE.match(clean):
        subject, value = match.group(1), match.group(2)
        subject_n = _norm_slot(subject)
        if (
            len(subject_n.split()) <= 6
            and subject_n not in _GENERIC_SUBJECTS
            and not any(token in _GENERIC_SUBJECTS for token in subject_n.split())
            and _looks_like_a_title(_norm_slot(value))
        ):
            add("titled", subject, value)
    return tuple(slots)


@lru_cache(maxsize=4096)
def _distinctive_terms(content: str) -> frozenset[str]:
    content_terms, _, _ = _text()
    return frozenset(term for term in content_terms(content) if term not in _GENERIC_SUBJECTS)


def classify_pair(new_content: str, old_content: str) -> dict[str, Any]:
    """Compare one new fact to one existing memory.

    Returns action: unrelated | duplicate | contradict | review
    Age is never consulted.
    """

    _, normalize, similarity_fn = _text()
    new_norm = normalize(new_content)
    old_norm = normalize(old_content)
    similarity = similarity_fn(new_norm, old_norm)
    if similarity >= MERGE_SIMILARITY:
        return {
            "action": "duplicate",
            "reason": "Near-duplicate of an existing memory.",
            "evidence": f"similarity {similarity:.2f}",
            "confidence": round(similarity, 3),
        }

    new_slots = extract_slots(new_content)
    old_slots = extract_slots(old_content)
    new_kinds = {slot[0] for slot in new_slots}
    replacement = bool(_REPLACEMENT_LANGUAGE.search(new_content))
    new_terms = _distinctive_terms(new_content)
    old_terms = _distinctive_terms(old_content)
    overlap = new_terms & old_terms
    union = new_terms | old_terms
    subject_jaccard = (len(overlap) / len(union)) if union else 0.0

    conflicting: list[str] = []
    version_mismatch: list[str] = []
    for kind, subject, value in new_slots:
        for old_kind, old_subject, old_value in old_slots:
            if kind != old_kind or value == old_value:
                continue
            if kind == "version":
                # Versions are exact identifiers, so the elaboration guard below
                # must not apply: 0.3.4 and 0.3.5 differ by one character and
                # score as near-identical, yet they name different builds.
                if similarity_fn(subject, old_subject) < 0.55:
                    continue
                version_mismatch.append(f"version: '{old_value}' vs '{value}'")
                continue
            if similarity_fn(value, old_value) >= 0.62:
                # Elaboration of the same value, not a replacement.
                continue
            if kind == "deadline":
                # A date without a shared project/entity is not enough to replace.
                if not subject or not old_subject:
                    continue
                subj_sim = similarity_fn(subject, old_subject)
                if subj_sim < 0.55:
                    continue
            elif kind == "titled":
                if similarity_fn(subject, old_subject) < 0.55:
                    continue
            conflicting.append(
                f"{kind}: '{old_value}' vs '{value}'"
            )

    if conflicting:
        evidence = "; ".join(conflicting)
        return {
            "action": "contradict",
            "reason": "A later fact states a different value for the same slot.",
            "evidence": evidence,
            "confidence": 0.86,
        }

    if version_mismatch and replacement:
        return {
            "action": "contradict",
            "reason": "A later fact names a different version of the same thing and says it replaces the old one.",
            "evidence": "; ".join(version_mismatch),
            "confidence": 0.9,
        }

    if version_mismatch:
        # A bare version bump is good evidence but not proof: the same product at
        # two versions can legitimately be installed on two machines. Say exactly
        # what was seen instead of falling through to "share a subject".
        return {
            "action": "review",
            "reason": "Two versions of the same thing are both active, and the newer memory does not say it replaces the older.",
            "evidence": "; ".join(version_mismatch),
            "confidence": 0.5,
        }

    if replacement and overlap:
        return {
            "action": "review",
            "reason": "Replacement language is present but the conflicting value is not explicit.",
            "evidence": f"shared terms {sorted(overlap)[:8]}; similarity {similarity:.2f}",
            "confidence": 0.45,
        }

    # Same generic frame (two bare deadlines, two untitled roles) with
    # different values and no shared entity: do not auto-supersede.
    if new_kinds and new_kinds == {slot[0] for slot in old_slots}:
        new_values = {slot[2] for slot in new_slots}
        old_values = {slot[2] for slot in old_slots}
        if new_values != old_values and subject_jaccard < 0.55:
            new_subjects = {slot[1] for slot in new_slots if slot[1]}
            old_subjects = {slot[1] for slot in old_slots if slot[1]}
            if new_subjects and old_subjects:
                return {
                    "action": "unrelated",
                    "reason": "Same kind of fact, but the named subjects are different.",
                    "evidence": f"subjects {sorted(new_subjects)} vs {sorted(old_subjects)}",
                    "confidence": round(similarity, 3),
                }
            return {
                "action": "review",
                "reason": "Same kind of fact, different value, but the subject is not clearly the same.",
                "evidence": f"kinds {sorted(new_kinds)}; similarity {similarity:.2f}",
                "confidence": 0.4,
            }

    if len(overlap) >= 2 and 0.28 <= similarity < MERGE_SIMILARITY:
        return {
            "action": "review",
            "reason": "These memories share a subject but do not clearly contradict.",
            "evidence": f"shared terms {sorted(overlap)[:8]}; similarity {similarity:.2f}",
            "confidence": 0.4,
        }

    return {
        "action": "unrelated",
        "reason": "No shared slot or distinctive subject.",
        "evidence": f"similarity {similarity:.2f}",
        "confidence": round(similarity, 3),
    }


def consider_incoming(new_content: str, existing: list[Any]) -> dict[str, Any] | None:
    """Pick at most one existing active memory to supersede or mark for review."""

    contradict: dict[str, Any] | None = None
    review: dict[str, Any] | None = None
    for row in existing:
        verdict = classify_pair(new_content, str(row["content"]))
        verdict["old"] = row
        if verdict["action"] == "contradict":
            if contradict is None or verdict["confidence"] > contradict["confidence"]:
                contradict = verdict
        elif verdict["action"] == "review":
            if review is None or verdict["confidence"] > review["confidence"]:
                review = verdict
    return contradict or review


def record_relation(
    connection: Any,
    *,
    old_memory_id: str,
    new_memory_id: str,
    decision: str,
    status: str,
    reason: str,
    evidence: str,
    confidence: float,
    source: str,
    created_at: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO memory_relations(
            old_memory_id, new_memory_id, decision, status,
            reason, evidence, confidence, source, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            old_memory_id,
            new_memory_id,
            decision,
            status,
            reason,
            evidence,
            confidence,
            source,
            created_at,
        ),
    )
    return int(cursor.lastrowid)
