"""Write-throughput benchmark: 500 remember() calls into an isolated temp store.

Usage:  python scripts/bench_writes.py [--src PATH] [--runs 3]
PATH defaults to plugins/memorysafe/src next to this script. Nothing outside a
temporary directory is touched.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


PEOPLE = "Avery Blake Casey Devon Emery Finley Gray Harper Jordan Kendall".split()
TOPICS = "billing onboarding security search mobile payments reporting analytics exports alerts".split()
ACTIONS = "owns reviews tests documents designs approves audits maintains supports migrates".split()
PLACES = "Lisbon Oslo Quito Kyoto Accra".split()


def distinct_workload() -> list[tuple[str, str]]:
    """500 distinct facts with no numbers: nothing merges, every write is compared."""

    items = []
    for i in range(500):
        person = PEOPLE[i % 10]
        topic = TOPICS[(i // 10) % 10]
        action = ACTIONS[(i // 100) % 5 + (i % 2) * 5]
        place = PLACES[(i // 100) % 5]
        items.append((f"{person} {action} the {topic} work from the {place} office", "project"))
    return items


def workload(kind: str = "tester") -> list[tuple[str, str]]:
    if kind == "distinct":
        return distinct_workload()
    items: list[tuple[str, str]] = []
    for i in range(60):
        items.append((f"Routine project log {i}: nightly build finished green on runner {i}", "project"))
    for i in range(440):
        items.append((f"Routine item {i}: checked the supply cart in room {i} and restocked gloves", "task"))
    return items


def run_once(src: Path, kind: str = "tester") -> float:
    with tempfile.TemporaryDirectory() as temp:
        os.environ["MEMORYSAFE_DB_PATH"] = str(Path(temp) / "bench.sqlite3")
        os.environ["MEMORYSAFE_STATE_DIR"] = str(Path(temp) / "state")
        from memorysafe_chatgpt.storage import MemoryStore

        store = MemoryStore(Path(os.environ["MEMORYSAFE_DB_PATH"]))
        start = time.perf_counter()
        for content, category in workload(kind):
            store.remember(content, category)
        return time.perf_counter() - start


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=Path, default=ROOT / "plugins" / "memorysafe" / "src")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--workload", choices=("tester", "distinct"), default="tester")
    args = parser.parse_args()
    sys.path.insert(0, str(args.src.resolve()))
    times = [run_once(args.src, args.workload) for _ in range(args.runs)]
    best = min(times)
    print(
        f"{args.workload}: 500 writes: best {best:.2f}s ({500 / best:.0f} writes/s), "
        f"median {statistics.median(times):.2f}s over {args.runs} runs"
    )


if __name__ == "__main__":
    main()
