#!/usr/bin/env python3
"""
visualize_smoke.py — Comparison figure for naive vs smart F3.b panel.

The (loss=0) cells are aggregates over n=10 trials per (build, size) at
1MB from experiments/results/tail_race.csv (sweep_tail_race.sh, n=30 total
per build). The (loss=5%) cells are still single smoke trials — that
column needs its own n=10+ sweep before making a quantitative claim.
"""
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# Each row: (build, loss_pct, packets_dropped_by_filter, total_packets_seen,
#           retry_rounds_used, success, comment)
#
# All rows are aggregates over measured trials (mean values shown):
#   (build, 0): tail_race.csv 1MB cell, n=10
#   (build, 5): loss_rates.csv 5% cell,  n=5
DATA = [
    ("smart", 0,  0,    1033, 1, True,  "n=10: 10/10 ok, mean 1.0 round"),
    ("smart", 5, 55,    1100, 7, True,  "n=5:  5/5 ok, mean 6.8 rounds"),
    ("naive", 0,  0,    1031, 0, False, "n=10: 10/10 fail, gap=2 at tail"),
    ("naive", 5, 53,     980, 0, False, "n=5:  0/5 success, no retry budget"),
]

# Colors: smart=teal, naive=salmon
SMART = "#0d9488"
NAIVE = "#dc2626"
GRID  = "#e5e7eb"

fig, axes = plt.subplots(2, 2, figsize=(12, 8))
fig.suptitle("satdeploy smoke-test results — smart DTP retry vs naive baseline",
             fontsize=14, fontweight="bold", y=0.995)

# ─────────────────────────────────────────────────────────────────────
# Panel 1: success/fail outcome
# ─────────────────────────────────────────────────────────────────────
ax = axes[0][0]
labels = ["smart\nclean", "smart\n5% loss", "naive\nclean", "naive\n5% loss"]
outcomes = [1 if d[5] else 0 for d in DATA]
colors = [SMART if d[0] == "smart" else NAIVE for d in DATA]
bars = ax.bar(labels, outcomes, color=colors, edgecolor="black", linewidth=0.6)
for bar, ok in zip(bars, outcomes):
    txt = "PASS" if ok else "FAIL"
    ax.text(bar.get_x() + bar.get_width()/2, 0.5, txt,
            ha="center", va="center", fontsize=11, fontweight="bold",
            color="white" if ok else "white")
ax.set_ylim(0, 1.15)
ax.set_yticks([])
ax.set_title("Push outcome (1MB file)")
ax.set_facecolor("#fafafa")
ax.spines[["top", "right", "left"]].set_visible(False)

# ─────────────────────────────────────────────────────────────────────
# Panel 2: retry rounds used
# ─────────────────────────────────────────────────────────────────────
ax = axes[0][1]
rounds = [d[4] for d in DATA]
bars = ax.bar(labels, rounds, color=colors, edgecolor="black", linewidth=0.6)
ax.set_title("DTP retry rounds used")
ax.set_ylabel("rounds")
ax.set_ylim(0, 10)
ax.axhline(y=8, color="gray", linestyle="--", linewidth=0.8, alpha=0.5)
ax.text(3.4, 8.2, "smart cap = 8", color="gray", fontsize=8, ha="right")
ax.axhline(y=0, color="gray", linestyle="--", linewidth=0.8, alpha=0.5)
ax.text(3.4, 0.2, "naive cap = 0", color="gray", fontsize=8, ha="right")
for bar, r in zip(bars, rounds):
    ax.text(bar.get_x() + bar.get_width()/2, r + 0.15, str(r),
            ha="center", va="bottom", fontsize=10)
ax.grid(True, axis="y", color=GRID, linewidth=0.6)
ax.set_axisbelow(True)
ax.set_facecolor("#fafafa")
ax.spines[["top", "right"]].set_visible(False)

# ─────────────────────────────────────────────────────────────────────
# Panel 3: packets seen vs dropped — proves loss filter rate matches config
# ─────────────────────────────────────────────────────────────────────
ax = axes[1][0]
filtered = [(d[0], d[1], d[2], d[3]) for d in DATA if d[2] is not None]
xlabels  = [f"{b}\n{lp}% loss" for (b, lp, _, _) in filtered]
seen     = [t for (_, _, _, t) in filtered]
dropped  = [d for (_, _, d, _) in filtered]
x = range(len(filtered))
ax.bar(x, seen, color="#cbd5e1", label="packets seen", edgecolor="black", linewidth=0.6)
ax.bar(x, dropped, color="#dc2626", label="dropped by filter", edgecolor="black", linewidth=0.6)
for i, (s, d) in enumerate(zip(seen, dropped)):
    pct = 100*d/s if s else 0
    ax.text(i, s + 30, f"{d}/{s}\n({pct:.2f}%)",
            ha="center", va="bottom", fontsize=9)
ax.set_xticks(list(x))
ax.set_xticklabels(xlabels)
ax.set_ylabel("packet count")
ax.set_title("Loss filter accuracy (configured 5% → measured ~5.3%)")
ax.legend(loc="upper left", framealpha=0.95)
ax.grid(True, axis="y", color=GRID, linewidth=0.6)
ax.set_axisbelow(True)
ax.set_facecolor("#fafafa")
ax.spines[["top", "right"]].set_visible(False)
ax.set_ylim(0, max(seen) * 1.25)

# ─────────────────────────────────────────────────────────────────────
# Panel 4: the F3.b shape this proves (the thesis chart preview)
# ─────────────────────────────────────────────────────────────────────
ax = axes[1][1]
#  measured cells:
#    smart  0% → 30/30 = 100%  (tail_race.csv, sweep_tail_race.sh)
#    smart  1% → 5/5  = 100%   mean 1.80 retry rounds  (loss_rates.csv)
#    smart  5% → 5/5  = 100%   mean 6.80 retry rounds — right at the budget edge
#    smart 10% → 0/5  =   0%   mean 8.00 (cap) — single-pass exhausts; resume needed
#    naive  0% → 1/30 = 3.3%   (tail_race.csv)
#    naive  1% → 0/5  =   0%   (loss_rates.csv)
#    naive  5% → 0/5  =   0%
#    naive 10% → 0/5  =   0%
loss_axis  = [0, 1, 5, 10]
smart_curve = [100, 100, 100, 0]   # single-pass; 10% requires cross-pass resume
naive_curve = [3.3, 0, 0, 0]
ax.plot(loss_axis, smart_curve, "o-", color=SMART, linewidth=2.5,
        markersize=8, label="smart DTP, single-pass")
ax.plot(loss_axis, naive_curve, "s-", color=NAIVE, linewidth=2.5,
        markersize=8, label="naive baseline")
# Mean retry rounds annotated above the smart points to show the budget-edge story
for x, y, r in zip(loss_axis[1:], smart_curve[1:], [1.80, 6.80, 8.00]):
    ax.text(x, y + 4, f"{r:.1f} rounds", ha="center", fontsize=8, color=SMART)
# Surprise call-out: naive fails at 0% loss too — libdtp tail race
ax.annotate("naive: 29/30 fail at 0%\n(libdtp tail-end race,\ntail_race.csv n=30)",
            xy=(0, 3.3), xytext=(2, 22),
            fontsize=8, ha="left", color=NAIVE,
            arrowprops=dict(arrowstyle="->", color=NAIVE, lw=0.8))
# Smart 10% point: single-pass fails but state is saved for cross-pass resume
ax.annotate("smart 10%: 0/5 single-pass\nbut all 5 saved state\nfor cross-pass resume",
            xy=(10, 0), xytext=(5.5, 35),
            fontsize=8, ha="left", color=SMART,
            arrowprops=dict(arrowstyle="->", color=SMART, lw=0.8))
ax.set_xlabel("packet loss rate (%)")
ax.set_ylabel("single-pass push success rate (%)")
ax.set_title("F3.b — measured: tail_race.csv n=30 + loss_rates.csv n=5")
ax.legend(loc="upper right", framealpha=0.95)
ax.grid(True, color=GRID, linewidth=0.6)
ax.set_axisbelow(True)
ax.set_facecolor("#fafafa")
ax.spines[["top", "right"]].set_visible(False)
ax.set_ylim(-5, 110)

plt.tight_layout(rect=[0, 0, 1, 0.97])

out = Path(__file__).parent / "results" / "figures"
out.mkdir(parents=True, exist_ok=True)
out_path = out / "smoke_comparison.png"
plt.savefig(out_path, dpi=140, bbox_inches="tight")
print(f"Wrote {out_path}")
