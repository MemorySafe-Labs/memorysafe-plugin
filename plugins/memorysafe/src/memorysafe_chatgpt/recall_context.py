"""Small, explicit vocabulary bridges for task context, not semantic search.

Direct lexical answers keep priority. These bridges only nominate standing rules
to fill unused recall slots; they do not change storage, protection, or scope.
Keep the vocabulary general rather than adding project or benchmark names.
"""

from collections.abc import Callable

# (task vocabulary, vocabulary used to describe the corresponding rules)
BRIDGES = (
    (
        "code programming function endpoint component python javascript typescript "
        "react vue angular svelte fastapi django flask rust golang java kotlin swift",
        "code formatting formatter lint linter ruff prettier eslint indentation indent",
    ),
    (
        "frontend ui interface component react vue angular svelte html css styling",
        "frontend ui interface component css styling styles stylesheet "
        "tailwind bootstrap sass scss accessibility accessible design",
    ),
)


def context_terms(query_terms: set[str], tokenize: Callable[[str], set[str]]) -> set[str]:
    """Return only the vocabulary of bridges activated by this task."""
    result: set[str] = set()
    for task_words, rule_words in BRIDGES:
        if query_terms & tokenize(task_words):
            result.update(tokenize(rule_words))
    return result
