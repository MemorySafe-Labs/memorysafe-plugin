# MemorySafe 0.4.1

Private, governed memory for Claude Code, Claude Desktop and Codex, kept in one SQLite
file on your own computer. macOS, Linux and Windows.

## Claude Code

    claude plugin marketplace add MemorySafe-Labs/memorysafe-plugin
    claude plugin install memorysafe@memorysafe

## Codex

    codex plugin marketplace add MemorySafe-Labs/memorysafe-plugin
    codex plugin add memorysafe@memorysafe

Codex asks you to trust the plugin's hook before running it. MemorySafe works without
it: the hook only makes automatic capture fire more reliably once you turn that on.

## Claude Desktop

Download https://github.com/MemorySafe-Labs/memorysafe-plugin/releases/latest/download/memorysafe-claude-desktop.mcpb
and open it with Claude Desktop.

## First start

The first time an assistant starts MemorySafe, it downloads uv from GitHub, a Python
build through uv, hash-pinned packages from PyPI, and the tokenizer data it counts tokens
with, all into the MemorySafe folder. That takes a minute or two. After that, nothing
leaves this computer. On a network that blocks GitHub, set MEMORYSAFE_UV to a uv you
already have, or HTTPS_PROXY to your proxy.

## Installed MemorySafe by hand before?

Then it is registered twice. Ask your assistant to run MemorySafe's migrate command, or
run it yourself; it shows what it would change and changes nothing without --apply:

    ~/.local/share/MemorySafe/bin/memorysafe migrate                  # Linux
    ~/Library/Application\ Support/MemorySafe/bin/memorysafe migrate  # macOS
