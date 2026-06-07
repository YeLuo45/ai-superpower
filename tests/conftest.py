"""Shared pytest fixtures for ai-superpower tests."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from starlette.testclient import TestClient
from ai_superpower.storage import CSVStorage


class TempStorageConfig:
    """Ephemeral config for tests — uses temp files."""
    def __init__(self, tmp_path):
        self.projects_csv = str(tmp_path / "projects.csv")
        self.proposals_csv = str(tmp_path / "proposals.csv")
        self.audit_log = str(tmp_path / "audit.log")
        self.data_dir = str(tmp_path)  # needed by _auto_backup_if_needed
        self.key = "test-key-456"
        self.socket_path = str(tmp_path / "api.sock")
        self.allow_delete = True
        # Sync fields
        self.sync_enabled = False
        self.sync_last_run = ""
        self.sync_target_repo = ""
        self.sync_prj_repo = ""
        self.sync_api_key = ""
        self.sync_interval_minutes = 0
        # Backup fields
        self.backup_enabled = False
        self.backup_frequency = "1h"
        self.backup_max_copies = 48
        self.backup_local_path = str(tmp_path / "backups")
        self.backup_remote_repo = ""
        self.backup_remote_branch = "backup"
        self.backup_api_key = ""
        self.auto_backup_threshold = 5


@pytest.fixture
def tmp_config(tmp_path):
    return TempStorageConfig(tmp_path)


@pytest.fixture
def storage(tmp_config):
    """Create CSVStorage with temporary files."""
    s = CSVStorage(tmp_config, actor="test")
    s.create_project(name="Test Project")
    return s


class APITestConfig:
    """Config for API-level test fixtures."""
    def __init__(self, tmp_path):
        self.projects_csv = str(tmp_path / "projects.csv")
        self.proposals_csv = str(tmp_path / "proposals.csv")
        self.audit_log = str(tmp_path / "audit.log")
        self.key = "test-key-456"
        self.socket_path = str(tmp_path / "api.sock")
        self.allow_delete = True
        # Sync fields
        self.sync_enabled = False
        self.sync_last_run = ""
        self.sync_target_repo = ""
        self.sync_prj_repo = ""
        self.sync_api_key = ""
        self.sync_interval_minutes = 0
        # Backup fields
        self.backup_enabled = False
        self.backup_frequency = "1h"
        self.backup_max_copies = 48
        self.backup_local_path = str(tmp_path / "backups")
        self.backup_remote_repo = ""
        self.backup_remote_branch = "backup"
        self.backup_api_key = ""
        self.auto_backup_threshold = 5


@pytest.fixture
def api_config(tmp_path):
    return APITestConfig(tmp_path)


@pytest.fixture
def api_storage(api_config):
    """Create CSVStorage for API tests."""
    from ai_superpower.storage import CSVStorage
    s = CSVStorage(api_config, actor="test")
    s.create_project(name="API Test Project")
    return s


@pytest.fixture
def api_client(api_storage, api_config):
    """TestClient with storage attached to app state."""
    import ai_superpower.config as config_mod
    import ai_superpower.server as server_mod

    orig_load = config_mod.load_config
    test_cfg = type('Config', (), {
        'projects_csv': api_config.projects_csv,
        'proposals_csv': api_config.proposals_csv,
        'audit_log': api_config.audit_log,
        'key': api_config.key,
        'socket_path': api_config.socket_path,
        'allow_delete': True,
        'sync_enabled': False,
        'sync_last_run': '',
        'sync_target_repo': '',
        'sync_prj_repo': '',
        'sync_api_key': '',
        'sync_interval_minutes': 0,
        'backup_enabled': False,
        'backup_frequency': '1h',
        'backup_max_copies': 48,
        'backup_local_path': api_config.backup_local_path,
        'backup_remote_repo': '',
        'backup_remote_branch': 'backup',
        'backup_api_key': '',
        'auto_backup_threshold': 5,
    })()
    config_mod.load_config = lambda: test_cfg
    server_mod.load_config = lambda: test_cfg
    server_mod._storage = api_storage

    # Suppress startup on_event warning — we bypass it by pre-setting _storage
    from ai_superpower.server import app
    with TestClient(app, raise_server_exceptions=True) as tc:
        yield tc

    config_mod.load_config = orig_load