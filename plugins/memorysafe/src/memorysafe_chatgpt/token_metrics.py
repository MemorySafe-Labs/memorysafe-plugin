from __future__ import annotations

from functools import lru_cache
import json
import math
import re

import tiktoken


TOKENIZER_NAME = "o200k_base"
FALLBACK_TOKENIZER_NAME = "local_wordpiece_fallback"
_FALLBACK_PIECES = re.compile(r"\w+|[^\w\s]", re.UNICODE)

# How many stored facts a governed turn restates. The dashboard has always fallen back
# to five when the field is missing, and storage.token_benchmark imports this name:
# without it every health call raised ImportError, so memorysafe_health never answered.
RECALLED_PER_TURN = 5


@lru_cache(maxsize=1)
def _encoding():
    try:
        return tiktoken.get_encoding(TOKENIZER_NAME)
    except Exception:  # The local tiktoken cache may be unavailable while offline.
        return None


def count_text_tokens(text: str) -> int:
    """Count model-input tokens without sending text off this computer."""

    encoding = _encoding()
    if encoding is not None:
        return len(encoding.encode(text))
    return len(_FALLBACK_PIECES.findall(text))


def tokenizer_metadata() -> dict[str, str | bool]:
    exact = _encoding() is not None
    return {
        "tokenizer": TOKENIZER_NAME if exact else FALLBACK_TOKENIZER_NAME,
        "exact": exact,
        "note": (
            "Exact local o200k_base token counts; no memory content leaves this computer."
            if exact
            else "Local fallback counts are shown because the o200k_base cache is unavailable. "
            "Memory storage and recall are unaffected."
        ),
    }


@lru_cache(maxsize=1)
def _fixed_overhead() -> tuple[int, int]:
    # bootstrap_catalog is the advertised tool list, and test_bootstrap_server keeps it
    # identical to the live server's, so measuring it measures what every conversation
    # is actually sent -- without importing the MCP SDK to find out.
    from .bootstrap_catalog import SERVER_INSTRUCTIONS, TOOLS

    tool_schema_tokens = count_text_tokens(json.dumps(TOOLS, separators=(",", ":"), sort_keys=True))
    instruction_tokens = count_text_tokens(SERVER_INSTRUCTIONS)
    return tool_schema_tokens, instruction_tokens


def fixed_overhead_tokens() -> dict[str, int]:
    """Tokens MemorySafe costs every conversation before any memory is recalled."""

    tool_schema_tokens, instruction_tokens = _fixed_overhead()
    return {
        "tool_schema_tokens": tool_schema_tokens,
        "instruction_tokens": instruction_tokens,
        "fixed_overhead_tokens": tool_schema_tokens + instruction_tokens,
    }


def break_even_facts(average_fact_tokens: int) -> int:
    """Smallest store at which restating every fact costs at least the governed turn."""

    average = max(1, int(average_fact_tokens))
    return math.ceil(fixed_overhead_tokens()["fixed_overhead_tokens"] / average) + RECALLED_PER_TURN
