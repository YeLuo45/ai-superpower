"""Sync to GitHub Pages — export CSV data as static JSON to gh-pages branch.

Exports three JSON files to data/ directory on gh-pages:
- data/proposals.json
- data/projects.json
- data/export_info.json
"""
import base64
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


# ─── CSV → JSON Conversion ────────────────────────────────────────────────────

def csv_to_gh_pages_proposals_json(csv_path: str) -> list[dict[str, Any]]:
    """Convert proposals.csv to GitHub Pages proposals.json format.

    JSON fields: id, name(=title), type="proposal", status, url(=deployment_url),
                gitRepo, tags=[], createdAt(=last_update), updatedAt(=last_update),
                prdConfirmation, techExpectations, acceptance
    """
    result: list[dict[str, Any]] = []

    if not Path(csv_path).exists():
        return result

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("id"):
                continue

            item: dict[str, Any] = {
                "id": row.get("id", ""),
                "name": row.get("title", ""),
                "type": "proposal",
                "status": row.get("status", ""),
                "url": row.get("deployment_url", ""),
                "gitRepo": row.get("git_repo", ""),
                "tags": [],
                "createdAt": row.get("last_update", ""),
                "updatedAt": row.get("last_update", ""),
                "prdConfirmation": row.get("prd_confirmation", ""),
                "techExpectations": row.get("tech_expectations", ""),
                "acceptance": row.get("acceptance", ""),
            }
            result.append(item)

    return result


def csv_to_gh_pages_projects_json(csv_path: str) -> list[dict[str, Any]]:
    """Convert projects.csv to GitHub Pages projects.json format.

    JSON fields: id, name, description, gitRepo, url(=prj_url), updatedAt(=last_update),
                proposalCount, syncEnabled
    """
    result: list[dict[str, Any]] = []

    if not Path(csv_path).exists():
        return result

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("id"):
                continue

            sync_enabled = row.get("sync_enabled", "false").lower() in ("true", "1", "yes")
            try:
                proposal_count = int(row.get("proposal_count", "0") or "0")
            except (ValueError, TypeError):
                proposal_count = 0

            item: dict[str, Any] = {
                "id": row.get("id", ""),
                "name": row.get("name", ""),
                "description": row.get("description", ""),
                "gitRepo": row.get("git_repo", ""),
                "url": row.get("prj_url", ""),
                "updatedAt": row.get("last_update", ""),
                "proposalCount": proposal_count,
                "syncEnabled": sync_enabled,
            }
            result.append(item)

    return result


def generate_export_info(proposals_count: int, projects_count: int) -> dict[str, Any]:
    """Generate export_info.json metadata."""
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "version": "1.0",
        "proposals_count": proposals_count,
        "projects_count": projects_count,
    }


# ─── GitHub API Push ──────────────────────────────────────────────────────────

def _get_file_sha(url: str, headers: dict, max_retries: int = 3) -> str | None:
    """GET a file's SHA from GitHub API. Returns None if file doesn't exist."""
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                return resp.json().get("sha")
            elif resp.status_code == 404:
                return None
            elif resp.status_code == 403 and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            else:
                return None
        except requests.RequestException:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return None
    return None


def _put_file(url: str, headers: dict, body: dict, max_retries: int = 3) -> dict:
    """PUT a file to GitHub API. Returns dict with success and status."""
    for attempt in range(max_retries):
        try:
            resp = requests.put(url, headers=headers, json=body, timeout=30)
            if resp.status_code in (200, 201):
                return {"success": True, "status_code": resp.status_code}
            elif resp.status_code == 403 and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            else:
                return {"success": False, "status_code": resp.status_code, "message": resp.text[:200]}
        except requests.RequestException as ex:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return {"success": False, "message": str(ex)}
    return {"success": False, "message": "Max retries exceeded"}


def push_json_to_gh_pages(
    data: list[dict] | dict,
    file_name: str,
    target_repo: str,
    api_key: str,
    branch: str = "gh-pages",
    max_retries: int = 3,
) -> dict:
    """Push a JSON file to the data/ directory on gh-pages branch.

    Args:
        data: List or dict to serialize as JSON and push.
        file_name: One of 'proposals.json', 'projects.json', 'export_info.json'.
        target_repo: "owner/repo" string.
        api_key: GitHub personal access token.
        branch: Target branch (default: gh-pages).

    Returns:
        dict with success, status_code, message
    """
    if not target_repo:
        return {"success": False, "message": "No target_repo configured"}
    if not api_key:
        return {"success": False, "message": "No API key configured"}

    owner, repo = target_repo.split("/", 1)
    file_path = f"data/{file_name}"
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"

    headers = {
        "Authorization": f"token {api_key}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "ai-superpower-sync",
    }

    json_content = json.dumps(data, ensure_ascii=False, indent=2)

    # Get current SHA (if file exists)
    sha = _get_file_sha(url, headers, max_retries)

    # PUT the file
    body = {
        "message": f"chore: sync {file_name} from ai-superpower",
        "content": base64.b64encode(json_content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        body["sha"] = sha

    result = _put_file(url, headers, body, max_retries)
    result["file"] = file_name
    return result


# ─── Main Export Function ──────────────────────────────────────────────────────

def export_to_github_pages(storage, target_repo: str, api_key: str) -> dict:
    """Export CSV data to GitHub Pages gh-pages branch as static JSON.

    Creates/updates three files in data/ directory:
    - proposals.json: All proposals from CSV
    - projects.json: All projects from CSV
    - export_info.json: Metadata about this export

    Args:
        storage: CSVStorage instance (must have .config with proposals_csv, projects_csv)
        target_repo: "owner/repo" for the GitHub repo
        api_key: GitHub personal access token

    Returns:
        dict with success, files_created, proposals_count, projects_count, message
    """
    # Read CSV data
    proposals = csv_to_gh_pages_proposals_json(storage.config.proposals_csv)
    projects = csv_to_gh_pages_projects_json(storage.config.projects_csv)

    files_created = 0
    errors = []

    # Push proposals.json
    result = push_json_to_gh_pages(proposals, "proposals.json", target_repo, api_key)
    if result.get("success"):
        files_created += 1
    else:
        errors.append(f"proposals.json: {result.get('message', 'failed')}")

    # Push projects.json
    result = push_json_to_gh_pages(projects, "projects.json", target_repo, api_key)
    if result.get("success"):
        files_created += 1
    else:
        errors.append(f"projects.json: {result.get('message', 'failed')}")

    # Push export_info.json
    export_info = generate_export_info(len(proposals), len(projects))
    result = push_json_to_gh_pages(export_info, "export_info.json", target_repo, api_key)
    if result.get("success"):
        files_created += 1
    else:
        errors.append(f"export_info.json: {result.get('message', 'failed')}")

    return {
        "success": files_created == 3,
        "files_created": files_created,
        "proposals_count": len(proposals),
        "projects_count": len(projects),
        "message": "; ".join(errors) if errors else f"Exported {files_created} files successfully",
    }