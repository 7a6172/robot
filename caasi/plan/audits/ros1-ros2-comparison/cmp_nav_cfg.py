#!/usr/bin/env python3
"""Compare ROS 1 vs ROS 2 navigation/mapping/costmap configuration VALUES.

ROS 2 wraps everything in `/**:\n  ros__parameters:` and reorganizes some
sections. Compare the actual (dotted_key_tail, value) pairs so restructuring
does not mask real numeric differences.
"""
import pathlib
import yaml

ROOT = pathlib.Path("/home/zar/Documents/phd/robot")
R1 = ROOT / "openmover_robot/config/apps"
R2 = ROOT / "openmover_ws/src/openmover/config_defaults/apps"


def load(path: pathlib.Path):
    return yaml.safe_load(path.read_text())


def flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        out[prefix] = obj
    else:
        out[prefix] = obj
    return out


def strip_ros2(d):
    """Drop the /**/ros__parameters wrapper and any node-name level."""
    if isinstance(d, dict):
        if set(d.keys()) == {"/**"}:
            d = d["/**"]
        if isinstance(d, dict) and set(d.keys()) == {"ros__parameters"}:
            d = d["ros__parameters"]
    return d


for name in ("navigation", "mapping"):
    p1 = R1 / f"{name}/{name}.yaml"
    p2 = R2 / f"{name}/{name}.yaml"
    if not p2.exists():
        print(f"### {name}: ROS2 counterpart missing")
        continue

    f1 = flatten(load(p1))
    f2 = flatten(strip_ros2(load(p2)))

    # Compare by leaf key-name -> value (paths may be reorganized).
    def by_leaf(d):
        m = {}
        for k, v in d.items():
            m.setdefault(k.split(".")[-1], {})[k] = v
        return m

    m1, m2 = by_leaf(f1), by_leaf(f2)

    print("=" * 78)
    print(f"{name}.yaml: ROS1 {len(f1)} leaves vs ROS2 {len(f2)} leaves")
    print("=" * 78)

    matches = differ = 0
    diffs = []
    for k in sorted(set(m1) & set(m2)):
        vals1 = set(map(repr, m1[k].values()))
        vals2 = set(map(repr, m2[k].values()))
        if vals1 == vals2:
            matches += 1
        else:
            differ += 1
            diffs.append((k, sorted(vals1), sorted(vals2)))

    only1 = sorted(set(m1) - set(m2))
    only2 = sorted(set(m2) - set(m1))

    print(f"leaf keys in both: {len(set(m1) & set(m2))}")
    print(f"  values match:    {matches}")
    print(f"  values differ:   {differ}")
    print(f"only in ROS1:      {only1}")
    print(f"only in ROS2:      {only2}")
    if diffs:
        print()
        print("--- differing leaf keys ---")
        for k, v1, v2 in diffs:
            print(f"   {k}: ROS1={v1}  ROS2={v2}")
    print()
