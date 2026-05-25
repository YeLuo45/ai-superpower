"""Tests for sync settings V5 — config, API endpoints, frequency parsing."""
import os
import tempfile
from pathlib import Path

import pytest
from unittest.mock import patch, MagicMock


# ── _parse_frequency tests ───────────────────────────────────────────────────

def test_parse_frequency_1h():
    from ai_superpower.config import _parse_frequency
    assert _parse_frequency("1h") == 60

def test_parse_frequency_6h():
    from ai_superpower.config import _parse_frequency
    assert _parse_frequency("6h") == 360

def test_parse_frequency_12h():
    from ai_superpower.config import _parse_frequency
    assert _parse_frequency("12h") == 720

def test_parse_frequency_1d():
    from ai_superpower.config import _parse_frequency
    assert _parse_frequency("1d") == 1440

def test_parse_frequency_off():
    from ai_superpower.config import _parse_frequency
    assert _parse_frequency("off") == 0
    assert _parse_frequency("0") == 0
    assert _parse_frequency("disabled") == 0

def test_parse_frequency_minutes():
    from ai_superpower.config import _parse_frequency
    assert _parse_frequency("30m") == 30
    assert _parse_frequency("120m") == 120

def test_parse_frequency_invalid():
    from ai_superpower.config import _parse_frequency
    assert _parse_frequency("invalid") == 0
    assert _parse_frequency("") == 0


# ── Config load tests ─────────────────────────────────────────────────────────

def test_load_sync_section():
    """load_config should read [sync] section from TOML."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.toml"
        config_path.write_text("""
[api]
key = "testkey123"

[server]
host = "0.0.0.0"
port = 8000

[sync]
enabled = true
frequency = "6h"
target_repo = "TestOrg/test-repo"
api_key = "ghp_testkey"
prj_repo = "TestOrg/prj"
""")
        with patch("ai_superpower.config.CONFIG_PATH", config_path):
            from ai_superpower.config import load_config
            cfg = load_config()
            assert cfg.sync_enabled is True
            assert cfg.sync_interval_minutes == 360  # "6h" parsed to 360 min
            assert cfg.sync_target_repo == "TestOrg/test-repo"
            assert cfg.sync_api_key == "ghp_testkey"
            assert cfg.sync_prj_repo == "TestOrg/prj"


def test_load_sync_section_defaults():
    """Missing [sync] section should use defaults."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.toml"
        config_path.write_text("""
[api]
key = "testkey123"

[server]
""")
        with patch("ai_superpower.config.CONFIG_PATH", config_path):
            from ai_superpower.config import load_config
            cfg = load_config()
            assert cfg.sync_enabled is False
            assert cfg.sync_target_repo == ""
            assert cfg.sync_api_key == ""
            assert cfg.sync_interval_minutes == 0


# ── API endpoint tests ────────────────────────────────────────────────────────

def test_sync_config_response_fields():
    """SyncConfigResponse should have all V5 fields."""
    from ai_superpower.server import SyncConfigResponse
    resp = SyncConfigResponse(
        sync_target_repo="org/repo",
        sync_prj_repo="org/prj",
        sync_enabled=True,
        sync_frequency="6h",
        sync_interval_minutes=360,
        sync_api_key_masked="********",
    )
    assert resp.sync_target_repo == "org/repo"
    assert resp.sync_prj_repo == "org/prj"
    assert resp.sync_enabled is True
    assert resp.sync_frequency == "6h"
    assert resp.sync_interval_minutes == 360
    assert resp.sync_api_key_masked == "********"


def test_frequency_to_str():
    """_frequency_to_str should convert minutes back to strings."""
    from ai_superpower.server import _frequency_to_str
    assert _frequency_to_str(60) == "1h"
    assert _frequency_to_str(360) == "6h"
    assert _frequency_to_str(720) == "12h"
    assert _frequency_to_str(1440) == "1d"
    assert _frequency_to_str(0) == "off"
    assert _frequency_to_str(30) == "30m"


# ── Web context tests ──────────────────────────────────────────────────────────

def test_web_ctx_includes_sync_config():
    """_web_ctx should include sync_config dict."""
    from ai_superpower.server import _web_ctx
    from unittest.mock import MagicMock

    mock_request = MagicMock()
    mock_request.app = None

    with patch("ai_superpower.server.load_config") as mock_load:
        mock_cfg = MagicMock()
        mock_cfg.key = "testkey"
        mock_cfg.socket_path = "/var/run/api.sock"
        mock_cfg.data_dir = "/tmp/data"
        mock_cfg.projects_csv = "/tmp/data/projects.csv"
        mock_cfg.sync_target_repo = "Org/repo"
        mock_cfg.sync_prj_repo = "Org/prj"
        mock_cfg.sync_enabled = True
        mock_cfg.sync_interval_minutes = 360
        mock_cfg.sync_last_run = ""
        mock_load.return_value = mock_cfg

        ctx = _web_ctx(mock_request)
        assert "sync_config" in ctx
        assert ctx["sync_config"]["sync_target_repo"] == "Org/repo"
        assert ctx["sync_config"]["sync_prj_repo"] == "Org/prj"
        assert ctx["sync_config"]["sync_enabled"] is True
        assert ctx["sync_config"]["sync_frequency"] == "6h"
        assert ctx["sync_config"]["sync_interval_minutes"] == 360