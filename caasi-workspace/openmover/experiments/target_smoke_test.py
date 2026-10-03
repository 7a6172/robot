#!/usr/bin/env python3
import os
import sys
import time
import subprocess

print("[SMOKE] Starting target smoke test...")
print(f"[SMOKE] PID: {os.getpid()}, PGID: {os.getpgrp()}")
print(f"[SMOKE] CAASI_PROJECT_ROOT: {os.environ.get('CAASI_PROJECT_ROOT')}")
print(f"[SMOKE] ROS_DISTRO: {os.environ.get('ROS_DISTRO')}")

# Verify ROS2 environment and built packages
try:
    import rclpy
    print("[SMOKE] rclpy import successful")
except ImportError as e:
    print(f"[SMOKE] rclpy import failed: {e}")

try:
    import openmover_msgs.msg
    print("[SMOKE] openmover_msgs import successful")
except ImportError as e:
    print(f"[SMOKE] openmover_msgs import failed: {e}")

# Spawn child process in same process group to test process group lifecycle
child = subprocess.Popen(["sleep", "120"])
print(f"[SMOKE] CHILD_PID: {child.pid}")
sys.stdout.flush()

for i in range(120):
    time.sleep(1)
    if i % 5 == 0:
        print(f"[SMOKE] Heartbeat step {i}/120 (PID {os.getpid()}, child {child.pid})")
        sys.stdout.flush()

print("[SMOKE] Finished naturally")
