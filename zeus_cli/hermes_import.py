"""Preview-bound, additive migration from a Hermes home into the active Zeus profile.

The source is never opened for writing or passed to SQLite. Compatible files are
staged and verified before publication; existing settings win and collisions are
namespaced. Credentials and runtime state deliberately have no import route.
"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid

import yaml

from zeus_constants import get_zeus_home
from zeus_cli.agent_import import load_yaml_file
from zeus_cli.hermes_import_files import CATEGORIES, compatible_settings, digest, fill_missing, inventory, is_link
from zeus_cli.hermes_import_sessions import backup_database, chat_count, merge_chats


def _paths(source):
    if source is not None and not isinstance(source, str):
        raise ValueError("The Hermes source must be a directory path on the gateway computer.")
    raw = Path(source.strip() if source and source.strip() else "~/.hermes").expanduser()
    target_raw = get_zeus_home()
    if is_link(raw) or is_link(target_raw):
        raise ValueError("Choose a directory rather than a symbolic link or junction.")
    source, target = raw.resolve(), target_raw.resolve()
    if not source.is_dir():
        raise ValueError("The Hermes directory was not found on the gateway computer.")
    if source == target or source.is_relative_to(target) or target.is_relative_to(source):
        raise ValueError("Hermes and Zeus directories must not overlap.")
    return source, target


def _safe_path(root, relative):
    path = root / relative
    if not path.resolve().is_relative_to(root):
        raise ValueError("An import path leaves the selected profile.")
    candidate = path
    while candidate != root:
        if is_link(candidate):
            raise ValueError("An import destination is a symbolic link or junction.")
        candidate = candidate.parent
    return path


def _settings(path):
    try:
        return load_yaml_file(path)
    except Exception as exc:
        raise ValueError("Existing Zeus settings are unreadable or invalid; repair them before importing.") from exc


def _source_key(source):
    return hashlib.sha256(os.path.normcase(str(source)).encode()).hexdigest()[:16]


def _profile_name(name, key):
    return "hermes-" + key[:8] + "-" + re.sub(r"[^a-z0-9_-]", "-", name.lower())[:40]


def _publication_lock(path):
    """Reuse established writers: memory locks cross processes; config locks only this process.

    These locks cover file publication/rollback only, never a conversation database transaction.
    External configuration editors do not participate in Zeus's in-process config lock.
    """
    if path.name == "config.yaml":
        from zeus_cli.config import _CONFIG_LOCK
        return _CONFIG_LOCK
    if path.parent.name == "memories" and path.name in {"MEMORY.md", "USER.md"}:
        from tools.memory_tool_store import MemoryStore
        return MemoryStore._file_lock(path)
    return nullcontext()


def _preview_counts(source, target, items):
    counts = {key: 0 for key in CATEGORIES}
    conflicts = dict(counts)
    profiles = set()
    skills = set()
    for item in items:
        category, relative = item["category"], Path(item["path"])
        if category == "chats":
            counts[category] = chat_count(source / relative)
        elif category == "profiles":
            profiles.add(relative.parts[1])
        elif category == "skills":
            skills.add(relative.parts[1] if len(relative.parts) > 1 else relative.name)
        elif category == "settings":
            incoming = compatible_settings(source / relative)
            counts[category] = len(incoming)
            try:
                _, _, conflicts[category] = fill_missing(_settings(target / relative), incoming)
            except ValueError:
                conflicts[category] = 1
        else:
            counts[category] += 1
            conflicts[category] += int((target / relative).exists())
    counts["skills"], counts["profiles"] = len(skills), len(profiles)
    conflicts["skills"] = sum((target / "skills" / name).exists() for name in skills)
    conflicts["profiles"] = sum((target / "profiles" / _profile_name(name, _source_key(source))).exists()
                                for name in profiles)
    return [{"id": key, "label": label, "count": counts[key], "conflicts": conflicts[key]}
            for key, label in CATEGORIES.items()]


def scan_hermes_import(source: str | None = None) -> dict:
    source, target = _paths(source)
    items, warnings = inventory(source)
    categories = _preview_counts(source, target, items)
    if target.parent.name == "profiles":
        categories = [item if item["id"] != "profiles" else {**item, "count": 0} for item in categories]
        warnings.append("Named profiles can be imported from the default Zeus profile only; this import stays inside the selected profile.")
    scan_id = str(uuid.uuid4())
    record = {"scan_id": scan_id, "source": str(source), "target": str(target), "items": items,
              "created_at": datetime.now(timezone.utc).isoformat()}
    path = _safe_path(target, "imports/hermes/scans/" + scan_id + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    return {key: record[key] for key in ("scan_id", "source", "target")} | {
        "categories": categories, "warnings": warnings}


def _validated_scan(source, target, scan_id):
    if not isinstance(scan_id, str) or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", scan_id):
        raise ValueError("Scan the Hermes directory before importing.")
    path = _safe_path(target, "imports/hermes/scans/" + scan_id + ".json")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["source"] != str(source) or record["target"] != str(target):
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("This preview does not belong to the selected source and Zeus profile; scan again.") from exc
    current, warnings = inventory(source)
    if record.get("items") != current:
        raise ValueError("Hermes data changed after the preview; scan again before importing.")
    return current, warnings


class _ImportPlan:
    def __init__(self, target, staging, backup):
        self.target, self.staging, self.backup = target, staging, backup
        self.files = []
        self.published = []
        self.created_directories = []
        self.conflicts = 0

    def content(self, relative):
        for planned, staged, _ in self.files:
            if planned == relative:
                return staged.read_bytes()
        path = _safe_path(self.target, relative)
        return path.read_bytes() if path.is_file() else b""

    def add(self, relative, content, *, replace=False):
        new_hash = digest(content) if isinstance(content, Path) else hashlib.sha256(content).hexdigest()
        for planned, staged, _ in self.files:
            if planned == relative:
                if digest(staged) == new_hash:
                    return False
                if not replace:
                    raise ValueError("Two Hermes files map to the same destination; import one source profile at a time.")
                shutil.copyfile(content, staged) if isinstance(content, Path) else staged.write_bytes(content)
                return True
        destination = _safe_path(self.target, relative)
        old_hash = digest(destination) if destination.is_file() else None
        if destination.exists() and not destination.is_file():
            raise ValueError("An import file conflicts with an existing directory.")
        if old_hash == new_hash:
            return False
        if old_hash and not replace:
            raise ValueError("An import destination changed or already exists; scan again.")
        staged = self.staging / "files" / str(len(self.files))
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(content, staged) if isinstance(content, Path) else staged.write_bytes(content)
        self.files.append((relative, staged, old_hash))
        return True

    def publish(self):
        # Validate the entire destination plan before the first content write.
        for relative, _, expected in self.files:
            destination = _safe_path(self.target, relative)
            actual = digest(destination) if destination.is_file() else None
            if actual != expected or (destination.exists() and not destination.is_file()):
                raise ValueError("Zeus data changed during the import; scan again.")
        for relative, staged, expected in self.files:
            written = digest(staged)
            destination = _safe_path(self.target, relative)
            parent = destination.parent
            missing = []
            while parent != self.target and not parent.exists():
                missing.append(parent)
                parent = parent.parent
            destination.parent.mkdir(parents=True, exist_ok=True)
            self.created_directories.extend(reversed(missing))
            with _publication_lock(destination):
                actual = digest(destination) if destination.is_file() else None
                if actual != expected or (destination.exists() and not destination.is_file()):
                    raise ValueError("Zeus data changed during the import; scan again.")
                if expected is not None:
                    backup = self.backup / relative
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(destination, backup)
                    if digest(destination) != expected:
                        raise ValueError("Zeus data changed during the import; scan again.")
                    os.replace(staged, destination)
                else:
                    # Same-filesystem publication fails atomically if another writer won.
                    os.link(staged, destination)
            self.published.append((relative, expected, written))

    def rollback(self):
        for relative, expected, written in reversed(self.published):
            destination = _safe_path(self.target, relative)
            with _publication_lock(destination):
                if not destination.is_file() or digest(destination) != written:
                    continue  # Never erase a user's concurrent edit to an imported file.
                if expected is None:
                    destination.unlink()
                else:
                    os.replace(self.backup / relative, destination)
        for path in reversed(self.created_directories):
            try:
                path.rmdir()
            except OSError:
                pass  # It contains a user's concurrent data, or was already removed.


def _file_destination(item, source, target, key, conflicted_skills):
    relative = Path(item["path"])
    if item["category"] == "skills" and len(relative.parts) > 1 and relative.parts[1] in conflicted_skills:
        return Path("skills") / ("hermes-" + key[:8]) / Path(*relative.parts[1:])
    if item["category"] == "memories" and relative.parts[0] == "memory":
        relative = Path("memories") / Path(*relative.parts[1:])
    destination = _safe_path(target, relative)
    if destination.exists() and digest(destination) != item["sha256"]:
        return relative.parent / (relative.stem + ".hermes-" + key[:8] + relative.suffix)
    return relative


def _prepare_files(source, target, items, selected, key, plan, imported, skipped):
    groups = {}
    for item in items:
        if item["category"] == "skills":
            groups.setdefault(Path(item["path"]).parts[1], []).append(item)
    conflicts = set()
    for group, files in groups.items():
        if not _safe_path(target, Path("skills") / group).exists():
            continue
        matches = [(_safe_path(target, item["path"]).is_file() and
                    digest(_safe_path(target, item["path"])) == item["sha256"]) for item in files]
        differs = any(_safe_path(target, item["path"]).exists() and not match
                      for item, match in zip(files, matches))
        if differs or not any(matches):
            conflicts.add(group)
    counted_skills = {}
    for item in items:
        category, relative = item["category"], Path(item["path"])
        if category not in selected or category in {"chats", "profiles"}:
            continue
        path = _safe_path(source, relative)
        if category == "settings":
            merged, added, collisions = fill_missing(_settings(_safe_path(target, relative)), compatible_settings(path))
            plan.conflicts += collisions
            if added:
                plan.add(relative, yaml.safe_dump(merged, allow_unicode=True, sort_keys=False).encode(), replace=True)
            imported[category] += added
            skipped[category] += collisions
            continue
        # Active memories append one stable block; existing notes remain byte-for-byte intact.
        if category == "memories" and relative.name in {"MEMORY.md", "USER.md"}:
            relative = Path("memories") / relative.name
            current = plan.content(relative)
            incoming = path.read_bytes()
            marker = ("<!-- hermes-import:" + key + ":" + item["sha256"] + " -->").encode()
            if marker in current or current == incoming:
                skipped[category] += 1
            else:
                content = current + (b"\n\n" if current else b"") + marker + b"\n" + incoming
                plan.add(relative, content, replace=True)
                imported[category] += 1
                plan.conflicts += bool(current)
            continue
        destination = _file_destination(item, source, target, key, conflicts)
        collision = destination != relative
        if category == "skills":
            group = relative.parts[1]
            added = plan.add(destination, path)
            if group not in counted_skills:
                plan.conflicts += int(collision)
            counted_skills[group] = counted_skills.get(group, False) or added
        else:
            added = plan.add(destination, path)
            imported[category] += int(added)
            skipped[category] += int(not added)
            plan.conflicts += int(collision)
    imported["skills"] += sum(counted_skills.values())
    skipped["skills"] += sum(not added for added in counted_skills.values())


def _prepare_profiles(source, target, items, key, plan, imported, skipped):
    if target.parent.name == "profiles":
        raise ValueError("Switch to the default Zeus profile to import named Hermes profiles.")
    profiles = sorted({Path(item["path"]).parts[1] for item in items if item["category"] == "profiles"})
    for name in profiles:
        renamed = _profile_name(name, key)
        if _safe_path(target, Path("profiles") / renamed).exists():
            skipped["profiles"] += 1
            plan.conflicts += 1
            continue
        for item in items:
            relative = Path(item["path"])
            if item["category"] != "profiles" or relative.parts[1] != name:
                continue
            suffix = Path(*relative.parts[2:])
            destination = Path("profiles") / renamed / suffix
            path = _safe_path(source, relative)
            if suffix == Path("config.yaml"):
                data = yaml.safe_dump(compatible_settings(path), allow_unicode=True).encode()
            elif suffix == Path("state.db"):
                snapshot = plan.staging / renamed / "source.db"
                backup_database(path, snapshot)
                database = plan.staging / renamed / "state.db"
                merge_chats(snapshot, database, key + ":" + name, profile=renamed)
                # The connection is closed; a SQLite backup folds any WAL into one file.
                packed = plan.staging / renamed / "published.db"
                backup_database(database, packed)
                data = packed
            else:
                data = path
            plan.add(destination, data)
        imported["profiles"] += 1


def import_hermes(*, source: str | None, scan_id: str, categories: list[str]) -> dict:
    if not isinstance(categories, list) or not categories or any(not isinstance(key, str) or key not in CATEGORIES for key in categories):
        raise ValueError("Select at least one supported category from the preview.")
    source, target = _paths(source)
    items, warnings = _validated_scan(source, target, scan_id)
    from zeus_cli.backup import _backup_operation_lock, BackupInProgressError
    try:
        with _backup_operation_lock(target):
            return _perform_import(source, target, scan_id, categories, items, warnings)
    except BackupInProgressError as exc:
        raise ValueError("Another backup or import is running; retry when it finishes.") from exc


def _perform_import(source, target, scan_id, categories, items, warnings):
    binding = {"source": str(source), "target": str(target), "scan_id": scan_id,
               "categories": sorted(set(categories))}
    operation = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    receipt = _safe_path(target, "imports/hermes/receipts/" + operation + ".json")
    # The caller validated source freshness and owns the import lock. An
    # ambiguous client timeout can repeat this exact operation without another
    # merge, backup, or file publication; a different selection gets its own key.
    if receipt.is_file():
        try:
            saved = json.loads(receipt.read_text(encoding="utf-8"))
            if saved.get("binding") != binding or not isinstance(saved.get("result"), dict):
                raise ValueError
            return saved["result"]
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError("The saved import receipt is unreadable; inspect import history before retrying.") from exc
    key, import_id = _source_key(source), str(uuid.uuid4())
    selected = set(categories)
    staging = _safe_path(target, "imports/hermes/staging/" + import_id)
    backup = _safe_path(target, "imports/hermes/backups/" + import_id)
    staging.mkdir(parents=True)
    imported = {category: 0 for category in CATEGORIES}
    skipped = dict(imported)
    plan = _ImportPlan(target, staging, backup)
    try:
        _prepare_files(source, target, items, selected, key, plan, imported, skipped)
        if "profiles" in selected:
            _prepare_profiles(source, target, items, key, plan, imported, skipped)
        source_db = next((item for item in items if item["category"] == "chats"), None)
        if "chats" in selected and source_db:
            snapshot = staging / "conversations.db"
            backup_database(_safe_path(source, source_db["path"]), snapshot)
            if _safe_path(target, "state.db").is_file():
                backup_database(target / "state.db", backup / "state.db")
        _validated_scan(source, target, scan_id)
        plan.publish()
        if "chats" in selected and source_db:
            profile = target.name if target.parent.name == "profiles" else "default"
            imported["chats"], skipped["chats"] = merge_chats(snapshot, target / "state.db", key, profile=profile)
    except BaseException:
        plan.rollback()
        raise
    finally:
        # Only remove the newly-created private staging directory under this profile.
        if staging.resolve().is_relative_to(target / "imports/hermes/staging"):
            shutil.rmtree(staging)
    result = {"source": str(source), "target": str(target), "imported": imported, "skipped": skipped,
              "conflicts": plan.conflicts, "backup_path": str(backup) if backup.exists() else None,
              "warnings": warnings, "restart_required": any(imported.values())}
    try:
        from utils import atomic_write_text
        receipt.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(receipt, json.dumps({"binding": binding, "result": result}))
    except OSError:
        result["warnings"].append("The import completed, but its receipt could not be saved.")
    return result
