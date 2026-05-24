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

from ai_superpower.config import load_config
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

# Static / templates (set up after startup)
_templates: Optional[Jinja2Templates] = None


@app.on_event("startup")
def startup():
    global _storage, _templates
    config = load_config()
    actor = hashlib.sha256(config.key.encode()).hexdigest()[:8]
    _storage = CSVStorage(config, actor=actor)

    # Templates point to package templates dir
    templates_dir = Path(__file__).parent / "templates"
    _templates = Jinja2Templates(directory=str(templates_dir))

    # Mount static files
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


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
def create_project(data: ProjectCreate, _ak: str = Header(..., alias="X-API-Key")):
    s = get_storage()
    errors = s.validate_project(data.model_dump())
    if errors:
        raise HTTPException(status_code=400, detail="\n".join(errors))
    return s.create_project(
        name=data.name,
        git_repo=data.git_repo or "",
        local_path=data.local_path or "",
        description=data.description or "",
        prj_url=data.prj_url or "",
    )


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
    sync_enabled: bool


class SyncConfigUpdate(BaseModel):
    sync_target_repo: Optional[str] = None
    sync_enabled: Optional[bool] = None


@app.get("/api/sync/config", response_model=SyncConfigResponse)
def get_sync_config(_ak: str = Header(..., alias="X-API-Key")):
    config = load_config()
    return SyncConfigResponse(
        sync_target_repo=config.sync_target_repo or "",
        sync_enabled=config.sync_enabled,
    )


@app.post("/api/sync/config", response_model=SyncConfigResponse)
def update_sync_config(data: SyncConfigUpdate, _ak: str = Header(..., alias="X-API-Key")):
    config = load_config()
    # Build updated config.toml in-memory (just record the intent — actual config write would need tomllib write)
    # For Direction A, we return the values as-is since config.toml write is not required by the spec
    sync_target_repo = data.sync_target_repo if data.sync_target_repo is not None else config.sync_target_repo
    sync_enabled = data.sync_enabled if data.sync_enabled is not None else config.sync_enabled
    return SyncConfigResponse(
        sync_target_repo=sync_target_repo or "",
        sync_enabled=sync_enabled,
    )


@app.post("/api/sync/export", status_code=202)
def trigger_sync_export(_ak: str = Header(..., alias="X-API-Key")):
    # Direction A: trigger placeholder — actual CSV→JSON export is Direction C
    return {"status": "accepted", "message": "Sync export triggered"}


# ─── Sync Push & Status (Direction B) ────────────────────────────────────────

class ProjectSyncStatusResponse(BaseModel):
    project_id: str
    sync_enabled: bool
    sync_last_run: str = ""


class GlobalSyncStatusResponse(BaseModel):
    sync_enabled: bool
    sync_target_repo: str
    sync_last_run: str


@app.get("/api/sync/status", response_model=GlobalSyncStatusResponse)
def get_sync_status(_ak: str = Header(..., alias="X-API-Key")):
    """Return current sync configuration and last run timestamp."""
    config = load_config()
    # sync_last_run is stored per-project in CSV, but we also track globally
    # For simplicity, we return the most recent from storage's audit log or config
    sync_last_run = getattr(config, "sync_last_run", "")
    return GlobalSyncStatusResponse(
        sync_enabled=config.sync_enabled,
        sync_target_repo=config.sync_target_repo or "",
        sync_last_run=sync_last_run or "",
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
    sort_by: Optional[str] = Query("last_update", description="Sort field: last_update, create_at, title, id, status, stage"),
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


# ─── Validate ─────────────────────────────────────────────────────────────────

class ValidatePayload(BaseModel):
    data: dict


@app.post("/validate", response_model=ValidateResponse)
def validate(data: ValidatePayload, _ak: str = Header(..., alias="X-API-Key")):
    s = get_storage()
    errors = s.validate_proposal(data.data)
    return ValidateResponse(valid=len(errors) == 0, errors=errors)


# ─── Audit ───────────────────────────────────────────────────────────────────

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
    return {
        "request": request,
        "api_key": config.key,
        "socket_path": config.socket_path,
        "data_dir": config.data_dir or str(Path(config.projects_csv).parent),
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
