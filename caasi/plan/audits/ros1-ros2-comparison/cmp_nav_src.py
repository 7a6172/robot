#!/usr/bin/env python3
"""Compare the navigation/localization algorithm sources ROS1 vs ROS2.

For files present on both sides, measure how much they differ. Byte-identical
files are strong evidence of a verbatim port; heavily modified files need
individual explanation.
"""
import difflib
import pathlib

ROOT = pathlib.Path("/home/zar/Documents/phd/robot")
R1 = ROOT / "openmover_robot/openmover_ws/src/openmover"
R2 = ROOT / "openmover_ws/src/openmover"

GROUPS = {
    "global_planner": "src/navigation/utils/global_planner",
    "local_planner": "src/navigation/utils/local_planner",
    "controllers": "src/navigation/utils/controllers.cpp",
    "collision_checker": "src/navigation/utils/collision_checker",
    "path_checker": "src/navigation/utils/path_checker",
    "math_utils": "src/navigation/utils/math_utils.cpp",
    "navigation_handler": "src/navigation/navigation/navigation_handler.cpp",
    "obstacle_handler": "src/navigation/obstacle/obstacle_handler.cpp",
    "localization_handler": "src/localization/localization_handler.cpp",
    "loc_confidence": "src/localization/localization_confidence_handler.cpp",
    "likelihood_field": "src/localization/utils/localization_confidence/likelihood_field.cpp",
    "motor_handler": "src/driver/motor_handler.cpp",
    "io_board_handler": "src/driver/io_board_handler.cpp",
    "simulation_handler": "src/driver/simulation_handler.cpp",
    "teleop_handler": "src/teleop/teleop_handler.cpp",
}

print(f"{'component':22} {'ROS1 lines':>10} {'ROS2 lines':>10} {'similarity':>11}  status")
print("-" * 88)

for name, rel in GROUPS.items():
    p1, p2 = R1 / rel, R2 / rel
    # a group may be a directory
    if p1.is_dir():
        f1 = sorted(p1.rglob("*.cpp"))
        l1 = sum(len(f.read_text(errors="replace").splitlines()) for f in f1)
        t1 = "".join(f.read_text(errors="replace") for f in f1)
    elif p1.is_file():
        t1 = p1.read_text(errors="replace")
        l1 = len(t1.splitlines())
    else:
        print(f"{name:22} {'MISSING':>10}")
        continue

    if p2.is_dir():
        f2 = sorted(p2.rglob("*.cpp"))
        l2 = sum(len(f.read_text(errors="replace").splitlines()) for f in f2)
        t2 = "".join(f.read_text(errors="replace") for f in f2)
    elif p2.is_file():
        t2 = p2.read_text(errors="replace")
        l2 = len(t2.splitlines())
    else:
        print(f"{name:22} {l1:>10} {'MISSING':>10}")
        continue

    if t1 == t2:
        sim, status = "100%", "BYTE-IDENTICAL"
    else:
        ratio = difflib.SequenceMatcher(None, t1, t2).ratio()
        sim = f"{ratio*100:.1f}%"
        status = "modified" if ratio < 0.999 else "trivial diff"
    print(f"{name:22} {l1:>10} {l2:>10} {sim:>11}  {status}")
