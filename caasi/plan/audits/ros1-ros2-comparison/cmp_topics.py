#!/usr/bin/env python3
"""Extract and compare the ROS 1 vs ROS 2 topic/frame interface surface.

Sources of truth:
  ROS 1: launch XML (<remap>, <param> topics, node names) + config YAML topics
  ROS 2: launch.py (parameters/remappings) + config_defaults YAML topics
"""
import pathlib
import re

ROOT = pathlib.Path("/home/zar/Documents/phd/robot")
L1 = ROOT / "openmover_robot/openmover_ws/src/openmover/launch"
L2 = ROOT / "openmover_ws/src/openmover/launch"
C1 = ROOT / "openmover_robot/config"
C2 = ROOT / "openmover_ws/src/openmover/config_defaults"

TOPIC_RE = re.compile(r"openmover/[A-Za-z0-9_/]+")
FRAME_RE = re.compile(r"\b(?:base_link|lidar_link|lidar_forward_link|lidar_rear_link|map|odom)\b")


def gather(paths):
    topics, frames = set(), set()
    for p in paths:
        for f in p.rglob("*"):
            if not f.is_file() or f.suffix not in (".launch", ".py", ".yaml", ".lua", ".rviz"):
                continue
            try:
                t = f.read_text(errors="replace")
            except OSError:
                continue
            topics |= set(TOPIC_RE.findall(t))
            frames |= set(FRAME_RE.findall(t))
    return topics, frames


t1, f1 = gather([L1, C1])
t2, f2 = gather([L2, C2])

# Normalize: ROS2 configs prefix topics with '/', ROS1 mostly does not.
def norm(s):
    return s.strip("/")


n1 = {norm(t) for t in t1}
n2 = {norm(t) for t in t2}

print("=" * 78)
print("Topic interface: ROS1 vs ROS2")
print("=" * 78)
print(f"ROS1 topics: {len(n1)}   ROS2 topics: {len(n2)}")
print(f"common: {len(n1 & n2)}")
print()
print("--- topics ONLY in ROS1 (missing from ROS2) ---")
for t in sorted(n1 - n2):
    print(f"   {t}")
print()
print("--- topics ONLY in ROS2 (new in port) ---")
for t in sorted(n2 - n1):
    print(f"   {t}")
print()

print("=" * 78)
print("TF frames: ROS1 vs ROS2")
print("=" * 78)
print(f"ROS1 frames: {sorted(f1)}")
print(f"ROS2 frames: {sorted(f2)}")
print(f"common: {sorted(f1 & f2)}")
print(f"only ROS1: {sorted(f1 - f2)}")
print(f"only ROS2: {sorted(f2 - f1)}")
