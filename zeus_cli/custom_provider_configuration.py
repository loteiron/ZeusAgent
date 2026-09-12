"""Non-interactive custom endpoint setup, shared with messaging control surfaces."""
from __future__ import annotations

import hashlib
import uuid
from urllib.parse import urlsplit

from zeus_constants import get_zeus_home


def configure_custom_provider(base_url: str, model: str, api_key: str,
                              api_mode: str = "chat_completions") -> dict:
    """Save a custom route with a private key reference; never return the credential.

    A fresh credential slot is published before the config transaction. A failed
    config write therefore cannot rotate the key used by the previous route.
    """
    from zeus_cli import config as config_io

    if not isinstance(base_url, str) or any(c.isspace() or ord(c) < 32 for c in base_url):
        raise ValueError("Enter a valid HTTP(S) API base URL without whitespace.")
    try:
        url = urlsplit(base_url)
        port = url.port
    except ValueError as exc:
        raise ValueError("Enter a valid HTTP(S) API base URL.") from exc
    if (url.scheme not in {"http", "https"} or not url.hostname or url.username is not None
            or url.password is not None or url.query or url.fragment or (port is not None and port == 0)):
        raise ValueError("Use an HTTP(S) API base URL without credentials, query parameters or fragments.")
    if not isinstance(model, str) or not model or len(model) > 512 or any(c.isspace() or ord(c) < 32 for c in model):
        raise ValueError("Enter one model ID without whitespace.")
    if api_mode not in {"chat_completions", "responses"}:
        raise ValueError("API mode must be chat_completions or responses.")
    if not isinstance(api_key, str) or not api_key or len(api_key) > 2048 or any(c.isspace() or not 32 <= ord(c) < 127 for c in api_key):
        raise ValueError("Enter an API key without whitespace, or none for an endpoint without authentication.")
    if config_io.is_managed():
        raise ValueError("This profile is managed; change its provider through the administrator.")

    from zeus_cli.config_providers import _canonical_api_mode
    api_mode = _canonical_api_mode(api_mode)
    base_url = base_url.rstrip("/")
    secret = "no-key-required" if api_key == "none" else api_key
    identity = hashlib.sha256(base_url.encode()).hexdigest()[:16] + "_" + uuid.uuid4().hex[:12]
    key_env = config_io.custom_endpoint_key_env(identity)
    with config_io._CONFIG_LOCK:
        cfg = config_io.read_user_config_raw(get_zeus_home() / "config.yaml")
        current = cfg.get("model")
        current = dict(current) if isinstance(current, dict) else {}
        config_io.clear_model_endpoint_credentials(current, clear_base_url=True)
        # A context pin and request headers belong to the old endpoint/model.
        for field in ("context_length", "request_headers", "extra_headers", "api_key_env"):
            current.pop(field, None)
        route = {"provider": "custom", "default": model, "base_url": base_url,
                 "api_mode": api_mode, "key_env": key_env}
        current.update(route)
        # The literal custom route reads model.api_key; keep a reference rather
        # than an inline key. Named endpoint resolution also understands key_env.
        current["api_key"] = "${" + key_env + "}"
        cfg["model"] = current
        entries = cfg.get("custom_providers")
        entries = list(entries) if isinstance(entries, list) else []
        entries = [entry for entry in entries if not isinstance(entry, dict)
                   or str(entry.get("base_url", "")).rstrip("/") != base_url]
        entries.append({"name": "Telegram custom " + url.netloc, "base_url": base_url,
                        "model": model, "api_mode": api_mode, "key_env": key_env})
        cfg["custom_providers"] = entries
        config_io.save_env_value(key_env, secret)
        if config_io.get_env_value(key_env) != secret:
            raise ValueError("The profile did not allow saving this credential; its route was preserved.")
        config_io.save_config(cfg)
    return route
