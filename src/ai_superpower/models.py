"""Data models and schemas for ai-superpower."""
import re
from datetime import date
from typing import Optional
from pydantic import BaseModel, Field, field_validator

# ─── ID Patterns ────────────────────────────────────────────────────────────

PROJECT_ID_PATTERN = re.compile(r"^PRJ-\d{8}-\d{3}$")
PROPOSAL_ID_PATTERN = re.compile(r"^P-\d{8}-\d{3}$")

# ─── Enums ───────────────────────────────────────────────────────────────────

VALID_PROPOSAL_STATUSES = {
    "intake", "clarifying", "prd_pending_confirmation", "approved_for_dev",
    "in_tdd_test", "in_dev", "in_test_acceptance", "test_failed",
    "accepted", "needs_revision", "deployed", "deploying",
    "research_direction_pending", "active", "archived", "delivered",
}
VALID_PROPOSAL_STAGES = {
    "ideation", "development", "research", "proposal", "in_dev",
    "in_acceptance", "accepted", "delivered", "active",
    "approved_for_dev", "prd_pending_confirmation",
}
VALID_ENUMS = {
    "prd_confirmation": {"pending", "confirmed", "timeout-approved", "rejected", ""},
    "tech_expectations": {"pending", "confirmed", "timeout-approved", ""},
    "acceptance": {"pending", "accepted", "rejected", ""},
    "game_type": {"", "休闲", "策略", "卡牌", "RPG", "消除", "塔防", "模拟", "动作", "射击"},
}

# ─── Status State Machine ─────────────────────────────────────────────────────

STATUS_TRANSITIONS: dict[str, set[str]] = {
    "intake": {"clarifying", "ideation"},
    "ideation": {"intake", "clarifying", "prd_pending_confirmation"},
    "clarifying": {"prd_pending_confirmation"},
    "prd_pending_confirmation": {"approved_for_dev"},
    "approved_for_dev": {"in_tdd_test", "in_dev", "in_test_acceptance", "accepted"},
    "in_tdd_test": {"in_dev"},
    "in_dev": {"in_test_acceptance", "needs_revision"},
    "in_test_acceptance": {"accepted", "test_failed"},
    "test_failed": {"in_dev"},
    "needs_revision": {"in_dev"},
    "accepted": {"deployed", "delivered"},
    "deployed": {"delivered"},
    "deploying": {"deployed"},
    "research_direction_pending": {"intake"},
    "active": {"active"},
    "archived": {"archived"},
    "delivered": {"delivered"},
}


# ─── Status Derivation Rules ────────────────────────────────────────────────
# When update_proposal() is called with business fields (stage / prd_confirmation /
# tech_expectations / acceptance), this table maps (field, value) -> derived status.
# The derived status is applied ONLY if the current status can transition to it
# per STATUS_TRANSITIONS (silent skip on illegal transition — does not raise).
# Later rules override earlier ones, so order encodes "more advanced" stages last.

STATUS_DERIVE_RULES: list[tuple[str, str, str]] = [
    # Early phase
    ("stage", "ideation", "ideation"),
    ("prd_confirmation", "pending", "prd_pending_confirmation"),
    ("tech_expectations", "pending", "prd_pending_confirmation"),
    # Approval phase
    ("prd_confirmation", "confirmed", "approved_for_dev"),
    ("tech_expectations", "confirmed", "approved_for_dev"),
    ("stage", "approved_for_dev", "approved_for_dev"),
    # Dev phase
    ("stage", "development", "in_dev"),
    ("stage", "in_dev", "in_dev"),
    # Test/Accept phase
    ("stage", "in_acceptance", "in_test_acceptance"),
    ("stage", "in_test_acceptance", "in_test_acceptance"),
    ("acceptance", "pending", "in_test_acceptance"),
    # Final
    ("acceptance", "accepted", "accepted"),
    ("stage", "accepted", "accepted"),
    ("acceptance", "rejected", "needs_revision"),
    # Delivery
    ("stage", "delivered", "delivered"),
    ("deployment_url", "deployed", "delivered"),  # special: when URL set + accepted → delivered
]


def derive_status_from_fields(row: dict) -> Optional[str]:
    """Pure helper: given a proposal row dict, return the status that
    business fields suggest. Returns None if no rule matches.

    Multiple rules can match — the LAST matching rule wins (rules are
    ordered from least-advanced to most-advanced).
    """
    derived: Optional[str] = None
    for field, value, status in STATUS_DERIVE_RULES:
        if field == "deployment_url":
            # Special: deployment_url is non-empty + acceptance=accepted → delivered
            if row.get("acceptance") == "accepted" and row.get("deployment_url"):
                derived = status
        elif row.get(field) == value:
            derived = status
    return derived

# ─── CSV Field Names ─────────────────────────────────────────────────────────

PROJECTS_CSV_HEADERS = ["id", "name", "proposal_count", "git_repo", "local_path", "description", "last_update", "create_at", "prj_url", "sync_enabled", "sync_last_run"]
PROPOSALS_CSV_HEADERS = [
    "id", "title", "owner", "status", "project_id", "project_name", "stage",
    "prd_path", "tech_solution_path", "project_path", "git_repo", "deployment_url",
    "prd_confirmation", "tech_expectations", "acceptance", "last_update",
    "create_at", "update_at", "project_local_path",
    "engine", "target", "game_type", "notes",
]


# ─── Project Models ──────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    git_repo: Optional[str] = Field(default="")
    local_path: Optional[str] = Field(default="")
    description: Optional[str] = Field(default="")
    prj_url: Optional[str] = Field(default="")


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    git_repo: Optional[str] = None
    local_path: Optional[str] = None
    description: Optional[str] = None
    prj_url: Optional[str] = None
    sync_enabled: Optional[str] = None


class SyncSettings(BaseModel):
    sync_target_repo: str = ""
    sync_enabled: bool = False
    auto_sync_interval: int = 0  # 0=disabled, minutes


class Project(BaseModel):
    id: str
    name: str
    proposal_count: int = 0
    git_repo: str = ""
    local_path: str = ""
    description: str = ""
    last_update: str = ""
    create_at: str = ""
    prj_url: str = ""
    sync_enabled: str = "false"
    sync_last_run: str = ""


# ─── Proposal Models ─────────────────────────────────────────────────────────

class ProposalCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    owner: str = Field(..., min_length=1)
    project_id: str = Field(...)
    stage: str = Field(...)
    prd_path: Optional[str] = Field(default="")
    tech_solution_path: Optional[str] = Field(default="")
    project_path: Optional[str] = Field(default="")
    git_repo: Optional[str] = Field(default="")
    deployment_url: Optional[str] = Field(default="")
    prd_confirmation: Optional[str] = Field(default="")
    tech_expectations: Optional[str] = Field(default="")
    acceptance: Optional[str] = Field(default="")
    research_direction: Optional[str] = Field(default="")
    engine: Optional[str] = Field(default="")
    target: Optional[str] = Field(default="")
    game_type: Optional[str] = Field(default="")
    notes: Optional[str] = Field(default="")
    project_local_path: Optional[str] = Field(default="")

    @field_validator("project_id")
    @classmethod
    def project_id_format(cls, v: str) -> str:
        if not PROJECT_ID_PATTERN.match(v):
            raise ValueError(f"Invalid project_id format: {v}. Expected PRJ-YYYYMMDD-NNN")
        return v

    @field_validator("stage")
    @classmethod
    def stage_enum(cls, v: str) -> str:
        if v not in VALID_PROPOSAL_STAGES:
            raise ValueError(f"Invalid stage: {v}")
        return v


class ProposalUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    owner: Optional[str] = Field(default=None, min_length=1)
    stage: Optional[str] = None
    prd_path: Optional[str] = None
    tech_solution_path: Optional[str] = None
    project_path: Optional[str] = None
    git_repo: Optional[str] = None
    deployment_url: Optional[str] = None
    prd_confirmation: Optional[str] = None
    tech_expectations: Optional[str] = None
    acceptance: Optional[str] = None
    research_direction: Optional[str] = None
    engine: Optional[str] = None
    target: Optional[str] = None
    game_type: Optional[str] = None
    notes: Optional[str] = None
    project_local_path: Optional[str] = None

    @field_validator("stage")
    @classmethod
    def stage_enum(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_PROPOSAL_STAGES:
            raise ValueError(f"Invalid stage: {v}")
        return v


class ProposalStatusUpdate(BaseModel):
    status: str = Field(...)

    @field_validator("status")
    @classmethod
    def status_enum(cls, v: str) -> str:
        if v not in VALID_PROPOSAL_STATUSES:
            raise ValueError(f"Invalid status: {v}")
        return v


class Proposal(BaseModel):
    id: str
    title: str
    owner: str
    status: str
    project_id: str
    project_name: str = ""
    stage: str
    prd_path: str = ""
    tech_solution_path: str = ""
    project_path: str = ""
    git_repo: str = ""
    deployment_url: str = ""
    prd_confirmation: str = ""
    tech_expectations: str = ""
    acceptance: str = ""
    last_update: str = ""
    engine: str = ""
    target: str = ""
    game_type: str = ""
    notes: str = ""
    create_at: str = ""
    update_at: str = ""
    project_local_path: str = ""


# ─── Pagination ──────────────────────────────────────────────────────────────

class PageResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    total_pages: int