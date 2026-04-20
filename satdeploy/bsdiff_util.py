"""Incremental binary-patch helpers (BSDIFF4).

Used by `satdeploy iterate` / `satdeploy push` to upload a delta instead of
the full binary when the previous deployment is still known. Patch is applied
on the target by the matching `bspatch` (libbsdiff4 / bsdiff4-CLI).

Only two operations are exported:

    compute_patch(old_bytes, new_bytes) -> Optional[bytes]
    apply_patch(old_bytes, patch_bytes) -> bytes

`compute_patch` returns ``None`` when the incremental path is unsafe — the
caller falls back to a full upload. Today the only such case is the
**5 MB size guard**: bsdiff's internal algorithm runs at roughly 17× the old
binary's size in RAM (per libbsdiff memory profiling). A 20 MB binary would
touch ~340 MB of RSS on the dev laptop, which is both slow and can OOM on
small CI runners. Skipping bsdiff for large files is cheap — full upload is
not the bottleneck when the binary itself is already multi-megabyte.
"""

from __future__ import annotations

from typing import Optional

import bsdiff4

BSDIFF_MAX_OLD_BYTES = 5 * 1024 * 1024
"""Skip bsdiff if the previous binary exceeds this size (landmine P1 #5)."""


def compute_patch(old_bytes: bytes, new_bytes: bytes) -> Optional[bytes]:
    """Compute a BSDIFF4 patch from ``old_bytes`` → ``new_bytes``.

    Returns ``None`` if the old binary is larger than ``BSDIFF_MAX_OLD_BYTES``;
    the caller should then send the full ``new_bytes`` unmodified.
    """
    if len(old_bytes) > BSDIFF_MAX_OLD_BYTES:
        return None
    return bsdiff4.diff(old_bytes, new_bytes)


def apply_patch(old_bytes: bytes, patch_bytes: bytes) -> bytes:
    """Apply a BSDIFF4 ``patch_bytes`` to ``old_bytes`` and return the result."""
    return bsdiff4.patch(old_bytes, patch_bytes)
