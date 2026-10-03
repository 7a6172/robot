#!/usr/bin/env python3
"""make_figures.py — generate the quantitative figures for paper draft v3.

Reads the project's own artifacts (traces, map JSONs, policy logs) plus the
published ledger numbers (docs/isaac/06_results.md) and writes PNG figures
into draft/figs/.  Pure matplotlib/numpy; no network, no simulator.

Every number plotted here is either (a) recomputed from a kept artifact
(traces/logs) or (b) copied verbatim from the results ledger, cited in the
caption of the corresponding figure in paper_v3.html.

COLOUR GRAMMAR (one meaning per colour, paper-wide):
    red         unprotected / policy-only / danger  (no shield in the loop)
    deep navy   trained policy + shield             (the neural thesis arm)
    steel blue  A*+DWA + shield                     (the classical thesis arm)
    gray        frozen weights / baselines / oracles (no interface, no risk claim)
    amber       escape-tier shield activity         (a shield tier, not an arm)
Anything wrapped in the shield is blue; anything unwrapped is red or gray.
"""
import json
import math
import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import PolyCollection

ROOT = "/home/zar/Documents/phd/robot"
WS = os.path.join(ROOT, "openmover_ws")
LAB = os.path.join(WS, "isaac", "lab")
FIGS = os.path.join(ROOT, "draft", "figs")
os.makedirs(FIGS, exist_ok=True)

IT1 = os.path.join(LAB, "videos", "custommap_demo")
IT2 = os.path.join(LAB, "videos", "custommap_shield")
MAPS = os.path.join(LAB, "maps")
LOGS = os.path.join(LAB, "logs")
HELDOUT = os.path.join(LAB, "campaign", "heldout")
HELDOUT_VIDEOS = os.path.join(HELDOUT, "videos_present", "videos")

MAPS5 = ["open", "mid", "crossings", "gauntlet", "tour"]

# --- palette (see module docstring) ---------------------------------------
C_UNPROT = "#C0392B"   # red:      unprotected / policy-only
C_NEURAL = "#123A6B"   # navy:     trained + shield
C_CLASS = "#4E8FC7"    # steel:    A*+DWA + shield
C_FROZEN = "#7A7A7A"   # gray:     frozen weights / baseline
C_ORACLE = "#B8B8B8"   # light gray: oracle / reference ceiling
C_ESCAPE = "#E8A33D"   # amber:    escape-tier interventions
C_SPAWN = "#2E8B57"    # green:    spawn marker
C_GOAL = "#111111"     # near-black: goal marker
C_WALL = "#3A3A3A"     # wall fill

# --- shield constants (verbatim from openmover_lab/shield_lite.py) ----------
SHIELD_MARGIN = 0.10        # m hull-surface clearance enforced (shield_lite.py:67)
WHEEL_HALF_TRACK = 0.162    # m, WHEEL_SEPARATION 0.324 / 2 (shield_lite.py:89)

plt.rcParams.update({
    "font.family": "serif", "font.size": 9, "axes.titlesize": 9,
    "axes.labelsize": 9, "legend.fontsize": 8, "figure.dpi": 150,
    "axes.grid": True, "grid.alpha": 0.3,
})

# --------------------------------------------------------------------------
# exact hull-vs-wall clearance (same geometry as 30_clearance_audit.py)
# --------------------------------------------------------------------------
HX, HY = 0.22, 0.14


def hull13(hx=HX, hy=HY):
    """The 13-point audit hull: centre, four edge midpoints, four corners,
    and four half-width points.  This is the instrument behind ledger §17.23
    and Fig. 10; it is COARSER than the shield's own 51-point perimeter."""
    pts = [(0.0, 0.0), (hx, 0.0), (-hx, 0.0), (0.0, hy), (0.0, -hy)]
    pts += [(sx * hx, sy * hy) for sx in (1, -1) for sy in (1, -1)]
    pts += [(sx, sy) for sx in (hx, -hx) for sy in (hy / 2, -hy / 2)]
    return pts


PTS = hull13()
PTS_WHEEL = hull13(hy=WHEEL_HALF_TRACK)   # drive-hardware envelope


def load_boxes(map_file):
    boxes = []
    for b in json.load(open(map_file))["boxes"]:
        boxes.append((b[0] - b[3] / 2, b[0] + b[3] / 2,
                      b[1] - b[4] / 2, b[1] + b[4] / 2))
    return boxes


def pt_box(px, py, x0, x1, y0, y1):
    dx = max(x0 - px, px - x1, 0.0)
    dy = max(y0 - py, py - y1, 0.0)
    if dx == 0.0 and dy == 0.0:
        return -min(px - x0, x1 - px, py - y0, y1 - py)
    return math.hypot(dx, dy)


def clearance_series(trace, boxes, pts=None):
    pts = PTS if pts is None else pts
    traj = np.load(trace)["traj"]
    cl = np.empty(traj.shape[0])
    for i in range(traj.shape[0]):
        x, y, yaw = traj[i]
        c, s = math.cos(yaw), math.sin(yaw)
        m = np.inf
        for bx, by in pts:
            wx = x + c * bx - s * by
            wy = y + s * bx + c * by
            m = min(m, min(pt_box(wx, wy, *b) for b in boxes))
        cl[i] = m
    return cl


def clearance_fast(traj, boxes, pts):
    """Vectorised clearance_series for the 884-box held-out map (chunked so
    the (frames, hull pts, boxes) broadcast stays inside ~100 MB)."""
    P = np.asarray(pts, dtype=float)
    B = np.asarray(boxes, dtype=float)
    x0, x1, y0, y1 = B[:, 0], B[:, 1], B[:, 2], B[:, 3]
    out = np.empty(len(traj))
    for s in range(0, len(traj), 100):
        ch = traj[s:s + 100]
        x, y, yaw = ch[:, 0], ch[:, 1], ch[:, 2]
        c, sn = np.cos(yaw)[:, None], np.sin(yaw)[:, None]
        wx = (x[:, None] + c * P[None, :, 0] - sn * P[None, :, 1])[:, :, None]
        wy = (y[:, None] + sn * P[None, :, 0] + c * P[None, :, 1])[:, :, None]
        dx = np.maximum(np.maximum(x0 - wx, wx - x1), 0.0)
        dy = np.maximum(np.maximum(y0 - wy, wy - y1), 0.0)
        d = np.hypot(dx, dy)
        din = np.minimum.reduce([wx - x0, x1 - wx, wy - y0, y1 - wy])
        out[s:s + 100] = np.where((dx == 0) & (dy == 0), -din, d).min(axis=(1, 2))
    return out


def wall_collection(boxes, fc=C_WALL, ec="0.15", lw=0.15):
    """One artist for N wall boxes (884 patches per panel is too slow)."""
    verts = [[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
             for x0, x1, y0, y1 in boxes]
    return PolyCollection(verts, facecolor=fc, edgecolor=ec, linewidths=lw)


def margin_band(ax, margin=SHIELD_MARGIN, label=False):
    """Shade the shield's enforced margin: pale red below +`margin` (inside
    the margin the shield refuses to enter), pale green above it (certified).
    `margin` is SHIELD_MARGIN = 0.10 m, the presentation-era constant."""
    lo, hi = ax.get_ylim()
    ax.axhspan(lo, 0.0, color=C_UNPROT, alpha=0.16, lw=0, zorder=0)
    ax.axhspan(0.0, margin, color=C_UNPROT, alpha=0.09, lw=0, zorder=0,
               label="inside shield margin" if label else None)
    ax.axhspan(margin, hi, color="#2E8B57", alpha=0.09, lw=0, zorder=0,
               label="certified (>margin)" if label else None)
    ax.axhline(0.0, color=C_UNPROT, lw=1.1, zorder=1)
    ax.axhline(margin, color="#2E8B57", lw=0.7, ls="--", zorder=1)


# --------------------------------------------------------------------------
# Fig 5 — adaptation-budget curve (ledger §6)
# --------------------------------------------------------------------------
def fig_budget():
    demos = np.array([0, 41, 82, 164, 328])
    succ = np.array([0.001, 0.005, 0.022, 0.083, 0.318])
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.plot(demos, succ, "o-", color=C_FROZEN, lw=1.6, ms=5,
            label="retrain-from-scratch BC")
    ax.axhline(0.190, color=C_NEURAL, ls="--", lw=1.6,
               label="frozen engine + interface (0.190)")
    ax.axhline(0.535, color=C_ORACLE, ls=":", lw=1.4,
               label="geodesic expert oracle (0.535)")
    cross = 238
    ax.plot([cross], [0.190], "*", color=C_GOAL, ms=15, zorder=5,
            mec="w", mew=0.6)
    ax.annotate("$\\approx$238k target demos\nto match frozen transfer",
                xy=(cross, 0.190), xytext=(cross - 195, 0.30), fontsize=8.5,
                ha="left", va="center", zorder=6,
                bbox=dict(boxstyle="round,pad=0.3", fc="white",
                          ec=C_NEURAL, lw=0.7, alpha=0.95),
                arrowprops=dict(arrowstyle="->", color=C_NEURAL, lw=0.9,
                                shrinkA=2, shrinkB=4))
    ax.set_xlabel("target-world expert demonstrations (thousands)")
    ax.set_ylabel("blocked-goal success")
    ax.set_title("Adaptation budget: retraining vs frozen transfer (rail yard)")
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3,
               bbox_to_anchor=(0.5, 0.02), framealpha=0.92, fontsize=7.0)
    ax.set_xlim(-14, 348)
    ax.set_ylim(0, 0.6)
    fig.tight_layout()
    fig.subplots_adjust(bottom=0.30)
    fig.savefig(f"{FIGS}/fig_budget_curve.svg")
    plt.close(fig)


# --------------------------------------------------------------------------
# Fig 6 — DOB-lite A/B (ledger §7)
# --------------------------------------------------------------------------
def fig_dob():
    labels = ["source\nfrozen", "source\n+DOB", "degraded\nfrozen",
              "degraded\n+DOB", "degraded\noracle", "combined\nfrozen",
              "combined\n+DOB"]
    vals = [0.287, 0.303, 0.028, 0.363, 0.375, 0.044, 0.250]
    cols = [C_FROZEN, C_NEURAL, C_FROZEN, C_NEURAL, C_ORACLE, C_FROZEN,
            C_NEURAL]
    fig, ax = plt.subplots(figsize=(7.0, 2.4))
    ax.bar(labels, vals, color=cols, edgecolor="k", linewidth=0.5)
    for i, v in enumerate(vals):
        ax.text(i, v + 0.01, f"{v:.3f}", ha="center", fontsize=7.5)
    ax.set_ylabel("blocked-goal success")
    ax.set_title("Dynamics axis: disturbance-observer interface, weights frozen"
                 "  (navy = interface active)")
    ax.set_ylim(0, 0.45)
    fig.tight_layout()
    fig.savefig(f"{FIGS}/fig_dob_ab.svg")
    plt.close(fig)


# --------------------------------------------------------------------------
# Fig 8 — CBF-lite A/B (ledger §8)
# --------------------------------------------------------------------------
def fig_cbf():
    seeds = ["42", "1", "7"]
    coll_f = [0.864, 0.783, 0.750]
    coll_c = [0.565, 0.591, 0.682]
    succ_f = [0.227, 0.348, 0.417]
    succ_c = [0.348, 0.318, 0.409]
    x = np.arange(3)
    fig, ax = plt.subplots(figsize=(7.0, 2.5))
    ax.bar(x - 0.2, coll_f, 0.4, color=C_UNPROT, edgecolor="k", lw=0.5,
           label="collision, unprotected (frozen)")
    ax.bar(x + 0.2, coll_c, 0.4, color=C_NEURAL, edgecolor="k", lw=0.5,
           label="collision, +CBF-lite")
    ax.plot(x - 0.2, succ_f, "s", color=C_GOAL, ms=5.5, mec="w", mew=0.6,
            label="success, unprotected")
    ax.plot(x + 0.2, succ_c, "o", color=C_NEURAL, ms=5.5, mec="w", mew=0.8,
            label="success, +CBF-lite")
    ax.set_xticks(x)
    ax.set_xticklabels([f"seed {s}" for s in seeds])
    ax.set_ylabel("rate")
    ax.set_title("Safety axis (ring map): barrier filter cuts collisions, task held")
    ax.legend(loc="upper right", ncol=2, framealpha=0.92)
    ax.set_ylim(0, 1.0)
    fig.tight_layout()
    fig.savefig(f"{FIGS}/fig_cbf_ab.svg")
    plt.close(fig)


# --------------------------------------------------------------------------
# Fig 7 — Koopman concept check (ledger §11)
# --------------------------------------------------------------------------
def fig_koopman():
    ch = ["vx", "wz", "wl", "wr"]
    src_on_src = [0.79, 0.82, 0.88, 0.88]
    src_on_deg = [0.81, 0.76, 0.57, 0.57]
    refit_deg = [0.90, 0.88, 0.99, 0.99]
    persist = [0.80, 0.77, 0.79, 0.77]
    x = np.arange(4)
    w = 0.2
    fig, ax = plt.subplots(figsize=(7.0, 2.5))
    ax.bar(x - 1.5 * w, src_on_src, w, color=C_ORACLE, edgecolor="k", lw=0.5,
           label="frozen source fit, source val")
    ax.bar(x - 0.5 * w, src_on_deg, w, color=C_FROZEN, edgecolor="k", lw=0.5,
           label="frozen source fit, degraded val")
    ax.bar(x + 0.5 * w, refit_deg, w, color=C_NEURAL, edgecolor="k", lw=0.5,
           label="refit on degraded, degraded val")
    ax.bar(x + 1.5 * w, persist, w, color="#DCDCDC", edgecolor="k", lw=0.5,
           label="persistence baseline, degraded")
    ax.set_xticks(x)
    ax.set_xticklabels(ch)
    ax.set_ylabel("one-step R$^2$")
    ax.set_title("Koopman lift: frozen structure loses wheel channels, refit recovers")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2,
              framealpha=0.92, fontsize=7)
    ax.set_ylim(0, 1.05)
    fig.tight_layout()
    fig.savefig(f"{FIGS}/fig_koopman.svg", bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------------------
# Fig 4 — difficulty ladder + shield on the hard rung (ledger §13, §15)
# --------------------------------------------------------------------------
def fig_ladder():
    labels = ["easy", "mid", "hard", "hard\n+shield"]
    times = [29.30, 26.15, np.nan, 29.10]
    rec = [20, 14, 25, 1]
    fig, ax = plt.subplots(figsize=(7.0, 2.4))
    for i, (t, r) in enumerate(zip(times, rec)):
        if np.isnan(t):
            ax.bar(i, 30, color="none", edgecolor=C_UNPROT, hatch="xxx", lw=0.9)
            ax.text(i, 31, "wedge\nfailure", ha="center", color=C_UNPROT,
                    fontsize=7.5)
        else:
            ax.bar(i, t, color=C_FROZEN if i < 2 else C_NEURAL,
                   edgecolor="k", lw=0.5)
            ax.text(i, t + 0.6, f"{t:.1f}s", ha="center", fontsize=7.5)
    ax.set_xticks(range(4))
    ax.set_xticklabels([f"{l}\nrec {r}" for l, r in zip(labels, rec)])
    ax.set_ylabel("time-to-goal (s)")
    ax.set_title("Transfer gradient: behaviour overlap, not visual complexity")
    ax.set_ylim(0, 36)
    fig.tight_layout()
    fig.savefig(f"{FIGS}/fig_ladder.svg")
    plt.close(fig)


# --------------------------------------------------------------------------
# Fig 9 — penetration frames, iteration 1 vs 2 (recomputed from traces)
# --------------------------------------------------------------------------
def fig_penetration():
    counts = {"iter1": [], "iter2": []}
    for m in MAPS5:
        mf = f"{MAPS}/demo_{m}.json"
        boxes = load_boxes(mf)
        for key, folder in (("iter1", IT1), ("iter2", IT2)):
            cl = clearance_series(f"{folder}/trace_demo_{m}.npz", boxes)
            counts[key].append(int((cl < 0).sum()))
    x = np.arange(5)
    fig, ax = plt.subplots(figsize=(7.0, 2.4))
    ax.bar(x - 0.2, counts["iter1"], 0.4, color=C_UNPROT, edgecolor="k",
           lw=0.5, label="iteration 1 (policy only, unprotected)")
    ax.bar(x + 0.2, counts["iter2"], 0.4, color=C_NEURAL, edgecolor="k",
           lw=0.5, label="iteration 2 (+deploy-time shield)")
    for i, v in enumerate(counts["iter1"]):
        ax.text(i - 0.2, v + 12, str(v), ha="center", fontsize=7.5,
                color=C_UNPROT)
    for i, v in enumerate(counts["iter2"]):
        ax.text(i + 0.2, v + 12, str(v), ha="center", fontsize=7.5,
                color=C_NEURAL)
    ax.set_xticks(x)
    ax.set_xticklabels([f"demo_{m}" for m in MAPS5], fontsize=8)
    ax.set_ylabel("hull-penetration frames (exact boxes)")
    ax.set_title("Contact frames before/after the deploy-time shield")
    ax.set_ylim(0, 1100)
    ax.legend(loc="upper left", framealpha=0.92)
    fig.tight_layout()
    fig.savefig(f"{FIGS}/fig_penetration.svg")
    plt.close(fig)
    return counts


# --------------------------------------------------------------------------
# Fig 10 — exact clearance time series, shielded runs (recomputed)
# --------------------------------------------------------------------------
def fig_clearance():
    fig, axs = plt.subplots(5, 1, figsize=(7.0, 6.5), sharex=False)
    mins = {}
    for ax, m in zip(axs, MAPS5):
        boxes = load_boxes(f"{MAPS}/demo_{m}.json")
        cl = clearance_series(f"{IT2}/trace_demo_{m}.npz", boxes)
        t = np.arange(len(cl)) / 15.0
        ax.set_ylim(-0.06, max(0.45, cl.max() * 1.12))
        margin_band(ax, label=(m == "open"))
        ax.plot(t, cl, lw=0.9, color=C_NEURAL, zorder=3)
        ax.fill_between(t, cl, 0, where=cl < 0, color=C_UNPROT, alpha=0.6,
                        zorder=4)
        mins[m] = cl.min()
        ax.set_ylabel(f"{m}\nclr (m)", fontsize=7.5)
        ax.text(0.005, 0.94, f"min {cl.min():+.3f} m", transform=ax.transAxes,
                ha="left", va="top", fontsize=7.5, zorder=6,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="0.7",
                          lw=0.5, alpha=0.9))
        ax.tick_params(labelsize=7)
    axs[0].legend(loc="upper right", fontsize=6.5, framealpha=0.92)
    axs[-1].set_xlabel("time (s)")
    fig.suptitle("Iteration 2: hull clearance over time, exact wall geometry "
                 f"(green band = certified, >{SHIELD_MARGIN:.2f} m margin)",
                 fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    fig.savefig(f"{FIGS}/fig_clearance.svg")
    plt.close(fig)
    return mins


# --------------------------------------------------------------------------
# Fig 11 — trajectories on the five presentation maps (recomputed)
# --------------------------------------------------------------------------
def fig_traj():
    fig, axs = plt.subplots(1, 5, figsize=(7.2, 2.0))
    for ax, m in zip(axs, MAPS5):
        spec = json.load(open(f"{MAPS}/demo_{m}.json"))
        boxes = load_boxes(f"{MAPS}/demo_{m}.json")
        ax.add_collection(wall_collection(boxes))
        tr = np.load(f"{IT2}/trace_demo_{m}.npz")["traj"]
        ax.plot(tr[:, 0], tr[:, 1], lw=1.1, color=C_NEURAL, zorder=3,
                solid_capstyle="round")
        ax.plot(tr[0, 0], tr[0, 1], "o", color=C_SPAWN, ms=7, zorder=5,
                mec="w", mew=0.8)
        goals = spec.get("goals") or [spec["goal"]]
        for gg in goals:
            ax.plot(gg[0], gg[1], "*", color=C_GOAL, ms=12, zorder=5,
                    mec="w", mew=0.7)
        sx, sy = spec["size"][0], spec["size"][1]
        ticks = [0, sx / 2, sx]
        ax.set_aspect("equal")
        ax.set_xticks(ticks)
        ax.set_yticks([0, sy / 2, sy])
        ax.tick_params(labelsize=6)
        ax.set_title(f"demo_{m}", fontsize=8)
        ax.grid(False)
        ax.set_xlim(-0.4, sx + 0.4)
        ax.set_ylim(-0.4, sy + 0.4)
    fig.tight_layout()
    fig.savefig(f"{FIGS}/fig_trajectories.svg")
    plt.close(fig)


# --------------------------------------------------------------------------
# Fig 12 — shield interventions parsed from the run logs
# --------------------------------------------------------------------------
def fig_interventions():
    logmap = {"open": "shield_policy_open_v4.log",
              "mid": "shield_policy_mid_v4.log",
              "crossings": "shield_policy_crossings_v4.log",
              "gauntlet": "shield_policy_gauntlet_v4.log",
              "tour": "shield_policy_tour_v5.log",
              "tour\nconfirm": "shield_policy_tour_v5_confirm.log"}
    ticks, esc = [], []
    for name, lf in logmap.items():
        txt = open(f"{LOGS}/{lf}").read()
        mm = re.findall(r"recoveries=(\d+); shield_ticks=(\d+)"
                        r"(?:; escape=(\d+))?", txt)
        st = ee = 0
        if mm:
            st = int(mm[-1][1])
            ee = int(mm[-1][2] or 0)
        ticks.append(st)
        esc.append(ee)
    x = np.arange(len(ticks))
    fig, ax = plt.subplots(figsize=(7.0, 2.5))
    base = [t - e for t, e in zip(ticks, esc)]
    ax.bar(x, base, color=C_NEURAL, edgecolor="k", lw=0.5,
           label="comfort/projection-tier interventions")
    ax.bar(x, esc, bottom=base, color=C_ESCAPE, edgecolor="k", lw=0.5,
           label="escape-tier interventions")
    for i, v in enumerate(ticks):
        ax.text(i, v + 1.5, str(v), ha="center", fontsize=7.5)
    ax.set_xticks(x)
    ax.set_xticklabels(logmap.keys(), fontsize=8)
    ax.set_ylabel("shield ticks / 2400")
    ax.set_title("Shield activity per run (0 = policy never needed the filter)")
    ax.set_ylim(0, max(ticks) * 1.30)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.02), ncol=2,
              framealpha=0.92, fontsize=7.5)
    fig.tight_layout()
    fig.savefig(f"{FIGS}/fig_interventions.svg")
    plt.close(fig)
    return dict(zip([k.replace("\n", " ") for k in logmap], ticks))


# --------------------------------------------------------------------------
# Fig 13 — 3-arm campaign: success/collision per difficulty bin
# (data: campaign/aggregate.json, episode-pooled by 34_aggregate_campaign.py)
# --------------------------------------------------------------------------
CAMP_ARMS = [("astar_dwa", "A*+DWA (unprotected)", C_UNPROT),
             ("astar_dwa_shield", "A*+DWA + shield", C_CLASS),
             ("shield", "trained + shield", C_NEURAL)]


def fig_campaign():
    agg_file = os.path.join(LAB, "campaign", "aggregate.json")
    if not os.path.exists(agg_file):
        return None
    agg = json.load(open(agg_file))
    bins = ["0", "1", "2", "3"]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.6), sharey=True)
    w = 0.26
    x = np.arange(len(bins))
    for panel, metric, title in (
            (axes[0], "success", "Success rate"),
            (axes[1], "collision", "Collision rate")):
        for k, (arm, label, colr) in enumerate(CAMP_ARMS):
            vals = []
            for b in bins:
                e = agg["arms"][arm]["per_bin"].get(b)
                vals.append(np.nan if e is None else e[metric])
            panel.bar(x + (k - 1) * w, vals, width=w, color=colr,
                      edgecolor="k", lw=0.5, label=label)
        panel.set_xticks(x)
        panel.set_xticklabels([f"bin {b}" for b in bins])
        panel.set_title(title)
        panel.set_ylim(0, 1.02)
    axes[0].set_ylabel("episode-pooled rate")
    axes[1].legend(loc="upper center", framealpha=0.92, ncols=1, fontsize=7.5)
    n_ep = sum(agg["arms"][a]["overall"]["episodes"]
               for a, _, _ in CAMP_ARMS
               if agg["arms"][a]["overall"] is not None)
    fig.suptitle(f"3-arm campaign: 56 procedural maps, {n_ep} episodes, seed 42"
                 "   (blue = shielded, red = unprotected)", fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(f"{FIGS}/fig_campaign.svg")
    plt.close(fig)
    return n_ep


# --------------------------------------------------------------------------
# Fig 15 — HELD-OUT ENDGAME HERO (ledger §17.22 / §17.23)
# row 1: env-0 trajectory per arm on the 884-box user-drawn map
# row 2: exact hull clearance vs time for the same episode
# Recomputed from campaign/heldout/videos_present/videos/heldout_<arm>_clip.npz
# --------------------------------------------------------------------------
HELDOUT_ARMS = [
    ("astar_dwa", "A*+DWA unprotected", C_UNPROT, False,
     "106.8 s, reached — COLLISION (env 0 penalized)"),
    ("astar_dwa_shield", "A*+DWA + shield (thesis)", C_CLASS, True,
     "104.1 s, reached — clean (env 0 not penalized)"),
    ("shield", "trained + shield (neural)", C_NEURAL, False,
     "147.5 s TIMEOUT — stopped 6.98 m short"),
]


def fig_heldout():
    spec = json.load(open(f"{MAPS}/heldout.json"))
    boxes = load_boxes(f"{MAPS}/heldout.json")
    spawn, goal = spec["spawn"], spec["goal"]
    fig = plt.figure(figsize=(7.2, 5.9))
    gs = fig.add_gridspec(2, 3, height_ratios=[1.15, 1.0],
                          hspace=0.55, wspace=0.26,
                          left=0.075, right=0.985, top=0.915, bottom=0.075)
    stats = {}
    for col, (arm, label, colr, reached, outcome) in enumerate(HELDOUT_ARMS):
        d = np.load(f"{HELDOUT_VIDEOS}/heldout_{arm}_clip.npz")
        off = d["origin"] - d["size"] / 2.0      # npz stores the tile CENTRE
        tr = d["traj"].astype(float)
        tr[:, 0] -= off[0]
        tr[:, 1] -= off[1]
        t = np.arange(len(tr)) / 20.0            # 20 Hz recording (ledger 17.23)
        cl = clearance_fast(tr, boxes, PTS)
        stats[arm] = {"frames": len(tr), "min": float(cl.min()),
                      "pen": int((cl < 0).sum()),
                      "sub": int((cl < SHIELD_MARGIN).sum())}

        # --- row 1: trajectory -------------------------------------------
        ax = fig.add_subplot(gs[0, col])
        ax.add_collection(wall_collection(boxes))
        ax.plot(tr[:, 0], tr[:, 1], lw=1.3, color=colr, zorder=3,
                solid_capstyle="round")
        ax.plot(spawn[0], spawn[1], "o", color=C_SPAWN, ms=8, zorder=5,
                mec="w", mew=0.9)
        ax.plot(goal[0], goal[1], "*", color=C_GOAL, ms=14, zorder=5,
                mec="w", mew=0.8)
        if not reached:
            ax.plot(tr[-1, 0], tr[-1, 1], "x", color=colr, ms=8, mew=1.8,
                    zorder=6)
        ax.set_aspect("equal")
        ax.set_xlim(0, spec["size"][0])
        ax.set_ylim(0, spec["size"][1])
        ax.set_xticks([0, 5, 10, 15])
        ax.set_yticks([0, 5, 10, 15])
        ax.tick_params(labelsize=6.5)
        ax.grid(False)
        ax.set_title(label, fontsize=8.5, color=colr, fontweight="bold")

        # --- row 2: clearance --------------------------------------------
        ac = fig.add_subplot(gs[1, col])
        clipped = cl.max() > 0.45
        ac.set_ylim(-0.05, 0.45 if clipped else cl.max() * 1.08)
        margin_band(ac, label=False)
        ac.plot(t, cl, lw=0.9, color=colr, zorder=4)
        ac.fill_between(t, cl, SHIELD_MARGIN, where=cl < SHIELD_MARGIN,
                        color=C_UNPROT, alpha=0.35, lw=0, zorder=3)
        if arm == "astar_dwa":
            # second instrument: the true drive-hardware envelope.  The shield
            # and the audit both model a 0.22 x 0.14 hull; the wheels sit at
            # y = +-0.162 (shield_lite.py:89), 2.2 cm outside it.  Drawn ONLY
            # for the unprotected arm - the shielded arms never breach the
            # margin on either instrument, so a second line is pure clutter.
            cw = clearance_fast(tr, boxes, PTS_WHEEL)
            stats[arm]["min_wheel"] = float(cw.min())
            ac.plot(t, cw, lw=0.9, ls="--", color=C_UNPROT, alpha=0.85,
                    zorder=5)
            ac.fill_between(t, cw, cl, color=C_UNPROT, alpha=0.22, lw=0,
                            zorder=2)
            k = int(np.argmin(cw))
            ac.annotate(f"wheel-track hull\n0.22$\\times$0.162, min "
                        f"{cw.min():+.3f} m", xy=(t[k], cw[k]),
                        xytext=(0.34, 0.88), textcoords="axes fraction",
                        fontsize=6.2, color=C_UNPROT,
                        ha="left", va="top", zorder=7,
                        bbox=dict(boxstyle="round,pad=0.2", fc="white",
                                  ec=C_UNPROT, lw=0.5, alpha=0.9),
                        arrowprops=dict(arrowstyle="->", color=C_UNPROT,
                                        lw=0.7, shrinkA=1, shrinkB=2))
        ac.set_xlabel("time (s)", fontsize=7.5)
        ac.set_ylabel("hull clearance (m)", fontsize=7.5)
        ac.tick_params(labelsize=6.5)

        # --- column annotation: outcome + clearance stats ----------------
        # wrapped to <=32 chars/line so three columns never collide
        lines = [outcome]
        lines.append(f"min clearance {cl.min():+.3f} m (audit hull)")
        if "min_wheel" in stats[arm]:
            lines.append(f"{stats[arm]['min_wheel']:+.3f} m on the wheel track")
        lines.append(f"{stats[arm]['sub']} frames inside the "
                     f"{SHIELD_MARGIN:.2f} m margin")
        if clipped:
            lines.append(f"open-corridor peaks to {cl.max():.2f} m, clipped")
        ax.text(0.5, -0.09, "\n".join(lines), transform=ax.transAxes,
                ha="center", va="top", fontsize=6.4, color=colr,
                linespacing=1.3)
    fig.suptitle("Held-out endgame, env 0 of 10: hand-drawn 15$\\times$15 m "
                 "maze, 884 walls, unseen in training and in the campaign",
                 fontsize=8.5)
    fig.savefig(f"{FIGS}/fig_heldout.svg")
    plt.close(fig)
    return stats


if __name__ == "__main__":
    fig_budget()
    fig_dob()
    fig_cbf()
    fig_koopman()
    fig_ladder()
    pen = fig_penetration()
    mins = fig_clearance()
    fig_traj()
    iv = fig_interventions()
    n = fig_campaign()
    ho = fig_heldout()
    print("penetration counts (iter1 vs iter2):", pen)
    print("iteration-2 min clearances (m):",
          {k: round(v, 4) for k, v in mins.items()})
    print("shield ticks:", iv)
    if n is not None:
        print("campaign figure: episodes pooled =", n)
    print("held-out hero (recomputed):")
    for k, v in ho.items():
        print("   ", k, {a: (round(b, 4) if isinstance(b, float) else b)
                        for a, b in v.items()})
    print("wrote", sorted(os.listdir(FIGS)))
