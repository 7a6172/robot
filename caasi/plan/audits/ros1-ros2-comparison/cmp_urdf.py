#!/usr/bin/env python3
"""Numerically compare ROS1 vs ROS2 OpenMover URDF robot models.

Focus on physical/kinematic parameters that define the robot itself, separate
from simulator-plugin differences.
"""
import pathlib
import re
import xml.etree.ElementTree as ET

ROOT = pathlib.Path("/home/zar/Documents/phd/robot")
PAIRS = [
    ("robot_description.urdf",
     ROOT / "openmover_robot/openmover_ws/src/openmover/urdf/robot_description.urdf",
     ROOT / "openmover_ws/src/openmover/urdf/robot_description.urdf"),
]


def parse(path):
    return ET.parse(path).getroot()


def links(root):
    return [e.get("name") for e in root.findall("link")]


def joints(root):
    out = {}
    for j in root.findall("joint"):
        name = j.get("name")
        out[name] = {
            "type": j.get("type"),
            "parent": (j.find("parent").get("link") if j.find("parent") is not None else None),
            "child": (j.find("child").get("link") if j.find("child") is not None else None),
            "origin": (j.find("origin").get("xyz") if j.find("origin") is not None else None),
            "axis": (j.find("axis").get("xyz") if j.find("axis") is not None else None),
            "limit": (
                {k: v for k, v in j.find("limit").attrib.items()}
                if j.find("limit") is not None else None
            ),
        }
    return out


for label, p1, p2 in PAIRS:
    r1, r2 = parse(p1), parse(p2)
    l1, l2 = links(r1), links(r2)
    j1, j2 = joints(r1), joints(r2)

    print("=" * 78)
    print(f"{label}: ROS1 vs ROS2")
    print("=" * 78)

    print(f"link count:  ROS1={len(l1)}  ROS2={len(l2)}")
    print(f"  only ROS1: {sorted(set(l1) - set(l2))}")
    print(f"  only ROS2: {sorted(set(l2) - set(l1))}")
    print()

    print(f"joint count: ROS1={len(j1)}  ROS2={len(j2)}")
    print(f"  only ROS1: {sorted(set(j1) - set(j2))}")
    print(f"  only ROS2: {sorted(set(j2) - set(j1))}")
    print()

    print("--- per-joint comparison (shared joints) ---")
    diffs = 0
    for name in sorted(set(j1) & set(j2)):
        a, b = j1[name], j2[name]
        if a != b:
            diffs += 1
            print(f"  DIFFERS: {name}")
            for k in a:
                if a[k] != b[k]:
                    print(f"     {k}: ROS1={a[k]!r}  ROS2={b[k]!r}")
    print(f"  shared joints with differences: {diffs}")
