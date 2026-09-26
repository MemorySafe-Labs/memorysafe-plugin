"""Acceptance run for the five tester evaluation scenarios.

Every scenario runs against its own throwaway store: MEMORYSAFE_DB_PATH and
MEMORYSAFE_STATE_DIR point into a temporary directory, so no real MemorySafe data
is read or written.

    python scripts/tester_scenarios.py            # exits non-zero if any scenario fails
    python scripts/tester_scenarios.py --src DIR  # test another source tree
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sys
import tempfile
import traceback
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class Isolated:
    """A temp store wired through the same env vars the server and CLI read."""

    def __init__(self, **env: str) -> None:
        self.env = env

    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="memorysafe-acceptance-")
        base = Path(self.temp.name)
        self.saved = {k: os.environ.get(k) for k in ("MEMORYSAFE_DB_PATH", "MEMORYSAFE_STATE_DIR", "MEMORYSAFE_MAX_ACTIVE", *self.env)}
        os.environ["MEMORYSAFE_DB_PATH"] = str(base / "data" / "memorysafe.sqlite3")
        os.environ["MEMORYSAFE_STATE_DIR"] = str(base / "state")
        os.environ.pop("MEMORYSAFE_MAX_ACTIVE", None)
        os.environ.update(self.env)
        from memorysafe_chatgpt import server
        from memorysafe_chatgpt.storage import MemoryStore

        server._stores.clear()
        self.store = MemoryStore(Path(os.environ["MEMORYSAFE_DB_PATH"]))
        return self

    def __exit__(self, *exc) -> None:
        from memorysafe_chatgpt import server

        server._stores.clear()
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp.cleanup()

    def cli(self, *args: str) -> str:
        from memorysafe_chatgpt.cli import main

        out = io.StringIO()
        with patch("sys.argv", ["memorysafe", *args]), redirect_stdout(out):
            main()
        return out.getvalue()

    def mcp(self, tool: str, arguments: dict) -> dict:
        from memorysafe_chatgpt import server

        result = asyncio.run(server.server.call_tool(tool, arguments))
        if result.is_error:
            raise AssertionError(f"{tool} failed: {result}")
        return result.structured_content


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def history(store, memory_id: str) -> list[str]:
    return [event["decision"] for event in store.explain(memory_id)["history"]]


# --------------------------------------------------------------------------- 1
def scenario_1_rare_but_important() -> str:
    cap = 150
    with Isolated(MEMORYSAFE_MAX_ACTIVE=str(cap)) as env:
        store = env.store
        routine_project = []
        for i in range(60):
            routine_project.append(store.remember(
                f"Routine project log {i}: nightly build finished green on runner {i}", "project"))
            if i == 20:
                safety = store.remember(
                    "Safety: the patient in bed 12 has a severe penicillin allergy, never give penicillin",
                    "safety")
                rare = store.remember(
                    "The spare key for the server room is taped under the third drawer of the reception desk",
                    "other")
        for i in range(440):
            store.remember(f"Routine item {i}: checked the supply cart in room {i} and restocked gloves", "task")

        health = store.health()
        check(health["active_memories"] <= cap, f"active {health['active_memories']} exceeds cap {cap}")
        for fact in (safety, rare):
            check(store.explain(fact["memory_id"])["state"] == "active", f"lost: {fact['content']}")
        top = store.find("penicillin allergy", 3, record=False)
        check(top and top[0]["memory_id"] == safety["memory_id"], "safety fact is not the top hit")
        top = store.find("where is the spare key for the server room", 3, record=False)
        check(top and top[0]["memory_id"] == rare["memory_id"], "rare fact is not the top hit")
        evicted = health["evicted_memories"]
        check(evicted == 502 - health["active_memories"], f"evicted {evicted} does not account for the gap")
        evict_events = health["decision_counts"].get("EVICT", 0)
        check(evict_events == evicted, f"{evict_events} EVICT events for {evicted} evictions")
        evicted_routine = [r["memory_id"] for r in routine_project
                           if store.explain(r["memory_id"])["state"] == "evicted"]
        check(evicted_routine, "no routine project log was evicted")
        check(all("EVICT" in history(store, m) for m in evicted_routine),
              "an evicted memory has no EVICT event in its history")
        protected_routine = sum(bool(r["protected"]) for r in routine_project)
        check(protected_routine == 0, f"{protected_routine}/60 routine project logs were auto-protected")
        check(health["open_reviews"] == 0, f"{health['open_reviews']} review conflicts from routine notes")
        return (f"cap {cap}: {health['active_memories']} active, {evicted} evicted (all audited), "
                "safety + rare fact retained and top hits, 0 routine logs auto-protected, 0 conflicts")


# --------------------------------------------------------------------------- 2
STALE = [
    ("Dana lives in Montreal.", "Dana moved to Toronto.", "where does Dana live", "Toronto", "Montreal"),
    ("The payments API is on version 2.3.1.", "The payments API was upgraded to version 2.4.0.",
     "payments API version", "2.4.0", "2.3.1"),
    ("The Apollo launch deadline is 15 Oct 2026.", "The Apollo launch deadline moved to 22 Oct 2026.",
     "Apollo launch deadline", "22 Oct", "15 Oct"),
    ("The daily standup is at 9am.", "The daily standup moved to 10am.", "what time is the daily standup",
     "10am", "9am"),
    ("The backend database is Postgres.", "We switched the backend database from Postgres to MySQL.",
     "backend database", "MySQL", "Postgres"),
]


def scenario_2_stale_state() -> str:
    with Isolated() as env:
        store = env.store
        for i in range(30):
            store.remember(f"Routine item {i}: checked the supply cart in room {i}", "task")
        for old, new, *_ in STALE:
            store.remember(old, "project")
            store.remember(new, "project")
        notes = []
        for old, new, query, fresh, stale in STALE:
            hits = store.find(query, 5, record=False)
            check(hits, f"nothing found for {query!r}")
            check(fresh in hits[0]["content"], f"{query!r}: first hit is {hits[0]['content']!r}")
            if stale:
                stale_hits = [h for h in hits if stale in h["content"] and fresh not in h["content"]]
                check(all(h["needs_review"] for h in stale_hits),
                      f"{query!r}: stale fact returned unmarked")
                notes.append(f"{fresh} ({'only' if not stale_hits else 'first'})")
            else:
                notes.append(f"{fresh} (first)")
        return "new fact first for all 5: " + ", ".join(notes)


# --------------------------------------------------------------------------- 3
def scenario_3_protect_forget() -> str:
    with Isolated() as env:
        store = env.store
        fact = store.remember("The office alarm code changes every quarter", "other")
        mid = fact["memory_id"]
        check(not fact["protected"], "setup: expected an unprotected memory")
        # MCP
        result = env.mcp("memorysafe_protect", {"memory_id": mid})
        check(result["protected"] and store.explain(mid)["protected"], "MCP protect did not protect")
        refused = env.mcp("memorysafe_forget", {"memory_id": mid})
        check(not refused["forgotten"] and refused["needs_confirmation"], "protected forget did not ask for confirm")
        check(store.explain(mid)["state"] == "active", "protected memory forgotten without confirm")
        env.mcp("memorysafe_forget", {"memory_id": mid, "confirm": True})
        check(store.explain(mid)["state"] == "deleted", "confirmed forget did not forget")
        env.mcp("memorysafe_restore", {"memory_id": mid, "confirm": True})
        check(store.explain(mid)["state"] == "active", "restore failed")
        env.mcp("memorysafe_protect", {"memory_id": mid, "protect": False})
        check(not store.explain(mid)["protected"], "MCP unprotect failed")
        # CLI
        other = store.remember("The loading dock closes at dusk on Sundays", "other")["memory_id"]
        env.cli("protect", other)
        check(store.explain(other)["protected"], "CLI protect failed")
        out = env.cli("forget", other)
        check("confirm" in out.lower() and store.explain(other)["state"] == "active", "CLI forget of protected did not ask")
        env.cli("forget", other, "--confirm")
        check(store.explain(other)["state"] == "deleted", "CLI forget --confirm failed")
        env.cli("restore", other, "--confirm")
        env.cli("unprotect", other)
        check(store.explain(other)["state"] == "active" and not store.explain(other)["protected"], "CLI restore/unprotect failed")
        for memory_id in (mid, other):
            trail = history(store, memory_id)
            for decision in ("PROTECT", "FORGET", "RESTORE", "UNPROTECT"):
                check(decision in trail, f"{decision} missing from history of {memory_id}: {trail}")
        return "protect/unprotect/forget(confirm)/restore via MCP and CLI; all four audited in history"


# --------------------------------------------------------------------------- 4
def scenario_4_conflict_recovery() -> str:
    with Isolated() as env:
        store = env.store
        right = store.remember("The release freeze starts on 3 Nov 2026.", "project")
        wrong = store.remember("The release freeze moved to 10 Nov 2026.", "project")
        check(wrong["lifecycle"] == "superseded_previous", f"contradiction not detected: {wrong['lifecycle']}")
        cid = wrong["conflict_id"]
        done = json.loads(env.cli("resolve-conflict", str(cid), "revert", "--confirm", "--json"))
        check(done["resolved"] and done["action"] == "revert", "revert did not run")
        hits = store.find("release freeze", 5, record=False)
        check(hits and hits[0]["memory_id"] == right["memory_id"], "prior fact not back first after revert")
        check(not any("10 Nov" in h["content"] for h in hits), "rejected update still in recall")
        check(store.health()["open_reviews"] == 0, "revert left a conflict open")

        # forget + restore reopens
        a = store.remember("The vendor contract renews at $12,000 per year.", "project")
        b = store.remember("The vendor contract renews at $15,000 per year.", "project", source="agent")
        check(b["lifecycle"] == "needs_review", f"expected an open conflict, got {b['lifecycle']}")
        cid = b["conflict_id"]
        check(store.explain(a["memory_id"])["state"] == "active", "agent write replaced the manual fact")
        store.forget(b["memory_id"], confirm=True)
        check(store.review_conflicts()["count"] == 0, "forget did not close the conflict")
        env.cli("restore", b["memory_id"], "--confirm")
        open_ids = [c["conflict_id"] for c in store.review_conflicts()["conflicts"]]
        check(cid in open_ids, "restore did not reopen the conflict")

        # resolve 'restore' keeps it flagged
        old = store.remember("The QA lead for Apollo is Priya.", "project")
        new = store.remember("The QA lead for Apollo is now Marco.", "project")
        check(new["lifecycle"] == "superseded_previous", f"QA lead change not detected: {new['lifecycle']}")
        store.resolve_conflict(new["conflict_id"], "restore", confirm=True)
        conflicts = {c["conflict_id"]: c for c in store.review_conflicts()["conflicts"]}
        check(new["conflict_id"] in conflicts, "resolve 'restore' left both active with no flag")
        flagged = [h for h in store.find("QA lead Apollo", 5, record=False) if h["needs_review"]]
        check({h["memory_id"] for h in flagged} == {old["memory_id"], new["memory_id"]},
              "both sides should be flagged in find after restore")
        return "contradiction detected; CLI 'resolve-conflict N revert' restores prior fact in one action; forget+restore reopens; resolve 'restore' stays flagged"


# --------------------------------------------------------------------------- 5
def scenario_5_false_certainty() -> str:
    with Isolated() as env:
        store = env.store
        manual = store.remember("The client budget for Apollo is $50,000.", "project")
        before = store.health()["memory_health"]
        agent = store.remember("The client budget for Apollo is now $80,000.", "project", source="agent")
        check(agent["confidence"] < manual["confidence"], "setup: agent write should be lower confidence")
        check(agent["lifecycle"] == "needs_review", f"agent write not flagged: {agent['lifecycle']}")
        check(store.explain(manual["memory_id"])["state"] == "active", "agent write superseded the manual fact")
        after = store.health()
        check(after["open_reviews"] >= 1 and after["memory_health"] < before,
              f"health did not drop with an open conflict ({before} -> {after['memory_health']})")
        found = env.mcp("memorysafe_find", {"query": "Apollo client budget", "limit": 5})["memories"]
        check(len(found) == 2 and all(m["needs_review"] and m["open_conflict_ids"] and m["review_note"] for m in found),
              "MCP find did not mark both sides of the open conflict")
        check(all("confidence" in m for m in found), "confidence missing from find")
        check(found[0]["memory_id"] == manual["memory_id"], "lower-confidence write outranked the manual fact")
        human = env.cli("find", "Apollo client budget")
        check("needs review" in human.lower() and "confidence 0.95" in human, "CLI find output hides conflict/confidence")
        return (f"both sides marked (MCP+CLI) with confidence; manual 0.95 fact kept over agent 0.85; "
                f"health {before} -> {after['memory_health']} with {after['open_reviews']} open conflict")


SCENARIOS = [
    ("1 rare-but-important retention", scenario_1_rare_but_important),
    ("2 stale-state suppression", scenario_2_stale_state),
    ("3 explicit protect/forget", scenario_3_protect_forget),
    ("4 conflict recovery", scenario_4_conflict_recovery),
    ("5 false certainty", scenario_5_false_certainty),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=Path, default=ROOT / "plugins" / "memorysafe" / "src")
    args = parser.parse_args()
    sys.path.insert(0, str(args.src.resolve()))
    failures = 0
    for name, run in SCENARIOS:
        try:
            detail = run()
            print(f"PASS  Scenario {name}: {detail}")
        except (Exception, SystemExit) as error:  # noqa: BLE001 - report every scenario
            failures += 1
            print(f"FAIL  Scenario {name}: {error}")
            if os.environ.get("MEMORYSAFE_ACCEPTANCE_TRACE"):
                traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failures}/{len(SCENARIOS)} scenarios passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
