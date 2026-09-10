"""Identity and distribution contract for the independent ZeusAgent source build."""

PRODUCT_NAME = "ZeusAgent"
FORK_REVISION = "zeus.1"
UPSTREAM_PROJECT = "Hermes Agent"
UPSTREAM_COMMIT = "2237be355906fbe6065ce1815711eee52b2d646e"
UPSTREAM_URL = "https://github.com/NousResearch/hermes-agent"
REMOTE_RELEASES_AVAILABLE = False


def source_update_message() -> str:
    return (
        "ZeusAgent is an independent source build. No ZeusAgent release channel has been configured. "
        "Install a reviewed ZeusAgent source package with: python scripts/setup_zeus.py. "
        "Automatic upstream updates would replace this fork with Hermes Agent."
    )


def handle_source_update(args) -> int:
    """Allow read-only planning; refuse a code swap before any external fetch or state change."""
    if getattr(args, "plan", False):
        from zeus_cli.update_inventory import collect_runtime_inventory, print_update_plan
        print_update_plan(collect_runtime_inventory())
        print(source_update_message())
        return 0
    print(source_update_message())
    return 0 if getattr(args, "check", False) else 2
