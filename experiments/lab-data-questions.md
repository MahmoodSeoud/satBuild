# Lab data — what we need to ask the DISCO ground-station team

This is a one-page sheet you can take to the operations team / Julian to unblock the trace-driven experiment plan (`flatsat-test-plan.md` §3). The thesis chapter on packet-loss recovery depends on having real pass-log data we can replay through software.

## The big ask, in one sentence

> *"During real DISCO passes, what telemetry do we capture about which CSP packets actually arrived versus which were lost, and how can I get a sample of that data in a parseable format?"*

If you only get an answer to that one question, follow up with the specifics below.

## Specific questions, grouped by priority

### Tier 1 — must answer before we can start (W0 blockers)

1. **What logs do we currently capture per pass?**
   - Ground-station receive log? Modem-side log? CSP-router log? OBC-side log?
   - Multiple logs per pass — which is the canonical source for "what got through"?

2. **What's in those logs?** Specifically:
   - Per-CSP-packet receive timestamps?
   - Per-frame modem CRC pass/fail?
   - Modem lock/unlock events (carrier acquired / lost)?
   - RSSI / SNR samples?
   - Anything else?

3. **What's the file format?**
   - CSV? JSON? Binary (which schema)? Custom telemetry frames? Pre-parsed Grafana metrics?
   - One file per pass, or a streaming append-only log?

4. **Where are these logs stored?**
   - A directory on a server? A Grafana database? An S3 bucket? Spreadsheet maintained by hand?
   - Can I get read access?

5. **Can you give me one or two recent pass logs as samples?**
   - "One quiet pass and one with notable fades" is ideal for first tests.
   - Format is fine as-is — we'll write the parser around whatever you have.

### Tier 2 — informs experiment design (need within W1)

6. **Time resolution of the timestamps.**
   - Per-packet (best)? Per-second buckets? Per-frame at the modem?

7. **How many archived passes do we have?**
   - <10 (need to wait and accumulate more)? ~100 (plenty for a thesis)? >1000 (we can subsample)?
   - Spans roughly what date range?

8. **Pattern diversity.**
   - Do the archived passes span different conditions? (Day/night, high/low elevation, weather variation, geographic ground stations.)
   - If we can pick: 5–10 passes from across the operational envelope is the sweet spot for a defensible pattern library.

9. **Is there documentation of the pass-log schema?**
   - If yes, link please.
   - If no, willing to spend 30 min walking me through one example file?

### Tier 3 — nice to have (W2+)

10. **Telemetry alongside packet outcomes.**
    - During a pass, do we also log radio modem AGC, OBC CPU load, antenna pointing, etc.? These correlate with loss events and are great for the thesis discussion section.

11. **Existing analysis tools.**
    - Has anyone in the lab already written code to parse pass logs? Even a small Python notebook that loads them into pandas would save days.

12. **F12 (live-satellite acceptance) coordination.**
    - When can we plausibly get 3–4 consecutive passes worth of dedicated test traffic? Need to coordinate this in advance with mission ops.
    - The F12 experiment uses the same harness as flatsat — only the link changes — so the scheduling load is just "during pass X, run this command."

## Why this matters (one paragraph for context)

Per `flatsat-test-plan.md` §3, the headline thesis experiments (F3 loss curve, F4 fade replay, F5 pass window) use **trace-driven simulation**: we replay the exact loss patterns observed during real passes against the protocol on the bench. This requires a library of pass-log files that we convert into a simple pattern format (`experiments/loss-pattern-format.md`). Without those logs, F3/F4 fall back to parametric models (Bernoulli loss / Gilbert-Elliott burst) that are weaker scientifically — replaying *what actually happened* is more defensible than *what might happen*.

## What we'll do with the data

- Convert each pass log into a `*.pattern` file via `experiments/lib/parse_pass_log.py`.
- Build a library: `clean.pattern`, `marginal.pattern`, `bad.pattern`, plus scaled variants.
- Replay them via the agent's `loss_filter` (compile-time-gated, NEVER ships to flight).
- Cite the patterns in the thesis methodology: "evaluation uses pass logs from N=X DISCO passes between dates A and B."

The pass logs themselves don't end up in the public repo — we cite them by date / pass-id and keep the raw files private if necessary. Derived `*.pattern` files can be sanitized (drop RSSI, keep only the up/down events) and shipped alongside the thesis.

## Definition we want to settle now

A pass log can mark "loss" at multiple layers. For consistency the thesis defines loss as:

> **A CSP packet was sent (or expected by the receiver) but did not arrive at the application within timeout.**

Reasoning: that's what DTP actually responds to. CRC failures the modem recovers from internally don't matter; we want the loss visible to the protocol under test. If your logs measure loss at a different layer (e.g. only modem CRC), let me know — the parser can interpolate or aggregate, but I'd rather use your data's natural unit if possible.

## Acceptance criterion for "we have the data"

- ✅ At least 3 sample pass logs in hand.
- ✅ I can run `parse_pass_log.py from-log <file> --out test.pattern` and produce a valid pattern file.
- ✅ The agent boots successfully with `LOSS_PATTERN_FILE=test.pattern` and prints the expected drop stats.
- ✅ A satdeploy push under that pattern produces sensible behavior (some retries, eventual success).

Once those four boxes are checked, F3/F4/F5 are unblocked and the rest of the thesis evaluation moves at the speed of "run scripts and gather CSVs."
