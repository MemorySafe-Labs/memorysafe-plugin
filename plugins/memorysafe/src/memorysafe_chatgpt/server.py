from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from collections.abc import Callable
from typing import Any, Annotated, ClassVar, Literal

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field, model_serializer

from .bootstrap_catalog import SERVER_INSTRUCTIONS, VERSION
from .tool_errors import spoken
from .dashboard import DASHBOARD_MIME_TYPE, DASHBOARD_URI, dashboard_html
from .doctor import run_doctor
from . import capture_policy, hosted_proxy
from .storage import MemoryStore


Category = Literal["preference", "personal", "project", "decision", "task", "safety", "other"]


class LeanResult(BaseModel):
    """A result that says only what is so: optional fields at their empty value are left out.

    Every key of every result is paid for in the assistant's context, on every call. One
    found memory of thirteen tokens used to arrive as a hundred and fifty: its text, plus
    importance, confidence, a match score, a full timestamp, `needs_review: false`,
    `open_conflict_ids: []` and `review_note: null`. None of those change what the assistant
    should do, and the three scores are the server's own bookkeeping.

    Only fields that have a default are ever left out, so what is sent still satisfies the
    declared output schema, and a reader that validates into the same model gets the
    defaults back. `_never_sent` names bookkeeping fields that are not sent at all.
    """

    _never_sent: ClassVar[frozenset[str]] = frozenset()

    @model_serializer(mode="wrap")
    def _lean(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        for name, field in type(self).model_fields.items():
            if field.is_required():
                continue
            value = data.get(name)
            if name in self._never_sent or value is None or value is False or value == [] or value in ("", "none"):
                data.pop(name, None)
        return data


class RememberResult(LeanResult):
    _never_sent: ClassVar[frozenset[str]] = frozenset({"importance", "confidence"})

    # FULL: the store is at its plan's limit; nothing was saved and nothing was removed.
    decision: Literal["PROTECT", "STORE", "MERGE", "SKIP", "FULL"]
    memory_id: str | None = None
    content: str
    category: str
    importance: float | None = None
    confidence: float | None = None
    protected: bool = False
    reason: str
    lifecycle: Literal["none", "superseded_previous", "needs_review"] | None = None
    replaced_memory_id: str | None = None
    conflict_id: int | None = None
    lifecycle_reason: str | None = None
    evicted_memory_ids: list[str] = []


class MemoryMatch(BaseModel):
    memory_id: str
    content: str
    category: str
    importance: float
    confidence: float
    protected: bool
    match_score: float
    updated_at: str
    # An open conflict must travel with the fact, or the assistant repeats a stale
    # or contested fact with full certainty.
    needs_review: bool = False
    open_conflict_ids: list[int] = []
    review_note: str | None = None


# A memory as a search returns it to an assistant: the text, what kind it is, when it last
# changed and its id; `protected` and the conflict fields only when they are set. (A comment,
# not a docstring: a docstring becomes the schema's description, and the hosted edition's
# subclass must publish the same schema.)
class FoundMemory(LeanResult, MemoryMatch):
    _never_sent: ClassVar[frozenset[str]] = frozenset({"importance", "confidence", "match_score"})

    importance: float | None = None
    confidence: float | None = None
    match_score: float | None = None
    protected: bool = False


class FindResult(BaseModel):
    query: str
    count: int
    memories: list[FoundMemory]


# What a hosted account adds to a result, kept when this plugin forwards to one. A model
# drops the keys it does not declare, so the account's "this may be out of date" never
# reached the assistant, which then stated an old status as current. These are returned
# only in hosted mode; the tools' published schemas stay the local ones (the MCP library
# dumps a returned subclass with its own fields). Empty, they are left out (LeanResult).
class _ForwardedFoundMemory(FoundMemory):
    layer: str | None = None
    possibly_stale: bool = False
    stale_reason: str | None = None
    status_review: str | None = None


class _ForwardedFindResult(FindResult):
    memories: list[_ForwardedFoundMemory]


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
    needs_confirmation: bool = False


class RestoreResult(BaseModel):
    restored: bool
    memory_id: str
    reason: str
    needs_confirmation: bool = False
    reopened_conflicts: list[int] = []


class ProtectResult(BaseModel):
    memory_id: str
    changed: bool
    protected: bool
    reason: str


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
    conflict_status: str | None = None


class ExplainResult(BaseModel):
    memory_id: str
    found: bool
    content: str | None = None
    protected: bool | None = None
    protected_because: str | None = None
    protected_since: str | None = None
    confidence: float | None = None
    recall_count: int | None = None
    restated_count: int | None = None
    last_used_at: str | None = None
    keywords: list[str] = []
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
    # "hosted_estimate" is the hosted edition's token_estimate, shown here when this
    # computer is in hosted mode: the same fields, counted on the account's memories.
    kind: Literal["live_local", "hosted_estimate"]
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
    # None only in hosted mode when the account sent no estimate; local health always has it.
    live_token_metrics: LiveTokenMetricsResult | None
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
    # True while a permanent erase waits for the store's file to be rewritten; erase_status
    # says what to do. An erase that silently never finished would be the worst kind.
    erase_unfinished: bool = False
    erase_status: str = ""
    # Declared, or Pydantic drops it before it reaches the dashboard -- the same
    # leak that already cost the recall telemetry and the conflict counters.
    governance_events: list[dict[str, Any]] = []
    conflict_penalty: int = 0
    evicted_memories: int = 0
    max_active: int | None = None
    # {"plan", "used", "limit"} when the store has a plan limit; null when it has none.
    plan: dict[str, Any] | None = None


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
    decision: Literal["PROTECT", "STORE", "MERGE", "SKIP", "FULL"]
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
_store_provider: Callable[[], MemoryStore] | None = None


def use_store_provider(provider: Callable[[], MemoryStore] | None) -> None:
    """Let a deployment choose the store per call; None restores the local file.

    A process that serves many users cannot key the store by a file path or an
    environment variable, since both are the same for every caller. It supplies the
    store itself, and is asked on every call so one user's store is never reused for
    the next.
    """
    global _store_provider
    _store_provider = provider


def _store() -> MemoryStore:
    if _store_provider is not None:
        return _store_provider()
    configured = os.environ.get("MEMORYSAFE_DB_PATH")
    path = Path(configured).expanduser().resolve() if configured else _default_database_path()
    if path not in _stores:
        _stores[path] = MemoryStore(path)
    return _stores[path]


def _hosted_mode() -> bool:
    """Whether this computer's tools are served by the person's hosted account.

    Only the local plugin is ever in hosted mode: a deployment with a store provider (the
    hosted edition itself) is the account, and never forwards. Read on every call, not
    cached: the dashboard changes the mode while the assistants are running, and the very
    next call must follow it.
    """
    return _store_provider is None and hosted_proxy.active()



class _ForwardedRememberResult(RememberResult):
    # Where the account filed it: its own, a project, the organization.
    layer: str | None = None


# The local result model -> the one a forwarded answer is read into.
_FORWARDED: dict[type[BaseModel], type[BaseModel]] = {
    FindResult: _ForwardedFindResult,
    RememberResult: _ForwardedRememberResult,
}

def _forward(name: str, model: type[BaseModel], **arguments: Any) -> Any:
    """The same tool, answered by the hosted account (hosted_proxy says what can fail)."""
    return _FORWARDED.get(model, model).model_validate(hosted_proxy.call(name, arguments))


# One sentence, because it ships in every conversation. With these words a search phrased
# differently from the memory can still find it; without them it almost never does.
KEYWORDS_DESCRIPTION = "3-6 other words it might be searched by (synonyms, topic), not already in it."

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
        Field(min_length=1, max_length=10_000, description="The fact to remember; line breaks are kept."),
    ],
    category: Annotated[Category, Field(description="Kind of memory.")] = "other",
    keywords: Annotated[list[str], Field(max_length=8, description=KEYWORDS_DESCRIPTION)] = [],
) -> RememberResult:
    if _hosted_mode():
        # Sent only when given: an account on an older release ignores the argument either
        # way, and an empty list is one less thing on the wire.
        extra = {"keywords": list(keywords)} if keywords else {}
        return _forward("memorysafe_remember", RememberResult, content=content, category=category, **extra)
    return RememberResult.model_validate(_store().remember(content, category, keywords=keywords))


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
    if _hosted_mode():
        return _forward("memorysafe_set_auto_mode", AutomaticModeResult, enabled=enabled)
    return AutomaticModeResult.model_validate(_store().set_automatic_mode(enabled))


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
        "Save the durable facts the user just stated — all of them in one call, only while automatic mode is on. Duplicates merge. Nothing stored is dropped for being old or low-value. Never ask first. Never pass whole messages, inferences, secrets, IDs, contacts, addresses or health data."
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
    keywords: Annotated[
        list[str],
        Field(max_length=3, description="Per fact, in order: " + KEYWORDS_DESCRIPTION[0].lower() + KEYWORDS_DESCRIPTION[1:-1] + ", comma-separated."),
    ] = [],
) -> AutomaticCaptureBatch:
    # One call for up to three facts. Three separate round trips was friction on the only
    # path that matters, and friction on a call the host model already has to choose to
    # make is how a memory product ends up with three captures a fortnight.
    if _hosted_mode():
        # The whole batch goes: the account applies the capture policy and its own
        # automatic-mode switch, so the refusal log is the account's, not this computer's.
        extra = {"keywords": list(keywords)} if keywords else {}
        return _forward("memorysafe_auto_capture", AutomaticCaptureBatch, facts=list(facts), category=category, **extra)
    results: list[AutomaticCaptureResult] = []
    for position, raw in enumerate(facts[:3]):
        clean_content = " ".join(str(raw).split())
        if not clean_content:
            continue
        # Search words are held to the same refusals as the fact: a secret must not ride
        # in beside a harmless sentence. Refused words are dropped; the fact is still judged
        # on its own.
        offered = str(keywords[position]) if position < len(keywords) else ""
        if offered and capture_policy.classify(offered) is not None:
            offered = ""
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
        stored = _store().remember(clean_content, category, source="automatic", keywords=offered)
        # A SKIP changed nothing: the fact is already held in a memory this call may
        # not change, so it is not counted or described as saved.
        saved = stored["decision"] not in ("SKIP", "FULL")
        results.append(
            AutomaticCaptureResult(
                saved=saved,
                decision=stored["decision"],
                memory_id=stored["memory_id"],
                content=stored["content"],
                category=stored["category"],
                reason=f"Saved automatically. {stored['reason']}" if saved else stored["reason"],
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
    if _hosted_mode():
        return _forward("memorysafe_find", FindResult, query=query, limit=limit)
    matches = [FoundMemory.model_validate(item) for item in _store().find(query, limit)]
    return FindResult(query=query, count=len(matches), memories=matches)


@server.tool(
    name="memorysafe_forget",
    title="Forget a memory",
    description=(
        "Remove one memory from active recall, only when the user asks. This is not a "
        "permanent erase. Without an exact ID, find and confirm it first. Protected "
        "memories need confirm=true."
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
    confirm: Annotated[
        bool, Field(description="Required for a protected memory, after the user agrees.")
    ] = False,
) -> ForgetResult:
    if _hosted_mode():
        return _forward("memorysafe_forget", ForgetResult, memory_id=memory_id, confirm=confirm)
    return ForgetResult.model_validate(_store().forget(memory_id, confirm=confirm))


@server.tool(
    name="memorysafe_protect",
    title="Protect or unprotect a memory",
    description=(
        "Protect one memory (never evicted; forgetting needs confirmation), or pass "
        "protect=false to remove protection. Only when the user asks. Audited."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def protect_memory(
    memory_id: Annotated[str, Field(min_length=1, max_length=80, description="Exact memory ID.")],
    protect: Annotated[bool, Field(description="true protects, false unprotects.")] = True,
) -> ProtectResult:
    if _hosted_mode():
        return _forward("memorysafe_protect", ProtectResult, memory_id=memory_id, protect=protect)
    return ProtectResult.model_validate(_store().protect(memory_id, protected=protect))


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
    if _hosted_mode():
        return _forward("memorysafe_explain", ExplainResult, memory_id=memory_id)
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
    if _hosted_mode():
        return _forward("memorysafe_review_conflicts", ReviewConflictsResult, include_resolved=include_resolved)
    return ReviewConflictsResult.model_validate(
        _store().review_conflicts(include_resolved=include_resolved)
    )


@server.tool(
    name="memorysafe_resolve_conflict",
    title="Resolve a memory conflict",
    description=(
        "Supersede, keep both, restore (conflict stays open), or revert (reject the newer "
        "update, bring back the prior fact). Requires confirm=true after the user agrees. "
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
        Literal["supersede", "keep_both", "restore", "revert"],
        Field(description="supersede, keep_both, restore, or revert."),
    ],
    confirm: Annotated[
        bool, Field(description="Must be true; otherwise nothing is changed.")
    ] = False,
) -> ResolveConflictResult:
    if _hosted_mode():
        return _forward(
            "memorysafe_resolve_conflict", ResolveConflictResult, conflict_id=conflict_id, action=action, confirm=confirm
        )
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
    if _hosted_mode():
        return _forward("memorysafe_restore", RestoreResult, memory_id=memory_id, confirm=confirm)
    return RestoreResult.model_validate(_store().restore(memory_id, confirm=confirm))


@server.tool(
    name="memorysafe_doctor",
    title="Diagnose a MemorySafe install",
    description=(
        "Check this MemorySafe installation when it is not working, memories seem missing or a fresh install does not respond, before suggesting a reinstall. Read-only; never reads memory contents. Read 'next_actions' out in plain language, in order, not the raw checks."
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
        "Show local memory counts, storage, governance decisions and the health formula. Call it first when the user asks how to set it up. Pass open=true to also open the visual dashboard; if the returned 'opened' is 'window' or 'browser', say it opened rather than pasting the link."
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


# The health tool is described as counts, and an assistant is told to call it first. It
# also carries text: the six latest memories, the governance trail's old and new wording,
# and the three most used. Unclipped, one 10,000-character memory made the answer 5,448
# tokens, all of it sent to the assistant's provider by a call nobody made to read memories.
HEALTH_TEXT_CHARS = 200


def bounded_health(data: dict[str, Any]) -> dict[str, Any]:
    """`data` with every piece of memory text in it clipped to HEALTH_TEXT_CHARS. For the
    tool's answer only: the dashboard page reads its own payload, in full, on this computer."""

    def clip(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        one_line = " ".join(value.split())
        return one_line if len(one_line) <= HEALTH_TEXT_CHARS else one_line[: HEALTH_TEXT_CHARS - 1].rstrip() + "…"

    for memory in data.get("recent_memories") or []:
        memory["content"] = clip(memory.get("content"))
    for event in data.get("governance_events") or []:
        for key in ("replaced", "kept", "evidence", "reason"):
            if key in event:
                event[key] = clip(event[key])
    for used in (data.get("recall") or {}).get("most_used") or []:
        used["content"] = clip(used.get("content"))
    return data


def _dashboard_data(open_window: bool = False) -> DashboardResult:
    if _hosted_mode():
        # The account's own health (the hosted edition sends the same fields, minus this
        # computer's), with this computer's dashboard address put back: the window still
        # opens here, and shows the account's numbers.
        data = dict(hosted_proxy.call("memorysafe_health", {}))
        data["database_path"] = str(data.get("stored_in") or "Your hosted account")
        data["live_token_metrics"] = data.pop("token_estimate", None)
        data["status"] = "healthy"
        data.setdefault("recent_memories", [])
        data["dashboard_url"] = _dashboard_url()
        data["opened"] = _open_dashboard_window(data["dashboard_url"]) if open_window else None
        return DashboardResult.model_validate(data)
    data = _store().health()
    data["status"] = "healthy"
    data["recent_memories"] = _store().recent(6)
    data["dashboard_url"] = _dashboard_url()
    data["opened"] = _open_dashboard_window(data["dashboard_url"]) if open_window else None
    return DashboardResult.model_validate(bounded_health(data))


# Every tool's own refusals reach the assistant in their own words (tool_errors).
for _tool in server._tool_manager.list_tools():
    _tool.fn = spoken(_tool.fn)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
