#!/usr/bin/env python3
"""Per-component topic/service surface comparison: ROS1 vs ROS2 node sources.

For each handler, extract the openmover/* string literals (topics, services,
parameters) used in code and compare the sets.
"""
import pathlib
import re

ROOT = pathlib.Path("/home/zar/Documents/phd/robot")
R1 = ROOT / "openmover_robot/openmover_ws/src/openmover"
R2 = ROOT / "openmover_ws/src/openmover"

PAT = re.compile(r'"(/?openmover/[A-Za-z0-9_/]+)"')

COMPONENTS = {
    "navigation_handler": "src/navigation/navigation/navigation_handler.cpp",
    "obstacle_handler": "src/navigation/obstacle/obstacle_handler.cpp",
    "localization_handler": "src/localization/localization_handler.cpp",
    "loc_confidence_handler": "src/localization/localization_confidence_handler.cpp",
    "motor_handler": "src/driver/motor_handler.cpp",
    "io_board_handler": "src/driver/io_board_handler.cpp",
    "simulation_handler": "src/driver/simulation_handler.cpp",
    "teleop_handler": "src/teleop/teleop_handler.cpp",
    "hal.py": "scripts/hal/hal.py",
    "func_mode_server": "scripts/server/func_mode_server_handler.py",
    "nav_area_server": "scripts/server/nav_area_server_handler.py",
    "cartographer_server": "scripts/server/cartographer_server_handler.py",
    "workload.py": "scripts/workload/workload.py",
}

print(f"{'component':24} {'R1':>4} {'R2':>4} {'both':>5}  missing-in-ROS2 / added-in-ROS2")
print("-" * 110)
for name, rel in COMPONENTS.items():
    p1, p2 = R1 / rel, R2 / rel
    if not p1.exists():
        print(f"{name:24}  (ROS1 file missing)")
        continue
    s1 = set(PAT.findall(p1.read_text(errors="replace")))
    if not p2.exists():
        print(f"{name:24} {len(s1):>4} {'--':>4} {'--':>5}  ROS2 FILE MISSING")
        continue
    s2 = set(PAT.findall(p2.read_text(errors="replace")))

    def norm(s):
        return s.lstrip("/")
    n1, n2 = {norm(x) for x in s1}, {norm(x) for x in s2}
    miss = sorted(n1 - n2)
    add = sorted(n2 - n1)
    print(f"{name:24} {len(n1):>4} {len(n2):>4} {len(n1 & n2):>5}  "
          f"missing={miss if miss else '-'}  added={add if add else '-'}")
