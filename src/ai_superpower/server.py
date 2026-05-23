"""FastAPI server for ai-superpower — API + Web UI."""
import hashlib
import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query, Response, Request
from fastapi.responses import HTMLResponse
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
    )


@app.get("/api/projects", response_model=PageResponse)
def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = None,
    _ak: str = Header(..., alias="X-API-Key"),
):
    s = get_storage()
    items, total = s.list_projects(page=page, page_size=page_size, search=search)
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
    _ak: str = Header(..., alias="X-API-Key"),
):
    s = get_storage()
    items, total = s.list_proposals(
        page=page, page_size=page_size,
        project_id=project_id, status=status,
        owner=owner, search=search, stage=stage,
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

@app.get("/", response_class=HTMLResponse)
def web_index(request: Request):
    return _templates.TemplateResponse("index.html", {"request": request})


@app.get("/web/projects", response_class=HTMLResponse)
def web_projects(request: Request):
    return _templates.TemplateResponse("projects/list.html", {"request": request})


@app.get("/web/proposals", response_class=HTMLResponse)
def web_proposals(request: Request):
    return _templates.TemplateResponse("proposals/list.html", {"request": request})


@app.get("/web/audit", response_class=HTMLResponse)
def web_audit(request: Request):
    return _templates.TemplateResponse("audit.html", {"request": request})


@app.get("/web/settings", response_class=HTMLResponse)
def web_settings(request: Request):
    return _templates.TemplateResponse("settings.html", {"request": request})
