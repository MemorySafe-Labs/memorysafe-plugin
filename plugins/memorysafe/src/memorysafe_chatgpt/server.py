from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from .bootstrap_catalog import SERVER_INSTRUCTIONS, VERSION
from .dashboard import DASHBOARD_MIME_TYPE, DASHBOARD_URI, dashboard_html
from .doctor import run_doctor
from . import capture_policy
from .storage import MemoryStore


Category = Literal["preference", "personal", "project", "decision", "task", "safety", "other"]


class RememberResult(BaseModel):
    decision: Literal["PROTECT", "STORE", "MERGE"]
    memory_id: str
    content: str
    category: str
    importance: float
    confidence: float
    protected: bool
    reason: str
    lifecycle: Literal["none", "superseded_previous", "needs_review"] | None = None
    replaced_memory_id: str | None = None
    conflict_id: int | None = None
    lifecycle_reason: str | None = None


class MemoryMatch(BaseModel):
    memory_id: str
    content: str
    category: str
    importance: float
    confidence: float
    protected: bool
    match_score: float
    updated_at: str


class FindResult(BaseModel):
    query: str
    count: int
    memories: list[MemoryMatch]


class DoctorCheck(BaseModel):
    id: str
    status: str
    summary: str
    details: dict[str, Any] = {}


class DoctorAction(BaseModel):
    priority: int
    check: str
    status: str
    action: str
    found: str = ""


class DoctorResult(BaseModel):
    overall_status: str
    checks: list[DoctorCheck]
    # The whole point of this tool: what to say to the person, not what the JSON says.
    next_actions: list[DoctorAction] = []
    runtimes: list[str] = []
    privacy: dict[str, Any] = {}
    generated_at: str = ""
    summary: str = ""


class ForgetResult(BaseModel):
    memory_id: str
    forgotten: bool
    reason: str
    # Forgetting one side of a conflict closes it. Declared so the count is not
    # silently dropped the way the health counters were.
    conflicts_closed: int = 0


class RestoreResult(BaseModel):
    restored: bool
    memory_id: str
    reason: str
    needs_confirmation: bool = False


class ConflictItem(BaseModel):
    conflict_id: int
    decision: str
    status: str
    reason: str
    evidence: str
    confidence: float
    source: str
    created_at: str
    old: dict[str, Any] | None = None
    new: dict[str, Any] | None = None


class ReviewConflictsResult(BaseModel):
    count: int
    conflicts: list[ConflictItem]


class ResolveConflictResult(BaseModel):
    resolved: bool
    reason: str
    action: str | None = None
    old_memory_id: str | None = None
    new_memory_id: str | None = None
    needs_confirmation: bool = False


class ExplainResult(BaseModel):
    memory_id: str
    found: bool
    content: str | None = None
    protected: bool | None = None
    protected_because: str | None = None
    protected_since: str | None = None
    recall_count: int | None = None
    state: str | None = None
    history: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    note: str | None = None


class ComparisonResult(BaseModel):
    raw_remember_requests: int
    memories_with_memorysafe: int
    duplicate_copies_avoided: int
    content_bytes_avoided: int
    note: str


class TokenCompareResult(BaseModel):
    facts_stored: int
    average_fact_tokens: int
    facts_recalled_per_turn: int
    fixed_overhead_tokens: int
    without_memorysafe_tokens: int
    with_memorysafe_tokens: int
    tokens_saved_per_turn: int
    tokens_extra_per_turn: int
    percent_saved: float
    paying_off: bool


class TokenBenchmarkResult(BaseModel):
    kind: Literal["measured_input_payload_model"]
    tokenizer: str
    tool_schema_tokens: int
    instruction_tokens: int = 0
    fixed_overhead_tokens: int = 0
    average_fact_tokens: int = 0
    recalled_per_turn: int = 0
    break_even_facts: int
    savings_at_80_facts: float
    savings_at_160_facts: float
    live_compare: TokenCompareResult
    model: str = ""
    chatgpt_live_usage_available: bool
    note: str


class LiveTokenMetricsResult(BaseModel):
    kind: Literal["live_local"]
    tokenizer: str
    exact: bool
    active_memory_tokens: int
    top_context_tokens: int
    average_memory_tokens: int
    counted_memories: int
    chatgpt_live_usage_available: bool
    note: str


class HealthResult(BaseModel):
    memory_health: int
    active_memories: int
    protected_memories: int
    average_importance: float
    average_confidence: float
    active_content_bytes: int
    database_bytes: int
    decision_counts: dict[str, int]
    automatic_mode: bool
    automatic_captures: int
    automatic_skips: int
    automatic_candidates_evaluated: int
    automatic_last_event_at: str | None
    automatic_last_decision: str | None
    automatic_last_reason: str | None
    comparison: ComparisonResult
    live_token_metrics: LiveTokenMetricsResult
    token_benchmark: TokenBenchmarkResult
    formula: str
    # Liveness, deliberately kept out of memory_health. Every term of the score rates what
    # is already stored, so the score cannot fall when capture stops -- a store that has
    # gone silent keeps scoring well. These fields are the only signal that says so.
    last_capture_at: str | None
    days_since_last_capture: int | None
    capture_freshness: Literal["active", "quiet", "stale", "never", "unknown"]
    capture_status: str
    formula_note: str
    # Which store these numbers came from. An unexpected path is the fastest explanation
    # for an empty dashboard, which is otherwise indistinguishable from a broken install.
    database_path: str
    # A bare automatic_captures of 0 is ambiguous: it reads the same whether the mode is
    # off, or on and never once invoked. Say which, so silent inactivity is visible.
    automatic_status: str
    # Undeclared keys are dropped by this model. storage.health() has computed both of
    # these all along and neither ever reached a caller, so an assistant asking how the
    # store was doing was told "healthy" while unresolved conflicts piled up behind it --
    # the same leak that already cost us the recall telemetry below.
    superseded_memories: int = 0
    open_reviews: int = 0
    governance_status: str = ""
    # Declared, or Pydantic drops it before it reaches the dashboard -- the same
    # leak that already cost the recall telemetry and the conflict counters.
    governance_events: list[dict[str, Any]] = []


class RecallSummary(BaseModel):
    times_memory_was_consulted: int = 0
    memories_ever_recalled: int = 0
    memories_never_recalled: int = 0
    content_bytes_recalled: int = 0
    average_bytes_per_recall: int = 0
    last_recall_at: str | None = None
    most_used: list[dict[str, Any]] = []
    note: str = ""


class DashboardResult(HealthResult):
    status: Literal["healthy"]
    recent_memories: list[MemoryMatch]
    # Undeclared keys are dropped, so recall telemetry never left the server: an
    # assistant asked "is this helping?" and got nothing, while the dashboard looked
    # fine because it reads the raw payload. Recall is the benefit — it has to travel.
    recall: RecallSummary | None = None
    # Set only by the dashboard tool: "window", "browser", "disabled", or None.
    opened: str | None = None
    # Clients that cannot render the inline mcp-app resource still need somewhere to send
    # the user. ChatGPT draws the dashboard in the conversation; Claude and other MCP
    # clients get numbers, so give them the local address to open.
    dashboard_url: str


class AutomaticModeResult(BaseModel):
    enabled: bool
    reason: str


class AutomaticCaptureResult(BaseModel):
    saved: bool
    decision: Literal["PROTECT", "STORE", "MERGE", "SKIP"]
    memory_id: str | None
    content: str
    category: str
    reason: str


class AutomaticCaptureBatch(BaseModel):
    saved: int
    skipped: int
    results: list[AutomaticCaptureResult]


def canonical_data_dir() -> Path:
    """The one place memories live, whatever installed the code.

    Claude and the ChatGPT/Codex connector are separate installs in separate roots, and
    the store used to be resolved relative to each of them: the Claude manifest pointed
    at its own configured directory, the macOS installer at its install root, and the
    code fallback at whatever folder the package happened to sit in. Three answers to
    one question, so the two assistants quietly kept separate memories and each looked
    as though it had forgotten what the other was told.

    Deliberately not under an install root: install roots differ per assistant and
    change between versions, and memories must outlive both.
    """

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "MemorySafe" / "data"


def _legacy_database_paths() -> list[Path]:
    """Stores written before the location was pinned down."""

    candidates = [
        Path(__file__).resolve().parents[2] / "data" / "memorysafe.sqlite3",
        Path.home() / "Library" / "Application Support" / "MemorySafe Beta" / "data" / "memorysafe.sqlite3",
    ]
    root = os.environ.get("MEMORYSAFE_INSTALL_ROOT")
    if root:
        candidates.append(Path(root) / "data" / "memorysafe.sqlite3")
    return candidates


def _default_database_path() -> Path:
    canonical = canonical_data_dir() / "memorysafe.sqlite3"
    if canonical.exists():
        return canonical
    # Adopt an existing store rather than starting empty beside it: silently opening a
    # fresh database is indistinguishable, to the user, from having lost everything.
    for legacy in _legacy_database_paths():
        if legacy.exists():
            return legacy
    return canonical


_stores: dict[Path, MemoryStore] = {}


def _store() -> MemoryStore:
    configured = os.environ.get("MEMORYSAFE_DB_PATH")
    path = Path(configured).expanduser().resolve() if configured else _default_database_path()
    if path not in _stores:
        _stores[path] = MemoryStore(path)
    return _stores[path]


server = MCPServer(
    name="memorysafe",
    title="MemorySafe",
    description="Private local memory governance for Claude, ChatGPT and Codex.",
    version=VERSION,
    instructions=SERVER_INSTRUCTIONS,
    log_level="WARNING",
)


@server.resource(
    DASHBOARD_URI,
    name="memorysafe-dashboard",
    title="MemorySafe dashboard",
    description="Inline visual dashboard for real local MemorySafe health and governed storage data.",
    mime_type=DASHBOARD_MIME_TYPE,
    meta={"ui": {"prefersBorder": True}},
)
def memorysafe_dashboard_resource() -> str:
    return dashboard_html()


@server.tool(
    name="memorysafe_remember",
    title="Remember with MemorySafe",
    description=(
        "Save one durable fact, only when the user explicitly asks to remember it. "
        "Stored locally; duplicates may merge."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
def remember(
    content: Annotated[
        str,
        Field(min_length=1, max_length=10_000, description="The fact to remember."),
    ],
    category: Annotated[Category, Field(description="Kind of memory.")] = "other",
) -> RememberResult:
    return RememberResult.model_validate(_store().remember(content, category))


@server.tool(
    name="memorysafe_set_auto_mode",
    title="Set automatic memory mode",
    description=(
        "Turn automatic capture on or off, only when the user asks."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def set_automatic_mode(
    enabled: Annotated[bool, Field(description="On or off.")],
) -> AutomaticModeResult:
    return AutomaticModeResult.model_validate(_store().set_automatic_mode(enabled))


_SENSITIVE_AUTOMATIC_CONTENT = re.compile(
    r"\b(?:password|passcode|one[- ]time code|otp|api key|secret key|private key|"
    r"access token|refresh token|credit card|debit card|card number|cvv|cvc|bank account|"
    r"routing number|social security|social insurance|passport|driver'?s? licen[cs]e|"
    r"date of birth|home address|street address|phone number|email address|diagnos(?:is|ed)|"
    r"medical record|medication|allerg(?:y|ic)|therapy|therapist)\b",
    re.IGNORECASE,
)
# The word list caught "social insurance number" and "phone number" but not an actual
# SIN or phone number written on its own, which is the form they are usually stated in.
# A privacy-first product leaking those is the worst failure available to it.
# Credential formats are matched by their issuer prefix rather than by entropy: the
# prefixes are distinctive enough to be near-zero false positive on ordinary prose,
# whereas an entropy test flags every base64 blob and every long identifier.
_SECRET_LIKE_VALUE = re.compile(
    r"\bsk-[A-Za-z0-9_-]{10,}\b"                      # API keys
    r"|\b\d{13,19}\b"                                  # card numbers
    r"|\b\d{3}[-. ]\d{3}[-. ]\d{3}\b"                  # Canadian SIN
    r"|\b\d{3}-\d{2}-\d{4}\b"                          # US SSN
    r"|(?:\+?\d{1,2}[-. ])?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b"  # phone numbers
    r"|\bA(?:KIA|SIA|ROA|IDA|GPA|NPA|NVA|IPA)[0-9A-Z]{16}\b"        # AWS key ids
    r"|\beyJ[A-Za-z0-9_/+=-]{15,}"                                   # JWT / bearer payloads
    r"|\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"                           # Authorization headers
    r"|\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{20,}\b"                 # GitHub tokens
    r"|\bgithub_pat_[A-Za-z0-9_]{20,}\b"                             # GitHub fine-grained PAT
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}\b"                             # Slack tokens
    r"|\bAIza[0-9A-Za-z_-]{30,}"                                     # Google API keys
    r"|\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"                 # Stripe keys
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"                            # PEM private keys
)


def _automatic_skip_reason(content: str, category: str) -> str | None:
    # Delegated to capture_policy so the refusal rules can be read, reviewed and
    # tested on their own. The old inline version tested the label rather than
    # the payload: it refused the phrase "email address" and saved an actual one.
    decision = capture_policy.skip_reason(
        content, category, _store().automatic_mode_enabled()
    )
    if decision is not None:
        _shape, reason = decision
        return reason
    # There was a threshold here on model-supplied importance and confidence. The server
    # sets both now, so the test could only ever pass. Capture stays conservative on
    # safety; there is no low-value pruning pass.
    return None


@server.tool(
    name="memorysafe_auto_capture",
    title="Capture durable memories",
    description=(
        "Save the durable facts the user just stated — all of them in one call, only while "
        "automatic mode is on. Duplicates merge. Nothing is dropped for being old or low-value. "
        "Never ask first. Never pass whole messages, inferences, secrets, IDs, contacts, "
        "addresses or health data."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
def automatic_capture(
    facts: Annotated[
        list[str],
        Field(min_length=1, max_length=3, description="One sentence each."),
    ],
    category: Annotated[Category, Field(description="Kind of memory.")] = "other",
) -> AutomaticCaptureBatch:
    # One call for up to three facts. Three separate round trips was friction on the only
    # path that matters, and friction on a call the host model already has to choose to
    # make is how a memory product ends up with three captures a fortnight.
    results: list[AutomaticCaptureResult] = []
    for raw in facts[:3]:
        clean_content = " ".join(str(raw).split())
        if not clean_content:
            continue
        reason = _automatic_skip_reason(clean_content, category)
        if reason:
            _store().record_automatic_skip(reason, clean_content)
            results.append(
                AutomaticCaptureResult(
                    saved=False,
                    decision="SKIP",
                    memory_id=None,
                    content=clean_content,
                    category=category,
                    reason=reason,
                )
            )
            continue
        stored = _store().remember(clean_content, category, source="automatic")
        results.append(
            AutomaticCaptureResult(
                saved=True,
                decision=stored["decision"],
                memory_id=stored["memory_id"],
                content=stored["content"],
                category=stored["category"],
                reason=f"Saved automatically. {stored['reason']}",
            )
        )
    return AutomaticCaptureBatch(
        saved=sum(1 for r in results if r.saved),
        skipped=sum(1 for r in results if not r.saved),
        results=results,
    )


@server.tool(
    name="memorysafe_find",
    title="Find memories",
    description=(
        "Search stored memories. Empty query browses recent ones."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def find_memories(
    query: Annotated[str, Field(max_length=500, description="What to look for.")] = "",
    limit: Annotated[int, Field(ge=1, le=20, description="Maximum results.")] = 5,
) -> FindResult:
    matches = [MemoryMatch.model_validate(item) for item in _store().find(query, limit)]
    return FindResult(query=query, count=len(matches), memories=matches)


@server.tool(
    name="memorysafe_forget",
    title="Forget a memory",
    description=(
        "Remove one memory from active recall, only when the user asks. This is not a "
        "permanent erase. Without an exact ID, find and confirm it first."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def forget_memory(
    memory_id: Annotated[str, Field(min_length=1, max_length=80, description="Exact memory ID.")],
) -> ForgetResult:
    return ForgetResult.model_validate(_store().forget(memory_id))


@server.tool(
    name="memorysafe_explain",
    title="Explain a memory",
    description=(
        "Inspect one memory in any state — active, superseded, or forgotten — with "
        "its decision history and replacement record. Not limited to normal recall."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def explain_memory(
    memory_id: Annotated[str, Field(min_length=1, max_length=80, description="Exact memory ID.")],
) -> ExplainResult:
    return ExplainResult.model_validate(_store().inspect_memory(memory_id))


@server.tool(
    name="memorysafe_review_conflicts",
    title="Review memory conflicts",
    description=(
        "List open conflicts where a new fact might replace an older one. "
        "Does not change anything."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def review_conflicts(
    include_resolved: Annotated[
        bool, Field(description="Also list already resolved replacements.")
    ] = False,
) -> ReviewConflictsResult:
    return ReviewConflictsResult.model_validate(
        _store().review_conflicts(include_resolved=include_resolved)
    )


@server.tool(
    name="memorysafe_resolve_conflict",
    title="Resolve a memory conflict",
    description=(
        "Supersede, keep both, or restore. Requires confirm=true after the user agrees. "
        "Nothing changes without that confirmation."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
def resolve_conflict(
    conflict_id: Annotated[int, Field(ge=1, description="Conflict ID from review.")],
    action: Annotated[
        Literal["supersede", "keep_both", "restore"],
        Field(description="supersede, keep_both, or restore."),
    ],
    confirm: Annotated[
        bool, Field(description="Must be true; otherwise nothing is changed.")
    ] = False,
) -> ResolveConflictResult:
    return ResolveConflictResult.model_validate(
        _store().resolve_conflict(conflict_id, action, confirm=confirm)
    )


@server.tool(
    name="memorysafe_restore",
    title="Restore a memory to recall",
    description=(
        "Put a superseded or forgotten memory back into active recall. "
        "Requires confirm=true after the user agrees."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def restore_memory(
    memory_id: Annotated[str, Field(min_length=1, max_length=80, description="Exact memory ID.")],
    confirm: Annotated[
        bool, Field(description="Must be true; otherwise nothing is changed.")
    ] = False,
) -> RestoreResult:
    return RestoreResult.model_validate(_store().restore(memory_id, confirm=confirm))


@server.tool(
    name="memorysafe_doctor",
    title="Diagnose a MemorySafe install",
    description=(
        "Check this MemorySafe installation and say what to do about anything wrong. "
        "Call this whenever the user says MemorySafe is not working, memories seem "
        "missing, or a fresh install does not respond -- and before suggesting a "
        "reinstall. Read-only: it inspects the installation, never memory contents, "
        "and changes nothing. Read 'next_actions' out in plain language and work "
        "through them in order; do not read the raw checks to the user."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def doctor() -> DoctorResult:
    """Self-diagnosis that does not need a terminal.

    The engine behind this has existed since 0.3.x, reachable only as
    `memorysafe doctor --json` from a shell. Claude Desktop has no shell, so the
    testers most likely to need it were the least able to run it, and the honest
    answer to "it isn't working" was to ask them to open Terminal.
    """

    report = run_doctor()
    actions = report.get("next_actions", [])
    if report["overall_status"] == "healthy":
        summary = "MemorySafe is installed correctly and the store is readable."
    elif not actions:
        summary = "Something is not right, but no known remedy matched. A support bundle would help."
    else:
        summary = actions[0]["action"]
    report["summary"] = summary
    return DoctorResult.model_validate(report)


@server.tool(
    name="memorysafe_health",
    title="Show memory health",
    description=(
        "Show local memory counts, storage, governance decisions and the health formula. "
        "Call this first when the user just installed MemorySafe or asks how to set it up, "
        "then walk them through restart, the dashboard at http://127.0.0.1:8765/dashboard, "
        "and one remember-then-find. Pass open=true to also open the visual dashboard; if "
        "the returned 'opened' is 'window' or 'browser', say it opened rather than pasting "
        "the link."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    meta={
        "ui": {"resourceUri": DASHBOARD_URI},
        "openai/outputTemplate": DASHBOARD_URI,
        "openai/toolInvocation/invoking": "Opening MemorySafe dashboard…",
        "openai/toolInvocation/invoked": "MemorySafe dashboard ready.",
    },
)
def memory_health(
    open: Annotated[bool, Field(description="Also open the dashboard window.")] = False,
) -> DashboardResult:
    return _dashboard_data(open_window=open)


def _dashboard_url() -> str:
    port = os.environ.get("MEMORYSAFE_SETUP_PORT", "8765")
    return f"http://127.0.0.1:{port}/dashboard"


_APP_WINDOW_BROWSERS = ("Google Chrome", "Brave Browser", "Microsoft Edge", "Chromium")


def _open_dashboard_window(url: str) -> str:
    """Open the dashboard in its own small window on this machine.

    Only the dashboard tool calls this, never the health tool: the user asked to *open*
    the dashboard, so a window is the answer. Firing one on every health check would be
    intrusive. Set MEMORYSAFE_OPEN_DASHBOARD=0 to disable.

    A Chromium-family browser gives a chromeless app window; otherwise fall back to the
    default browser. Output is discarded because stdout carries the MCP protocol.
    """
    if os.environ.get("MEMORYSAFE_OPEN_DASHBOARD", "1").strip().lower() in {"0", "false", "no", "off"}:
        return "disabled"
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        try:
            subprocess.Popen(["cmd", "/c", "start", "", url], **quiet)
            return "browser"
        except OSError:
            return "unavailable"
    if sys.platform != "darwin":
        try:
            subprocess.Popen(["xdg-open", url], **quiet)
            return "browser"
        except OSError:
            return "unavailable"

    for app in _APP_WINDOW_BROWSERS:
        if not Path(f"/Applications/{app}.app").exists():
            continue
        try:
            subprocess.Popen(
                ["open", "-na", app, "--args", f"--app={url}",
                 "--window-size=1180,820", "--window-position=180,120"],
                **quiet,
            )
            return "window"
        except OSError:
            continue
    try:
        subprocess.Popen(["open", url], **quiet)
        return "browser"
    except OSError:
        return "unavailable"


def _dashboard_data(open_window: bool = False) -> DashboardResult:
    data = _store().health()
    data["status"] = "healthy"
    data["recent_memories"] = _store().find("", 6)
    data["dashboard_url"] = _dashboard_url()
    data["opened"] = _open_dashboard_window(data["dashboard_url"]) if open_window else None
    return DashboardResult.model_validate(data)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
