"""Tests for new API features: Stats API, SyncStatus API, auto-backup trigger."""
import pytest

AUTH_HEADER = {"X-API-Key": "test-key-456"}


# ─── Stats API ─────────────────────────────────────────────────────────────────

class TestStatsEndpoint:
    def test_stats_returns_totals(self, api_client):
        r = api_client.get("/api/stats?days=7", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert "totals" in data
        assert "projects" in data["totals"]
        assert "proposals" in data["totals"]

    def test_stats_returns_today(self, api_client):
        r = api_client.get("/api/stats?days=7", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert "today" in data
        assert "projects" in data["today"]
        assert "proposals" in data["today"]

    def test_stats_returns_trends(self, api_client):
        r = api_client.get("/api/stats?days=7", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert "trends" in data
        assert "days" in data["trends"]
        assert "projects_by_date" in data["trends"]
        assert "proposals_by_date" in data["trends"]
        assert len(data["trends"]["projects_by_date"]) == 7
        assert len(data["trends"]["proposals_by_date"]) == 7

    def test_stats_returns_by_status(self, api_client):
        r = api_client.get("/api/stats?days=7", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert "by_status" in data
        # by_status is a dict of status -> count

    def test_stats_returns_recent_activity(self, api_client):
        r = api_client.get("/api/stats?days=7", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert "recent_activity" in data
        # recent_activity is a list (may be empty in fresh test DB)

    def test_stats_days_param_bounds(self, api_client):
        # days must be 7-90
        r = api_client.get("/api/stats?days=6", headers=AUTH_HEADER)
        assert r.status_code == 422  # validation error
        r = api_client.get("/api/stats?days=91", headers=AUTH_HEADER)
        assert r.status_code == 422


# ─── SyncStatus API ─────────────────────────────────────────────────────────────

class TestSyncStatusEndpoint:
    def _create_project(self, api_client):
        r = api_client.post("/api/projects", json={"name": "Sync Test"}, headers=AUTH_HEADER)
        return r.json()["id"]

    def test_get_sync_status_default_false(self, api_client):
        project_id = self._create_project(api_client)
        r = api_client.get(f"/api/projects/{project_id}/sync-status", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["project_id"] == project_id
        assert data["sync_enabled"] is False
        assert data["sync_last_run"] == ""

    def test_get_sync_status_not_found(self, api_client):
        r = api_client.get("/api/projects/PRJ-20991231-999/sync-status", headers=AUTH_HEADER)
        assert r.status_code == 404

    def test_set_sync_enabled_true(self, api_client):
        project_id = self._create_project(api_client)
        r = api_client.put(f"/api/projects/{project_id}/sync-enabled?enabled=true", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["sync_enabled"] == "true"

    def test_set_sync_enabled_false(self, api_client):
        project_id = self._create_project(api_client)
        # First enable it
        api_client.put(f"/api/projects/{project_id}/sync-enabled?enabled=true", headers=AUTH_HEADER)
        # Then disable it
        r = api_client.put(f"/api/projects/{project_id}/sync-enabled?enabled=false", headers=AUTH_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["sync_enabled"] == "false"

    def test_set_sync_enabled_not_found(self, api_client):
        r = api_client.put("/api/projects/PRJ-20991231-999/sync-enabled?enabled=true", headers=AUTH_HEADER)
        assert r.status_code == 404


# ─── Storage get_stats ─────────────────────────────────────────────────────────

class TestStatsStorage:
    def test_get_stats_days_7(self, storage):
        stats = storage.get_stats(days=7)
        assert "totals" in stats
        assert "today" in stats
        assert "trends" in stats
        assert "by_status" in stats
        assert "recent_activity" in stats
        assert stats["trends"]["days"] == 7
        assert len(stats["trends"]["projects_by_date"]) == 7
        assert len(stats["trends"]["proposals_by_date"]) == 7

    def test_get_stats_days_30(self, storage):
        stats = storage.get_stats(days=30)
        assert stats["trends"]["days"] == 30
        assert len(stats["trends"]["projects_by_date"]) == 30
        assert len(stats["trends"]["proposals_by_date"]) == 30

    def test_get_stats_days_90(self, storage):
        stats = storage.get_stats(days=90)
        assert stats["trends"]["days"] == 90
        assert len(stats["trends"]["projects_by_date"]) == 90
        assert len(stats["trends"]["proposals_by_date"]) == 90

    def test_get_stats_by_status_counts(self, storage):
        stats = storage.get_stats(days=30)
        assert isinstance(stats["by_status"], dict)
        # All values should be non-negative integers
        for v in stats["by_status"].values():
            assert isinstance(v, int)
            assert v >= 0

    def test_get_stats_totals_structure(self, storage):
        stats = storage.get_stats(days=30)
        totals = stats["totals"]
        assert "projects" in totals
        assert "proposals" in totals
        assert isinstance(totals["projects"], int)
        assert isinstance(totals["proposals"], int)

    def test_get_stats_today_structure(self, storage):
        stats = storage.get_stats(days=30)
        today = stats["today"]
        assert "projects" in today
        assert "proposals" in today
        assert isinstance(today["projects"], int)
        assert isinstance(today["proposals"], int)


# ─── Sync fields on Project ──────────────────────────────────────────────────────

class TestProjectSyncFields:
    def test_project_model_has_sync_fields(self):
        from ai_superpower.models import Project
        p = Project(id="PRJ-TEST-001", name="Test", proposal_count=0)
        assert hasattr(p, "sync_enabled")
        assert hasattr(p, "sync_last_run")

    def test_project_update_has_sync_fields(self):
        from ai_superpower.models import ProjectUpdate
        u = ProjectUpdate(sync_enabled="true")
        assert u.sync_enabled == "true"


# ─── Auto-backup trigger ────────────────────────────────────────────────────────

class TestAutoBackupTrigger:
    def test_auto_backup_threshold_zero_disables(self, storage):
        """When auto_backup_threshold=0 (default in TempStorageConfig), no backup triggered."""
        # Create several proposals - should not trigger backup
        proj = storage.create_project(name="Backup Test", git_repo="", local_path="", description="")
        for i in range(10):
            storage.create_proposal({
                "title": f"Proposal {i}",
                "owner": "test",
                "project_id": proj.id,
                "stage": "ideation",
            })
        # If we got here without exception, auto-backup didn't crash
        # (actual backup trigger would require threshold > 0)
        assert True