"""Timezone-aware clock for ZeusAgent.

``now()`` returns a tz-aware datetime in the user's configured IANA timezone. Resolution order:
``ZEUS_TIMEZONE`` env var, then ``timezone`` in ``~/.zeus/config.yaml``, else server-local
time. Invalid timezone values log a warning and fall back — never crash.
"""

import logging
import os
import re
import threading
from datetime import datetime
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from zeus_constants import get_config_path
from agent.message_sanitization import _sanitize_surrogates

logger = logging.getLogger(__name__)

# Cache keyed by timezone *source* identity. This process can multiplex profiles by switching
# ZEUS_HOME, so one unkeyed global would leak the first profile's timezone into later
# profile-scoped work (e.g. the desktop multiplex cron ticker persisting another profile's
# ``next_run_at``). Entries are published atomically under ``_cache_lock`` as one
# ``identity -> (name, ZoneInfo | None)`` value, so racing resolvers can never publish a mixed
# identity/value pair. Call reset_cache() after in-place config changes.
_cache_lock = threading.Lock()
_tz_cache: Dict[Tuple[str, str], Tuple[str, Optional[ZoneInfo]]] = {}


_WEEKDAY_NAMES = (
    ("Monday", "Mon"),
    ("Tuesday", "Tue"),
    ("Wednesday", "Wed"),
    ("Thursday", "Thu"),
    ("Friday", "Fri"),
    ("Saturday", "Sat"),
    ("Sunday", "Sun"),
)
_MONTH_NAMES = (
    ("January", "Jan"),
    ("February", "Feb"),
    ("March", "Mar"),
    ("April", "Apr"),
    ("May", "May"),
    ("June", "Jun"),
    ("July", "Jul"),
    ("August", "Aug"),
    ("September", "Sep"),
    ("October", "Oct"),
    ("November", "Nov"),
    ("December", "Dec"),
)
_LOCALE_DIRECTIVE_RE = re.compile(r"(?<!%)%(?:[EO])?([aAbBchpXxZz])")


def _numeric_utc_offset(value: datetime) -> str:
    offset = value.utcoffset()
    if offset is None:
        return ""
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    suffix = f"{seconds:02d}" if seconds else ""
    return f"{sign}{hours:02d}{minutes:02d}{suffix}"


def _portable_directive(value: datetime, directive: str) -> str:
    weekday_long, weekday_short = _WEEKDAY_NAMES[value.weekday()]
    month_long, month_short = _MONTH_NAMES[value.month - 1]
    hour = getattr(value, "hour", 0)
    minute = getattr(value, "minute", 0)
    second = getattr(value, "second", 0)
    replacements = {
        "a": weekday_short,
        "A": weekday_long,
        "b": month_short,
        "h": month_short,
        "B": month_long,
        "c": (
            f"{weekday_short} {month_short} {value.day:02d} "
            f"{hour:02d}:{minute:02d}:{second:02d} {value.year:04d}"
        ),
        "p": "AM" if hour < 12 else "PM",
        "X": f"{hour:02d}:{minute:02d}:{second:02d}",
        "x": f"{value.year:04d}-{value.month:02d}-{value.day:02d}",
        "z": _numeric_utc_offset(value),
    }
    if directive == "Z":
        try:
            return value.tzname() or ""
        except UnicodeEncodeError:
            return ""
    return replacements[directive]


def safe_strftime(value: datetime, fmt: str) -> str:
    """Format a datetime without leaking invalid locale surrogates.

    Some Windows locale/code-page combinations raise ``UnicodeEncodeError``
    inside ``strftime`` before Python receives a string. Retry with portable
    replacements for locale-sensitive directives, then scrub any surrogate
    code points returned by the platform or ``tzname()``.
    """
    try:
        rendered = value.strftime(fmt)
    except UnicodeEncodeError:
        replacements: Dict[str, str] = {}

        def replace_directive(match: re.Match[str]) -> str:
            token = f"__ZEUS_TIME_{len(replacements)}__"
            replacements[token] = _sanitize_surrogates(
                _portable_directive(value, match.group(1))
            )
            return token

        rendered = value.strftime(_LOCALE_DIRECTIVE_RE.sub(replace_directive, fmt))
        for token, replacement in replacements.items():
            rendered = rendered.replace(token, replacement)
    return _sanitize_surrogates(rendered)



def _timezone_cache_identity() -> Tuple[str, str]:
    tz_env = os.getenv("ZEUS_TIMEZONE", "").strip()
    return ("environment", tz_env) if tz_env else ("config", str(get_config_path()))


def _resolve_timezone_name() -> str:
    """Read the configured IANA timezone string (or ``""``). Does file I/O — callers cache."""
    tz_env = os.getenv("ZEUS_TIMEZONE", "").strip()
    if tz_env:
        return tz_env
    try:
        # Prefer the shared cached raw-config reader (mtime-keyed + libyaml): a direct safe_load of
        # a large config.yaml costs ~100 ms and this ran inside the FIRST system prompt build.
        try:
            from zeus_cli.config import read_raw_config
            cfg = read_raw_config() or {}
        except Exception:
            import yaml
            config_path = get_config_path()
            cfg = (yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}) if config_path.exists() else {}
        if cfg:
            # Managed scope: an administrator can pin ``timezone`` too (fail-open overlay).
            try:
                from zeus_cli import managed_scope
                cfg = managed_scope.apply_managed_overlay(cfg)
            except Exception:
                pass
            tz_cfg = cfg.get("timezone", "")
            if isinstance(tz_cfg, str) and tz_cfg.strip():
                return tz_cfg.strip()
    except Exception:
        pass
    return ""


def get_timezone() -> Optional[ZoneInfo]:
    """Return the active profile's configured ZoneInfo, or None (server-local)."""
    cache_identity = _timezone_cache_identity()
    with _cache_lock:
        entry = _tz_cache.get(cache_identity)
        if entry is not None:
            return entry[1]
    # Resolve outside the lock (config file I/O); first writer wins so concurrent resolvers of the
    # same identity converge on one ZoneInfo object.
    name = _resolve_timezone_name()
    tz = None
    if name:
        try:
            tz = ZoneInfo(name)
        except Exception as exc:
            logger.warning("Invalid timezone '%s': %s. Falling back to server local time.", name, exc)
    with _cache_lock:
        return _tz_cache.setdefault(cache_identity, (name, tz))[1]


def reset_cache() -> None:
    """Clear the cached timezone so the next call re-resolves it (after config/env changes)."""
    with _cache_lock:
        _tz_cache.clear()


def now() -> datetime:
    """Current time as a tz-aware datetime: configured zone, else server-local."""
    tz = get_timezone()
    return datetime.now(tz) if tz is not None else datetime.now().astimezone()
