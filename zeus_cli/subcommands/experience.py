"""Inspect and annotate project experience without adding a model tool."""
import argparse


def configure_parser(parser):
    parser.add_argument("--root", default=None, help="Project directory (default: current directory)")
    parser.add_argument("--json", action="store_true", help="Emit structured results")
    actions = parser.add_subparsers(dest="experience_action")
    for name, help_text in (
        ("list", "List this project's learned experiences"),
        ("status", "Show this project's learning state"),
        ("recall", "Find relevant observations and their source freshness"),
        ("show", "Inspect an experience and its evidence"),
        ("explain", "Attach a cause hypothesis, repair and limitations"),
        ("forget", "Delete an experience and its copied observations"),
    ):
        child = actions.add_parser(name, help=help_text)
        child.add_argument("--root", default=argparse.SUPPRESS)
        child.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        if name in {"show", "explain", "forget"}:
            child.add_argument("id", help="Experience ID")
        if name == "recall":
            child.add_argument("query", nargs="*", help="Error, task or repair to find")
        if name in {"list", "recall"}:
            child.add_argument("--limit", type=int, default=5)
        if name == "explain":
            child.add_argument("--cause", required=True, help="Proposed cause; always labeled as a hypothesis")
            child.add_argument("--resolution", required=True, help="What changed or should be attempted")
            child.add_argument("--avoid", default="", help="Failed approach to avoid repeating")
            child.add_argument("--conditions", default="", help="Where this explanation applies")


def build_experience_parser(subparsers):
    parser = subparsers.add_parser("experience", help="Learn from verified failures and recoveries")
    configure_parser(parser)
    parser.set_defaults(func=_command)


def _command(args):
    from zeus_cli.experience_command import run_experience_command

    raise SystemExit(run_experience_command(args))
