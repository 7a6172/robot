#!/usr/bin/env python3
"""Compare ROS1 vs ROS2 openmover_msgs definitions field-by-field.

Names differ by convention (ROS1 snake_case -> ROS2 PascalCase), so map by
normalized name and report field-level differences.
"""
import pathlib
import re

ROOT = pathlib.Path("/home/zar/Documents/phd/robot")
ROS1 = ROOT / "openmover_robot/openmover_ws/src/openmover_msgs"
ROS2 = ROOT / "openmover_ws/src/openmover_msgs"


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def collect(base: pathlib.Path):
    out = {}
    for kind in ("msg", "srv"):
        for f in sorted((base / kind).rglob("*")):
            if f.suffix not in (".msg", ".srv"):
                continue
            out[(kind, norm(f.stem))] = f
    return out


def structure(path: pathlib.Path):
    """Return the non-comment, non-blank structural lines."""
    lines = []
    for ln in path.read_text(errors="replace").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(s)
    return lines


a, b = collect(ROS1), collect(ROS2)

print("=" * 78)
print("openmover_msgs: ROS1 vs ROS2")
print("=" * 78)
only1 = sorted(set(a) - set(b))
only2 = sorted(set(b) - set(a))
print(f"ROS1 definitions: {len(a)}   ROS2 definitions: {len(b)}")
print(f"only in ROS1: {only1}")
print(f"only in ROS2: {only2}")
print()

for key in sorted(set(a) & set(b)):
    l1, l2 = structure(a[key]), structure(b[key])
    status = "IDENTICAL fields" if l1 == l2 else "DIFFERS"
    print(f"--- {key[0]}/{key[1]}: {a[key].name}  vs  {b[key].name}  [{status}]")
    if l1 != l2:
        print(f"    ROS1 ({len(l1)} lines):")
        for x in l1:
            print(f"       {x}")
        print(f"    ROS2 ({len(l2)} lines):")
        for x in l2:
            print(f"       {x}")
