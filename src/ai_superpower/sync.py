"""Sync utilities for pushing proposals to prj-proposals-manager GitHub repo.

Implements CSV → JSON conversion and GitHub REST API push.
"""
import base64
import csv
import json
import time
from pathlib import Path
from typing import Any

import requests


# ─── CSV → JSON Conversion ───────────────────────────────────────────────────

def csv_to_prj_proposals_json(csv_path: str) -> list[dict]:
    """Convert proposals.csv to prj-proposals-manager proposals.json format.

    CSV fields: id, title, owner, status, project_id, project_name, stage,
               last_update, prd_confirmation, tech_expectations, acceptance,
               git_repo, deployment_url

    JSON fields: id, name(=title), description, type="proposal", status,
                 url(=deployment_url), gitRepo, tags=[], createdAt(=last_update),
                 updatedAt(=last_update), prdConfirmation, techExpectations, acceptance
    """
    result: list[dict] = []

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip empty rows
            if not row.get("id"):
                continue

            item: dict[str, Any] = {
                "id": row.get("id", ""),
                "name": row.get("title", ""),
                "description": "",  # No direct mapping in CSV
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


# ─── GitHub API Push ─────────────────────────────────────────────────────────

def push_proposals_to_github(
    data: list[dict],
    target_repo: str,
    api_key: str,
    max_retries: int = 3,
) -> dict:
    """Push proposals.json to a GitHub repo via REST API.

    Uses GET + PUT to get SHA and update the file (upsert pattern).

    Args:
        data: List of proposal dicts in prj-proposals-manager format.
        target_repo: "owner/repo" string.
        api_key: GitHub personal access token.

    Returns:
        dict with success, status_code, message
    """
    if not target_repo:
        return {"success": False, "message": "No target_repo configured"}

    owner, repo = target_repo.split("/", 1)
    file_path = "data/proposals.json"
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"

    headers = {
        "Authorization": f"token {api_key}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "ai-superpower-sync",
    }

    json_content = json.dumps(data, ensure_ascii=False)

    # Step 1: GET existing file to get SHA
    sha: str | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                sha = resp.json().get("sha")
                break
            elif resp.status_code == 404:
                # File doesn't exist yet, that's fine
                break
            elif resp.status_code == 403 and attempt < max_retries - 1:
                # Rate limit - wait and retry
                time.sleep(2 ** attempt)
                continue
            else:
                return {
                    "success": False,
                    "status_code": resp.status_code,
                    "message": f"GET failed: {resp.text[:200]}",
                }
        except requests.RequestException as ex:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return {"success": False, "message": f"GET request failed: {ex}"}

    # Step 2: PUT to create/update the file
    body = {
        "message": "chore: sync proposals from ai-superpower",
        "content": base64.b64encode(json_content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        body["sha"] = sha

    for attempt in range(max_retries):
        try:
            resp = requests.put(url, headers=headers, json=body, timeout=30)
            if resp.status_code in (200, 201):
                return {
                    "success": True,
                    "status_code": resp.status_code,
                    "message": f"Successfully pushed {len(data)} proposals to {target_repo}",
                    "pushed_count": len(data),
                }
            elif resp.status_code == 403 and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            else:
                return {
                    "success": False,
                    "status_code": resp.status_code,
                    "message": f"PUT failed: {resp.text[:200]}",
                }
        except requests.RequestException as ex:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return {"success": False, "message": f"PUT request failed: {ex}"}

    return {"success": False, "message": "Max retries exceeded"}