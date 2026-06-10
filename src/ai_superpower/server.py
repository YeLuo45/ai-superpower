"""FastAPI server for ai-superpower — API + Web UI."""
import hashlib
import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query, Response, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent))

from ai_superpower.config import load_config, _parse_frequency
from ai_superpower.models import (
    Proposal,
    ProposalCreate,
    ProposalStatusUpdate,
    ProposalUpdate,
    Project,
    ProjectCreate,
    ProjectUpdate,
    VALID_ENUMS,
)
from ai_superpower.storage import CSVStorage

# APScheduler for sync jobs
_scheduler = None


def _run_scheduled_sync():
    """Background job that runs the scheduled sync export."""
    from datetime import datetime
    from .sync_gh_pages import export_to_github_pages

    global _export_status, _export_last_run
    try:
        config = load_config()
        if not config.sync_enabled or config.sync_interval_minutes <= 0:
            return
        if _storage is None:
            return
        _export_status = "running"
        result = export_to_github_pages(
            storage=get_storage(),
            target_repo=config.sync_target_repo or "YeLuo45/ai-superpower",
            api_key=config.sync_api_key or "",
        )
        _export_last_run = datetime.now().isoformat()
        _export_status = "done" if result.get("success") else "error"
    except Exception:
        _export_status = "error"


# ─── Response Models ───────────────────────────────────────────────────────────

class PageResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list


class ValidateResponse(BaseModel):
    valid: bool
    errors: list[str]


class StatsResponse(BaseModel):
    totals: dict
    today: dict
    trends: dict
    by_status: dict
    recent_activity: list


# ─── App Setup ───────────────────────────────────────────────────────────────

app = FastAPI(title="ai-superpower", version="0.1.0")
_storage: Optional[CSVStorage] = None
_export_status: str = "idle"
_export_last_run: str = ""

# Static / templates (set up after startup)
_templates: Optional[Jinja2Templates] = None

# Mount MCP server (Streamable HTTP) at /mcp
# This lets consumers (browsers, remote agents) connect to MCP via HTTP+SSE
# alongside the existing Web UI and (legacy) /api/* REST endpoints.
#
# IMPORTANT: FastAPI doesn't propagate mounted sub-app lifespans, so the
# inner StreamableHTTP session manager is started lazily in the FIRST
# /mcp request handler instead of in lifespan. This avoids breaking
# test fixtures that create multiple TestClient instances back-to-back.
try:
    from ai_superpower.mcp_server import make_asgi_app as _make_mcp_app
    _mcp_app = _make_mcp_app()
    app.mount("/mcp", _mcp_app)
except Exception as _mcp_err:
    # MCP optional — log and continue if not importable
    import warnings
    warnings.warn(f"MCP server not mounted: {_mcp_err}")
    _mcp_app = None


@app.on_event("startup")
def startup():
    global _storage, _templates, _scheduler
    config = load_config()
    actor = hashlib.sha256(config.key.encode()).hexdigest()[:8]
    _storage = CSVStorage(config, actor=actor)

    # Templates point to package templates dir
    templates_dir = Path(__file__).parent / "templates"
    _templates = Jinja2Templates(directory=str(templates_dir))

    # Mount static files
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ── APScheduler: register sync job ───────────────────────────────────────────
    if config.sync_enabled and config.sync_interval_minutes > 0:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            _scheduler = BackgroundScheduler()
            _scheduler.add_job(
                _run_scheduled_sync,
                "interval",
                minutes=config.sync_interval_minutes,
                id="sync_export_job",
            )
            _scheduler.start()
            print(f"[Scheduler] Sync job registered: every {config.sync_interval_minutes} minutes", flush=True)
        except Exception as e:
            print(f"[Scheduler] Failed to start sync job: {e}", flush=True)


def get_storage() -> CSVStorage:
    if _storage is None:
        raise HTTPException(status_code=503, detail="Storage not initialized")
    return _storage


def get_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> str:
    config = load_config()
    if x_api_key != config.key:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return x_api_key


# ─── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "healthy"}


# ─── Projects ─────────────────────────────────────────────────────────────────

@app.post("/api/projects", response_model=Project, status_code=201)
def create_project(data: ProjectCreate, force: bool = Query(False), _ak: str = Header(..., alias="X-API-Key")):
    s = get_storage()
    errors = s.validate_project(data.model_dump())
    if errors:
        raise HTTPException(status_code=400, detail="\n".join(errors))
    # Exact-name short-circuit (boss preference 2026-06-10)
    if not force:
        existing = s.find_project_by_exact_name(data.name)
        if existing is not None:
            from fastapi.responses import JSONResponse
            payload = existing.model_dump()
            payload["_existing"] = True
            payload["_note"] = (
                f"Project with exact name {data.name!r} already exists; "
                f"returning existing project id {existing.id}"
            )
            return JSONResponse(status_code=200, content=payload)
    try:
        return s.create_project(
            name=data.name,
            git_repo=data.git_repo or "",
            local_path=data.local_path or "",
            description=data.description or "",
            prj_url=data.prj_url or "",
            force=force,
        )
    except ValueError as e:
        msg = str(e)
        if "Duplicate project" in msg:
            # Extract existing_id from error if present
            existing_id = ""
            if "existing_id=" in msg:
                existing_id = msg.split("existing_id=")[-1].strip()
            raise HTTPException(
                status_code=409,
                detail=msg,
            )
        raise HTTPException(status_code=409, detail=msg)


@app.get("/api/projects/duplicates")
def list_duplicate_projects(
    case_insensitive: bool = Query(True),
    _ak: str = Header(..., alias="X-API-Key"),
):
    """Scan existing projects for duplicate names (case-insensitive by default).

    Returns: [{"name": "...", "count": N, "projects": [{id, name, git_repo, ...}, ...]}, ...]
    """
    s = get_storage()
    return s.scan_duplicate_projects(case_insensitive=case_insensitive)


class MergeProjectsRequest(BaseModel):
    target_id: str
    source_id: str
    delete_source: bool = True


@app.post("/api/projects/merge")
def merge_projects_endpoint(
    body: MergeProjectsRequest,
    _ak: str = Header(..., alias="X-API-Key"),
):
    """Merge source project INTO target project.

    Steps:
    1. Move all proposals from source → target (project_id field rewritten)
    2. Audit each proposal's project_id change
    3. If delete_source=True: remove source project from projects.csv
    """
    s = get_storage()
    try:
        return s.merge_projects(
            target_id=body.target_id,
            source_id=body.source_id,
            delete_source=body.delete_source,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/projects/check-duplicate")
def check_project_duplicate(
    name: Optional[str] = Query(None),
    git_repo: Optional[str] = Query(None),
    _ak: str = Header(..., alias="X-API-Key"),
):
    """Check if a project with the same name or git_repo already exists."""
    if not name and not git_repo:
        raise HTTPException(status_code=400, detail="name or git_repo required")
    s = get_storage()
    result = s.check_project_duplicate(name=name or "", git_repo=git_repo or "")
    if result is None:
        return {"duplicate": False}
    return {"duplicate": True, **result}


@app.get("/api/projects", response_model=PageResponse)
def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = None,
    sort_by: Optional[str] = Query("last_update", description="Sort field: last_update, create_at, name, id"),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc or desc"),
    _ak: str = Header(..., alias="X-API-Key"),
):
    s = get_storage()
    items, total = s.list_projects(
        page=page, page_size=page_size, search=search,
        sort_by=sort_by, sort_order=sort_order,
    )
    return PageResponse(total=total, page=page, page_size=page_size, items=[i.model_dump() for i in items])


@app.get("/api/projects/{project_id}", response_model=Project)
def get_project(project_id: str, _ak: str = Header(..., alias="X-API-Key")):
    s = get_storage()
    project = s.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.put("/api/projects/{project_id}", response_model=Project)
def update_project(project_id: str, data: ProjectUpdate, _ak: str = Header(..., alias="X-API-Key")):
    s = get_storage()
    existing = s.get_project(project_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Project not found")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    return s.update_project(project_id, updates)


@app.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: str, _ak: str = Header(..., alias="X-API-Key")):
    s = get_storage()
    print(f"[DEBUG] allow_delete={s.config.allow_delete}", flush=True)
    if not s.config.allow_delete:
        raise HTTPException(
            status_code=403,
            detail="Delete operation is disabled. Set `allow_delete = true` in config.toml to enable.",
        )
    try:
        deleted = s.delete_project(project_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Project not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response(status_code=204)


# ─── Project Sync Status ─────────────────────────────────────────────────────

class SyncStatusResponse(BaseModel):
    project_id: str
    sync_enabled: bool
    sync_last_run: str = ""


@app.get("/api/projects/{project_id}/sync-status", response_model=SyncStatusResponse)
def get_project_sync_status(project_id: str, _ak: str = Header(..., alias="X-API-Key")):
    s = get_storage()
    project = s.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return SyncStatusResponse(
        project_id=project_id,
        sync_enabled=project.sync_enabled == "true",
        sync_last_run=project.sync_last_run,
    )


@app.put("/api/projects/{project_id}/sync-enabled", response_model=Project)
def set_project_sync_enabled(project_id: str, enabled: bool, _ak: str = Header(..., alias="X-API-Key")):
    s = get_storage()
    project = s.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return s.update_project(project_id, {"sync_enabled": "true" if enabled else "false"})


# ─── Global Sync Config ─────────────────────────────────────────────────────

class SyncConfigResponse(BaseModel):
    sync_target_repo: str
    sync_prj_repo: str
    sync_enabled: bool
    sync_frequency: str
    sync_interval_minutes: int
    sync_api_key_masked: str  # masked, not actual key


class SyncConfigUpdate(BaseModel):
    sync_target_repo: Optional[str] = None
    sync_prj_repo: Optional[str] = None
    sync_enabled: Optional[bool] = None
    sync_frequency: Optional[str] = None  # "1h", "6h", "off", etc.
    sync_api_key: Optional[str] = None


def _frequency_to_str(minutes: int) -> str:
    """Convert interval minutes back to frequency string."""
    if minutes >= 1440:
        return f"{minutes // 1440}d"
    if minutes >= 60:
        return f"{minutes // 60}h"
    if minutes > 0:
        return f"{minutes}m"
    return "off"


@app.get("/api/sync/config", response_model=SyncConfigResponse)
def get_sync_config(_ak: str = Header(..., alias="X-API-Key")):
    config = load_config()
    masked = "********" if config.sync_api_key else ""
    return SyncConfigResponse(
        sync_target_repo=config.sync_target_repo or "",
        sync_prj_repo=config.sync_prj_repo or "",
        sync_enabled=config.sync_enabled,
        sync_frequency=_frequency_to_str(config.sync_interval_minutes),
        sync_interval_minutes=config.sync_interval_minutes,
        sync_api_key_masked=masked,
    )


@app.put("/api/sync/config", response_model=SyncConfigResponse)
def put_sync_config(data: SyncConfigUpdate, _ak: str = Header(..., alias="X-API-Key")):
    """Update sync config (target_repo, prj_repo, enabled, frequency, api_key).
    Writes updated values back to config.toml so they persist across restarts."""
    from pathlib import Path
    import tomllib

    config = load_config()
    masked = "********" if config.sync_api_key else ""

    # Apply updates
    if data.sync_target_repo is not None:
        config.sync_target_repo = data.sync_target_repo
    if data.sync_prj_repo is not None:
        config.sync_prj_repo = data.sync_prj_repo
    if data.sync_enabled is not None:
        config.sync_enabled = data.sync_enabled
    if data.sync_frequency is not None:
        config.sync_interval_minutes = _parse_frequency(data.sync_frequency)
    if data.sync_api_key is not None:
        config.sync_api_key = data.sync_api_key
        masked = "********" if data.sync_api_key else ""

    # Persist to config.toml
    config_path = Path.home() / ".ai-superpower" / "config.toml"
    try:
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)
    except Exception:
        raw = {}

    # Ensure [sync] section
    if "sync" not in raw:
        raw["sync"] = {}
    raw["sync"]["target_repo"] = config.sync_target_repo
    raw["sync"]["prj_repo"] = config.sync_prj_repo
    raw["sync"]["enabled"] = config.sync_enabled
    raw["sync"]["frequency"] = _frequency_to_str(config.sync_interval_minutes)
    if config.sync_api_key:
        raw["sync"]["api_key"] = config.sync_api_key

    # Write back
    import io
    buf = io.StringIO()
    for section, keys in [("api", ["key", "socket_path", "data_dir", "allow_delete"]),
                           ("backup", ["enabled", "frequency", "local_path", "remote_repo", "remote_branch", "api_key", "max_copies", "auto_backup_threshold"]),
                           ("sync", ["enabled", "frequency", "target_repo", "api_key", "prj_repo"]),
                           ("server", ["host", "port"])]:
        if section not in raw:
            continue
        buf.write(f"[{section}]\n")
        for k in keys:
            v = raw[section].get(k)
            if v is None:
                continue
            if isinstance(v, bool):
                buf.write(f"{k} = {'true' if v else 'false'}\n")
            elif isinstance(v, int):
                buf.write(f"{k} = {v}\n")
            else:
                buf.write(f'{k} = "{v}"\n')
        buf.write("\n")

    with open(config_path, "w") as f:
        f.write(buf.getvalue())

    return SyncConfigResponse(
        sync_target_repo=config.sync_target_repo or "",
        sync_prj_repo=config.sync_prj_repo or "",
        sync_enabled=config.sync_enabled,
        sync_frequency=_frequency_to_str(config.sync_interval_minutes),
        sync_interval_minutes=config.sync_interval_minutes,
        sync_api_key_masked=masked,
    )


# Keep POST for backward compat — redirect to PUT
@app.post("/api/sync/config", response_model=SyncConfigResponse)
def post_sync_config(data: SyncConfigUpdate, _ak: str = Header(..., alias="X-API-Key")):
    return put_sync_config(data, _ak)


@app.post("/api/sync/export", status_code=202)
def trigger_sync_export(_ak: str = Header(..., alias="X-API-Key")):
    """Trigger CSV → JSON export to GitHub Pages gh-pages branch.

    Runs export_to_github_pages() to push proposals.json, projects.json,
    and export_info.json to the data/ directory on gh-pages.
    """
    from datetime import datetime
    from .sync_gh_pages import export_to_github_pages

    global _export_status, _export_last_run

    config = load_config()
    s = get_storage()

    _export_status = "running"

    try:
        result = export_to_github_pages(
            storage=s,
            target_repo=config.sync_target_repo or "YeLuo45/ai-superpower",
            api_key=config.backup_api_key or config.sync_api_key or "",
        )
        _export_last_run = datetime.now().isoformat()
        _export_status = "done" if result.get("success") else "error"
        return {
            "status": "accepted",
            "message": result.get("message", "Export complete"),
            "export_last_run": _export_last_run,
            "files_created": result.get("files_created", 0),
            "proposals_count": result.get("proposals_count", 0),
            "projects_count": result.get("projects_count", 0),
        }
    except Exception as ex:
        _export_status = "error"
        return {
            "status": "error",
            "message": str(ex),
            "export_last_run": _export_last_run,
        }


class ExportStatusResponse(BaseModel):
    export_last_run: str
    export_status: str  # "idle" | "running" | "done" | "error"
    proposals_count: int
    projects_count: int


@app.get("/api/sync/export-status", response_model=ExportStatusResponse)
def get_export_status(_ak: str = Header(..., alias="X-API-Key")):
    """Return current export status and last run timestamp."""
    s = get_storage()

    # Count current items
    proposals, total_p = s.list_proposals(page=1, page_size=1)
    projects, total_proj = s.list_projects(page=1, page_size=1)

    return ExportStatusResponse(
        export_last_run=_export_last_run,
        export_status=_export_status,
        proposals_count=total_p,
        projects_count=total_proj,
    )


# ─── Sync Push & Status (Direction B) ────────────────────────────────────────

class ProjectSyncStatusResponse(BaseModel):
    project_id: str
    sync_enabled: bool
    sync_last_run: str = ""


class GlobalSyncStatusResponse(BaseModel):
    sync_enabled: bool
    sync_target_repo: str
    sync_prj_repo: str
    sync_last_run: str
    sync_interval_minutes: int


@app.get("/api/sync/status", response_model=GlobalSyncStatusResponse)
def get_sync_status(_ak: str = Header(..., alias="X-API-Key")):
    """Return current sync configuration and last run timestamp."""
    config = load_config()
    return GlobalSyncStatusResponse(
        sync_enabled=config.sync_enabled,
        sync_target_repo=config.sync_target_repo or "",
        sync_prj_repo=config.sync_prj_repo or "",
        sync_last_run=config.sync_last_run or "",
        sync_interval_minutes=config.sync_interval_minutes,
    )


class SyncPushResponse(BaseModel):
    success: bool
    message: str
    pushed_count: int = 0
    sync_last_run: str = ""


@app.post("/api/sync/push", response_model=SyncPushResponse)
def sync_push(_ak: str = Header(..., alias="X-API-Key")):
    """Read proposals.csv, convert to prj-proposals-manager format, push to GitHub.

    Returns count of proposals pushed and timestamp of this run.
    """
    from datetime import datetime
    from .sync import csv_to_prj_proposals_json, push_proposals_to_github

    config = load_config()
    s = get_storage()

    # Convert proposals.csv to JSON
    proposals_json = csv_to_prj_proposals_json(config.proposals_csv)

    # Push to GitHub if target is configured
    pushed_count = len(proposals_json)
    sync_last_run = datetime.now().isoformat()

    if config.sync_target_repo and config.sync_api_key:
        result = push_proposals_to_github(
            data=proposals_json,
            target_repo=config.sync_target_repo,
            api_key=config.sync_api_key,
        )
        if not result.get("success"):
            return SyncPushResponse(
                success=False,
                message=result.get("message", "Push failed"),
                pushed_count=0,
                sync_last_run=sync_last_run,
            )
        pushed_count = result.get("pushed_count", len(proposals_json))
    elif not config.sync_target_repo:
        return SyncPushResponse(
            success=False,
            message="sync_target_repo not configured",
            pushed_count=0,
            sync_last_run=sync_last_run,
        )

    return SyncPushResponse(
        success=True,
        message=f"Pushed {pushed_count} proposals to {config.sync_target_repo}",
        pushed_count=pushed_count,
        sync_last_run=sync_last_run,
    )


# ─── Proposals ───────────────────────────────────────────────────────────────

@app.post("/api/proposals", response_model=Proposal, status_code=201)
def create_proposal(data: ProposalCreate, _ak: str = Header(..., alias="X-API-Key")):
    s = get_storage()
    errors = s.validate_proposal(data.model_dump())
    if errors:
        raise HTTPException(status_code=400, detail="\n".join(errors))
    return s.create_proposal(data.model_dump())


@app.get("/api/proposals", response_model=PageResponse)
def list_proposals(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    owner: Optional[str] = None,
    search: Optional[str] = None,
    stage: Optional[str] = None,
    sort_by: Optional[str] = Query("last_update", description="Sort field: last_update, create_at, update_at, title, id, status, stage"),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc or desc"),
    _ak: str = Header(..., alias="X-API-Key"),
):
    s = get_storage()
    items, total = s.list_proposals(
        page=page, page_size=page_size,
        project_id=project_id, status=status,
        owner=owner, search=search, stage=stage,
        sort_by=sort_by, sort_order=sort_order,
    )
    return PageResponse(total=total, page=page, page_size=page_size, items=[i.model_dump() for i in items])


@app.get("/api/proposals/{proposal_id}", response_model=Proposal)
def get_proposal(proposal_id: str, _ak: str = Header(..., alias="X-API-Key")):
    s = get_storage()
    proposal = s.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


@app.put("/api/proposals/{proposal_id}/status", response_model=Proposal)
def update_proposal_status(proposal_id: str, data: ProposalStatusUpdate, _ak: str = Header(..., alias="X-API-Key")):
    s = get_storage()
    try:
        return s.update_proposal_status(proposal_id, data.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/proposals/{proposal_id}/fields", response_model=Proposal)
def update_proposal_fields(proposal_id: str, data: ProposalUpdate, _ak: str = Header(..., alias="X-API-Key")):
    s = get_storage()
    existing = s.get_proposal(proposal_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    for field, valid_values in VALID_ENUMS.items():
        if field in updates:
            val = updates[field]
            if val and val not in valid_values:
                raise HTTPException(status_code=400, detail=f"Invalid {field}: {val}")
    return s.update_proposal(proposal_id, updates)


@app.delete("/api/proposals/{proposal_id}", status_code=204)
def delete_proposal(proposal_id: str, _ak: str = Header(..., alias="X-API-Key")):
    s = get_storage()
    print(f"[DEBUG] allow_delete={s.config.allow_delete}", flush=True)
    if not s.config.allow_delete:
        raise HTTPException(
            status_code=403,
            detail="Delete operation is disabled. Set `allow_delete = true` in config.toml to enable.",
        )
    deleted = s.delete_proposal(proposal_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return Response(status_code=204)


class MergeByProjectRequest(BaseModel):
    target_project_id: str
    source_project_name: str


class MergeByProjectResponse(BaseModel):
    merged_count: int
    merged_ids: list[str]


@app.post("/api/proposals/merge-by-project", response_model=MergeByProjectResponse)
def merge_proposals_by_project(body: MergeByProjectRequest, _ak: str = Header(..., alias="X-API-Key")):
    """Merge all proposals from source_project_name into target_project_id.

    Only proposals with status 'active' or 'archived' are merged.
    """
    s = get_storage()
    try:
        result = s.merge_proposals_by_project(
            target_project_id=body.target_project_id,
            source_project_name=body.source_project_name,
        )
        return MergeByProjectResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Validate ─────────────────────────────────────────────────────────────────

class ValidatePayload(BaseModel):
    data: dict


@app.post("/validate", response_model=ValidateResponse)
def validate(data: ValidatePayload, _ak: str = Header(..., alias="X-API-Key")):
    s = get_storage()
    errors = s.validate_proposal(data.data)
    return ValidateResponse(valid=len(errors) == 0, errors=errors)


# ─── Audit ───────────────────────────────────────────────────────────────────

class UndoRequest(BaseModel):
    entity: str  # "project" or "proposal"
    id: str


class UndoResponse(BaseModel):
    success: bool
    message: str
    entry: dict
    warning: bool = False


@app.post("/api/replay/undo", response_model=UndoResponse)
def undo_operation(body: UndoRequest, _ak: str = Header(..., alias="X-API-Key")):
    """Undo the last operation on an entity.

    Uses Replay.undo_last() programmatically (not CLI) to reverse the last
    operation recorded in the audit log for the given entity.
    """
    from ai_superpower.replay import Replay

    s = get_storage()
    # Replay needs to use the same storage as the server
    replay = Replay(dry_run=False)
    # Inject the server's storage so undo operations use the same data
    replay.storage = s

    result = replay.undo_last(body.id, entity=body.entity)

    return UndoResponse(
        success=result.get("success", False),
        message=result.get("message", ""),
        entry=result.get("entry") or {},
        warning=result.get("warning", False),
    )


@app.get("/api/stats", response_model=StatsResponse)
def get_stats(
    days: int = Query(30, ge=7, le=90, description="Trend window in days"),
    _ak: str = Header(..., alias="X-API-Key"),
):
    s = get_storage()
    return s.get_stats(days=days)


@app.get("/api/audit", response_model=PageResponse)
def list_audit(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    entity_id: Optional[str] = None,
    op: Optional[str] = None,
    entity: Optional[str] = None,
    _ak: str = Header(..., alias="X-API-Key"),
):
    s = get_storage()
    items, total = s.list_audit(page=page, page_size=page_size, entity_id=entity_id, op=op, entity=entity)
    return PageResponse(total=total, page=page, page_size=page_size, items=items)


# ─── Web UI ───────────────────────────────────────────────────────────────────

def _web_ctx(request: Request) -> dict:
    config = load_config()
    sync_config = {
        "sync_target_repo": config.sync_target_repo or "",
        "sync_prj_repo": config.sync_prj_repo or "",
        "sync_enabled": config.sync_enabled,
        "sync_interval_minutes": config.sync_interval_minutes,
        "sync_frequency": _frequency_to_str(config.sync_interval_minutes),
        "sync_last_run": config.sync_last_run or "",
    }
    return {
        "request": request,
        "api_key": config.key,
        "socket_path": config.socket_path,
        "data_dir": config.data_dir or str(Path(config.projects_csv).parent),
        "sync_config": sync_config,
    }


@app.get("/", response_class=HTMLResponse)
def web_index(request: Request):
    return _templates.TemplateResponse("index.html", _web_ctx(request))


@app.get("/web", response_class=RedirectResponse)
def web_root():
    return RedirectResponse(url="/", status_code=302)


@app.get("/web/projects", response_class=HTMLResponse)
def web_projects(request: Request):
    return _templates.TemplateResponse("projects/list.html", _web_ctx(request))


@app.get("/web/proposals", response_class=HTMLResponse)
def web_proposals(request: Request):
    return _templates.TemplateResponse("proposals/list.html", _web_ctx(request))


@app.get("/web/audit", response_class=HTMLResponse)
def web_audit(request: Request):
    return _templates.TemplateResponse("audit.html", _web_ctx(request))


@app.get("/web/settings", response_class=HTMLResponse)
def web_settings(request: Request):
    return _templates.TemplateResponse("settings.html", _web_ctx(request))
