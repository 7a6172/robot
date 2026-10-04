#!/usr/bin/env python3
"""Extract and compare hardware parameter VALUES between ROS 1 and ROS 2 configs.

ROS 2 restructures the flat ROS 1 YAML into node-scoped parameter files, so a
structural diff is misleading. This walks both trees and compares the actual
(key, value) pairs found anywhere in the file.
"""
import pathlib
import yaml

ROOT = pathlib.Path("/home/zar/Documents/phd/robot")
F1 = ROOT / "openmover_robot/config/hardwares/hardwares.yaml"
F2 = ROOT / "openmover_ws/src/openmover/config_defaults/hardwares.yaml"
F3 = ROOT / "openmover_robot/config/modules/modules.yaml"
F4 = ROOT / "openmover_ws/src/openmover/config_defaults/modules.yaml"


def flatten(obj, prefix=""):
    """Flatten nested dicts/lists into {dotted_key: value}."""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        out[prefix] = obj  # keep lists atomic (footprint etc.)
    else:
        out[prefix] = obj
    return out


def values_only(d):
    """Map leaf value -> set of leaf key names, ignoring key paths.

    ROS 2 renames/renests keys, so compare on the VALUE level to detect semantic
    drift in the numbers that actually drive behavior.
    """
    out = {}
    for k, v in d.items():
        key = repr(v)
        out.setdefault(key, set()).add(k.split(".")[-1])
    return out


for label, p1, p2 in [
    ("hardwares.yaml", F1, F2),
    ("modules.yaml", F3, F4),
]:
    if not p2.exists():
        print(f"### {label}: ROS2 counterpart missing ({p2})")
        print()
        continue

    d1 = flatten(yaml.safe_load(p1.read_text()))
    d2 = flatten(yaml.safe_load(p2.read_text()))
    v1, v2 = values_only(d1), values_only(d2)

    print("=" * 78)
    print(f"{label}: ROS1 ({len(d1)} leaves) vs ROS2 ({len(d2)} leaves)")
    print("=" * 78)

    only1 = {k: v for k, v in v1.items() if k not in v2}
    only2 = {k: v for k, v in v2.items() if k not in v1}

    print(f"values present in BOTH: {len(set(v1) & set(v2))}")
    print()
    print("--- values ONLY in ROS1 (potential dropped parameters) ---")
    for val, keys in sorted(only1.items()):
        # ignore trivial/structural values
        if val in ("''", "None", "{}", "[]"):
            continue
        print(f"   {val:38} keys={sorted(keys)}")
    print()
    print("--- values ONLY in ROS2 (new/changed parameters) ---")
    for val, keys in sorted(only2.items()):
        if val in ("''", "None", "{}", "[]"):
            continue
        print(f"   {val:38} keys={sorted(keys)}")
    print()
