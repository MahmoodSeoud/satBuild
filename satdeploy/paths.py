"""Path utilities for config-provided paths.

Config files (YAML) carry user-facing paths like ``~/builds/controller``
or ``$HOME/build/libparam.so``. The project was only calling
``os.path.expanduser`` on these, which handles ``~`` but not ``$VAR``
references — so a user who wrote ``$HOME/...`` in config.yaml got the
literal ``$HOME`` back, producing a confusing "file not found" error
(hit live on 2026-04-23 during the Pi benchmark setup).

``expand_path`` does both expansions in the correct order (env vars
first, then ``~``, because ``~`` may itself reference ``$HOME``). Any
undefined ``$VAR`` references are left literal, matching shell
``${VAR-}`` behavior — we don't want to surprise-fail on a typo; the
downstream "file not found" error names the unresolved path.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Union


def expand_path(p: Union[str, Path, None]) -> str:
    """Expand ``$VAR`` and ``~`` in a config-provided path string.

    Args:
        p: Path string or ``Path`` object. ``None`` / empty returns "".

    Returns:
        Expanded path as a string. If a ``$VAR`` is undefined, it stays
        literal (matching ``os.path.expandvars`` default) — the caller
        gets to produce a clearer "file not found" error downstream.
    """
    if not p:
        return ""
    return os.path.expanduser(os.path.expandvars(str(p)))
