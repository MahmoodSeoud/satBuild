"""Tests for git provenance tracking."""

import os
import subprocess
from unittest.mock import patch

import pytest

from satdeploy.provenance import capture_provenance, detect_ci_provenance, resolve_provenance


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repository with a committed file."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )

    # Create and commit a binary file
    file_path = tmp_path / "app.bin"
    file_path.write_bytes(b"\x00" * 64)
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "app.bin"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "initial"],
        check=True,
        capture_output=True,
    )

    return tmp_path, str(file_path)


class TestCaptureProvenance:
    """Tests for capture_provenance()."""

    def test_clean_tree(self, git_repo):
        """Clean git repo returns branch@hash with no -dirty suffix."""
        repo_dir, file_path = git_repo

        result = capture_provenance(file_path)

        assert result is not None
        # Should not have -dirty suffix
        assert "-dirty" not in result
        # Should have branch@hash format (default branch could be main or master)
        assert "@" in result
        parts = result.split("@")
        assert len(parts) == 2
        assert len(parts[1]) == 8  # 8-char short hash

    def test_dirty_tree(self, git_repo):
        """Dirty git repo returns branch@hash-dirty."""
        repo_dir, file_path = git_repo

        # Make the tree dirty
        dirty_file = repo_dir / "uncommitted.txt"
        dirty_file.write_text("dirty")
        subprocess.run(
            ["git", "-C", str(repo_dir), "add", "uncommitted.txt"],
            check=True,
            capture_output=True,
        )

        result = capture_provenance(file_path)

        assert result is not None
        assert result.endswith("-dirty")
        assert "@" in result

    def test_detached_head(self, git_repo):
        """Detached HEAD returns @hash without branch name."""
        repo_dir, file_path = git_repo

        # Get the current commit hash and detach HEAD
        hash_result = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        commit_hash = hash_result.stdout.strip()
        subprocess.run(
            ["git", "-C", str(repo_dir), "checkout", commit_hash],
            check=True,
            capture_output=True,
        )

        result = capture_provenance(file_path)

        assert result is not None
        # Should start with @ (no branch name)
        assert result.startswith("@")
        # Remove "@" prefix and optional "-dirty" suffix to get the hash
        hash_part = result[1:]  # strip leading "@"
        if hash_part.endswith("-dirty"):
            hash_part = hash_part[:-6]
        assert len(hash_part) == 8

    def test_not_a_git_repo(self, tmp_path):
        """Non-git directory returns None."""
        file_path = tmp_path / "app.bin"
        file_path.write_bytes(b"\x00" * 64)

        result = capture_provenance(str(file_path))

        assert result is None

    def test_git_not_installed(self, tmp_path):
        """Returns None when git is not installed."""
        file_path = tmp_path / "app.bin"
        file_path.write_bytes(b"\x00" * 64)

        with patch("satdeploy.provenance.subprocess.run", side_effect=FileNotFoundError):
            result = capture_provenance(str(file_path))

        assert result is None

    def test_subprocess_error(self, tmp_path):
        """Returns None on subprocess errors."""
        file_path = tmp_path / "app.bin"
        file_path.write_bytes(b"\x00" * 64)

        with patch(
            "satdeploy.provenance.subprocess.run",
            side_effect=subprocess.SubprocessError("git crashed"),
        ):
            result = capture_provenance(str(file_path))

        assert result is None

    def test_branch_name_in_result(self, git_repo):
        """Branch name is included in the provenance string."""
        repo_dir, file_path = git_repo

        # Create and switch to a named branch
        subprocess.run(
            ["git", "-C", str(repo_dir), "checkout", "-b", "feature/test"],
            check=True,
            capture_output=True,
        )

        result = capture_provenance(file_path)

        assert result is not None
        assert result.startswith("feature/test@")


class TestDetectCiProvenance:
    """Tests for CI environment detection."""

    def test_github_actions_full(self):
        """Detects GitHub Actions with all env vars."""
        env = {
            "GITHUB_SHA": "abc123def456789012345678901234567890abcd",
            "GITHUB_REF_NAME": "main",
            "GITHUB_RUN_ID": "42",
        }
        with patch.dict(os.environ, env, clear=False):
            prov, source = detect_ci_provenance()

        assert prov == "main@abc123de (ci:github/run/42)"
        assert source == "ci/github"

    def test_github_actions_minimal(self):
        """Detects GitHub Actions with only GITHUB_SHA."""
        env = {"GITHUB_SHA": "abc123def456789012345678901234567890abcd"}
        with patch.dict(os.environ, env, clear=False):
            # Clear other env vars that might be set
            with patch.dict(os.environ, {"GITHUB_REF_NAME": "", "GITHUB_RUN_ID": ""}, clear=False):
                prov, source = detect_ci_provenance()

        assert prov == "@abc123de"
        assert source == "ci/github"

    def test_not_in_ci(self):
        """Returns None when not in CI."""
        env_remove = {"GITHUB_SHA": None, "GITHUB_REF_NAME": None, "GITHUB_RUN_ID": None}
        with patch.dict(os.environ, {}, clear=False):
            # Ensure GITHUB_SHA is not set
            for key in env_remove:
                os.environ.pop(key, None)
            prov, source = detect_ci_provenance()

        assert prov is None
        assert source is None


class TestResolveProvenance:
    """Tests for provenance resolution priority."""

    def test_manual_override_wins(self, tmp_path):
        """Manual override beats CI and local git."""
        f = tmp_path / "test"
        f.write_text("test")

        env = {"GITHUB_SHA": "abc123def456789012345678901234567890abcd"}
        with patch.dict(os.environ, env, clear=False):
            prov, source = resolve_provenance(str(f), manual_override="release/v1.0@deadbeef")

        assert prov == "release/v1.0@deadbeef"
        assert source == "manual"

    def test_ci_beats_local(self, git_repo):
        """CI provenance beats local git when both available."""
        _, file_path = git_repo

        env = {
            "GITHUB_SHA": "abc123def456789012345678901234567890abcd",
            "GITHUB_REF_NAME": "main",
            "GITHUB_RUN_ID": "99",
        }
        with patch.dict(os.environ, env, clear=False):
            prov, source = resolve_provenance(file_path)

        assert source == "ci/github"
        assert "abc123de" in prov

    def test_fallback_to_local(self, git_repo):
        """Falls back to local git when no CI and no manual override."""
        _, file_path = git_repo

        # Ensure no CI env vars
        for key in ("GITHUB_SHA", "GITHUB_REF_NAME", "GITHUB_RUN_ID"):
            os.environ.pop(key, None)

        prov, source = resolve_provenance(file_path)

        assert source == "local"
        assert prov is not None
        assert "@" in prov  # branch@hash format
