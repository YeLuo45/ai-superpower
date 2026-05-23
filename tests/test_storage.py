"""Tests for ai_superpower CSV storage layer."""
import csv
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
    s = CSVStorage(config)
    # Create a test project so proposals can reference it
    s.create_project(name="Test Project", git_repo="", local_path="", description="")
    return s


# ─── Init & Files ─────────────────────────────────────────────────────────────

class TestStorageInit:
    def test_csv_files_created(self, tmp_path):
        from ai_superpower.storage import CSVStorage
        config = TempStorageConfig(tmp_path)
        s = CSVStorage(config)
        assert os.path.exists(config.projects_csv)
        assert os.path.exists(config.proposals_csv)
        assert os.path.exists(config.audit_log)

    def test_audit_log_created(self, tmp_path):
        from ai_superpower.storage import CSVStorage
        config = TempStorageConfig(tmp_path)
        s = CSVStorage(config)
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


# ─── Audit Logging ───────────────────────────────────────────────────────────

class TestAuditLogging:
    def test_audit_log_after_create(self, storage, tmp_path):
        config = storage.config
        proj = storage.create_project(name="Audit Me")
        with open(config.audit_log, "r") as f:
            entries = f.readlines()
        assert len(entries) >= 1
        assert "CSV_WRITE" in entries[-1]
        assert config.projects_csv.split("/")[-1] in entries[-1]

    def test_audit_log_sha记录(self, storage, tmp_path):
        config = storage.config
        storage.create_project(name="SHA Test")
        with open(config.audit_log, "r") as f:
            entry = f.readlines()[-1]
        # Should contain sha pattern: 8 hex chars → 8 hex chars
        import re
        sha_pattern = re.search(r'[0-9a-f]{8}→[0-9a-f]{8}', entry)
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
