"""Where this person chose to keep their memories: on this computer, or in their hosted account.

MemorySafe is one product with two places a memory can live. The local edition is this
package: one SQLite file on this computer, no network. The hosted edition is the same
engine behind https://memory.memorysafe.ca, which each assistant connects to as a remote
connector through its own settings. Until now the two read as two products, and a person
who used both had assistants answering from two memories without anything saying so.

This module records the person's one choice, made on the dashboard. The record is a
Connect-layer decision, not a storage switch: writing it moves no memories, uploads
nothing, and changes nothing about the local store or any assistant's existing
connection. What it changes is what MemorySafe offers next:

- `local` (the default, and the only mode until the person chooses): the dashboard's
  assistants panel connects assistants to the local plugin, exactly as before.
- `hosted`: the panel stops offering the local plugin -- including the one-time
  "connect your other assistants too?" start-up connect, which must not install local
  plugins the person has decided against -- and points at the hosted Connect page
  instead, where each assistant's own steps live. An assistant that already has the
  plugin needs nothing more: once this computer is signed in (device_link), the plugin's
  tools are answered by the account (hosted_proxy) and its hooks leave the local file
  alone. Moving the memories themselves stays what it was: the person exports here and
  imports on their account page.

The record lives beside connect-decision.json in the state dir, owner-readable JSON,
because it is this computer's setup state: it is not a memory, it must be readable
before any store opens, and the hosted edition must never see or need it.
"""

from __future__ import annotations

from pathlib import Path

from .device import read_private_json, utc_now, write_private_json

MODE_FILE = "storage-mode.json"
LOCAL = "local"
HOSTED = "hosted"
MODES = (LOCAL, HOSTED)
# The hosted edition's public page of per-assistant connect steps. A link, never fetched
# from here: this module adds no network call.
HOSTED_CONNECT_URL = "https://memory.memorysafe.ca/connect"


def read_storage_mode(state_dir: Path) -> str:
    """The chosen mode, `local` unless the record plainly says `hosted`.

    Anything unreadable, missing or unexpected is `local`: the default must match what
    MemorySafe does when the person has decided nothing, and a half-written file must
    not strand them in a mode they did not choose.
    """

    value = read_private_json(state_dir / MODE_FILE).get("mode")
    return HOSTED if value == HOSTED else LOCAL


def write_storage_mode(state_dir: Path, mode: str) -> None:
    """Record the person's choice. Only the two known modes are accepted."""

    if mode not in MODES:
        raise ValueError("Choose local or hosted.")
    record = read_private_json(state_dir / MODE_FILE)
    record.update(mode=mode, decided_at=utc_now())
    write_private_json(state_dir / MODE_FILE, record)
