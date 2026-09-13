"""Shared experience command semantics for terminals and read-only chat controls."""
import argparse
import json
from pathlib import Path
import shlex
import sqlite3


USAGE = "Usage: /experience [list | status | recall <words> | show <id>]"


def _list(store, args, root):
    return store.recall(root=root, query=" ".join(getattr(args, "query", []) or []),
                        limit=getattr(args, "limit", 5))


def _show(store, args, root):
    return store.show(args.id, root=root)


def _explain(store, args, root):
    return store.explain(args.id, root=root, cause=args.cause, resolution=args.resolution,
                         avoid=args.avoid, conditions=args.conditions)


def _forget(store, args, root):
    return {"id": args.id, "forgotten": store.forget(args.id, root=root)}


_ACTIONS = {"list": _list, "status": _list, "recall": _list, "show": _show,
            "explain": _explain, "forget": _forget}


def execute_experience_command(args):
    from agent.experience_store import ExperienceStore

    root = Path(getattr(args, "root", None) or ".").expanduser().resolve()
    action = getattr(args, "experience_action", None) or "list"
    if action not in _ACTIONS:
        raise ValueError("Unknown experience action.")
    return _ACTIONS[action](ExperienceStore(), args, root)


def format_experiences(report: dict) -> str:
    if report.get("forgotten"):
        return f"Forgot experience {report['id']}. Original verification history is retained."
    if "error" in report:
        return report["error"]
    items = report.get("experiences", [report] if "id" in report else [])
    if not items:
        return "No matching experience in this project and profile. Failed checks are learned automatically."
    lines = ["Project experience — observed outcomes; explanations are hypotheses."]
    for item in items:
        lines.append(f"\n{item['id']} · {item['state']} · source {item.get('freshness', 'not checked')}")
        for key, label in (("symptom", "Observed failure"), ("cause", "Cause hypothesis"),
                           ("resolution", "Repair"), ("avoid", "Avoid"), ("conditions", "Applies when")):
            if item.get(key):
                lines.append(f"{label}: {item[key][:500]}")
        for receipt in item.get("observations", [])[-6:]:
            lines.append(f"  Check #{receipt['event_id']} · {receipt['status']} · {receipt['scope']} · "
                         f"{receipt['fingerprint'][:12] or 'source unknown'}")
    return "\n".join(lines)


def run_experience_command(args) -> int:
    try:
        report, code = execute_experience_command(args), 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        from agent.experience_store import _text
        report, code = {"error": _text(str(exc))}, 2
    print(json.dumps(report, ensure_ascii=False) if getattr(args, "json", False) else format_experiences(report))
    return code


class _ChatParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(USAGE)

    def exit(self, status=0, message=None):
        raise ValueError(USAGE)


def dispatch_experience_command(text: str, *, root) -> str:
    """Chat inspection cannot execute checks, change roots, write notes or erase history."""
    from zeus_cli.subcommands.experience import configure_parser

    try:
        args = shlex.split(text)
        if args and args[0] not in {"list", "status", "recall", "show"}:
            return USAGE
        if any(arg.startswith("--") for arg in args):
            return USAGE
        parser = _ChatParser(prog="/experience", add_help=False)
        configure_parser(parser)
        parsed = parser.parse_args(args)
        parsed.root = str(root)
        return format_experiences(execute_experience_command(parsed))[:3600]
    except (ValueError, OSError, sqlite3.Error):
        return "Experience could not be inspected. " + USAGE
