from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PRODUCT = "MemorySafe Beta"
DIAGNOSTIC_SCHEMA_VERSION = 2
MAX_ERROR_SOURCE_BYTES = 128 * 1024
MAX_ERROR_EVENTS = 80

_SECRET = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_TUNNEL_ID = re.compile(r"\btunnel_[A-Za-z0-9]+\b")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_LONG_NUMBER = re.compile(r"\b\d{12,19}\b")
_ERROR_MARKERS = (
    "error",
    "traceback",
    "exception",
    "failed",
    "permission denied",
    "operation not permitted",
    "address already in use",
    "fork/exec",
)

# One memory directory can serve more than one assistant: the ChatGPT connector
# installs a .venv plus tunnel client, and the Claude extension builds its own
# claude-runtime alongside it. A check that assumes either one is the whole
# product reports failures for files the other install never ships, so every
# assistant-specific check below is gated on the runtime actually being present.
CHATGPT_RUNTIME = "chatgpt"
CLAUDE_RUNTIME = "claude"
# The plugins keep their code in the plugin folder and publish runtimes keyed by their
# lock under runtime/<key>/, each complete once its ready marker exists.
PLUGIN_RUNTIME = "plugin"
_LAUNCH_LABELS = ("ca.memorysafe.beta.setup", "ca.memorysafe.beta.tunnel")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _display_path(path: Path) -> str:
    """A path a person can read back, and type.

    Claude Desktop ships as an MSIX package, and Windows redirects LOCALAPPDATA for
    packaged apps into AppData\\Local\\Packages\\Claude_<publisher-hash>\\LocalCache.
    Collapsing only the home prefix left that whole path in the report, which is not
    something a user recognises as their MemorySafe folder or can retype. The
    resolved path is still reported, under real_path, for --json and support bundles.

    The separator is written literally rather than via Path, so the string is the
    same when these tests run off Windows. Branches on sys.platform to match
    DoctorPaths.from_install_root, which is what built the path being displayed.
    """
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            try:
                relative = path.resolve().relative_to(Path(local).resolve())
            except (OSError, ValueError):
                relative = None
            if relative is not None:
                return "%LOCALAPPDATA%\\" + str(relative).replace("/", "\\")
    try:
        return f"~/{path.resolve().relative_to(Path.home().resolve())}"
    except (OSError, ValueError):
        return str(path)


def redact(text: str) -> str:
    """Remove secrets and direct personal identifiers from diagnostic text."""
    value = text.replace(str(Path.home()), "~")
    value = _SECRET.sub("sk-[redacted]", value)
    value = _TUNNEL_ID.sub("tunnel_[redacted]", value)
    value = _EMAIL.sub("[email redacted]", value)
    value = _LONG_NUMBER.sub("[long number redacted]", value)
    return value


def _sanitize(value: Any) -> Any:
    """Apply redaction to every string in the report, not only error text.

    An install root outside the home directory keeps its absolute form in
    _display_path, and that path travels inside the support bundle.
    """
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _runtime_python(runtime_dir: str) -> str:
    """Interpreter path inside a private runtime, as the platform lays it out."""
    if os.name == "nt":
        return f"{runtime_dir}/Scripts/python.exe"
    return f"{runtime_dir}/bin/python"


@dataclass(frozen=True)
class DoctorPaths:
    install_root: Path
    database_path: Path
    state_dir: Path
    secret_file: Path
    tunnel_id_file: Path
    health_url_file: Path

    @classmethod
    def from_install_root(cls, install_root: Path | None = None) -> "DoctorPaths":
        # platform_default used to be computed as a plain statement above this branch,
        # so its Path.home() call ran unconditionally -- even for a caller who passed
        # install_root or set MEMORYSAFE_INSTALL_ROOT, whose value was going to win
        # anyway. Path.home() raises RuntimeError when it cannot resolve a home
        # directory (no USERPROFILE/HOMEDRIVE+HOMEPATH on Windows, no HOME and no
        # passwd entry on POSIX), so an override-set caller still crashed if that
        # branch's Path.home() would have raised, purely from computing a default that
        # was never going to be used. Each branch below now runs only when it is the
        # one actually needed, matching cli.py's _resolve_database.
        env_install_root = os.environ.get("MEMORYSAFE_INSTALL_ROOT")
        if install_root:
            root = Path(install_root)
        elif env_install_root:
            root = Path(env_install_root)
        elif sys.platform == "win32":
            root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "MemorySafe"
        elif sys.platform == "darwin":
            root = Path.home() / "Library" / "Application Support" / "MemorySafe"
        else:
            xdg = os.environ.get("XDG_DATA_HOME")
            root = (Path(xdg) if xdg else Path.home() / ".local" / "share") / "MemorySafe"
        root = root.expanduser().resolve()
        state = Path(os.environ.get("MEMORYSAFE_STATE_DIR", root / "runtime-state")).expanduser().resolve()
        return cls(
            install_root=root,
            database_path=Path(os.environ.get("MEMORYSAFE_DB_PATH", root / "data" / "memorysafe.sqlite3")).expanduser().resolve(),
            state_dir=state,
            secret_file=Path(os.environ.get("MEMORYSAFE_RUNTIME_KEY_FILE", root / ".secrets" / "tunnel-runtime-key")).expanduser().resolve(),
            tunnel_id_file=Path(os.environ.get("MEMORYSAFE_TUNNEL_ID_FILE", state / "tunnel-id")).expanduser().resolve(),
            health_url_file=Path(os.environ.get("MEMORYSAFE_HEALTH_URL_FILE", state / "health" / "tunnel.url")).expanduser().resolve(),
        )


@dataclass(frozen=True)
class Layout:
    """Which runtimes this memory directory actually contains."""

    runtimes: tuple[str, ...]
    is_extension_bundle: bool

    @property
    def has_chatgpt(self) -> bool:
        return CHATGPT_RUNTIME in self.runtimes

    @property
    def has_claude(self) -> bool:
        return CLAUDE_RUNTIME in self.runtimes

    @property
    def has_plugin(self) -> bool:
        return PLUGIN_RUNTIME in self.runtimes


def detect_layout(root: Path) -> Layout:
    runtimes: list[str] = []
    if (root / "config" / "tunnel-client").is_dir() or (root / "scripts" / "run_tunnel_service.sh").is_file():
        runtimes.append(CHATGPT_RUNTIME)
    elif (root / _runtime_python(".venv")).is_file():
        runtimes.append(CHATGPT_RUNTIME)
    if (root / "claude-runtime").is_dir():
        runtimes.append(CLAUDE_RUNTIME)
    if any((root / "runtime").glob("*/ready")):
        runtimes.append(PLUGIN_RUNTIME)
    # The Claude extension directory ships the code but is not the memory
    # directory, so pointing the doctor at it should say so rather than list
    # every runtime file it was never meant to hold.
    bundle = not runtimes and (root / "mcpb_server.py").is_file() and (root / "manifest.json").is_file()
    return Layout(runtimes=tuple(runtimes), is_extension_bundle=bundle)


def _check(identifier: str, status: str, summary: str, **details: Any) -> dict[str, Any]:
    return {"id": identifier, "status": status, "summary": summary, "details": details}


def _url_ready(url: str, path: str, timeout: float = 0.6) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return False
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}{path}", timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError, ValueError):
        return False


def _dashboard_report(url: str = "http://127.0.0.1:8765") -> dict[str, Any] | None:
    """What the dashboard on the port says it is, or None if that is not one of ours.

    Deliberately a second, smaller reader rather than reusing
    claude_launcher._dashboard_status: importing claude_launcher pulls in server.py
    and the whole MCP stack, and doctor must stay runnable when that import is the
    thing that is broken.
    """
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return None
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/api/status", timeout=0.6) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("product") != PRODUCT:
        return None
    version = payload.get("version")
    if not isinstance(version, str):
        return None
    pid = payload.get("pid")
    return {"version": version, "pid": pid if isinstance(pid, int) and not isinstance(pid, bool) else None}


def _dashboard_version_check() -> dict[str, Any] | None:
    """Whether the dashboard answering on 8765 belongs to this install.

    The install instructions name that page as the proof an install worked, so a
    dashboard left by an older install confirms the wrong thing. A pre-0.4 one
    reports no PID, so it cannot be stopped from here -- only named, with the
    remedy pointed at the old extension that is holding the port.
    """
    from .bootstrap_catalog import VERSION

    running = _dashboard_report()
    if running is None:
        return None
    if running["version"] == VERSION:
        return _check(
            "dashboard_version",
            "pass",
            "The dashboard on port 8765 belongs to this install.",
            version=running["version"],
        )
    return _check(
        "dashboard_version",
        "warning",
        f"The dashboard on port 8765 is version {running['version']}, from an older install.",
        version=running["version"],
        expected=VERSION,
        stoppable=running["pid"] is not None,
    )


def _layout_check(paths: DoctorPaths, layout: Layout) -> dict[str, Any]:
    if layout.is_extension_bundle:
        return _check(
            "install_layout",
            "error",
            "This is the Claude extension folder, not your memory directory.",
            root=_display_path(paths.install_root),
            hint="Run the doctor against the memory directory you chose when installing.",
        )
    if not layout.runtimes:
        return _check(
            "install_layout",
            "error",
            "No MemorySafe runtime was found in this folder.",
            root=_display_path(paths.install_root),
            hint="Check the folder, or reinstall to build the runtime.",
        )
    assistants = {CHATGPT_RUNTIME: "ChatGPT", CLAUDE_RUNTIME: "Claude", PLUGIN_RUNTIME: "the Claude Code and Codex plugins"}
    present = ", ".join(assistants[name] for name in layout.runtimes)
    return _check(
        "install_layout",
        "pass",
        f"Installed for {present}.",
        root=_display_path(paths.install_root),
        runtimes=list(layout.runtimes),
    )


def _installation_check(paths: DoctorPaths, layout: Layout) -> dict[str, Any]:
    required: dict[str, tuple[str, ...]] = {}
    if layout.has_chatgpt:
        required[CHATGPT_RUNTIME] = (
            "src/memorysafe_chatgpt/server.py",
            "src/memorysafe_chatgpt/setup_app.py",
            "scripts/run_mcp_service.sh",
            "scripts/run_setup_service.sh",
            "scripts/run_tunnel_service.sh",
            _runtime_python(".venv"),
        )
    if layout.has_claude:
        # The Claude extension keeps its code in the extension folder and only
        # builds a private interpreter here, so that is all this root must hold.
        required[CLAUDE_RUNTIME] = (_runtime_python("claude-runtime"),)
    if layout.has_plugin:
        # Nothing else lives here for the plugin: its code is in the plugin folder.
        required[PLUGIN_RUNTIME] = ()

    missing = [
        f"{runtime}: {item}"
        for runtime, items in required.items()
        for item in items
        if not (paths.install_root / item).is_file()
    ]
    return _check(
        "installation",
        "error" if missing else "pass",
        "Installation is incomplete." if missing else "Required runtime files are installed.",
        root=_display_path(paths.install_root),
        checked_runtimes=list(required),
        missing=missing,
    )


def _memory_directory_check(paths: DoctorPaths) -> dict[str, Any]:
    data_dir = paths.database_path.parent
    problems: list[str] = []
    if not data_dir.is_dir():
        problems.append("The memory folder does not exist.")
    elif not os.access(data_dir, os.W_OK):
        problems.append("The memory folder is not writable.")
    return _check(
        "memory_directory",
        "error" if problems else "pass",
        "The memory folder needs attention." if problems else "The memory folder is writable.",
        path=_display_path(data_dir),
        real_path=str(data_dir),
        problems=problems,
    )


def _registration_check(home: Path) -> dict[str, Any]:
    from .migrate import (
        claude_code_plugin_installed,
        claude_config,
        claude_registration_present,
        codex_config,
        codex_plugin_installed,
        codex_registration_present,
    )

    # Both halves must be in the same assistant. The plugin runtime this check runs
    # beside is shared by every host, so it says nothing about the host holding a manual
    # entry, and the fix named below would remove that host's only registration.
    twice = [
        label
        for present, label in (
            (claude_registration_present(claude_config(home)) and claude_code_plugin_installed(home), "Claude Code"),
            (codex_registration_present(codex_config(home)) and codex_plugin_installed(home), "Codex"),
        )
        if present
    ]
    if not twice:
        return _check("registration", "pass", "No assistant has MemorySafe registered twice.")
    return _check(
        "registration",
        "warning",
        f"MemorySafe is registered twice in {' and '.join(twice)}: by the plugin and by an older manual install.",
        registered_twice=twice,
        fix="memorysafe migrate --apply",
    )


def _database_check(paths: DoctorPaths) -> dict[str, Any]:
    if not paths.database_path.is_file():
        return _check(
            "database",
            "warning",
            "No memories have been stored yet.",
            path=_display_path(paths.database_path),
            real_path=str(paths.database_path),
            hint="The database is created the first time MemorySafe saves something.",
        )
    try:
        connection = sqlite3.connect(f"file:{paths.database_path}?mode=ro", uri=True, timeout=2)
        try:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            active = int(connection.execute("SELECT COUNT(*) FROM memories WHERE state = 'active'").fetchone()[0])
            decisions = int(connection.execute("SELECT COUNT(*) FROM decision_events").fetchone()[0])
            automatic = connection.execute("SELECT value FROM settings WHERE key = 'automatic_mode'").fetchone()
        finally:
            connection.close()
    except (sqlite3.Error, OSError) as error:
        return _check("database", "error", "The database could not be inspected.", error=redact(str(error)))
    status = "pass" if integrity == "ok" else "error"
    return _check(
        "database",
        status,
        "Database integrity passed." if status == "pass" else "Database integrity failed.",
        path=_display_path(paths.database_path),
        real_path=str(paths.database_path),
        integrity=integrity,
        active_memories=active,
        decision_events=decisions,
        automatic_mode=bool(automatic and automatic[0] == "enabled"),
        bytes=paths.database_path.stat().st_size,
    )


def _configuration_check(paths: DoctorPaths) -> dict[str, Any]:
    """Tunnel wiring. Only meaningful where the ChatGPT connector is installed."""
    config = paths.install_root / "config" / "tunnel-client" / "memorysafe-runtime.json"
    problems: list[str] = []
    command = ""
    try:
        payload = json.loads(config.read_text(encoding="utf-8"))
        command = str(payload["mcp"]["commands"][0]["command"])
        if any(character.isspace() for character in command):
            problems.append("The MCP command contains whitespace.")
        if not Path(command).is_file():
            problems.append("The MCP wrapper is missing.")
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        problems.append("The tunnel runtime configuration is missing or invalid.")
    key_present = paths.secret_file.is_file() and paths.secret_file.stat().st_size >= 30
    tunnel_present = False
    try:
        tunnel_present = paths.tunnel_id_file.read_text(encoding="utf-8").strip().startswith("tunnel_")
    except OSError:
        pass
    if not key_present:
        problems.append("The private runtime key is missing.")
    if not tunnel_present:
        problems.append("The tunnel ID is missing.")
    # Never set up at all is not the same as broken. The ChatGPT runtime ships with
    # every install, so a Claude-only user who never touched ChatGPT had all four
    # pieces missing and was told their working installation was in "error" -- the
    # most alarming word available, for a feature they had chosen not to use.
    untouched = not any((config.is_file(), key_present, tunnel_present))
    if untouched:
        return _check(
            "configuration",
            "info",
            "ChatGPT support is installed but not set up. Claude and Claude Code do not need it.",
            config_present=False,
            wrapper_present=False,
            runtime_key_present=False,
            tunnel_id_present=False,
            problems=[],
            not_configured=True,
        )
    return _check(
        "configuration",
        "error" if problems else "pass",
        "ChatGPT connection configuration is incomplete." if problems else "ChatGPT connection configuration is valid.",
        config_present=config.is_file(),
        wrapper_present=bool(command and Path(command).is_file()),
        runtime_key_present=key_present,
        tunnel_id_present=tunnel_present,
        problems=problems,
    )


def _dashboard_check() -> dict[str, Any]:
    ready = _url_ready("http://127.0.0.1:8765", "/api/status")
    return _check(
        "dashboard_service",
        "pass" if ready else "warning",
        "Local dashboard is ready." if ready else "Local dashboard did not answer its health check.",
        url="http://127.0.0.1:8765/dashboard",
    )


def _private_connection_check(paths: DoctorPaths, configured: bool = True) -> dict[str, Any]:
    if not configured:
        return _check(
            "private_connection",
            "info",
            "The ChatGPT private connection is not in use.",
            health_file_present=False,
            not_configured=True,
        )

    try:
        health_url = paths.health_url_file.read_text(encoding="utf-8").strip()
    except OSError:
        health_url = ""
    ready = bool(health_url and _url_ready(health_url, "/readyz"))
    return _check(
        "private_connection",
        "pass" if ready else "warning",
        "Private ChatGPT connection is ready." if ready else "Private ChatGPT connection is not ready.",
        health_file_present=paths.health_url_file.is_file(),
    )


def _process_running(pattern: str) -> bool | None:
    """True/False when pgrep can answer, None when it cannot."""
    try:
        completed = subprocess.run(
            ["/usr/bin/pgrep", "-f", pattern],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode not in (0, 1):
        return None
    return bool(completed.stdout.strip())


def _launch_services_check() -> dict[str, Any] | None:
    """Registration and liveness are different facts, so report them separately.

    Reporting "unavailable" for a service whose process is running was wrong in
    both directions: it contradicted the connection check in the same report,
    and it hid the finding that actually matters, which is that nothing would
    come back after a restart.

    launchd is macOS-only, so there is nothing to check on Windows -- and nothing
    to widen the except for either. os.getuid() does not exist there, and
    AttributeError was never in the caught tuple, so a caller that dropped the
    run_doctor darwin gate crashed the whole report instead of skipping this check.
    """
    if os.name == "nt":
        return None
    patterns = {
        "ca.memorysafe.beta.setup": "memorysafe_chatgpt.setup_app",
        "ca.memorysafe.beta.tunnel": "tunnel-client run --config",
    }
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    services: dict[str, dict[str, Any]] = {}
    for label in _LAUNCH_LABELS:
        registered = False
        try:
            completed = subprocess.run(
                ["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            output = completed.stdout + completed.stderr
            registered = completed.returncode == 0 and "state = running" in output
        except (OSError, subprocess.TimeoutExpired):
            registered = False
        services[label] = {
            "registered": registered,
            "plist_present": (agents_dir / f"{label}.plist").is_file(),
            "process_running": _process_running(patterns[label]),
        }

    registered_all = all(item["registered"] for item in services.values())
    running_all = all(item["process_running"] is not False for item in services.values())
    if registered_all:
        status, summary = "pass", "Launch services are registered and running."
    elif running_all:
        status, summary = (
            "warning",
            "MemorySafe is running, but its services are not registered to start at login.",
        )
    else:
        status, summary = "warning", "One or more MemorySafe services are not running."
    return _check("launch_services", status, summary, services=services)


def _runtime_check(paths: DoctorPaths) -> dict[str, Any]:
    usage = shutil.disk_usage(paths.install_root)
    logs = paths.state_dir / "logs"
    sizes = {
        item.name: item.stat().st_size
        for item in sorted(logs.glob("*.log*"))
        if item.is_file()
    } if logs.is_dir() else {}
    oversized = [name for name, size in sizes.items() if size > 11 * 1024 * 1024]
    status = "warning" if usage.free < 250 * 1024 * 1024 or oversized else "pass"
    return _check(
        "runtime_resources",
        status,
        "Runtime resources need attention." if status == "warning" else "Disk space and runtime logs are within limits.",
        disk_free_bytes=usage.free,
        log_sizes=sizes,
        oversized_logs=oversized,
    )


def _capture_hook_check(plugin_root: Path | None = None) -> dict[str, Any] | None:
    """Whether the prompt-time capture nudge can run at all on this platform.

    plugin/hooks/hooks.json names one command for every platform -- Claude Code does
    not read a per-platform hook command (anthropics/claude-code#90122) -- and that
    command is "/bin/sh <root>/scripts/capture_hook". Windows has no /bin/sh, so the
    hook never fires there, and until this check existed nothing told the user.

    "info", not "warning", on purpose. run_doctor's own comment records that info is
    deliberately not a fault, and the gap is harmless: a hook that never runs cannot
    block a prompt. Automatic capture still works when the assistant calls
    memorysafe_auto_capture; only the nudge is missing.

    A sh/batch polyglot fix was written and reverted in a09de8b, because Windows CI
    produced failures that could not be attributed to the change rather than the
    runner -- including the hook exiting 1 with output, where the contract is exit 0
    and silence. That trade stands until hooks can be exercised under a real cmd.exe
    in CI, or upstream ships a per-platform hook command. Do not reopen it from here.

    Branches on sys.platform rather than os.name, matching DoctorPaths.from_install_root
    in this same file; _launch_services_check's os.name check is the older idiom.

    Returns None, following _launch_services_check's precedent, when this bundle
    never had hooks/ to begin with -- see the guard below for why that is not the
    same thing as a broken install.
    """
    root = plugin_root or Path(__file__).resolve().parents[2]
    hooks_dir = root / "hooks"
    if not hooks_dir.is_dir():
        # The Claude Desktop extension and the Claude Code .zip never ship hooks/ --
        # only the marketplace tree does (build_plugin._PLUGIN_FILES). detect_layout
        # cannot tell them apart, because the Desktop bundle launches through the same
        # scripts/start and writes the same runtime/<key>/ready marker, so has_plugin is
        # true there too. Reporting a missing hint to a product that never had one is a
        # false fault, and a noisy doctor is worth less than a quiet one.
        return None
    manifest = hooks_dir / "hooks.json"
    script = root / "scripts" / "capture_hook"
    if sys.platform == "win32":
        return _check(
            "capture_hook",
            "info",
            "The prompt-time capture hint does not run on Windows. Automatic capture still works.",
            platform="windows",
            hooks_manifest=_display_path(manifest),
            reason="hooks.json cannot name a per-platform command",
        )
    present = manifest.is_file() and script.is_file()
    return _check(
        "capture_hook",
        "pass" if present else "warning",
        "The prompt-time capture hint is installed."
        if present
        else "The prompt-time capture hint is missing from this install.",
        platform="posix",
        hooks_manifest=_display_path(manifest),
        hook_script=_display_path(script),
    )


def run_doctor(install_root: Path | None = None) -> dict[str, Any]:
    paths = DoctorPaths.from_install_root(install_root)
    layout = detect_layout(paths.install_root)

    checks = [_layout_check(paths, layout)]
    if layout.runtimes:
        checks.append(_installation_check(paths, layout))
        checks.append(_memory_directory_check(paths))
        checks.append(_database_check(paths))
        chatgpt_configured = True
        if layout.has_chatgpt:
            configuration = _configuration_check(paths)
            chatgpt_configured = not configuration["details"].get("not_configured", False)
            checks.append(configuration)
        checks.append(_dashboard_check())
        dashboard_version = _dashboard_version_check()
        if dashboard_version is not None:
            checks.append(dashboard_version)
        if layout.has_chatgpt:
            checks.append(_private_connection_check(paths, chatgpt_configured))
            if sys.platform == "darwin":
                checks.append(_launch_services_check())
        checks.append(_runtime_check(paths))
        if layout.has_plugin:
            checks.append(_registration_check(Path.home()))
            capture_hook = _capture_hook_check()
            if capture_hook is not None:
                checks.append(capture_hook)

    # "info" is deliberately not a fault: it reports a feature the user has not set up.
    statuses = {item["status"] for item in checks}
    overall = "error" if "error" in statuses else "degraded" if "warning" in statuses else "healthy"
    report = {
        "product": PRODUCT,
        "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "generated_at": _now(),
        "overall_status": overall,
        "runtimes": list(layout.runtimes),
        "checks": _sanitize(checks),
        "privacy": {
            "memory_contents_included": False,
            "conversation_history_included": False,
            "runtime_keys_included": False,
            "complete_tunnel_ids_included": False,
            "uploaded_automatically": False,
        },
    }
    report["next_actions"] = next_actions(report)
    return report


# What a person should actually do about each failed check, in their own words and
# without a terminal. The checks were written for a developer reading JSON; a beta
# tester on Claude Desktop has no terminal at all, which is why the diagnosis engine
# below went unused for the people who needed it most. Every remedy here is phrased
# as an instruction the assistant can read out and the user can carry out alone.
_REMEDIES: dict[str, dict[str, str]] = {
    "install_layout": {
        "error": (
            "MemorySafe is not installed in the folder it is looking at. Re-run the "
            "installer from the unzipped folder and accept the suggested location."
        ),
    },
    "installation": {
        "error": (
            "Some MemorySafe files are missing, so the install did not finish. Unzip the "
            "download again and run the installer once more -- your stored memories are "
            "in a separate folder and are not affected."
        ),
    },
    "memory_directory": {
        "error": (
            "MemorySafe cannot write to its memory folder. This is usually macOS or "
            "Windows privacy permissions on that folder rather than a MemorySafe fault."
        ),
    },
    "database": {
        "warning": (
            "Nothing has been stored yet. This is normal on a new install -- state one "
            "durable fact and ask to remember it, then search for it to prove the store works."
        ),
        "error": (
            "The memory database could not be read. Do not reinstall yet: a backup copy "
            "may exist in the backups folder and reinstalling will not repair the file."
        ),
    },
    "configuration": {
        "error": (
            "The assistant configuration file is missing or unreadable, so the assistant "
            "cannot find MemorySafe. Re-run the installer, then fully quit and reopen the assistant."
        ),
        "warning": (
            "The configuration points somewhere unexpected. If memories seem to have "
            "vanished, this is the reason -- two stores, not lost data."
        ),
    },
    "dashboard_service": {
        "warning": (
            "The dashboard is not answering on this computer. It starts with the "
            "assistant, so quit the assistant completely and reopen it."
        ),
    },
    "private_connection": {
        "warning": (
            "The private connection for ChatGPT is not ready. Claude and Claude Code do "
            "not use it, so ignore this unless you are setting up ChatGPT."
        ),
    },
    "dashboard_version": {
        "warning": (
            "An older MemorySafe is still running and holding the dashboard address. "
            "It is usually a previous Claude Desktop extension: open Claude Desktop, go "
            "to Settings then Extensions, remove the older MemorySafe, and restart it. "
            "Your memories are in a separate folder and are not affected."
        ),
    },
    "launch_services": {
        "warning": (
            "A background MemorySafe service is not running. Restarting the computer "
            "starts it again; nothing needs reinstalling."
        ),
        "error": (
            "A background MemorySafe service failed to start. Restart the computer, and "
            "if it happens again this is worth reporting -- it is a real bug."
        ),
    },
    "runtime_resources": {
        "error": (
            "The private Python that MemorySafe runs on is missing or damaged. Re-run the "
            "installer; it rebuilds the runtime and leaves your memories alone."
        ),
        "warning": (
            "The MemorySafe runtime is incomplete. Re-running the installer rebuilds it."
        ),
    },
    "registration": {
        "warning": (
            "MemorySafe is connected to this assistant twice -- once by the plugin and once "
            "by an older manual install -- so every MemorySafe tool appears twice. Ask the "
            "assistant to remove the old MemorySafe registration; it will show what changes "
            "before making them."
        ),
    },
    "capture_hook": {
        # No "info" key here on purpose. next_actions() only ever builds actions
        # for checks with status "error" or "warning" -- an "info" remedy is dead
        # code, unreachable by construction. A Windows install with no prompt-time
        # hook is documented as harmless, not wrong, so it earns no action item;
        # the Windows-specific message already lives in the check's own `summary`
        # (see _capture_hook_check), which _print_human prints regardless.
        "warning": (
            "The prompt-time capture hint is missing from this install. Automatic capture "
            "still works when you ask for something to be remembered. Reinstalling the "
            "plugin restores the hint."
        ),
    },
}

# Restarting the assistant fixes a genuinely large share of first-install reports,
# because the tools are only registered when the client starts. Say it first and say
# it plainly, before anyone is asked to look at a file.
_RESTART_FIRST = (
    "Quit the assistant completely and reopen it. Tools are only picked up at start-up, "
    "so a first install that looks broken is usually a client that has not been restarted."
)


def next_actions(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Ordered, plain-language remedies for whatever the doctor just found.

    Read-only: this decides what to say, never what to change.
    """

    failed = [
        check
        for check in report.get("checks", [])
        if check.get("status") in {"error", "warning"}
    ]
    if not failed:
        return []

    actions: list[dict[str, Any]] = []
    if any(
        check["id"] in {"configuration", "dashboard_service", "launch_services"}
        for check in failed
    ):
        actions.append(
            {"priority": 1, "check": "restart", "status": "info", "action": _RESTART_FIRST}
        )

    for check in failed:
        remedy = _REMEDIES.get(check["id"], {}).get(check["status"])
        if remedy is None:
            continue
        actions.append(
            {
                # Errors block the install; warnings usually do not.
                "priority": 2 if check["status"] == "error" else 3,
                "check": check["id"],
                "status": check["status"],
                "found": check.get("summary", ""),
                "action": remedy,
            }
        )
    actions.sort(key=lambda item: item["priority"])
    return actions


def _error_signature(line: str) -> str | None:
    lowered = line.lower()
    signatures = (
        ("path_whitespace", "fork/exec", "no such file or directory"),
        ("port_in_use", "address already in use"),
        ("permission_denied", "permissionerror", "permission denied", "operation not permitted"),
        ("connection_cancelled", "context canceled"),
        ("python_traceback", "traceback"),
        ("startup_failed", "start failed", "onstart hook failed"),
    )
    for signature in signatures:
        if any(marker in lowered for marker in signature[1:]):
            return signature[0]
    if any(marker in lowered for marker in _ERROR_MARKERS):
        return "other_error"
    return None


def _error_events(paths: DoctorPaths) -> list[dict[str, Any]]:
    # Deliberately aggregate known signatures instead of copying raw log lines.
    # A raw error can contain user-provided text; counts cannot expose memory content.
    counts: dict[tuple[str, str], int] = {}
    log_dir = paths.state_dir / "logs"
    if not log_dir.is_dir():
        return []
    for log in sorted(log_dir.glob("*.log*")):
        if not log.is_file():
            continue
        try:
            with log.open("rb") as stream:
                size = log.stat().st_size
                stream.seek(max(0, size - MAX_ERROR_SOURCE_BYTES))
                lines = stream.read(MAX_ERROR_SOURCE_BYTES).decode("utf-8", "replace").splitlines()
        except OSError:
            continue
        for line in lines:
            signature = _error_signature(line)
            if signature:
                key = (log.name, signature)
                counts[key] = counts.get(key, 0) + 1
    events = [
        {"log": log, "signature": signature, "count": count}
        for (log, signature), count in sorted(counts.items())
    ]
    return events[-MAX_ERROR_EVENTS:]


# Exactly the names create_support_bundle writes, so find_support_bundle can serve nothing
# else: no other file, no path, no "..". fullmatch and [0-9] because `$` lets a trailing
# newline through and `\d` takes any script's digits, and a served name goes into a header.
SUPPORT_BUNDLE_NAME = re.compile(r"MemorySafe-Support-[0-9]{8}-[0-9]{6}\.zip")


def _support_bundle_dir(paths: DoctorPaths) -> Path:
    return paths.state_dir / "support-bundles"


def find_support_bundle(install_root: Path | None, name: str) -> Path | None:
    """The bundle called `name` in this install's support-bundles folder, if it is one."""

    if not SUPPORT_BUNDLE_NAME.fullmatch(name):
        return None
    candidate = _support_bundle_dir(DoctorPaths.from_install_root(install_root)) / name
    return candidate if candidate.is_file() else None


# What the person typed into "What went wrong?". Their own words, which they chose to
# include; capped so a pasted log cannot turn the bundle into something else.
DESCRIPTION_LIMIT = 4000


def create_support_bundle(
    install_root: Path | None = None,
    output_path: Path | None = None,
    description: str | None = None,
) -> Path:
    paths = DoctorPaths.from_install_root(install_root)
    support_dir = _support_bundle_dir(paths)
    support_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = (output_path or support_dir / f"MemorySafe-Support-{stamp}.zip").expanduser().resolve()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    report = run_doctor(paths.install_root)
    errors = _error_events(paths)
    readme = (
        "MemorySafe Beta support bundle\n\n"
        "Created locally after an explicit user request. It contains diagnostic status, "
        "counts, and sanitized error signatures. It does not contain memory contents, "
        "conversation history, runtime keys, or complete tunnel identifiers. Nothing was uploaded.\n"
    )
    written = (description or "").strip()[:DESCRIPTION_LIMIT]
    if written:
        readme += "what-went-wrong.txt is the description the person typed when creating this report.\n"
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", readme)
        archive.writestr("doctor.json", json.dumps(report, indent=2, sort_keys=True) + "\n")
        archive.writestr("sanitized-errors.json", json.dumps(errors, indent=2, sort_keys=True) + "\n")
        if written:
            archive.writestr("what-went-wrong.txt", written + "\n")
    os.chmod(temporary, 0o600)
    temporary.replace(target)
    os.chmod(target, 0o600)
    return target
