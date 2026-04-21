"""Unit tests for the week-1 feasibility harness (scripts/feasibility_test.py).

The harness lives under ``scripts/`` because it's a standalone evaluation tool
rather than library code, but its mutation helpers and pair-batch aggregation
carry the load-bearing claim for the iterate wedge (p50 / p95 / p99 patch-size
distributions). Loading the script as a module lets us pin the invariants.
"""

from __future__ import annotations

import importlib.util
import random
from pathlib import Path

import pytest

from satdeploy.bsdiff_util import apply_patch, compute_patch

_HARNESS_PATH = Path(__file__).resolve().parent.parent / "scripts" / "feasibility_test.py"
_spec = importlib.util.spec_from_file_location("feasibility_test", _HARNESS_PATH)
assert _spec is not None and _spec.loader is not None
feasibility_test = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(feasibility_test)


@pytest.mark.parametrize("kind", ["replace", "insert", "delete"])
def test_mutation_roundtrips_through_bsdiff(kind):
    rng = random.Random(42)
    baseline = feasibility_test.make_baseline(4096)
    new = feasibility_test.mutate(kind, baseline, 64, rng)

    # Length invariants per mutation kind.
    if kind == "insert":
        assert len(new) == len(baseline) + 64
    elif kind == "delete":
        assert len(new) == len(baseline) - 64
    else:
        assert len(new) == len(baseline)

    # Every mutation must be recoverable via bsdiff → bspatch.
    patch = compute_patch(baseline, new)
    assert patch is not None
    assert apply_patch(baseline, patch) == new


def test_mixed_mutation_dispatches_across_kinds():
    rng = random.Random(0)
    baseline = feasibility_test.make_baseline(4096)
    length_deltas: set[int] = set()
    for _ in range(30):
        new = feasibility_test.mutate("mixed", baseline, 64, rng)
        length_deltas.add(len(new) - len(baseline))
    # Any two of {replace=0, insert=+64, delete=-64} landing is enough to prove
    # the dispatch is actually sampling — not stuck on one kind.
    assert len(length_deltas) >= 2


def test_unknown_mutation_kind_raises():
    rng = random.Random(1)
    baseline = feasibility_test.make_baseline(1024)
    with pytest.raises(ValueError, match="unknown mutation kind"):
        feasibility_test.mutate("bogus", baseline, 16, rng)


def test_pair_batch_aggregates_adjacent_pairs(tmp_path):
    rng = random.Random(7)
    baseline = feasibility_test.make_baseline(4096)
    (tmp_path / "0001.bin").write_bytes(baseline)
    second = feasibility_test.mutate("insert", baseline, 32, rng)
    (tmp_path / "0002.bin").write_bytes(second)
    third = feasibility_test.mutate("replace", second, 128, rng)
    (tmp_path / "0003.bin").write_bytes(third)

    report = feasibility_test.run_pair_batch(tmp_path)

    assert report["mode"] == "pair-batch"
    assert report["pairs"] == 2
    assert report["skipped"] == []
    assert report["patch_size_bytes"]["min"] > 0
    assert 0.0 < report["patch_ratio"]["p50"] <= 1.0
    # per_pair must be emitted in sorted order, not arbitrary iterdir order.
    assert [Path(rec["new"]).name for rec in report["per_pair"]] == ["0002.bin", "0003.bin"]


def test_pair_batch_errors_when_directory_has_too_few_files(tmp_path):
    (tmp_path / "only.bin").write_bytes(b"not enough")
    with pytest.raises(SystemExit, match="need at least 2 files"):
        feasibility_test.run_pair_batch(tmp_path)


def test_pair_batch_skips_oversize_old_without_aborting(tmp_path, monkeypatch):
    # Dial the bsdiff size guard down so we can exercise the skip path without
    # generating megabytes of synthetic data.
    from satdeploy import bsdiff_util
    monkeypatch.setattr(bsdiff_util, "BSDIFF_MAX_OLD_BYTES", 64)

    # 3 files: first 128 B (triggers skip when used as old), then two small
    # files that DO roundtrip so the run still has usable pairs.
    (tmp_path / "0001.bin").write_bytes(b"x" * 128)      # old → oversize, skip
    (tmp_path / "0002.bin").write_bytes(b"y" * 32)       # new (small); next iter uses this as old
    (tmp_path / "0003.bin").write_bytes(b"y" * 32 + b"z")

    report = feasibility_test.run_pair_batch(tmp_path)

    assert report["pairs"] == 1
    assert report["skipped"] == [str(tmp_path / "0001.bin")]


def test_pair_batch_detects_bsdiff_version_skew(tmp_path, monkeypatch):
    # Simulate the landmine: apply_patch returns wrong bytes. Harness must
    # abort — a silent mismatch would mean deployed binaries don't match their
    # expected SHA256 on target.
    (tmp_path / "0001.bin").write_bytes(b"a" * 64)
    (tmp_path / "0002.bin").write_bytes(b"b" * 64)

    monkeypatch.setattr(feasibility_test, "apply_patch", lambda old, patch: b"wrong")

    with pytest.raises(SystemExit, match="bspatch mismatch"):
        feasibility_test.run_pair_batch(tmp_path)
