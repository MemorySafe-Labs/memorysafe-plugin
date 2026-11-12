"""What a tool says when it refuses, and what it keeps to itself when it breaks.

A MemorySafe tool that cannot do what it was asked raises ValueError or RuntimeError with a
sentence written for the person: "Memory content must include letters or numbers.", "Your
hosted account could not be reached; your memories were not changed." Since version 2.2 the MCP library passes a tool's
message on to the assistant only when it is a ToolError, and replaces everything else with
"Error executing tool <name>". That is the right default for a crash, whose message may
quote a path, a row or an argument, and the wrong one for these sentences: an assistant
told only that the tool failed cannot tell the person why, or what to do next.

spoken() is the one place that says which is which. ValueError and RuntimeError are what
this package raises on purpose, so their words go through. Everything else (a database
error, a KeyError, a result that fails its own model) stays a crash and stays unsaid.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError


def _said(error: BaseException) -> bool:
    # pydantic's ValidationError is a ValueError, and its text quotes the values it rejected.
    return isinstance(error, (ValueError, RuntimeError)) and not isinstance(error, ValidationError)


def spoken(fn: Callable[..., Any]) -> Callable[..., Any]:
    """`fn`, with the refusals it raises on purpose turned into ToolError so they are read."""

    if hasattr(fn, "unspoken"):
        return fn
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await fn(*args, **kwargs)
            except Exception as error:
                if _said(error):
                    raise ToolError(str(error)) from error
                raise
    else:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except Exception as error:
                if _said(error):
                    raise ToolError(str(error)) from error
                raise
    wrapper.unspoken = fn  # type: ignore[attr-defined]
    return wrapper


def unspoken(fn: Callable[..., Any]) -> Callable[..., Any]:
    """The function spoken() wrapped, for a caller that wraps it again and speaks last."""

    return getattr(fn, "unspoken", fn)
