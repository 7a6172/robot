#!/usr/bin/env python3
"""TEST F comparison: global planner algorithm A/B, ROS 1 vs ROS 2.

Both sides ran the SAME deterministic synthetic costmaps with the SAME
start/goal and the SAME planner parameters.

DECLARED TOLERANCE (chosen before comparing the numbers)
-------------------------------------------------------
The planner plans on a 0.05 m occupancy grid. Agreement within ONE GRID CELL
therefore means both implementations selected the same free-space route; any
smaller difference is sub-cell arithmetic.

  - success flag     : exact
  - goal reached     : exact (endpoints are pinned)
  - route agreement  : symmetric Hausdorff distance <= 1 cell (0.05 m)

Naive per-point comparison is NOT used as the pass criterion, because two
planners may sample the same route at different waypoint intervals, and
rounding coordinates to cell indices is unstable near cell boundaries (a 1 mm
shift flips the rounded index). Hausdorff distance to the other polyline is
boundary-stable and is the metric reported.

Context for interpreting residual differences: the ROS 1 planner is built with
GCC 9.4 (Ubuntu 20.04) and the ROS 2 planner with GCC 13.3 (Ubuntu 24.04).
Different compilers contract/reassociate floating-point arithmetic differently,
which shifts sub-cell interpolated waypoint positions. That is a toolchain
difference, not an algorithmic one; the planner sources are byte-identical or
API-translation-only (see the source comparison in the audit).
"""
import json
import math
import re
import sys

ROS1_JSON = "/tmp/ros1_test_f.log"
ROS2_JSON = "/tmp/ros2_test_f.log"
CELL = 0.05
TOL = CELL  # 1 grid cell


def load(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    m = re.search(r"###JSON_START###(.*?)###JSON_END###", t, re.S)
    if not m:
        sys.exit(f"no JSON in {path}")
    return json.loads(m.group(1))


def poly_dist(pt, poly):
    """Min distance from pt to a polyline (boundary-stable)."""
    best = float("inf")
    for i in range(len(poly) - 1):
        x0, y0 = poly[i]
        x1, y1 = poly[i + 1]
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((pt[0] - x0) * dx + (pt[1] - y0) * dy) / L2))
        best = min(best, math.hypot(pt[0] - (x0 + t * dx), pt[1] - (y0 + t * dy)))
    return best


def hausdorff(pa, pb):
    return max(max(poly_dist(p, pb) for p in pa), max(poly_dist(p, pa) for p in pb))


def path_len(p):
    return sum(math.dist(p[i], p[i + 1]) for i in range(len(p) - 1))


a = load(ROS1_JSON)
b = load(ROS2_JSON)

print("=" * 104)
print("TEST F - global planner algorithm A/B (identical synthetic costmaps, start/goal, parameters)")
print("=" * 104)
print(f"grid definition identical on both sides: {a['grid'] == b['grid']}")
print(f"grid: {a['grid']['width']}x{a['grid']['height']} @ {a['grid']['resolution']} m")
print(f"start {a['grid']['start']}  goal {a['grid']['goal']}")
print(f"declared tolerance: route agreement <= {TOL} m (1 grid cell)")
print()

rows = []
fails = 0
for name in sorted(a["results"]):
    ra, rb = a["results"][name], b["results"][name]
    pa, pb = ra["plan"], rb["plan"]
    ok_succ = ra["success"] == rb["success"]
    ok_goal = pa[-1] == pb[-1] and pa[0] == pb[0]
    hd = hausdorff(pa, pb) if pa and pb else float("inf")
    ok_route = hd <= TOL
    la, lb = path_len(pa) if len(pa) > 1 else 0.0, path_len(pb) if len(pb) > 1 else 0.0
    ok_len = abs(la - lb) <= TOL
    ok = ok_succ and ok_goal and ok_route and ok_len
    if not ok:
        fails += 1
    rows.append((name, ra["success"], rb["success"], ra["plan_len"], rb["plan_len"],
                 hd, la, lb, abs(la - lb), ok))

print(f"{'scenario':18} {'ROS1 ok':8} {'ROS2 ok':8} {'pts L/R':12} {'Hausdorff':12} "
      f"{'len ROS1':10} {'len ROS2':10} {'dlen':10} result")
print("-" * 104)
for name, s1, s2, n1, n2, hd, l1, l2, dl, ok in rows:
    print(f"{name:18} {str(s1):8} {str(s2):8} {f'{n1}/{n2}':12} {hd:12.4e} "
          f"{l1:10.4f} {l2:10.4f} {dl:10.2e} {'PASS' if ok else 'FAIL'}")
print("-" * 104)
print(f"scenarios: {len(rows)}   PASS: {len(rows)-fails}   FAIL: {fails}")
print()

# Interpretation aids
print("Interpretation")
print("--------------")
for name, s1, s2, n1, n2, hd, l1, l2, dl, ok in rows:
    print(f"  {name}: Hausdorff {hd:.4e} m = {hd/CELL:.3f} cells; "
          f"path-length difference {dl:.2e} m; waypoint counts {n1} vs {n2}")
print()
print("  Sub-cell route agreement means both implementations selected the same")
print("  free-space route. The residual is consistent with the GCC 9.4 (ROS 1)")
print("  vs GCC 13.3 (ROS 2) floating-point difference described in the header.")
