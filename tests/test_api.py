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
        self.allow_delete = True


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
        'allow_delete': True,
    })()
    s = CSVStorage(cfg, actor="test")
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
        'allow_delete': True,
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
        r = client.post("/api/projects", json={"name": "New Project", "git_repo": "https://github.com/test"}, headers=AUTH_HEADER)
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "New Project"
        assert data["id"].startswith("PRJ-")

    def test_list_projects(self, client):
        r = client.get("/api/projects", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "items" in data
        assert data["total"] >= 1

    def test_list_projects_pagination(self, client):
        r = client.get("/api/projects?page=1&page_size=1", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert len(data["items"]) == 1
        assert data["total"] >= 1

    def test_get_project(self, client):
        r = client.post("/api/projects", json={"name": "Get Me"}, headers=AUTH_HEADER)
        project_id = r.json()["id"]
        r = client.get(f"/api/projects/{project_id}", headers=AUTH_HEADER)
        assert r.status_code == 200
        assert r.json()["name"] == "Get Me"

    def test_get_project_not_found(self, client):
        r = client.get("/api/projects/PRJ-20991231-999", headers=AUTH_HEADER)
        assert r.status_code == 404

    def test_update_project(self, client):
        r = client.post("/api/projects", json={"name": "Old"}, headers=AUTH_HEADER)
        project_id = r.json()["id"]
        r = client.put(f"/api/projects/{project_id}", json={"name": "New", "description": "Desc"}, headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "New"
        assert data["description"] == "Desc"

    def test_update_project_not_found(self, client):
        r = client.put("/api/projects/PRJ-20991231-999", json={"name": "X"}, headers=AUTH_HEADER)
        assert r.status_code == 404

    def test_update_project_no_fields(self, client):
        r = client.post("/api/projects", json={"name": "X"}, headers=AUTH_HEADER)
        project_id = r.json()["id"]
        r = client.put(f"/api/projects/{project_id}", json={}, headers=AUTH_HEADER)
        assert r.status_code == 400

    def test_delete_project(self, client):
        # allow_delete=True in storage fixture
        r = client.post("/api/projects", json={"name": "Delete Me"}, headers=AUTH_HEADER)
        project_id = r.json()["id"]
        r = client.delete(f"/api/projects/{project_id}", headers=AUTH_HEADER)
        assert r.status_code == 204

    def test_delete_project_disabled_returns_403(self, client):
        """DELETE returns 403 when allow_delete=False on storage config."""
        import ai_superpower.server as server_mod
        # Patch storage.config.allow_delete on the pre-initialized storage
        original_allow = server_mod._storage.config.allow_delete
        server_mod._storage.config.allow_delete = False
        try:
            r = client.delete("/api/projects/PRJ-NONEXISTENT-999", headers=AUTH_HEADER)
            assert r.status_code == 403
            assert "allow_delete" in r.json()["detail"]
        finally:
            server_mod._storage.config.allow_delete = original_allow

    def test_delete_project_not_found(self, client):
        r = client.delete("/api/projects/PRJ-20991231-999", headers=AUTH_HEADER)
        assert r.status_code == 404


# ─── Proposals CRUD ───────────────────────────────────────────────────────────

class TestProposalEndpoints:
    def _get_project_id(self, client):
        r = client.get("/api/projects", headers=AUTH_HEADER)
        return r.json()["items"][0]["id"]

    def test_create_proposal(self, client):
        project_id = self._get_project_id(client)
        r = client.post("/api/proposals", json={
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
        r = client.post("/api/proposals", json={
            "title": "Bad Stage",
            "owner": "boss",
            "project_id": project_id,
            "stage": "not_a_stage",
        }, headers=AUTH_HEADER)
        # Pydantic ValidationError → FastAPI 422
        assert r.status_code == 422

    def test_create_proposal_invalid_project_id(self, client):
        r = client.post("/api/proposals", json={
            "title": "X",
            "owner": "boss",
            "project_id": "PRJ-20991231-999",
            "stage": "ideation",
        }, headers=AUTH_HEADER)
        assert r.status_code == 400

    def test_list_proposals(self, client):
        r = client.get("/api/proposals", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "items" in data

    def test_list_proposals_filter_project_id(self, client):
        project_id = self._get_project_id(client)
        r = client.get(f"/api/proposals?project_id={project_id}", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        for item in data["items"]:
            assert item["project_id"] == project_id

    def test_list_proposals_filter_status(self, client):
        r = client.get("/api/proposals?status=intake", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        for item in data["items"]:
            assert item["status"] == "intake"

    def test_get_proposal(self, client):
        project_id = self._get_project_id(client)
        r = client.post("/api/proposals", json={
            "title": "Get Me",
            "owner": "boss",
            "project_id": project_id,
            "stage": "ideation",
        }, headers=AUTH_HEADER)
        proposal_id = r.json()["id"]
        r = client.get(f"/api/proposals/{proposal_id}", headers=AUTH_HEADER)
        assert r.status_code == 200
        assert r.json()["title"] == "Get Me"

    def test_get_proposal_not_found(self, client):
        r = client.get("/api/proposals/P-20991231-999", headers=AUTH_HEADER)
        assert r.status_code == 404


# ─── Proposal Status Update ───────────────────────────────────────────────────

class TestProposalStatusUpdate:
    def _create_proposal(self, client):
        r = client.get("/api/projects", headers=AUTH_HEADER)
        project_id = r.json()["items"][0]["id"]
        r = client.post("/api/proposals", json={
            "title": "Status Test",
            "owner": "boss",
            "project_id": project_id,
            "stage": "ideation",
        }, headers=AUTH_HEADER)
        return r.json()["id"]

    def test_update_status_valid_transition(self, client):
        proposal_id = self._create_proposal(client)
        r = client.put(f"/api/proposals/{proposal_id}/status", json={"status": "clarifying"}, headers=AUTH_HEADER)
        assert r.status_code == 200
        assert r.json()["status"] == "clarifying"

    def test_update_status_invalid_transition(self, client):
        proposal_id = self._create_proposal(client)
        r = client.put(f"/api/proposals/{proposal_id}/status", json={"status": "accepted"}, headers=AUTH_HEADER)
        assert r.status_code == 400
        assert "Invalid status transition" in r.json()["detail"]

    def test_update_status_invalid_status_value(self, client):
        proposal_id = self._create_proposal(client)
        r = client.put(f"/api/proposals/{proposal_id}/status", json={"status": "not_a_real_status"}, headers=AUTH_HEADER)
        # Pydantic ValidationError → FastAPI 422
        assert r.status_code == 422


# ─── Proposal Fields Update ─────────────────────────────────────────────────

class TestProposalFieldsUpdate:
    def _create_proposal(self, client):
        r = client.get("/api/projects", headers=AUTH_HEADER)
        project_id = r.json()["items"][0]["id"]
        r = client.post("/api/proposals", json={
            "title": "Fields Test",
            "owner": "boss",
            "project_id": project_id,
            "stage": "ideation",
        }, headers=AUTH_HEADER)
        return r.json()["id"]

    def test_update_fields(self, client):
        proposal_id = self._create_proposal(client)
        r = client.put(f"/api/proposals/{proposal_id}/fields", json={
            "title": "New Title",
            "owner": "alice",
        }, headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["title"] == "New Title"
        assert data["owner"] == "alice"

    def test_update_fields_invalid_enum(self, client):
        proposal_id = self._create_proposal(client)
        r = client.put(f"/api/proposals/{proposal_id}/fields", json={
            "prd_confirmation": "invalid_value",
        }, headers=AUTH_HEADER)
        assert r.status_code == 400


# ─── Validate Endpoint ───────────────────────────────────────────────────────

class TestValidateEndpoint:
    def test_validate_valid_data(self, client):
        r = client.get("/api/projects", headers=AUTH_HEADER)
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
        client.post("/api/projects", json={"name": "Audit Test"}, headers=AUTH_HEADER)
        r = client.get("/api/audit", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1


# ─── End-to-End Flow ─────────────────────────────────────────────────────────

class TestEndToEndFlow:
    def test_full_proposal_lifecycle(self, client):
        r = client.post("/api/projects", json={"name": "E2E Project"}, headers=AUTH_HEADER)
        project_id = r.json()["id"]

        r = client.post("/api/proposals", json={
            "title": "E2E Proposal",
            "owner": "boss",
            "project_id": project_id,
            "stage": "ideation",
        }, headers=AUTH_HEADER)
        proposal_id = r.json()["id"]
        assert r.json()["status"] == "intake"

        for new_status in ["clarifying", "prd_pending_confirmation", "approved_for_dev", "in_dev"]:
            r = client.put(f"/api/proposals/{proposal_id}/status", json={"status": new_status}, headers=AUTH_HEADER)
            assert r.json()["status"] == new_status

        r = client.put(f"/api/proposals/{proposal_id}/fields", json={"notes": "E2E test notes"}, headers=AUTH_HEADER)
        assert r.json()["notes"] == "E2E test notes"

        r = client.get(f"/api/proposals/{proposal_id}", headers=AUTH_HEADER)
        data = r.json()
        assert data["status"] == "in_dev"
        assert data["notes"] == "E2E test notes"
        assert data["title"] == "E2E Proposal"


# ─── Pagination Boundary Cases ────────────────────────────────────────────────

class TestPaginationBoundary:
    def _create_project(self, client):
        r = client.post("/api/projects", json={"name": "Pag Test"}, headers=AUTH_HEADER)
        return r.json()["id"]

    def _create_proposal(self, client, project_id, title):
        r = client.post("/api/proposals", json={
            "title": title,
            "owner": "boss",
            "project_id": project_id,
            "stage": "ideation",
        }, headers=AUTH_HEADER)

    def test_page_size_1(self, client):
        pid = self._create_project(client)
        for i in range(3):
            self._create_proposal(client, pid, f"Page Item {i}")
        r = client.get("/api/proposals?page=1&page_size=1", headers=AUTH_HEADER)
        assert r.status_code == 200
        assert len(r.json()["items"]) == 1
        assert r.json()["total"] >= 3

    def test_page_beyond_range(self, client):
        pid = self._create_project(client)
        self._create_proposal(client, pid, "Only One")
        r = client.get("/api/proposals?page=999&page_size=50", headers=AUTH_HEADER)
        assert r.status_code == 200
        assert len(r.json()["items"]) == 0
        assert r.json()["total"] >= 1

    def test_list_proposals_filter_owner(self, client):
        pid = self._create_project(client)
        self._create_proposal(client, pid, "Owner Alice")
        self._create_proposal(client, pid, "Owner Bob")
        # Update owner of second proposal via fields
        r = client.get("/api/proposals", headers=AUTH_HEADER)
        items = r.json()["items"]
        for item in items:
            if item["title"] == "Owner Alice":
                r = client.put(f"/api/proposals/{item['id']}/fields", json={"owner": "alice"}, headers=AUTH_HEADER)
        r = client.get("/api/proposals?owner=alice", headers=AUTH_HEADER)
        assert r.status_code == 200
        for item in r.json()["items"]:
            assert item["owner"] == "alice"

    def test_list_proposals_filter_stage(self, client):
        pid = self._create_project(client)
        self._create_proposal(client, pid, "Stage Idea")
        r = client.get("/api/proposals?stage=ideation", headers=AUTH_HEADER)
        assert r.status_code == 200
        for item in r.json()["items"]:
            assert item["stage"] == "ideation"

    def test_list_proposals_filter_combined(self, client):
        pid = self._create_project(client)
        self._create_proposal(client, pid, "Combo Test")
        r = client.get(f"/api/proposals?project_id={pid}&status=intake", headers=AUTH_HEADER)
        assert r.status_code == 200
        for item in r.json()["items"]:
            assert item["project_id"] == pid
            assert item["status"] == "intake"


# ─── Field Boundary Cases ─────────────────────────────────────────────────────

class TestFieldBoundary:
    def _create_project(self, client):
        r = client.post("/api/projects", json={"name": "Field Test"}, headers=AUTH_HEADER)
        return r.json()["id"]

    def test_empty_string_fields_accepted(self, client):
        """Empty strings are valid for optional string fields."""
        pid = self._create_project(client)
        r = client.post("/api/proposals", json={
            "title": "Empty Fields",
            "owner": "boss",
            "project_id": pid,
            "stage": "ideation",
            "prd_path": "",
            "git_repo": "",
        }, headers=AUTH_HEADER)
        assert r.status_code == 201
        data = r.json()
        assert data["prd_path"] == ""
        assert data["git_repo"] == ""

    def test_update_with_empty_string(self, client):
        pid = self._create_project(client)
        r = client.post("/api/proposals", json={
            "title": "Update Empty",
            "owner": "boss",
            "project_id": pid,
            "stage": "ideation",
            "notes": "has notes",
        }, headers=AUTH_HEADER)
        proposal_id = r.json()["id"]
        r = client.put(f"/api/proposals/{proposal_id}/fields", json={"notes": ""}, headers=AUTH_HEADER)
        assert r.status_code == 200
        assert r.json()["notes"] == ""

    def test_proposal_id_not_updated_if_in_body(self, client):
        """发送包含 id 的请求体，API 应拒绝（id 不在 ProposalUpdate 字段中）。"""
        pid = self._create_project(client)
        r = client.post("/api/proposals", json={
            "title": "ID Test",
            "owner": "boss",
            "project_id": pid,
            "stage": "ideation",
        }, headers=AUTH_HEADER)
        proposal_id = r.json()["id"]
        # ProposalUpdate 不包含 id 字段，Pydantic extra='forbid' 拒绝额外字段
        # FastAPI 对 Pydantic ValidationError 返回 422，但 storage 层格式化错误返回 400
        # 两者都表示拒绝，重点是 proposal_id 未被改变
        r = client.put(f"/api/proposals/{proposal_id}/fields", json={"id": "P-20991231-999"}, headers=AUTH_HEADER)
        assert r.status_code in (400, 422)
        # 确认原 proposal 不变（未被篡改成 P-20991231-999）
        r2 = client.get(f"/api/proposals/{proposal_id}", headers=AUTH_HEADER)
        assert r2.json()["id"] == proposal_id


# ─── Config Loading ──────────────────────────────────────────────────────────

class TestConfigLoading:
    def test_config_missing_key_returns_empty_string(self, tmp_path):
        """Config file with no API key key returns empty string key (not crash)."""
        import ai_superpower.config as config_mod
        from pathlib import Path as PathClass

        orig_path = config_mod.CONFIG_PATH
        no_key_config = tmp_path / "no_key.toml"
        no_key_config.write_text("")

        config_mod.CONFIG_PATH = PathClass(no_key_config)
        try:
            cfg = config_mod.load_config()
            # Should return APIConfig with empty key, not crash
            assert cfg.key == ""
        finally:
            config_mod.CONFIG_PATH = orig_path
