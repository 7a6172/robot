#!/usr/bin/env python3
"""Extract and compare raw physical parameters from ROS1 vs ROS2 URDF text,
independent of simulator-plugin syntax differences."""
import pathlib
import re

ROOT = pathlib.Path("/home/zar/Documents/phd/robot")
P1 = ROOT / "openmover_robot/openmover_ws/src/openmover/urdf/robot_description.urdf"
P2 = ROOT / "openmover_ws/src/openmover/urdf/robot_description.urdf"


def txt(p):
    return p.read_text(errors="replace")


a, b = txt(P1), txt(P2)

print("=" * 78)
print("Physical parameter comparison (ROS1 vs ROS2 robot_description.urdf)")
print("=" * 78)

# --- wheel separation / diameter, expressed differently by each plugin ---
def find(pat, s):
    m = re.search(pat, s)
    return m.group(1).strip() if m else None

pairs = [
    ("wheel separation", r"<wheelSeparation>([^<]+)", r"<wheel_separation>([^<]+)"),
    ("wheel diameter",   r"<wheelDiameter>([^<]+)",   r"<wheel_radius>([^<]+)"),
    ("wheel torque",     r"<wheelTorque>([^<]+)",     r"<max_wheel_torque>([^<]+)"),
    ("update rate",      r"<updateRate>([^<]+)",      r"<odom_publish_frequency>([^<]+)"),
    ("odometry topic",   r"<odometryTopic>([^<]+)",   r"<odom_topic>([^<]+)"),
]

for label, pa, pb in pairs:
    va, vb = find(pa, a), find(pb, b)
    note = ""
    if label == "wheel diameter" and va and vb:
        d = float(va)
        note = f"  -> ROS1 diameter {d} / 2 = {d/2:.5f}; ROS2 radius {vb}  MATCH={abs(d/2 - float(vb)) < 1e-9}"
    print(f"{label:18} ROS1={va!r:20} ROS2={vb!r:20}{note}")

print()
print("--- LiDAR / sensor blocks ---")
for name, s in (("ROS1", a), ("ROS2", b)):
    print(f"[{name}]")
    for pat in (r"<update_rate>[^<]+", r"<samples>\d+", r"<min_angle>[^<]+",
                r"<max_angle>[^<]+", r"<min_range>[^<]+", r"<max_range>[^<]+",
                r"<resolution>[^<]+", r"<range>[^<]+"):
        for m in re.findall(pat, s):
            print(f"   {m}")
    print()

print("--- <inertial> / mass values ---")
for name, s in (("ROS1", a), ("ROS2", b)):
    masses = re.findall(r"<mass value=\"([^\"]+)\"", s)
    print(f"[{name}] masses: {masses}")
