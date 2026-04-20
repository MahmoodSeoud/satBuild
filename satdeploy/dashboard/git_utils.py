"""``git show`` subprocess helper with LRU caching (eng-review L6).

The R6 iteration page renders ``git show <hash>`` inside ``<pre>`` tags.
Git commits are immutable, so the cache is trivially correct: hash in,
diff out, forever. ``functools.lru_cache`` keeps it bounded.

Callers must escape the result before rendering as HTML — the cache
returns raw git output which can contain ``<``, ``>``, ``&``. Jinja2
``autoescape=True`` (default in FastAPI's ``Jinja2Templates``) is the
standard escape; the ``iteration.html`` template uses ``{{ diff }}``
(NOT ``{{ diff | safe }}``) for exactly this reason.
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Optional


class GitLookupError(Exception):
    """Raised when git is unavailable or the commit cannot be resolved."""


def _run_git_show(git_hash: str, repo: Optional[str] = None) -> str:
    cmd = ["git"]
    if repo:
        cmd.extend(["-C", repo])
    cmd.extend(["show", "--stat", "--patch", git_hash])
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        raise GitLookupError(proc.stderr.strip() or f"git show {git_hash} failed")
    return proc.stdout


@lru_cache(maxsize=256)
def git_show(git_hash: str, repo: Optional[str] = None) -> str:
    """Return ``git show --stat --patch <git_hash>`` output. Cached forever."""
    return _run_git_show(git_hash, repo)


def clear_cache() -> None:
    git_show.cache_clear()
