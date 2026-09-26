"""Lightweight MCP metadata used before the full server has imported.

This module is deliberately standard-library-only.  On Windows, importing the MCP
SDK and the storage stack can take long enough for the host's shared chat pool to
give up even though the process is healthy.  The bootstrap process can answer the
handshake and discovery requests from this static catalogue while the real server
starts behind it.
"""

from __future__ import annotations


VERSION = "0.4.11"
PROTOCOL_VERSION = "2024-11-05"

SERVER_INSTRUCTIONS = (
    "First session or 'how do I set this up': call memorysafe_health. Then help in this order: "
    "(1) restart Codex and/or Claude Code after install; Claude Desktop must confirm the .mcpb "
    "if asked. (2) Open http://127.0.0.1:8765/dashboard on this computer. (3) Prove the store: "
    "remember one durable fact, then find it. Automatic capture stays off until they ask to "
    "turn it on or use the dashboard toggle. One local file is shared by Claude Desktop, "
    "Claude Code and Codex. Nothing is uploaded. Do not claim MemorySafe reads chats by itself. "
    "When automatic mode is on and the user states durable facts — a deadline, a decision, "
    "who someone is, a preference, a constraint — call memorysafe_auto_capture once with all "
    "of them. Duplicates merge. Nothing is pruned for being old or low-value. Never capture "
    "secrets, credentials, payment or government IDs, contact details, precise addresses, "
    "health data, or third-party personal details. Search memory before answering about past "
    "work, people or decisions. ChatGPT.com is not on this SQLite. "
    "memorysafe_remember needs an explicit request. Confirm before "
    "forgetting or resolving a conflict. Forget removes a memory from recall; it does not "
    "erase it. Quote memory content, not IDs."
)

CATEGORIES = ["preference", "personal", "project", "decision", "task", "safety", "other"]


def _annotations(*, read_only: bool, destructive: bool, idempotent: bool) -> dict[str, bool]:
    return {
        "readOnlyHint": read_only,
        "destructiveHint": destructive,
        "idempotentHint": idempotent,
        "openWorldHint": False,
    }


def _object(properties: dict, required: list[str] | None = None) -> dict:
    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


TOOLS = [
    {
        "name": "memorysafe_remember",
        "title": "Remember with MemorySafe",
        "description": (
            "Save one durable fact, only when the user explicitly asks to remember it. "
            "Stored locally; duplicates may merge."
        ),
        "inputSchema": _object(
            {
                "content": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 10_000,
                    "description": "The fact to remember.",
                },
                "category": {
                    "type": "string",
                    "enum": CATEGORIES,
                    "default": "other",
                    "description": "Kind of memory.",
                },
            },
            ["content"],
        ),
        "annotations": _annotations(read_only=False, destructive=False, idempotent=False),
    },
    {
        "name": "memorysafe_set_auto_mode",
        "title": "Set automatic memory mode",
        "description": "Turn automatic capture on or off, only when the user asks.",
        "inputSchema": _object(
            {"enabled": {"type": "boolean", "description": "On or off."}}, ["enabled"]
        ),
        "annotations": _annotations(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "memorysafe_auto_capture",
        "title": "Capture durable memories",
        "description": (
            "Save the durable facts the user just stated — all of them in one call, only while "
            "automatic mode is on. Duplicates merge. Nothing is dropped for being old or low-value. "
            "Never ask first. Never pass whole messages, inferences, secrets, IDs, contacts, "
            "addresses or health data."
        ),
        "inputSchema": _object(
            {
                "facts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 3,
                    "description": "One sentence each.",
                },
                "category": {
                    "type": "string",
                    "enum": CATEGORIES,
                    "default": "other",
                    "description": "Kind of memory.",
                },
            },
            ["facts"],
        ),
        "annotations": _annotations(read_only=False, destructive=False, idempotent=False),
    },
    {
        "name": "memorysafe_find",
        "title": "Find memories",
        "description": "Search stored memories. Empty query browses recent ones.",
        "inputSchema": _object(
            {
                "query": {
                    "type": "string",
                    "maxLength": 500,
                    "default": "",
                    "description": "What to look for.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5,
                    "description": "Maximum results.",
                },
            }
        ),
        "annotations": _annotations(read_only=True, destructive=False, idempotent=True),
    },
    {
        "name": "memorysafe_forget",
        "title": "Forget a memory",
        "description": (
            "Remove one memory from active recall, only when the user asks. This is not a "
            "permanent erase. Without an exact ID, find and confirm it first. Protected "
            "memories need confirm=true."
        ),
        "inputSchema": _object(
            {
                "memory_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 80,
                    "description": "Exact memory ID.",
                },
                "confirm": {
                    "type": "boolean",
                    "default": False,
                    "description": "Required for a protected memory, after the user agrees.",
                },
            },
            ["memory_id"],
        ),
        "annotations": _annotations(read_only=False, destructive=True, idempotent=True),
    },
    {
        "name": "memorysafe_protect",
        "title": "Protect or unprotect a memory",
        "description": (
            "Protect one memory (never evicted; forgetting needs confirmation), or pass "
            "protect=false to remove protection. Only when the user asks. Audited."
        ),
        "inputSchema": _object(
            {
                "memory_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 80,
                    "description": "Exact memory ID.",
                },
                "protect": {
                    "type": "boolean",
                    "default": True,
                    "description": "true protects, false unprotects.",
                },
            },
            ["memory_id"],
        ),
        "annotations": _annotations(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "memorysafe_explain",
        "title": "Explain a memory",
        "description": (
            "Inspect one memory in any state — active, superseded, or forgotten — with "
            "its decision history and replacement record. Not limited to normal recall."
        ),
        "inputSchema": _object(
            {
                "memory_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 80,
                    "description": "Exact memory ID.",
                }
            },
            ["memory_id"],
        ),
        "annotations": _annotations(read_only=True, destructive=False, idempotent=True),
    },
    {
        "name": "memorysafe_review_conflicts",
        "title": "Review memory conflicts",
        "description": (
            "List open conflicts where a new fact might replace an older one. "
            "Does not change anything."
        ),
        "inputSchema": _object(
            {
                "include_resolved": {
                    "type": "boolean",
                    "default": False,
                    "description": "Also list already resolved replacements.",
                }
            }
        ),
        "annotations": _annotations(read_only=True, destructive=False, idempotent=True),
    },
    {
        "name": "memorysafe_resolve_conflict",
        "title": "Resolve a memory conflict",
        "description": (
            "Supersede, keep both, restore (conflict stays open), or revert (reject the newer "
            "update, bring back the prior fact). Requires confirm=true after the user agrees. "
            "Nothing changes without that confirmation."
        ),
        "inputSchema": _object(
            {
                "conflict_id": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Conflict ID from review.",
                },
                "action": {
                    "type": "string",
                    "enum": ["supersede", "keep_both", "restore", "revert"],
                    "description": "supersede, keep_both, restore, or revert.",
                },
                "confirm": {
                    "type": "boolean",
                    "default": False,
                    "description": "Must be true; otherwise nothing is changed.",
                },
            },
            ["conflict_id", "action"],
        ),
        "annotations": _annotations(read_only=False, destructive=True, idempotent=False),
    },
    {
        "name": "memorysafe_restore",
        "title": "Restore a memory to recall",
        "description": (
            "Put a superseded or forgotten memory back into active recall. "
            "Requires confirm=true after the user agrees."
        ),
        "inputSchema": _object(
            {
                "memory_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 80,
                    "description": "Exact memory ID.",
                },
                "confirm": {
                    "type": "boolean",
                    "default": False,
                    "description": "Must be true; otherwise nothing is changed.",
                },
            },
            ["memory_id"],
        ),
        "annotations": _annotations(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "memorysafe_doctor",
        "title": "Diagnose a MemorySafe install",
        "description": (
            "Check this MemorySafe installation and say what to do about anything wrong. "
            "Call this whenever the user says MemorySafe is not working, memories seem "
            "missing, or a fresh install does not respond -- and before suggesting a "
            "reinstall. Read-only: it inspects the installation, never memory contents, "
            "and changes nothing. Read 'next_actions' out in plain language and work "
            "through them in order; do not read the raw checks to the user."
        ),
        "inputSchema": _object({}),
        "annotations": _annotations(read_only=True, destructive=False, idempotent=True),
    },
    {
        "name": "memorysafe_health",
        "title": "Show memory health",
        "description": (
            "Show local memory counts, storage, governance decisions and the health formula. "
            "Call this first when the user just installed MemorySafe or asks how to set it up, "
            "then walk them through restart, the dashboard at http://127.0.0.1:8765/dashboard, "
            "and one remember-then-find. Pass open=true to also open the visual dashboard; if "
            "the returned 'opened' is 'window' or 'browser', say it opened rather than pasting "
            "the link."
        ),
        "inputSchema": _object(
            {
                "open": {
                    "type": "boolean",
                    "default": False,
                    "description": "Also open the dashboard window.",
                }
            }
        ),
        "annotations": _annotations(read_only=True, destructive=False, idempotent=True),
        "_meta": {
            "ui": {"resourceUri": "ui://memorysafe/dashboard-v3.html"},
            "openai/outputTemplate": "ui://memorysafe/dashboard-v3.html",
            "openai/toolInvocation/invoking": "Opening MemorySafe dashboard…",
            "openai/toolInvocation/invoked": "MemorySafe dashboard ready.",
        },
    },
]

RESOURCES = [
    {
        "uri": "ui://memorysafe/dashboard-v3.html",
        "name": "memorysafe-dashboard",
        "title": "MemorySafe dashboard",
        "description": "Inline visual dashboard for real local MemorySafe health and governed storage data.",
        "mimeType": "text/html;profile=mcp-app",
        "_meta": {"ui": {"prefersBorder": True}},
    }
]

