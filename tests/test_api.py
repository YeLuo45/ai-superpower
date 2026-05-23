"""Tests for ai_superpower FastAPI endpoints using TestClient (no real server needed)."""
import json
import os
import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from starlette.testclient import TestClient
from ai_superpower.storage import CSVStorage
from ai_superpower.server import app


# ─── Test Fixtures ─────────────────────────────────────────────────────────────

class ConfigForTest:
    def __init__(self, tmp_path):
        self.projects_csv = str(tmp_path / "projects.csv")
        self.proposals_csv = str(tmp_path / "proposals.csv")
        self.audit_log = str(tmp_path / "audit.log")
        self.key = "test-key-456"
        self.socket_path = str(tmp_path / "api.sock")


@pytest.fixture
def config(tmp_path):
    return ConfigForTest(tmp_path)


@pytest.fixture
def storage(config):
    """Create storage with test config."""
    from ai_superpower.storage import CSVStorage
    cfg = type('Config', (), {
        'projects_csv': config.projects_csv,
        'proposals_csv': config.proposals_csv,
        'audit_log': config.audit_log,
        'key': config.key,
        'socket_path': config.socket_path,
    })()
    s = CSVStorage(cfg)
    s.create_project(name="API Test Project")
    return s


@pytest.fixture
def client(storage, config):
    """Attach storage to app state and return TestClient."""
    # Patch load_config to return test config
    import ai_superpower.config as config_mod
    import ai_superpower.server as server_mod
    orig_load = config_mod.load_config
    test_cfg = type('Config', (), {
        'projects_csv': config.projects_csv,
        'proposals_csv': config.proposals_csv,
        'audit_log': config.audit_log,
        'key': config.key,
        'socket_path': config.socket_path,
    })()
    config_mod.load_config = lambda: test_cfg
    server_mod.load_config = lambda: test_cfg
    server_mod._storage = storage

    # Suppress startup on_event warning — we bypass it by pre-setting _storage
    with TestClient(app, raise_server_exceptions=True) as tc:
        yield tc

    config_mod.load_config = orig_load


# ─── Auth Header ───────────────────────────────────────────────────────────────

AUTH_HEADER = {"X-API-Key": "test-key-456"}


# ─── Health ───────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"


# ─── Auth ─────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_auth_works_with_correct_key(self, client):
        r = client.get("/health", headers={"X-API-Key": "test-key-456"})
        assert r.status_code == 200


# ─── Projects CRUD ─────────────────────────────────────────────────────────────

class TestProjectEndpoints:
    def test_create_project(self, client):
        r = client.post("/projects", json={"name": "New Project", "git_repo": "https://github.com/test"}, headers=AUTH_HEADER)
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "New Project"
        assert data["id"].startswith("PRJ-")

    def test_list_projects(self, client):
        r = client.get("/projects", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "items" in data
        assert data["total"] >= 1

    def test_list_projects_pagination(self, client):
        r = client.get("/projects?page=1&page_size=1", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert len(data["items"]) == 1
        assert data["total"] >= 1

    def test_get_project(self, client):
        r = client.post("/projects", json={"name": "Get Me"}, headers=AUTH_HEADER)
        project_id = r.json()["id"]
        r = client.get(f"/projects/{project_id}", headers=AUTH_HEADER)
        assert r.status_code == 200
        assert r.json()["name"] == "Get Me"

    def test_get_project_not_found(self, client):
        r = client.get("/projects/PRJ-20991231-999", headers=AUTH_HEADER)
        assert r.status_code == 404

    def test_update_project(self, client):
        r = client.post("/projects", json={"name": "Old"}, headers=AUTH_HEADER)
        project_id = r.json()["id"]
        r = client.put(f"/projects/{project_id}", json={"name": "New", "description": "Desc"}, headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "New"
        assert data["description"] == "Desc"

    def test_update_project_not_found(self, client):
        r = client.put("/projects/PRJ-20991231-999", json={"name": "X"}, headers=AUTH_HEADER)
        assert r.status_code == 404

    def test_update_project_no_fields(self, client):
        r = client.post("/projects", json={"name": "X"}, headers=AUTH_HEADER)
        project_id = r.json()["id"]
        r = client.put(f"/projects/{project_id}", json={}, headers=AUTH_HEADER)
        assert r.status_code == 400

    def test_delete_project(self, client):
        r = client.post("/projects", json={"name": "Delete Me"}, headers=AUTH_HEADER)
        project_id = r.json()["id"]
        r = client.delete(f"/projects/{project_id}", headers=AUTH_HEADER)
        assert r.status_code == 204

    def test_delete_project_not_found(self, client):
        r = client.delete("/projects/PRJ-20991231-999", headers=AUTH_HEADER)
        assert r.status_code == 404


# ─── Proposals CRUD ───────────────────────────────────────────────────────────

class TestProposalEndpoints:
    def _get_project_id(self, client):
        r = client.get("/projects", headers=AUTH_HEADER)
        return r.json()["items"][0]["id"]

    def test_create_proposal(self, client):
        project_id = self._get_project_id(client)
        r = client.post("/proposals", json={
            "title": "My Proposal",
            "owner": "boss",
            "project_id": project_id,
            "stage": "ideation",
        }, headers=AUTH_HEADER)
        assert r.status_code == 201
        data = r.json()
        assert data["title"] == "My Proposal"
        assert data["status"] == "intake"

    def test_create_proposal_invalid_stage(self, client):
        project_id = self._get_project_id(client)
        r = client.post("/proposals", json={
            "title": "Bad Stage",
            "owner": "boss",
            "project_id": project_id,
            "stage": "not_a_stage",
        }, headers=AUTH_HEADER)
        # Pydantic ValidationError → FastAPI 422
        assert r.status_code == 422

    def test_create_proposal_invalid_project_id(self, client):
        r = client.post("/proposals", json={
            "title": "X",
            "owner": "boss",
            "project_id": "PRJ-20991231-999",
            "stage": "ideation",
        }, headers=AUTH_HEADER)
        assert r.status_code == 400

    def test_list_proposals(self, client):
        r = client.get("/proposals", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "items" in data

    def test_list_proposals_filter_project_id(self, client):
        project_id = self._get_project_id(client)
        r = client.get(f"/proposals?project_id={project_id}", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        for item in data["items"]:
            assert item["project_id"] == project_id

    def test_list_proposals_filter_status(self, client):
        r = client.get("/proposals?status=intake", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        for item in data["items"]:
            assert item["status"] == "intake"

    def test_get_proposal(self, client):
        project_id = self._get_project_id(client)
        r = client.post("/proposals", json={
            "title": "Get Me",
            "owner": "boss",
            "project_id": project_id,
            "stage": "ideation",
        }, headers=AUTH_HEADER)
        proposal_id = r.json()["id"]
        r = client.get(f"/proposals/{proposal_id}", headers=AUTH_HEADER)
        assert r.status_code == 200
        assert r.json()["title"] == "Get Me"

    def test_get_proposal_not_found(self, client):
        r = client.get("/proposals/P-20991231-999", headers=AUTH_HEADER)
        assert r.status_code == 404


# ─── Proposal Status Update ───────────────────────────────────────────────────

class TestProposalStatusUpdate:
    def _create_proposal(self, client):
        r = client.get("/projects", headers=AUTH_HEADER)
        project_id = r.json()["items"][0]["id"]
        r = client.post("/proposals", json={
            "title": "Status Test",
            "owner": "boss",
            "project_id": project_id,
            "stage": "ideation",
        }, headers=AUTH_HEADER)
        return r.json()["id"]

    def test_update_status_valid_transition(self, client):
        proposal_id = self._create_proposal(client)
        r = client.put(f"/proposals/{proposal_id}/status", json={"status": "clarifying"}, headers=AUTH_HEADER)
        assert r.status_code == 200
        assert r.json()["status"] == "clarifying"

    def test_update_status_invalid_transition(self, client):
        proposal_id = self._create_proposal(client)
        r = client.put(f"/proposals/{proposal_id}/status", json={"status": "accepted"}, headers=AUTH_HEADER)
        assert r.status_code == 400
        assert "Invalid status transition" in r.json()["detail"]

    def test_update_status_invalid_status_value(self, client):
        proposal_id = self._create_proposal(client)
        r = client.put(f"/proposals/{proposal_id}/status", json={"status": "not_a_real_status"}, headers=AUTH_HEADER)
        # Pydantic ValidationError → FastAPI 422
        assert r.status_code == 422


# ─── Proposal Fields Update ─────────────────────────────────────────────────

class TestProposalFieldsUpdate:
    def _create_proposal(self, client):
        r = client.get("/projects", headers=AUTH_HEADER)
        project_id = r.json()["items"][0]["id"]
        r = client.post("/proposals", json={
            "title": "Fields Test",
            "owner": "boss",
            "project_id": project_id,
            "stage": "ideation",
        }, headers=AUTH_HEADER)
        return r.json()["id"]

    def test_update_fields(self, client):
        proposal_id = self._create_proposal(client)
        r = client.put(f"/proposals/{proposal_id}/fields", json={
            "title": "New Title",
            "owner": "alice",
        }, headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["title"] == "New Title"
        assert data["owner"] == "alice"

    def test_update_fields_invalid_enum(self, client):
        proposal_id = self._create_proposal(client)
        r = client.put(f"/proposals/{proposal_id}/fields", json={
            "prd_confirmation": "invalid_value",
        }, headers=AUTH_HEADER)
        assert r.status_code == 400


# ─── Validate Endpoint ───────────────────────────────────────────────────────

class TestValidateEndpoint:
    def test_validate_valid_data(self, client):
        r = client.get("/projects", headers=AUTH_HEADER)
        project_id = r.json()["items"][0]["id"]
        r = client.post("/validate", json={
            "data": {
                "title": "Valid",
                "owner": "boss",
                "project_id": project_id,
                "stage": "ideation",
            }
        }, headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is True
        assert data["errors"] == []

    def test_validate_invalid_data(self, client):
        r = client.post("/validate", json={
            "data": {
                "title": "X",
                "owner": "boss",
                "project_id": "PRJ-20991231-999",
                "stage": "ideation",
            }
        }, headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0


# ─── Audit Endpoint ───────────────────────────────────────────────────────────

class TestAuditEndpoint:
    def test_audit_after_create(self, client):
        client.post("/projects", json={"name": "Audit Test"}, headers=AUTH_HEADER)
        r = client.get("/audit", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1


# ─── End-to-End Flow ─────────────────────────────────────────────────────────

class TestEndToEndFlow:
    def test_full_proposal_lifecycle(self, client):
        r = client.post("/projects", json={"name": "E2E Project"}, headers=AUTH_HEADER)
        project_id = r.json()["id"]

        r = client.post("/proposals", json={
            "title": "E2E Proposal",
            "owner": "boss",
            "project_id": project_id,
            "stage": "ideation",
        }, headers=AUTH_HEADER)
        proposal_id = r.json()["id"]
        assert r.json()["status"] == "intake"

        for new_status in ["clarifying", "prd_pending_confirmation", "approved_for_dev", "in_dev"]:
            r = client.put(f"/proposals/{proposal_id}/status", json={"status": new_status}, headers=AUTH_HEADER)
            assert r.json()["status"] == new_status

        r = client.put(f"/proposals/{proposal_id}/fields", json={"notes": "E2E test notes"}, headers=AUTH_HEADER)
        assert r.json()["notes"] == "E2E test notes"

        r = client.get(f"/proposals/{proposal_id}", headers=AUTH_HEADER)
        data = r.json()
        assert data["status"] == "in_dev"
        assert data["notes"] == "E2E test notes"
        assert data["title"] == "E2E Proposal"
