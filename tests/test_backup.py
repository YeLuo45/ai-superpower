"""Tests for backup.py — BackupScheduler."""
import json, os, shutil, subprocess, tempfile, time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# ── Fixtures ────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_config(tmp_path):
    cfg = MagicMock()
    cfg.data_dir = str(tmp_path / "db")
    cfg.backup_local_path = str(tmp_path / "backups")
    cfg.backup_max_copies = 3
    cfg.backup_remote_repo = ""
    cfg.backup_remote_branch = "backup"
    cfg.backup_api_key = ""
    cfg.audit_log = str(tmp_path / "audit.log")
    return cfg

@pytest.fixture
def populated_db(tmp_path, mock_config):
    db = Path(mock_config.data_dir)
    db.mkdir(parents=True, exist_ok=True)
    (db / "projects.csv").write_text("id,name\nPRJ-001,Test\n")
    (db / "proposals.csv").write_text("id,project_id,title\nP-001,PRJ-001,Test\n")
    (db / "audit.log").write_text("")
    return mock_config

# ── BackupScheduler.__init__ ────────────────────────────────────────────────────

def test_init_loads_config(mock_config):
    from ai_superpower.backup import BackupScheduler
    bs = BackupScheduler(mock_config)
    assert bs.local_path == mock_config.backup_local_path
    assert bs.max_copies == mock_config.backup_max_copies

def test_init_defaults():
    from ai_superpower.backup import BackupScheduler
    cfg = MagicMock()
    cfg.data_dir = "/tmp/nonexistent"
    cfg.backup_local_path = "/tmp/backups"
    cfg.backup_max_copies = 3
    cfg.backup_remote_repo = ""
    cfg.backup_remote_branch = "backup"
    cfg.backup_api_key = ""
    cfg.audit_log = "/tmp/audit.log"
    with patch("ai_superpower.backup.load_config", return_value=cfg):
        bs = BackupScheduler()
        assert bs.local_path == cfg.backup_local_path

# ── BackupScheduler.backup (local) ──────────────────────────────────────────────

def test_backup_local_success(populated_db):
    from ai_superpower.backup import BackupScheduler
    bs = BackupScheduler(populated_db)
    result = bs.backup()
    assert result["local_done"] is True
    assert result["success"] is True
    assert Path(populated_db.backup_local_path).exists()

def test_backup_creates_subdirs(populated_db):
    from ai_superpower.backup import BackupScheduler
    bs = BackupScheduler(populated_db)
    bs.backup()
    backups = bs.list_backups()
    assert len(backups) == 1

def test_backup_local_failure():
    from ai_superpower.backup import BackupScheduler
    cfg = MagicMock()
    cfg.data_dir = "/nonexistent/path"
    cfg.backup_local_path = str(tempfile.mkdtemp())
    cfg.backup_max_copies = 3
    cfg.backup_remote_repo = ""
    cfg.backup_remote_branch = "backup"
    cfg.backup_api_key = ""
    cfg.audit_log = "/tmp/audit.log"
    bs = BackupScheduler(cfg)
    result = bs.backup()
    assert result["local_done"] is False
    assert result["success"] is False
    assert result["error"] is not None

def test_backup_remote_not_configured(populated_db):
    from ai_superpower.backup import BackupScheduler
    bs = BackupScheduler(populated_db)
    result = bs.backup()
    assert result["remote_done"] is False
    assert result["error"] is None

def test_backup_remote_failure_non_fatal(populated_db):
    from ai_superpower.backup import BackupScheduler
    cfg = MagicMock()
    cfg.data_dir = populated_db.data_dir
    cfg.backup_local_path = populated_db.backup_local_path
    cfg.backup_max_copies = 3
    cfg.backup_remote_repo = "https://github.com/nonexistent/repo.git"
    cfg.backup_remote_branch = "backup"
    cfg.backup_api_key = "fake_token"
    cfg.audit_log = populated_db.audit_log
    bs = BackupScheduler(cfg)
    def fake_push(*a, **k): raise RuntimeError("push failed")
    bs._git_push = fake_push
    result = bs.backup()
    assert result["local_done"] is True
    assert result["success"] is True
    assert result["error"] is not None

def test_backup_multiple_calls_increment_count(populated_db):
    """After N backups, list should return N entries (unique timestamps per call)."""
    from ai_superpower.backup import BackupScheduler
    import time
    bs = BackupScheduler(populated_db)
    initial = len(bs.list_backups())
    # Sleep 1 second between calls to get unique timestamps
    for i in range(3):
        bs.backup()
        time.sleep(1.01)
    backups = bs.list_backups()
    assert len(backups) == initial + 3

# ── BackupScheduler.list_backups ────────────────────────────────────────────────

def test_list_backups_empty(tmp_path):
    from ai_superpower.backup import BackupScheduler
    cfg = MagicMock()
    cfg.data_dir = str(tmp_path / "db")
    cfg.backup_local_path = str(tmp_path / "backups")
    cfg.backup_max_copies = 3
    cfg.backup_remote_repo = ""
    cfg.backup_remote_branch = "backup"
    cfg.backup_api_key = ""
    cfg.audit_log = str(tmp_path / "audit.log")
    bs = BackupScheduler(cfg)
    assert bs.list_backups() == []

def test_list_backups_sorted(tmp_path):
    from ai_superpower.backup import BackupScheduler
    cfg = MagicMock()
    cfg.data_dir = str(tmp_path / "db")
    cfg.backup_local_path = str(tmp_path / "backups")
    cfg.backup_max_copies = 3
    cfg.backup_remote_repo = ""
    cfg.backup_remote_branch = "backup"
    cfg.backup_api_key = ""
    cfg.audit_log = str(tmp_path / "audit.log")
    bs = BackupScheduler(cfg)
    bp = Path(cfg.backup_local_path)
    bp.mkdir(parents=True)
    (bp / "db_backup_20250101_000000").mkdir()
    (bp / "db_backup_20250102_000000").mkdir()
    backups = bs.list_backups()
    assert len(backups) == 2
    assert backups[0]["name"] > backups[1]["name"]

def test_list_backups_includes_size(tmp_path):
    from ai_superpower.backup import BackupScheduler
    cfg = MagicMock()
    cfg.data_dir = str(tmp_path / "db")
    cfg.backup_local_path = str(tmp_path / "backups")
    cfg.backup_max_copies = 3
    cfg.backup_remote_repo = ""
    cfg.backup_remote_branch = "backup"
    cfg.backup_api_key = ""
    cfg.audit_log = str(tmp_path / "audit.log")
    bs = BackupScheduler(cfg)
    bp = Path(cfg.backup_local_path)
    bp.mkdir(parents=True)
    (bp / "db_backup_20250101_000000").mkdir()
    (bp / "db_backup_20250101_000000/somefile.txt").write_text("hello")
    backups = bs.list_backups()
    assert backups[0]["size"] > 0

def test_list_backups_mtime(tmp_path):
    from ai_superpower.backup import BackupScheduler
    cfg = MagicMock()
    cfg.data_dir = str(tmp_path / "db")
    cfg.backup_local_path = str(tmp_path / "backups")
    cfg.backup_max_copies = 3
    cfg.backup_remote_repo = ""
    cfg.backup_remote_branch = "backup"
    cfg.backup_api_key = ""
    cfg.audit_log = str(tmp_path / "audit.log")
    bs = BackupScheduler(cfg)
    bp = Path(cfg.backup_local_path)
    bp.mkdir(parents=True)
    d = bp / "db_backup_20250101_000000"
    d.mkdir()
    backups = bs.list_backups()
    assert "mtime" in backups[0]

# ── BackupScheduler.restore ────────────────────────────────────────────────────

def test_restore_success(populated_db):
    """Restore should copy backup back to data_dir."""
    from ai_superpower.backup import BackupScheduler
    bs = BackupScheduler(populated_db)
    bs.backup()
    backups = bs.list_backups()
    backup_name = backups[0]["name"]
    data_dir = Path(populated_db.data_dir)
    # Patch both copytree calls (emergency backup + restore) since data_dir is fake
    with patch("ai_superpower.backup.shutil.copytree") as mock_ct:
        mock_ct.return_value = None
        result = bs.restore(backup_name)
        assert result is True
        # Verify copytree was called at least twice (emergency + restore)
        assert mock_ct.call_count >= 2

def test_restore_not_found(populated_db):
    from ai_superpower.backup import BackupScheduler
    bs = BackupScheduler(populated_db)
    result = bs.restore("nonexistent_backup_20250101_000000")
    assert result is False

# ── BackupScheduler._prune_old ──────────────────────────────────────────────────

def test_prune_old_keeps_max(tmp_path):
    from ai_superpower.backup import BackupScheduler
    cfg = MagicMock()
    cfg.data_dir = str(tmp_path / "db")
    cfg.backup_local_path = str(tmp_path / "backups")
    cfg.backup_max_copies = 2
    cfg.backup_remote_repo = ""
    cfg.backup_remote_branch = "backup"
    cfg.backup_api_key = ""
    cfg.audit_log = str(tmp_path / "audit.log")
    bs = BackupScheduler(cfg)
    bp = Path(cfg.backup_local_path)
    bp.mkdir(parents=True)
    for i, name in enumerate(["20250001", "20250002", "20250003", "20250004", "20250005"]):
        d = bp / f"db_backup_{name}_000000"
        d.mkdir()
        (d / "projects.csv").write_text("id\n")
        import time
        older_mtime = time.time() - (5 - i) * 86400
        os.utime(d, (older_mtime, older_mtime))
    bs._prune_old()
    remaining = bs.list_backups()
    assert len(remaining) == 2

def test_prune_old_no_op_when_within_limit(populated_db):
    from ai_superpower.backup import BackupScheduler
    bp = Path(populated_db.backup_local_path)
    for i in range(2):
        d = bp / f"db_backup_2025010{i}_000000"
        d.mkdir(parents=True)
        (d / "projects.csv").write_text("id\n")
    bs = BackupScheduler(populated_db)
    bs._prune_old()
    assert len(bs.list_backups()) == 2

# ── BackupScheduler._git_push ──────────────────────────────────────────────────

def test_git_push_inits_repo(tmp_path):
    """_git_push should init a repo if .git doesn't exist."""
    from ai_superpower.backup import BackupScheduler
    cfg = MagicMock()
    cfg.data_dir = str(tmp_path / "db")
    cfg.backup_local_path = str(tmp_path / "backups")
    cfg.backup_max_copies = 3
    cfg.backup_remote_repo = "https://github.com/test/repo.git"
    cfg.backup_remote_branch = "backup"
    cfg.backup_api_key = ""
    cfg.audit_log = str(tmp_path / "audit.log")
    bs = BackupScheduler(cfg)
    backup_dir = tmp_path / "test_backup"
    backup_dir.mkdir()
    (backup_dir / "data.txt").write_text("test")
    def fake_run(cmd, **kwargs):
        if cmd[0] == "git" and cmd[1] == "init":
            (backup_dir / ".git").mkdir()
            return MagicMock(returncode=0)
        return MagicMock(returncode=0)
    with patch("subprocess.run", side_effect=fake_run):
        bs._git_push(backup_dir, "https://github.com/test/repo.git")
    assert (backup_dir / ".git").exists()

def test_git_push_with_token(tmp_path):
    """_git_push should configure credential helper when token provided."""
    from ai_superpower.backup import BackupScheduler
    cfg = MagicMock()
    cfg.data_dir = str(tmp_path / "db")
    cfg.backup_local_path = str(tmp_path / "backups")
    cfg.backup_max_copies = 3
    cfg.backup_remote_repo = "https://github.com/test/repo.git"
    cfg.backup_remote_branch = "backup"
    cfg.backup_api_key = "fake_token"
    cfg.audit_log = str(tmp_path / "audit.log")
    bs = BackupScheduler(cfg)
    backup_dir = tmp_path / "test_backup2"
    backup_dir.mkdir()
    (backup_dir / "data.txt").write_text("test")
    called_cmds = []
    def fake_run(cmd, **kwargs):
        called_cmds.append(cmd[1] if len(cmd) > 1 else cmd[0])
        if cmd[0] == "git" and cmd[1] == "init":
            (backup_dir / ".git").mkdir()
            return MagicMock(returncode=0)
        return MagicMock(returncode=0)
    with patch("subprocess.run", side_effect=fake_run):
        bs._git_push(backup_dir, "https://github.com/test/repo.git")
    assert "config" in called_cmds
