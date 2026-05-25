"""Tests for project_local_path auto-fill (feature 1)."""
import pytest


class TestProjectLocalPathAutoFill:
    """Test that project_local_path is auto-filled when creating proposals."""

    def test_create_proposal_auto_fills_local_path(self, storage):
        """project_local_path should be auto-filled from project's local_path."""
        project = storage.list_projects(page=1, page_size=1)[0][0]
        # Update project with local_path
        storage.update_project(project.id, {"local_path": "/home/user/my-project"})

        proposal = storage.create_proposal({
            "title": "Auto Fill Path", "owner": "alice", "project_id": project.id,
            "stage": "ideation",
        })
        assert proposal.project_local_path == "/home/user/my-project"

    def test_create_proposal_does_not_override_explicit_local_path(self, storage):
        """Explicit project_local_path in request should not be overridden."""
        project = storage.list_projects(page=1, page_size=1)[0][0]
        storage.update_project(project.id, {"local_path": "/home/user/my-project"})

        proposal = storage.create_proposal({
            "title": "Explicit Path", "owner": "alice", "project_id": project.id,
            "stage": "ideation",
            "project_local_path": "/explicit/path",
        })
        assert proposal.project_local_path == "/explicit/path"

    def test_create_proposal_empty_local_path_when_project_has_no_path(self, storage):
        """project_local_path should be empty if project's local_path is empty."""
        project = storage.list_projects(page=1, page_size=1)[0][0]
        # Ensure project has no local_path (default in conftest)
        assert project.local_path == ""

        proposal = storage.create_proposal({
            "title": "No Project Path", "owner": "alice", "project_id": project.id,
            "stage": "ideation",
        })
        assert proposal.project_local_path == ""

    def test_project_local_path_in_csv(self, storage):
        """project_local_path should be written to CSV correctly."""
        project = storage.list_projects(page=1, page_size=1)[0][0]
        storage.update_project(project.id, {"local_path": "/data/myproj"})

        proposal = storage.create_proposal({
            "title": "CSV Check", "owner": "alice", "project_id": project.id,
            "stage": "ideation",
        })

        # Read CSV directly
        import csv
        with open(storage.config.proposals_csv, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["id"] == proposal.id:
                    assert row["project_local_path"] == "/data/myproj"
                    break

    def test_update_proposal_preserves_project_local_path(self, storage):
        """Updating proposal should not change project_local_path."""
        project = storage.list_projects(page=1, page_size=1)[0][0]
        storage.update_project(project.id, {"local_path": "/home/preserved"})

        proposal = storage.create_proposal({
            "title": "Preserve Test", "owner": "alice", "project_id": project.id,
            "stage": "ideation",
        })
        assert proposal.project_local_path == "/home/preserved"

        updated = storage.update_proposal(proposal.id, {"title": "New Title"})
        assert updated.project_local_path == "/home/preserved"