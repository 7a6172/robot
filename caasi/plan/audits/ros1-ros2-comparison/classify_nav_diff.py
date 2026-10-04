#!/usr/bin/env python3
"""Classify the nature of changes in the navigation algorithm core.

For each modified file, report whether the ONLY changes are ROS 1 -> ROS 2 API
translations (ros::->rclcpp::, ROS_*->RCLCPP_*, node handle/param plumbing),
versus changes to algorithmic logic.
"""
import difflib
import pathlib
import re

ROOT = pathlib.Path("/home/zar/Documents/phd/robot")
R1 = ROOT / "openmover_robot/openmover_ws/src/openmover"
R2 = ROOT / "openmover_ws/src/openmover"

# ROS 1 -> ROS 2 API translation patterns
TRANSLATION_PATTERNS = [
    (re.compile(r"\bros::"), "ros:: -> rclcpp::"),
    (re.compile(r"\bROS_(INFO|WARN|ERROR|DEBUG|FATAL)\b"), "ROS_* -> RCLCPP_*"),
    (re.compile(r"\bRCLCPP_(INFO|WARN|ERROR|DEBUG|FATAL)\b"), "RCLCPP_* (target side)"),
    (re.compile(r"\bnh\b|node_handle|NodeHandle"), "node handle plumbing"),
    (re.compile(r"\bparam\b|\bgetParam\b|\bparam<"), "parameter access"),
    (re.compile(r"nav_msgs::|geometry_msgs::|sensor_msgs::"), "message namespaces"),
    (re.compile(r"\bros::Time\b|\bnow\(\)"), "time API"),
    (re.compile(r"#include\s*[<\"](ros/|rclcpp)"), "ROS headers"),
    (re.compile(r"\bnh_|\bn_\.|node_handle_"), "member node handles"),
]


def changed_lines(p1: pathlib.Path, p2: pathlib.Path):
    a = p1.read_text(errors="replace").splitlines()
    b = p2.read_text(errors="replace").splitlines()
    sm = difflib.SequenceMatcher(None, a, b)
    changed = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete", "insert"):
            for ln in a[i1:i2]:
                changed.append(("-", ln))
            for ln in b[j1:j2]:
                changed.append(("+", ln))
    return changed


FILES = [
    "src/navigation/utils/global_planner/dijkstra.cpp",
    "src/navigation/utils/global_planner/gradient_path.cpp",
    "src/navigation/utils/global_planner/planner.cpp",
    "src/navigation/utils/global_planner/quadratic_calculator.cpp",
    "src/navigation/utils/global_planner/orientation_filter.cpp",
    "src/navigation/utils/global_planner/polyline_generation.cpp",
    "src/navigation/utils/global_planner/planner_with_costmap.cpp",
    "src/navigation/utils/global_planner/backend_optimization.cpp",
    "src/navigation/utils/local_planner/path_follower.cpp",
    "src/navigation/utils/local_planner/mover.cpp",
    "src/navigation/utils/controllers.cpp",
    "src/navigation/utils/math_utils.cpp",
]

print(f"{'file':58} {'chg':>5} {'API':>5} {'other':>6}  verdict")
print("-" * 100)
for rel in FILES:
    p1, p2 = R1 / rel, R2 / rel
    if not (p1.exists() and p2.exists()):
        print(f"{rel:58}  MISSING")
        continue
    ch = changed_lines(p1, p2)
    api = 0
    other = []
    for _sign, ln in ch:
        s = ln.strip()
        if not s or s.startswith("//"):
            continue
        if any(p.search(s) for p, _ in TRANSLATION_PATTERNS):
            api += 1
        else:
            other.append(ln)
    total = api + len(other)
    verdict = "API translation only" if not other else f"{len(other)} non-API line(s)"
    print(f"{rel:58} {total:>5} {api:>5} {len(other):>6}  {verdict}")
    for ln in other[:6]:
        print(f"{'':58}      | {ln.strip()[:70]}")
