"""How many memories a plan holds, and how this computer knows its plan.

MemorySafe is one product with a free plan and a paid one, on either kind of storage. The
only thing a plan changes in the engine is how many active memories the store accepts. This
module names no size: a hosted account's limit comes from the account, and a plan key
carries its own.

What happens at the limit is the same on every plan and every backend, and it is the rule
the hosted edition has had since October 2026: a full store stops accepting NEW memories
and says so; it never drops, evicts or fades one to make room. Saying a fact again still
merges, a correction still replaces the fact it corrects, and forgetting or erasing frees
room. Nothing here removes anything.

Where the plan comes from:
  * Hosted storage: the account (private; this module only supplies the numbers).
  * Local storage: a plan key, a short signed text the person copies from their account
    page. It is checked on this computer against PUBLIC_KEYS with no network call, so the
    local edition stays offline, and no sign-in is left on a computer whose memories live
    here. An absent, unreadable, expired or wrongly signed key is the free plan.

The local limit is enforced only when PUBLIC_KEYS holds at least one key and
FREE_MAX_ACTIVE is set. Both ship empty: a limit nobody can lift is a wall, not a plan, and
the production signing key and the free plan's size are set when paid plans are sold. Until
then the local edition has no limit, exactly as before. Setting both in a release is what
turns the local free limit on; `MEMORYSAFE_PLAN_PUBLIC_KEY` and `MEMORYSAFE_PLAN_FREE_LIMIT`
do the same for a staging or test install.

This is a plan, not a lock. The store is a file on the person's own computer and the
code is theirs to read; the key keeps honest people honest and nothing more.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

FREE = "free"
PAID = "paid"
BETA = "beta"
PLANS = (FREE, PAID, BETA)

# How many active memories a local store holds with no plan key. None until plans are
# announced: no size is published in this file before then.
FREE_MAX_ACTIVE: Optional[int] = None

# Ed25519 public keys (URL-safe base64, 32 bytes) whose signatures on a plan key are
# accepted. Empty: the local limit is not enforced. See the module docstring.
PUBLIC_KEYS: tuple[str, ...] = ()

PLAN_FILE = "plan.json"
KEY_PREFIX = "msplan1"


def free_limit() -> Optional[int]:
    """The free plan's size on this computer, or None while none is set."""

    configured = os.environ.get("MEMORYSAFE_PLAN_FREE_LIMIT", "").strip()
    if configured:
        try:
            value = int(configured)
        except ValueError:
            return None
        return value if value > 0 else None
    return FREE_MAX_ACTIVE


def full_reason(used: int, limit: int, plan: str) -> str:
    """What a save is told when the store is full. Names no memory text."""

    plan_name = "Free" if plan == FREE else "your"
    room = (
        "Forget or erase memories you no longer need, or move to a paid plan for more room."
        if plan == FREE
        else "Forget or erase memories you no longer need."
    )
    return (
        f"Nothing was saved: this memory store is full ({used:,} of {limit:,} on {plan_name} plan). "
        f"Nothing was removed to make room. {room}"
    )


def _public_keys() -> tuple[str, ...]:
    configured = os.environ.get("MEMORYSAFE_PLAN_PUBLIC_KEY", "").strip()
    return PUBLIC_KEYS + ((configured,) if configured else ())


def enforced() -> bool:
    """Whether this build can check a plan key and knows the free plan's size, and so
    whether the local limit applies."""

    return bool(_public_keys()) and free_limit() is not None


def _b64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def read_key(key: str, now: Optional[float] = None) -> Optional[dict[str, Any]]:
    """The claims of a plan key ({plan, max, exp}) if one of PUBLIC_KEYS signed it and it
    has not expired; otherwise None. `max` is how many active memories the plan holds: the
    key carries it, so this file needs no table of sizes. Never raises: a bad key is no key."""

    parts = str(key or "").strip().split(".")
    if len(parts) != 3 or parts[0] != KEY_PREFIX:
        return None
    try:
        payload, signature = _b64(parts[1]), _b64(parts[2])
        claims = json.loads(payload.decode("utf-8"))
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None
    if not isinstance(claims, dict) or claims.get("plan") not in PLANS:
        return None
    try:
        expires = float(claims.get("exp", 0))
        size = int(claims.get("max", 0))
    except (TypeError, ValueError):
        return None
    if size <= 0:
        return None
    if expires <= (time.time() if now is None else now):
        return None
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:  # the system Python a hook may run under: no key can be checked
        return None
    for public in _public_keys():
        try:
            Ed25519PublicKey.from_public_bytes(_b64(public)).verify(signature, parts[1].encode("ascii"))
        except (InvalidSignature, ValueError, binascii.Error):
            continue
        return claims
    return None


def state_dir_for(database_path: Path) -> Path:
    """Where this install keeps its setup records: MEMORYSAFE_STATE_DIR, else beside data/."""

    configured = os.environ.get("MEMORYSAFE_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(database_path).parent.parent / "runtime-state"


def stored_key(state_dir: Path) -> str:
    try:
        record = json.loads((Path(state_dir) / PLAN_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(record.get("key", "")) if isinstance(record, dict) else ""


def store_key(state_dir: Path, key: str) -> dict[str, Any]:
    """Keep a plan key on this computer, after checking it. Raises ValueError when it is not
    one this build accepts, so a mistyped key is never stored as if it worked."""

    claims = read_key(key)
    if claims is None:
        raise ValueError(
            "That plan key was not accepted: it is mistyped, has expired, or was not issued for "
            "this version of MemorySafe. Copy it again from your account page."
        )
    folder = Path(state_dir)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / PLAN_FILE
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump({"key": key.strip()}, handle)
        handle.write("\n")
    return claims


def remove_key(state_dir: Path) -> bool:
    try:
        (Path(state_dir) / PLAN_FILE).unlink()
        return True
    except FileNotFoundError:
        return False


def local_plan(database_path: Path) -> dict[str, Any]:
    """This computer's plan for the store at `database_path`.

    {"enforced": False} while no key can be checked (no limit, as before). Otherwise the
    plan named by a valid stored key, or free, with its limit and the key's expiry.
    """

    if not enforced():
        return {"enforced": False, "plan": None, "limit": None, "expires_at": None}
    claims = read_key(stored_key(state_dir_for(database_path)))
    return {
        "enforced": True,
        "plan": str(claims["plan"]) if claims else FREE,
        "limit": int(claims["max"]) if claims else free_limit(),
        "expires_at": float(claims["exp"]) if claims else None,
    }
