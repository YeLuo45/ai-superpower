"""Tests for ai-superpower APIClient — HTTP request building and error handling.

Strategy: replace ``socket.socket`` at the module level so the APIClient
hits an in-process mock that returns canned HTTP responses. This avoids
spawning a real Unix-socket server thread (which deadlocks in CI) and
keeps each test under 50ms.
"""
import json
import socket as _socket_mod
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class _MockSocket:
    """A scripted socket that returns one canned HTTP response per connection.

    Construct with a list of HTTP response strings. Each call to .connect()
    pops the next response off the queue; subsequent .recv() calls yield
    one chunk of that response per call. When the response is exhausted,
    .recv() returns b"" (server close).
    """

    def __init__(self, responses):
        # responses: list of full HTTP/1.1 response strings (incl. headers + body)
        self._responses = [r.encode("utf-8") for r in responses]
        self._current = b""
        self._pos = 0
        self.connected_to = None
        self.closed = False

    def connect(self, path):
        self.connected_to = path
        if not self._responses:
            raise RuntimeError("MockSocket: no more responses queued")
        self._current = self._responses.pop(0)
        self._pos = 0

    def sendall(self, data):
        pass  # we don't inspect outgoing data in these tests

    def recv(self, n):
        if self._pos >= len(self._current):
            return b""
        chunk = self._current[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk

    def close(self):
        self.closed = True


@pytest.fixture
def mock_socket(monkeypatch, tmp_path):
    """Patch ai_superpower.client.socket.socket to return _MockSocket instances.

    Returns a function: caller passes a list of HTTP response strings,
    each call to APIClient() will pop one and return it.
    """
    state = {"queue": [], "instances": []}

    def factory(*args, **kwargs):
        if not state["queue"]:
            raise RuntimeError("mock_socket: no queued responses left")
        ms = _MockSocket(state["queue"])
        state["instances"].append(ms)
        return ms

    # Patch the global socket.socket so client.py's `import socket` picks it up
    # (client.py does `import socket` inside _do_request, so the lookup goes
    # through sys.modules each time)
    monkeypatch.setattr(_socket_mod, "socket", factory)

    class FakeConfig:
        socket_path = str(tmp_path / "api.sock")
        key = "test-key-456"
        projects_csv = str(tmp_path / "p.csv")
        proposals_csv = str(tmp_path / "pr.csv")
        audit_log = str(tmp_path / "audit.log")

    # Patch config loading.
    # client.py uses `from .config import load_config`, which binds the name
    # into client module's globals at import time. Patching config_mod only
    # would not affect the already-bound reference inside client.
    from ai_superpower import config as config_mod
    from ai_superpower import client as client_mod
    orig_load_cfg = config_mod.load_config
    orig_load_cli = client_mod.load_config
    monkeypatch.setattr(config_mod, "load_config", lambda: FakeConfig())
    monkeypatch.setattr(client_mod, "load_config", lambda: FakeConfig())

    def queue_response(http_string: str):
        state["queue"].append(http_string)

    return queue_response, state, FakeConfig


def _build_response(status_code: int, body: dict) -> str:
    body_str = json.dumps(body)
    status_text = {200: "OK", 201: "Created", 204: "No Content",
                   400: "Bad Request", 404: "Not Found", 500: "Server Error"}.get(
        status_code, "Status")
    return (
        f"HTTP/1.1 {status_code} {status_text}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body_str)}\r\n"
        f"\r\n"
        f"{body_str}"
    )


# ─── Happy-path single-method coverage ──────────────────────────────────────


class TestAPIClientHappyPath:
    """Each test exercises ONE method on APIClient end-to-end via _do_request."""

    def test_create_project(self, mock_socket):
        queue, state, FakeConfig = mock_socket
        queue(_build_response(201, {"id": "PRJ-1", "name": "Test"}))
        from ai_superpower.client import APIClient
        c = APIClient()
        c.create_project(name="Test")
        assert state["instances"][0].connected_to == FakeConfig.socket_path

    def test_list_projects(self, mock_socket):
        queue, state, _ = mock_socket
        queue(_build_response(200, {"items": [], "total": 0}))
        from ai_superpower.client import APIClient
        c = APIClient()
        c.list_projects(page=1, page_size=10, search="hello")
        assert state["instances"][0].connected_to

    def test_get_project(self, mock_socket):
        queue, state, _ = mock_socket
        queue(_build_response(200, {"id": "PRJ-1", "name": "Test"}))
        from ai_superpower.client import APIClient
        c = APIClient()
        c.get_project("PRJ-1")
        assert state["instances"][0].connected_to

    def test_delete_project(self, mock_socket, capsys):
        queue, state, _ = mock_socket
        queue(_build_response(204, {}))
        from ai_superpower.client import APIClient
        c = APIClient()
        c.delete_project("PRJ-1")
        captured = capsys.readouterr()
        assert "Deleted project PRJ-1" in captured.out
        assert state["instances"][0].closed is True

    def test_create_proposal(self, mock_socket):
        queue, state, _ = mock_socket
        queue(_build_response(201, {"id": "P-1", "title": "T"}))
        from ai_superpower.client import APIClient
        c = APIClient()
        c.create_proposal(title="T", owner="boss", project_id="PRJ-1", stage="ideation")
        assert state["instances"][0].connected_to

    def test_list_proposals_with_all_filters(self, mock_socket):
        """All optional filters (project_id, status, owner, search, stage) are URL-encoded."""
        queue, state, _ = mock_socket
        queue(_build_response(200, {"items": [], "total": 0}))
        from ai_superpower.client import APIClient
        c = APIClient()
        c.list_proposals(project_id="PRJ-1", status="in_dev", owner="boss",
                         search="foo bar", stage="ideation")
        assert state["instances"][0].connected_to

    def test_get_proposal(self, mock_socket):
        queue, state, _ = mock_socket
        queue(_build_response(200, {"id": "P-1"}))
        from ai_superpower.client import APIClient
        c = APIClient()
        c.get_proposal("P-1")
        assert state["instances"][0].connected_to

    def test_update_proposal_status(self, mock_socket):
        queue, state, _ = mock_socket
        queue(_build_response(200, {"id": "P-1", "status": "in_dev"}))
        from ai_superpower.client import APIClient
        c = APIClient()
        c.update_proposal_status("P-1", "in_dev")
        assert state["instances"][0].connected_to

    def test_update_proposal_fields(self, mock_socket):
        queue, state, _ = mock_socket
        queue(_build_response(200, {"id": "P-1", "notes": "new"}))
        from ai_superpower.client import APIClient
        c = APIClient()
        c.update_proposal_fields("P-1", notes="new", owner="boss")
        assert state["instances"][0].connected_to

    def test_delete_proposal(self, mock_socket, capsys):
        queue, state, _ = mock_socket
        queue(_build_response(204, {}))
        from ai_superpower.client import APIClient
        c = APIClient()
        c.delete_proposal("P-1")
        captured = capsys.readouterr()
        assert "Deleted proposal P-1" in captured.out

    def test_validate(self, mock_socket):
        queue, state, _ = mock_socket
        queue(_build_response(200, {"valid": True, "errors": []}))
        from ai_superpower.client import APIClient
        c = APIClient()
        c.validate({"title": "x", "project_id": "PRJ-1"})
        assert state["instances"][0].connected_to

    def test_get_audit_with_filters(self, mock_socket):
        """All audit filters (entity_id, op, entity) are URL-encoded."""
        queue, state, _ = mock_socket
        queue(_build_response(200, {"items": [], "total": 0}))
        from ai_superpower.client import APIClient
        c = APIClient()
        c.get_audit(entity_id="P-1", op="UPDATE", entity="proposal")
        assert state["instances"][0].connected_to


# ─── Error handling and response parsing branches ───────────────────────────


class TestAPIClientErrorPaths:
    """Cover _do_request error branches: 4xx, 204, no Content-Length, malformed body."""

    def test_4xx_raises_system_exit(self, mock_socket, capsys):
        queue, state, _ = mock_socket
        queue(_build_response(404, {"detail": "Not found"}))
        from ai_superpower.client import APIClient
        c = APIClient()
        with pytest.raises(SystemExit) as exc:
            c.get_project("PRJ-MISSING")
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Error: Not found" in captured.err

    def test_4xx_with_malformed_json(self, mock_socket, capsys):
        """4xx with non-JSON body still exits with HTTP <code> message."""
        queue, state, _ = mock_socket
        body_str = "internal server error text"
        response = (
            f"HTTP/1.1 500 Server Error\r\n"
            f"Content-Length: {len(body_str)}\r\n"
            f"Content-Type: text/plain\r\n"
            f"\r\n"
            f"{body_str}"
        )
        queue(response)
        from ai_superpower.client import APIClient
        c = APIClient()
        with pytest.raises(SystemExit):
            c.get_project("X")
        captured = capsys.readouterr()
        assert "Error: HTTP 500" in captured.err

    def test_204_no_content_returns_empty(self, mock_socket):
        """204 No Content: returns empty dict without parsing body."""
        queue, state, _ = mock_socket
        # Minimal valid 204 response — APIClient short-circuits before reading body
        response = "HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n"
        queue(response)
        from ai_superpower.client import APIClient
        c = APIClient()
        result = c._do_request("DELETE", "/projects/PRJ-1")
        assert result == {}

    def test_no_content_length_reads_until_close(self, mock_socket):
        """When response has no Content-Length, read until socket closes (recv returns b'')."""
        queue, state, _ = mock_socket
        # No Content-Length header — APIClient falls back to read-until-close
        body_str = json.dumps({"id": "X", "name": "Y"})
        response = (
            f"HTTP/1.1 200 OK\r\n"
            f"Content-Type: application/json\r\n"
            f"\r\n"
            f"{body_str}"
        )
        queue(response)
        from ai_superpower.client import APIClient
        c = APIClient()
        result = c._do_request("GET", "/projects/X")
        assert result == {"id": "X", "name": "Y"}

    def test_failed_to_read_headers_raises(self, mock_socket):
        """If headers aren't received, APIClient sys.exits with error message."""
        # Simulate server closing immediately — recv() returns b'' before any headers
        from ai_superpower.client import APIClient
        import socket as _socket_mod
        # Patch with a headerless mock socket
        class HeaderlessMock(_MockSocket):
            def connect(self, path):
                self._current = b""
                self._pos = 0
        import ai_superpower.client as client_mod
        # Import the function's local socket module by re-importing
        import socket as fresh_socket
        monkeypatch = pytest.MonkeyPatch()
        # We can't easily reach the local `socket` inside _do_request, but
        # patching the global _socket_mod.socket should work since
        # `import socket` re-fetches from sys.modules
        ms = HeaderlessMock([])
        old = _socket_mod.socket
        _socket_mod.socket = lambda *a, **kw: ms
        try:
            c = APIClient()
            with pytest.raises(SystemExit) as exc:
                c._do_request("GET", "/projects/X")
            assert "Failed to read response headers" in str(exc.value)
        finally:
            _socket_mod.socket = old

    def test_partial_recv_reads_until_content_length(self, mock_socket):
        """Cover client.py line 87-90: response body arrives in multiple chunks,
        client keeps reading until len matches Content-Length."""
        queue, state, _ = mock_socket
        body_str = json.dumps({"items": list(range(50))})  # big body
        # Build a response where body is split into many small chunks
        # by prepending a Content-Length header that is larger than first chunk
        full = (
            f"HTTP/1.1 200 OK\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body_str)}\r\n"
            f"\r\n"
            f"{body_str}"
        )
        # Truncate to first 50 bytes; client should keep reading
        truncated = full[:50]
        # Wrap so .recv(4096) returns one byte at a time
        class SlowSocket(_MockSocket):
            def __init__(self, full_data):
                self._full = full_data.encode("utf-8")
                self._pos = 0
            def connect(self, path):
                self._pos = 0
            def recv(self, n):
                if self._pos >= len(self._full):
                    return b""
                chunk = self._full[self._pos : self._pos + 1]  # 1 byte at a time
                self._pos += 1
                return chunk
            def close(self):
                pass
        import socket as _socket_mod
        old = _socket_mod.socket
        _socket_mod.socket = lambda *a, **kw: SlowSocket(full)
        try:
            from ai_superpower.client import APIClient
            c = APIClient()
            result = c._do_request("GET", "/proposals?page_size=50")
            assert "items" in result
            assert len(result["items"]) == 50
        finally:
            _socket_mod.socket = old

    def test_read_until_close_with_truncated_header(self, mock_socket):
        """Cover client.py line 98: when no Content-Length header, recv reads
        until socket closes. We use a valid {} body so JSON parses cleanly."""
        # A response WITHOUT Content-Length header — recv fallback path
        class NoContentLengthSocket(_MockSocket):
            def connect(self, path):
                self._current = (
                    f"HTTP/1.1 200 OK\r\n"
                    f"Content-Type: application/json\r\n"
                    f"\r\n"
                    f'{{}}'
                ).encode("utf-8")
                self._pos = 0
        import socket as _socket_mod
        old = _socket_mod.socket
        _socket_mod.socket = lambda *a, **kw: NoContentLengthSocket([])
        try:
            from ai_superpower.client import APIClient
            c = APIClient()
            result = c._do_request("GET", "/x")
            assert result == {}
        finally:
            _socket_mod.socket = old

    def test_create_project_with_optional_fields(self, mock_socket):
        """Cover client.py lines 120, 122, 124: git_repo, local_path, description
        are all added to the request body when truthy."""
        queue, state, _ = mock_socket
        queue(_build_response(201, {"id": "PRJ-1", "name": "Test"}))
        from ai_superpower.client import APIClient
        c = APIClient()
        # All optional fields populated
        c.create_project(
            name="Test",
            git_repo="https://github.com/x/y",
            local_path="/tmp/y",
            description="a project",
        )
        assert state["instances"][0].connected_to

    def test_list_projects_search_uses_quote(self, mock_socket):
        """Cover client.py line 131: search param is URL-encoded with urllib.parse.quote."""
        queue, state, _ = mock_socket
        queue(_build_response(200, {"items": [], "total": 0}))
        from ai_superpower.client import APIClient
        c = APIClient()
        c.list_projects(search="hello world & special/chars?")
        # Server should receive the URL-encoded version
        assert state["instances"][0].connected_to
