#!/usr/bin/env python3
"""Week-1 feasibility harness: measure bsdiff patch size + compute latency.

Design doc (`docs/designs/vercel-for-cubesats.md`) gates the whole iterate
claim on this test:

    "Feasibility test on DISCO-2 (p50 ≤10s over ZMQ/CAN with 500KB binary
     via bsdiff; measure patch-size p50/p95/p99 too)"

Two modes:

* **Synthetic (default):** build a 500 KB baseline binary, mutate N random
  bytes per iteration, compute bsdiff, record size + latency. Runs anywhere
  with no external state, so you can iterate on the harness before going to
  hardware.

* **Pair (``--pair OLD NEW``):** compute a single bsdiff between two real
  binaries you supply (e.g. successive ``controller`` builds). Good for a
  one-shot sanity check with your actual workload.

Output: a small plain-text summary + optional ``--json`` dump so the numbers
can feed into the thesis evaluation table later.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from satdeploy.bsdiff_util import (  # noqa: E402
    BSDIFF_MAX_OLD_BYTES,
    apply_patch,
    compute_patch,
)

DEFAULT_BASELINE_SIZE = 500 * 1024
DEFAULT_ITERATIONS = 100
DEFAULT_MIN_DELTA = 64
DEFAULT_MAX_DELTA = 4096


def make_baseline(size: int, seed: int = 0xC0FFEE) -> bytes:
    """Deterministic pseudo-binary of ``size`` bytes for reproducible runs."""
    rng = random.Random(seed)
    return bytes(rng.getrandbits(8) for _ in range(size))


def mutate(baseline: bytes, delta_bytes: int, rng: random.Random) -> bytes:
    """Replace ``delta_bytes`` contiguous bytes at a random offset."""
    if delta_bytes >= len(baseline):
        raise ValueError("delta larger than baseline")
    offset = rng.randrange(0, len(baseline) - delta_bytes)
    replacement = bytes(rng.getrandbits(8) for _ in range(delta_bytes))
    return baseline[:offset] + replacement + baseline[offset + delta_bytes:]


def percentiles(values: list[float], p: list[float]) -> dict[str, float]:
    if not values:
        return {f"p{int(q)}": 0.0 for q in p}
    sorted_vals = sorted(values)
    out = {}
    for q in p:
        if q >= 100:
            out[f"p{int(q)}"] = sorted_vals[-1]
            continue
        idx = int(round((q / 100.0) * (len(sorted_vals) - 1)))
        out[f"p{int(q)}"] = sorted_vals[idx]
    return out


def run_synthetic(
    size: int,
    iterations: int,
    min_delta: int,
    max_delta: int,
    seed: int,
) -> dict:
    if size > BSDIFF_MAX_OLD_BYTES:
        raise SystemExit(
            f"baseline size {size} exceeds BSDIFF_MAX_OLD_BYTES "
            f"({BSDIFF_MAX_OLD_BYTES}); bsdiff would be skipped in production"
        )

    baseline = make_baseline(size)
    rng = random.Random(seed)

    patch_sizes: list[int] = []
    compute_ms: list[float] = []

    for i in range(iterations):
        delta = rng.randint(min_delta, max_delta)
        new_bytes = mutate(baseline, delta, rng)

        t0 = time.perf_counter()
        patch = compute_patch(baseline, new_bytes)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        if patch is None:
            raise SystemExit("compute_patch returned None for in-range baseline")

        # Sanity: patch applies cleanly and produces byte-identical output.
        rebuilt = apply_patch(baseline, patch)
        if rebuilt != new_bytes:
            raise SystemExit(f"iteration {i}: bspatch mismatch (bsdiff4 version skew?)")

        patch_sizes.append(len(patch))
        compute_ms.append(elapsed_ms)

    return {
        "mode": "synthetic",
        "baseline_size": size,
        "iterations": iterations,
        "min_delta": min_delta,
        "max_delta": max_delta,
        "patch_size_bytes": {
            "min": min(patch_sizes),
            "max": max(patch_sizes),
            "mean": statistics.mean(patch_sizes),
            **percentiles(patch_sizes, [50, 95, 99]),
        },
        "compute_ms": {
            "min": min(compute_ms),
            "max": max(compute_ms),
            "mean": statistics.mean(compute_ms),
            **percentiles(compute_ms, [50, 95, 99]),
        },
    }


def run_pair(old_path: Path, new_path: Path) -> dict:
    old_bytes = old_path.read_bytes()
    new_bytes = new_path.read_bytes()

    t0 = time.perf_counter()
    patch = compute_patch(old_bytes, new_bytes)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    result = {
        "mode": "pair",
        "old": str(old_path),
        "new": str(new_path),
        "old_size": len(old_bytes),
        "new_size": len(new_bytes),
        "compute_ms": elapsed_ms,
    }
    if patch is None:
        result["patch_size"] = None
        result["skipped"] = "old binary exceeds BSDIFF_MAX_OLD_BYTES"
        return result

    rebuilt = apply_patch(old_bytes, patch)
    if rebuilt != new_bytes:
        raise SystemExit("bspatch mismatch (bsdiff4 version skew?)")

    result["patch_size"] = len(patch)
    result["patch_ratio"] = len(patch) / len(new_bytes)
    return result


def format_synthetic(report: dict) -> str:
    ps = report["patch_size_bytes"]
    cm = report["compute_ms"]
    return (
        f"Synthetic feasibility run\n"
        f"  baseline : {report['baseline_size']:>10} bytes\n"
        f"  trials   : {report['iterations']}\n"
        f"  delta    : {report['min_delta']}..{report['max_delta']} bytes per trial\n"
        f"\n"
        f"  patch size (bytes)   p50={ps['p50']:<8} p95={ps['p95']:<8} p99={ps['p99']:<8} max={ps['max']}\n"
        f"  compute  (ms)        p50={cm['p50']:<8.2f} p95={cm['p95']:<8.2f} p99={cm['p99']:<8.2f} max={cm['max']:.2f}\n"
    )


def format_pair(report: dict) -> str:
    if "skipped" in report:
        return f"Pair skipped: {report['skipped']}\n"
    ratio_pct = report["patch_ratio"] * 100
    return (
        f"Pair feasibility run\n"
        f"  old      : {report['old']} ({report['old_size']} bytes)\n"
        f"  new      : {report['new']} ({report['new_size']} bytes)\n"
        f"  patch    : {report['patch_size']} bytes ({ratio_pct:.2f}% of new)\n"
        f"  compute  : {report['compute_ms']:.2f} ms\n"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--size", type=int, default=DEFAULT_BASELINE_SIZE,
                   help="baseline size in bytes (default: %(default)s)")
    p.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS,
                   help="synthetic-mode trial count (default: %(default)s)")
    p.add_argument("--min-delta", type=int, default=DEFAULT_MIN_DELTA,
                   help="smallest mutation size in bytes (default: %(default)s)")
    p.add_argument("--max-delta", type=int, default=DEFAULT_MAX_DELTA,
                   help="largest mutation size in bytes (default: %(default)s)")
    p.add_argument("--seed", type=int, default=int(os.environ.get("SATDEPLOY_SEED", "1")),
                   help="RNG seed for reproducibility (default: %(default)s)")
    p.add_argument("--pair", nargs=2, metavar=("OLD", "NEW"),
                   help="compute a single patch between two real binaries")
    p.add_argument("--json", action="store_true",
                   help="emit machine-readable JSON instead of a summary")
    args = p.parse_args(argv)

    if args.pair:
        report = run_pair(Path(args.pair[0]), Path(args.pair[1]))
        out = format_pair(report)
    else:
        report = run_synthetic(args.size, args.iterations,
                               args.min_delta, args.max_delta, args.seed)
        out = format_synthetic(report)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(out, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
