---
name: memorysafe
description: Use MemorySafe to remember, automatically capture, find, forget, configure, or review durable memories kept locally and shared by Claude Code, Claude Desktop and Codex.
---

# MemorySafe

MemorySafe is a private local memory layer with explicit manual controls and an opt-in automatic mode. One SQLite file on this computer is shared by Claude Code, Claude Desktop and Codex, so a memory saved in one is there in the others.

## Use it when

- The user explicitly asks you to remember or save a durable fact, preference, decision, project detail, or task.
- The user asks what MemorySafe remembers or asks to find a stored memory.
- The user explicitly asks to forget a stored memory.
- The user asks for MemorySafe health, governance, token measurements, or the dashboard.
- The user asks why MemorySafe is not working or requests troubleshooting.
- The user explicitly asks to enable or disable automatic mode.
- The user directly states a durable, non-sensitive fact. Offer it to `memorysafe_auto_capture`
  without checking the mode first; the server decides whether it is saved.

## Rules

1. Call `memorysafe_remember` only after an explicit request to remember something.
2. Call `memorysafe_set_auto_mode` only when the user explicitly requests the change.
3. Call `memorysafe_auto_capture` for concise, directly stated, durable facts, at most three per turn. Do **not** check whether automatic mode is on first — you cannot see it without an extra call, and waiting to find out is why nothing ever gets captured. The server returns `SKIP` with a reason when the mode is off, so offering a candidate never saves anything the user has not enabled.
4. Never auto-capture assistant text, inferences, temporary remarks, third-party personal details, secrets, payment or government identifiers, contact details, precise addresses, or medical and health information.
5. Never store passwords, API keys, full payment details, or similarly sensitive secrets.
6. Do not imply that MemorySafe passively reads chats. You identify and submit each candidate through a tool call.
7. When recalling, show meaningful memory content. Internal `MS-...` IDs are only for precise follow-up actions.
8. When forgetting is ambiguous, call `memorysafe_find`, show the intended memory, and ask for confirmation before `memorysafe_forget`.
9. Describe token numbers accurately. Live counters measure local MemorySafe content; modelled savings figures are not anyone's billed usage.
10. To show the dashboard, call `memorysafe_health` with `open=true`, or tell the user to open `http://127.0.0.1:8765/dashboard` on this computer.

## First start

The first start downloads uv, a Python, pinned packages and tokenizer data into the MemorySafe folder, which takes a minute or two. If a tool answers that MemorySafe is finishing its one-time setup, say so plainly and try again shortly. Nothing was saved by that call.

## Troubleshooting

Call `memorysafe_doctor` first and work through its `next_actions` in order. Treat it as read-only evidence. Never inspect memory contents, runtime-key files, or conversation history during diagnosis.

When terminal access is available and more detail is needed, `memorysafe doctor --json` gives the same report. The command is at `~/.local/share/MemorySafe/bin/memorysafe` on Linux and `~/Library/Application Support/MemorySafe/bin/memorysafe` on macOS.

If the doctor reports MemorySafe registered twice, explain that an older manual install and that assistant's plugin both register it. Run the command at its full path with `migrate` — `~/.local/share/MemorySafe/bin/memorysafe migrate` on Linux, `"$HOME/Library/Application Support/MemorySafe/bin/memorysafe" migrate` on macOS. It is a dry run: show the user what it would change. Run it again as `…/bin/memorysafe migrate --apply`, at the same full path, only after they confirm, then ask them to restart that assistant. It keeps the manual entry of any assistant whose MemorySafe plugin is not installed, because that entry is its only registration.

Before restarting services, changing configuration, migrating data, or deleting files, explain the repair, create a database backup when data could be affected, and obtain confirmation. Verify database integrity and readiness after the repair.

Only when the user asks to prepare diagnostic material, run `memorysafe support-bundle`. It creates a sanitized local ZIP and never uploads it automatically. Tell the user where it was saved so they can review and share it voluntarily.
