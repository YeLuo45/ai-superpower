"""Tests for ai-superpower CLI entry point (cli.py).

Strategy: replace ``APIClient`` at the module level with a MagicMock so
each ``cmd_*`` function exercises its arg-parsing / dispatch logic without
making real HTTP requests. ``cmd_run`` and ``cmd_tui`` are skipped because
they spawn long-running processes (uvicorn / curses) that are out of scope
for unit tests — covered by manual smoke tests.
"""
import argparse
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ─── Project command handlers ───────────────────────────────────────────────


class TestCliProjectCommands:
    def test_cmd_project_create_calls_api(self, monkeypatch):
        from ai_superpower import cli
        mock_client = MagicMock()
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        args = argparse.Namespace(
            name="X", git_repo="https://x", local_path="/p", description="d",
            prj_url="https://example.com",
        )
        cli.cmd_project_create(args)
        mock_client.create_project.assert_called_once_with(
            name="X", git_repo="https://x", local_path="/p",
            description="d", prj_url="https://example.com",
        )

    def test_cmd_project_list_passes_args(self, monkeypatch):
        from ai_superpower import cli
        mock_client = MagicMock()
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        args = argparse.Namespace(
            page=2, page_size=20, search="foo", sort_by="name", sort_order="asc",
        )
        cli.cmd_project_list(args)
        mock_client.list_projects.assert_called_once_with(
            page=2, page_size=20, search="foo",
            sort_by="name", sort_order="asc",
        )

    def test_cmd_project_get(self, monkeypatch):
        from ai_superpower import cli
        mock_client = MagicMock()
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        args = argparse.Namespace(id="PRJ-1")
        cli.cmd_project_get(args)
        mock_client.get_project.assert_called_once_with("PRJ-1")

    def test_cmd_project_delete(self, monkeypatch):
        from ai_superpower import cli
        mock_client = MagicMock()
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        args = argparse.Namespace(id="PRJ-1")
        cli.cmd_project_delete(args)
        mock_client.delete_project.assert_called_once_with("PRJ-1")

    def test_cmd_project_sync_status(self, monkeypatch, capsys):
        from ai_superpower import cli
        mock_client = MagicMock()
        mock_client._do_request.return_value = {
            "project_id": "PRJ-1",
            "sync_enabled": True,
            "sync_last_run": "2026-06-01T00:00:00Z",
        }
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        args = argparse.Namespace(id="PRJ-1")
        cli._cmd_project_sync_status(args)
        captured = capsys.readouterr()
        assert "Project: PRJ-1" in captured.out
        assert "Sync enabled: True" in captured.out
        assert "Last sync: 2026-06-01T00:00:00Z" in captured.out

    def test_cmd_project_sync_status_never_ran(self, monkeypatch, capsys):
        """Empty sync_last_run prints 'never'."""
        from ai_superpower import cli
        mock_client = MagicMock()
        mock_client._do_request.return_value = {
            "project_id": "PRJ-1", "sync_enabled": False, "sync_last_run": "",
        }
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        args = argparse.Namespace(id="PRJ-1")
        cli._cmd_project_sync_status(args)
        captured = capsys.readouterr()
        assert "Last sync: never" in captured.out

    def test_cmd_project_sync_enable(self, monkeypatch, capsys):
        from ai_superpower import cli
        mock_client = MagicMock()
        mock_client._do_request.return_value = {
            "id": "PRJ-1", "sync_enabled": "true",
        }
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        args = argparse.Namespace(id="PRJ-1")
        cli._cmd_project_sync_enable(args, True)
        captured = capsys.readouterr()
        assert "PRJ-1" in captured.out
        mock_client._do_request.assert_called_once_with(
            "PUT", "/projects/PRJ-1/sync-enabled?enabled=True"
        )


# ─── Proposal command handlers ──────────────────────────────────────────────


class TestCliProposalCommands:
    def test_cmd_proposal_create_with_all_optional_fields(self, monkeypatch):
        from ai_superpower import cli
        mock_client = MagicMock()
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        args = argparse.Namespace(
            title="T", owner="boss", project_id="PRJ-1", stage="ideation",
            prd_path="p.md", tech_solution_path="t.md", project_path="/p",
            git_repo="https://g", deployment_url="https://d",
            engine="e", target="t", game_type="g", notes="n",
        )
        cli.cmd_proposal_create(args)
        # Verify all fields made it to the API call
        call_kwargs = mock_client.create_proposal.call_args.kwargs
        assert call_kwargs["title"] == "T"
        assert call_kwargs["owner"] == "boss"
        assert call_kwargs["project_id"] == "PRJ-1"
        assert call_kwargs["stage"] == "ideation"
        assert call_kwargs["prd_path"] == "p.md"
        assert call_kwargs["tech_solution_path"] == "t.md"
        assert call_kwargs["project_path"] == "/p"
        assert call_kwargs["git_repo"] == "https://g"
        assert call_kwargs["deployment_url"] == "https://d"
        assert call_kwargs["engine"] == "e"
        assert call_kwargs["target"] == "t"
        assert call_kwargs["game_type"] == "g"
        assert call_kwargs["notes"] == "n"

    def test_cmd_proposal_create_skips_empty_optionals(self, monkeypatch):
        """Empty string optional fields are not passed (avoids polluting payload)."""
        from ai_superpower import cli
        mock_client = MagicMock()
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        args = argparse.Namespace(
            title="T", owner="boss", project_id="PRJ-1", stage="ideation",
            prd_path="", tech_solution_path="", project_path="",
            git_repo="", deployment_url="",
            engine="", target="", game_type="", notes="",
        )
        cli.cmd_proposal_create(args)
        call_kwargs = mock_client.create_proposal.call_args.kwargs
        # Only the 4 required fields are present
        assert set(call_kwargs.keys()) == {"title", "owner", "project_id", "stage"}

    def test_cmd_proposal_list_passes_all_filters(self, monkeypatch):
        from ai_superpower import cli
        mock_client = MagicMock()
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        args = argparse.Namespace(
            page=1, page_size=10, project_id="PRJ-1", status="in_dev",
            owner="boss", search="foo", stage="ideation",
            sort_by="title", sort_order="asc",
        )
        cli.cmd_proposal_list(args)
        mock_client.list_proposals.assert_called_once_with(
            page=1, page_size=10, project_id="PRJ-1", status="in_dev",
            owner="boss", search="foo", stage="ideation",
            sort_by="title", sort_order="asc",
        )

    def test_cmd_proposal_get(self, monkeypatch):
        from ai_superpower import cli
        mock_client = MagicMock()
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        args = argparse.Namespace(id="P-1")
        cli.cmd_proposal_get(args)
        mock_client.get_proposal.assert_called_once_with("P-1")

    def test_cmd_proposal_update_status(self, monkeypatch):
        from ai_superpower import cli
        mock_client = MagicMock()
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        args = argparse.Namespace(id="P-1", status="in_dev")
        cli.cmd_proposal_update_status(args)
        mock_client.update_proposal_status.assert_called_once_with("P-1", "in_dev")

    def test_cmd_proposal_update_fields_parses_kv(self, monkeypatch):
        """--field key=value pairs are parsed into a dict. Items without '='
        are silently dropped (not added to the update payload)."""
        from ai_superpower import cli
        mock_client = MagicMock()
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        args = argparse.Namespace(
            id="P-1",
            fields=["title=Hello", "owner=alice", "no_equals_sign_here"],
        )
        cli.cmd_proposal_update_fields(args)
        call_kwargs = mock_client.update_proposal_fields.call_args.kwargs
        assert call_kwargs == {"title": "Hello", "owner": "alice"}

    def test_cmd_proposal_delete(self, monkeypatch):
        from ai_superpower import cli
        mock_client = MagicMock()
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        args = argparse.Namespace(id="P-1")
        cli.cmd_proposal_delete(args)
        mock_client.delete_proposal.assert_called_once_with("P-1")


# ─── Utility command handlers ──────────────────────────────────────────────


class TestCliUtilityCommands:
    def test_cmd_validate_parses_json(self, monkeypatch):
        from ai_superpower import cli
        mock_client = MagicMock()
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        args = argparse.Namespace(data='{"title": "X", "project_id": "PRJ-1"}')
        cli.cmd_validate(args)
        mock_client.validate.assert_called_once_with(
            {"title": "X", "project_id": "PRJ-1"}
        )

    def test_cmd_validate_handles_python_literal_fallback(self, monkeypatch):
        """args.data starting with { but with single-quotes is NOT valid JSON;
        cli.cmd_validate attempts json.loads first and fails. This documents
        the behavior: a Python dict with single quotes raises JSONDecodeError
        (the ast.literal_eval fallback is unreachable since startswith('{') is True)."""
        from ai_superpower import cli
        mock_client = MagicMock()
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        args = argparse.Namespace(data="{'title': 'X', 'project_id': 'PRJ-1'}")
        with pytest.raises(json.JSONDecodeError):
            cli.cmd_validate(args)
        mock_client.validate.assert_not_called()

    def test_cmd_audit_passes_filters(self, monkeypatch):
        from ai_superpower import cli
        mock_client = MagicMock()
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        args = argparse.Namespace(
            page=1, page_size=50, entity_id="P-1",
            op="UPDATE", entity="proposal",
        )
        cli.cmd_audit(args)
        mock_client.get_audit.assert_called_once_with(
            page=1, page_size=50, entity_id="P-1",
            op="UPDATE", entity="proposal",
        )

    def test_cmd_backup_list(self, capsys):
        from ai_superpower import cli
        from unittest.mock import patch
        mock_bs = MagicMock()
        mock_bs.list_backups.return_value = [
            {"name": "db_backup_20260601_120000", "size": 1024, "mtime": "2026-06-01T12:00:00"},
            {"name": "db_backup_20260602_120000", "size": 2048, "mtime": "2026-06-02T12:00:00"},
        ]
        with patch("ai_superpower.backup.BackupScheduler", return_value=mock_bs):
            args = argparse.Namespace(list_backups=True, restore=None)
            cli.cmd_backup(args)
        captured = capsys.readouterr()
        assert "db_backup_20260601_120000" in captured.out
        assert "db_backup_20260602_120000" in captured.out
        mock_bs.backup.assert_not_called()
        mock_bs.restore.assert_not_called()

    def test_cmd_backup_restore(self):
        from ai_superpower import cli
        from unittest.mock import patch
        mock_bs = MagicMock()
        with patch("ai_superpower.backup.BackupScheduler", return_value=mock_bs):
            args = argparse.Namespace(list_backups=False, restore="db_backup_X")
            cli.cmd_backup(args)
        mock_bs.restore.assert_called_once_with("db_backup_X")
        mock_bs.backup.assert_not_called()

    def test_cmd_backup_run_success(self, capsys):
        from ai_superpower import cli
        from unittest.mock import patch
        mock_bs = MagicMock()
        mock_bs.backup.return_value = {
            "success": True,
            "backup_dir": "/tmp/backups/db_x",
            "remote_done": True,
            "error": None,
        }
        with patch("ai_superpower.backup.BackupScheduler", return_value=mock_bs):
            args = argparse.Namespace(list_backups=False, restore=None)
            cli.cmd_backup(args)
        captured = capsys.readouterr()
        assert "Backup complete" in captured.out
        assert "Remote push: OK" in captured.out

    def test_cmd_backup_run_failure(self, capsys):
        from ai_superpower import cli
        from unittest.mock import patch
        mock_bs = MagicMock()
        mock_bs.backup.return_value = {
            "success": False, "backup_dir": "", "remote_done": False,
            "error": "disk full",
        }
        with patch("ai_superpower.backup.BackupScheduler", return_value=mock_bs):
            args = argparse.Namespace(list_backups=False, restore=None)
            cli.cmd_backup(args)
        captured = capsys.readouterr()
        assert "Backup failed" in captured.out
        assert "disk full" in captured.out

    def test_cmd_replay_dry_run(self):
        from ai_superpower import cli
        from unittest.mock import patch
        mock_replay = MagicMock()
        # The function does `from ai_superpower.replay import Replay` so we
        # patch the symbol in the source module directly.
        with patch("ai_superpower.replay.Replay", mock_replay):
            args = argparse.Namespace(
                dry_run=True, undo=None,
                from_time=None, last=None, entity_id=None,
            )
            cli.cmd_replay(args)
        mock_replay.assert_called_once_with(dry_run=True)
        mock_replay.return_value.replay_from_file.assert_called_once_with(
            from_time=None, last_n=None, entity_id=None,
        )

    def test_cmd_replay_undo(self):
        from ai_superpower import cli
        from unittest.mock import patch
        mock_replay = MagicMock()
        with patch("ai_superpower.replay.Replay", mock_replay):
            args = argparse.Namespace(
                dry_run=False, undo="P-1",
                from_time=None, last=None, entity_id=None,
            )
            cli.cmd_replay(args)
        mock_replay.assert_called_once_with(dry_run=False)
        mock_replay.return_value.undo_last.assert_called_once_with("P-1")


# ─── main() entry dispatch ─────────────────────────────────────────────────


class TestCliMain:
    def test_main_no_args_prints_help(self, monkeypatch, capsys):
        """main() with no command prints help and exits with status 1."""
        from ai_superpower import cli
        monkeypatch.setattr(sys, "argv", ["aisp"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "usage:" in captured.out or "aisp" in captured.out

    def test_main_dispatches_to_project_create(self, monkeypatch):
        """main() routes 'project create' to cmd_project_create."""
        from ai_superpower import cli
        mock_client = MagicMock()
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        monkeypatch.setattr(sys, "argv", [
            "aisp", "project", "create", "--name", "X",
            "--git-repo", "https://g",
        ])
        cli.main()
        mock_client.create_project.assert_called_once()
        assert mock_client.create_project.call_args.kwargs["name"] == "X"

    def test_main_dispatches_to_proposal_list(self, monkeypatch):
        from ai_superpower import cli
        mock_client = MagicMock()
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        monkeypatch.setattr(sys, "argv", [
            "aisp", "proposal", "list", "--page-size", "5",
        ])
        cli.main()
        mock_client.list_proposals.assert_called_once()
        assert mock_client.list_proposals.call_args.kwargs["page_size"] == 5

    def test_main_dispatches_to_audit(self, monkeypatch):
        from ai_superpower import cli
        mock_client = MagicMock()
        monkeypatch.setattr(cli, "APIClient", lambda: mock_client)
        monkeypatch.setattr(sys, "argv", ["aisp", "audit", "--op", "UPDATE"])
        cli.main()
        mock_client.get_audit.assert_called_once()
        assert mock_client.get_audit.call_args.kwargs["op"] == "UPDATE"
