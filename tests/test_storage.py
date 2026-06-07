"""Tests for ai_superpower CSV storage layer."""
import csv
import json
import os
import pytest
import tempfile
import hashlib
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai_superpower.models import PROJECTS_CSV_HEADERS, PROPOSALS_CSV_HEADERS
from ai_superpower.config import APIConfig


class TempStorageConfig:
    """ Ephemeral config for tests — uses temp files. """
    def __init__(self, tmp_path):
        self.projects_csv = str(tmp_path / "projects.csv")
        self.proposals_csv = str(tmp_path / "proposals.csv")
        self.audit_log = str(tmp_path / "audit.log")
        self.key = "test-key-123"
        self.socket_path = str(tmp_path / "test.sock")


@pytest.fixture
def storage(tmp_path):
    from ai_superpower.storage import CSVStorage
    config = TempStorageConfig(tmp_path)
    s = CSVStorage(config, actor="test")
    # Create a test project so proposals can reference it
    s.create_project(name="Test Project", git_repo="", local_path="", description="")
    return s


# ─── Init & Files ─────────────────────────────────────────────────────────────

class TestStorageInit:
    def test_csv_files_created(self, tmp_path):
        from ai_superpower.storage import CSVStorage
        config = TempStorageConfig(tmp_path)
        s = CSVStorage(config, actor="test")
        assert os.path.exists(config.projects_csv)
        assert os.path.exists(config.proposals_csv)
        assert os.path.exists(config.audit_log)

    def test_audit_log_created(self, tmp_path):
        from ai_superpower.storage import CSVStorage
        config = TempStorageConfig(tmp_path)
        s = CSVStorage(config, actor="test")
        with open(config.audit_log) as f:
            content = f.read()
        assert content == ""


# ─── Projects CRUD ─────────────────────────────────────────────────────────────

class TestProjectCrud:
    def test_create_project(self, storage):
        proj = storage.create_project(name="New Project", git_repo="https://github.com/test/test")
        assert proj.id.startswith("PRJ-")
        assert proj.name == "New Project"
        assert proj.git_repo == "https://github.com/test/test"

    def test_list_projects(self, storage):
        projects, total = storage.list_projects()
        assert total >= 1  # fixture creates one

    def test_list_projects_pagination(self, storage):
        for i in range(5):
            storage.create_project(name=f"Project {i}")
        items, total = storage.list_projects(page=1, page_size=2)
        assert len(items) == 2
        assert total >= 6

    def test_list_projects_search(self, storage):
        storage.create_project(name="Alpha Project")
        storage.create_project(name="Beta Project")
        items, total = storage.list_projects(search="alpha")
        assert total == 1
        assert items[0].name == "Alpha Project"

    def test_get_project(self, storage):
        created = storage.create_project(name="Get Me")
        fetched = storage.get_project(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == "Get Me"

    def test_get_project_not_found(self, storage):
        result = storage.get_project("PRJ-20991231-999")
        assert result is None

    def test_update_project(self, storage):
        proj = storage.create_project(name="Old Name")
        updated = storage.update_project(proj.id, {"name": "New Name"})
        assert updated.name == "New Name"

    def test_update_project_multiple_fields(self, storage):
        proj = storage.create_project(name="Old")
        updated = storage.update_project(proj.id, {
            "name": "New",
            "description": "A description",
        })
        assert updated.name == "New"
        assert updated.description == "A description"

    def test_update_nonexistent_project(self, storage):
        result = storage.update_project("PRJ-20991231-999", {"name": "X"})
        assert result is None

    def test_delete_project(self, storage):
        proj = storage.create_project(name="To Delete")
        deleted = storage.delete_project(proj.id)
        assert deleted is True
        assert storage.get_project(proj.id) is None

    def test_delete_project_with_proposals_fails(self, storage):
        projects, _ = storage.list_projects()
        proj = projects[0]
        storage.create_proposal({
            "title": "Test",
            "owner": "boss",
            "project_id": proj.id,
            "stage": "ideation",
        })
        with pytest.raises(ValueError) as exc_info:
            storage.delete_project(proj.id)
        assert "has proposals" in str(exc_info.value)

    def test_project_id_auto_increment(self, storage):
        today_prefix = "PRJ-"
        p1 = storage.create_project(name="A")
        p2 = storage.create_project(name="B")
        assert p1.id != p2.id


# ─── Proposals CRUD ───────────────────────────────────────────────────────────

class TestProposalCrud:
    def test_create_proposal(self, storage):
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({
            "title": "My Proposal",
            "owner": "boss",
            "project_id": proj.id,
            "stage": "ideation",
        })
        assert prop.id.startswith("P-")
        assert prop.title == "My Proposal"
        assert prop.owner == "boss"
        assert prop.status == "intake"

    def test_create_proposal_auto_id_increment(self, storage):
        proj = storage.list_projects()[0][0]
        p1 = storage.create_proposal({"title": "A", "owner": "boss", "project_id": proj.id, "stage": "ideation"})
        p2 = storage.create_proposal({"title": "B", "owner": "boss", "project_id": proj.id, "stage": "ideation"})
        assert p1.id != p2.id

    def test_list_proposals(self, storage):
        proj = storage.list_projects()[0][0]
        storage.create_proposal({"title": "List Me", "owner": "boss", "project_id": proj.id, "stage": "ideation"})
        proposals, total = storage.list_proposals()
        assert total >= 1

    def test_list_proposals_filter_project_id(self, storage):
        proj1 = storage.list_projects()[0][0]
        proj2 = storage.create_project(name="Proj2")
        storage.create_proposal({"title": "For Proj1", "owner": "boss", "project_id": proj1.id, "stage": "ideation"})
        storage.create_proposal({"title": "For Proj2", "owner": "boss", "project_id": proj2.id, "stage": "ideation"})
        items, total = storage.list_proposals(project_id=proj2.id)
        assert total == 1
        assert items[0].title == "For Proj2"

    def test_list_proposals_filter_status(self, storage):
        proj = storage.list_projects()[0][0]
        p1 = storage.create_proposal({"title": "P1", "owner": "boss", "project_id": proj.id, "stage": "ideation"})
        storage.update_proposal_status(p1.id, "clarifying")
        items, total = storage.list_proposals(status="clarifying")
        assert total >= 1
        assert items[0].status == "clarifying"

    def test_list_proposals_search(self, storage):
        proj = storage.list_projects()[0][0]
        storage.create_proposal({"title": "Search Target", "owner": "boss", "project_id": proj.id, "stage": "ideation"})
        items, total = storage.list_proposals(search="search target")
        assert total == 1
        assert items[0].title == "Search Target"

    def test_list_proposals_pagination(self, storage):
        proj = storage.list_projects()[0][0]
        for i in range(5):
            storage.create_proposal({"title": f"Prop {i}", "owner": "boss", "project_id": proj.id, "stage": "ideation"})
        items, total = storage.list_proposals(page=1, page_size=2)
        assert len(items) == 2
        assert total >= 5

    def test_get_proposal(self, storage):
        proj = storage.list_projects()[0][0]
        created = storage.create_proposal({"title": "Get Me", "owner": "boss", "project_id": proj.id, "stage": "ideation"})
        fetched = storage.get_proposal(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    def test_get_proposal_not_found(self, storage):
        result = storage.get_proposal("P-20991231-999")
        assert result is None

    def test_update_proposal(self, storage):
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "Old Title", "owner": "boss", "project_id": proj.id, "stage": "ideation"})
        updated = storage.update_proposal(prop.id, {"title": "New Title"})
        assert updated.title == "New Title"

    def test_update_proposal_id_rejected(self, storage):
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "X", "owner": "boss", "project_id": proj.id, "stage": "ideation"})
        updated = storage.update_proposal(prop.id, {"id": "P-20991231-999"})
        assert updated.id == prop.id  # id field is ignored

    def test_delete_proposal(self, storage):
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "Delete Me", "owner": "boss", "project_id": proj.id, "stage": "ideation"})
        deleted = storage.delete_proposal(prop.id)
        assert deleted is True
        assert storage.get_proposal(prop.id) is None

    def test_delete_nonexistent_proposal(self, storage):
        result = storage.delete_proposal("P-20991231-999")
        assert result is False


# ─── Status State Machine ───────────────────────────────────────────────────

class TestStatusStateMachine:
    def test_valid_status_transition_intake_to_clarifying(self, storage):
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "X", "owner": "boss", "project_id": proj.id, "stage": "ideation"})
        assert prop.status == "intake"
        updated = storage.update_proposal_status(prop.id, "clarifying")
        assert updated.status == "clarifying"

    def test_invalid_status_transition(self, storage):
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "X", "owner": "boss", "project_id": proj.id, "stage": "ideation"})
        with pytest.raises(ValueError) as exc_info:
            storage.update_proposal_status(prop.id, "accepted")  # Can't jump
        assert "Invalid status transition" in str(exc_info.value)

    def test_full_happy_path(self, storage):
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "Happy Path", "owner": "boss", "project_id": proj.id, "stage": "ideation"})
        assert prop.status == "intake"
        prop = storage.update_proposal_status(prop.id, "clarifying")
        assert prop.status == "clarifying"
        prop = storage.update_proposal_status(prop.id, "prd_pending_confirmation")
        assert prop.status == "prd_pending_confirmation"
        prop = storage.update_proposal_status(prop.id, "approved_for_dev")
        assert prop.status == "approved_for_dev"
        prop = storage.update_proposal_status(prop.id, "in_dev")
        assert prop.status == "in_dev"
        prop = storage.update_proposal_status(prop.id, "in_test_acceptance")
        assert prop.status == "in_test_acceptance"
        prop = storage.update_proposal_status(prop.id, "accepted")
        assert prop.status == "accepted"

    def test_needs_revision_to_in_dev(self, storage):
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "X", "owner": "boss", "project_id": proj.id, "stage": "ideation"})
        storage.update_proposal_status(prop.id, "clarifying")
        storage.update_proposal_status(prop.id, "prd_pending_confirmation")
        storage.update_proposal_status(prop.id, "approved_for_dev")
        storage.update_proposal_status(prop.id, "in_dev")
        prop = storage.update_proposal_status(prop.id, "needs_revision")
        assert prop.status == "needs_revision"
        prop = storage.update_proposal_status(prop.id, "in_dev")
        assert prop.status == "in_dev"

    def test_test_failed_to_in_dev(self, storage):
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "X", "owner": "boss", "project_id": proj.id, "stage": "ideation"})
        for s in ["clarifying", "prd_pending_confirmation", "approved_for_dev", "in_dev", "in_test_acceptance"]:
            prop = storage.update_proposal_status(prop.id, s)
        prop = storage.update_proposal_status(prop.id, "test_failed")
        assert prop.status == "test_failed"
        prop = storage.update_proposal_status(prop.id, "in_dev")
        assert prop.status == "in_dev"


# ─── Status Auto-Derivation from Business Fields ───────────────────────────
# update_proposal() should auto-advance status when business fields change,
# so legacy call sites that only updated stage/acceptance don't leave
# status stuck at "intake".

class TestStatusAutoDerivation:
    """Verify update_proposal() advances status when business fields change."""

    def test_stage_ideation_sets_status_ideation(self, storage):
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "X", "owner": "boss", "project_id": proj.id})
        assert prop.status == "intake"
        updated = storage.update_proposal(prop.id, {"stage": "ideation"})
        assert updated.status == "ideation"
        assert updated.stage == "ideation"

    def test_prd_confirmation_pending_advances_status(self, storage):
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "X", "owner": "boss", "project_id": proj.id})
        # Need to walk to clarifying first (intake → clarifying is the only way)
        prop = storage.update_proposal_status(prop.id, "clarifying")
        updated = storage.update_proposal(prop.id, {"prd_confirmation": "pending"})
        assert updated.status == "prd_pending_confirmation"

    def test_prd_confirmation_confirmed_advances_to_approved(self, storage):
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "X", "owner": "boss", "project_id": proj.id})
        storage.update_proposal_status(prop.id, "clarifying")
        storage.update_proposal(prop.id, {"prd_confirmation": "pending"})
        updated = storage.update_proposal(prop.id, {"prd_confirmation": "confirmed"})
        assert updated.status == "approved_for_dev"

    def test_stage_approved_for_dev_advances_from_prd_pending(self, storage):
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "X", "owner": "boss", "project_id": proj.id})
        storage.update_proposal_status(prop.id, "clarifying")
        storage.update_proposal(prop.id, {"prd_confirmation": "pending"})
        # Now at prd_pending_confirmation
        updated = storage.update_proposal(prop.id, {"stage": "approved_for_dev"})
        assert updated.status == "approved_for_dev"

    def test_stage_development_advances_to_in_dev(self, storage):
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "X", "owner": "boss", "project_id": proj.id})
        storage.update_proposal_status(prop.id, "clarifying")
        storage.update_proposal(prop.id, {"prd_confirmation": "pending"})
        storage.update_proposal(prop.id, {"prd_confirmation": "confirmed"})
        updated = storage.update_proposal(prop.id, {"stage": "development"})
        assert updated.status == "in_dev"

    def test_acceptance_accepted_advances_to_accepted(self, storage):
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "X", "owner": "boss", "project_id": proj.id})
        # Walk through the state machine
        storage.update_proposal_status(prop.id, "clarifying")
        storage.update_proposal(prop.id, {"prd_confirmation": "pending"})
        storage.update_proposal(prop.id, {"prd_confirmation": "confirmed"})
        storage.update_proposal(prop.id, {"stage": "development"})
        storage.update_proposal_status(prop.id, "in_test_acceptance")
        updated = storage.update_proposal(prop.id, {"acceptance": "accepted"})
        assert updated.status == "accepted"

    def test_explicit_status_in_update_skips_auto_derive(self, storage):
        """If caller passes status explicitly, auto-derive must NOT override it."""
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "X", "owner": "boss", "project_id": proj.id})
        # Set business field AND status — user's status wins
        updated = storage.update_proposal(prop.id, {"stage": "development", "status": "clarifying"})
        assert updated.status == "clarifying"
        assert updated.stage == "development"

    def test_business_field_drives_status_even_from_intake(self, storage):
        """Business fields are ground truth — auto-derive syncs status
        to match even when the state machine would forbid the transition.
        This reflects legacy data where business fields (stage, acceptance)
        were set ahead of status — auto-derive corrects the lag."""
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "X", "owner": "boss", "project_id": proj.id})
        # acceptance=accepted is set directly. status should follow.
        updated = storage.update_proposal(prop.id, {"acceptance": "accepted"})
        assert updated.status == "accepted"  # business field wins
        assert updated.acceptance == "accepted"

    def test_unrelated_field_update_does_not_change_status(self, storage):
        """title/notes changes should not trigger status derivation."""
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "Original", "owner": "boss", "project_id": proj.id})
        assert prop.status == "intake"
        updated = storage.update_proposal(prop.id, {"title": "Renamed", "notes": "extra"})
        assert updated.status == "intake"
        assert updated.title == "Renamed"

    def test_existing_state_machine_still_works(self, storage):
        """Regression: explicit update_proposal_status() path must still validate."""
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "X", "owner": "boss", "project_id": proj.id})
        # This should still raise on illegal transition
        import pytest
        with pytest.raises(ValueError):
            storage.update_proposal_status(prop.id, "accepted")  # intake → accepted illegal

    def test_derive_helper_pure_function(self):
        """Sanity check the pure helper used by storage layer."""
        from ai_superpower.models import derive_status_from_fields
        # No business fields → no derive
        assert derive_status_from_fields({}) is None
        # stage=approved_for_dev
        assert derive_status_from_fields({"stage": "approved_for_dev"}) == "approved_for_dev"
        # acceptance=accepted wins (later rule)
        row = {"stage": "approved_for_dev", "acceptance": "accepted"}
        assert derive_status_from_fields(row) == "accepted"
        # deployment_url only triggers if acceptance=accepted
        assert derive_status_from_fields({"deployment_url": "https://x"}) is None
        assert derive_status_from_fields({"deployment_url": "https://x", "acceptance": "accepted"}) == "delivered"


# ─── Coverage Boosters for Edge Cases ──────────────────────────────────────
# Tests targeting specific storage.py lines that were uncovered to push
# coverage above 99%. Each test name mentions the target line.

class TestEdgeCases:
    """Cover error paths and filter branches in storage.py."""

    def test_list_proposals_filter_by_owner(self, storage):
        """storage.py line 289 — owner filter branch."""
        proj = storage.list_projects()[0][0]
        storage.create_proposal({"title": "A", "owner": "alice", "project_id": proj.id})
        storage.create_proposal({"title": "B", "owner": "bob", "project_id": proj.id})
        # Filter by owner
        props, total = storage.list_proposals(owner="alice")
        assert total == 1
        assert all(p.owner == "alice" for p in props)

    def test_list_proposals_filter_by_stage(self, storage):
        """storage.py line 291 — stage filter branch."""
        proj = storage.list_projects()[0][0]
        storage.create_proposal({"title": "A", "owner": "x", "project_id": proj.id, "stage": "ideation"})
        storage.create_proposal({"title": "B", "owner": "x", "project_id": proj.id, "stage": "development"})
        # Filter by stage
        props, total = storage.list_proposals(stage="development")
        assert total == 1
        assert all(p.stage == "development" for p in props)

    def test_get_proposal_not_found(self, storage):
        """storage.py line 408 — get_proposal returns None for missing ID."""
        assert storage.get_proposal("P-20991231-999") is None

    def test_update_proposal_status_not_found(self, storage):
        """storage.py line 469 — update_proposal_status returns None for missing ID."""
        assert storage.update_proposal_status("P-20991231-999", "clarifying") is None

    def test_delete_project_not_found(self, storage):
        """storage.py line 240 — delete_project returns False for missing ID."""
        assert storage.delete_project("PRJ-20991231-999") is False

    def test_update_proposal_not_found(self, storage):
        """storage.py line 408 — update_proposal returns None for missing ID."""
        assert storage.update_proposal("P-20991231-999", {"title": "X"}) is None

    def test_sync_project_count_empty_id(self, storage):
        """storage.py line 512 — _sync_project_proposal_count returns on empty project_id."""
        # Should not raise even with empty project_id
        storage._sync_project_proposal_count("")
        assert True  # no exception = pass

    def test_auto_backup_empty_id(self, storage):
        """storage.py line 523 — _auto_backup_if_needed returns on empty project_id."""
        # Should not raise even with empty project_id
        storage._auto_backup_if_needed("")
        assert True

    def test_id_to_date_extraction(self, storage):
        """storage.py lines 555-558 — _id_to_date extracts YYYY-MM-DD from proposal ID."""
        from ai_superpower.storage import _ID_DATE_RE
        import re
        # The static method is private; replicate the regex
        d = storage._id_to_date("P-20260607-001")
        assert d == "2026-06-07"
        d2 = storage._id_to_date("PRJ-20260607-002")
        assert d2 == "2026-06-07"
        # Invalid ID returns None
        assert storage._id_to_date("INVALID") is None
        assert storage._id_to_date("") is None

    def test_audit_log_list_empty_file(self, storage, tmp_path):
        """storage.py line 630 — list_audit returns ([], 0) when audit log doesn't exist."""
        from ai_superpower.config import APIConfig
        # Create storage with non-existent audit log
        fake_config = type("Cfg", (), {
            "projects_csv": str(tmp_path / "p.csv"),
            "proposals_csv": str(tmp_path / "pr.csv"),
            "audit_log": str(tmp_path / "nonexistent.log"),
            "key": "k",
            "socket_path": str(tmp_path / "s.sock"),
        })()
        from ai_superpower.storage import CSVStorage
        s = CSVStorage(fake_config)
        # Remove the audit log that __init__ may have created
        import os
        if os.path.exists(fake_config.audit_log):
            os.remove(fake_config.audit_log)
        entries, total = s.list_audit()
        assert entries == []
        assert total == 0

    def test_audit_log_skips_invalid_json(self, storage, tmp_path):
        """storage.py lines 639-646 — list_audit skips malformed JSON lines."""
        from ai_superpower.storage import CSVStorage
        fake_config = type("Cfg", (), {
            "projects_csv": str(tmp_path / "p.csv"),
            "proposals_csv": str(tmp_path / "pr.csv"),
            "audit_log": str(tmp_path / "audit_mixed.log"),
            "key": "k",
            "socket_path": str(tmp_path / "s.sock"),
        })()
        # Write a mix of valid and invalid lines
        with open(fake_config.audit_log, "w") as f:
            f.write('{"op": "CREATE", "entity": "project", "id": "P-1"}\n')
            f.write('this is not json\n')  # invalid — should be skipped
            f.write('{"op": "UPDATE", "entity": "proposal", "id": "P-2"}\n')
            f.write('\n')  # empty line — should be skipped
        s = CSVStorage(fake_config)
        entries, total = s.list_audit()
        assert total == 2  # only valid JSON lines
        assert entries[0]["id"] == "P-1"
        assert entries[1]["id"] == "P-2"

    def test_validate_proposal_invalid_project_id(self, storage):
        """storage.py line 660 — validate_proposal catches invalid project_id format."""
        errors = storage.validate_proposal({
            "title": "X",
            "project_id": "INVALID",
            "stage": "ideation",
        })
        assert any("project_id" in e for e in errors)

    def test_validate_proposal_invalid_project_id_in_lookup(self, storage):
        """storage.py line 683 — validate_project catches invalid project_id (in lookup)."""
        errors = storage.validate_project({
            "project_id": "INVALID",
            "name": "X",
        })
        assert any("project_id" in e for e in errors)

    def test_validate_project_missing_name(self, storage):
        """storage.py line 686 — validate_project requires name field."""
        errors = storage.validate_project({})  # no name
        assert any("name" in e.lower() for e in errors)

    def test_list_audit_entity_filter(self, storage, tmp_path):
        """storage.py lines 642-646 — list_audit filters by entity_id/op/entity."""
        from ai_superpower.storage import CSVStorage
        fake_config = type("Cfg", (), {
            "projects_csv": str(tmp_path / "p.csv"),
            "proposals_csv": str(tmp_path / "pr.csv"),
            "audit_log": str(tmp_path / "audit_filter.log"),
            "key": "k",
            "socket_path": str(tmp_path / "s.sock"),
        })()
        with open(fake_config.audit_log, "w") as f:
            f.write('{"op": "CREATE", "entity": "project", "id": "P-1"}\n')
            f.write('{"op": "UPDATE", "entity": "proposal", "id": "P-2"}\n')
            f.write('{"op": "DELETE", "entity": "proposal", "id": "P-3"}\n')
        s = CSVStorage(fake_config)
        # Filter by entity_id
        entries, _ = s.list_audit(entity_id="P-2")
        assert len(entries) == 1
        # Filter by op
        entries, _ = s.list_audit(op="DELETE")
        assert len(entries) == 1
        # Filter by entity
        entries, _ = s.list_audit(entity="proposal")
        assert len(entries) == 2

    def test_project_created_date_falls_back_to_id(self, storage, tmp_path):
        """storage.py line 565 — _project_created_date falls back to ID date extraction."""
        from ai_superpower.storage import CSVStorage
        # create_at empty → fall through to _id_to_date
        result = CSVStorage._project_created_date({"id": "PRJ-20260607-001", "create_at": ""})
        assert result == "2026-06-07"
        # create_at present → use it directly
        result2 = CSVStorage._project_created_date({"id": "PRJ-20991231-999", "create_at": "2025-01-01"})
        assert result2 == "2025-01-01"


class TestModelValidationEdgeCases:
    """Cover models.py edge cases — line 180 (project_id validator raise)."""

    def test_project_id_format_validator_raises(self):
        """models.py line 180 — invalid project_id format raises ValueError.

        The validator is on ProposalCreate, not Proposal, so we instantiate
        ProposalCreate with an invalid project_id.
        """
        from ai_superpower.models import ProposalCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError) as exc:
            ProposalCreate(title="X", owner="x", project_id="INVALID", stage="ideation")
        assert "project_id" in str(exc.value).lower() or "PRJ-" in str(exc.value)


# ─── Audit Logging ───────────────────────────────────────────────────────────

class TestAuditLogging:
    def test_audit_log_after_create(self, storage, tmp_path):
        config = storage.config
        proj = storage.create_project(name="Audit Me")
        with open(config.audit_log, "r") as f:
            entries = [json.loads(line) for line in f if line.strip()]
        assert len(entries) >= 1
        assert entries[-1]["op"] == "CREATE"
        assert entries[-1]["entity"] == "project"
        assert entries[-1]["id"] == proj.id
        assert entries[-1]["checksum_after"] is not None

    def test_audit_log_sha记录(self, storage, tmp_path):
        config = storage.config
        storage.create_project(name="SHA Test")
        with open(config.audit_log, "r") as f:
            lines = [line.strip() for line in f if line.strip()]
        import re
        # JSON format: checksum_after is a full SHA256 hex
        sha_pattern = re.search(r'[0-9a-f]{64}', lines[-1])
        assert sha_pattern is not None


# ─── Proposal Count Sync ─────────────────────────────────────────────────────

class TestProposalCountSync:
    def test_proposal_count_increments(self, storage):
        proj = storage.list_projects()[0][0]
        initial_count = storage.get_project(proj.id).proposal_count
        storage.create_proposal({"title": "Count Test", "owner": "boss", "project_id": proj.id, "stage": "ideation"})
        updated_proj = storage.get_project(proj.id)
        assert updated_proj.proposal_count == initial_count + 1

    def test_proposal_count_decrements_on_delete(self, storage):
        proj = storage.list_projects()[0][0]
        prop = storage.create_proposal({"title": "Delete Count", "owner": "boss", "project_id": proj.id, "stage": "ideation"})
        before = storage.get_project(proj.id).proposal_count
        storage.delete_proposal(prop.id)
        after = storage.get_project(proj.id).proposal_count
        assert after == before - 1


# ─── Validation ─────────────────────────────────────────────────────────────

class TestValidation:
    def test_validate_proposal_invalid_project_id(self, storage):
        errors = storage.validate_proposal({
            "title": "X",
            "owner": "boss",
            "project_id": "PRJ-20991231-999",
            "stage": "ideation",
        })
        assert any("does not exist" in e for e in errors)

    def test_validate_proposal_invalid_stage(self, storage):
        proj = storage.list_projects()[0][0]
        errors = storage.validate_proposal({
            "title": "X",
            "owner": "boss",
            "project_id": proj.id,
            "stage": "not_a_stage",
        })
        assert any("Invalid stage" in e for e in errors)

    def test_validate_proposal_invalid_enum_field(self, storage):
        proj = storage.list_projects()[0][0]
        errors = storage.validate_proposal({
            "title": "X",
            "owner": "boss",
            "project_id": proj.id,
            "stage": "ideation",
            "prd_confirmation": "invalid_value",
        })
        assert any("Invalid prd_confirmation" in e for e in errors)


# ─── File Integrity (SHA256) ─────────────────────────────────────────────────

class TestFileIntegrity:
    def test_sha_changes_after_write(self, storage, tmp_path):
        config = storage.config
        sha_before = storage._sha256(config.projects_csv)
        storage.create_project(name="Integrity Test")
        sha_after = storage._sha256(config.projects_csv)
        assert sha_before != sha_after

    def test_sha_same_without_changes(self, storage, tmp_path):
        config = storage.config
        sha_before = storage._sha256(config.projects_csv)
        # Read-only operation
        storage.list_projects()
        sha_after = storage._sha256(config.projects_csv)
        assert sha_before == sha_after
