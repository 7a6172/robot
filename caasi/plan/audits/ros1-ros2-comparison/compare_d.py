#!/usr/bin/env python3
"""TEST D comparison: forward kinematics from robot_state_publisher,
ROS 1 vs ROS 2, given identical URDF and identical joint state.

Tolerance: 1e-12 on translation and quaternion components. This is a strict
tolerance deliberately: robot_state_publisher computes FK from the same URDF
in both stacks, so agreement should be at floating-point noise level.
"""
import json
import re
import struct


def load(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    m = re.search(r"###JSON_START###(.*?)###JSON_END###", t, re.S)
    return json.loads(m.group(1))


a = load("/tmp/ros1_test_d.log")
b = load("/tmp/ros2_test_d.log")

TOL = 1e-12
print("=" * 112)
print("TEST D — TF / forward kinematics (robot_state_publisher), identical URDF + identical joint state")
print("=" * 112)
print(f"joint state: {a['joint_state']}")
print(f"parent frame: {a['parent_frame']}")
print()

rows = []
for frame in a["frames_requested"]:
    ta, tb = a["transforms"].get(frame), b["transforms"].get(frame)
    if ta is None or tb is None:
        rows.append((frame, "missing", "-", "-", "FAIL"))
        continue
    if "error" in ta or "error" in tb:
        rows.append((frame, "error", str(ta.get("error"))[:24], str(tb.get("error"))[:24],
                     "FAIL" if ta.get("error") != tb.get("error") else "PASS"))
        continue
    worst = 0.0
    detail = []
    for key in ("t", "q"):
        for i, (x, y) in enumerate(zip(ta[key], tb[key])):
            d = abs(float(x) - float(y))
            worst = max(worst, d)
            if d != 0.0:
                detail.append(f"{key}[{i}] ROS1={x!r} ROS2={y!r} d={d:.3e}")
    # also record whether the doubles are bit-identical
    bit_same = all(
        struct.pack(">d", float(x)) == struct.pack(">d", float(y))
        for key in ("t", "q") for x, y in zip(ta[key], tb[key])
    )
    ok = worst <= TOL
    rows.append((frame, f"{'bit-identical' if bit_same else f'max diff {worst:.3e}'}",
                 str([round(v, 9) for v in ta['t']]), str([round(v, 9) for v in tb['t']]),
                 "PASS" if ok else "FAIL"))
    for d in detail:
        print(f"   diff: {frame} {d}")

print(f"{'frame':24} {'agreement':32} {'ROS1 translation':30} {'ROS2 translation':30} result")
print("-" * 112)
fails = 0
for frame, agree, t1, t2, res in rows:
    if res == "FAIL":
        fails += 1
    print(f"{frame:24} {agree[:32]:32} {t1[:30]:30} {t2[:30]:30} {res}")
print("-" * 112)
print(f"tolerance: {TOL}")
print(f"frames: {len(rows)}   PASS: {len(rows)-fails}   FAIL: {fails}")
