# MemorySafe 0.4.2

Private, governed memory for Claude Code, Claude Desktop and Codex, kept in one SQLite
file on your own computer. macOS, Linux and Windows.

## Before you start

Whatever you install below: **restart the assistant afterwards.** Its first start then
builds a private Python runtime — a minute or two, once. When that finishes,
<http://127.0.0.1:8765/dashboard> opens on this computer. That is how you know it worked.

## Claude Code

Needs the `claude` command-line tool.

    claude plugin marketplace add MemorySafe-Labs/memorysafe-plugin
    claude plugin install memorysafe@memorysafe

Restart Claude Code, run `/mcp`, and confirm `memorysafe` is connected with eleven tools.

## Claude Desktop

The desktop app does not include the `claude` command, so the commands above will not
work here. Install the extension instead.

Download https://github.com/MemorySafe-Labs/memorysafe-plugin/releases/latest/download/memorysafe-claude-desktop.mcpb and open it with
Claude Desktop, or choose it from **Settings → Extensions → Advanced settings → Install
Extension…**. Leave the data folder empty so Claude Desktop shares the same store.

Then restart Claude Desktop and open <http://127.0.0.1:8765/dashboard>. If it loads,
MemorySafe is installed. You do not need to download the extension again.

## Codex

    codex plugin marketplace add MemorySafe-Labs/memorysafe-plugin
    codex plugin add memorysafe@memorysafe

Codex asks you to trust the plugin's hook before running it. MemorySafe works without
it: the hook only makes automatic capture fire more reliably once you turn that on.

## First start

The first time an assistant starts MemorySafe, it downloads uv from GitHub, a Python
build through uv, hash-pinned packages from PyPI, and the tokenizer data it counts tokens
with, all into the MemorySafe folder. That takes a minute or two, once. After that,
nothing leaves this computer. On a network that blocks GitHub, set MEMORYSAFE_UV to a uv
you already have, or HTTPS_PROXY to your proxy.

## What MemorySafe decides

Most agent memory tools are built to remember. This one is built to **decide what's worth
keeping** — and to show you its reasoning. Every candidate gets one of four outcomes:

| | |
|---|---|
| **Protect** | high value, kept with the reason on record; it leaves recall only when a later fact replaces it (recorded, and reversible) or you ask to forget it |
| **Store** | worth keeping |
| **Merge** | you already knew this; fold it in rather than duplicate |
| **Skip** | not stored: automatic capture refused it, or automatic mode is off |

A memory health score reports how well the store is doing: importance and confidence at
60%, protection of high-value memories at 30%, duplicate cleanliness at 10%. The formula
is printed with the score, so you can check the arithmetic rather than trust it.

## What stays local

- One SQLite file serves Claude Code, Claude Desktop and Codex:
  `~/Library/Application Support/MemorySafe/data/memorysafe.sqlite3` on macOS,
  `~/.local/share/MemorySafe/data/memorysafe.sqlite3` on Linux,
  `%LOCALAPPDATA%\MemorySafe\data\memorysafe.sqlite3` on Windows.
- The dashboard is reachable only from this computer.
- MemorySafe does not copy full conversations and does not read an assistant's own memory.

## Off by default

Automatic capture is **disabled** until you explicitly enable it:

> Turn on MemorySafe automatic mode.

Even then, the assistant recognises and submits each candidate itself — MemorySafe never
watches a conversation on its own. Manual saves always require you to ask.

## What it refuses to store

Automatic capture will not save assistant-generated text, inferences, passing remarks,
passwords, API keys, payment or government identifiers, contact details, precise
addresses, or medical information. These are refusals, not settings. Keeping other
people's personal details out is a rule the assistant is told to follow; the server does
not yet enforce it.

## Installed MemorySafe by hand before?

Then it is registered twice. Ask your assistant to run MemorySafe's migrate command, or
run it yourself; it shows what it would change and changes nothing without `--apply`:

    ~/.local/share/MemorySafe/bin/memorysafe migrate                  # Linux
    ~/Library/Application\ Support/MemorySafe/bin/memorysafe migrate  # macOS
    %LOCALAPPDATA%\MemorySafe\bin\memorysafe.cmd migrate              # Windows

## About the numbers

Live token counts are exact measurements of what MemorySafe holds locally. The savings
figure shown next to them is a **modelled estimate**, not anyone's billed usage, and it is
labelled as such wherever it appears.
