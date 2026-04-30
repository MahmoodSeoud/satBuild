#!/usr/bin/env python3
"""
parse_pass_log.py — convert real DISCO pass logs into loss-pattern files.

Status: STUB. The actual parsing logic depends on what format the lab's
operations team produces. This stub:
  - Documents the expected interface.
  - Implements the format-agnostic transformations (scale, shift, splice,
    validate) that work on already-parsed pattern files.
  - Has a clear `_parse_real_log()` extension point with TODO markers.

Once we know what the real logs look like (CSV from a logger, GreatViewer
output, raw CSP receive timestamps, JSON telemetry, ...), wire it into
`_parse_real_log` and the rest of this script just works.

Pattern format documented in experiments/loss-pattern-format.md.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path
from typing import Iterable


# --------------------------------------------------------------------------
# Pattern model
# --------------------------------------------------------------------------

@dataclasses.dataclass
class PatternEvent:
    """One line in a pattern file: a timestamp + an action."""
    t_offset_s: float          # seconds from pattern start
    action: str                # 'up' | 'down' | 'prob' | 'clear'
    prob: float | None = None  # for action='prob' only

    def render(self) -> str:
        if self.action == "prob":
            assert self.prob is not None
            return f"{self.t_offset_s:.3f}  prob {self.prob:.4f}"
        return f"{self.t_offset_s:.3f}  {self.action}"


@dataclasses.dataclass
class Pattern:
    """A list of events plus optional metadata header lines."""
    events: list[PatternEvent]
    metadata: dict[str, str] = dataclasses.field(default_factory=dict)
    header_comments: list[str] = dataclasses.field(default_factory=list)

    def render(self) -> str:
        lines: list[str] = []
        lines.extend(f"# {c}" for c in self.header_comments)
        for k, v in self.metadata.items():
            lines.append(f"# pass_meta:{k}={v}")
        lines.append("")
        for ev in self.events:
            lines.append(ev.render())
        return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Pattern file I/O
# --------------------------------------------------------------------------

def load_pattern(path: Path) -> Pattern:
    """Read a .pattern file and return a Pattern."""
    events: list[PatternEvent] = []
    metadata: dict[str, str] = {}
    header_comments: list[str] = []
    with path.open() as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                stripped = line.lstrip("#").strip()
                if stripped.startswith("pass_meta:"):
                    payload = stripped[len("pass_meta:"):].strip()
                    for chunk in payload.split():
                        if "=" in chunk:
                            k, v = chunk.split("=", 1)
                            metadata[k] = v
                else:
                    header_comments.append(stripped)
                continue
            parts = line.split()
            t = float(parts[0])
            action = parts[1]
            prob = float(parts[2]) if action == "prob" else None
            events.append(PatternEvent(t_offset_s=t, action=action, prob=prob))
    return Pattern(events=events, metadata=metadata,
                   header_comments=header_comments)


def write_pattern(path: Path, pat: Pattern) -> None:
    path.write_text(pat.render())


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def validate(pat: Pattern) -> list[str]:
    """Return a list of error messages; empty list = valid."""
    errors: list[str] = []
    valid_actions = {"up", "down", "prob", "clear"}
    last_t = -1.0
    for i, ev in enumerate(pat.events):
        if ev.t_offset_s < 0:
            errors.append(f"event[{i}]: negative t_offset {ev.t_offset_s}")
        if ev.t_offset_s < last_t:
            errors.append(
                f"event[{i}]: timestamps not monotonic "
                f"({ev.t_offset_s} < previous {last_t})"
            )
        last_t = max(last_t, ev.t_offset_s)
        if ev.action not in valid_actions:
            errors.append(f"event[{i}]: unknown action '{ev.action}'")
        if ev.action == "prob":
            if ev.prob is None or not (0.0 <= ev.prob <= 1.0):
                errors.append(f"event[{i}]: prob must be in [0,1], got {ev.prob}")
    return errors


# --------------------------------------------------------------------------
# Transformations
# --------------------------------------------------------------------------

def scale(pat: Pattern, factor: float) -> Pattern:
    """
    Multiply drop intensity by `factor`.

    For up/down patterns: stretch each `down` interval by `factor`.
    For `prob` segments: multiply probability by `factor` (clamped to [0,1]).

    factor=0.5 -> half the drops; factor=2.0 -> twice the drops.
    """
    if factor < 0:
        raise ValueError("scale factor must be non-negative")
    out_events: list[PatternEvent] = []
    state = "up"
    interval_start = 0.0
    for ev in pat.events:
        if ev.action == "down":
            state = "down"
            interval_start = ev.t_offset_s
            out_events.append(PatternEvent(ev.t_offset_s, "down"))
        elif ev.action == "up" and state == "down":
            recorded_len = ev.t_offset_s - interval_start
            new_len = recorded_len * factor
            new_up_t = interval_start + new_len
            out_events.append(PatternEvent(new_up_t, "up"))
            state = "up"
        elif ev.action == "prob":
            new_prob = max(0.0, min(1.0, (ev.prob or 0.0) * factor))
            out_events.append(PatternEvent(ev.t_offset_s, "prob", new_prob))
        else:
            out_events.append(PatternEvent(ev.t_offset_s, ev.action, ev.prob))
    out_meta = dict(pat.metadata)
    out_meta["scaled_by"] = f"{factor}"
    return Pattern(events=out_events, metadata=out_meta,
                   header_comments=pat.header_comments + [
                       f"Derived: scaled by {factor}x"
                   ])


def shift(pat: Pattern, dt_s: float) -> Pattern:
    """Add `dt_s` to every timestamp. Negative values not supported."""
    if dt_s < 0:
        raise ValueError("negative shift not supported")
    out_events = [PatternEvent(ev.t_offset_s + dt_s, ev.action, ev.prob)
                  for ev in pat.events]
    out_meta = dict(pat.metadata)
    out_meta["shifted_by_s"] = f"{dt_s}"
    return Pattern(events=out_events, metadata=out_meta,
                   header_comments=pat.header_comments + [
                       f"Derived: shifted by {dt_s} s"
                   ])


def build_pass_window(pass_len_s: float, gap_s: float,
                      total_len_s: float) -> Pattern:
    """
    Build a synthetic pass-window pattern for F5.

    Yields: link up for pass_len_s, down for gap_s, up for pass_len_s, ...
    until total_len_s is exceeded.
    """
    events: list[PatternEvent] = []
    t = 0.0
    state = "up"
    events.append(PatternEvent(0.0, "up"))
    while t < total_len_s:
        if state == "up":
            t += pass_len_s
            events.append(PatternEvent(t, "down"))
            state = "down"
        else:
            t += gap_s
            events.append(PatternEvent(t, "up"))
            state = "up"
    return Pattern(
        events=events,
        metadata={
            "pattern_kind": "synthetic_pass_window",
            "pass_len_s": str(pass_len_s),
            "gap_s": str(gap_s),
        },
        header_comments=[
            f"Synthetic pass-window pattern: {pass_len_s}s up / {gap_s}s down",
        ],
    )


# --------------------------------------------------------------------------
# Real-log parsing (THE EXTENSION POINT — fill in once we know the format)
# --------------------------------------------------------------------------

def _parse_real_log(path: Path, loss_definition: str = "csp_timeout") -> Pattern:
    """
    Convert a real DISCO pass log into a Pattern.

    TODO: implement once we know the actual log format from the lab.

    Likely candidates:
      - CSV from a Python logger: timestamp, packet_id, outcome
      - JSON streamed telemetry from libparam
      - Raw CSP receive timestamps from the modem
      - libgreat / ground-station log format

    `loss_definition` controls how we interpret the input:
      - "csp_timeout"   - drop = CSP packet not delivered to app (recommended)
      - "modem_lock"    - drop = modem reports loss-of-lock for this interval
      - "crc_failure"   - drop = modem CRC failed (more conservative; counts
                          recoverable bit errors as drops)

    Returns a Pattern object ready to write_pattern() out.
    """
    raise NotImplementedError(
        "Real-log parsing not implemented. Once the lab tells us what "
        "format the pass logs are in, implement this function. See "
        "experiments/lab-data-questions.md for the questions to ask."
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_validate = sub.add_parser("validate", help="Validate a pattern file")
    p_validate.add_argument("path", type=Path)

    p_scale = sub.add_parser("scale", help="Scale drop intensity")
    p_scale.add_argument("path", type=Path)
    p_scale.add_argument("--factor", type=float, required=True)
    p_scale.add_argument("--out", type=Path, required=True)

    p_shift = sub.add_parser("shift", help="Shift timestamps")
    p_shift.add_argument("path", type=Path)
    p_shift.add_argument("--dt", type=float, required=True)
    p_shift.add_argument("--out", type=Path, required=True)

    p_pw = sub.add_parser("build-pass-window",
                          help="Generate synthetic pass-window pattern")
    p_pw.add_argument("--pass-len-s", type=float, required=True)
    p_pw.add_argument("--gap-s", type=float, required=True)
    p_pw.add_argument("--total-len-s", type=float, required=True)
    p_pw.add_argument("--out", type=Path, required=True)

    p_parse = sub.add_parser("from-log",
                             help="Parse a real pass log into a pattern")
    p_parse.add_argument("path", type=Path)
    p_parse.add_argument("--loss-def", default="csp_timeout",
                         choices=["csp_timeout", "modem_lock", "crc_failure"])
    p_parse.add_argument("--out", type=Path, required=True)

    args = ap.parse_args()

    if args.cmd == "validate":
        pat = load_pattern(args.path)
        errors = validate(pat)
        if errors:
            for e in errors:
                print(f"ERROR: {e}", file=sys.stderr)
            return 1
        print(f"OK: {args.path} ({len(pat.events)} events)")
        return 0

    if args.cmd == "scale":
        pat = load_pattern(args.path)
        write_pattern(args.out, scale(pat, args.factor))
        return 0

    if args.cmd == "shift":
        pat = load_pattern(args.path)
        write_pattern(args.out, shift(pat, args.dt))
        return 0

    if args.cmd == "build-pass-window":
        pat = build_pass_window(args.pass_len_s, args.gap_s, args.total_len_s)
        write_pattern(args.out, pat)
        return 0

    if args.cmd == "from-log":
        pat = _parse_real_log(args.path, args.loss_def)
        write_pattern(args.out, pat)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
