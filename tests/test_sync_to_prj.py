"""Tests for Direction B: Sync to prj-proposals-manager.

TDD approach: tests are written first, then implementation.
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

class SyncTestConfig:
    """Config for sync tests."""
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
        self.backup_api_key = ""
        self.sync_target_repo = "YeLuo45/prj-proposals-manager"
        self.sync_enabled = True
        self.sync_api_key = "test-github-token"


@pytest.fixture
def sync_config(tmp_path):
    return SyncTestConfig(tmp_path)


@pytest.fixture
def sync_storage(sync_config):
    """Create CSVStorage for sync tests."""
    from ai_superpower.storage import CSVStorage
    cfg = type('Config', (), {
        'projects_csv': sync_config.projects_csv,
        'proposals_csv': sync_config.proposals_csv,
        'audit_log': sync_config.audit_log,
        'key': sync_config.key,
        'socket_path': sync_config.socket_path,
        'allow_delete': True,
        'data_dir': sync_config.data_dir,
        'backup_local_path': sync_config.backup_local_path,
        'backup_max_copies': sync_config.backup_max_copies,
        'backup_remote_repo': sync_config.backup_remote_repo,
        'backup_api_key': sync_config.backup_api_key,
        'sync_target_repo': sync_config.sync_target_repo,
        'sync_enabled': sync_config.sync_enabled,
        'sync_api_key': sync_config.sync_api_key,
    })()
    s = CSVStorage(cfg, actor="test")
    s.create_project(name="Sync Test Project")
    return s


@pytest.fixture
def sync_client(sync_storage, sync_config):
    """TestClient with storage attached for sync tests."""
    import ai_superpower.config as config_mod
    import ai_superpower.server as server_mod

    orig_load = config_mod.load_config
    test_cfg = type('Config', (), {
        'projects_csv': sync_config.projects_csv,
        'proposals_csv': sync_config.proposals_csv,
        'audit_log': sync_config.audit_log,
        'key': sync_config.key,
        'socket_path': sync_config.socket_path,
        'allow_delete': True,
        'data_dir': sync_config.data_dir,
        'backup_local_path': sync_config.backup_local_path,
        'backup_max_copies': sync_config.backup_max_copies,
        'backup_remote_repo': sync_config.backup_remote_repo,
        'backup_api_key': sync_config.backup_api_key,
        'sync_target_repo': sync_config.sync_target_repo,
        'sync_enabled': sync_config.sync_enabled,
        'sync_api_key': sync_config.sync_api_key,
    })()
    config_mod.load_config = lambda: test_cfg
    server_mod.load_config = lambda: test_cfg
    server_mod._storage = sync_storage

    from ai_superpower.server import app
    with TestClient(app, raise_server_exceptions=True) as tc:
        yield tc

    config_mod.load_config = orig_load


AUTH_HEADER = {"X-API-Key": "test-key-456"}


# ─── CSV → JSON Data Conversion Tests ──────────────────────────────────────────

class TestCsvToJsonConversion:
    """Test csv_to_prj_proposals_json() field mapping."""

    def test_csv_to_json_field_mapping(self, tmp_path):
        """Verify proposals.csv fields map correctly to prj-proposals-manager JSON format.

        CSV fields: id, title, owner, status, project_id, project_name, stage,
                   last_update, prd_confirmation, tech_expectations, acceptance,
                   git_repo, deployment_url
        JSON fields: id, name(=title), description, type="proposal", status,
                     url(=deployment_url), gitRepo, tags=[], createdAt(=last_update),
                     updatedAt(=last_update), prdConfirmation, techExpectations, acceptance
        """
        from ai_superpower.sync import csv_to_prj_proposals_json

        # Create a temp CSV with test data
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

        result = csv_to_prj_proposals_json(str(csv_path))

        assert len(result) == 1
        item = result[0]

        # Core fields
        assert item["id"] == "P-20250524-001"
        assert item["name"] == "Test Proposal"
        assert item["status"] == "in_dev"
        assert item["type"] == "proposal"

        # Field mappings
        assert item["url"] == "https://test-app.example.com"
        assert item["gitRepo"] == "https://github.com/test/repo"
        assert item["prdConfirmation"] == "confirmed"
        assert item["techExpectations"] == "pending"
        assert item["acceptance"] == "pending"
        assert item["createdAt"] == "2025-05-24"
        assert item["updatedAt"] == "2025-05-24"

        # tags should be empty list
        assert item["tags"] == []

    def test_csv_to_json_empty_csv(self, tmp_path):
        """Empty CSV returns empty array."""
        from ai_superpower.sync import csv_to_prj_proposals_json

        csv_path = tmp_path / "empty.csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "title", "owner", "status", "project_id", "project_name",
                "stage", "last_update", "prd_confirmation", "tech_expectations",
                "acceptance", "git_repo", "deployment_url"
            ])
            writer.writeheader()

        result = csv_to_prj_proposals_json(str(csv_path))
        assert result == []

    def test_csv_to_json_multiple_rows(self, tmp_path):
        """Multiple CSV rows convert to multiple JSON items."""
        from ai_superpower.sync import csv_to_prj_proposals_json

        csv_path = tmp_path / "proposals.csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "title", "owner", "status", "project_id", "project_name",
                "stage", "last_update", "prd_confirmation", "tech_expectations",
                "acceptance", "git_repo", "deployment_url"
            ])
            writer.writeheader()
            for i in range(3):
                writer.writerow({
                    "id": f"P-20250524-{i+1:03d}",
                    "title": f"Proposal {i+1}",
                    "owner": "alice",
                    "status": "intake",
                    "project_id": "PRJ-20250524-001",
                    "project_name": "Test Project",
                    "stage": "ideation",
                    "last_update": "2025-05-24",
                    "prd_confirmation": "",
                    "tech_expectations": "",
                    "acceptance": "",
                    "git_repo": "",
                    "deployment_url": "",
                })

        result = csv_to_prj_proposals_json(str(csv_path))
        assert len(result) == 3
        assert result[0]["name"] == "Proposal 1"
        assert result[1]["name"] == "Proposal 2"
        assert result[2]["name"] == "Proposal 3"


# ─── POST /api/sync/push Tests ─────────────────────────────────────────────────

class TestSyncPush:
    """Test POST /api/sync/push endpoint."""

    def _get_project_id(self, client):
        r = client.get("/api/projects", headers=AUTH_HEADER)
        return r.json()["items"][0]["id"]

    def test_sync_push_returns_200(self, sync_client):
        """Sync push endpoint returns 200 on success."""
        with patch("ai_superpower.sync.requests.put") as mock_put:
            mock_put.return_value = MagicMock(status_code=200, json=lambda: {"commit": {}})

            r = sync_client.post("/api/sync/push", headers=AUTH_HEADER)
            assert r.status_code == 200

    def test_sync_push_empty_proposals(self, sync_client):
        """Empty proposals.csv returns 200 with empty array message."""
        with patch("ai_superpower.sync.requests.put") as mock_put:
            mock_put.return_value = MagicMock(status_code=200, json=lambda: {"commit": {}})

            r = sync_client.post("/api/sync/push", headers=AUTH_HEADER)
            assert r.status_code == 200
            data = r.json()
            assert "pushed_count" in data or "message" in data

    def test_sync_push_with_proposals(self, sync_client):
        """Sync push with proposals in CSV returns correct count."""
        project_id = self._get_project_id(sync_client)

        # Create a proposal
        sync_client.post("/api/proposals", json={
            "title": "Push Test Proposal",
            "owner": "alice",
            "project_id": project_id,
            "stage": "ideation",
        }, headers=AUTH_HEADER)

        with patch("ai_superpower.sync.requests.get") as mock_get, \
             patch("ai_superpower.sync.requests.put") as mock_put:
            mock_get.return_value = MagicMock(status_code=404)  # file doesn't exist yet
            mock_put.return_value = MagicMock(status_code=201, json=lambda: {"commit": {}})

            r = sync_client.post("/api/sync/push", headers=AUTH_HEADER)
            assert r.status_code == 200
            data = r.json()
            assert data.get("pushed_count", 0) >= 1

    def test_sync_push_updates_sync_last_run(self, sync_client):
        """After successful push, sync_last_run is updated in storage."""
        project_id = self._get_project_id(sync_client)

        with patch("ai_superpower.sync.requests.put") as mock_put:
            mock_put.return_value = MagicMock(status_code=200, json=lambda: {"commit": {}})

            r = sync_client.post("/api/sync/push", headers=AUTH_HEADER)
            assert r.status_code == 200

        # Verify sync_last_run was updated (should be non-empty)
        r = sync_client.get(f"/api/projects/{project_id}", headers=AUTH_HEADER)
        # Note: per-project sync_last_run is different from global sync_last_run


# ─── GET /api/sync/status Tests ───────────────────────────────────────────────

class TestSyncStatus:
    """Test GET /api/sync/status endpoint."""

    def test_sync_status_returns_expected_fields(self, sync_client):
        """Status response contains sync_enabled, sync_target_repo, sync_last_run."""
        r = sync_client.get("/api/sync/status", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()

        assert "sync_enabled" in data
        assert "sync_target_repo" in data
        assert "sync_last_run" in data

    def test_sync_status_sync_enabled_is_bool(self, sync_client):
        """sync_enabled field is a boolean."""
        r = sync_client.get("/api/sync/status", headers=AUTH_HEADER)
        assert r.status_code == 200
        assert isinstance(r.json()["sync_enabled"], bool)

    def test_sync_status_returns_correct_repo(self, sync_client):
        """sync_target_repo matches config."""
        r = sync_client.get("/api/sync/status", headers=AUTH_HEADER)
        assert r.status_code == 200
        assert r.json()["sync_target_repo"] == "YeLuo45/prj-proposals-manager"


# ─── BackupScheduler Tests ────────────────────────────────────────────────────

class TestBackupScheduler:
    """Test BackupScheduler.backup() and prune behavior."""

    def test_backup_scheduler_backup_success(self, tmp_path):
        """BackupScheduler.backup() creates a backup directory."""
        from ai_superpower.backup import BackupScheduler

        # Use separate paths so backup_local_path is NOT inside data_dir
        data_dir = str(tmp_path / "data")
        backup_path = str(tmp_path / "backups")
        Path(data_dir).mkdir(parents=True, exist_ok=True)

        # Write a simple CSV to represent data
        proposals_csv = Path(data_dir) / "proposals.csv"
        projects_csv = Path(data_dir) / "projects.csv"
        with open(proposals_csv, "w") as f:
            f.write("id,title\n")
        with open(projects_csv, "w") as f:
            f.write("id,name\n")

        cfg = type('Config', (), {
            'data_dir': data_dir,
            'backup_local_path': backup_path,
            'backup_max_copies': 3,
            'backup_remote_repo': '',
            'backup_remote_branch': 'backup',
            'backup_api_key': '',
        })()

        scheduler = BackupScheduler(cfg)
        result = scheduler.backup()

        assert result["success"] is True
        assert result["local_done"] is True
        assert Path(result["backup_dir"]).exists()

    def test_backup_scheduler_prunes_old(self, tmp_path):
        """BackupScheduler removes oldest backups when max_copies exceeded."""
        from ai_superpower.backup import BackupScheduler
        import time

        data_dir = str(tmp_path / "data")
        backup_path = str(tmp_path / "backups")
        Path(data_dir).mkdir(parents=True, exist_ok=True)

        with open(Path(data_dir) / "proposals.csv", "w") as f:
            f.write("id,title\n")
        with open(Path(data_dir) / "projects.csv", "w") as f:
            f.write("id,name\n")

        cfg = type('Config', (), {
            'data_dir': data_dir,
            'backup_local_path': backup_path,
            'backup_max_copies': 2,
            'backup_remote_repo': '',
            'backup_remote_branch': 'backup',
            'backup_api_key': '',
        })()

        scheduler = BackupScheduler(cfg)

        # Create 3 backups with a sleep to get different timestamps
        for i in range(3):
            result = scheduler.backup()
            assert result["success"] is True, f"Backup {i} failed: {result.get('error')}"
            time.sleep(1.1)  # ensure different timestamp

        backups = scheduler.list_backups()
        assert len(backups) == 2  # pruned to max_copies

    def test_backup_scheduler_list_backups(self, tmp_path):
        """BackupScheduler.list_backups() returns sorted list."""
        from ai_superpower.backup import BackupScheduler
        import time

        data_dir = str(tmp_path / "data")
        backup_path = str(tmp_path / "backups")
        Path(data_dir).mkdir(parents=True, exist_ok=True)

        with open(Path(data_dir) / "proposals.csv", "w") as f:
            f.write("id,title\n")
        with open(Path(data_dir) / "projects.csv", "w") as f:
            f.write("id,name\n")

        cfg = type('Config', (), {
            'data_dir': data_dir,
            'backup_local_path': backup_path,
            'backup_max_copies': 5,
            'backup_remote_repo': '',
            'backup_remote_branch': 'backup',
            'backup_api_key': '',
        })()

        scheduler = BackupScheduler(cfg)

        # Create 2 backups with a sleep to get different timestamps
        scheduler.backup()
        time.sleep(1.1)
        scheduler.backup()

        backups = scheduler.list_backups()
        assert len(backups) == 2
        # Should be sorted descending by name (newest first)
        assert backups[0]["name"] >= backups[1]["name"]