#!/usr/bin/env python3
"""Compare ROS 1 vs ROS 2 behavioral test JSON for Tests A/B/C.

Tolerances are declared BEFORE comparison and printed with the result:
  - discrete/boolean outcomes : exact equality (no tolerance)
  - command velocities        : 0 ULPs (bit-identical float comparison)
  - odometry/pose values      : 0 ULPs
  - obstacle grid distances   : 0 ULPs, with infinity treated as a value
"""
import json
import math
import re
import struct
import sys


def load(path, tag):
    txt = open(path, encoding="utf-8", errors="replace").read()
    m = re.search(r"###JSON_START###(.*?)###JSON_END###", txt, re.S)
    if not m:
        sys.exit(f"no JSON block in {path}")
    return json.loads(m.group(1))


def ulp_diff(a, b):
    """Exact float comparison: 0 means bit-identical."""
    if a is None and b is None:
        return 0
    if a is None or b is None:
        return None
    if isinstance(a, float) and math.isinf(a):
        return 0 if (isinstance(b, float) and math.isinf(b) and (a > 0) == (b > 0)) else None
    ba = struct.pack(">d", float(a))
    bb = struct.pack(">d", float(b))
    if ba == bb:
        return 0
    ia = struct.unpack(">q", ba)[0]
    ib = struct.unpack(">q", bb)[0]
    return abs(ia - ib)


r1 = load("/tmp/ros1_beh.log", "ros1")
r2 = load("/tmp/ros2_beh.log", "ros2")

ROWS = []


def row(test, metric, v1, v2, tol, ok):
    ROWS.append((test, metric, v1, v2, tol, ok))


# ---------------- TEST A: cmd_vel response ----------------
A1, A2 = r1["test_A_cmd_vel"], r2["test_A_cmd_vel"]

row("A", "services available (cmd_vel_mode, stop)",
    (A1["services_available"]["cmd_vel_mode"], A1["services_available"]["stop"]),
    (A2["services_available"]["cmd_vel_mode"], A2["services_available"]["stop"]),
    "exact", A1["services_available"] == A2["services_available"])

row("A", "initial manual mode", A1["initial_manual_mode"], A2["initial_manual_mode"],
    "exact", A1["initial_manual_mode"] == A2["initial_manual_mode"])

for k in ("mode_service_response_manual_false",
          "stop_service_response_enable_true",
          "stop_service_response_enable_false"):
    row("A", f"service response {k.split('_')[-1]}", A1.get(k), A2.get(k),
        "exact", A1.get(k) == A2.get(k))

a1c = {c["name"]: c for c in A1["cases"]}
a2c = {c["name"]: c for c in A2["cases"]}
row("A", "same case set", sorted(a1c), sorted(a2c), "exact",
    sorted(a1c) == sorted(a2c))

for name in a1c:
    c1, c2 = a1c[name], a2c[name]
    row("A", f"[{name}] published?", c1["published"], c2["published"],
        "exact", c1["published"] == c2["published"])
    o1, o2 = c1["output"], c2["output"]
    if o1 is None or o2 is None:
        row("A", f"[{name}] output", o1, o2, "exact", o1 == o2)
    else:
        d = max(ulp_diff(o1["vx"], o2["vx"]), ulp_diff(o1["wz"], o2["wz"]))
        row("A", f"[{name}] cmd_vel_sim (vx,wz)", (o1["vx"], o1["wz"]),
            (o2["vx"], o2["wz"]), "0 ULP", d == 0)

# ---------------- TEST B: odometry ----------------
B1, B2 = r1["test_B_odom"], r2["test_B_odom"]
row("B", "input identical", B1["input"], B2["input"], "exact", B1["input"] == B2["input"])
for key in ("odom", "twist"):
    v1, v2 = B1.get(key), B2.get(key)
    if v1 is None or v2 is None:
        row("B", f"{key} message", v1, v2, "exact", v1 == v2)
        continue
    row("B", f"{key} frame_id", v1["frame_id"], v2["frame_id"], "exact",
        v1["frame_id"] == v2["frame_id"])
    worst = 0
    for f in v1:
        if f == "frame_id":
            continue
        d = ulp_diff(v1[f], v2[f])
        if d is None or d > worst:
            worst = d if d is not None else 10**9
    row("B", f"{key} numeric fields", {k: v for k, v in v1.items() if k != "frame_id"},
        {k: v for k, v in v2.items() if k != "frame_id"}, "0 ULP", worst == 0)

# ---------------- TEST C: obstacle grid ----------------
C1, C2 = r1["test_C_obstacle"], r2["test_C_obstacle"]
row("C", "input identical", C1["input"], C2["input"], "exact", C1["input"] == C2["input"])
o1, o2 = C1["output"], C2["output"]
if o1 is None or o2 is None:
    row("C", "output present", o1 is not None, o2 is not None, "exact", o1 == o2)
else:
    row("C", "grid size", o1["size"], o2["size"], "exact", o1["size"] == o2["size"])
    for arr in ("obstacle_forward", "obstacle_backward", "obstacle_left", "obstacle_right"):
        a, b = o1[arr], o2[arr]
        # ROS1 emits Infinity; ROS2 probe serialized infinity as null. Normalize.
        na = [None if (isinstance(x, float) and math.isinf(x)) else x for x in a]
        nb = [None if x is None else x for x in b]
        worst = 0
        for x, y in zip(na, nb):
            d = ulp_diff(x, y)
            if d is None:
                worst = 10**9
                break
            worst = max(worst, d)
        row("C", f"{arr} (5 cells)", na, nb, "0 ULP", worst == 0)

# ---------------- print table ----------------
print("=" * 118)
print("BEHAVIORAL EQUIVALENCE: ROS 1 (noetic) vs ROS 2 (jazzy)  — simulator-free message/node tests")
print("=" * 118)
print(f"{'test':5} {'metric':50} {'ROS1':22} {'ROS2':22} {'tol':7} result")
print("-" * 118)
fails = 0
for test, metric, v1, v2, tol, ok in ROWS:
    def fmt(v):
        s = str(v)
        return s if len(s) <= 22 else s[:19] + "..."
    res = "PASS" if ok else "FAIL"
    if not ok:
        fails += 1
    print(f"{test:5} {metric[:50]:50} {fmt(v1):22} {fmt(v2):22} {tol:7} {res}")
print("-" * 118)
print(f"checks: {len(ROWS)}   PASS: {len(ROWS)-fails}   FAIL: {fails}")
