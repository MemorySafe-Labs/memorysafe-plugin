# MemorySafe — private beta

Most agent memory tools are built to remember. This one is built to **decide what's worth
keeping** — and to show you its reasoning.

Every candidate memory gets one of four outcomes:

| | |
|---|---|
| **Protect** | high value, kept with the reason on record; it leaves recall only when a later fact replaces it (recorded, and reversible) or you ask to forget it |
| **Store** | worth keeping |
| **Merge** | you already knew this; fold it in rather than duplicate |
| **Skip** | not stored: automatic capture refused it, or automatic mode is off |

A memory health score reports how well the store is doing: importance and confidence at
60%, protection of high-value memories at 30%, duplicate cleanliness at 10%. The formula
is printed with the score, so you can check the arithmetic rather than trust it.

## Install

```bash
# Claude Code
claude plugin marketplace add MemorySafe-Labs/memorysafe-plugin
claude plugin install memorysafe@memorysafe

# Codex
codex plugin marketplace add MemorySafe-Labs/memorysafe-plugin
codex plugin add memorysafe@memorysafe
```

Claude Desktop: install `memorysafe-claude-desktop.mcpb` from the same repository's releases.

## What stays local

- One SQLite file serves Claude Code, Claude Desktop and Codex:
  `~/Library/Application Support/MemorySafe/data/memorysafe.sqlite3` on macOS,
  `~/.local/share/MemorySafe/data/memorysafe.sqlite3` on Linux,
  `%LOCALAPPDATA%\MemorySafe\data\memorysafe.sqlite3` on Windows.
- The dashboard is reachable only from this computer, at `http://127.0.0.1:8765/dashboard`.
- MemorySafe does not copy full conversations and does not read an assistant's own memory.
- The first start downloads uv, a Python, pinned packages and tokenizer data. After that
  nothing leaves this computer.

## Off by default

Automatic capture is **disabled** until you explicitly enable it:

> Turn on MemorySafe automatic mode.

Even then, the assistant recognises and submits each candidate itself — MemorySafe never
watches a conversation on its own. Manual saves always require you to ask.

## What it refuses to store

Automatic capture will not save assistant-generated text, inferences, passing remarks,
passwords, API keys, payment or government identifiers, contact details, precise addresses,
or medical information. These are refusals, not settings. Keeping other people's personal
details out is a rule the assistant is told to follow; the server does not yet enforce it.

## About the numbers

Live token counts are exact measurements of what MemorySafe holds locally. The savings figure
shown next to them is a **modelled estimate**, not anyone's billed usage, and it is labelled as
such wherever it appears. MemorySafe makes no claim about task quality or retrieval speed,
because neither has been measured yet.
