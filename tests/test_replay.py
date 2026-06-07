"""Tests for replay.py — Replay (audit log replay)."""
import json, os, tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, Mock

import pytest

# ── Fixtures ────────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_audit(tmp_path):
    """A temporary audit log file."""
    p = tmp_path / "audit.log"
    p.write_text("")
    return p

# ── Replay.__init__ ─────────────────────────────────────────────────────────────

def test_init_dry_run_true_by_default():
    from ai_superpower.replay import Replay
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = "/tmp/nonexistent/audit.log"
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage"):
        r = Replay()
        assert r.dry_run is True

def test_init_respects_dry_run_flag():
    from ai_superpower.replay import Replay
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = "/tmp/nonexistent/audit.log"
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage"):
        r = Replay(dry_run=False)
        assert r.dry_run is False

# ── Replay.replay_from_file ────────────────────────────────────────────────────

def test_replay_file_not_found(tmp_audit):
    from ai_superpower.replay import Replay
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = str(tmp_audit)
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage"):
        r = Replay()
        r.replay_from_file(log_path="/nonexistent/audit.log")

def test_replay_no_entries(tmp_audit):
    from ai_superpower.replay import Replay
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = str(tmp_audit)
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage"):
        r = Replay()
        r.replay_from_file()

def test_replay_with_entries_dry_run(tmp_audit):
    from ai_superpower.replay import Replay
    tmp_audit.write_text(
        json.dumps({"op":"UPDATE","entity":"project","id":"PRJ-001","field":"name","old":"OldName","new":"NewName","ts":"2025-01-01T00:00:00Z"}) + "\n"
    )
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = str(tmp_audit)
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage"):
        r = Replay(dry_run=True)
        r.replay_from_file()

def test_replay_filter_by_entity_id(tmp_audit):
    from ai_superpower.replay import Replay
    tmp_audit.write_text(
        json.dumps({"op":"UPDATE","entity":"project","id":"PRJ-001","field":"name","old":"O","new":"N","ts":"2025-01-01T00:00:00Z"}) + "\n"
        + json.dumps({"op":"UPDATE","entity":"project","id":"PRJ-002","field":"name","old":"O","new":"N","ts":"2025-01-01T00:00:01Z"}) + "\n"
    )
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = str(tmp_audit)
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage"):
        r = Replay(dry_run=True)
        r.replay_from_file(entity_id="PRJ-001")

def test_replay_filter_by_last_n(tmp_audit):
    from ai_superpower.replay import Replay
    for i in range(5):
        tmp_audit.write_text(
            tmp_audit.read_text()
            + json.dumps({"op":"UPDATE","entity":"project","id":"PRJ-001","field":"name","old":"O","new":"N","ts":"2025-01-01T00:00:00Z"}) + "\n"
        )
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = str(tmp_audit)
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage"):
        r = Replay(dry_run=True)
        r.replay_from_file(last_n=2)

def test_replay_filter_by_from_time(tmp_audit):
    from ai_superpower.replay import Replay
    tmp_audit.write_text(
        json.dumps({"op":"UPDATE","entity":"project","id":"PRJ-001","field":"name","old":"O","new":"N","ts":"2025-01-01T00:00:00Z"}) + "\n"
        + json.dumps({"op":"UPDATE","entity":"project","id":"PRJ-001","field":"name","old":"O","new":"N","ts":"2025-01-02T00:00:00Z"}) + "\n"
    )
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = str(tmp_audit)
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage"):
        r = Replay(dry_run=True)
        r.replay_from_file(from_time="2025-01-02T00:00:00Z")

def test_replay_skips_malformed_json(tmp_audit):
    from ai_superpower.replay import Replay
    tmp_audit.write_text(
        "not valid json\n"
        + json.dumps({"op":"UPDATE","entity":"project","id":"PRJ-001","field":"name","old":"O","new":"N","ts":"2025-01-01T00:00:00Z"}) + "\n"
    )
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = str(tmp_audit)
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage"):
        r = Replay(dry_run=True)
        r.replay_from_file()

# ── Replay.undo_last ───────────────────────────────────────────────────────────

def test_undo_last_no_file():
    from ai_superpower.replay import Replay
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = "/tmp/nonexistent/audit.log"
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage"):
        r = Replay()
        r.undo_last("PRJ-001")

def test_undo_last_entity_not_found(tmp_audit):
    from ai_superpower.replay import Replay
    tmp_audit.write_text(
        json.dumps({"op":"UPDATE","entity":"project","id":"PRJ-999","field":"name","old":"O","new":"N","ts":"2025-01-01T00:00:00Z"}) + "\n"
    )
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = str(tmp_audit)
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage"):
        r = Replay()
        r.undo_last("PRJ-001")

def test_undo_last_dry_run(tmp_audit):
    from ai_superpower.replay import Replay
    tmp_audit.write_text(
        json.dumps({"op":"UPDATE","entity":"project","id":"PRJ-001","field":"name","old":"OldName","new":"NewName","ts":"2025-01-01T00:00:00Z"}) + "\n"
    )
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = str(tmp_audit)
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage"):
        r = Replay(dry_run=True)
        r.undo_last("PRJ-001")

def test_undo_last_live(tmp_audit):
    from ai_superpower.replay import Replay
    tmp_audit.write_text(
        json.dumps({"op":"UPDATE","entity":"project","id":"PRJ-001","field":"name","old":"OldName","new":"NewName","ts":"2025-01-01T00:00:00Z"}) + "\n"
    )
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = str(tmp_audit)
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage"):
        r = Replay(dry_run=False)
        r.undo_last("PRJ-001")

# ── Replay._load_entries ───────────────────────────────────────────────────────

def test_load_entries_all(tmp_audit):
    from ai_superpower.replay import Replay
    for i in range(3):
        tmp_audit.write_text(
            tmp_audit.read_text()
            + json.dumps({"op":"UPDATE","entity":"project","id":"PRJ-001","field":"name","old":"O","new":"N","ts":"2025-01-01T00:00:00Z"}) + "\n"
        )
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = str(tmp_audit)
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage"):
        r = Replay()
        entries = r._load_entries(str(tmp_audit), None, None, None)
        assert len(entries) == 3

# ── Replay._apply_entry ───────────────────────────────────────────────────────

def test_apply_entry_update_dry_run():
    from ai_superpower.replay import Replay
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = "/tmp/nonexistent/audit.log"
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage"):
        r = Replay(dry_run=True)
        entry = {"op":"UPDATE","entity":"project","id":"PRJ-001","field":"name","old":"Old","new":"New","ts":"2025-01-01T00:00:00Z"}
        r._apply_entry(entry)

def test_apply_entry_delete_skip():
    from ai_superpower.replay import Replay
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = "/tmp/nonexistent/audit.log"
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage"):
        r = Replay(dry_run=True)
        entry = {"op":"DELETE","entity":"project","id":"PRJ-001","field":None,"old":"data","new":None,"ts":"2025-01-01T00:00:00Z"}
        r._apply_entry(entry)

def test_apply_entry_update_live():
    from ai_superpower.replay import Replay
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = "/tmp/nonexistent/audit.log"
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    storage_mock = MagicMock()
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage", return_value=storage_mock):
        r = Replay(dry_run=False)
        entry = {"op":"UPDATE","entity":"project","id":"PRJ-001","field":"name","old":"Old","new":"New","ts":"2025-01-01T00:00:00Z"}
        r._apply_entry(entry)
        storage_mock.update_project.assert_called_once_with("PRJ-001", {"name": "New"})

def test_apply_entry_proposal_update_live():
    from ai_superpower.replay import Replay
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = "/tmp/nonexistent/audit.log"
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    storage_mock = MagicMock()
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage", return_value=storage_mock):
        r = Replay(dry_run=False)
        entry = {"op":"UPDATE","entity":"proposal","id":"P-001","field":"stage","old":"draft","new":"review","ts":"2025-01-01T00:00:00Z"}
        r._apply_entry(entry)
        storage_mock.update_proposal.assert_called_once_with("P-001", {"stage": "review"})

# ── Replay._apply_reverse ──────────────────────────────────────────────────────

def test_apply_reverse_update():
    from ai_superpower.replay import Replay
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = "/tmp/nonexistent/audit.log"
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    storage_mock = MagicMock()
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage", return_value=storage_mock):
        r = Replay(dry_run=False)
        entry = {"op":"UPDATE","entity":"project","id":"PRJ-001","field":"name","old":"OldName","new":"NewName","ts":"2025-01-01T00:00:00Z"}
        r._apply_reverse(entry)
        storage_mock.update_project.assert_called_once_with("PRJ-001", {"name": "OldName"})

def test_apply_reverse_create_undo():
    from ai_superpower.replay import Replay
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = "/tmp/nonexistent/audit.log"
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    storage_mock = MagicMock()
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage", return_value=storage_mock):
        r = Replay(dry_run=False)
        entry = {"op":"CREATE","entity":"project","id":"PRJ-001","field":None,"old":None,"new":None,"ts":"2025-01-01T00:00:00Z"}
        r._apply_reverse(entry)
        storage_mock.delete_project.assert_called_once_with("PRJ-001")

def test_apply_reverse_delete_skipped():
    from ai_superpower.replay import Replay
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = "/tmp/nonexistent/audit.log"
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    storage_mock = MagicMock()
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage", return_value=storage_mock):
        r = Replay(dry_run=False)
        entry = {"op":"DELETE","entity":"project","id":"PRJ-001","field":None,"old":"data","new":None,"ts":"2025-01-01T00:00:00Z"}
        r._apply_reverse(entry)

def test_apply_reverse_proposal_update():
    from ai_superpower.replay import Replay
    mock_cfg = MagicMock()
    mock_cfg.data_dir = "/tmp/nonexistent"
    mock_cfg.audit_log = "/tmp/nonexistent/audit.log"
    mock_cfg.backup_local_path = "/tmp/backups"
    mock_cfg.backup_max_copies = 3
    mock_cfg.backup_remote_repo = ""
    mock_cfg.backup_remote_branch = "backup"
    mock_cfg.backup_api_key = ""
    storage_mock = MagicMock()
    with patch("ai_superpower.replay.load_config", return_value=mock_cfg),          patch("ai_superpower.replay.CSVStorage", return_value=storage_mock):
        r = Replay(dry_run=False)
        entry = {"op":"UPDATE","entity":"proposal","id":"P-001","field":"stage","old":"draft","new":"review","ts":"2025-01-01T00:00:00Z"}
        r._apply_reverse(entry)
        storage_mock.update_proposal.assert_called_once_with("P-001", {"stage": "draft"})


# ─── V5 B2 Coverage: replay.py lines 68, 71-72, 91, 121, 159, 167-169, 174-177, 205-206

class TestReplayEdgeCases:
    """Cover remaining miss lines in replay.py."""

    def test_undo_last_with_entity_filter(self, tmp_path):
        """Line 68: entity filter skips entries whose entity type doesn't match."""
        from ai_superpower.replay import Replay
        audit_log = tmp_path / "audit.log"
        audit_log.write_text(
            '{"op":"UPDATE","entity":"project","id":"X-1","field":"name","old":"a","new":"b","ts":"2025-01-01T00:00:00Z"}\n'
            '{"op":"UPDATE","entity":"proposal","id":"X-1","field":"title","old":"c","new":"d","ts":"2025-01-02T00:00:00Z"}\n'
        )
        # Pre-create storage files so Replay's __init__ -> CSVStorage succeeds
        (tmp_path / "projects.csv").write_text("id,name\n")
        (tmp_path / "proposals.csv").write_text("id,title\n")
        mock_cfg = MagicMock()
        mock_cfg.audit_log = str(audit_log)
        mock_cfg.data_dir = str(tmp_path)
        mock_cfg.projects_csv = str(tmp_path / "projects.csv")
        mock_cfg.proposals_csv = str(tmp_path / "proposals.csv")
        with patch("ai_superpower.replay.load_config", return_value=mock_cfg):
            r = Replay(dry_run=True)
            # Without filter: latest entry (proposal) is returned
            r1 = r.undo_last("X-1")
            assert r1["found"] is True
            assert r1["entry"]["entity"] == "proposal"
            # With entity="project" filter: older project entry is returned
            r2 = r.undo_last("X-1", entity="project")
            assert r2["found"] is True
            assert r2["entry"]["entity"] == "project"
            assert r2["entry"]["field"] == "name"

    def test_undo_last_skips_corrupted_audit_lines(self, tmp_path):
        """Lines 71-72: malformed JSON lines in audit log are silently skipped."""
        from ai_superpower.replay import Replay
        audit_log = tmp_path / "audit.log"
        audit_log.write_text(
            'this is not valid JSON\n'
            '{"op":"UPDATE","entity":"project","id":"X-1","field":"name","old":"a","new":"b","ts":"2025-01-01T00:00:00Z"}\n'
            '{also broken\n'
        )
        (tmp_path / "projects.csv").write_text("id,name\n")
        (tmp_path / "proposals.csv").write_text("id,title\n")
        mock_cfg = MagicMock()
        mock_cfg.audit_log = str(audit_log)
        mock_cfg.data_dir = str(tmp_path)
        mock_cfg.projects_csv = str(tmp_path / "projects.csv")
        mock_cfg.proposals_csv = str(tmp_path / "proposals.csv")
        with patch("ai_superpower.replay.load_config", return_value=mock_cfg):
            r = Replay(dry_run=True)
            result = r.undo_last("X-1")
            assert result["found"] is True
            assert result["entry"]["op"] == "UPDATE"

    def test_undo_last_dry_run_returns_dry_message(self, tmp_path):
        """Line 91: dry_run=True returns [DRY] Would undo message and does NOT call _apply_reverse."""
        from ai_superpower.replay import Replay
        audit_log = tmp_path / "audit.log"
        audit_log.write_text(
            '{"op":"UPDATE","entity":"project","id":"X-1","field":"name","old":"a","new":"b","ts":"2025-01-01T00:00:00Z"}\n'
        )
        (tmp_path / "projects.csv").write_text("id,name\n")
        (tmp_path / "proposals.csv").write_text("id,title\n")
        mock_cfg = MagicMock()
        mock_cfg.audit_log = str(audit_log)
        mock_cfg.data_dir = str(tmp_path)
        mock_cfg.projects_csv = str(tmp_path / "projects.csv")
        mock_cfg.proposals_csv = str(tmp_path / "proposals.csv")
        with patch("ai_superpower.replay.load_config", return_value=mock_cfg):
            r = Replay(dry_run=True)
            result = r.undo_last("X-1")
            assert result["success"] is True
            assert "[DRY] Would undo" in result["message"]
            assert result["warning"] is False

    def test_load_entries_skips_empty_and_corrupt_lines(self, tmp_path):
        """Line 121 (empty) + corrupted JSON skip in _load_entries."""
        from ai_superpower.replay import Replay
        audit_log = tmp_path / "audit.log"
        audit_log.write_text(
            '\n'
            '   \n'
            'garbage not json\n'
            '{"op":"UPDATE","entity":"project","id":"X-1","field":"name","old":"a","new":"b","ts":"2025-01-01T00:00:00Z"}\n'
            '\n'
        )
        (tmp_path / "projects.csv").write_text("id,name\n")
        (tmp_path / "proposals.csv").write_text("id,title\n")
        mock_cfg = MagicMock()
        mock_cfg.audit_log = str(audit_log)
        mock_cfg.data_dir = str(tmp_path)
        mock_cfg.projects_csv = str(tmp_path / "projects.csv")
        mock_cfg.proposals_csv = str(tmp_path / "proposals.csv")
        with patch("ai_superpower.replay.load_config", return_value=mock_cfg):
            r = Replay(dry_run=True)
            entries = r._load_entries(str(audit_log), from_time=None, last_n=None, entity_id=None)
            assert len(entries) == 1
            assert entries[0]["id"] == "X-1"

    def test_apply_entry_dry_run_with_no_old_no_new(self, capsys):
        """Line 159: dry_run when both old and new are None prints the generic op message."""
        from ai_superpower.replay import Replay
        mock_cfg = MagicMock()
        mock_cfg.data_dir = "/tmp/nonexistent"
        mock_cfg.audit_log = "/tmp/nonexistent/audit.log"
        storage_mock = MagicMock()
        with patch("ai_superpower.replay.load_config", return_value=mock_cfg), \
             patch("ai_superpower.replay.CSVStorage", return_value=storage_mock):
            r = Replay(dry_run=True)
            entry = {
                "op": "CREATE", "entity": "project", "id": "PRJ-1",
                "field": None, "old": None, "new": None,
                "ts": "2025-01-01T00:00:00Z",
            }
            r._apply_entry(entry)
            captured = capsys.readouterr()
            assert "[DRY] Would create" in captured.out

    def test_apply_entry_delete_project_logs_skip(self, capsys):
        """Lines 167-169: DELETE replay for project is a no-op with skip message."""
        from ai_superpower.replay import Replay
        mock_cfg = MagicMock()
        mock_cfg.data_dir = "/tmp/nonexistent"
        mock_cfg.audit_log = "/tmp/nonexistent/audit.log"
        storage_mock = MagicMock()
        with patch("ai_superpower.replay.load_config", return_value=mock_cfg), \
             patch("ai_superpower.replay.CSVStorage", return_value=storage_mock):
            r = Replay(dry_run=False)
            entry = {
                "op": "DELETE", "entity": "project", "id": "PRJ-1",
                "field": None, "old": None, "new": None,
                "ts": "2025-01-01T00:00:00Z",
            }
            r._apply_entry(entry)
            storage_mock.delete_project.assert_not_called()
            captured = capsys.readouterr()
            assert "[SKIP] DELETE replay for projects not yet implemented" in captured.out

    def test_apply_entry_delete_proposal_logs_skip(self, capsys):
        """Lines 174-175: DELETE replay for proposal is a no-op with skip message."""
        from ai_superpower.replay import Replay
        mock_cfg = MagicMock()
        mock_cfg.data_dir = "/tmp/nonexistent"
        mock_cfg.audit_log = "/tmp/nonexistent/audit.log"
        storage_mock = MagicMock()
        with patch("ai_superpower.replay.load_config", return_value=mock_cfg), \
             patch("ai_superpower.replay.CSVStorage", return_value=storage_mock):
            r = Replay(dry_run=False)
            entry = {
                "op": "DELETE", "entity": "proposal", "id": "P-1",
                "field": None, "old": None, "new": None,
                "ts": "2025-01-01T00:00:00Z",
            }
            r._apply_entry(entry)
            storage_mock.delete_proposal.assert_not_called()
            captured = capsys.readouterr()
            assert "[SKIP] DELETE replay for proposals not yet implemented" in captured.out

    def test_apply_entry_handles_storage_exceptions(self, capsys):
        """Line 176-177: storage.update_* exception during forward replay is caught and logged."""
        from ai_superpower.replay import Replay
        mock_cfg = MagicMock()
        mock_cfg.data_dir = "/tmp/nonexistent"
        mock_cfg.audit_log = "/tmp/nonexistent/audit.log"
        storage_mock = MagicMock()
        storage_mock.update_project.side_effect = RuntimeError("disk gone")
        with patch("ai_superpower.replay.load_config", return_value=mock_cfg), \
             patch("ai_superpower.replay.CSVStorage", return_value=storage_mock):
            r = Replay(dry_run=False)
            entry = {
                "op": "UPDATE", "entity": "project", "id": "PRJ-1",
                "field": "name", "old": "a", "new": "b",
                "ts": "2025-01-01T00:00:00Z",
            }
            r._apply_entry(entry)  # should not raise
            captured = capsys.readouterr()
            assert "[ERROR]" in captured.out

    def test_apply_reverse_handles_storage_exceptions(self, capsys):
        """Lines 205-206: storage.update_*/delete_* exception during reverse is caught and logged."""
        from ai_superpower.replay import Replay
        mock_cfg = MagicMock()
        mock_cfg.data_dir = "/tmp/nonexistent"
        mock_cfg.audit_log = "/tmp/nonexistent/audit.log"
        storage_mock = MagicMock()
        storage_mock.update_project.side_effect = RuntimeError("disk gone during undo")
        with patch("ai_superpower.replay.load_config", return_value=mock_cfg), \
             patch("ai_superpower.replay.CSVStorage", return_value=storage_mock):
            r = Replay(dry_run=False)
            entry = {
                "op": "UPDATE", "entity": "project", "id": "PRJ-1",
                "field": "name", "old": "a", "new": "b",
                "ts": "2025-01-01T00:00:00Z",
            }
            r._apply_reverse(entry)  # should not raise
            captured = capsys.readouterr()
            assert "[ERROR]" in captured.out
