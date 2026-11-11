"""The two forms of memory text: the one stored and the one analysed.

Until 0.4.31 remember() stored `" ".join(content.split())`, so every memory was one line
and a list, a heading or a code block never reached the store. The stored form now keeps
its line breaks (`clean_text`). Everything that pattern-matches memory text (duplicate
detection, protection hints, the lifecycle classifiers, the hosted staleness checks) was
written against one-line text and reads `flat`, which is exactly what 0.4.30 stored:
`flat(clean_text(x)) == flat(x)` for every string, so no verdict depends on where the
lines break. Stdlib only; imports nothing from the package.
"""

from __future__ import annotations

import re

_INDENT = re.compile(r"[ \t]*")


def flat(text: str) -> str:
    """The text as one line, every run of whitespace a single space."""

    return " ".join(text.split())


def clean_text(content: str) -> str:
    """The text as stored: line breaks kept, everything else tidied.

    Every line ending (\\r\\n, \\r, \\u2028, ...) becomes \\n. A line keeps its leading
    spaces and tabs, which nested lists and code blocks need; every other run of
    whitespace in it becomes one space and trailing whitespace goes. Empty lines at the
    start and end are dropped, and more than one empty line in a row becomes one.
    """

    lines: list[str] = []
    for line in content.splitlines():
        words = line.split()
        if not words:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        indent = _INDENT.match(line).group() if lines else ""
        lines.append(indent + " ".join(words))
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)
