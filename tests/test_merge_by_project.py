"""Tests for merge_proposals_by_project (feature 3)."""
import pytest


class TestMergeProposalsByProjectStorage:
    """Test merge at storage layer."""

    def test_merge_nonexistent_target(self, storage):
        """Should raise ValueError for nonexistent target project."""
        with pytest.raises(ValueError, match="Target project not found"):
            storage.merge_proposals_by_project("PRJ-99999999-999", "some name")

    def test_merge_no_matching_source(self, storage):
        """Should return 0 merged when no proposals match source name."""
        project = storage.list_projects(page=1, page_size=1)[0][0]
        result = storage.merge_proposals_by_project(
            target_project_id=project.id,
            source_project_name="ThisProjectDoesNotExist",
        )
        assert result["merged_count"] == 0
        assert result["merged_ids"] == []

    def test_merge_active_and_archived_only(self, storage):
        """Only active/archived proposals should be merged."""
        from ai_superpower.models import ProposalCreate

        project = storage.list_projects(page=1, page_size=1)[0][0]
        project_id = project.id

        # Create proposals with different statuses
        active_proposal_id = storage.create_proposal({
            "title": "Active Proposal", "owner": "alice", "project_id": project_id,
            "stage": "active", "status": "active",
        }).id

        archived_proposal_id = storage.create_proposal({
            "title": "Archived Proposal", "owner": "bob", "project_id": project_id,
            "stage": "archived", "status": "archived",
        }).id

        intake_proposal_id = storage.create_proposal({
            "title": "Intake Proposal", "owner": "carol", "project_id": project_id,
            "stage": "intake", "status": "intake",
        }).id

        # Create target project
        target = storage.create_project(name="Target Project")

        # Merge from project by name
        result = storage.merge_proposals_by_project(
            target_project_id=target.id,
            source_project_name=project.name,
        )

        assert result["merged_count"] == 2
        assert active_proposal_id in result["merged_ids"]
        assert archived_proposal_id in result["merged_ids"]
        assert intake_proposal_id not in result["merged_ids"]

    def test_merge_updates_project_id(self, storage):
        """Merged proposals should have their project_id updated."""
        project = storage.list_projects(page=1, page_size=1)[0][0]

        proposal = storage.create_proposal({
            "title": "To Merge", "owner": "alice", "project_id": project.id,
            "stage": "active", "status": "active",
        })

        target = storage.create_project(name="Merge Target")

        result = storage.merge_proposals_by_project(
            target_project_id=target.id,
            source_project_name=project.name,
        )

        assert result["merged_count"] == 1
        updated = storage.get_proposal(result["merged_ids"][0])
        assert updated.project_id == target.id

    def test_merge_case_insensitive_name_match(self, storage):
        """Source project name matching should be case-insensitive."""
        project = storage.list_projects(page=1, page_size=1)[0][0]
        storage.create_proposal({
            "title": "Test", "owner": "alice", "project_id": project.id,
            "stage": "active", "status": "active",
        })

        target = storage.create_project(name="Target 2")
        result = storage.merge_proposals_by_project(
            target_project_id=target.id,
            source_project_name=project.name.upper(),
        )
        assert result["merged_count"] == 1

    def test_merge_empty_source(self, storage):
        """Empty source name with no matches returns 0."""
        target = storage.list_projects(page=1, page_size=1)[0][0]
        result = storage.merge_proposals_by_project(
            target_project_id=target.id,
            source_project_name="NoMatchProject",
        )
        assert result["merged_count"] == 0
        assert result["merged_ids"] == []