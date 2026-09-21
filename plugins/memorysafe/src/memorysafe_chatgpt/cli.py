from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .doctor import create_support_bundle, run_doctor


def _print_human(report: dict) -> None:
    print(f"MemorySafe Doctor: {report['overall_status'].upper()}")
    for check in report["checks"]:
        # "info" became reachable on every Windows plugin install once the
        # capture_hook check landed (it reports the prompt-time hint as
        # unavailable there, not broken). A total dict lookup against this
        # open-ended status field crashed `memorysafe doctor` with
        # KeyError('info') -- the exact command plugin/INSTALL.md tells
        # users to run when something looks wrong. Any status this dict
        # doesn't know about must degrade to a plain bullet, not kill the
        # report.
        marker = {"pass": "✓", "info": "i", "warning": "!", "error": "✗"}.get(check["status"], "·")
        print(f"{marker} {check['summary']}")
    print("\nPrivate by default: no memories, chats, or secrets were included or uploaded.")


def _resolve_database(install_root: Path | None) -> Path:
    import os
    import sys

    override = os.environ.get("MEMORYSAFE_DB_PATH")
    if override:
        return Path(override)
    if install_root is not None:
        root = install_root
    elif os.environ.get("MEMORYSAFE_INSTALL_ROOT"):
        root = Path(os.environ["MEMORYSAFE_INSTALL_ROOT"])
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "MemorySafe"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "MemorySafe"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        root = (Path(xdg) if xdg else Path.home() / ".local" / "share") / "MemorySafe"
    return Path(root) / "data" / "memorysafe.sqlite3"


def _print_explanation(detail: dict) -> None:
    if not detail.get("found"):
        print(f"No memory with id {detail['memory_id']}.")
        return
    print(f"{detail['memory_id']}  ({detail['state']})")
    print(f"  {detail['content']}\n")
    if detail["protected"]:
        print(f"  Protected: {detail['protected_because']}")
        print(f"  Since:     {detail['protected_since']}")
    else:
        print("  Not protected.")
    print(f"  Recalled:  {detail['recall_count']} time(s)\n")
    print("  Decision history")
    for event in detail["history"]:
        print(f"    {event['at'][:19]}  {event['decision']:8s} {event['reason']}")
    if detail.get("relations"):
        print("\n  Replacements")
        for rel in detail["relations"]:
            print(
                f"    {rel['created_at'][:19]}  {rel['decision']:10s} {rel['status']:10s} "
                f"{rel['old_memory_id']} -> {rel['new_memory_id']}"
            )
            print(f"      {rel['reason']} ({rel['evidence']})")
    print(f"\n  {detail['note']}")


CATEGORIES = ("preference", "personal", "project", "decision", "task", "safety", "other")


def _print_matches(query: str, matches: list[dict]) -> None:
    if not matches:
        print(f'Nothing stored matches "{query}".')
        return
    print(f'{len(matches)} match(es) for "{query}":\n')
    for match in matches:
        print(f"  {match['content']}")
        print(
            f"    {match['memory_id']}  {match['category']}  "
            f"score {match['match_score']:.2f}  updated {match['updated_at'][:10]}"
            + ("  protected" if match["protected"] else "")
        )
        print()
    print("Run  memorysafe explain <id>  to see why one is held.")


def _print_written(result: dict) -> None:
    print(f"{result['decision']}  {result['memory_id']}")
    print(f"  {result['content']}\n")
    print(f"  Category:   {result['category']}")
    print(f"  Importance: {result['importance']}   Confidence: {result['confidence']}")
    print(f"  Protected:  {'yes' if result['protected'] else 'no'}")
    print(f"  {result['reason']}")
    # Supersession is the one outcome a caller must not miss: something they stored
    # earlier is no longer active, and nothing else on this path would say so.
    if result.get("lifecycle") and result["lifecycle"] != "none":
        print(f"\n  Lifecycle:  {result['lifecycle']}")
        if result.get("replaced_memory_id"):
            print(f"  Replaced:   {result['replaced_memory_id']}")
        if result.get("conflict_id"):
            print(f"  Review:     conflict {result['conflict_id']} is open")
        if result.get("lifecycle_reason"):
            print(f"  Because:    {result['lifecycle_reason']}")


def _print_migration(found: dict, changed: list[str], applied: bool) -> None:
    print("MemorySafe migrate" + ("" if applied else " (dry run: nothing changed)"))
    removable = False
    restart = []
    for key, label in (("claude_code", "Claude Code"), ("codex", "Codex")):
        entry = found[key]
        if not entry["registered"]:
            print(f"  {label:12s} no manual registration")
        elif not entry["plugin_installed"]:
            # Without that assistant's own plugin, the manual entry is its only way in.
            print(
                f"  {label:12s} registered by hand in {entry['config']} -> "
                f"kept: the MemorySafe plugin for {label} is not installed"
            )
        elif entry["config"] in changed:
            print(f"  {label:12s} removed from {entry['config']} (backup: {entry['config']}.memorysafe-backup)")
            restart.append(label)
        elif applied:
            print(f"  {label:12s} registered by hand in {entry['config']} -> could not be removed")
        else:
            print(f"  {label:12s} registered by hand in {entry['config']} -> would remove")
            removable = True
    projects = found["claude_code"].get("projects") or []
    project_files = found["claude_code"].get("project_files") or []
    if projects or project_files:
        # These outlived every earlier migrate, which only ever read the user-scope entry.
        for name in projects:
            state = "removed from" if found["claude_code"]["config"] in changed and applied else (
                "would remove from" if found["claude_code"]["plugin_installed"] else "kept in"
            )
            print(f"  Project      memorysafe {state} {name} in {found['claude_code']['config']}")
        for path in project_files:
            state = "removed from" if path in changed else ("would remove from" if found["claude_code"]["plugin_installed"] else "kept in")
            print(f"  Project      memorysafe {state} {path}")
        if not found["claude_code"]["plugin_installed"]:
            print("               kept: the MemorySafe plugin for Claude Code is not installed")
        elif not applied:
            removable = True
    if found["old_runtime"]:
        megabytes = found["old_runtime"]["bytes"] / (1024 * 1024)
        print(
            f"  Old runtime  {found['old_runtime']['path']} ({megabytes:.0f} MB) left in place: "
            "Windows and older Claude Desktop installs may still use it"
        )
    if found["launch_agents"]:
        print(f"  LaunchAgents {', '.join(found['launch_agents'])} left in place: ChatGPT on the web still needs them")
    if not applied and removable:
        print("\nRun  memorysafe migrate --apply  to make these changes. Each file is backed up first.")
    if restart:
        # The assistant keeps the old registration's tools until it reads its config again.
        print(f"\nRestart {' and '.join(restart)} so the old registration is gone from new conversations.")
    if found["codex"]["registered"]:
        # Codex rewrites config.toml from its own state. An entry removed here while
        # it is running comes back the next time it saves: on this machine the same
        # block returned twice, hours after being deleted, which is why it looked
        # like MemorySafe was rewriting it.
        print(
            "\nClose Codex first. It rewrites config.toml from its own state, so an entry"
            "\nremoved while it is running comes back when it next saves."
        )


def _megabytes(size: int) -> str:
    return f"{size / (1024 * 1024):.0f} MB" if size >= 1024 * 1024 else f"{size / 1024:.0f} KB"


def _print_uninstall(items: list[dict], result: dict, applied: bool, purge: bool) -> None:
    print("MemorySafe uninstall" + ("" if applied else " (dry run: nothing changed)"))
    if not items:
        print("\n  Nothing of MemorySafe's is on this computer.")
        return
    total = sum(item["bytes"] for item in items if not item["purge_only"])
    print(f"One memory for every assistant, off this computer again. {_megabytes(total)} to free.\n")
    for item in items:
        size = f"  ({_megabytes(item['bytes'])})" if item["bytes"] else ""
        if item["manual"]:
            print(f"  !  {item['label']:16s} {item['detail']}{size}")
            print(f"     {item['manual']}")
        elif item["purge_only"] and not purge:
            # Never a side effect of uninstalling: a person who reinstalls expects these back.
            print(f"  ·  {item['label']:16s} {item['detail']}{size} -> kept; add --purge to delete")
        elif applied:
            marker = "✓" if "{}: {}".format(item["label"], item["detail"]) in result["removed"] else "✗"
            print(f"  {marker}  {item['label']:16s} {item['detail']}{size}")
        else:
            print(f"  →  {item['label']:16s} {item['detail']}{size} -> would remove")
    if result["memories_backup"]:
        print(f"\n  Your memories were copied to {result['memories_backup']} before being deleted.")
    for failure in result["failed"]:
        print(f"\n  Could not remove {failure}")
    if result.get("still_in_use"):
        # A list of WinError 5 lines tells the reader nothing they can act on. The
        # first uninstall on this machine left all 268 MB behind for exactly this
        # reason: MemorySafe was running in every assistant at the time.
        print(
            "\n  Those are in use, which means MemorySafe is still running. Close Claude Desktop,"
            "\n  Claude Code and Codex, then run this again -- it picks up where it left off."
        )
    if not applied:
        print("\nRun  memorysafe uninstall --apply  to remove these. Each file it edits is backed up first.")
        if not purge:
            print("Add --purge to delete your memories too; a copy is saved to your home folder first.")


def _print_connect(agents: list[dict], results: list[dict], applied: bool) -> None:
    import os
    import sys

    from .agents import command_line, plan

    print("MemorySafe connect" + ("" if applied else " (dry run: nothing changed)"))
    print("One memory for every assistant on this computer.\n")
    by_agent = {result["agent"]: result for result in results}
    home = Path.home()
    missing = []
    restart = []
    connectable = False
    for agent in agents:
        label = agent["label"]
        if not agent["present"]:
            missing.append(label)
            continue
        result = by_agent.get(agent["id"])
        if result is not None:
            print(f"  {'✓' if result['ok'] else '✗'} {label:15s} {result['message']}")
            if result["ok"] and result["steps"]:
                restart.append(label)
        elif agent["connected"]:
            print(f"  ✓ {label:15s} connected ({agent['how']})")
        elif agent["can_connect"]:
            commands = "  then  ".join(command_line(argv, os.environ, sys.platform) for argv in plan(agent, home))
            print(f"  → {label:15s} not connected -> would run  {commands}")
            connectable = True
        else:
            print(f"  ! {label:15s} not connected. {agent['next_step']}")
    if missing:
        print(f"\n  Not on this computer: {', '.join(missing)}")
    if not applied and connectable:
        print("\nRun  memorysafe connect --apply  to connect them. Each one goes through that assistant's own installer.")
    if restart:
        # An assistant reads its plugins at start-up, so a running one has not seen the new install.
        print(f"\nRestart {' and '.join(restart)} to start using MemorySafe there.")


def _write_utf8_whatever_the_console_is() -> None:
    """Stop a legacy Windows code page from killing the command mid-report.

    Python talks to a real Windows console in UTF-16 and is fine there. Redirect the
    output and it falls back to the locale encoding instead -- cp1252 on a French or
    English Windows -- and the first character outside it raises UnicodeEncodeError.

    That is not a corner case here. `memorysafe doctor` prints a tick for every passing
    check, `uninstall` prints an arrow for every item it would remove, and `find` prints
    memory content, which can hold any character a person typed. Redirected output is
    also exactly how an assistant runs these commands: the skill tells it to run the
    doctor and read what comes back, and capturing output is a pipe.

    The doctor's own comment already records one crash of this shape, from a KeyError on
    an unknown status. Same command, same lesson: the report has to survive its own
    contents.
    """

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            # Not a reconfigurable text stream (a capture in a test, an odd platform).
            # Nothing here is worth failing a command over.
            pass


def main() -> None:
    _write_utf8_whatever_the_console_is()
    parser = argparse.ArgumentParser(
        prog="memorysafe",
        description="Read, write and inspect MemorySafe locally. Only `connect --apply` reaches the network, "
        "through each assistant's own installer.",
    )
    parser.add_argument("--install-root", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor", help="Inspect MemorySafe locally without changing it.")
    doctor.add_argument("--json", action="store_true", dest="as_json")
    bundle = subparsers.add_parser("support-bundle", help="Create a sanitized local support bundle.")
    bundle.add_argument("--output", type=Path)
    # Deliberately a command rather than an MCP tool: a tool definition costs tokens in
    # every conversation, while a command costs nothing and an assistant can still run
    # it. "Protected" has to be answerable, not merely asserted.
    explain = subparsers.add_parser(
        "explain", help="Show why a memory is held, and every decision made about it."
    )
    explain.add_argument("memory_id")
    explain.add_argument("--json", action="store_true", dest="as_json")
    # find and remember exist so that MemorySafe is reachable from any host that can run
    # a command, not only from the three that speak MCP over stdio. Some hosts launch
    # their MCP servers inside their own container, where this machine's paths do not
    # exist; that is not a bug we can fix from here, and it is not a reason to put the
    # store on a network. A command is the one interface every host already has.
    find = subparsers.add_parser("find", help="Search stored memories.")
    find.add_argument("query")
    find.add_argument("--limit", type=int, default=5)
    find.add_argument("--json", action="store_true", dest="as_json")
    remember = subparsers.add_parser("remember", help="Store one durable fact.")
    remember.add_argument("content")
    remember.add_argument("--category", choices=CATEGORIES, default="other")
    remember.add_argument(
        "--source",
        default="manual",
        help="Who is writing. Anything but 'manual' scores lower confidence, because a "
        "fact an agent volunteered is weaker evidence than one the user asked for.",
    )
    remember.add_argument("--json", action="store_true", dest="as_json")
    migrate = subparsers.add_parser(
        "migrate",
        help="Remove the manual MemorySafe registrations the plugins replace. Changes nothing without --apply.",
    )
    migrate.add_argument("--apply", action="store_true")
    migrate.add_argument("--json", action="store_true", dest="as_json")
    # A command, like explain, so it costs no tokens: an assistant asked to "connect
    # MemorySafe to my other assistants" can run it, and so can the user.
    connect = subparsers.add_parser(
        "connect",
        help="Connect every assistant on this computer to the same MemorySafe store. Changes nothing without --apply.",
    )
    connect.add_argument("--apply", action="store_true")
    connect.add_argument("--agent", choices=("claude_code", "codex", "claude_desktop"))
    connect.add_argument("--json", action="store_true", dest="as_json")
    uninstall = subparsers.add_parser(
        "uninstall",
        help="Remove MemorySafe from this computer. Changes nothing without --apply, and keeps your "
        "memories unless you add --purge.",
    )
    uninstall.add_argument("--apply", action="store_true")
    uninstall.add_argument(
        "--purge",
        action="store_true",
        help="Also delete the memories. A copy of the database is saved to your home folder first.",
    )
    uninstall.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if args.command == "doctor":
        report = run_doctor(args.install_root)
        if args.as_json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            _print_human(report)
        return

    if args.command == "migrate":
        from .migrate import apply, find_legacy

        home = Path.home()
        found = find_legacy(home, _resolve_database(args.install_root).parent.parent)
        changed = apply(home) if args.apply else []
        if args.as_json:
            print(json.dumps({"applied": args.apply, "found": found, "changed": changed}, indent=2, sort_keys=True))
        else:
            _print_migration(found, changed, args.apply)
        return

    if args.command == "uninstall":
        from . import uninstall as uninstall_module

        data_root = args.install_root or _resolve_database(args.install_root).parent.parent
        items = uninstall_module.inventory(data_root=Path(data_root))
        result = (
            uninstall_module.apply(data_root=Path(data_root), purge=args.purge)
            if args.apply
            else {"removed": [], "failed": [], "manual": [], "memories_backup": None}
        )
        if args.as_json:
            print(json.dumps({"applied": args.apply, "purge": args.purge, "items": items, **result}, indent=2, sort_keys=True))
        else:
            _print_uninstall(items, result, args.apply, args.purge)
        return

    if args.command == "connect":
        from .agents import connect as connect_agent
        from .agents import inventory

        agents = inventory()
        targets = [
            agent["id"]
            for agent in agents
            if agent["can_connect"] and not agent["connected"] and args.agent in (None, agent["id"])
        ]
        results = [connect_agent(agent_id) for agent_id in targets] if args.apply else []
        if results:
            agents = inventory()
        if args.as_json:
            print(json.dumps({"applied": args.apply, "agents": agents, "results": results}, indent=2, sort_keys=True))
        else:
            _print_connect(agents, results, args.apply)
        return

    if args.command in {"find", "remember"}:
        from .storage import MemoryStore

        store = MemoryStore(_resolve_database(args.install_root))
        if args.command == "find":
            matches = store.find(args.query, args.limit)
            if args.as_json:
                # Printed straight from storage, never through a result model: a model
                # that has not been taught a key drops it silently, and that has cost us
                # real data three times.
                print(json.dumps({"query": args.query, "count": len(matches), "memories": matches}, indent=2, sort_keys=True))
            else:
                _print_matches(args.query, matches)
            return
        written = store.remember(args.content, args.category, source=args.source)
        if args.as_json:
            print(json.dumps(written, indent=2, sort_keys=True))
        else:
            _print_written(written)
        return

    if args.command == "explain":
        from .storage import MemoryStore

        store = MemoryStore(_resolve_database(args.install_root))
        detail = store.explain(args.memory_id)
        if args.as_json:
            print(json.dumps(detail, indent=2, sort_keys=True))
        else:
            _print_explanation(detail)
        return

    target = create_support_bundle(args.install_root, args.output)
    print(target)


if __name__ == "__main__":
    main()
