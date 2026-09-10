"""Explicit, profile-scoped Hermes preview and import; never imports on startup."""
from .method_ctx import HandlerRegistry, bind_module

_registry = HandlerRegistry()
method = _registry.method
_profile_scoped = _registry.profile_scoped


@method("hermes.migration.scan")
@_profile_scoped
def _(rid, params: dict) -> dict:
    from zeus_cli.hermes_import import scan_hermes_import
    try:
        return _ok(rid, {"preview": scan_hermes_import(params.get("source"))})
    except ValueError as exc:
        return _err(rid, 4004, str(exc))
    except Exception:
        logger.warning("Hermes migration preview failed")
        return _err(rid, 5031, "Could not inspect Hermes data. Check the source path and file permissions.")


@method("hermes.migration.import")
@_profile_scoped
def _(rid, params: dict) -> dict:
    from zeus_cli.hermes_import import import_hermes
    try:
        result = import_hermes(source=params.get("source"), scan_id=params.get("scan_id"),
                               categories=params.get("categories"))
        return _ok(rid, {"result": result})
    except ValueError as exc:
        return _err(rid, 4004, str(exc))
    except Exception:
        logger.warning("Hermes migration import failed")
        return _err(rid, 5031, "Hermes import could not finish. Existing Zeus files are preserved; inspect the import backups before retrying.")


def register(server):
    bind_module(globals(), server, skip=("_",))
