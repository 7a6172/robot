"""Plot the p3 adaptation-budget curve (RailYard, task-v2 protocol).

Reproduces figs/p3_adaptation_budget_curve.png from the measured points in
docs/isaac/06_results.md §6. X axis = target-world (rail-yard) expert demos used
to retrain-from-scratch via BC; Y axis = blocked-goal success under the transfer
protocol (--fixed_block_prob 1.0, 256 envs x 2405 steps, seed 42).

Reference lines:
  - engine zero-shot: frozen source policy, NO target data, NO gradient steps
    (transfer ledger §3, blocked success 0.190);
  - expert oracle: in-engine geodesic expert measured on the same protocol
    (0.535, see p3_railyard_collect.log).

Usage:
    cd openmover_ws/isaac/lab && python3 28_plot_budget_curve.py
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

budgets = [0, 40960, 81920, 163840, 327680]
blocked_success = [0.001, 0.005, 0.022, 0.083, 0.318]
ENGINE_ZERO_SHOT = 0.190  # transfer ledger §3 (frozen run17 clone on rail yard)
EXPERT_ORACLE = 0.535     # geodesic expert, 1541 episodes (p3_railyard_collect.log)

fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=150)
ax.plot(budgets, blocked_success, "o-", color="#d62728", lw=2.2, ms=7,
        label="retrain from scratch (BC on rail-yard expert demos)")
ax.axhline(ENGINE_ZERO_SHOT, color="#1a9c4b", ls=(0, (6, 3)), lw=2.0,
           label=f"NMTE engine zero-shot = {ENGINE_ZERO_SHOT:.3f} (0 target demos)")
ax.axhline(EXPERT_ORACLE, color="#1f6feb", ls=(0, (2, 2)), lw=1.6,
           label=f"geodesic expert oracle = {EXPERT_ORACLE:.3f}")

# linear interpolation between 164k and 328k for the crossing budget
x0, x1 = 163840, 327680
y0, y1 = 0.083, 0.318
cross = x0 + (ENGINE_ZERO_SHOT - y0) * (x1 - x0) / (y1 - y0)
ax.plot([cross], [ENGINE_ZERO_SHOT], marker="x", ms=11, mew=2.4, color="#333333")
ax.annotate(f"reaching the engine's zero-shot needs\n~{cross / 1e3:.0f}k target demos",
            xy=(cross, ENGINE_ZERO_SHOT), xytext=(cross * 0.42, ENGINE_ZERO_SHOT + 0.065),
            fontsize=8.5, color="#333333",
            arrowprops=dict(arrowstyle="->", color="#333333", lw=1.1))

ax.set_xticks(budgets)
ax.set_xticklabels(["0", "41k", "82k", "164k", "328k"])
ax.set_xlabel("rail-yard expert demos (retraining budget)")
ax.set_ylabel("blocked-goal success")
ax.set_ylim(-0.02, 0.60)
ax.set_xlim(-12000, 420000)
ax.set_title("Adaptation budget curve — rail yard (task-v2 protocol, seed 42)")
ax.grid(alpha=0.3)
ax.legend(loc="upper left", fontsize=8.5)
fig.tight_layout()

out = Path(__file__).resolve().parent / "figs" / "p3_adaptation_budget_curve.png"
out.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(out)
print(f"[plot] wrote {out} (crossing budget ~{cross:.0f} demos)")
