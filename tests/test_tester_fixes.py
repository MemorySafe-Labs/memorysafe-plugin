"""Regression tests for the 0.4.10 tester findings (fixed in 0.4.11).

Run from the repository root:
    PYTHONPATH=plugins/memorysafe/src python -m pytest tests
Every test uses its own temporary store.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from memorysafe_chatgpt.lifecycle import classify_pair
from memorysafe_chatgpt.storage import MemoryStore

ROOT = Path(__file__).resolve().parents[1]


class StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "data" / "memorysafe.sqlite3"
        self.env = patch.dict(os.environ, {"MEMORYSAFE_DB_PATH": str(self.db),
                                           "MEMORYSAFE_STATE_DIR": str(Path(self.temp.name) / "state")})
        self.env.start()
        os.environ.pop("MEMORYSAFE_MAX_ACTIVE", None)
        self.store = MemoryStore(self.db)

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def history(self, memory_id: str) -> list[str]:
        return [e["decision"] for e in self.store.explain(memory_id)["history"]]

    def cli(self, *args: str) -> str:
        from memorysafe_chatgpt.cli import main

        out = io.StringIO()
        with patch("sys.argv", ["memorysafe", *args]), redirect_stdout(out):
            main()
        return out.getvalue()


# 1. retention -----------------------------------------------------------------
class CapacityTests(StoreCase):
    def routine(self, n: int, category: str = "task") -> list[dict]:
        return [self.store.remember(f"Routine item {i}: checked cart in room {i}", category) for i in range(n)]

    def test_no_capacity_limit_by_default(self) -> None:
        self.routine(40)
        health = self.store.health()
        self.assertEqual(health["active_memories"], 40)
        self.assertEqual(health["evicted_memories"], 0)
        self.assertIsNone(health["max_active"])

    def test_capacity_evicts_routine_first_and_keeps_rare_and_protected(self) -> None:
        with patch.dict(os.environ, {"MEMORYSAFE_MAX_ACTIVE": "20"}):
            safety = self.store.remember("Bed 12 patient is allergic to penicillin", "safety")
            rare = self.store.remember("The spare server room key is under the reception desk", "other")
            self.routine(60)
        health = self.store.health()
        self.assertEqual(health["active_memories"], 20)
        self.assertEqual(health["evicted_memories"], 42)
        self.assertEqual(health["decision_counts"].get("EVICT"), 42)
        for kept in (safety, rare):
            self.assertEqual(self.store.explain(kept["memory_id"])["state"], "active")

    def test_protected_memories_are_never_evicted(self) -> None:
        with patch.dict(os.environ, {"MEMORYSAFE_MAX_ACTIVE": "3"}):
            guarded = [self.store.remember(f"Decision {w}: ship it", "decision") for w in ("alpha", "beta", "gamma", "delta")]
            self.routine(5)
        for memory in guarded:
            self.assertEqual(self.store.explain(memory["memory_id"])["state"], "active")

    def test_eviction_is_audited_and_restorable(self) -> None:
        with patch.dict(os.environ, {"MEMORYSAFE_MAX_ACTIVE": "5"}):
            first = self.routine(10)[0]
        self.assertEqual(self.store.explain(first["memory_id"])["state"], "evicted")
        self.assertIn("EVICT", self.history(first["memory_id"]))
        self.store.restore(first["memory_id"], confirm=True)
        self.assertEqual(self.store.explain(first["memory_id"])["state"], "active")

    def test_routine_project_logs_are_not_auto_protected(self) -> None:
        logs = [self.store.remember(f"Project log {i}: build green on runner {i} on 3 Sep 2026", "project")
                for i in range(20)]
        self.assertLessEqual(sum(bool(r["protected"]) for r in logs), 2)
        self.assertFalse(self.store.remember("Working note about the dashboard colours", "project")["protected"])
        self.assertTrue(self.store.remember("We decided the Apollo launch is 5 Dec 2026", "project")["protected"])


# 2. stale state -----------------------------------------------------------------
STALE = [
    ("Dana moved to Toronto.", "Dana lives in Montreal."),
    ("The payments API was upgraded to version 2.4.0.", "The payments API is on version 2.3.1."),
    ("The Apollo launch deadline moved to 22 Oct 2026.", "The Apollo launch deadline is 15 Oct 2026."),
    ("The daily standup moved to 10am.", "The daily standup is at 9am."),
    ("We switched the backend database from Postgres to MySQL.", "The backend database is Postgres."),
    ("The Apollo deadline is 22 Oct 2026.", "The Apollo deadline is 15 Oct 2026."),
]


class StaleStateTests(StoreCase):
    def test_value_and_change_language_contradictions(self) -> None:
        for new, old in STALE:
            with self.subTest(new=new):
                self.assertEqual(classify_pair(new, old)["action"], "contradict")

    def test_not_contradictions(self) -> None:
        for new, old in (
            ("Routine item 27: checked cart in room 27", "Routine item 7: checked cart in room 7"),
            ("Deadline is 4 November 2026", "Deadline is 28 September 2026"),  # no subject
            ("The Apollo party moved to Toronto.", "Dana lives in Montreal."),
            ("Sam lives in Paris.", "Dana lives in Montreal."),
        ):
            with self.subTest(new=new):
                self.assertNotEqual(classify_pair(new, old)["action"], "contradict")

    def test_find_returns_the_new_fact_first(self) -> None:
        for new, old in STALE[:5]:
            self.store.remember(old, "project")
            self.store.remember(new, "project")
        for query, fresh in (("where does Dana live", "Toronto"), ("payments API version", "2.4.0"),
                             ("Apollo launch deadline", "22 Oct"), ("daily standup", "10am"),
                             ("backend database", "MySQL")):
            hits = self.store.find(query, 5, record=False)
            self.assertIn(fresh, hits[0]["content"], query)

    def test_open_conflict_never_ranks_older_above_newer_unmarked(self) -> None:
        old = self.store.remember("The daily standup is at 9am.", "project")
        new = self.store.remember("The daily standup moved to 10am.", "project")
        self.store.resolve_conflict(new["conflict_id"], "restore", confirm=True)
        hits = self.store.find("daily standup 9am", 5, record=False)
        ids = [h["memory_id"] for h in hits]
        self.assertLess(ids.index(new["memory_id"]), ids.index(old["memory_id"]))
        self.assertTrue(all(h["needs_review"] for h in hits))


# 3. protect / forget -------------------------------------------------------------
class ProtectForgetTests(StoreCase):
    def test_protect_unprotect_are_audited(self) -> None:
        mid = self.store.remember("The alarm code changes quarterly", "other")["memory_id"]
        self.assertTrue(self.store.protect(mid)["protected"])
        self.assertTrue(self.store.explain(mid)["protected_because"])
        self.assertFalse(self.store.protect(mid, protected=False)["protected"])
        self.assertIsNone(self.store.explain(mid)["protected_because"])
        self.assertEqual(self.history(mid)[-2:], ["PROTECT", "UNPROTECT"])

    def test_forgetting_a_protected_memory_needs_confirm(self) -> None:
        mid = self.store.remember("Never deploy on Fridays", "decision")["memory_id"]
        refused = self.store.forget(mid)
        self.assertFalse(refused["forgotten"])
        self.assertTrue(refused["needs_confirmation"])
        self.assertEqual(self.store.explain(mid)["state"], "active")
        self.assertTrue(self.store.forget(mid, confirm=True)["forgotten"])
        unprotected = self.store.remember("Lunch is at noon", "other")["memory_id"]
        self.assertTrue(self.store.forget(unprotected)["forgotten"])

    def test_cli_exposes_governance_commands(self) -> None:
        mid = self.store.remember("The loading dock closes at dusk", "other")["memory_id"]
        self.cli("protect", mid)
        self.assertTrue(self.store.explain(mid)["protected"])
        self.assertIn("confirm", self.cli("forget", mid).lower())
        self.cli("forget", mid, "--confirm")
        self.assertEqual(self.store.explain(mid)["state"], "deleted")
        self.cli("restore", mid, "--confirm")
        self.cli("unprotect", mid)
        detail = self.store.explain(mid)
        self.assertEqual((detail["state"], detail["protected"]), ("active", False))
        self.store.remember("Contract renews at $12,000", "project")
        self.store.remember("Contract renews at $15,000", "project", source="agent")
        listed = json.loads(self.cli("review-conflicts", "--json"))
        self.assertEqual(listed["count"], 1)
        cid = listed["conflicts"][0]["conflict_id"]
        self.assertIn("Conflict", self.cli("review-conflicts"))
        done = json.loads(self.cli("resolve-conflict", str(cid), "keep_both", "--confirm", "--json"))
        self.assertTrue(done["resolved"])

    def test_mcp_protect_tool(self) -> None:
        from memorysafe_chatgpt import server

        server._stores.clear()
        mid = self.store.remember("Visitors sign in at the front desk", "other")["memory_id"]
        result = asyncio.run(server.server.call_tool("memorysafe_protect", {"memory_id": mid}))
        self.assertTrue(result.structured_content["protected"])
        refused = asyncio.run(server.server.call_tool("memorysafe_forget", {"memory_id": mid}))
        self.assertTrue(refused.structured_content["needs_confirmation"])
        server._stores.clear()


# 4. conflict recovery ---------------------------------------------------------------
class ConflictRecoveryTests(StoreCase):
    def open_pair(self) -> tuple[dict, dict]:
        a = self.store.remember("The vendor contract renews at $12,000 per year.", "project")
        b = self.store.remember("The vendor contract renews at $15,000 per year.", "project", source="agent")
        self.assertEqual(b["lifecycle"], "needs_review")
        return a, b

    def test_restore_reopens_a_conflict_closed_by_forget(self) -> None:
        for forget_new in (True, False):
            with self.subTest(forget_new=forget_new):
                a, b = self.open_pair()
                target = b if forget_new else a
                self.store.forget(target["memory_id"], confirm=True)
                self.assertNotIn(b["conflict_id"], [c["conflict_id"] for c in self.store.review_conflicts()["conflicts"]])
                restored = self.store.restore(target["memory_id"], confirm=True)
                self.assertIn(b["conflict_id"], restored["reopened_conflicts"])
                self.assertIn(b["conflict_id"], [c["conflict_id"] for c in self.store.review_conflicts()["conflicts"]])
                self.store.resolve_conflict(b["conflict_id"], "keep_both", confirm=True)
                for m in (a, b):
                    self.store.forget(m["memory_id"], confirm=True)

    def test_resolve_restore_keeps_the_conflict_open(self) -> None:
        self.store.remember("The QA lead for Apollo is Priya.", "project")
        new = self.store.remember("The QA lead for Apollo is now Marco.", "project")
        self.assertEqual(new["lifecycle"], "superseded_previous")
        result = self.store.resolve_conflict(new["conflict_id"], "restore", confirm=True)
        self.assertEqual(result["conflict_status"], "open")
        self.assertEqual(self.store.health()["open_reviews"], 1)

    def test_revert_rejects_the_update_and_restores_the_prior_fact(self) -> None:
        right = self.store.remember("The release freeze starts on 3 Nov 2026.", "project")
        wrong = self.store.remember("The release freeze moved to 10 Nov 2026.", "project")
        self.assertEqual(self.store.explain(right["memory_id"])["state"], "superseded")
        self.store.resolve_conflict(wrong["conflict_id"], "revert", confirm=True)
        self.assertEqual(self.store.explain(right["memory_id"])["state"], "active")
        self.assertEqual(self.store.explain(wrong["memory_id"])["state"], "rejected")
        self.assertIn("REJECT", self.history(wrong["memory_id"]))
        hits = self.store.find("release freeze", 5, record=False)
        self.assertEqual([h["memory_id"] for h in hits], [right["memory_id"]])
        self.assertEqual(self.store.health()["open_reviews"], 0)


# 5. false certainty ----------------------------------------------------------------
class FalseCertaintyTests(StoreCase):
    def test_lower_confidence_write_does_not_supersede(self) -> None:
        manual = self.store.remember("The client budget is $50,000.", "project")
        agent = self.store.remember("The client budget is now $80,000.", "project", source="agent")
        self.assertEqual(agent["lifecycle"], "needs_review")
        self.assertIn("lower confidence", agent["lifecycle_reason"])
        self.assertEqual(self.store.explain(manual["memory_id"])["state"], "active")
        hits = self.store.find("client budget", 5, record=False)
        self.assertEqual(hits[0]["memory_id"], manual["memory_id"])
        self.assertTrue(all(h["needs_review"] and h["open_conflict_ids"] for h in hits))
        self.assertTrue(all(0 < h["confidence"] <= 1 for h in hits))

    def test_equal_confidence_update_still_supersedes(self) -> None:
        old = self.store.remember("The client budget is $50,000.", "project")
        self.store.remember("The client budget is now $80,000.", "project")
        self.assertEqual(self.store.explain(old["memory_id"])["state"], "superseded")

    def test_health_counts_open_conflicts(self) -> None:
        self.store.remember("The client budget is $50,000.", "project")
        before = self.store.health()
        self.store.remember("The client budget is now $80,000.", "project", source="agent")
        after = self.store.health()
        self.assertEqual(after["open_reviews"], 1)
        self.assertEqual(after["conflict_penalty"], 5)
        self.assertLess(after["memory_health"], before["memory_health"])

    def test_cli_find_shows_conflict_and_confidence(self) -> None:
        self.store.remember("The client budget is $50,000.", "project")
        self.store.remember("The client budget is now $80,000.", "project", source="agent")
        out = self.cli("find", "client budget")
        self.assertIn("NEEDS REVIEW", out)
        self.assertIn("confidence 0.95", out)
        self.assertIn("confidence 0.85", out)


# rough edges ---------------------------------------------------------------------
class RoughEdgeTests(StoreCase):
    def test_numbered_items_are_not_merged(self) -> None:
        seven = self.store.remember("Routine item 7: checked the supply cart in room 7", "task")
        other = self.store.remember("Routine item 27: checked the supply cart in room 27", "task")
        self.assertEqual(other["decision"], "STORE")
        self.assertNotEqual(seven["memory_id"], other["memory_id"])

    def test_merge_never_loses_text(self) -> None:
        first = self.store.remember("I prefer concise answers in every reply", "preference")
        merged = self.store.remember("I prefer concise answers in every single reply", "preference")
        self.assertEqual(merged["decision"], "MERGE")
        reasons = " ".join(e["reason"] for e in self.store.explain(first["memory_id"])["history"])
        self.assertIn("I prefer concise answers in every reply", reasons)

    def test_number_search_prefers_the_exact_number(self) -> None:
        for i in range(1, 10):
            self.store.remember(f"Supply cart for room {i} restocked with gloves", "task")
        self.assertIn("room 7 ", self.store.find("room 7", 3, record=False)[0]["content"])

    def test_similar_routine_memories_open_no_conflicts(self) -> None:
        for i in range(200):
            self.store.remember(f"Routine item {i}: checked the supply cart in room {i}", "task")
        self.assertEqual(self.store.health()["open_reviews"], 0)

    def test_cli_does_not_call_an_auto_resolved_conflict_open(self) -> None:
        self.cli("remember", "The daily standup is at 9am.", "--category", "project")
        out = self.cli("remember", "The daily standup moved to 10am.", "--category", "project")
        self.assertIn("resolved automatically", out)
        self.assertNotIn("is open", out)

    def test_versions_agree(self) -> None:
        from memorysafe_chatgpt import __version__
        from memorysafe_chatgpt.bootstrap_catalog import VERSION

        self.assertEqual(__version__, VERSION)
        self.assertEqual(VERSION, "0.4.11")
        plugin = ROOT / "plugins" / "memorysafe"
        for path in (plugin / "plugin.json", plugin / ".claude-plugin" / "plugin.json"):
            if path.exists():
                self.assertEqual(json.loads(path.read_text())["version"], VERSION, path)
        for readme in (ROOT / "README.md", plugin / "README.md"):
            if plugin.exists() and readme.exists():  # only in the plugin repository layout
                self.assertTrue(readme.read_text().startswith(f"# MemorySafe {VERSION}"), readme)


if __name__ == "__main__":
    unittest.main()
