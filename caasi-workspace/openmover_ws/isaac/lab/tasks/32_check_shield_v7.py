"""Offline validation of the shield barrier (no simulator, no ROS spin).

Reproducible evidence for the "certified margin" claim in ledger 17.9. The
shield's barrier must be a LOWER bound on the quantity the clearance audit
measures (exact rotated-rectangle hull vs the map's real boxes), otherwise the
no-collision rule is only nominal -- that is exactly what 17.8 caught in v6.

Checks, per map:
  1. BoxSDF vs brute-force exact point-to-box signed distance (over- and
     under-estimate; only the field side matters, it must never over-read).
  2. Certified floor: total optimism of "field sampled on the 0.03 m hull" vs
     "exact distance on a 0.004 m reference hull", over every frame of a real
     trace. Must stay <= SHIELD_ESDF_SLACK, else the slack does not pay for the
     discretisation and the verdict prints NOT CERTIFIED.
  3. Replay: for every frame of a trace, would the tier-1 barrier veto the twist
     the robot actually executed (recovered by finite differences)? Cross-
     tabulated against "the next SHIELD_HORIZON s of the REAL trajectory brought
     the hull inside margin+slack". The guarantee-relevant number is the second
     one: frames where the hull was truly inside a box must all be vetoed.
  4. Per-tick cost of the pass-through check and of the full candidate batch
     against the 20 Hz budget (50 ms).

Run with the Isaac Sim interpreter (policy_node imports torch at module level):

    ~/isaaclab/isaaclab.sh -p isaac/lab/32_check_shield_v7.py
    ~/isaaclab/isaaclab.sh -p isaac/lab/32_check_shield_v7.py \
        --pairs f4_b1_m00:trace_f4_b1_m00_v3_10m.npz --pairs ...
"""
import argparse
import importlib.util
import json
import math
import os
import sys
import time
import types

import numpy as np

LAB = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(os.path.dirname(LAB))
PN = os.path.join(WS, "src", "warehouse_simulation", "scripts", "policy_node.py")

DEFAULT_PAIRS = ("f4_b1_m00:trace_f4_b1_m00_v3_10m.npz",
                 "f6_b2_m00:trace_f6_b2_m00_v3_10m.npz")

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--pairs", action="append", default=None,
                help="MAP:TRACE.npz (trace in videos/genmaps_test); repeatable. "
                     "Default: the two 17.8 v6 failure traces.")
ap.add_argument("--ref_spacing", type=float, default=0.004,
                help="m reference-hull perimeter spacing for check 2")
args = ap.parse_args()
PAIRS = tuple(p.split(":") for p in (args.pairs or DEFAULT_PAIRS))

# ---- stub the ROS imports so the module loads in a plain interpreter --------
for pkg in ("rclpy", "geometry_msgs", "nav_msgs", "sensor_msgs"):
    sys.modules.setdefault(pkg, types.ModuleType(pkg))
rclpy = sys.modules["rclpy"]
rclpy.init = rclpy.shutdown = lambda *a, **k: None
rclpy.spin = lambda *a, **k: None
node_mod = types.ModuleType("rclpy.node")


class Node:                      # noqa: D101 - stub base
    def __init__(self, *a, **k):
        pass


node_mod.Node = Node
rclpy.node = node_mod
sys.modules["rclpy.node"] = node_mod
for pkg, names in (("geometry_msgs", ["Twist"]), ("nav_msgs", ["Odometry"]),
                   ("sensor_msgs", ["LaserScan"])):
    m = types.ModuleType(pkg + ".msg")
    for n in names:
        setattr(m, n, type(n, (), {}))
    sys.modules[pkg + ".msg"] = m
    setattr(sys.modules[pkg], "msg", m)

spec = importlib.util.spec_from_file_location("pn", PN)
pn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pn)


class Shim:
    """Bare object carrying just the barrier methods + the exact field."""


def make_shim(boxes, bounds):
    sh = Shim()
    sh.sdf = pn.BoxSDF(boxes, bounds)
    for m in ("_arc_poses", "_arc_hull", "_arc_clearance", "_barrier_ok"):
        setattr(sh, m, types.MethodType(getattr(pn.PolicyNode, m), sh))
    return sh


def exact_dist(pts, boxes):
    """Brute-force signed distance (C,) from (P,2) points to a box union."""
    best = np.full(pts.shape[0], np.inf)
    for bx, by, yaw, sx, sy in boxes:
        c, s = math.cos(yaw), math.sin(yaw)
        dx, dy = pts[:, 0] - bx, pts[:, 1] - by
        lx = c * dx + s * dy
        ly = -s * dx + c * dy
        ox = np.abs(lx) - 0.5 * sx
        oy = np.abs(ly) - 0.5 * sy
        d = (np.hypot(np.maximum(ox, 0.0), np.maximum(oy, 0.0))
             + np.minimum(np.maximum(ox, oy), 0.0))
        best = np.minimum(best, d)
    return best


def load_map(name):
    with open(f"{LAB}/maps/gen/{name}.json") as f:
        sp = json.load(f)
    boxes = [(float(b[0]), float(b[1]), float(b[2]), float(b[3]), float(b[4]))
             for b in sp["boxes"]]
    bounds = (0.0, 0.0, float(sp["size"][0]), float(sp["size"][1]))
    return sp, boxes, bounds


def hull_at(poses, hull):
    """(T,3) poses x (H,2) hull -> (T*H,2) world points."""
    c = np.cos(poses[:, 2])[:, None]
    s = np.sin(poses[:, 2])[:, None]
    x = poses[:, 0][:, None] + hull[None, :, 0] * c - hull[None, :, 1] * s
    y = poses[:, 1][:, None] + hull[None, :, 0] * s + hull[None, :, 1] * c
    return np.stack([x.ravel(), y.ravel()], axis=1)


for MAP, TRACE in PAIRS:
    sp, boxes, bounds = load_map(MAP)
    sh = make_shim(boxes, bounds)
    sdf = sh.sdf
    print("=" * 78)
    print(f"{MAP}: {len(boxes)} boxes, ESDF {sdf.nx}x{sdf.ny} @ "
          f"{pn.SHIELD_ESDF_RES} m, hull {len(pn.SHIELD_HULL_PTS)} pts")

    # ---- 1. field accuracy vs brute force
    rng = np.random.default_rng(0)
    px = rng.uniform(bounds[0], bounds[2], 4000)
    py = rng.uniform(bounds[1], bounds[3], 4000)
    ex = exact_dist(np.stack([px, py], axis=1), boxes)
    fi = sdf.sample(px, py)
    keep = ex < pn.SHIELD_ESDF_HALO - 1e-6      # clamped region is not compared
    over = (fi - ex)[keep]
    print(f"[1] field vs exact on {keep.sum()} pts (|d|<halo): "
          f"max overestimate {over.max():+.4f} m, max underestimate "
          f"{over.min():+.4f} m, mean abs {np.abs(over).mean():.4f} m")

    # ---- 2. certified floor: hull-perimeter discretisation
    t0 = time.time()
    dh = pn._hull_perimeter(spacing=args.ref_spacing)
    print(f"[2] dense reference hull: {len(dh)} pts "
          f"(spacing {args.ref_spacing} m)")
    tr = np.load(f"{LAB}/videos/genmaps_test/{TRACE}")
    traj = tr["traj"].astype(np.float64)
    T = traj.shape[0]
    fps = 15.0
    fine = exact_dist(hull_at(traj, dh), boxes).reshape(T, -1).min(axis=1)
    coarse = exact_dist(hull_at(traj, pn.SHIELD_HULL_PTS),
                        boxes).reshape(T, -1).min(axis=1)
    field = sdf.sample(hull_at(traj, pn.SHIELD_HULL_PTS)[:, 0],
                       hull_at(traj, pn.SHIELD_HULL_PTS)[:, 1]
                       ).reshape(T, -1).min(axis=1)
    disc = (coarse - fine)          # >= 0: sparse hull over-reads clearance
    opt = (field - coarse)          # field vs exact at the SAME samples
    print(f"    hull discretisation  max {disc.max():+.4f} m "
          f"(budget {pn.SHIELD_HULL_SPACING / 2:.4f})")
    print(f"    field vs exact       max {opt.max():+.4f} m "
          f"min {opt.min():+.4f} m")
    print(f"    total optimism       max {(field - fine).max():+.4f} m "
          f"vs SLACK {pn.SHIELD_ESDF_SLACK} m -> "
          f"{'CERTIFIED' if (field - fine).max() <= pn.SHIELD_ESDF_SLACK else 'NOT CERTIFIED'}")
    print(f"    (exact-box pass over {T} frames x {len(dh)}+"
          f"{len(pn.SHIELD_HULL_PTS)} pts: {time.time() - t0:.1f} s)")

    # ---- 3. replay: would the tier-1 barrier veto the twist executed?
    dt = 1.0 / fps
    dv = np.zeros(T)
    dw = np.zeros(T)
    dxy = np.diff(traj[:, :2], axis=0)
    c, s = np.cos(traj[:-1, 2]), np.sin(traj[:-1, 2])
    dv[:-1] = (dxy[:, 0] * c + dxy[:, 1] * s) / dt
    dw[:-1] = np.diff(np.unwrap(traj[:, 2])) / dt
    dv[-1], dw[-1] = dv[-2], dw[-2]
    H = int(round(pn.SHIELD_HORIZON * fps))
    fut = np.array([fine[t:min(T, t + H + 1)].min() for t in range(T)])
    need = fut < pn.SHIELD_MARGIN + pn.SHIELD_ESDF_SLACK
    veto = np.zeros(T, dtype=bool)
    for t in range(T):
        veto[t] = not sh._barrier_ok(
            np.array([dv[t]]), np.array([dw[t]]), traj[t, :2], traj[t, 2],
            pn.SHIELD_HULL_PTS, pn.SHIELD_MARGIN, None)[0]
    caught = int((need & veto).sum())
    missed = int((need & ~veto).sum())
    print(f"[3] replay of {TRACE} ({T} frames):")
    print(f"    frames whose next {pn.SHIELD_HORIZON} s breach the certified "
          f"floor: {int(need.sum())}")
    print(f"    tier-1 vetoes: {caught} caught / {missed} MISSED")
    pen = fine < 0.0
    print(f"    true-penetration frames (exact boxes): {int(pen.sum())}; "
          f"vetoed at those frames: {int((pen & veto).sum())}")
    if missed:
        mi = np.nonzero(need & ~veto)[0]
        worst = mi[np.argsort(fut[mi])[:5]]
        for t in sorted(worst):
            print(f"      MISSED t={t / fps:6.1f}s pose=({traj[t, 0]:+.2f},"
                  f"{traj[t, 1]:+.2f}) cmd=({dv[t]:+.2f},{dw[t]:+.2f}) "
                  f"future_min={fut[t]:+.3f} now={fine[t]:+.3f}")
    lead = np.nonzero(pen)[0]
    if lead.size:
        first = lead[0]
        prev_veto = np.nonzero(veto[:first])[0]
        print(f"    first penetration t={first / fps:.1f}s; last veto before it "
              f"t={(prev_veto[-1] / fps if prev_veto.size else float('nan')):.1f}s"
              f" ({(first - prev_veto[-1]) / fps if prev_veto.size else float('nan'):.1f}"
              f" s of warning)")

    # ---- 4. cost of the full batch (tier-1 search)
    cv, cw = (a.ravel() for a in np.meshgrid(pn.SHIELD_V_SET,
                                             pn.SHIELD_W_SET, indexing="ij"))
    n = int(round(2 * pn.SHIELD_GRID_EXT / pn.SHIELD_GRID_RES)) + 1
    grid = np.zeros((n, n), dtype=bool)
    grid[30:36, 30:36] = True
    xy, yaw = traj[T // 2, :2], traj[T // 2, 2]
    N = 20
    t0 = time.time()
    for _ in range(N):
        sh._barrier_ok(cv, cw, xy, yaw, pn.SHIELD_HULL_PTS,
                       pn.SHIELD_MARGIN, grid)
    full = (time.time() - t0) / N * 1e3
    t0 = time.time()
    for _ in range(N):
        sh._barrier_ok(np.array([0.2]), np.array([0.3]), xy, yaw,
                       pn.SHIELD_HULL_PTS, pn.SHIELD_MARGIN, grid)
    one = (time.time() - t0) / N * 1e3
    print(f"[4] cost: pass-through check (2 candidates) {one:.2f} ms, "
          f"full batch ({cv.size} candidates) {full:.2f} ms "
          f"-> 20 Hz budget 50 ms {'OK' if full < 30 else 'TIGHT'}")
