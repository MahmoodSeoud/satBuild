"""Unit tests for satdeploy.bsdiff_util (P0 landmine #4 + P1 landmine #5)."""

import os

import pytest

from satdeploy import bsdiff_util


def test_patch_roundtrip_small_delta():
    old = b"hello world " * 1000  # ~12 KB
    new = old.replace(b"world", b"earth")
    patch = bsdiff_util.compute_patch(old, new)
    assert patch is not None
    assert bsdiff_util.apply_patch(old, patch) == new


def test_patch_roundtrip_identical_inputs():
    blob = os.urandom(4096)
    patch = bsdiff_util.compute_patch(blob, blob)
    assert patch is not None
    assert bsdiff_util.apply_patch(blob, patch) == blob


def test_size_guard_returns_none_above_threshold():
    # Use sentinel `bytes` subclass so we don't actually allocate 5MB+1 of data.
    class FakeBytes(bytes):
        def __new__(cls, length):
            instance = super().__new__(cls, b"")
            instance._length = length
            return instance

        def __len__(self):
            return self._length

    oversized = FakeBytes(bsdiff_util.BSDIFF_MAX_OLD_BYTES + 1)
    assert bsdiff_util.compute_patch(oversized, b"anything") is None


def test_size_guard_allows_exact_threshold(monkeypatch):
    # Verify the comparison is strict (`>`, not `>=`): a buffer of exactly the
    # threshold length is still processed. We dial the threshold down to a
    # small value so bsdiff doesn't churn on megabytes of data.
    monkeypatch.setattr(bsdiff_util, "BSDIFF_MAX_OLD_BYTES", 4096)
    old = os.urandom(4096)
    new = old[:2000] + b"edit" + old[2004:]
    patch = bsdiff_util.compute_patch(old, new)
    assert patch is not None
    assert bsdiff_util.apply_patch(old, patch) == new


def test_patch_size_smaller_than_full_binary_for_local_edit():
    # Regression: if bsdiff suddenly produces "full binary + overhead" for a
    # tiny delta, something has broken (version skew, wrong algorithm). This
    # guards the premise of the whole iterate wedge.
    old = bytes(range(256)) * 1000  # 256 KB deterministic
    new = bytearray(old)
    new[12345:12355] = b"ABCDEFGHIJ"
    patch = bsdiff_util.compute_patch(old, bytes(new))
    assert patch is not None
    assert len(patch) < len(old) // 4, (
        f"patch is {len(patch)} bytes for a 10-byte edit — expected much smaller"
    )
