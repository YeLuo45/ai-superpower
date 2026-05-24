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
        self.key = "test-key-456"
        self.socket_path = str(tmp_path / "api.sock")
        self.allow_delete = True


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
    })()
    config_mod.load_config = lambda: test_cfg
    server_mod.load_config = lambda: test_cfg
    server_mod._storage = api_storage

    from ai_superpower.server import app
    with TestClient(app, raise_server_exceptions=True) as tc:
        yield tc

    config_mod.load_config = orig_load