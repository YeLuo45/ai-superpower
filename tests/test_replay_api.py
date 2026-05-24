"""TDD tests for POST /api/replay/undo endpoint.

These tests are written first and should FAIL until the feature is implemented.
"""
import json
import pytest
from starlette.testclient import TestClient

from ai_superpower.storage import CSVStorage


class TestReplayAPI:
    """Test POST /api/replay/undo endpoint."""

    @pytest.fixture
    def replay_api_client(self, tmp_path, monkeypatch):
        """Create test client with temporary storage and API key."""
        import ai_superpower.config as config_mod
        import ai_superpower.server as server_mod

        audit_log = str(tmp_path / "audit.log")
        projects_csv = str(tmp_path / "projects.csv")
        proposals_csv = str(tmp_path / "proposals.csv")
        api_key = "test-key-456"

        test_cfg = type('Config', (), {
            'projects_csv': projects_csv,
            'proposals_csv': proposals_csv,
            'audit_log': audit_log,
            'key': api_key,
            'socket_path': str(tmp_path / "api.sock"),
            'allow_delete': True,
            'data_dir': str(tmp_path),
        })()

        monkeypatch.setattr(config_mod, 'load_config', lambda: test_cfg)
        monkeypatch.setattr(server_mod, 'load_config', lambda: test_cfg)

        storage = CSVStorage(test_cfg, actor="test")
        server_mod._storage = storage

        from ai_superpower.server import app
        with TestClient(app, raise_server_exceptions=True) as tc:
            yield tc, storage, audit_log

    def test_undo_project_update(self, replay_api_client):
        """POST /api/replay/undo should reverse a project UPDATE operation."""
        tc, storage, audit_log = replay_api_client

        # Create project
        proj = storage.create_project(name="Undo Test Project")
        # Modify it (creates audit entry)
        storage.update_project(proj.id, {"description": "updated desc"})

        # Verify UPDATE entry exists in audit log
        with open(audit_log, "r") as f:
            lines = [json.loads(l) for l in f if l.strip()]
        update_entries = [l for l in lines if l["op"] == "UPDATE" and l["entity"] == "project"]
        assert len(update_entries) >= 1, f"Should have at least one UPDATE entry, got: {lines}"

        # Undo the update via API
        resp = tc.post(
            "/api/replay/undo",
            json={"entity": "project", "id": proj.id},
            headers={"X-API-Key": "test-key-456"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["success"] is True, f"Undo failed: {data}"
        assert data["entry"]["id"] == proj.id
        assert data["entry"]["op"] == "UPDATE"
        assert "message" in data

    def test_undo_proposal_create(self, replay_api_client):
        """POST /api/replay/undo should delete a newly created proposal."""
        tc, storage, audit_log = replay_api_client

        # Create project first (proposal needs it)
        proj = storage.create_project(name="Undo Proposal Test")

        # Create proposal
        prop = storage.create_proposal({
            "title": "Undo Me Proposal",
            "project_id": proj.id,
            "status": "draft",
            "stage": "ideation",
        })

        # Verify proposal exists
        assert storage.get_proposal(prop.id) is not None

        # Verify CREATE entry exists in audit log for this proposal
        with open(audit_log, "r") as f:
            lines = [json.loads(l) for l in f if l.strip()]
        create_entries = [l for l in lines if l["op"] == "CREATE" and l["entity"] == "proposal" and l["id"] == prop.id]
        assert len(create_entries) >= 1, f"Should have CREATE entry for proposal, got: {lines}"

        # Undo the create via API (should delete the proposal)
        resp = tc.post(
            "/api/replay/undo",
            json={"entity": "proposal", "id": prop.id},
            headers={"X-API-Key": "test-key-456"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["success"] is True, f"Undo failed: {data}, audit_log contents: {open(audit_log).read() if open(audit_log).read() else 'empty'}"
        assert data["entry"]["op"] == "CREATE"
        assert data["entry"]["entity"] == "proposal"

        # Proposal should be gone
        assert storage.get_proposal(prop.id) is None

    def test_undo_delete_returns_warning(self, replay_api_client):
        """DELETE undo operations should return a warning message."""
        tc, storage, audit_log = replay_api_client

        # Create and delete a project
        proj = storage.create_project(name="Delete Me")
        storage.delete_project(proj.id)

        # Verify DELETE entry exists in audit log
        with open(audit_log, "r") as f:
            lines = [json.loads(l) for l in f if l.strip()]
        delete_entries = [l for l in lines if l["op"] == "DELETE" and l["entity"] == "project" and l["id"] == proj.id]
        assert len(delete_entries) >= 1, f"Should have DELETE entry, got: {lines}"

        # Try to undo the DELETE - should warn
        resp = tc.post(
            "/api/replay/undo",
            json={"entity": "project", "id": proj.id},
            headers={"X-API-Key": "test-key-456"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        # DELETE undo should return warning=True or message indicating skip
        assert data["warning"] is True or "cannot" in data["message"].lower() or "skip" in data["message"].lower() or "data lost" in data["message"].lower(), f"Expected warning for DELETE undo, got: {data}"

    def test_undo_without_api_key_returns_422(self, replay_api_client):
        """Requests without X-API-Key header should return 422 (FastAPI validation error)."""
        tc, storage, _ = replay_api_client

        resp = tc.post(
            "/api/replay/undo",
            json={"entity": "project", "id": "PRJ-999"},
        )
        # FastAPI returns 422 for missing required header
        assert resp.status_code == 422

    def test_undo_entity_not_found(self, replay_api_client):
        """Undoing a non-existent entity should return success=False with message."""
        tc, storage, _ = replay_api_client

        resp = tc.post(
            "/api/replay/undo",
            json={"entity": "project", "id": "PRJ-NONEXISTENT"},
            headers={"X-API-Key": "test-key-456"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        # Message contains "no entry found"
        assert "no entry found" in data["message"].lower()

    def test_undo_invalid_api_key_returns_error(self, replay_api_client):
        """Requests with invalid API key should still succeed but return error in body."""
        tc, storage, _ = replay_api_client

        resp = tc.post(
            "/api/replay/undo",
            json={"entity": "project", "id": "PRJ-999"},
            headers={"X-API-Key": "wrong-key"},
        )
        # Currently API key value is not validated server-side
        # This test documents that invalid keys are accepted (not ideal but current behavior)
        assert resp.status_code == 200
        data = resp.json()
        # Result is an error because entity doesn't exist
        assert data["success"] is False
        assert "no entry found" in data["message"].lower()

    def test_undo_proposal_update(self, replay_api_client):
        """POST /api/replay/undo should reverse a proposal UPDATE operation."""
        tc, storage, audit_log = replay_api_client

        proj = storage.create_project(name="Proposal Undo Test")
        prop = storage.create_proposal({
            "title": "Undo Update Test",
            "project_id": proj.id,
            "status": "draft",
            "stage": "ideation",
        })

        # Update proposal
        storage.update_proposal(prop.id, {"stage": "prototype"})

        # Verify UPDATE entry exists in audit log
        with open(audit_log, "r") as f:
            lines = [json.loads(l) for l in f if l.strip()]
        update_entries = [l for l in lines if l["op"] == "UPDATE" and l["entity"] == "proposal" and l["id"] == prop.id]
        assert len(update_entries) >= 1, f"Should have UPDATE entry, got: {lines}"

        # Undo the update
        resp = tc.post(
            "/api/replay/undo",
            json={"entity": "proposal", "id": prop.id},
            headers={"X-API-Key": "test-key-456"},
        )
        assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["success"] is True, f"Undo failed: {data}"
        assert data["entry"]["op"] == "UPDATE"
        assert data["entry"]["entity"] == "proposal"

        # Verify stage was reverted
        updated = storage.get_proposal(prop.id)
        assert updated.stage == "ideation"