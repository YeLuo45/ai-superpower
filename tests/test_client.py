"""Tests for ai_superpower APIClient — validates request building and error handling."""
import pytest
import json
import socket
import threading
import time
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class MockUnixServer:
    """A real TCP server that speaks HTTP-over-UNIX for testing APIClient.

    APIClient uses socket.socket(AF_UNIX, SOCK_STREAM) — we replace
    socket.socket at the module level so APIClient connects to our server.
    """

    def __init__(self, sock_path):
        self.sock_path = sock_path
        self.running = False
        self._thread = None
        self._server_sock = None
        self.responses = {}  # path → (status_code, json_body)
        self.requests = []   # list of (method, raw_path)

    def set_response(self, path, status, body):
        self.responses[path] = (status, body)

    def start(self):
        import os
        if os.path.exists(self.sock_path):
            os.unlink(self.sock_path)
        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(self.sock_path)
        self._server_sock.listen(5)
        self.running = True

        def loop():
            while self.running:
                self._server_sock.settimeout(0.5)
                try:
                    conn, _ = self._server_sock.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()
        time.sleep(0.05)

    def _handle(self, conn):
        try:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk

            text = data.decode("utf-8", errors="replace")
            if not text:
                conn.close()
                return

            lines = text.split("\r\n")
            request_line = lines[0]
            parts = request_line.split(" ")
            if len(parts) < 2:
                conn.close()
                return
            method, raw_path = parts[0], parts[1]
            path = raw_path.split("?")[0]
            self.requests.append((method, raw_path))

            status, body = self.responses.get(path, (404, {"detail": "Not found"}))
            body_str = json.dumps(body)
            response = (
                f"HTTP/1.1 {status} OK\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body_str)}\r\n"
                f"\r\n"
                f"{body_str}"
            )
            conn.sendall(response.encode("utf-8"))
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def stop(self):
        self.running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
        import os
        if os.path.exists(self.sock_path):
            try:
                os.unlink(self.sock_path)
            except Exception:
                pass


class TestClientHappyPath:
    """Test APIClient by replacing socket.socket at the module level."""

    def test_create_project_request_sent(self, tmp_path):
        sock_path = str(tmp_path / "api.sock")
        mock = MockUnixServer(sock_path)
        mock.set_response("/projects", 201, {"id": "PRJ-20260523-001", "name": "Test Proj"})
        mock.start()

        import socket as sock_module
        original = sock_module.socket

        class MockSocket:
            def __init__(self, *args, **kwargs):
                self._conn = original(*args, **kwargs)

            def connect(self, path):
                self._conn.close()
                self._conn = original(sock_module.AF_UNIX, sock_module.SOCK_STREAM)
                self._conn.connect(path)

            def sendall(self, data):
                self._conn.sendall(data)

            def recv(self, n):
                return self._conn.recv(n)

            def close(self):
                self._conn.close()

        sock_module.socket = MockSocket

        class FakeConfig:
            socket_path = sock_path
            key = "test-key-456"
            projects_csv = str(tmp_path / "p.csv")
            proposals_csv = str(tmp_path / "pr.csv")
            audit_log = str(tmp_path / "audit.log")

        from ai_superpower import config as config_mod
        orig_load = config_mod.load_config
        config_mod.load_config = lambda: FakeConfig()

        try:
            from ai_superpower.client import APIClient
            client = APIClient()
            client.config = FakeConfig()
            client.create_project(name="Test Proj")
            assert ("POST", "/projects") in mock.requests
        finally:
            sock_module.socket = original
            config_mod.load_config = orig_load
            mock.stop()

    def test_get_audit_ok(self, tmp_path):
        sock_path = str(tmp_path / "api.sock")
        mock = MockUnixServer(sock_path)
        mock.set_response("/audit", 200, {"items": [], "total": 0, "page": 1, "page_size": 100})
        mock.start()

        import socket as sock_module
        original = sock_module.socket

        class MockSocket:
            def __init__(self, *args, **kwargs):
                self._conn = original(*args, **kwargs)

            def connect(self, path):
                self._conn.close()
                self._conn = original(sock_module.AF_UNIX, sock_module.SOCK_STREAM)
                self._conn.connect(path)

            def sendall(self, data):
                self._conn.sendall(data)

            def recv(self, n):
                return self._conn.recv(n)

            def close(self):
                self._conn.close()

        sock_module.socket = MockSocket

        class FakeConfig:
            socket_path = sock_path
            key = "test-key-456"
            projects_csv = str(tmp_path / "p.csv")
            proposals_csv = str(tmp_path / "pr.csv")
            audit_log = str(tmp_path / "audit.log")

        from ai_superpower import config as config_mod
        orig_load = config_mod.load_config
        config_mod.load_config = lambda: FakeConfig()

        try:
            from ai_superpower.client import APIClient
            client = APIClient()
            client.config = FakeConfig()
            client.get_audit()
            assert ("GET", "/audit") in mock.requests
        finally:
            sock_module.socket = original
            config_mod.load_config = orig_load
            mock.stop()


    def test_list_proposals_encodes_filters(self, tmp_path):
        """Verify owner and stage filter params are sent in the request."""
        sock_path = str(tmp_path / "api.sock")
        mock = MockUnixServer(sock_path)
        mock.set_response("/proposals", 200, {"items": [], "total": 0, "page": 1, "page_size": 50})
        mock.start()

        import socket as sock_module
        original = sock_module.socket

        class MockSocket:
            def __init__(self, *args, **kwargs):
                self._conn = original(*args, **kwargs)

            def connect(self, path):
                self._conn.close()
                self._conn = original(sock_module.AF_UNIX, sock_module.SOCK_STREAM)
                self._conn.connect(path)

            def sendall(self, data):
                self._conn.sendall(data)

            def recv(self, n):
                return self._conn.recv(n)

            def close(self):
                self._conn.close()

        sock_module.socket = MockSocket

        class FakeConfig:
            socket_path = sock_path
            key = "test-key-456"
            projects_csv = str(tmp_path / "p.csv")
            proposals_csv = str(tmp_path / "pr.csv")
            audit_log = str(tmp_path / "audit.log")

        from ai_superpower import config as config_mod
        orig_load = config_mod.load_config
        config_mod.load_config = lambda: FakeConfig()

        try:
            from ai_superpower.client import APIClient
            client = APIClient()
            client.config = FakeConfig()
            client.list_proposals(owner="alice bob", stage="ideation")
            raw_requests = [r for r in mock.requests if r[0] == "GET" and "/proposals" in r[1]]
            assert len(raw_requests) >= 1
            url = raw_requests[0][1]
            assert "owner=" in url
            assert "stage=" in url
        finally:
            sock_module.socket = original
            config_mod.load_config = orig_load
            mock.stop()


class TestClientErrorHandling:
    def test_get_project_404_raises_system_exit(self, tmp_path):
        sock_path = str(tmp_path / "api.sock")
        mock = MockUnixServer(sock_path)
        mock.set_response("/projects/PRJ-999", 404, {"detail": "Not found"})
        mock.start()

        import socket as sock_module
        original = sock_module.socket

        class MockSocket:
            def __init__(self, *args, **kwargs):
                self._conn = original(*args, **kwargs)

            def connect(self, path):
                self._conn.close()
                self._conn = original(sock_module.AF_UNIX, sock_module.SOCK_STREAM)
                self._conn.connect(path)

            def sendall(self, data):
                self._conn.sendall(data)

            def recv(self, n):
                return self._conn.recv(n)

            def close(self):
                self._conn.close()

        sock_module.socket = MockSocket

        class FakeConfig:
            socket_path = sock_path
            key = "test-key-456"
            projects_csv = str(tmp_path / "p.csv")
            proposals_csv = str(tmp_path / "pr.csv")
            audit_log = str(tmp_path / "audit.log")

        from ai_superpower import config as config_mod
        orig_load = config_mod.load_config
        config_mod.load_config = lambda: FakeConfig()

        try:
            from ai_superpower.client import APIClient
            client = APIClient()
            client.config = FakeConfig()
            with pytest.raises(SystemExit) as exc:
                client.get_project("PRJ-999")
            assert exc.value.code == 1
        finally:
            sock_module.socket = original
            config_mod.load_config = orig_load
            mock.stop()

    def test_do_request_401_raises_system_exit(self, tmp_path):
        sock_path = str(tmp_path / "api.sock")
        mock = MockUnixServer(sock_path)
        mock.set_response("/health", 401, {"detail": "Invalid API Key"})
        mock.start()

        import socket as sock_module
        original = sock_module.socket

        class MockSocket:
            def __init__(self, *args, **kwargs):
                self._conn = original(*args, **kwargs)

            def connect(self, path):
                self._conn.close()
                self._conn = original(sock_module.AF_UNIX, sock_module.SOCK_STREAM)
                self._conn.connect(path)

            def sendall(self, data):
                self._conn.sendall(data)

            def recv(self, n):
                return self._conn.recv(n)

            def close(self):
                self._conn.close()

        sock_module.socket = MockSocket

        class FakeConfig:
            socket_path = sock_path
            key = "test-key-456"
            projects_csv = str(tmp_path / "p.csv")
            proposals_csv = str(tmp_path / "pr.csv")
            audit_log = str(tmp_path / "audit.log")

        from ai_superpower import config as config_mod
        orig_load = config_mod.load_config
        config_mod.load_config = lambda: FakeConfig()

        try:
            from ai_superpower.client import APIClient
            client = APIClient()
            client.config = FakeConfig()
            with pytest.raises(SystemExit) as exc:
                client._do_request("GET", "/health")
            assert exc.value.code == 1
        finally:
            sock_module.socket = original
            config_mod.load_config = orig_load
            mock.stop()

    def test_create_proposal_400_raises_system_exit(self, tmp_path):
        sock_path = str(tmp_path / "api.sock")
        mock = MockUnixServer(sock_path)
        mock.set_response("/proposals", 400, {"detail": "Invalid project_id"})
        mock.start()

        import socket as sock_module
        original = sock_module.socket

        class MockSocket:
            def __init__(self, *args, **kwargs):
                self._conn = original(*args, **kwargs)

            def connect(self, path):
                self._conn.close()
                self._conn = original(sock_module.AF_UNIX, sock_module.SOCK_STREAM)
                self._conn.connect(path)

            def sendall(self, data):
                self._conn.sendall(data)

            def recv(self, n):
                return self._conn.recv(n)

            def close(self):
                self._conn.close()

        sock_module.socket = MockSocket

        class FakeConfig:
            socket_path = sock_path
            key = "test-key-456"
            projects_csv = str(tmp_path / "p.csv")
            proposals_csv = str(tmp_path / "pr.csv")
            audit_log = str(tmp_path / "audit.log")

        from ai_superpower import config as config_mod
        orig_load = config_mod.load_config
        config_mod.load_config = lambda: FakeConfig()

        try:
            from ai_superpower.client import APIClient
            client = APIClient()
            client.config = FakeConfig()
            with pytest.raises(SystemExit) as exc:
                client.create_proposal(
                    title="X", owner="boss",
                    project_id="PRJ-20991231-999", stage="ideation"
                )
            assert exc.value.code == 1
        finally:
            sock_module.socket = original
            config_mod.load_config = orig_load
            mock.stop()
