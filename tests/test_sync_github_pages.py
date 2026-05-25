"""Tests for Direction C: Sync to GitHub Pages.

TDD approach: tests are written first, then implementation.

Covers:
- POST /api/sync/export → 202
- GET /api/sync/export-status → returns export_last_run, export_status
- CSV → JSON conversion validation
- proposals.json + projects.json + export_info.json generation
"""
import csv
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from starlette.testclient import TestClient
from ai_superpower.storage import CSVStorage


# ─── Test Fixtures ─────────────────────────────────────────────────────────────

class ExportTestConfig:
    """Config for export tests."""
    def __init__(self, tmp_path):
        self.projects_csv = str(tmp_path / "projects.csv")
        self.proposals_csv = str(tmp_path / "proposals.csv")
        self.audit_log = str(tmp_path / "audit.log")
        self.key = "test-key-456"
        self.socket_path = str(tmp_path / "api.sock")
        self.allow_delete = True
        self.data_dir = str(tmp_path)
        self.backup_local_path = str(tmp_path / "backups")
        self.backup_max_copies = 3
        self.backup_remote_repo = ""
        self.backup_api_key = "test-github-token"
        self.sync_target_repo = "YeLuo45/ai-superpower"
        self.sync_enabled = True
        self.sync_api_key = "test-github-token"
        self.sync_interval_minutes = 60


@pytest.fixture
def export_config(tmp_path):
    return ExportTestConfig(tmp_path)


@pytest.fixture
def export_storage(export_config):
    """Create CSVStorage for export tests."""
    cfg = type('Config', (), {
        'projects_csv': export_config.projects_csv,
        'proposals_csv': export_config.proposals_csv,
        'audit_log': export_config.audit_log,
        'key': export_config.key,
        'socket_path': export_config.socket_path,
        'allow_delete': True,
        'data_dir': export_config.data_dir,
        'backup_local_path': export_config.backup_local_path,
        'backup_max_copies': export_config.backup_max_copies,
        'backup_remote_repo': export_config.backup_remote_repo,
        'backup_api_key': export_config.backup_api_key,
        'sync_target_repo': export_config.sync_target_repo,
        'sync_enabled': export_config.sync_enabled,
        'sync_api_key': export_config.sync_api_key,
        'sync_interval_minutes': export_config.sync_interval_minutes,
    })()
    s = CSVStorage(cfg, actor="test")
    s.create_project(name="Export Test Project")
    return s


@pytest.fixture
def export_client(export_storage, export_config):
    """TestClient with storage attached for export tests."""
    import ai_superpower.config as config_mod
    import ai_superpower.server as server_mod

    orig_load = config_mod.load_config
    test_cfg = type('Config', (), {
        'projects_csv': export_config.projects_csv,
        'proposals_csv': export_config.proposals_csv,
        'audit_log': export_config.audit_log,
        'key': export_config.key,
        'socket_path': export_config.socket_path,
        'allow_delete': True,
        'data_dir': export_config.data_dir,
        'backup_local_path': export_config.backup_local_path,
        'backup_max_copies': export_config.backup_max_copies,
        'backup_remote_repo': export_config.backup_remote_repo,
        'backup_api_key': export_config.backup_api_key,
        'sync_target_repo': export_config.sync_target_repo,
        'sync_enabled': export_config.sync_enabled,
        'sync_api_key': export_config.sync_api_key,
        'sync_interval_minutes': export_config.sync_interval_minutes,
        'sync_prj_repo': "YeLuo45/prj-proposals-manager",
    })()
    config_mod.load_config = lambda: test_cfg
    server_mod.load_config = lambda: test_cfg
    server_mod._storage = export_storage

    from ai_superpower.server import app
    with TestClient(app, raise_server_exceptions=True) as tc:
        yield tc

    config_mod.load_config = orig_load


AUTH_HEADER = {"X-API-Key": "test-key-456"}


# ─── CSV → JSON Conversion Tests ──────────────────────────────────────────────

class TestCsvToGhPagesJson:
    """Test csv_to_gh_pages_json() conversion for GitHub Pages export."""

    def test_proposals_csv_to_json_format(self, tmp_path):
        """Verify proposals.csv converts to GitHub Pages proposals.json format."""
        from ai_superpower.sync_gh_pages import csv_to_gh_pages_proposals_json

        csv_path = tmp_path / "proposals.csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "title", "owner", "status", "project_id", "project_name",
                "stage", "last_update", "prd_confirmation", "tech_expectations",
                "acceptance", "git_repo", "deployment_url"
            ])
            writer.writeheader()
            writer.writerow({
                "id": "P-20250524-001",
                "title": "Test Proposal",
                "owner": "alice",
                "status": "in_dev",
                "project_id": "PRJ-20250524-001",
                "project_name": "Test Project",
                "stage": "development",
                "last_update": "2025-05-24",
                "prd_confirmation": "confirmed",
                "tech_expectations": "pending",
                "acceptance": "pending",
                "git_repo": "https://github.com/test/repo",
                "deployment_url": "https://test-app.example.com",
            })

        result = csv_to_gh_pages_proposals_json(str(csv_path))

        assert len(result) == 1
        item = result[0]
        assert item["id"] == "P-20250524-001"
        assert item["name"] == "Test Proposal"
        assert item["type"] == "proposal"
        assert item["status"] == "in_dev"
        assert item["url"] == "https://test-app.example.com"
        assert item["gitRepo"] == "https://github.com/test/repo"
        assert item["tags"] == []
        assert item["createdAt"] == "2025-05-24"
        assert item["updatedAt"] == "2025-05-24"
        assert item["prdConfirmation"] == "confirmed"
        assert item["techExpectations"] == "pending"
        assert item["acceptance"] == "pending"

    def test_projects_csv_to_json_format(self, tmp_path):
        """Verify projects.csv converts to GitHub Pages projects.json format."""
        from ai_superpower.sync_gh_pages import csv_to_gh_pages_projects_json

        csv_path = tmp_path / "projects.csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "name", "proposal_count", "git_repo", "local_path",
                "description", "last_update", "create_at", "prj_url",
                "sync_enabled", "sync_last_run"
            ])
            writer.writeheader()
            writer.writerow({
                "id": "PRJ-20250524-001",
                "name": "Test Project",
                "proposal_count": "2",
                "git_repo": "https://github.com/test/project",
                "local_path": "/path/to/project",
                "description": "A test project",
                "last_update": "2025-05-24",
                "create_at": "2025-05-01",
                "prj_url": "https://test-project.example.com",
                "sync_enabled": "false",
                "sync_last_run": "",
            })

        result = csv_to_gh_pages_projects_json(str(csv_path))

        assert len(result) == 1
        item = result[0]
        assert item["id"] == "PRJ-20250524-001"
        assert item["name"] == "Test Project"
        assert item["description"] == "A test project"
        assert item["gitRepo"] == "https://github.com/test/project"
        assert item["url"] == "https://test-project.example.com"
        assert item["proposalCount"] == 2
        assert item["syncEnabled"] is False
        assert item["updatedAt"] == "2025-05-24"

    def test_csv_to_json_empty_proposals(self, tmp_path):
        """Empty proposals.csv returns empty array."""
        from ai_superpower.sync_gh_pages import csv_to_gh_pages_proposals_json

        csv_path = tmp_path / "empty.csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "title", "owner", "status", "project_id", "project_name",
                "stage", "last_update", "prd_confirmation", "tech_expectations",
                "acceptance", "git_repo", "deployment_url"
            ])
            writer.writeheader()

        result = csv_to_gh_pages_proposals_json(str(csv_path))
        assert result == []

    def test_csv_to_json_empty_projects(self, tmp_path):
        """Empty projects.csv returns empty array."""
        from ai_superpower.sync_gh_pages import csv_to_gh_pages_projects_json

        csv_path = tmp_path / "empty.csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "name", "proposal_count", "git_repo", "local_path",
                "description", "last_update", "create_at", "prj_url",
                "sync_enabled", "sync_last_run"
            ])
            writer.writeheader()

        result = csv_to_gh_pages_projects_json(str(csv_path))
        assert result == []


# ─── export_to_github_pages Tests ──────────────────────────────────────────────

class TestExportToGithubPages:
    """Test export_to_github_pages() function."""

    def test_export_generates_three_json_files(self, tmp_path, export_config):
        """export_to_github_pages generates proposals.json, projects.json, export_info.json."""
        from ai_superpower.sync_gh_pages import export_to_github_pages

        # Create a proposal in the storage
        export_storage = export_config  # already a config

        with patch("ai_superpower.sync_gh_pages.requests.get") as mock_get, \
             patch("ai_superpower.sync_gh_pages.requests.put") as mock_put:
            # Mock gh-pages branch ref (404 = new branch)
            mock_get.return_value = MagicMock(status_code=404)
            # Mock successful file creation
            mock_put.return_value = MagicMock(status_code=201, json=lambda: {"commit": {}})

            result = export_to_github_pages(
                storage=type('Storage', (), {
                    'config': type('Config', (), {
                        'projects_csv': export_config.projects_csv,
                        'proposals_csv': export_config.proposals_csv,
                    })()
                })(),
                target_repo="YeLuo45/ai-superpower",
                api_key="test-token"
            )

            assert result["success"] is True
            assert result["files_created"] == 3  # proposals.json, projects.json, export_info.json

    def test_export_with_empty_db(self, tmp_path):
        """Export with empty CSV files succeeds with empty arrays."""
        from ai_superpower.sync_gh_pages import export_to_github_pages

        # Create empty CSV files
        proposals_csv = tmp_path / "proposals.csv"
        projects_csv = tmp_path / "projects.csv"
        with open(proposals_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "title", "owner", "status", "project_id", "project_name",
                "stage", "last_update", "prd_confirmation", "tech_expectations",
                "acceptance", "git_repo", "deployment_url"
            ])
            writer.writeheader()
        with open(projects_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "name", "proposal_count", "git_repo", "local_path",
                "description", "last_update", "create_at", "prj_url",
                "sync_enabled", "sync_last_run"
            ])
            writer.writeheader()

        with patch("ai_superpower.sync_gh_pages.requests.get") as mock_get, \
             patch("ai_superpower.sync_gh_pages.requests.put") as mock_put:
            mock_get.return_value = MagicMock(status_code=404)
            mock_put.return_value = MagicMock(status_code=201, json=lambda: {"commit": {}})

            result = export_to_github_pages(
                storage=type('Storage', (), {
                    'config': type('Config', (), {
                        'projects_csv': str(projects_csv),
                        'proposals_csv': str(proposals_csv),
                    })()
                })(),
                target_repo="YeLuo45/ai-superpower",
                api_key="test-token"
            )

            assert result["success"] is True


# ─── API Endpoint Tests ────────────────────────────────────────────────────────

class TestSyncExport:
    """Test POST /api/sync/export endpoint."""

    def _get_project_id(self, client):
        r = client.get("/api/projects", headers=AUTH_HEADER)
        return r.json()["items"][0]["id"]

    def test_sync_export_returns_202(self, export_client):
        """POST /api/sync/export returns 202 Accepted."""
        with patch("ai_superpower.sync_gh_pages.requests.get") as mock_get, \
             patch("ai_superpower.sync_gh_pages.requests.put") as mock_put:
            mock_get.return_value = MagicMock(status_code=404)
            mock_put.return_value = MagicMock(status_code=201, json=lambda: {"commit": {}})

            r = export_client.post("/api/sync/export", headers=AUTH_HEADER)
            assert r.status_code == 202

    def test_sync_export_triggers_gh_pages_sync(self, export_client):
        """POST /api/sync/export triggers GitHub Pages export."""
        project_id = self._get_project_id(export_client)

        # Create a proposal
        export_client.post("/api/proposals", json={
            "title": "Export Test Proposal",
            "owner": "alice",
            "project_id": project_id,
            "stage": "ideation",
        }, headers=AUTH_HEADER)

        with patch("ai_superpower.sync_gh_pages.requests.get") as mock_get, \
             patch("ai_superpower.sync_gh_pages.requests.put") as mock_put:
            mock_get.return_value = MagicMock(status_code=404)
            mock_put.return_value = MagicMock(status_code=201, json=lambda: {"commit": {}})

            r = export_client.post("/api/sync/export", headers=AUTH_HEADER)
            assert r.status_code == 202
            data = r.json()
            assert data.get("status") == "accepted"


class TestExportStatus:
    """Test GET /api/sync/export-status endpoint."""

    def test_export_status_returns_expected_fields(self, export_client):
        """GET /api/sync/export-status returns export_last_run and export_status."""
        r = export_client.get("/api/sync/export-status", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()

        assert "export_last_run" in data
        assert "export_status" in data
        assert "proposals_count" in data
        assert "projects_count" in data

    def test_export_status_export_status_values(self, export_client):
        """export_status is one of: idle, running, done, error."""
        r = export_client.get("/api/sync/export-status", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()

        assert data["export_status"] in {"idle", "running", "done", "error"}

    def test_export_status_counts_match_storage(self, export_client):
        """proposals_count and projects_count match actual storage counts."""
        # Create a project (already done in fixture) and a proposal
        project_id = export_client.get("/api/projects", headers=AUTH_HEADER).json()["items"][0]["id"]
        export_client.post("/api/proposals", json={
            "title": "Status Test Proposal",
            "owner": "bob",
            "project_id": project_id,
            "stage": "ideation",
        }, headers=AUTH_HEADER)

        r = export_client.get("/api/sync/export-status", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()

        assert data["proposals_count"] == 1
        assert data["projects_count"] == 1

    def test_export_status_after_export_shows_done(self, export_client):
        """After successful export, export_status shows 'done'."""
        project_id = export_client.get("/api/projects", headers=AUTH_HEADER).json()["items"][0]["id"]
        export_client.post("/api/proposals", json={
            "title": "Done Test Proposal",
            "owner": "bob",
            "project_id": project_id,
            "stage": "ideation",
        }, headers=AUTH_HEADER)

        with patch("ai_superpower.sync_gh_pages.requests.get") as mock_get, \
             patch("ai_superpower.sync_gh_pages.requests.put") as mock_put:
            mock_get.return_value = MagicMock(status_code=404)
            mock_put.return_value = MagicMock(status_code=201, json=lambda: {"commit": {}})

            export_client.post("/api/sync/export", headers=AUTH_HEADER)

        r = export_client.get("/api/sync/export-status", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()

        assert data["export_status"] == "done"
        assert data["export_last_run"] != ""


# ─── JSON Format Validation Tests ──────────────────────────────────────────────

class TestGhPagesJsonFormat:
    """Validate the JSON format matches the specified structure."""

    def test_proposals_json_structure(self, tmp_path):
        """proposals.json has correct structure per spec."""
        from ai_superpower.sync_gh_pages import csv_to_gh_pages_proposals_json

        csv_path = tmp_path / "proposals.csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "title", "owner", "status", "project_id", "project_name",
                "stage", "last_update", "prd_confirmation", "tech_expectations",
                "acceptance", "git_repo", "deployment_url"
            ])
            writer.writeheader()
            writer.writerow({
                "id": "P-20250524-001",
                "title": "Test Proposal",
                "owner": "alice",
                "status": "in_dev",
                "project_id": "PRJ-20250524-001",
                "project_name": "Test Project",
                "stage": "development",
                "last_update": "2025-05-24T10:30:00",
                "prd_confirmation": "confirmed",
                "tech_expectations": "pending",
                "acceptance": "pending",
                "git_repo": "https://github.com/test/repo",
                "deployment_url": "https://test-app.example.com",
            })

        result = csv_to_gh_pages_proposals_json(str(csv_path))
        json_str = json.dumps(result, ensure_ascii=False)

        # Verify it's valid JSON
        parsed = json.loads(json_str)
        assert len(parsed) == 1

        # Verify required fields present
        item = parsed[0]
        required_fields = ["id", "name", "type", "status", "url", "gitRepo", "tags",
                          "createdAt", "updatedAt", "prdConfirmation", "techExpectations", "acceptance"]
        for field in required_fields:
            assert field in item, f"Missing field: {field}"

    def test_projects_json_structure(self, tmp_path):
        """projects.json has correct structure per spec."""
        from ai_superpower.sync_gh_pages import csv_to_gh_pages_projects_json

        csv_path = tmp_path / "projects.csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "name", "proposal_count", "git_repo", "local_path",
                "description", "last_update", "create_at", "prj_url",
                "sync_enabled", "sync_last_run"
            ])
            writer.writeheader()
            writer.writerow({
                "id": "PRJ-20250524-001",
                "name": "Test Project",
                "proposal_count": "5",
                "git_repo": "https://github.com/test/project",
                "local_path": "/path/to/project",
                "description": "A test project",
                "last_update": "2025-05-24T10:30:00",
                "create_at": "2025-05-01T08:00:00",
                "prj_url": "https://test.example.com",
                "sync_enabled": "true",
                "sync_last_run": "2025-05-24T12:00:00",
            })

        result = csv_to_gh_pages_projects_json(str(csv_path))
        json_str = json.dumps(result, ensure_ascii=False)

        parsed = json.loads(json_str)
        assert len(parsed) == 1

        item = parsed[0]
        required_fields = ["id", "name", "description", "gitRepo", "url", "updatedAt", "proposalCount", "syncEnabled"]
        for field in required_fields:
            assert field in item, f"Missing field: {field}"

    def test_export_info_json_structure(self, tmp_path):
        """export_info.json has correct structure per spec."""
        from ai_superpower.sync_gh_pages import generate_export_info

        info = generate_export_info(proposals_count=10, projects_count=3)
        json_str = json.dumps(info, ensure_ascii=False)

        parsed = json.loads(json_str)
        assert "exported_at" in parsed
        assert "version" in parsed
        assert parsed["proposals_count"] == 10
        assert parsed["projects_count"] == 3
        assert parsed["version"] == "1.0"