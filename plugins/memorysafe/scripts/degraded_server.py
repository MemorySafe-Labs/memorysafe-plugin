#!/usr/bin/env python3
"""A MemorySafe server that starts when MemorySafe cannot.

The real server needs a private runtime. When building that runtime fails - no
Python, no network, a locked-down machine, a broken manifest - the launcher used
to print to stderr and exit non-zero. Claude Desktop shows that as "Server
disconnected", every MemorySafe tool disappears, and the one tool that could
explain the failure is inside the process that did not start. A beta tester spent
an evening reverse-engineering a manifest because of it.

So this starts instead. It speaks just enough MCP to connect and offer a single
tool, memorysafe_doctor, which reports what actually went wrong in words the
person can act on. The assistant is already sitting there; it can do the
troubleshooting itself if we give it something to call.

Hard constraints, because this runs precisely when nothing else does:
  - standard library only, no imports from memorysafe_chatgpt
  - no venv, no pip, no network
  - old interpreters welcome: this must run on whatever Python was found
  - nothing but JSON-RPC may ever reach stdout
"""

import json
import os
import platform
import re
import sys

PROTOCOL_VERSION = "2024-11-05"
MAX_LOG_LINES = 25


def _catalog_version():
    """The version bootstrap_catalog declares, read as text.

    Importing the package is exactly what this server must never need, and a hardcoded
    string here went stale at every release.
    """

    here = os.path.dirname(os.path.abspath(__file__))
    catalog = os.path.join(here, os.pardir, "src", "memorysafe_chatgpt", "bootstrap_catalog.py")
    try:
        with open(catalog, "r", encoding="utf-8") as handle:
            match = re.search(r'^VERSION = "([^"]+)"', handle.read(), re.MULTILINE)
    except OSError:
        return "unknown"
    return match.group(1) if match else "unknown"


def _log(message):
    sys.stderr.write("memorysafe-degraded: " + str(message) + "\n")
    sys.stderr.flush()


def _read_log_tail(path):
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "r", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError as error:
        return ["(could not read the install log: %s)" % error]
    return [line for line in lines[-MAX_LOG_LINES:] if line.strip()]


def _writable(path):
    if not path:
        return None
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".memorysafe-write-probe")
        with open(probe, "w") as handle:
            handle.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def explain(reason):
    """A headline for one setup failure, and what to do about it, in order.

    The bootstrap proxy's progress page shows a failed build in these same words, so the
    page and this server's doctor cannot describe one failure two ways. Builds a new list on
    every call: _diagnose inserts into the one it gets back.
    """

    if reason == "no_python":
        headline = (
            "MemorySafe could not find Python 3.10 or later on this computer, so it "
            "could not build the small private runtime it needs."
        )
        actions = [
            "Install Python from https://www.python.org/downloads/ - on Windows, tick "
            "\"Add python.exe to PATH\" during setup.",
            "Quit your assistant completely and reopen it.",
            "Ask me to check MemorySafe again.",
        ]
    elif reason == "runtime_build_failed":
        headline = (
            "MemorySafe found Python but could not finish building its private "
            "runtime. The install log below says why."
        )
        actions = [
            "Check the last lines of the install log for the real error.",
            "A company-managed machine or an offline network usually blocks this step, "
            "because building the runtime downloads a few packages.",
            "Quit your assistant completely and reopen it, and ask me to check again.",
        ]
    elif reason == "download_failed":
        headline = (
            "MemorySafe could not download the tool it uses to set itself up. This computer "
            "is probably offline, or a network proxy is blocking GitHub."
        )
        actions = [
            "Check that this computer can reach github.com, then quit your assistant "
            "completely and reopen it.",
            "On a company network, ask IT whether downloads from github.com and pypi.org "
            "are allowed.",
            "If uv is already installed, MemorySafe can use it: set MEMORYSAFE_UV to its "
            "full path.",
        ]
    elif reason == "uv_checksum_mismatch":
        headline = (
            "MemorySafe downloaded its setup tool, but the file did not match its recorded "
            "checksum, so it was deleted without being run."
        )
        actions = [
            "Quit your assistant completely and reopen it to download it again.",
            "If this happens twice, something between this computer and GitHub is changing "
            "downloads. Report it rather than retrying.",
        ]
    elif reason == "install_root_unwritable":
        headline = "MemorySafe cannot write to its data folder, so it cannot set itself up."
        actions = [
            "Check that the MemorySafe folder in your user account is not read-only.",
            "Quit your assistant completely and reopen it.",
        ]
    else:
        headline = "MemorySafe started in a limited mode and cannot store memories yet."
        actions = [
            "Quit your assistant completely and reopen it.",
            "Ask me to check MemorySafe again.",
        ]
    return headline, actions


def _diagnose():
    """Everything that can be established without the runtime."""

    reason = os.environ.get("MEMORYSAFE_DEGRADED_REASON", "unknown")
    root = os.environ.get("MEMORYSAFE_INSTALL_ROOT", "")
    log_path = os.environ.get("MEMORYSAFE_INSTALL_LOG", "")
    version = "%d.%d.%d" % sys.version_info[:3]
    old_python = sys.version_info[:2] < (3, 10)

    headline, actions = explain(reason)

    if reason == "no_python" and old_python:
        # Only here is this interpreter's age the problem: the pip launcher found nothing
        # newer to build with. Every other reason comes from the uv path, whose runtime
        # Python is downloaded, while the fallback runs on the system python3 (3.9 from
        # the Command Line Tools, 3.8 on older Ubuntu). Opening every uv failure by calling
        # that Python too old sends people to install one that fixes nothing.
        actions.insert(
            0,
            "The Python running this fallback is %s, which is older than the 3.10 "
            "MemorySafe needs." % version,
        )

    return {
        "status": "degraded",
        "memorysafe_working": False,
        "headline": headline,
        "what_to_do": actions,
        "reason_code": reason,
        "install_root": root or "(not set)",
        "install_root_writable": _writable(root),
        "fallback_python": version,
        "platform": platform.platform(),
        "install_log": log_path or "(none)",
        "install_log_tail": _read_log_tail(log_path),
        "note": (
            "No memories have been lost. MemorySafe never started, so nothing was "
            "written. Any existing store is untouched."
        ),
        "for_the_assistant": (
            "Tell the user the headline in your own words, then walk them through "
            "what_to_do in order. Do not read the reason code or the log tail aloud "
            "unless they ask or nothing else has worked."
        ),
    }


TOOL = {
    "name": "memorysafe_doctor",
    "description": (
        "Explain why MemorySafe is not working on this computer and what to do about "
        "it. MemorySafe is running in a limited mode: it cannot store or recall "
        "memories until the problem below is fixed. Call this whenever the user asks "
        "about MemorySafe, says it is not working, or wonders why its other tools are "
        "missing - and before suggesting a reinstall."
    ),
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
}


def _result(request_id, payload):
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _handle(message):
    method = message.get("method")
    request_id = message.get("id")

    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "memorysafe-degraded", "version": _catalog_version()},
                "instructions": (
                    "MemorySafe is installed but not working on this computer. Call "
                    "memorysafe_doctor to find out why and how to fix it. Do not tell "
                    "the user MemorySafe is remembering anything - it is not."
                ),
            },
        )
    if method == "tools/list":
        return _result(request_id, {"tools": [TOOL]})
    if method == "tools/call":
        report = _diagnose()
        return _result(
            request_id,
            {
                "content": [{"type": "text", "text": json.dumps(report, indent=2)}],
                "structuredContent": report,
                "isError": False,
            },
        )
    if method == "ping":
        return _result(request_id, {})
    if method in ("resources/list", "prompts/list"):
        key = method.split("/")[0]
        return _result(request_id, {key: []})
    if request_id is None:
        # A notification. Nothing to answer, and answering would be a protocol error.
        return None
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": "MemorySafe is in limited mode: %s is unavailable." % method},
    }


def main():
    # Python opens stdout with newline=None on Windows, which rewrites every "\n" this
    # process writes to "\r\n" -- and stdout is the JSON-RPC channel every reply travels
    # over. Reconfigured first, before the loop below can write anything.
    sys.stdout.reconfigure(newline="")
    _log("started in limited mode: " + os.environ.get("MEMORYSAFE_DEGRADED_REASON", "unknown"))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        try:
            reply = _handle(message)
        except Exception as error:  # never take the transport down
            _log("handler error: %s" % error)
            continue
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
