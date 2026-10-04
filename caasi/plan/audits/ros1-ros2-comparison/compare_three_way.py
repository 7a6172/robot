#!/usr/bin/env python3
"""Three-way behavioral equivalence comparison: ROS1-reference vs ROS2-reference vs caasi-ROS2.

Usage:
    compare_three_way.py --ros1 <A logs> --ros2 <B logs> --caasi <C logs>

Reads the structured JSON emitted by the six harnesses, applies the DECLARED
per-test rule (exact / 0-ULP / declared tolerance), and emits one compact
machine-readable record per behavior. Nothing here changes the tests, inputs or
tolerances used for the original A<->B comparison.

TEST RULES (declared for A<->B previously and reused unchanged)
--------------------------------------------------------------
1  cmd_vel gating/mode/emergency : exact on discrete outcomes, 0 ULP on values
2  odometry/twist                : exact on frame ids, 0 ULP on values
3  obstacle grid                 : exact, 0 ULP on finite cells; +inf and the
                                   ROS 2 probe's null both mean "no return"
4  TF forward kinematics         : 1e-12 on translation and quaternion (declared)
5  laserscan_multi_merger        : exact structure + 0 ULP on all numerics
6  global planner algorithm      : symmetric Hausdorff <= 1 grid cell (0.05 m),
                                   declared before results were seen

Exit code is 0 when every behavior satisfies its rule on all three pairings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import sys

CELL = 0.05          # planner grid resolution (m)
TF_TOL = 1e-12       # Test 4 declared tolerance
NUM_RECORD_VERSION = 1


# --------------------------------------------------------------------------- io
def load_json_block(path: str):
    with open(path, encoding="utf-8", errors="replace") as fh:
        txt = fh.read()
    m = re.search(r"###JSON_START###(.*?)###JSON_END###", txt, re.S)
    if not m:
        raise SystemExit(f"no structured JSON block found in {path}")
    return json.loads(m.group(1))


def fhash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def ulp(a, b):
    if a is None and b is None:
        return 0
    if a is None or b is None:
        return None
    if isinstance(a, float) and math.isinf(a):
        return 0 if (isinstance(b, float) and math.isinf(b)) else None
    return abs(struct.unpack(">q", struct.pack(">d", float(a)))[0]
               - struct.unpack(">q", struct.pack(">d", float(b)))[0])


def bits_eq(a, b) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return struct.pack(">d", float(a)) == struct.pack(">d", float(b))


# ------------------------------------------------------------------ test rules
def rule_cmd_vel(A, B):
    """Test 1: exact on published/discrete, 0 ULP on forwarded values."""
    ca = {c["name"]: c for c in A["test_A_cmd_vel"]["cases"]}
    cb = {c["name"]: c for c in B["test_A_cmd_vel"]["cases"]}
    if set(ca) != set(cb):
        return False, "case set differs"
    worst = 0
    for n in ca:
        if ca[n]["published"] != cb[n]["published"]:
            return False, f"{n}: published differs"
        oa, ob = ca[n]["output"], cb[n]["output"]
        if (oa is None) != (ob is None):
            return False, f"{n}: output presence differs"
        if oa and ob:
            for k in ("vx", "wz"):
                d = ulp(oa[k], ob[k])
                if d is None:
                    return False, f"{n}.{k}: incomparable"
                worst = max(worst, d)
    if A["test_A_cmd_vel"]["services_available"] != B["test_A_cmd_vel"]["services_available"]:
        return False, "service availability differs"
    for k in ("mode_service_response_manual_false", "stop_service_response_enable_true",
              "stop_service_response_enable_false"):
        if A["test_A_cmd_vel"].get(k) != B["test_A_cmd_vel"].get(k):
            return False, f"service response {k} differs"
    return True, f"max {worst} ULP"


def rule_odom(A, B):
    """Test 2: exact frame ids, 0 ULP on values."""
    a, b = A["test_B_odom"], B["test_B_odom"]
    worst = 0
    for key in ("odom", "twist"):
        x, y = a.get(key), b.get(key)
        if (x is None) != (y is None):
            return False, f"{key} presence differs"
        if x is None:
            continue
        if x["frame_id"] != y["frame_id"]:
            return False, f"{key} frame_id differs"
        for f, v in x.items():
            if f == "frame_id":
                continue
            d = ulp(v, y[f])
            if d is None:
                return False, f"{key}.{f} incomparable"
            worst = max(worst, d)
    return True, f"max {worst} ULP"


def _cells(o):
    """Normalize: ROS 1 emits Infinity; the ROS 2 probe serializes it as null."""
    if o is None:
        return None
    def cl(seq):
        return [None if (v is None or (isinstance(v, float) and math.isinf(v))) else v
                for v in seq]
    return {"size": o["size"],
            **{k: cl(o[k]) for k in ("obstacle_forward", "obstacle_backward",
                                     "obstacle_left", "obstacle_right")}}


def rule_obstacle(A, B):
    """Test 3: exact, 0 ULP on finite cells."""
    a = _cells(A["test_C_obstacle"]["output"])
    b = _cells(B["test_C_obstacle"]["output"])
    if (a is None) != (b is None):
        return False, "output presence differs"
    if a is None:
        return True, "both absent"
    if a["size"] != b["size"]:
        return False, "grid size differs"
    worst = 0
    for k in ("obstacle_forward", "obstacle_backward", "obstacle_left", "obstacle_right"):
        if len(a[k]) != len(b[k]):
            return False, f"{k} length differs"
        for i, (x, y) in enumerate(zip(a[k], b[k])):
            d = ulp(x, y)
            if d is None:
                return False, f"{k}[{i}] incomparable"
            worst = max(worst, d)
    return True, f"max {worst} ULP"


def rule_tf(A, B):
    """Test 4: 1e-12 on translation and quaternion."""
    worst = 0.0
    both_bits = True
    for f in A["transforms"]:
        ta, tb = A["transforms"][f], B["transforms"].get(f)
        if tb is None:
            return False, f"{f}: missing"
        if "error" in ta or "error" in tb:
            if ta.get("error") != tb.get("error"):
                return False, f"{f}: error mismatch"
            continue
        for k in ("t", "q"):
            for p, q in zip(ta[k], tb[k]):
                worst = max(worst, abs(float(p) - float(q)))
                if not bits_eq(p, q):
                    both_bits = False
    ok = worst <= TF_TOL
    return ok, f"max {worst:.3e} m, bit-identical={both_bits}"


def rule_merger(A, B):
    """Test 5: exact structure and 0 ULP on all numerics."""
    oa, ob = A["output"], B["output"]
    if (oa is None) != (ob is None):
        return False, "output presence differs"
    if oa is None:
        return True, "both absent"
    if A["params"] != B["params"] or A["input"] != B["input"]:
        return False, "params/input differ"
    for k in ("frame_id", "num_ranges"):
        if oa[k] != ob[k]:
            return False, f"{k} differs"
    for k in ("angle_min", "angle_max", "angle_increment", "range_min", "range_max"):
        if not bits_eq(oa[k], ob[k]):
            return False, f"{k} not bit-identical"
    fa, fb = oa["finite_ranges"], ob["finite_ranges"]
    if len(fa) != len(fb):
        return False, "finite return count differs"
    for i, (x, y) in enumerate(zip(fa, fb)):
        if x["index"] != y["index"]:
            return False, f"return[{i}] index differs"
        for k in ("angle", "range"):
            if not bits_eq(x[k], y[k]):
                return False, f"return[{i}].{k} not bit-identical"
    return True, "bit-identical"


def _poly_dist(pt, poly):
    best = float("inf")
    for i in range(len(poly) - 1):
        x0, y0 = poly[i]
        x1, y1 = poly[i + 1]
        dx, dy = x1 - x0, y1 - y0
        l2 = dx * dx + dy * dy
        t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((pt[0] - x0) * dx + (pt[1] - y0) * dy) / l2))
        best = min(best, math.hypot(pt[0] - (x0 + t * dx), pt[1] - (y0 + t * dy)))
    return best


def _hausdorff(pa, pb):
    return max(max(_poly_dist(p, pb) for p in pa), max(_poly_dist(p, pa) for p in pb))


def rule_planner(A, B):
    """Test 6: symmetric Hausdorff <= 1 grid cell, plus exact success flag."""
    worst = 0.0
    for name in A["results"]:
        ra, rb = A["results"][name], B["results"].get(name)
        if rb is None:
            return False, f"{name}: missing"
        if ra["success"] != rb["success"]:
            return False, f"{name}: success flag differs"
        h = _hausdorff(ra["plan"], rb["plan"])
        worst = max(worst, h)
    return worst <= CELL, f"max Hausdorff {worst:.4e} m ({worst/CELL:.3f} cells)"


TESTS = [
    ("1_cmd_vel",        "cmd_vel gating / mode / emergency", "test_A_cmd_vel",    rule_cmd_vel,  "exact / 0 ULP"),
    ("2_odometry",       "odometry / twist transform",        "test_B_odom",       rule_odom,     "exact / 0 ULP"),
    ("3_obstacle_grid",  "obstacle grid from LaserScan",      "test_C_obstacle",   rule_obstacle, "exact / 0 ULP"),
    ("4_tf",             "TF forward kinematics",             "transforms",        rule_tf,       f"{TF_TOL}"),
    ("5_scan_merger",    "laserscan_multi_merger",            "output",            rule_merger,   "exact / 0 ULP"),
    ("6_planner",        "global planner algorithm",          "results",           rule_planner,  f"<= {CELL} m (1 cell)"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ros1", required=True, help="ROS1-reference result file (test 1-3)")
    ap.add_argument("--ros2", required=True, help="ROS2-reference result file")
    ap.add_argument("--caasi", required=True, help="caasi-ROS2 result file")
    ap.add_argument("--test", required=True,
                    choices=[t[0] for t in TESTS], help="which behavior to compare")
    ap.add_argument("--json", action="store_true", help="emit the compact record as JSON")
    args = ap.parse_args()

    name, subject, _key, rule, tol = next(t for t in TESTS if t[0] == args.test)

    A = load_json_block(args.ros1)
    B = load_json_block(args.ros2)
    C = load_json_block(args.caasi)

    pairs = [("ROS1-reference|ROS2-reference", A, B),
             ("ROS2-reference|caasi-ROS2", B, C),
             ("ROS1-reference|caasi-ROS2", A, C)]

    record = {
        "record_version": NUM_RECORD_VERSION,
        "test": name,
        "subject": subject,
        "tolerance": tol,
        "inputs": {
            "ROS1-reference": fhash(A),
            "ROS2-reference": fhash(B),
            "caasi-ROS2": fhash(C),
        },
        "pairings": {},
    }
    all_ok = True
    for label, x, y in pairs:
        ok, detail = rule(x, y)
        record["pairings"][label] = {"pass": bool(ok), "detail": detail}
        all_ok = all_ok and ok
    record["result"] = "PASS" if all_ok else "FAIL"

    if args.json:
        print(json.dumps(record, indent=2))
    else:
        print(f"{name:18} {subject:36} tol={tol}")
        for label, v in record["pairings"].items():
            print(f"   {label:32} {'PASS' if v['pass'] else 'FAIL':4}  {v['detail']}")
        print(f"   -> {record['result']}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
