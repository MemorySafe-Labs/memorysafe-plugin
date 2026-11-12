"""How likely a memory is to be needed again, from how it has been used.

The store keeps everything it is told. What is scarce is the assistant's context: a session
can carry a dozen memories and a search can return five, out of hundreds. Until now the
choice among them looked only at what kind of memory it was (category, protection) and when
its row last changed. Whether anyone had ever needed it again was recorded and never read.

This module turns the record of use into one number. It is the base-level activation of
Anderson and Schooler's rational analysis of memory (Psychological Science, 1991), which
found that how often and how recently something came up predicts how likely it is to come
up again, as a power function of time and not an exponential one:

    activation = ln( sum over every use j of  (now - t_j) ** -DECAY )

Every use adds a trace, every trace fades as a power of its age, and traces add up. A fact
used once last week and a fact used ten times over six months are both ahead of a fact
saved once in spring and never touched. The store does not keep every use's time, only the
first, the last and the count, so the sum uses Petrov's approximation (Proceedings of the
International Conference on Cognitive Modeling, 2006): the latest use exactly, the earlier
ones as if spread evenly between the first use and the latest.

What this number is used for, and what it is never used for:
  * It orders memories that are otherwise equal: which ones a session carries, and which
    of two equally relevant search results comes first.
  * It never removes, hides or erases anything, and it never overrides protection or a
    person's own decision. A memory nobody has needed for a year is still found by a
    search for its words.

Stdlib only, and written for Python 3.8, because the session-start hook imports it and may
run on the system interpreter.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

# The decay exponent of the power law. 0.5 is the conventional value for the base-level
# learning equation; nothing here was fitted to MemorySafe's own data.
DECAY = 0.5
# A use a minute ago and a use an hour ago are both "just now" for a store that is read a
# few times a day; without a floor the newest trace would swamp every other term.
MIN_AGE_DAYS = 1.0 / 24.0
# How far a memory's kind moves it against use. One unit of activation is the gap between
# a fact used today and the same fact unused for a week, so a safety memory (0.95) starts
# about a week of disuse ahead of a passing note (0.60) and use can still overtake it.
SALIENCE_WEIGHT = 3.0


def parse_time(value: Any) -> Optional[datetime]:
    """An aware datetime from a stored timestamp, or None when it cannot be read."""

    if isinstance(value, datetime):
        moment = value
    else:
        if not value:
            return None
        try:
            moment = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if moment.tzinfo is None:
        # Stores written by older builds hold naive strings; they were UTC.
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def age_days(then: Any, now: datetime) -> float:
    """Days from `then` to `now`, never below the floor (a clock set back is not a negative age)."""

    moment = parse_time(then)
    if moment is None:
        return MIN_AGE_DAYS
    return max(MIN_AGE_DAYS, (now - moment).total_seconds() / 86400.0)


def activation(first_used: Any, last_used: Any, uses: int, now: datetime) -> float:
    """Base-level activation of a memory used `uses` times between two dates.

    `uses` counts the save itself, so it is at least 1. With one use the sum has one term.
    With more, the latest use is exact and the rest are integrated over the span between
    the first use and the latest (Petrov's approximation, keeping one exact trace).
    """

    count = max(1, int(uses or 1))
    oldest = age_days(first_used, now)
    newest = min(oldest, age_days(last_used if last_used else first_used, now))
    total = newest ** -DECAY
    if count > 1:
        if oldest - newest > 1e-9:
            spread = (oldest ** (1.0 - DECAY) - newest ** (1.0 - DECAY)) / ((1.0 - DECAY) * (oldest - newest))
        else:
            # Every use at the same moment: each earlier trace is as old as the latest.
            spread = newest ** -DECAY
        total += (count - 1) * spread
    return math.log(total)


def uses_of(row: Any) -> int:
    """How many times a stored memory has come up: the save, each recall, each restatement."""

    def read(name: str) -> int:
        try:
            return int(row[name] or 0)
        except (KeyError, IndexError, TypeError, ValueError):
            return 0

    return 1 + read("recall_count") + read("restated_count")


def last_use_of(row: Any) -> Any:
    """When a stored memory last came up, or when it was saved if it never has since."""

    try:
        latest = row["last_used_at"]
    except (KeyError, IndexError):
        latest = None
    return latest or row["created_at"]


def row_activation(row: Any, now: datetime) -> float:
    """activation() for a memories row (needs created_at; reads the use columns when present)."""

    return activation(row["created_at"], last_use_of(row), uses_of(row), now)


def retention(row: Any, now: datetime) -> float:
    """One number to rank memories by when only some can be carried: use, plus what kind it is.

    Importance is the server's own reading of the memory's kind and source (never the
    model's opinion of itself), so this stays something the store can account for:
    `explain` can say "used 7 times, last on 3 March" and that is the whole reason.
    """

    try:
        importance = float(row["importance"])
    except (KeyError, IndexError, TypeError, ValueError):
        importance = 0.6
    return row_activation(row, now) + SALIENCE_WEIGHT * importance
