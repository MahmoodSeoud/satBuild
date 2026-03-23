"""Git provenance tracking for deployed files."""

import os
import subprocess
from typing import Optional


def capture_provenance(file_path: str) -> Optional[str]:
    """Capture git provenance for the directory containing a file.

    Runs git commands in the directory of file_path to capture:
    - commit hash (short, 8 chars)
    - branch name (or None if detached HEAD)
    - dirty flag (uncommitted changes)

    Returns:
        Provenance string like "main@3c940acf", "main@3c940acf-dirty",
        "@3c940acf" (detached HEAD), or None (not in git repo).
    """
    try:
        work_dir = os.path.dirname(os.path.abspath(file_path))

        # Get short commit hash
        result = subprocess.run(
            ["git", "-C", work_dir, "rev-parse", "--short=8", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        commit_hash = result.stdout.strip()

        # Get branch name ("HEAD" if detached)
        result = subprocess.run(
            ["git", "-C", work_dir, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        branch = result.stdout.strip()

        # Check for dirty tree (exit code 1 = dirty)
        result = subprocess.run(
            ["git", "-C", work_dir, "diff-index", "--quiet", "HEAD", "--"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        dirty = result.returncode != 0

        # Build provenance string
        if branch == "HEAD":
            # Detached HEAD
            provenance = f"@{commit_hash}"
        else:
            provenance = f"{branch}@{commit_hash}"

        if dirty:
            provenance += "-dirty"

        return provenance

    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None


def is_dirty(provenance: str | None) -> bool:
    """Check if a provenance string indicates a dirty working tree.

    Uses endswith() rather than 'in' to avoid false positives from
    branch names containing 'dirty' (e.g., 'fix-dirty-flag@abc12345').
    """
    return provenance is not None and provenance.endswith("-dirty")


def detect_ci_provenance() -> tuple[Optional[str], Optional[str]]:
    """Auto-detect CI environment and return (provenance_string, source).

    Currently supports GitHub Actions. Returns (None, None) if not in CI.

    GitHub Actions sets:
    - GITHUB_SHA: full commit hash
    - GITHUB_REF_NAME: branch or tag name
    - GITHUB_RUN_ID: workflow run identifier
    """
    github_sha = os.environ.get("GITHUB_SHA")
    if github_sha:
        ref = os.environ.get("GITHUB_REF_NAME", "")
        run_id = os.environ.get("GITHUB_RUN_ID", "")
        short_sha = github_sha[:8]

        prov = f"{ref}@{short_sha}" if ref else f"@{short_sha}"
        if run_id:
            prov += f" (ci:github/run/{run_id})"
        return prov, "ci/github"

    return None, None


def resolve_provenance(
    file_path: str,
    manual_override: Optional[str] = None,
) -> tuple[Optional[str], str]:
    """Resolve provenance with priority: manual > CI > local git.

    Args:
        file_path: Path to the file being deployed (used for local git lookup).
        manual_override: If set, use this string as provenance.

    Returns:
        (provenance_string, source) where source is "manual", "ci/github",
        or "local".
    """
    if manual_override:
        return manual_override, "manual"

    ci_prov, ci_source = detect_ci_provenance()
    if ci_prov:
        return ci_prov, ci_source

    local_prov = capture_provenance(file_path)
    return local_prov, "local"
