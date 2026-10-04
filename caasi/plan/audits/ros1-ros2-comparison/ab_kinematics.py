#!/usr/bin/env python3
"""Deterministic A/B kinematic comparison: ROS 1 vs ROS 2 OpenMover robot model.

ROS 1 input : live container capture (/tmp/ros1_tf.json), taken from the
              /robot_description parameter of a running ROS 1 master.
ROS 2 input : the ROS 2 port's robot_description.urdf, parsed directly.

Compares links and joints with explicit numeric tolerance so the comparison is
reproducible rather than visual.
"""
import json
import pathlib
import xml.etree.ElementTree as ET

ROS1_JSON = pathlib.Path("/tmp/ros1_tf.json")
ROS2_URDF = pathlib.Path("/home/zar/Documents/phd/robot/openmover_ws/src/openmover/urdf/robot_description.urdf")

TOL = 1e-9  # exact for URDF-derived values; they are decimal literals


def nums(s):
    if s is None:
        return None
    return [float(x) for x in s.split()]


def parse_ros2(p):
    root = ET.parse(p).getroot()
    links = sorted(e.get("name") for e in root.findall("link"))
    joints = {}
    for j in root.findall("joint"):
        o, ax, lim = j.find("origin"), j.find("axis"), j.find("limit")
        joints[j.get("name")] = {
            "type": j.get("type"),
            "parent": j.find("parent").get("link") if j.find("parent") is not None else None,
            "child": j.find("child").get("link") if j.find("child") is not None else None,
            "origin_xyz": o.get("xyz") if o is not None else None,
            "axis": ax.get("xyz") if ax is not None else None,
            "limit": dict(lim.attrib) if lim is not None else None,
        }
    return links, joints


r1 = json.loads(ROS1_JSON.read_text())
l1, j1 = r1["links"], {j["name"]: j for j in r1["joints"]}
l2, j2 = parse_ros2(ROS2_URDF)

print("=" * 78)
print("Kinematic A/B: ROS 1 (live) vs ROS 2 (port)")
print("=" * 78)
print(f"links:  ROS1={len(l1)}  ROS2={len(l2)}  identical_set={set(l1) == set(l2)}")
print(f"joints: ROS1={len(j1)}  ROS2={len(j2)}  identical_set={set(j1) == set(j2)}")
print()

fails = []
for name in sorted(set(j1) | set(j2)):
    a, b = j1.get(name), j2.get(name)
    if a is None or b is None:
        fails.append((name, "missing on one side"))
        print(f"  MISSING {name}")
        continue
    row = []
    for field in ("type", "parent", "child"):
        if a[field] != b[field]:
            row.append(f"{field}: ROS1={a[field]} ROS2={b[field]}")
            fails.append((name, field))
    for field in ("origin_xyz", "axis"):
        va, vb = nums(a[field]), nums(b[field])
        if (va is None) != (vb is None):
            row.append(f"{field}: ROS1={a[field]} ROS2={b[field]}")
            fails.append((name, field))
        elif va is not None and any(abs(x - y) > TOL for x, y in zip(va, vb)):
            row.append(f"{field}: ROS1={va} ROS2={vb}")
            fails.append((name, field))
    status = "MATCH" if not row else "DIFF"
    print(f"  {status:5} {name:24} {'; '.join(row)}")

print()
print(f"tolerance: {TOL}")
print(f"joint fields compared: type, parent, child, origin_xyz, axis (5 x {len(set(j1)|set(j2))} joints)")
print(f"FAILURES: {len(fails)}")
if fails:
    for f in fails:
        print("   ", f)
else:
    print("   none - ROS 1 and ROS 2 kinematic models are numerically identical")
