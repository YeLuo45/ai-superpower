"""CLI client for ai-superpower."""
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

from .config import load_config


class APIClient:
    """HTTP client for ai-superpower API over Unix socket."""

    def __init__(self):
        self.config = load_config()
        self.socket_path = self.config.socket_path

    def _do_request(self, method: str, path: str, body: dict = None) -> dict:
        """Make an HTTP request via Unix socket."""
        import http.client
        import socket

        # Connect via Unix socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self.socket_path)

        # Build HTTP request
        if body:
            body_bytes = json.dumps(body).encode("utf-8")
        else:
            body_bytes = b""

        request_lines = [
            f"{method} {path} HTTP/1.1",
            f"Host: localhost",
            f"X-API-Key: {self.config.key}",
            f"Content-Type: application/json",
            f"Content-Length: {len(body_bytes)}",
            "",
            "",
        ]
        if body_bytes:
            request_lines.append("")

        sock.sendall("\r\n".join(request_lines).encode("utf-8"))
        if body_bytes:
            sock.sendall(body_bytes)

        # Read response
        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
            if b"\r\n\r\n" in response:
                break

        sock.close()

        # Parse HTTP response
        response_text = response.decode("utf-8")
        if "\r\n\r\n" in response_text:
            _, body = response_text.split("\r\n\r\n", 1)
        else:
            body = response_text

        # Extract status code
        status_line = response_text.split("\r\n")[0]
        status_code = int(status_line.split()[1])

        if status_code == 204:
            return {}

        result = json.loads(body) if body.strip() else {}

        if status_code >= 400:
            detail = result.get("detail", f"HTTP {status_code}")
            sys.stderr.write(f"Error: {detail}\n")
            sys.exit(1)

        return result

    # ─── Projects ────────────────────────────────────────────────────────────

    def create_project(self, name: str, git_repo: str = "", local_path: str = "", description: str = ""):
        body = {"name": name}
        if git_repo:
            body["git_repo"] = git_repo
        if local_path:
            body["local_path"] = local_path
        if description:
            body["description"] = description
        result = self._do_request("POST", "/projects", body)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    def list_projects(self, page: int = 1, page_size: int = 50, search: str = None):
        params = f"page={page}&page_size={page_size}"
        if search:
            params += f"&search={urllib.parse.quote(search)}"
        result = self._do_request("GET", f"/projects?{params}")
        print(json.dumps(result, indent=2, ensure_ascii=False))

    def get_project(self, project_id: str):
        result = self._do_request("GET", f"/projects/{project_id}")
        print(json.dumps(result, indent=2, ensure_ascii=False))

    def delete_project(self, project_id: str):
        self._do_request("DELETE", f"/projects/{project_id}")
        print(f"Deleted project {project_id}")

    # ─── Proposals ────────────────────────────────────────────────────────────

    def create_proposal(self, **kwargs):
        result = self._do_request("POST", "/proposals", kwargs)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    def list_proposals(self, page: int = 1, page_size: int = 50, project_id: str = None,
                       status: str = None, owner: str = None, search: str = None, stage: str = None):
        import urllib.parse
        params = f"page={page}&page_size={page_size}"
        if project_id:
            params += f"&project_id={urllib.parse.quote(project_id)}"
        if status:
            params += f"&status={urllib.parse.quote(status)}"
        if owner:
            params += f"&owner={urllib.parse.quote(owner)}"
        if search:
            params += f"&search={urllib.parse.quote(search)}"
        if stage:
            params += f"&stage={urllib.parse.quote(stage)}"
        result = self._do_request("GET", f"/proposals?{params}")
        print(json.dumps(result, indent=2, ensure_ascii=False))

    def get_proposal(self, proposal_id: str):
        result = self._do_request("GET", f"/proposals/{proposal_id}")
        print(json.dumps(result, indent=2, ensure_ascii=False))

    def update_proposal_status(self, proposal_id: str, status: str):
        result = self._do_request("PUT", f"/proposals/{proposal_id}/status", {"status": status})
        print(json.dumps(result, indent=2, ensure_ascii=False))

    def update_proposal_fields(self, proposal_id: str, **fields):
        result = self._do_request("PUT", f"/proposals/{proposal_id}/fields", fields)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    def delete_proposal(self, proposal_id: str):
        self._do_request("DELETE", f"/proposals/{proposal_id}")
        print(f"Deleted proposal {proposal_id}")

    def validate(self, data: dict):
        result = self._do_request("POST", "/validate", {"data": data})
        print(json.dumps(result, indent=2, ensure_ascii=False))

    def get_audit(self, page: int = 1, page_size: int = 100, target: str = None, action: str = None):
        import urllib.parse
        params = f"page={page}&page_size={page_size}"
        if target:
            params += f"&target={urllib.parse.quote(target)}"
        if action:
            params += f"&action={urllib.parse.quote(action)}"
        result = self._do_request("GET", f"/audit?{params}")
        print(json.dumps(result, indent=2, ensure_ascii=False))


# Alias for convenience
import urllib.parse
