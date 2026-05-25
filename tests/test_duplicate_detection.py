"""Tests for duplicate project detection (feature 2)."""
import pytest
from ai_superpower.storage import CSVStorage


class TestDuplicateDetectionStorage:
    """Test duplicate detection at the storage layer."""

    def test_duplicate_name_case_insensitive(self, storage):
        """Same name (different case) should raise ValueError."""
        with pytest.raises(ValueError, match="Duplicate project: name="):
            storage.create_project(name="TEST PROJECT")

    def test_duplicate_name_same_case(self, storage):
        """Same name (same case) should raise ValueError."""
        with pytest.raises(ValueError, match="Duplicate project: name="):
            storage.create_project(name="Test Project")

    def test_duplicate_git_repo_same(self, storage):
        """Same git_repo should raise ValueError when already exists."""
        # Create first project with git_repo
        storage.create_project(name="First Repo", git_repo="https://github.com/test/repo")
        # Second project with same repo should raise
        with pytest.raises(ValueError, match="Duplicate project: git_repo="):
            storage.create_project(name="Second Repo", git_repo="https://github.com/test/repo")

    def test_duplicate_git_repo_trailing_slash(self, storage):
        """git_repo with trailing slash should match without trailing slash."""
        storage.create_project(name="Slash Repo", git_repo="https://github.com/slash/test/")
        with pytest.raises(ValueError, match="Duplicate project: git_repo="):
            storage.create_project(name="No Slash Repo", git_repo="https://github.com/slash/test")

    def test_force_allows_duplicate(self, storage):
        """force=True should bypass duplicate detection."""
        p = storage.create_project(name="Test Project", force=True)
        assert p.name == "Test Project"

    def test_no_duplicate_for_new_name_and_repo(self, storage):
        """New name and repo should not raise."""
        p = storage.create_project(name="Unique Project", git_repo="https://github.com/unique/repo")
        assert p.name == "Unique Project"
        assert p.git_repo == "https://github.com/unique/repo"


class TestCheckDuplicateHelper:
    """Test check_project_duplicate helper."""

    def test_check_duplicate_name_match(self, storage):
        """check_project_duplicate returns reason=name for name match."""
        result = storage.check_project_duplicate(name="Test Project")
        assert result is not None
        assert result["reason"] == "name"

    def test_check_duplicate_git_match(self, storage):
        """check_project_duplicate returns reason=git_repo for git_repo match."""
        storage.create_project(name="Git Test", git_repo="https://github.com/git/match")
        result = storage.check_project_duplicate(git_repo="https://github.com/git/match")
        assert result is not None
        assert result["reason"] == "git_repo"

    def test_check_duplicate_none_for_unique(self, storage):
        """check_project_duplicate returns None for unique name+repo."""
        result = storage.check_project_duplicate(name="Never Seen Name", git_repo="https://github.com/unique/new")
        assert result is None

    def test_check_duplicate_git_repo_trailing_slash(self, storage):
        """check_project_duplicate handles trailing slash in git_repo."""
        storage.create_project(name="Slash Test", git_repo="https://github.com/slash/test/")
        result = storage.check_project_duplicate(git_repo="https://github.com/slash/test")
        assert result is not None
        assert result["reason"] == "git_repo"

    def test_check_duplicate_empty_params(self, storage):
        """check_project_duplicate with empty params returns None."""
        result = storage.check_project_duplicate(name="", git_repo="")
        assert result is None