"""Tests for ai_superpower models — enum validation and state machine."""
import pytest
from pydantic import ValidationError

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai_superpower.models import (
    PROJECT_ID_PATTERN,
    PROPOSAL_ID_PATTERN,
    VALID_PROPOSAL_STATUSES,
    VALID_PROPOSAL_STAGES,
    VALID_ENUMS,
    STATUS_TRANSITIONS,
    ProjectCreate,
    ProjectUpdate,
    ProposalCreate,
    ProposalUpdate,
    ProposalStatusUpdate,
)


# ─── ID Format ────────────────────────────────────────────────────────────────

class TestProjectIdFormat:
    def test_valid_prj_id(self):
        assert PROJECT_ID_PATTERN.match("PRJ-20260523-001")

    def test_invalid_prj_id_wrong_prefix(self):
        with pytest.raises(ValidationError) as exc_info:
            ProjectCreate(project_id="P-20260523-001")  # Wrong prefix
        assert "project_id" in str(exc_info.value)

    def test_invalid_prj_id_no_date(self):
        with pytest.raises(ValidationError) as exc_info:
            ProjectCreate(project_id="PRJ-20260523001")  # Missing dashes
        assert "project_id" in str(exc_info.value)


class TestProposalIdFormat:
    def test_valid_proposal_id(self):
        assert PROPOSAL_ID_PATTERN.match("P-20260523-001")

    def test_invalid_proposal_id(self):
        assert not PROPOSAL_ID_PATTERN.match("PRJ-20260523-001")  # Wrong prefix


# ─── Proposal Stage Enum ─────────────────────────────────────────────────────

class TestProposalStageEnum:
    def test_valid_stage(self):
        p = ProposalCreate(
            title="Test",
            owner="boss",
            project_id="PRJ-20260523-001",
            stage="ideation",
        )
        assert p.stage == "ideation"

    def test_invalid_stage(self):
        with pytest.raises(ValidationError) as exc_info:
            ProposalCreate(
                title="Test",
                owner="boss",
                project_id="PRJ-20260523-001",
                stage="invalid_stage",
            )
        assert "stage" in str(exc_info.value).lower()


# ─── Proposal Status Enum ────────────────────────────────────────────────────

class TestProposalStatusEnum:
    def test_valid_status(self):
        s = ProposalStatusUpdate(status="intake")
        assert s.status == "intake"

    def test_invalid_status(self):
        with pytest.raises(ValidationError) as exc_info:
            ProposalStatusUpdate(status="invalid_status")
        assert "status" in str(exc_info.value).lower()


# ─── Enum Fields ─────────────────────────────────────────────────────────────

class TestEnumFields:
    @pytest.mark.parametrize("field,valid", [
        ("prd_confirmation", ["pending", "confirmed", "timeout-approved", "rejected", ""]),
        ("tech_expectations", ["pending", "confirmed", "timeout-approved", ""]),
        ("acceptance", ["pending", "accepted", "rejected", ""]),
    ])
    def test_valid_enum_fields(self, field, valid):
        kwargs = {
            "title": "Test",
            "owner": "boss",
            "project_id": "PRJ-20260523-001",
            "stage": "ideation",
            field: valid[0],
        }
        p = ProposalCreate(**kwargs)
        assert getattr(p, field) == valid[0]

    def test_game_type_valid(self):
        p = ProposalCreate(
            title="Test",
            owner="boss",
            project_id="PRJ-20260523-001",
            stage="ideation",
            game_type="策略",
        )
        assert p.game_type == "策略"


# ─── Status State Machine ─────────────────────────────────────────────────────

class TestStatusStateMachine:
    """Test that STATUS_TRANSITIONS covers all valid statuses."""
    
    def test_all_valid_statuses_have_transitions(self):
        for status in VALID_PROPOSAL_STATUSES:
            assert status in STATUS_TRANSITIONS, f"{status} has no transition entry"

    def test_intake_only_goes_to_clarifying(self):
        allowed = STATUS_TRANSITIONS["intake"]
        assert allowed == {"clarifying"}

    def test_clarifying_only_goes_to_prd_pending(self):
        allowed = STATUS_TRANSITIONS["clarifying"]
        assert allowed == {"prd_pending_confirmation"}

    def test_approved_for_dev_can_go_to_tdd_test_or_dev(self):
        allowed = STATUS_TRANSITIONS["approved_for_dev"]
        assert allowed == {"in_tdd_test", "in_dev"}

    def test_in_dev_allowed_transitions(self):
        allowed = STATUS_TRANSITIONS["in_dev"]
        assert allowed == {"in_test_acceptance", "needs_revision"}

    def test_in_test_acceptance_allowed(self):
        allowed = STATUS_TRANSITIONS["in_test_acceptance"]
        assert allowed == {"accepted", "test_failed"}

    def test_accepted_only_goes_to_deployed(self):
        allowed = STATUS_TRANSITIONS["accepted"]
        assert allowed == {"deployed"}

    def test_deployed_only_goes_to_delivered(self):
        allowed = STATUS_TRANSITIONS["deployed"]
        assert allowed == {"delivered"}

    def test_active_stays_active(self):
        allowed = STATUS_TRANSITIONS["active"]
        assert allowed == {"active"}

    def test_archived_stays_archived(self):
        allowed = STATUS_TRANSITIONS["archived"]
        assert allowed == {"archived"}

    def test_needs_revision_goes_to_in_dev(self):
        allowed = STATUS_TRANSITIONS["needs_revision"]
        assert allowed == {"in_dev"}

    def test_test_failed_goes_to_in_dev(self):
        allowed = STATUS_TRANSITIONS["test_failed"]
        assert allowed == {"in_dev"}

    def test_deploying_goes_to_deployed(self):
        allowed = STATUS_TRANSITIONS["deploying"]
        assert allowed == {"deployed"}

    def test_research_direction_pending_goes_to_intake(self):
        allowed = STATUS_TRANSITIONS["research_direction_pending"]
        assert allowed == {"intake"}

    def test_delivered_stays_delivered(self):
        allowed = STATUS_TRANSITIONS["delivered"]
        assert allowed == {"delivered"}

    def test_prd_pending_confirmation_valid_transition(self):
        allowed = STATUS_TRANSITIONS["prd_pending_confirmation"]
        assert "approved_for_dev" in allowed

    def test_in_tdd_test_valid_transition(self):
        allowed = STATUS_TRANSITIONS["in_tdd_test"]
        assert "in_dev" in allowed


# ─── ProjectUpdate ────────────────────────────────────────────────────────────

class TestProjectUpdate:
    def test_partial_update_all_none(self):
        u = ProjectUpdate()
        assert u.name is None

    def test_partial_update_name_only(self):
        u = ProjectUpdate(name="New Name")
        assert u.name == "New Name"
        assert u.git_repo is None

    def test_update_empty_string_rejected_for_name(self):
        # name has min_length=1, so "" is rejected
        with pytest.raises(ValidationError):
            ProjectUpdate(name="")


# ─── ProposalUpdate ──────────────────────────────────────────────────────────

class TestProposalUpdate:
    def test_update_stage_valid(self):
        u = ProposalUpdate(stage="development")
        assert u.stage == "development"

    def test_update_stage_invalid(self):
        with pytest.raises(ValidationError):
            ProposalUpdate(stage="not_a_stage")

    def test_update_multiple_fields(self):
        u = ProposalUpdate(
            title="New Title",
            owner="alice",
            stage="development",
        )
        assert u.title == "New Title"
        assert u.owner == "alice"
        assert u.stage == "development"

    def test_update_id_not_in_model(self):
        # ProposalUpdate doesn't have an id field
        u = ProposalUpdate(title="X")
        assert "id" not in u.model_fields
