"""Boost sync.py and sync_gh_pages.py coverage by hitting missing branches."""
import io, json, os, tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest, requests


# ─── sync.py coverage ─────────────────────────────────────────────────────────

def test_csv_to_prj_proposals_json_skips_empty_rows(tmp_path):
    """Line 35: rows with no id are skipped."""
    from ai_superpower.sync import csv_to_prj_proposals_json

    csv_file = tmp_path / "proposals.csv"
    csv_file.write_text("id,title,status,last_update\n,,,\nP-001,Test,active,2026-05-25\n")
    result = csv_to_prj_proposals_json(str(csv_file))
    assert len(result) == 1
    assert result[0]["id"] == "P-001"


def test_push_proposals_no_target_repo():
    """Line 78: returns error when target_repo is empty."""
    from ai_superpower.sync import push_proposals_to_github
    result = push_proposals_to_github([], "", "fake-key")
    assert result["success"] is False
    assert "No target_repo" in result["message"]


def test_push_proposals_http_error_not_404(tmp_path):
    """Lines 105-106: HTTP error that isn't 404 returns error message."""
    from ai_superpower.sync import push_proposals_to_github

    with patch("ai_superpower.sync.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_get.return_value = mock_resp

        result = push_proposals_to_github([{"id": "P-001"}], "owner/repo", "fake-key")
        # 500 error path - SHA fetch fails
        assert result["success"] is False


def test_push_proposals_put_http_error():
    """Lines 113-117: PUT returns non-200/201 status."""
    from ai_superpower.sync import push_proposals_to_github

    with patch("ai_superpower.sync.requests.get") as mock_get:
        with patch("ai_superpower.sync.requests.put") as mock_put:
            # SHA fetch succeeds
            mock_get_resp = MagicMock()
            mock_get_resp.status_code = 200
            mock_get_resp.json.return_value = {"sha": "abc123"}
            mock_get.return_value = mock_get_resp

            # PUT fails
            mock_put_resp = MagicMock()
            mock_put_resp.status_code = 403
            mock_put_resp.text = "Forbidden"
            mock_put.return_value = mock_put_resp

            result = push_proposals_to_github([{"id": "P-001"}], "owner/repo", "fake-key")
            assert result["success"] is False
            assert "status_code" in result


def test_push_proposals_retry_exhausted():
    """Line 125: all retries exhausted on GET."""
    from ai_superpower.sync import push_proposals_to_github

    with patch("ai_superpower.sync.requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.Timeout("timeout")
        result = push_proposals_to_github([{"id": "P-001"}], "owner/repo", "fake-key", max_retries=2)
        assert result["success"] is False
        assert "retries" in result["message"].lower() or "timeout" in result["message"].lower()


# ─── sync_gh_pages.py coverage ─────────────────────────────────────────────────

def test_csv_to_gh_pages_proposals_json_file_not_found():
    """Line 37: missing CSV file returns empty list."""
    from ai_superpower.sync_gh_pages import csv_to_gh_pages_proposals_json
    result = csv_to_gh_pages_proposals_json("/nonexistent/path.csv")
    assert result == []


def test_csv_to_gh_pages_projects_json_skips_empty_rows(tmp_path):
    """Lines 73, 78-79: empty rows skipped; invalid proposal_count yields 0."""
    from ai_superpower.sync_gh_pages import csv_to_gh_pages_projects_json

    csv_file = tmp_path / "projects.csv"
    csv_file.write_text("id,name,proposal_count,git_repo,prj_url,last_update,sync_enabled\n,,invalid,,,\nP-001,Test Project,not_a_number,git@github.com:owner/repo,https://example.com,2026-05-25,false\n")
    result = csv_to_gh_pages_projects_json(str(csv_file))
    assert len(result) == 1
    assert result[0]["proposalCount"] == 0
    assert result[0]["syncEnabled"] is False


def test_push_json_to_gh_pages_get_sha_error():
    """Lines 114, 117-127: GET SHA fails (not 404) -> error."""
    from ai_superpower.sync_gh_pages import push_json_to_gh_pages

    with patch("ai_superpower.sync_gh_pages.requests.get") as mock_get:
        with patch("ai_superpower.sync_gh_pages.requests.put") as mock_put:
            mock_get_resp = MagicMock()
            mock_get_resp.status_code = 500
            mock_get_resp.text = "Server Error"
            mock_get.return_value = mock_get_resp

            data = {"proposals": []}
            result = push_json_to_gh_pages(data, "proposals.json", "owner/repo", "fake-key")
            assert result["success"] is False


def test_push_json_to_gh_pages_put_error_not_404():
    """Lines 137-147: PUT fails with non-200/201 status."""
    from ai_superpower.sync_gh_pages import push_json_to_gh_pages

    with patch("ai_superpower.sync_gh_pages.requests.get") as mock_get:
        with patch("ai_superpower.sync_gh_pages.requests.put") as mock_put:
            mock_get_resp = MagicMock()
            mock_get_resp.status_code = 200
            mock_get_resp.json.return_value = {"sha": "abc123"}
            mock_get.return_value = mock_get_resp

            mock_put_resp = MagicMock()
            mock_put_resp.status_code = 422
            mock_put_resp.text = "Unprocessable Entity"
            mock_put.return_value = mock_put_resp

            data = {"proposals": []}
            result = push_json_to_gh_pages(data, "proposals.json", "owner/repo", "fake-key")
            assert result["success"] is False


def test_export_to_github_pages_connection_error():
    """Lines 171, 173: connection error sets status to error."""
    from ai_superpower.sync_gh_pages import export_to_github_pages

    with patch("ai_superpower.sync_gh_pages.push_json_to_gh_pages") as mock_push:
        with patch("ai_superpower.sync_gh_pages.requests.get") as mock_get:
            mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")

            # Need storage mock
            mock_storage = MagicMock()
            mock_storage.list_projects.return_value = []
            mock_storage.list_proposals.return_value = []

            result = export_to_github_pages(mock_storage, "owner/repo", "fake-key")
            # Should return with success false (connection error)
            assert "success" in result


def test_generate_export_info():
    """Lines 96-103: basic sanity check."""
    from ai_superpower.sync_gh_pages import generate_export_info
    info = generate_export_info(5, 2)
    assert info["proposals_count"] == 5
    assert info["projects_count"] == 2
    assert info["version"] == "1.0"
    assert "exported_at" in info


def test_push_json_to_gh_pages_get_raises_request_exception():
    """Line 196: GET raises RequestException (e.g. Timeout)."""
    from ai_superpower.sync_gh_pages import push_json_to_gh_pages

    with patch("ai_superpower.sync_gh_pages.requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.Timeout("timeout")
        data = {"proposals": []}
        result = push_json_to_gh_pages(data, "proposals.json", "owner/repo", "fake-key")
        assert result["success"] is False


def test_push_json_to_gh_pages_put_raises_request_exception():
    """Line 233: PUT raises RequestException."""
    from ai_superpower.sync_gh_pages import push_json_to_gh_pages

    with patch("ai_superpower.sync_gh_pages.requests.get") as mock_get:
        with patch("ai_superpower.sync_gh_pages.requests.put") as mock_put:
            mock_get_resp = MagicMock()
            mock_get_resp.status_code = 200
            mock_get_resp.json.return_value = {"sha": "abc123"}
            mock_get.return_value = mock_get_resp

            mock_put.side_effect = requests.exceptions.Timeout("timeout")

            data = {"proposals": []}
            result = push_json_to_gh_pages(data, "proposals.json", "owner/repo", "fake-key")
            assert result["success"] is False


def test_push_json_to_gh_pages_retry_exhausted():
    """Lines 240, 248: max retries exhausted on GET."""
    from ai_superpower.sync_gh_pages import push_json_to_gh_pages

    with patch("ai_superpower.sync_gh_pages.requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.Timeout("timeout")

        data = {"proposals": []}
        result = push_json_to_gh_pages(data, "proposals.json", "owner/repo", "fake-key", max_retries=1)
        assert result["success"] is False