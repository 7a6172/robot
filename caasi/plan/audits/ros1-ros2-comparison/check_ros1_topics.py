#!/usr/bin/env python3
"""Check whether each ROS1-only topic is referenced by real node CODE (C++/Python)
rather than only by Rviz configs or documentation dumps.

This separates genuine interface gaps from visualization/documentation remnants.
"""
import pathlib
import re

ROOT = pathlib.Path("/home/zar/Documents/phd/robot")
R1 = ROOT / "openmover_robot"

TOPICS = [
    "openmover/control/joy",
    "openmover/hardware/lidar/scan/dist_diff_to_side",
    "openmover/localization/odom",
    "openmover/localization/ser",
    "openmover/mapping/global_planner/costmap/footprint",
    "openmover/mapping/global_planner/planner/polyline_plan",
    "openmover/mapping/lio/cloud_registered",
    "openmover/mapping/lio/feature/corner_both_side",
    "openmover/mapping/lio/feature/corner_one_side",
    "openmover/mapping/lio/feature/surface",
]

CODE_EXT = {".cpp", ".h", ".hpp", ".py"}
DOC_EXT = {".rviz", ".txt", ".md"}

print(f"{'topic':58} {'code hits':>9}  {'viz/doc hits':>12}  verdict")
print("-" * 110)
for t in TOPICS:
    code, doc = [], []
    for f in R1.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix not in CODE_EXT | DOC_EXT:
            continue
        try:
            txt = f.read_text(errors="replace")
        except OSError:
            continue
        if t in txt:
            (code if f.suffix in CODE_EXT else doc).append(f.relative_to(R1))
    verdict = "REAL CODE REFERENCE" if code else "visualization/doc only"
    print(f"{t:58} {len(code):>9}  {len(doc):>12}  {verdict}")
    for c in code[:3]:
        print(f"{'':58}    code: {c}")
