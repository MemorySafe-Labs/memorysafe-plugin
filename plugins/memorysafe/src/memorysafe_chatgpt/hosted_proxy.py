"""Hosted mode's store: the same tools, served by the person's own hosted account.

When the person chose "In my hosted account" on the dashboard (storage_mode.HOSTED) and this
computer is signed in (device_link), every memory tool the assistants call on this computer
is answered by the hosted edition at the account's origin, over MCP: the local tool forwards
its own name and arguments as a `tools/call` to the account's `/mcp` and returns what comes
back. The hosted edition runs the same engine, so the result has the same shape; the server
is the one place the memories live, and nothing is cached here. The local SQLite file is not
read or written in hosted mode. Its memories stay untouched until the person comes back.

What this module promises:
  * No call leaves this computer unless hosted mode is chosen AND the tool was called. Local
    mode never imports this module's network path; server._hosted_mode() is the one switch.
  * One bearer per call, from device_link.access_token: refreshed first when it is about to
    expire, never logged, never in a result.
  * A failure says, in one sentence the person can act on, what it means for their memories:
    device_link.NOT_LINKED, device_link.SIGN_IN_AGAIN, device_link.OFFLINE, and, for a write
    the server may or may not have finished, UNSURE. Nothing is retried blindly: a retried
    write could store a memory twice, and a retried refresh could sign every computer out.
  * The hosted edition's own refusals (an org that is read-only, a memory that is not yours)
    pass through in the server's words, since they were written for the person.

The cost: the proxy adds a network round trip to every tool call. measure() times it on the
real hosted app, run as `memorysafe hosted-latency`; a median above STOP_LINE_MS on a home
connection is too slow to release.
"""

from __future__ import annotations

import http.client
import json
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from . import device, device_link, storage_mode

MCP_PATH = "/mcp"
# The hosted edition's stateless transport answers a bare tools/call; this is the handshake
# version its own tests send.
PROTOCOL_VERSION = "2025-06-18"
HTTP_TIMEOUT_SECONDS = 20
STOP_LINE_MS = 300

UNSURE = (
    "Your hosted account did not confirm this change; it may or may not have been saved. "
    "Search for it before repeating it."
)
UNREADABLE = "Your hosted account answered in a form this plugin does not understand; update the plugin."
# The same answer to a write: the account said yes to something, in words this plugin cannot read.
UNSURE_UNREADABLE = (
    "Your hosted account answered in a form this plugin does not understand, so this change may "
    "or may not have been saved. Search for it before repeating it, and update the plugin."
)

# A read that times out changed nothing, so it is OFFLINE; a write that times out may have
# landed, so it is UNSURE. memorysafe_health is a read.
READ_ONLY_TOOLS = frozenset(
    {"memorysafe_find", "memorysafe_explain", "memorysafe_review_conflicts", "memorysafe_health"}
)

# (url, body, headers) -> (status, raw body). Replaceable so the tests never open a socket.
PostCall = Callable[[str, bytes, dict[str, str]], tuple[int, bytes]]


class HostedError(RuntimeError):
    """The hosted edition refused or could not answer; the message is written for the person."""


def active(state_dir: Path | None = None) -> bool:
    """Whether this computer's tools are served by the hosted account (the mode file says so)."""

    return storage_mode.read_storage_mode(state_dir or device.default_state_dir()) == storage_mode.HOSTED


def _post(url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
    if not url.startswith("https://"):
        raise OSError(f"refusing a token over plain http: {url}")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with device_link.open_without_redirects(request, HTTP_TIMEOUT_SECONDS) as response:  # https only, no redirect
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


# What a call can fail with once the request may already be with the account: no answer in
# time, a connection dropped or reset, an answer cut short. A refused connection or a name
# that does not resolve is not in this list: nothing was sent.
_MAYBE_SENT = (TimeoutError, ConnectionResetError, ConnectionAbortedError, BrokenPipeError, http.client.HTTPException)


def _maybe_sent(error: BaseException) -> bool:
    return isinstance(error, _MAYBE_SENT) or isinstance(getattr(error, "reason", None), _MAYBE_SENT)


def call(
    name: str,
    arguments: dict[str, Any],
    *,
    state_dir: Path | None = None,
    post: PostCall | None = None,
    now: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """One tool call on the hosted account; the tool's structured result as a dict.

    Raises device_link.LinkError with NOT_LINKED, SIGN_IN_AGAIN or OFFLINE, or HostedError
    with UNSURE, UNREADABLE or the server's own refusal."""

    post = post or _post
    state_dir = state_dir or device.default_state_dir()
    token = device_link.access_token(state_dir, now=now)
    record = device_link.read_link(state_dir)
    if not record:
        raise device_link.LinkError(device_link.NOT_LINKED, linked=False)
    url = str(record["issuer"]).rstrip("/") + MCP_PATH
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    ).encode("utf-8")
    write = name not in READ_ONLY_TOOLS

    status, raw = _send(url, body, token, post, write=write)
    if status == 401:
        # The server stopped honouring a token it issued (a sign-in ended on the server, a
        # key rotated). One refresh, then the honest sentence; never a loop.
        device_link.forget_access_token(state_dir, spent=token)
        token = device_link.access_token(state_dir, now=now)
        status, raw = _send(url, body, token, post, write=write)
        if status == 401:
            raise device_link.LinkError(device_link.SIGN_IN_AGAIN, linked=True)
    if status != 200:
        if write and status >= 500:
            # A gateway error can come back after the account committed the write. "Your
            # memories were not changed" would be a guess, and a retry would store it twice.
            raise HostedError(UNSURE)
        raise device_link.LinkError(device_link.OFFLINE, linked=True)
    try:
        return _result(name, raw)
    except HostedError as error:
        if write and str(error) == UNREADABLE:
            raise HostedError(UNSURE_UNREADABLE) from None
        raise


def _send(url: str, body: bytes, token: str, post: PostCall, *, write: bool) -> tuple[int, bytes]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        "Authorization": f"Bearer {token}",
    }
    try:
        return post(url, body, headers)
    except (OSError, http.client.HTTPException) as error:
        if write and _maybe_sent(error):
            raise HostedError(UNSURE) from None
        raise device_link.LinkError(device_link.OFFLINE, linked=True) from None


def _result(name: str, raw: bytes) -> dict[str, Any]:
    try:
        message = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise HostedError(UNREADABLE) from None
    if not isinstance(message, dict):
        raise HostedError(UNREADABLE)
    if isinstance(message.get("error"), dict):
        # A protocol-level refusal (unknown tool, bad arguments): the server's words.
        raise HostedError(str(message["error"].get("message") or UNREADABLE))
    result = message.get("result")
    if not isinstance(result, dict):
        raise HostedError(UNREADABLE)
    texts = [str(part.get("text", "")) for part in result.get("content", []) if isinstance(part, dict) and part.get("type") == "text"]
    if result.get("isError"):
        text = " ".join(texts).strip()
        prefix = f"Error executing tool {name}: "
        if text.startswith(prefix):
            text = text[len(prefix):]
        raise HostedError(text or UNREADABLE)
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for text in texts:
        try:
            parsed = json.loads(text)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise HostedError(UNREADABLE)


def measure(
    local_find: Callable[[], Any],
    *,
    samples: int = 20,
    state_dir: Path | None = None,
    post: PostCall | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """The stop-line measurement: the median a hosted find adds over a local one.

    `local_find` is the same call on the local file. Each sample is one
    memorysafe_review_conflicts, a real call through the account's sign-in, scope and
    database that writes nothing. It was a find, and a find is a use: one run added twenty
    to a memory's use count, which now orders what a session carries. Medians, not means:
    one slow sample on a home connection should not decide."""

    samples = max(1, int(samples))

    def timed(action: Callable[[], Any]) -> float:
        started = clock()
        action()
        return (clock() - started) * 1000

    local = sorted(timed(local_find) for _ in range(samples))
    hosted = sorted(
        timed(lambda: call("memorysafe_review_conflicts", {"include_resolved": False}, state_dir=state_dir, post=post))
        for _ in range(samples)
    )
    local_median = statistics.median(local)
    hosted_median = statistics.median(hosted)
    added = max(0.0, hosted_median - local_median)
    return {
        "samples": samples,
        "local_median_ms": round(local_median, 1),
        "hosted_median_ms": round(hosted_median, 1),
        "hosted_slowest_ms": round(hosted[-1], 1),
        "added_median_ms": round(added, 1),
        "stop_line_ms": STOP_LINE_MS,
        "within_stop_line": added < STOP_LINE_MS,
    }
