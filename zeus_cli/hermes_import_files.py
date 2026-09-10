"""Compatible settings and bounded, non-following file inventory for Hermes imports."""

from __future__ import annotations

import hashlib
from pathlib import Path
import os
from urllib.parse import urlsplit, urlunsplit

from zeus_cli.agent_import import is_secret_key, load_yaml_file


CATEGORIES = {"chats": "Conversations", "settings": "Compatible settings", "memories": "Memories",
              "skills": "Skills", "prompts": "Custom prompts", "profiles": "Named profiles"}
_SETTINGS = {"model", "temperature", "max_tokens", "reasoning_effort", "agent", "display", "terminal",
             "compression", "memory", "skills", "providers", "auxiliary", "delegation", "toolsets"}
_SKIP_NAMES = {".git", "node_modules", "__pycache__", ".venv", "venv", ".env", "auth.json",
               "credentials.json", "token.json", "tokens.json", "gateway_state.json", "processes.json"}
_MAX_FILE = 64 * 1024 * 1024
_MAX_TOTAL = 1024 * 1024 * 1024


def is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def compatible_settings(path: Path) -> dict:
    try:
        data = load_yaml_file(path)
    except Exception as exc:
        raise ValueError("A settings file is unreadable or invalid YAML; repair it before importing.") from exc

    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items() if isinstance(key, str) and
                    not is_secret_key(key) and key.lower() not in {"env", "environment", "headers", "enabled"}}
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, str) and "://" in value:
            try:
                parsed = urlsplit(value)
                if parsed.username or parsed.password or parsed.query:
                    return urlunsplit((parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", ""))
            except ValueError:
                return ""
        return value
    return {key: clean(value) for key, value in data.items() if key in _SETTINGS}


def fill_missing(target: dict, source: dict) -> tuple[dict, int, int]:
    merged, added, conflicts = dict(target), 0, 0
    for key, value in source.items():
        if key not in merged:
            merged[key], added = value, added + 1
        elif isinstance(value, dict) and isinstance(merged[key], dict):
            merged[key], child_added, child_conflicts = fill_missing(merged[key], value)
            added += child_added
            conflicts += child_conflicts
        elif merged[key] != value:
            conflicts += 1
    return merged, added, conflicts


def inventory(source: Path) -> tuple[list[dict], list[str]]:
    items, warnings, total = [], [], 0
    candidates = [(source / "config.yaml", "settings"), (source / "state.db", "chats")]
    candidates += [(source / name, "prompts") for name in ("SOUL.md", "AGENTS.md", "USER.md")]
    for directory, category in (("memories", "memories"), ("memory", "memories"), ("skills", "skills"),
                                ("prompts", "prompts"), ("profiles", "profiles")):
        base = source / directory
        if is_link(base):
            warnings.append("Linked files or directories were excluded from the import.")
            continue
        if not base.is_dir():
            continue
        for parent, dirs, files in os.walk(base, followlinks=False):
            parent = Path(parent)
            if any(is_link(parent / name) for name in dirs + files):
                warnings.append("Linked files or directories were excluded from the import.")
            dirs[:] = [name for name in dirs if name.lower() not in _SKIP_NAMES and not is_link(parent / name)]
            for name in files:
                lower = name.lower()
                if lower in _SKIP_NAMES or lower.startswith(".env.") or lower.endswith(("-wal", "-shm", ".lock", ".log", ".pyc", ".pem", ".key")):
                    continue
                if category == "profiles":
                    relative = (parent / name).relative_to(base).parts
                    if len(relative) < 2 or relative[1] not in {"config.yaml", "state.db", "memories", "memory", "skills", "prompts", "SOUL.md", "AGENTS.md", "USER.md"}:
                        continue
                candidates.append((parent / name, category))
    for path, category in candidates:
        if is_link(path):
            warnings.append("Linked files or directories were excluded from the import.")
        if not path.is_file() or is_link(path):
            continue
        size = path.stat().st_size
        limit = _MAX_TOTAL if path.name == "state.db" else _MAX_FILE
        if size > limit or total + size > _MAX_TOTAL or len(items) >= 20_000:
            raise ValueError("Hermes data exceeds the supported import size; select a smaller profile.")
        total += size
        items.append({"path": path.relative_to(source).as_posix(), "category": category,
                      "size": size, "sha256": digest(path)})
        if path.name == "state.db" and Path(str(path) + "-wal").is_file():
            wal = Path(str(path) + "-wal")
            if is_link(wal) or wal.stat().st_size + total > _MAX_TOTAL:
                raise ValueError("The database journal is linked or exceeds the supported import size.")
            total += wal.stat().st_size
            items[-1]["wal_sha256"] = digest(wal)
    if not items:
        raise ValueError("No compatible Hermes data was found at this location.")
    warnings.append("API keys, login tokens, scheduled jobs, plugins, project pins, live processes and gateway connections are not imported. Reconnect accounts in ZeusAgent.")
    if any(item["path"].endswith("state.db") for item in items):
        warnings.append("Conversation text and tool history are copied. Attachments and external file references are not transferred; images or downloads may require their original files.")
    return sorted(items, key=lambda item: item["path"]), sorted(set(warnings))
