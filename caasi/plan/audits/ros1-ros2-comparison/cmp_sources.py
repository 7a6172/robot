#!/usr/bin/env python3
"""Quantify source-level correspondence between ROS1 and ROS2 openmover packages.

Distinguishes: identical content, present-but-modified, present-only-in-ROS1,
present-only-in-ROS2.
"""
import hashlib
import pathlib

ROOT = pathlib.Path("/home/zar/Documents/phd/robot")
R1 = ROOT / "openmover_robot/openmover_ws/src/openmover"
R2 = ROOT / "openmover_ws/src/openmover"

SKIP_DIRS = {"build", "devel", "install", "__pycache__", ".git"}
EXTS = {".cpp", ".h", ".hpp", ".py", ".launch", ".urdf", ".world", ".xml", ".txt", ".yaml", ".cfg"}


def scan(base: pathlib.Path):
    out = {}
    for f in base.rglob("*"):
        if not f.is_file() or f.suffix not in EXTS:
            continue
        if any(p in SKIP_DIRS for p in f.parts):
            continue
        rel = f.relative_to(base)
        out[str(rel)] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


a, b = scan(R1), scan(R2)

identical = [k for k in a if k in b and a[k] == b[k]]
modified = [k for k in a if k in b and a[k] != b[k]]
only1 = sorted(set(a) - set(b))
only2 = sorted(set(b) - set(a))

print("=" * 78)
print("openmover package: ROS1 vs ROS2 source correspondence")
print("=" * 78)
print(f"ROS1 files: {len(a)}   ROS2 files: {len(b)}")
print()
print(f"byte-identical:            {len(identical)}")
print(f"present in both, MODIFIED: {len(modified)}")
print(f"only in ROS1:              {len(only1)}")
print(f"only in ROS2:              {len(only2)}")
print()

print("--- byte-identical files (ROS1 == ROS2) ---")
for k in sorted(identical):
    print(f"   {k}")
print()

print("--- modified files ---")
for k in sorted(modified):
    print(f"   {k}")
print()

print("--- only in ROS1 ---")
for k in only1:
    print(f"   {k}")
print()

print("--- only in ROS2 (port additions) ---")
for k in only2:
    print(f"   {k}")
