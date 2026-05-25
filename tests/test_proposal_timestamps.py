"""Tests for proposal timestamps create_at/update_at (feature 4)."""
import pytest
import time
from datetime import datetime, timezone


class TestProposalTimestamps:
    """Test create_at and update_at on proposals."""

    def test_create_proposal_sets_create_at(self, storage):
        """create_proposal should set create_at to current UTC time."""
        project = storage.list_projects(page=1, page_size=1)[0][0]
        proposal = storage.create_proposal({
            "title": "Timestamp Test", "owner": "alice", "project_id": project.id,
            "stage": "ideation",
        })
        assert proposal.create_at is not None
        assert proposal.create_at != ""
        # Should be ISO8601 format
        dt = datetime.fromisoformat(proposal.create_at.replace("Z", "+00:00"))
        assert dt.tzinfo is not None

    def test_create_proposal_sets_update_at_equal_to_create_at(self, storage):
        """create_proposal should set update_at equal to create_at."""
        project = storage.list_projects(page=1, page_size=1)[0][0]
        proposal = storage.create_proposal({
            "title": "Timestamp Test 2", "owner": "alice", "project_id": project.id,
            "stage": "ideation",
        })
        assert proposal.update_at == proposal.create_at

    def test_update_proposal_updates_update_at(self, storage):
        """update_proposal should update update_at to current UTC time."""
        project = storage.list_projects(page=1, page_size=1)[0][0]
        proposal = storage.create_proposal({
            "title": "Update Timestamp Test", "owner": "alice", "project_id": project.id,
            "stage": "ideation",
        })
        original_update_at = proposal.update_at
        time.sleep(0.01)  # Small delay to ensure different timestamp
        updated = storage.update_proposal(proposal.id, {"title": "Updated Title"})
        assert updated.update_at != original_update_at
        # Both should be ISO8601
        dt = datetime.fromisoformat(updated.update_at.replace("Z", "+00:00"))
        assert dt.tzinfo is not None

    def test_create_at_remains_unchanged_on_update(self, storage):
        """create_at should not change when proposal is updated."""
        project = storage.list_projects(page=1, page_size=1)[0][0]
        proposal = storage.create_proposal({
            "title": "Keep CreateAt", "owner": "alice", "project_id": project.id,
            "stage": "ideation",
        })
        original_create_at = proposal.create_at
        time.sleep(0.01)
        updated = storage.update_proposal(proposal.id, {"title": "Changed Title"})
        assert updated.create_at == original_create_at

    def test_sort_by_create_at(self, storage):
        """list_proposals should support sorting by create_at."""
        project = storage.list_projects(page=1, page_size=1)[0][0]
        p1 = storage.create_proposal({
            "title": "First", "owner": "alice", "project_id": project.id,
            "stage": "ideation",
        })
        p2 = storage.create_proposal({
            "title": "Second", "owner": "bob", "project_id": project.id,
            "stage": "ideation",
        })
        proposals, _ = storage.list_proposals(page=1, page_size=10, sort_by="create_at", sort_order="desc")
        ids = [p.id for p in proposals]
        # Most recently created should be first
        assert ids.index(p2.id) < ids.index(p1.id)

    def test_sort_by_update_at(self, storage):
        """list_proposals should support sorting by update_at."""
        project = storage.list_projects(page=1, page_size=1)[0][0]
        p1 = storage.create_proposal({
            "title": "Update Sort 1", "owner": "alice", "project_id": project.id,
            "stage": "ideation",
        })
        p2 = storage.create_proposal({
            "title": "Update Sort 2", "owner": "bob", "project_id": project.id,
            "stage": "ideation",
        })
        # Update p1 to make it newer
        time.sleep(0.01)
        storage.update_proposal(p1.id, {"title": "Updated First"})
        proposals, _ = storage.list_proposals(page=1, page_size=10, sort_by="update_at", sort_order="desc")
        ids = [p.id for p in proposals]
        assert ids.index(p1.id) < ids.index(p2.id)