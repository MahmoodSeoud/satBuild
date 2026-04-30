# Flatsat test plan — reliable data transfer over UHF for CSP-based CubeSats

**Date:** 2026-04-29.
**Author:** Mahmood Seoud (with Julian, advisor).
**Companion to:** `experiments/README.md` (the harness this plan drives).

---

## 1. What we're trying to prove

> *DTP + cross-pass resume + SHA256 verification delivers a bit-exact binary across an unreliable, intermittent UHF link, where naive approaches fail.*

The dev-tier harness (`experiments/README.md`) already provides evidence on a fake KISS link (`impair.py`). This document describes the **flatsat-tier evidence** — same experiments run against real hardware so the thesis story has three consistent tiers of data:

```
   dev container          flatsat                     live satellite
   (fake everything)      (real hw on a bench)        (the real thing)
   ───────────────►       ──────────────►             ──────────────►
   logic correctness      hw-realistic timing         space-realistic conditions
   resume / state         real radio framing           Doppler, pass dynamics
   correctness            real fade behavior           atmospheric fades
```

Each tier produces a CSV with the **same schema** (`experiments/lib/metrics.sh`). The thesis chapter is the same plot drawn three times, datasets stacked, "dev predicted X, flatsat showed X ± Y, satellite confirmed within stat error."

---

## 2. Setup — what's on the bench

The flatsat is **radio-less**: real OBC, real CAN bus, real flight software, but no UHF modem. The ground laptop and spacecraft side connect through whatever wired CSP transport the lab's flatsat is wired with (CAN, ZMQ, UDP, eth — TBD with the lab). RF only enters the picture for the live-satellite acceptance test (F12), which uses the actual ground-station + flight radio.

```
    ┌──────────────────────────────┐                          ┌──────────────────────────────┐
    │   GROUND-SIDE LAPTOP         │                          │   FLATSAT (spacecraft side)  │
    │                              │                          │                              │
    │   csh + harness              │                          │   OBC  (DISCO-2)             │
    │     │                        │                          │   running satdeploy-agent    │
    │     │  wired CSP transport   │                          │     ▲                        │
    │     │  (CAN / ZMQ / UDP /    │                          │     │                        │
    │     ▼  eth — see below)      │                          │     │                        │
    │   ─────────────────────  wire/cable  ─────────────────────►   │                        │
    │                              │                          │     │                        │
    │   loss-pattern file ─────────┼──►  agent loss_filter ──►│     │  CAN bus to other      │
    │     (LOSS_PATTERN_FILE        │     drops CSP packets   │     │  subsystems            │
    │      env var)                │     per recorded trace   │                              │
    │                              │                          │                              │
    │   Prometheus exporter        │◄── current/voltage ──────┼── PDU / inline meter         │
    │     │                        │                          │                              │
    │     ▼                        │   csh `power on/off` ───►│   Space Inventor PDU-P4      │
    │   Grafana dashboard          │   over CSP               │   powering the OBC           │
    └──────────────────────────────┘                          └──────────────────────────────┘
```

The loss happens in software inside the agent — the `loss_filter` module reads a recorded pass-log pattern and drops CSP packets in its receive path. There is no RF, no SDR, no attenuator. This is the trace-driven approach (§3) and it works against any wired CSP transport the flatsat happens to use.

### What we have

| Item | Use |
|---|---|
| Real OBC (DISCO-2) running flight satdeploy-agent | The thing we deploy to |
| Real CAN bus between subsystems on the spacecraft side | Internal-bus deploy paths (`--link can`) |
| Wired CSP transport between ground laptop and OBC | Carries CSP traffic to/from the agent. Specific transport TBD with the lab |
| **Space Inventor PDU-P4** (csh `power on/off`) | Remote power-cycle of the OBC for reboot scenarios |
| **Prometheus + Grafana already in place** | Watts-on-OBC telemetry, correlated with deploy events |

### What we don't have (and don't need)

| Item | Why not |
|---|---|
| ~~UHF radio modem on flatsat~~ | Not present; not planned |
| ~~SDR / RF attenuator / coupler~~ | Trace-driven loss injection (§3) replaces RF noise injection — same evaluation outcome |
| ~~Antenna / RF cabling~~ | Same |

For the from-scratch SDR primer (in case a future flatsat revision adds a radio): see `experiments/sdr-primer.md`.

### What we still need to nail down

- [ ] **Pass-log access to real satellite operations** — what telemetry do we currently capture during real DISCO passes? See `experiments/lab-data-questions.md` for the specific questions. **This is the gating item — F3 / F4 / F5 cannot start without it.**
- [ ] **What wired CSP transport does the flatsat use?** CAN over `can0`? ZMQ over a network cable? UDP? Goes into `init/flatsat.csh` and determines the `--link` flag. Confirm with the lab.
- [ ] **PDU-P4 channel for the OBC** — which channel the OBC is wired to on the lab's PDU-P4. Used for `node add -p pdu1-a -c <CHANNEL> obc`.
- [ ] **PDU CSP hostname** — the PDU's CSP hostname/address. Used for the `-p` arg above.
- [ ] **CSP-layer loss-filter hook** — small module in the agent (`loss_filter.[ch]`) that reads pattern files and conditionally drops packets. Sketch and integration guide in `satdeploy-agent/include/loss_filter.h` + `loss_filter.integration.md`.
- [ ] **Pattern-file format + log parser** — pattern files documented in `experiments/loss-pattern-format.md`. Parser at `experiments/lib/parse_pass_log.py` (stub today, fill in `_parse_real_log` once we know the input format).
- [ ] **Prometheus exporter for satdeploy events** — emit a metric every time a push starts/completes/resumes so Grafana can overlay deploy events on the watts trace.

---

## 3. Loss injection — trace-driven CSP-layer drop (primary approach)

### Why this approach

**DTP only ever sees one thing: "did CSP packet sequence N arrive at me, yes or no."** That's the abstraction layer where DTP's recovery logic operates. Every layer below — KISS, AX.25, FEC, GMSK, RF — is a black box from DTP's perspective. The radio modem either delivers a clean CSP packet or it doesn't.

So loss should be injected at the CSP layer, not the RF layer. We're testing the protocol's response to packet loss; we are not testing the radio modem (which is a vendor component we accept as-is).

The loss **pattern** comes from real satellite operations. We capture pass logs during real DISCO passes, derive when packets actually got dropped, and replay that exact pattern through software on the bench. This is **trace-driven simulation** — a standard technique in network research, used heavily in the TCP literature. The defense argument writes itself:

> *"We don't claim our loss model is realistic — we claim it **is** the loss observed during pass X on date Y. The protocol succeeded against that exact pattern."*

### How it works end-to-end

```
   real satellite pass logs   →   parser       →   pattern file        →   agent loss filter
   (timestamps, lock events,      (Python in    (deterministic                 (compiled into
    CSP packet receipts)           the harness)  drop schedule)                  the C agent)
                                                                                       │
                                                                                       ▼
                                                                              drops CSP packets
                                                                                in the agent's
                                                                              receive path during
                                                                                 a satdeploy push
```

Three components:

1. **Pattern file format** — a simple line-oriented format describing when the link is up/down. Documented at `experiments/loss-pattern-format.md`.
2. **Log parser** — `experiments/lib/parse_pass_log.py`, converts whatever telemetry the lab captures into the pattern format.
3. **Loss filter in the agent** — `satdeploy-agent/{include,src}/loss_filter.{h,c}`. Loads a pattern file at startup (gated by `LOSS_PATTERN_FILE` env var) and decides whether to drop each incoming CSP packet. **Compile-time gated by `-DSATDEPLOY_TEST_LOSS_FILTER`** so the flight build can never accidentally include it.

### What the harness experience looks like

```bash
# Replay a real pass — bit-exact reproduction of conditions on 2026-04-15
LOSS_PATTERN_FILE=experiments/patterns/pass_2026-04-15_dtu1.pattern \
    ./experiments/harness.sh \
    --experiment f3 --link kiss \
    --size 1048576 --seed 1 \
    --csv results/flatsat/f3_loss_curve.csv \
    --label pass-2026-04-15

# Or use a synthetic baseline (sanity check the filter itself)
LOSS_PATTERN_FILE=experiments/patterns/synthetic_5pct_bernoulli.pattern \
    ./experiments/harness.sh ...
```

The harness exports `LOSS_PATTERN_FILE`; the agent reads it on boot. Same harness flags everywhere else.

### Defining "loss" — a definitional decision we have to make

A real pass log contains evidence at multiple layers:

- **Modem CRC failures** — the RF layer detected a corrupt frame and discarded it
- **Modem lock/unlock events** — the carrier dropped, no frames at all during the gap
- **CSP frame timeouts** — packet was sent but no application-level response within RTT
- **Application-level no-shows** — a libcsp `recv` call returned NULL

These aren't the same event. CRC failures happen often without affecting CSP because higher layers retry. Lock loss is binary — link totally down. CSP timeouts include all of the above plus protocol-level edge cases.

**For the thesis, the right definition is "CSP packet did not arrive at the application within timeout."** Reasoning: that's what DTP actually responds to. CRC failures that the modem recovers from don't matter for our story.

This means the parser converts pass logs into pattern files using "CSP packet didn't arrive" as the unit-of-loss event. If the lab logs are at a lower layer (e.g. only modem CRC counts), the parser interpolates with documented assumptions; we cite this in the thesis methodology.

### Pattern file format (sketch — full spec in `loss-pattern-format.md`)

```
# pass_2026-04-15_dtu1.pattern
# Recorded from DISCO pass 2026-04-15T14:32:00Z, 8m12s duration
# Definition of loss: CSP packet not delivered within 1s of expected arrival
#
# Format: <t_offset_seconds> <action>
# Actions: down (link goes down) | up (link comes back up)
#
# Default state at t=0 is "up". Each "down" event marks the start of a
# gap; the next "up" closes it. The agent drops every CSP packet whose
# arrival timestamp falls inside a [down, up) interval.

12.500 down
13.200 up
45.100 down
45.150 up
217.800 down
220.450 up
# ...
```

Variants the format supports:
- `prob 0.05` — set drop probability (Bernoulli) to 5% from this point
- `interval` — for stochastic patterns derived from real data parameters

### Parametric scaling of recorded patterns

A pattern file is one trace from one pass. To produce a loss *curve*, we scale recorded patterns:

- **1.0×** — replay exactly as recorded (the truth case)
- **0.5×** — half as many drops (use this for "good pass" simulation)
- **2.0×** — twice as many drops (worst-case stress)
- **time-shift** — slide the pattern by N seconds (resilience to where the gaps fall)

Scaling and shift are CLI flags on the parser, producing a derived pattern file. The thesis chapter shows the protocol's response to actual passes (1.0×) plus the scaled variants (the curve).

---

## 3a. SDR — not part of the plan

The current flatsat **does not carry a radio** and there's no plan to add one. SDR-based RF noise injection (which would normally validate trace-driven loss models against real RF) isn't part of the thesis evaluation path.

This works out cleanly: trace-driven CSP-layer loss (§3) tests the application protocol's response to packet loss directly, without needing the radio layer at all. The radio layer is below the abstraction the protocol cares about — the live satellite (F12) is where real RF actually gets exercised, as an acceptance test rather than a controlled experiment.

If a future flatsat revision ever adds a radio, or if you want to validate the trace-driven model against real RF on a separate test bench, see `experiments/sdr-primer.md` for a from-scratch SDR primer (parked there for reference, not part of the active plan).

---

## 4. The PDU — power-cycling the OBC

The PDU lets us script reboot scenarios that on a real satellite would be triggered by watchdog timers, ESD events, or operator commands.

### How we talk to it

The flatsat's PDU is a **Space Inventor PDU-P4** — same vendor as libcsp/csh/libparam. It's its own CSP node that exposes channels (one per powered subsystem) and accepts `power on` / `power off` commands. **No HTTP, no SNMP, no custom wrapper** — it's controlled the same way as everything else on the bus, through `csh`.

The plumbing lives in csh's "SI APM" (`libcsh_si.so`). Once that APM is loaded and the PDU is registered, you get:

```csh
# One-time setup: register the PDU and tell csh which channel powers the OBC
host>> apm load
host>> node add -p pdu1-a -c 2 obc

# Now you can power-cycle by name
host>> power off obc
host>> sleep 1000
host>> power on obc
host>> ping obc
   | Ping node 6 size 1 timeout 1000: Reply in 1 [ms]
```

In that example: `pdu1-a` is the PDU's CSP hostname, `-c 2` is the channel that powers the OBC, and `obc` is the friendly name we register. After `node add`, every power-on/off references the friendly name — channel routing happens automatically.

`ping obc` is the **"OBC is back up" signal** for the harness. CSP ping returns a reply once the OBC has booted far enough to respond on its CSP node. That's our cue to issue the next `satdeploy push`.

### Two roles in the test plan

#### Role A — explicit reboot mid-transfer (F6)

```
1. start satdeploy push of a 5 MB binary
2. poll target file size; wait until ~50% transferred
3. csh> power off obc                         # mid-transfer kill
4. sleep 15
5. csh> power on obc
6. csh> until ping -t 60 obc; do sleep 1; done   # block until alive
7. issue satdeploy push for same app
8. verify SHA-256 of received file matches source
```

The expected behaviour: the **sidecar bitmap** (`/var/lib/satdeploy/state/<app>.dtpstate`) survives the power-cut because it's written via atomic rename (per the design). On the next push, the agent reads the sidecar and only requests still-missing seqs. This is **the cross-pass resume contribution of the thesis, demonstrated against a real OBC reboot**.

#### Role B — extreme-case row in F5 (pass-window stress test)

F5 simulates satellites passing in/out of view. Primary method is the **loss filter pattern** (`up`/`down` events drop CSP packets at the agent layer — see §3). The OBC stays powered, the link goes down in software. Realistic — actual satellites don't power-cycle their OBC every pass.

For one extreme-case row in F5, we additionally use the **PDU to cycle the OBC** between simulated passes. Brutal but reveals whether the agent + sidecar survive when "link down" coincides with a hard reboot. Tagged in CSV as `notes=pass_via_pdu_cycle`.

### PDU driver — `experiments/lib/pdu.sh`

Since PDU control is csh commands, the harness "driver" is just a thin wrapper that runs csh in batch mode (same `script -qfec ... csh -i init.csh "<command>"` trick the existing `csh_driver.sh` uses). No custom networking code:

```bash
# experiments/lib/pdu.sh — sketch
PDU_INIT="${PDU_INIT:-/satdeploy/init/flatsat.csh}"
PDU_OBC_NAME="${PDU_OBC_NAME:-obc}"
PDU_PING_TIMEOUT_MS="${PDU_PING_TIMEOUT_MS:-60000}"

_csh_one_shot() {
    local cmd="$1"
    script -qfec \
        "$CSH_BIN -i $PDU_INIT \"$cmd\"" \
        /dev/null </dev/null
}

pdu_off() { _csh_one_shot "power off $PDU_OBC_NAME"; }
pdu_on()  { _csh_one_shot "power on  $PDU_OBC_NAME"; }

# Block until the OBC responds to CSP ping. Returns 0 on alive, non-zero on timeout.
obc_wait_ready() {
    local deadline=$(( $(date +%s) + 60 ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if _csh_one_shot "ping -t 1000 $PDU_OBC_NAME" 2>&1 | grep -q "Reply"; then
            return 0
        fi
        sleep 1
    done
    return 124
}

pdu_cycle() {
    local off_seconds="${1:-10}"
    pdu_off
    sleep "$off_seconds"
    pdu_on
    obc_wait_ready
}
```

The companion `init/flatsat.csh` registers the CSP transport, loads the SI APM, and registers the OBC + PDU nodes:

```csh
# init/flatsat.csh — for the live ground station
csp init
csp add can -c can0 -d 19      # or whatever transport reaches the spacecraft bus
apm load                        # picks up libcsh_si.so + libcsh_satdeploy_apm.so
# Register PDU + OBC. Substitute pdu1-a / channel / addr for your flatsat.
node add -p pdu1-a -c 2 obc
```

Channel 2 is a placeholder — match it to whichever channel the OBC is actually wired to on your PDU-P4 (4 channels per unit). Confirm with the lab when wiring up.

### Why this is nice

The same shell that runs `satdeploy push` also runs `power off obc`. That means the harness can interleave deploy and power commands in a single csh batch session if useful, e.g.:

```csh
satdeploy push controller -n 5425   # push
power off obc                       # cut mid-transfer
sleep 10
power on obc
satdeploy push controller -n 5425   # resume after reboot
```

Concretely, this means **F6 can be implemented as one csh batch script** rather than orchestrated from the bash harness. We'll likely do both — bash-orchestrated for primary timing-sensitive trials, csh-batch for repeatable scripted scenarios.

---

## 5. Power telemetry via Prometheus + Grafana

### What this gives us beyond raw success/failure

A satdeploy push goes through phases: idle → DTP transfer (CPU + disk active) → SHA verification (CPU spike) → service restart (process churn) → idle. Each phase has a different power signature. By correlating the OBC's instantaneous power draw with deploy events, we can:

- **Spot hangs** — agent that's "running" but actually wedged shows as flat low-power CPU. A real DTP transfer should show ~constant elevated draw.
- **Detect reboots cleanly** — power spike on cold boot is unmistakable. Useful for proving "the OBC actually rebooted in F6" rather than just "we sent a kill signal."
- **Estimate energy cost per deploy** — integrate watts × seconds. Mission planners care: a 10 MB push that costs 50 J of OBC energy is meaningful info for power budget.
- **Catch retry storms** — a buggy DTP retry loop that re-sends 10× more data than needed will show as elevated power for longer than expected. A working one shouldn't.

### What to record

| Metric | Source | Sample rate |
|---|---|---|
| `obc_power_watts` | PDU's built-in current/voltage telemetry (or inline INA219 / Joulescope) | 10 Hz |
| `obc_power_5v_amps` | same | 10 Hz |
| `satdeploy_push_started{app=...,size_bytes=...}` | Prometheus exporter inside the harness | Event |
| `satdeploy_push_completed{outcome=...}` | same | Event |
| `satdeploy_pass_progress_bytes` | agent-side gauge from session_state | 1 Hz |
| `loss_filter_link_state{state=up/down}` | agent loss_filter (transitions when pattern fires) | Event |
| `loss_filter_packets_dropped` | same | 1 Hz counter |
| `pdu_state{powered=true/false}` | PDU script | Event |

### Grafana dashboard (proposed)

One panel per test, showing:

```
            obc_power_watts (line, left axis)
   ┌────────────────────────────────────────────────────────────────────────┐
   │       ╱╲              ╱╲                              ╱╲              │
   │      ╱  ╲___          ╱  ╲___                       ╱  ╲___           │
   │     ╱       ╲________╱       ╲_____________________╱       ╲_______   │
 ──┼──────────────────────────────────────────────────────────────────────  │ ← deploy events
   │  PUSH_START         RESUME              PUSH_COMPLETE                  │
   │                                                                        │
   │  ░░░░░ pattern: down ░░░░░       ░░░░░ pattern: down ░░░░░             │ ← loss filter dropping
   └────────────────────────────────────────────────────────────────────────┘
        t=0         t=120       t=240        t=360      t=480 (sec)
```

Annotations are pulled via Grafana's Prometheus query for the event metrics. Power line is the headline graph the thesis chapter shows.

### Wiring the harness to Prometheus

Add to `experiments/lib/metrics.sh`:

```bash
prom_emit() {
    # Push a single-shot metric to the Pushgateway
    local metric="$1" labels="$2" value="$3"
    if [ -n "${PROM_PUSHGATEWAY:-}" ]; then
        echo "$metric{$labels} $value" \
            | curl -s --data-binary @- "$PROM_PUSHGATEWAY/metrics/job/satdeploy"
    fi
}
```

Called from `harness.sh` at trial boundaries (`push_started`, `push_completed`). When `PROM_PUSHGATEWAY` is unset, the function is a no-op — keeps the dev-tier harness identical.

---

## 6. The test catalog (F1–F12)

Test IDs match the dev-tier IDs (E1, E2, ...) where applicable, prefixed with `F` for flatsat. CSVs use `experiment=fN` and `link_kind` per test. All tests run **before** any live-satellite work — flatsat must be solid first.

### F1 — Real-link smoke
**Goal:** baseline plumbing on real hardware. Confirms the harness, transports, and SHA verification work end-to-end on the real OBC and real CAN bus.

| Subtest | Link | Sizes | N | Loss filter | PDU | Acceptance |
|---|---|---|---|---|---|---|
| F1.a | `can` over the real CAN bus to the OBC | 1 KB, 100 KB, 5 MB | 20 | off | static | 20/20 success, SHA matches |
| F1.b | wired CSP transport (whatever the lab uses) between ground laptop and OBC | 1 KB, 100 KB, 5 MB | 20 | off | static | 20/20 success, SHA matches |

**Run command:**
```bash
# Subtest will look like this — actual --link value depends on the
# flatsat's ground-to-OBC wiring (TBD with the lab).
LINK=can N=20 SIZES="1024 102400 5242880" \
    ./experiments/runs/e1_baseline.sh
```

The two subtests cover (a) the spacecraft-internal CAN bus path, where deploys move between OBC and other on-board subsystems, and (b) the ground-to-OBC path that mirrors the operational deploy direction. Both are exercised through the same harness — only the `--link` value differs.

### F2 — Throughput floor on flatsat hardware
**Goal:** measure how fast a deploy actually runs against the real OBC + real flight software stack. Establishes the dev-vs-flatsat overhead delta.

| Subtest | Description | Acceptance |
|---|---|---|
| F2.a | Push 100 KB over clean wired link, N=10. Record wall-clock. | Median throughput within 20% of dev-tier prediction |
| F2.b | Push 1 MB over clean wired link, N=10. Record wall-clock. | Same |

**Output:** an "effective flatsat goodput" number (KB/s). The wired transport bandwidth is much higher than UHF, so this number reflects the protocol/CPU/disk overhead — not the link bandwidth. **For UHF goodput**, see F12 (live satellite); only the real RF link gives that number.

### F3 — Loss curve via trace-driven replay (the headline experiment)
**Goal:** demonstrate DTP recovery against actual loss patterns observed in real DISCO operations. **This is the chart that defines the thesis's reliability claim.**

Method:
1. Start from a **library of pattern files** derived from real pass logs:
   - `pattern_clean_pass.pattern` — a pass with near-zero loss
   - `pattern_marginal_pass.pattern` — moderate loss
   - `pattern_bad_pass.pattern` — heavy fades
2. For each pattern, additionally generate **scaled variants** using `experiments/lib/parse_pass_log.py --scale <factor>`:
   - 0.5× (half the recorded drops)
   - 1.0× (truth case — exact replay)
   - 1.5×, 2.0×, 3.0× (worse than what we observed)
3. Run N=20 pushes of 100 KB per pattern.
4. Record success rate, retry rounds, wall-clock time, total bytes dropped.

**Acceptance shape:**

| Pattern intensity | Expected success rate | Notes |
|---|---|---|
| Clean pass × 1.0 | 100% | Baseline; any failure = real bug |
| Marginal × 1.0 | ≥95% | DTP retry handles realistic flight conditions |
| Bad × 1.0 | ≥80% | The protocol earns its keep |
| Bad × 2.0 | partial | Past the operational envelope; document where it gives up |
| Bad × 3.0 | mostly fails | Defines breaking point — discussion point |

**Plot:** success rate (y) vs pattern intensity (x), with bars showing the categorical patterns and a continuous curve for scaled variants of one base pattern. Side-by-side with the dev-tier curve from running the **same patterns** through the dev container — the two curves should match (proves the loss filter is the only thing we changed between tiers).

### F3.b — Naive baseline (the "satdeploy beats raw upload" comparison)
**Goal:** show what would happen WITHOUT DTP's retry / cross-pass resume. Without this, the F3 result has no story to tell.

Method: same patterns, same harness, but the `--approach` flag selects a path that bypasses DTP — e.g., a single-shot CSP upload that retries the whole transfer if any packet drops. Run N=20 per pattern.

**Acceptance:** naive approach collapses where DTP holds. The plot in F3 has two lines:
```
   100% ┤───────────────────────╮
        │   DTP ─────────────────╲___
        │                            ╲___
        │                                ╲___
        │   naive ──╲                        ╲___
     0% ┤            ╲___________________________
        ┴─────────────────────────────────────────►
        clean      marginal     bad         bad×2  pattern intensity
```

**This is the headline thesis chart.** Without F3.b you don't have a comparison; with it you have proof.

### F4 — Real-fade replay
**Goal:** prove DTP handles fades that actually occurred during real passes.

Method:
1. From the pattern library, pick passes with known fade events (lock-loss intervals ≥ 1s).
2. For each, run N=10 pushes of 1 MB each. Compare success rate, retry rounds, wall-clock to the same pattern run through the dev tier.
3. Bonus: tune the dev-tier `impair.py` Gilbert-Elliott parameters (p, r, loss_bad) to match the empirical fade distribution. Cite the calibrated parameters in the thesis as "the GE parameters that reproduce DISCO UHF fade behavior in software."

**Acceptance:**
- Trace replay completes successfully against the real OBC.
- GE-calibrated dev tier reproduces flatsat results within 1 stddev — the dev model is now credible for predictive work.

### F5 — Pass-window simulation (cross-pass resume on real hardware)
**Goal:** prove cross-pass resume works against a real OBC running flight software, with realistic (compressed) pass windows.

Setup:
- Pass length: **8 minutes** (matches our actual ground-station pass duration).
- Inter-pass dead time: **30 seconds** (compressed from real-world ~6 hours; we don't have time to wait that long, and the protocol doesn't care about absolute time).
- Push file: **5 MB binary**. At dev-tier-predicted UHF goodput, this needs ~3 passes — the right number to exercise resume across two cuts.

Procedure (trace-driven primary path):
```
1. Generate pattern: 8-minute "up" intervals separated by 30-second "down" gaps,
   repeating until pattern length > 25 minutes. Optionally interleave with
   a recorded fade pattern from a real pass.
   $ ./experiments/lib/parse_pass_log.py --build-pass-window-pattern \
         --pass-len-s 480 --gap-s 30 --total-len-s 1500 \
         > experiments/patterns/passwin_8m_30s.pattern

2. Run the harness with the loss filter pointed at this pattern:
   $ LOSS_PATTERN_FILE=experiments/patterns/passwin_8m_30s.pattern \
       ./experiments/harness.sh --experiment f5 --link kiss \
         --size 5242880 --max-passes 6 --timeout-s 1800 ...
```

The agent's loss filter handles the link-up/link-down cycle in software. The bash harness does no orchestration of the link — the pattern *is* the orchestration.

Optional extreme-case comparison row: PDU-cycle the OBC during each "down" interval (forces full reboot between passes). Tests resume-after-cold-boot, not just resume-after-link-loss. Tagged `notes=pass_via_pdu_cycle`.

**Per-trial recording (CSV):**
- passes_used (1, 2, 3, ...)
- bytes_recovered_per_pass (from agent log)
- bytes_re_sent_per_pass (resume overhead)
- sidecar size at start of each pass
- final outcome (success / passes_exhausted)

**Acceptance:**
- File completes in ≤4 passes (some headroom over the theoretical 3).
- Resume overhead < 5% (bytes re-sent / bytes already on target).
- Sidecar grows monotonically until completion, then is removed.
- SHA matches source on success.

**This is the headline contribution experiment.** The thesis claim "cross-pass resume works on real hardware" needs this dataset to defend.

### F6 — OBC reboot mid-transfer
**Goal:** prove resume survives a hard OBC power cycle (not just a process kill).

Procedure:
```
1. start satdeploy push of 1 MB
2. wait until 50% transferred (poll sidecar size or target file size)
3. PDU off
4. sleep 15 seconds
5. PDU on
6. wait for agent process to come up (poll CSP status command)
7. re-issue satdeploy push for same app (same SHA)
8. verify SHA matches source
```

**Acceptance:**
- Resume succeeds; SHA matches.
- Sidecar header (full SHA + nof_packets) intact post-reboot.
- Pre-existing target file fragments not corrupted by the cut.
- Power telemetry shows clean reboot signature (visible in Grafana — the "F6 evidence chart").

### F7 — Disk-full / disk-error
**Goal:** prove the agent fails gracefully when storage runs out, doesn't poison subsequent deploys.

Procedure:
1. Pre-fill `/var/lib/satdeploy/` to within 100 KB free (`fallocate -l ... filler.bin`).
2. Push a 1 MB file. Should fail somewhere mid-transfer.
3. Verify: agent process still alive, no half-written file in deploy target, recognizable error in agent log.
4. Free space. Re-push the same file. Should now succeed (sidecar from prior failed attempt may or may not be reusable — record either way).

**Acceptance:** no crash; recoverable; no corruption of unrelated apps.

### F8 — CAN bus stress
**Goal:** confirm `--link can` survives realistic background bus load.

Procedure:
1. Start `cangen vcan0 -g 10` from another node (10ms inter-frame gap = ~100 frames/sec background load).
2. Run F1.c (3 sizes × 20 trials).
3. Repeat at 1ms gap (1000 frames/sec, ~50% bus utilization at 1 Mbps).
4. Repeat at 0.1ms gap (~80% utilization).

**Acceptance:**
- 100% success at ≤50% utilization.
- ≥90% success at 80% utilization.
- Document the rate at which CSP frame loss starts mattering — useful for mission ops planning.

### F9 — Concurrent operations
**Goal:** verify metadata commands during active push don't corrupt the transfer.

Procedure:
1. Start a 5 MB push.
2. From a separate csh session, run `satdeploy status` every 5 seconds.
3. From a third csh session, run `satdeploy logs telemetry` every 10 seconds.
4. Wait for original push to complete.

**Acceptance:**
- Original push completes; SHA matches.
- All concurrent commands return valid responses (don't hang or error).

### F10 — Deploy / verify / rollback / re-verify
**Goal:** end-to-end version-management workflow.

Procedure:
1. Push v1 of `controller`. Verify SHA = sha_v1.
2. Push v2 (different content). Verify SHA = sha_v2.
3. Rollback to v1. Verify SHA = sha_v1.
4. List versions; expect to see both in the backup directory.
5. Roll forward to v2. Verify SHA = sha_v2.

**Acceptance:** every verify-step matches its expected SHA; backup directory contains both versions.

### F11 — Multi-app push (`push -a`)
**Goal:** dependency-aware deploy of the full app set in one operation.

Procedure:
1. Modify config so `controller` depends_on `csp_server`, `libparam` is restart-after for `controller`.
2. Run `satdeploy push -a`.
3. Verify all apps' SHAs match source.
4. Verify systemd services restarted in correct dependency order (read journalctl).

**Acceptance:** all apps installed correctly, no service stuck in failed state, restart order matches dependency graph.

### F12 — Live-satellite acceptance
**Goal:** the final validation. Run F1, F3, and F5 against the real satellite during real passes.

Procedure: same scripts, point ground station at the live satellite instead of flatsat.
Schedule: minimum of **3 passes** worth of data per subtest (so ~24 minutes uplink time at 8 min/pass).

**Acceptance:** results agree with flatsat data within 1 stddev. If they don't, the gap is the **thesis discussion section** — what real space conditions add that flatsat couldn't capture.

---

## 7. Data collection plan

### CSV organization

All flatsat CSVs land in `experiments/results/flatsat/` with one file per test:

```
experiments/results/flatsat/
├── f1_smoke.csv
├── f2_throughput.csv
├── f3_loss_curve.csv
├── f4_fade.csv
├── f5_pass_window.csv
├── f6_reboot.csv
├── ...
└── f12_live_satellite.csv
```

### Each CSV has the standard schema (`lib/metrics.sh`) plus these flatsat-specific notes columns

Use the existing `notes` column with structured key=value pairs:

```
notes="pattern=pass_2026-04-15_dtu1.pattern;scale=1.0;measured_drops=158"
notes="pass_index=2/3;bytes_recovered=2097152;sidecar_size=512"
notes="reboot_at_byte=524288;pdu_off_s=10;reboot_clean=true"
```

A trivial Python post-processor expands `notes` into separate columns at analysis time.

### Per-trial artifacts (besides CSV)

For each trial, keep in `/tmp/satdeploy-experiments/<label>/`:
- `pass-N.agent.log` — agent stdout/stderr per pass
- `pass-N.csh.log` — ground-side push log
- `impair.log` — dev-tier byte-level impairment stats (KISS path only)
- `loss_filter.log` — agent's per-trial loss-filter stats (events fired, packets dropped)
- **NEW**: `pdu.log` — PDU on/off events with timestamps
- **NEW**: `power.csv` — 10 Hz watts samples for the trial duration (pulled from Prometheus at end of trial)
- `pattern.copy` — the exact pattern file used (copied verbatim into the trial dir for reproducibility)

### Cross-tier comparison

The thesis chapter pulls all three tiers into one dataframe:

```python
import pandas as pd
dev = pd.read_csv("experiments/results/e2_loss_curve.csv");        dev["tier"]="dev"
fls = pd.read_csv("experiments/results/flatsat/f3_loss_curve.csv"); fls["tier"]="flatsat"
sat = pd.read_csv("experiments/results/flatsat/f12_live.csv");      sat["tier"]="satellite"
all_data = pd.concat([dev, fls, sat])
# Plot: success rate vs frame loss %, faceted by tier.
```

If the three lines in that plot match, the thesis is defensible. If they diverge, the discussion section explains why.

---

## 8. Schedule (rough)

| Week | Activity |
|---|---|
| W0 (now) | Get pass-log access from real DISCO ops (the gating dependency). Build `loss_filter.[ch]` in the agent. Define pattern format + parser stub. Build `init/flatsat.csh` + `lib/pdu.sh` (PDU-blocked on wires). |
| W1 | Parse first batch of real pass logs into pattern files. Build pattern library: clean / marginal / bad / scaled variants. Smoke test the loss filter on dev tier (replay a synthetic pattern, confirm DTP sees the drops). |
| W2 | F1 (smoke). F2 (throughput). Establish clean-link baseline on flatsat. |
| W3 | **F3 (loss curve via trace replay) — the headline experiment.** F3.b naive baseline. F4 (real-fade replay + GE calibration). |
| W4 | F5 (pass window via trace pattern). The cross-pass resume experiment on real hardware. |
| W5 | F6 (reboot, blocked on PDU wires). F7 (disk full). F8 (CAN stress). |
| W6 | F9 (concurrent). F10 (rollback). F11 (multi-app). End-to-end ops. |
| W7 | F12 (live satellite). Same scripts, real spacecraft. |
| W8+ | Analysis, plots, thesis writeup. |

W0 is the pacing item — the trace-driven path needs real pass logs. Everything else is engineering work that proceeds in parallel. If the lab can hand over an existing log dump quickly, W1 starts immediately; if not, W0 expands until the data flows.

---

## 9. Acceptance criteria summary (one table for the thesis defense)

| Test | Pass means | Failure means |
|---|---|---|
| F1 | 60/60 success across all transports/sizes | Plumbing bug or hw integration issue — block other tests until fixed |
| F2 | Real throughput within 20% of dev-tier sim | Document the gap; not a thesis-breaker |
| F3 | DTP holds ≥95% success on `marginal × 1.0` and ≥80% on `bad × 1.0` real-pass replays; degrades gracefully on 2× / 3× scaled variants | Headline result chart |
| F3.b | Naive baseline (single-shot CSP upload) collapses where DTP holds — gap is the thesis money chart | Without this, F3 has no story |
| F4 | Dev-tier GE params predict flatsat fade behavior within 1 stddev | Calibration done; dev model credible for predictive work |
| F5 | 5 MB delivered in ≤4 passes, <5% resume overhead | The cross-pass resume contribution proven on real hw |
| F6 | Resume succeeds across PDU power cycle | Sidecar atomic-rename design validated end-to-end |
| F7 | Graceful failure, recoverable | Robustness against operational reality |
| F8 | ≥90% success at 80% CAN bus utilization | CAN viability for parallel deploys |
| F9 | Concurrent metadata cmds don't corrupt transfer | Operational concurrency safe |
| F10 | All SHAs match across deploy/rollback/re-deploy cycle | Version management integrity |
| F11 | All apps deployed in correct order | Dependency graph correctness |
| F12 | Live-satellite results match flatsat within 1 stddev | "It works in space" |

---

## 10. Open questions / parking lot

- **Pass-log access — the gating item.** What real telemetry do we currently capture during DISCO passes? Format, schema, retention? Full question list at `experiments/lab-data-questions.md`.
- **Naive baseline implementation (F3.b).** Simplest option: build the agent with DTP retry rounds capped at 1 (`MAX_RETRY_ROUNDS=1` build flag in `dtp_client.c`). Gives a "no retry" comparison without writing new transfer code.
- **Definition of "loss" in pass logs.** Multiple candidates (CRC failure, lock loss, CSP timeout). Plan picks "CSP packet not delivered to application within timeout" — see §3 "Defining loss." Verify this aligns with what the lab actually logs.
- **Pattern diversity.** Need passes spanning weather/elevation/season for a defensible library. Discuss with operations team early — what's archived and easily extractable?
- **Power telemetry sample rate.** 10 Hz catches push start/end / reboot transitions cleanly; SHA-verification spikes are ~100ms and may need 100 Hz on key trials. Decide per-experiment.
- **Live-satellite pass time budget (F12).** Needs 3+ passes of test traffic. Coordinate with mission ops early — non-mission traffic during a real pass costs operations time.
- **`cangen` on the flatsat laptop.** The CAN-stress tool is in can-utils — already in the dev container, but the flatsat ground-station laptop needs it too. `apt install can-utils`.

---

## 11. References

- `experiments/README.md` — the harness this plan drives
- `experiments/lib/impair.py` — dev-tier KISS impairment model (calibration target for F4)
- `CLAUDE.md` § "Cross-pass DTP resume" — the design being validated
- `satdeploy-agent/include/session_state.h` — sidecar format under test in F6
- KISS protocol: <https://www.ax25.net/kiss.aspx>
- Gilbert-Elliott model: Gilbert (1960), Elliott (1963). Used in F4 calibration.
