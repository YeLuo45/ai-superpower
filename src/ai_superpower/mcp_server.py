"""ai-superpower MCP server — exposes proposal/project CRUD + audit + sync as MCP tools.

Transports:
- stdio: `aisp mcp --transport=stdio`
- Streamable HTTP: `aisp mcp --transport=http --port 8000` (mount path /mcp)
- FastAPI mount: `app.mount("/mcp", mcp.streamable_http_app())`

Auth:
- HTTP transport: X-API-Key header
- stdio: AI_SUPERPOWER_API_KEY env var OR _api_key argument
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from .config import APIConfig, CONFIG_PATH
from .storage import CSVStorage

# Single shared FastMCP instance — all 19 tools registered as decorators below.
# streamable_http_path="/" lets the FastAPI mount at /mcp result in a clean
# /mcp endpoint (instead of the default /mcp/mcp from path concatenation).
mcp = FastMCP("ai-superpower", instructions="Proposal/project management + audit + sync", streamable_http_path="/")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_api_key() -> str:
    """Read configured API key (env var > default config)."""
    return os.environ.get("AI_SUPERPOWER_API_KEY", "")


def _check_auth(api_key: Optional[str]) -> None:
    """Raise if api_key doesn't match configured key. Empty key from caller = reject."""
    expected = _get_api_key()
    if not expected:
        raise PermissionError("No API key configured on server (set AI_SUPERPOWER_API_KEY env var)")
    if not api_key:
        raise PermissionError("Missing API key (set api_key argument or X-API-Key header)")
    if api_key != expected:
        raise PermissionError("Invalid API key")


def _storage_instance(config: APIConfig) -> CSVStorage:
    return CSVStorage(config)


def _to_dict(model: Any) -> dict:
    """Convert Pydantic model to dict, fallback to str() for non-models."""
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if isinstance(model, dict):
        return model
    return {"value": str(model)}


# ─── Auth bootstrap tool (special — allows client to set key for stdio) ─────

@mcp.tool()
def set_api_key(api_key: str) -> dict:
    """Set the API key in the AI_SUPERPOWER_API_KEY env var (stdio mode only)."""
    if not api_key or not isinstance(api_key, str):
        raise ValueError("api_key must be a non-empty string")
    os.environ["AI_SUPERPOWER_API_KEY"] = api_key
    return {"ok": True, "key_length": len(api_key)}


# ─── Project tools ────────────────────────────────────────────────────────────

@mcp.tool()
def list_projects(
    page: int = 1,
    page_size: int = 20,
    search: str = "",
    sort_by: str = "last_update",
    sort_order: str = "desc",
    api_key: Optional[str] = None,
) -> dict:
    """List projects with pagination, search, and sort."""
    _check_auth(api_key)
    from .config import load_config
    storage = _storage_instance(load_config())
    items, total = storage.list_projects(
        page=page, page_size=page_size, search=search,
        sort_by=sort_by, sort_order=sort_order,
    )
    return {"items": [_to_dict(i) for i in items], "total": total, "page": page, "page_size": page_size}


@mcp.tool()
def get_project(project_id: str, api_key: Optional[str] = None) -> dict:
    """Fetch a single project by ID."""
    _check_auth(api_key)
    from .config import load_config
    storage = _storage_instance(load_config())
    p = storage.get_project(project_id)
    if p is None:
        raise FileNotFoundError(f"Project not found: {project_id}")
    return _to_dict(p)


@mcp.tool()
def create_project(
    name: str,
    git_repo: str = "",
    local_path: str = "",
    description: str = "",
    prj_url: str = "",
    force: bool = False,
    api_key: Optional[str] = None,
) -> dict:
    """Create a new project. Returns the created (or pre-existing) project.

    Behavior (boss preference 2026-06-10):
    - First checks for an EXACT (case-sensitive) name match.
    - If an exact-name match exists, returns the existing project with
      ``_existing: true`` (NOT a new ID). The existing project's ``id`` is
      returned so the caller can use it directly.
    - If no exact match, performs standard case-insensitive duplicate
      check (name or git_repo). A duplicate raises ``ValueError``.
    - Pass ``force=True`` to bypass all duplicate detection (always create new).
    """
    _check_auth(api_key)
    from .config import load_config
    storage = _storage_instance(load_config())

    # Exact-name match short-circuit (boss preference, case-sensitive)
    if not force:
        existing = storage.find_project_by_exact_name(name)
        if existing is not None:
            result = _to_dict(existing)
            result["_existing"] = True
            result["_note"] = (
                f"Project with exact name {name!r} already exists; "
                f"returning existing project id {existing.id}"
            )
            return result

    project = storage.create_project(
        name=name, git_repo=git_repo, local_path=local_path,
        description=description, prj_url=prj_url, force=force,
    )
    result = _to_dict(project)
    result["_existing"] = False
    return result


@mcp.tool()
def update_project(
    project_id: str,
    updates: dict,
    api_key: Optional[str] = None,
) -> dict:
    """Update a project. Pass `updates` as {field: value} (e.g. {"name": "x", "description": "y"})."""
    _check_auth(api_key)
    if not isinstance(updates, dict) or not updates:
        raise ValueError("updates must be a non-empty dict")
    from .config import load_config
    storage = _storage_instance(load_config())
    p = storage.update_project(project_id=project_id, updates=updates)
    if p is None:
        raise FileNotFoundError(f"Project not found: {project_id}")
    return _to_dict(p)


@mcp.tool()
def delete_project(project_id: str, api_key: Optional[str] = None) -> dict:
    """Delete a project (requires allow_delete=True in config)."""
    _check_auth(api_key)
    from .config import load_config
    storage = _storage_instance(load_config())
    if not storage.config.allow_delete:
        raise PermissionError("allow_delete=False in config; deletion disabled")
    ok = storage.delete_project(project_id)
    if not ok:
        raise FileNotFoundError(f"Project not found: {project_id}")
    return {"deleted": True, "project_id": project_id}


@mcp.tool()
def check_project_duplicate(
    name: str = "",
    git_repo: str = "",
    api_key: Optional[str] = None,
) -> dict:
    """Check if a project with the given name or git_repo already exists.

    Returns {"duplicate": False} or {"duplicate": True, "reason": ..., "existing_id": ..., "existing_value": ...}
    """
    _check_auth(api_key)
    from .config import load_config
    storage = _storage_instance(load_config())
    if not name and not git_repo:
        raise ValueError("Must provide at least one of name or git_repo")
    result = storage.check_project_duplicate(name=name, git_repo=git_repo)
    if result is None:
        return {"duplicate": False}
    return {"duplicate": True, **result}


# ─── Proposal tools ───────────────────────────────────────────────────────────

@mcp.tool()
def list_proposals(
    page: int = 1,
    page_size: int = 20,
    search: str = "",
    status: str = "",
    project_id: str = "",
    sort_by: str = "last_update",
    sort_order: str = "desc",
    api_key: Optional[str] = None,
) -> dict:
    """List proposals with pagination, search, status/project filter, and sort."""
    _check_auth(api_key)
    from .config import load_config
    storage = _storage_instance(load_config())
    items, total = storage.list_proposals(
        page=page, page_size=page_size, search=search, status=status or None,
        project_id=project_id or None, sort_by=sort_by, sort_order=sort_order,
    )
    return {"items": [_to_dict(i) for i in items], "total": total, "page": page, "page_size": page_size}


@mcp.tool()
def get_proposal(proposal_id: str, api_key: Optional[str] = None) -> dict:
    """Fetch a single proposal by ID."""
    _check_auth(api_key)
    from .config import load_config
    storage = _storage_instance(load_config())
    p = storage.get_proposal(proposal_id)
    if p is None:
        raise FileNotFoundError(f"Proposal not found: {proposal_id}")
    return _to_dict(p)


@mcp.tool()
def create_proposal(
    data: dict,
    api_key: Optional[str] = None,
) -> dict:
    """Create a new proposal. Pass `data` as {field: value}.

    Required fields: title, project_id, owner. Optional: stage, prd_path, tech_solution_path,
    project_path, git_repo, deployment_url, prd_confirmation, tech_expectations, engine, target,
    game_type, notes.
    """
    _check_auth(api_key)
    if not isinstance(data, dict) or not data:
        raise ValueError("data must be a non-empty dict")
    for required in ("title", "project_id", "owner"):
        if required not in data:
            raise ValueError(f"data missing required field: {required}")
    from .config import load_config
    storage = _storage_instance(load_config())
    p = storage.create_proposal(data=data)
    return _to_dict(p)


@mcp.tool()
def update_proposal_status(
    proposal_id: str,
    status: str,
    api_key: Optional[str] = None,
) -> dict:
    """Update a proposal's status (state machine validated)."""
    _check_auth(api_key)
    from .config import load_config
    storage = _storage_instance(load_config())
    p = storage.update_proposal_status(proposal_id=proposal_id, new_status=status)
    if p is None:
        raise FileNotFoundError(f"Proposal not found: {proposal_id}")
    return _to_dict(p)


@mcp.tool()
def update_proposal_fields(
    proposal_id: str,
    fields: dict,
    api_key: Optional[str] = None,
) -> dict:
    """Update specific fields of a proposal. Pass `fields` as {field: value}."""
    _check_auth(api_key)
    if not isinstance(fields, dict) or not fields:
        raise ValueError("fields must be a non-empty dict")
    from .config import load_config
    storage = _storage_instance(load_config())
    p = storage.update_proposal(proposal_id=proposal_id, updates=fields)
    if p is None:
        raise FileNotFoundError(f"Proposal not found: {proposal_id}")
    return _to_dict(p)


@mcp.tool()
def delete_proposal(proposal_id: str, api_key: Optional[str] = None) -> dict:
    """Delete a proposal (requires allow_delete=True in config)."""
    _check_auth(api_key)
    from .config import load_config
    storage = _storage_instance(load_config())
    if not storage.config.allow_delete:
        raise PermissionError("allow_delete=False in config; deletion disabled")
    ok = storage.delete_proposal(proposal_id)
    if not ok:
        raise FileNotFoundError(f"Proposal not found: {proposal_id}")
    return {"deleted": True, "proposal_id": proposal_id}


@mcp.tool()
def scan_duplicate_projects(
    case_insensitive: bool = True,
    api_key: Optional[str] = None,
) -> list[dict]:
    """Scan existing projects for duplicate names (legacy data deduplication).

    Returns groups of projects sharing the same name (case-insensitive by default).
    Each group: {"name": "...", "count": N, "projects": [{id, name, ...}, ...]}.
    Only groups with >= 2 projects are returned.

    Typical workflow:
        1. Call this tool to find duplicates
        2. Pick the "target" (older / canonical project) and "source" (newer / typo)
        3. Call `merge_projects(target_id=..., source_id=..., delete_source=True)`
           to move proposals and delete source
    """
    _check_auth(api_key)
    from .config import load_config
    storage = _storage_instance(load_config())
    return storage.scan_duplicate_projects(case_insensitive=case_insensitive)


@mcp.tool()
def merge_projects(
    target_id: str,
    source_id: str,
    delete_source: bool = True,
    api_key: Optional[str] = None,
) -> dict:
    """Merge source_project INTO target_project.

    Steps (boss preference 2026-06-10):
    1. Move ALL proposals of source → target (project_id field rewritten,
       all other fields preserved including status, stage, notes)
    2. Audit each merged proposal's project_id change
    3. If delete_source=True: remove source project from projects.csv

    Returns: {"target_id", "source_id", "merged_proposals", "merged_proposal_ids",
              "deleted_source"}.

    Raises ValueError if target_id == source_id, target not found, or source not found.
    """
    _check_auth(api_key)
    from .config import load_config
    storage = _storage_instance(load_config())
    return storage.merge_projects(
        target_id=target_id, source_id=source_id, delete_source=delete_source,
    )


@mcp.tool()
def merge_proposals_by_project(
    target_project_id: str,
    source_project_name: str,
    api_key: Optional[str] = None,
) -> dict:
    """Merge all proposals from source project (matched by name) into target project.

    Only `active`/`archived` proposals are moved; in-progress ones stay.
    """
    _check_auth(api_key)
    from .config import load_config
    storage = _storage_instance(load_config())
    return storage.merge_proposals_by_project(
        target_project_id=target_project_id,
        source_project_name=source_project_name,
    )


# ─── Audit / stats tools ──────────────────────────────────────────────────────

@mcp.tool()
def get_audit(
    page: int = 1,
    page_size: int = 50,
    entity: str = "",
    op: str = "",
    api_key: Optional[str] = None,
) -> dict:
    """Get audit log entries with pagination + filter."""
    _check_auth(api_key)
    from .config import load_config
    storage = _storage_instance(load_config())
    entries, total = storage.list_audit(
        page=page, page_size=page_size, entity=entity or None, op=op or None,
    )
    return {"items": entries, "total": total, "page": page, "page_size": page_size}


@mcp.tool()
def get_stats(
    days: int = 30,
    api_key: Optional[str] = None,
) -> dict:
    """Get aggregate statistics (project count, proposal count, audit count, etc.)."""
    _check_auth(api_key)
    from .config import load_config
    storage = _storage_instance(load_config())
    return storage.get_stats(days=days)


# ─── Sync tools ───────────────────────────────────────────────────────────────

@mcp.tool()
def get_sync_config(api_key: Optional[str] = None) -> dict:
    """Read current sync configuration."""
    _check_auth(api_key)
    from .config import load_config
    cfg = load_config()
    return {
        "sync_target_repo": cfg.sync_target_repo,
        "sync_prj_repo": cfg.sync_prj_repo,
        "sync_enabled": cfg.sync_enabled,
        "sync_api_key_set": bool(cfg.sync_api_key),
        "sync_interval_minutes": cfg.sync_interval_minutes,
        "sync_last_run": cfg.sync_last_run,
    }


@mcp.tool()
def update_sync_config(
    sync_target_repo: str = "",
    sync_prj_repo: str = "",
    sync_enabled: Optional[bool] = None,
    sync_api_key: str = "",
    sync_interval_minutes: Optional[int] = None,
    api_key: Optional[str] = None,
) -> dict:
    """Update sync configuration (persisted to config.toml)."""
    _check_auth(api_key)
    from .config import load_config
    import tomllib

    cfg = load_config()
    if sync_target_repo:
        cfg.sync_target_repo = sync_target_repo
    if sync_prj_repo:
        cfg.sync_prj_repo = sync_prj_repo
    if sync_enabled is not None:
        cfg.sync_enabled = sync_enabled
    if sync_api_key:
        cfg.sync_api_key = sync_api_key
    if sync_interval_minutes is not None:
        cfg.sync_interval_minutes = sync_interval_minutes

    # Persist to config.toml (preserve other sections)
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            existing = tomllib.load(f)
    else:
        existing = {}

    api_section = existing.get("api", {})
    api_section["sync_target_repo"] = cfg.sync_target_repo
    api_section["sync_prj_repo"] = cfg.sync_prj_repo
    api_section["sync_enabled"] = cfg.sync_enabled
    api_section["sync_api_key"] = cfg.sync_api_key
    api_section["sync_interval_minutes"] = cfg.sync_interval_minutes
    existing["api"] = api_section

    # Re-serialize (basic TOML writer — avoids extra dep)
    lines = []
    for section, vals in existing.items():
        lines.append(f"[{section}]")
        for k, v in vals.items():
            if isinstance(v, bool):
                lines.append(f"{k} = {str(v).lower()}")
            elif isinstance(v, int):
                lines.append(f"{k} = {v}")
            else:
                lines.append(f'{k} = "{v}"')
        lines.append("")
    with open(CONFIG_PATH, "w") as f:
        f.write("\n".join(lines))

    return {"updated": True, "config_path": str(CONFIG_PATH)}


@mcp.tool()
def export_sync(api_key: Optional[str] = None) -> dict:
    """Trigger a sync export to GitHub Pages (CSV → JSON push)."""
    _check_auth(api_key)
    from .config import load_config
    from .sync_gh_pages import export_to_github_pages
    cfg = load_config()
    storage = _storage_instance(cfg)
    if not cfg.sync_target_repo:
        raise ValueError("sync_target_repo not configured")
    result = export_to_github_pages(
        storage=storage,
        target_repo=cfg.sync_target_repo,
        api_key=cfg.sync_api_key or "",
    )
    return result


@mcp.tool()
def get_sync_status(api_key: Optional[str] = None) -> dict:
    """Get current sync status (enabled, last run, target repo)."""
    _check_auth(api_key)
    from .config import load_config
    cfg = load_config()
    return {
        "sync_enabled": cfg.sync_enabled,
        "sync_last_run": cfg.sync_last_run,
        "sync_target_repo": cfg.sync_target_repo,
        "sync_interval_minutes": cfg.sync_interval_minutes,
    }


# ─── ASGI app factory (for FastAPI mount) ─────────────────────────────────────

def make_asgi_app() -> "Starlette":
    """Return the ASGI app for Streamable HTTP transport (mount at /mcp).

    The inner Starlette's own lifespan runs the session manager. When
    mounted as a sub-app of a parent FastAPI, the lifespan IS triggered
    by Starlette on the first request (the Mount wrapper runs it as part
    of sub-app startup). For stdio usage, `mcp.run(transport='stdio')`
    handles lifespan directly.

    See `references/mcp-connection-troubleshooting.md` § 3 for details on
    the mount+sub-app lifespan interaction.
    """
    return mcp.streamable_http_app()


def main_stdio() -> None:
    """Entry point for `aisp mcp --transport=stdio`."""
    mcp.run(transport="stdio")


def main_http(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Entry point for `aisp mcp --transport=http`."""
    import uvicorn
    app = mcp.streamable_http_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    main_stdio()
