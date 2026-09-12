"""URLs for the API and webhook listeners displayed by gateway status."""

from typing import Any

_WILDCARD_HOSTS = {"", "0.0.0.0", "::", "[::]", "*"}


def listener_base_url(host: Any, port: Any) -> str:
    """``http://host:port`` clients use to reach a listener bound on ``host`` (wildcards → loopback)."""
    host = "127.0.0.1" if host is None or str(host).strip() in _WILDCARD_HOSTS else str(host)
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port or 0}"

