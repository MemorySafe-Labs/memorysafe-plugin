"""Evidence-based memory lifecycle for the Agent beta connector.

This module is not the research continual-learning stack. It does not implement
MVI, ProtectScore, age decay, embeddings, or any network call. It only answers:
should a new fact replace an existing active memory? (The optional capacity bound,
MEMORYSAFE_MAX_ACTIVE, lives in storage.py and is off unless configured.)

States used by the store:

- active      in normal recall
- superseded  removed from recall because a later memory replaced it
- deleted     removed from recall because the user asked to forget it
- evicted     removed from recall by the optional capacity bound (never protected ones)
- rejected    a newer update the user reverted as wrong

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
    r"rolled back to|switched (?:to|from)|renamed to|now called|"
    # "We switched the backend database from Postgres to MySQL" and "the standup
    # moved to 10am" were only ever flagged for review: the verb and its
    # preposition were not adjacent, and a bare "now" was not recognised at all.
    r"switched\b[\w\s]{0,40}?\b(?:to|from)|moved\b[\w\s]{0,40}?\bto|"
    r"changed\b[\w\s]{0,40}?\bto|rescheduled|postponed|pushed (?:back )?to|now)\b",
    re.IGNORECASE,
)

# Words that announce a change. They say *that* something changed, not *what* it is
# about, so they are left out when two memories' subjects are compared.
_CHANGE_WORDS = frozenset(
    """
    now moved move moves switched switch switches changed change changes updated update
    replaced replacing replace replaces instead upgraded upgrade downgraded rescheduled
    postponed pushed new no longer from to anymore was were became become has have
    """.split()
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

_LIVES_IN = re.compile(r"^(?P<subject>.*?)\bliv(?:e|es|ing)\s+in\s+(?P<value>.+)$", re.IGNORECASE)
# "Dana moved to Toronto" is a change of residence. "The standup moved to 10am" is
# not, so a destination containing a digit is left to the value comparison below.
_MOVED_TO = re.compile(
    r"^(?P<subject>.*?)\b(?:has\s+)?(?:moved|relocated)\s+to\s+(?P<value>[^\d]+?)\.?$",
    re.IGNORECASE,
)
_WORKS_AT = re.compile(r"\bworks?\s+(?:at|for)\s+(.+)$", re.IGNORECASE)
_WORKS_AS = re.compile(r"\bworks?\s+as\s+(.+)$", re.IGNORECASE)
_PREFERS = re.compile(r"\bprefers?\s+(.+)$", re.IGNORECASE)
_IS_ROLE = re.compile(
    r"^(.+?)\s+(?:is|are)\s+(?:an?\s+|the\s+)?(.+)$",
    re.IGNORECASE,
)
# A title is a short noun phrase -- "Head of Operations", "strategic advisor".
# _IS_ROLE matches any "X is Y" sentence, so "she is satisfied that ..." and
# "she is recording ..." were read as two competing job titles for the same
# person and one silently superseded the other at confidence 0.86. Everything
# below exists to keep a clause from being mistaken for a title.
_MAX_TITLE_WORDS = 5
_CLAUSE_MARKERS = frozenset("that because when while since so if whether although".split())
# States and opinions, not roles. "She is satisfied with X" is not a job.
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


def _person_subject(text: str) -> str:
    """The name in front of 'lives in' / 'moved to', without filler words."""

    words = [w for w in re.findall(r"[^\W\d_][\w'-]*", text) if w.casefold() not in {"has", "have", "and", "also", "recently", "just"}]
    return " ".join(words[-3:])


def _looks_like_a_person(subject: str) -> bool:
    words = subject.split()
    if not words:
        return False
    if words[-1].casefold() in {"i", "we", "he", "she", "they"}:
        return True
    return all(word[:1].isupper() for word in words) and words[0].casefold() not in {"the", "our", "my", "a", "an"}


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
        add("lives_in", _person_subject(match.group("subject")), match.group("value"))
    elif match := _MOVED_TO.search(clean):
        subject = _person_subject(match.group("subject"))
        # Only people move house. "The launch party moved to Toronto" names an event.
        if subject and _looks_like_a_person(subject):
            add("lives_in", subject, match.group("value"))
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


_MONTHS = {
    name: index
    for index, names in enumerate(
        (
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
            ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
            ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}
_MONTH = r"(?P<{0}>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_DATE_VALUE = re.compile(
    r"\b(?P<d1>\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH.format("m1") + r"(?:,?\s+(?P<y1>20\d{2}))?\b"
    r"|\b" + _MONTH.format("m2") + r"\s+(?P<d2>\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(?P<y2>20\d{2}))?\b"
    r"|\b(?P<y3>20\d{2})-(?P<m3>\d{2})-(?P<d3>\d{2})\b",
    re.IGNORECASE,
)
_TIME_VALUE = re.compile(
    r"\b(?P<h1>\d{1,2})(?::(?P<n1>\d{2}))?\s*(?P<ap>[ap])\.?m\b\.?"
    r"|\b(?P<h2>[01]?\d|2[0-3]):(?P<n2>[0-5]\d)\b"
    r"|\b(?P<noon>noon|midnight)\b",
    re.IGNORECASE,
)
_AMOUNT_VALUE = re.compile(
    r"(?P<cur>[$€£])\s?(?P<a1>\d[\d,]*(?:\.\d+)?)\s?(?P<k1>[km])?\b"
    r"|\b(?P<a2>\d[\d,]*(?:\.\d+)?)\s?(?P<pct>%|percent\b)",
    re.IGNORECASE,
)
_VERSION_VALUE = re.compile(r"\bv?(\d+\.\d+\.\d+(?:\.\d+)*)\b|\b(?:v|version|release)\s*(\d+\.\d+(?:\.\d+)*)\b", re.IGNORECASE)
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")


@lru_cache(maxsize=4096)
def extract_values(content: str) -> tuple[dict[str, frozenset], frozenset[str], str]:
    """Typed values (dates, times, amounts, versions), leftover identifiers, and the
    text with every value cut out.

    Comparing values as strings was the stale-state bug: "15 Oct 2026" and
    "22 Oct 2026" score 0.8 as text, so the newer deadline was read as an
    elaboration of the old one and both stayed in recall. Values are parsed and
    compared as values instead. A bare number that is none of these -- "item 27",
    "room 7" -- is an identifier: it names *which* thing, so two memories with
    different identifiers are about different things, not a change of value.
    """

    values: dict[str, set] = {}
    spans: list[tuple[int, int]] = []

    def take(kind: str, value: Any, match: re.Match) -> None:
        values.setdefault(kind, set()).add(value)
        spans.append(match.span())

    for match in _VERSION_VALUE.finditer(content):
        take("version", match.group(1) or match.group(2), match)
    for match in _DATE_VALUE.finditer(content):
        g = match.groupdict()
        if g["y3"]:
            month, day, year = int(g["m3"]), int(g["d3"]), g["y3"]
        else:
            name = (g["m1"] or g["m2"]).casefold().rstrip(".")
            month = _MONTHS.get(name) or _MONTHS.get(name[:3], 0)
            day = int(g["d1"] or g["d2"])
            year = g["y1"] or g["y2"]
        take("date", (month, day, year), match)
    for match in _TIME_VALUE.finditer(content):
        g = match.groupdict()
        if g["noon"]:
            minutes = 720 if g["noon"].casefold() == "noon" else 0
        elif g["h1"]:
            hour = int(g["h1"]) % 12 + (12 if g["ap"].casefold() == "p" else 0)
            minutes = hour * 60 + int(g["n1"] or 0)
        else:
            minutes = int(g["h2"]) * 60 + int(g["n2"])
        take("time", minutes, match)
    for match in _AMOUNT_VALUE.finditer(content):
        g = match.groupdict()
        raw = (g["a1"] or g["a2"]).replace(",", "")
        amount = float(raw) * {"k": 1e3, "m": 1e6}.get((g["k1"] or "").casefold(), 1)
        take("percent" if g["pct"] else "amount", amount, match)

    def covered(start: int, end: int) -> bool:
        return any(a <= start and end <= b for a, b in spans)

    identifiers = frozenset(
        m.group(0) for m in _NUMBER.finditer(content) if not covered(*m.span())
    )
    residue = content
    for start, end in sorted(spans, reverse=True):
        residue = residue[:start] + " " + residue[end:]
    residue = _NUMBER.sub(" ", residue)
    return {k: frozenset(v) for k, v in values.items()}, identifiers, residue


def _dates_differ(new: frozenset, old: frozenset) -> bool:
    for nm, nd, ny in new:
        for om, od, oy in old:
            if (nm, nd) == (om, od) and (ny is None or oy is None or ny == oy):
                return False
    return True


@lru_cache(maxsize=4096)
def _frame_terms(content: str) -> frozenset[str]:
    """What a memory is about once its values and change words are removed."""

    from . import storage as _storage

    _, _, residue = extract_values(content)
    return frozenset(
        _storage._stem(token)
        for token in _storage._normalize(residue).split()
        if len(token) > 1
        and token not in _storage._STOPWORDS
        and token not in _CHANGE_WORDS
        and token not in _GENERIC_SUBJECTS
        and not any(ch.isdigit() for ch in token)
    )


_FROM_TO = re.compile(
    r"\bfrom\s+(?P<old>[\w.+#-]+)\s+to\s+(?P<new>[\w.+#-]+)"
    r"|\breplac(?:ed|ing)\s+(?P<old2>[\w.+#-]+)\s+with\s+(?P<new2>[\w.+#-]+)"
    r"|\b(?P<new3>[\w.+#-]+)\s+instead\s+of\s+(?P<old3>[\w.+#-]+)",
    re.IGNORECASE,
)


def _value_change(new_content: str, old_content: str, change_language: bool) -> dict[str, Any] | None:
    """Same subject, different date/time/amount/version, or an explicit X -> Y."""

    content_terms, _, _ = _text()
    new_values, new_ids, _ = extract_values(new_content)
    old_values, old_ids, _ = extract_values(old_content)
    if new_ids != old_ids and (new_ids or old_ids):
        return {"action": "unrelated", "reason": "Different identifiers name different things.",
                "evidence": f"identifiers {sorted(old_ids)} vs {sorted(new_ids)}", "confidence": 0.0}

    new_frame = _frame_terms(new_content)
    old_frame = _frame_terms(old_content)

    # "switched from Postgres to MySQL": the old memory holds the old value, the
    # new memory names both, and they share the rest of the subject.
    if change_language and (match := _FROM_TO.search(new_content)):
        before = (match.group("old") or match.group("old2") or match.group("old3")).rstrip(".,;:")
        after = (match.group("new") or match.group("new2") or match.group("new3")).rstrip(".,;:")
        before_terms = content_terms(before)
        after_terms = content_terms(after)
        old_terms = content_terms(old_content)
        if before_terms and before_terms <= old_terms and not (after_terms & old_terms):
            shared = (new_frame - after_terms) & (old_frame - before_terms)
            if shared or len(old_frame) <= 2:
                return {"action": "contradict",
                        "reason": "A later fact says the value changed from the one this memory holds.",
                        "evidence": f"changed: '{before}' -> '{after}'",
                        "confidence": 0.92}

    if not new_frame or not old_frame:
        return None
    shared = new_frame & old_frame
    if not shared:
        return None
    jaccard = len(shared) / len(new_frame | old_frame)
    smaller = min(len(new_frame), len(old_frame))
    same_subject = jaccard >= 0.75 or (change_language and len(shared) / smaller >= 0.6)
    if not same_subject:
        return None
    changed: list[str] = []
    for kind in ("date", "time", "amount", "percent", "version"):
        if kind not in new_values or kind not in old_values:
            continue
        if kind == "date":
            differs = _dates_differ(new_values[kind], old_values[kind])
        else:
            differs = not (new_values[kind] & old_values[kind])
        if differs:
            changed.append(f"{kind}: {_show(old_values[kind])} vs {_show(new_values[kind])}")
    if not changed:
        return None
    return {"action": "contradict",
            "reason": ("A later fact gives a different value for the same subject"
                       + (" and says it changed." if change_language else ".")),
            "evidence": "; ".join(changed) + f"; subject {sorted(shared)[:6]}",
            "confidence": 0.9 if change_language else 0.8}


def _show(values: frozenset) -> str:
    def one(value: Any) -> str:
        if isinstance(value, tuple):
            month, day, year = value
            return f"{year or '????'}-{month:02d}-{day:02d}"
        if isinstance(value, int):
            return f"{value // 60:02d}:{value % 60:02d}"
        if isinstance(value, float):
            return f"{value:g}"
        return str(value)

    return ", ".join(sorted(one(v) for v in values))


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
    # The bounded call skips SequenceMatcher when the pair cannot be a duplicate;
    # the exact score is only computed if a later branch reports it.
    similarity = similarity_fn(new_norm, old_norm, minimum=MERGE_SIMILARITY)
    if similarity >= MERGE_SIMILARITY:
        return {
            "action": "duplicate",
            "reason": "Near-duplicate of an existing memory.",
            "evidence": f"similarity {similarity:.2f}",
            "confidence": round(similarity, 3),
        }

    cached: list[float] = []

    def exact_similarity() -> float:
        if not cached:
            cached.append(similarity_fn(new_norm, old_norm))
        return cached[0]

    replacement = bool(_REPLACEMENT_LANGUAGE.search(new_content))
    changed_value = _value_change(new_content, old_content, replacement)
    if changed_value is not None:
        return changed_value

    new_slots = extract_slots(new_content)
    old_slots = extract_slots(old_content)
    new_kinds = {slot[0] for slot in new_slots}
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
            elif kind == "lives_in":
                # "Dana lives in Montreal" says nothing about where Sam lives.
                if subject and old_subject and similarity_fn(subject, old_subject) < 0.55:
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
            "evidence": f"shared terms {sorted(overlap)[:8]}; similarity {exact_similarity():.2f}",
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
                    "confidence": round(exact_similarity(), 3),
                }
            return {
                "action": "review",
                "reason": "Same kind of fact, different value, but the subject is not clearly the same.",
                "evidence": f"kinds {sorted(new_kinds)}; similarity {exact_similarity():.2f}",
                "confidence": 0.4,
            }

    # "These memories share a subject" used to open a review here with no evidence
    # of disagreement at all. 500 similar routine notes opened 496 of them and buried
    # the few real conflicts. Similar is not contradictory: without a differing value
    # or change language there is nothing for a person to decide.
    return {
        "action": "unrelated",
        "reason": "No shared slot, differing value, or change language.",
        "evidence": f"shared terms {sorted(overlap)[:8]}",
        "confidence": 0.0,
    }


def consider_incoming(new_content: str, existing: list[Any]) -> dict[str, Any] | None:
    """Pick at most one existing active memory to supersede or mark for review."""

    contradict: dict[str, Any] | None = None
    review: dict[str, Any] | None = None
    new_terms = _distinctive_terms(new_content)
    new_kinds = {slot[0] for slot in extract_slots(new_content)}
    new_ids = extract_values(new_content)[1]
    for row in existing:
        old_content = str(row["content"])
        # Different identifiers ("room 7" vs "room 27") are different things;
        # classify_pair would say "unrelated" after a full similarity pass.
        if extract_values(old_content)[1] != new_ids:
            continue
        # Cheap exact pre-filter. Every verdict other than an (ignored) duplicate
        # needs a shared distinctive term or a shared slot kind, so a pair with
        # neither is unrelated -- and skipping it avoids a quadratic
        # SequenceMatcher per stored memory on every write.
        if not (new_terms & _distinctive_terms(old_content)) and not (
            new_kinds & {slot[0] for slot in extract_slots(old_content)}
        ):
            continue
        verdict = classify_pair(new_content, old_content)
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
