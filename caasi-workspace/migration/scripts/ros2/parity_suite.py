#!/usr/bin/env python3
"""One-pass ROS 2 parity suite: the same measurements taken on the ROS 1 reference.

Runs on the robot with the stack already up (bringup.launch.py hardware:=swjtumover
system_mode:=1), and reports everything in one JSON blob so the comparison with ROS 1 is a
single table rather than a pile of logs.

Phases:
  1. sensor contract   - /scan rate, samples, frame, angles, ranges, invalid distribution
  2. state contract    - /openmover/hardware/odom rate, tf odom->base_link, tf base_link->lidar_link
  3. motion            - only with --motion, and only if the actuation gate is open
Each motion command is bounded and always ends with a zero-velocity stream.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import LaserScan
from geometry_msgs.msg import Twist, PoseWithCovarianceStamped

CMD_TOPIC = "openmover/control/cmd_vel_manual"
ODOM_TOPIC = "openmover/hardware/odom"


def qos_best_effort(depth=10):
    return QoSProfile(depth=depth, reliability=ReliabilityPolicy.BEST_EFFORT)


def sensor_section(node, timeout):
    scans = []
    sub = node.create_subscription(LaserScan, "/scan", scans.append, qos_best_effort())
    start = time.time()
    while len(scans) < 8 and time.time() - start < timeout:
        rclpy.spin_once(node, timeout_sec=0.2)
    node.destroy_subscription(sub)
    if not scans:
        return {"error": "no scan"}
    stamps = [m.header.stamp.sec + m.header.stamp.nanosec * 1e-9 for m in scans]
    deltas = [b - a for a, b in zip(stamps, stamps[1:]) if b > a]
    s = scans[-1]
    return {
        "rate_hz": round(1.0 / statistics.mean(deltas), 3) if deltas else None,
        "samples": len(s.ranges),
        "frame": s.header.frame_id,
        "angle_min": s.angle_min, "angle_max": s.angle_max,
        "angle_increment": s.angle_increment,
        "range_min": s.range_min, "range_max": s.range_max,
        "scan_time": s.scan_time, "time_increment": s.time_increment,
        "valid": sum(1 for r in s.ranges if math.isfinite(r) and s.range_min <= r <= s.range_max),
        "nan": sum(1 for r in s.ranges if math.isnan(r)),
        "inf": sum(1 for r in s.ranges if math.isinf(r)),
        "stamp_minus_wallclock_s": round(stamps[-1] - time.time(), 3),
    }


def odom_rate(node, timeout):
    msgs = []
    sub = node.create_subscription(PoseWithCovarianceStamped, ODOM_TOPIC, msgs.append, 10)
    start = time.time()
    while len(msgs) < 6 and time.time() - start < timeout:
        rclpy.spin_once(node, timeout_sec=0.2)
    node.destroy_subscription(sub)
    if not msgs:
        return {"error": "no odometry"}
    stamps = [m.header.stamp.sec + m.header.stamp.nanosec * 1e-9 for m in msgs]
    deltas = [b - a for a, b in zip(stamps, stamps[1:]) if b > a]
    q = msgs[-1].pose.pose.orientation
    return {
        "rate_hz": round(1.0 / statistics.mean(deltas), 3) if deltas else None,
        "frame": msgs[-1].header.frame_id,
        "quaternion_norm": round(math.sqrt(q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w), 9),
    }


def tf_section(node):
    from tf2_ros import Buffer, TransformListener

    def quat_to_rpy(q):
        roll = math.atan2(2 * (q.w * q.x + q.y * q.z), 1 - 2 * (q.x * q.x + q.y * q.y))
        pitch_arg = 2 * (q.w * q.y - q.z * q.x)
        pitch = math.copysign(math.pi / 2, pitch_arg) if abs(pitch_arg) >= 1 else math.asin(pitch_arg)
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        return [roll, pitch, yaw]

    buf = Buffer()
    _ = TransformListener(buf, node)
    out = {}
    for parent, child in (("base_link", "lidar_link"), ("odom", "base_link")):
        end = time.time() + 10
        while time.time() < end and not buf.can_transform(parent, child, rclpy.time.Time()):
            rclpy.spin_once(node, timeout_sec=0.2)
        try:
            t = buf.lookup_transform(parent, child, rclpy.time.Time())
            tr, rot = t.transform.translation, t.transform.rotation
            out[f"{parent}->{child}"] = {
                "xyz": [round(tr.x, 6), round(tr.y, 6), round(tr.z, 6)],
                "rpy": [round(v, 6) for v in quat_to_rpy(rot)],
            }
        except Exception as exc:
            out[f"{parent}->{child}"] = {"error": type(exc).__name__}
    return out


def motion_section(node, speed, seconds):
    """One bounded move, then the mirror move, with odometry deltas for each."""
    pub = node.create_publisher(Twist, CMD_TOPIC, 2)
    state = {"odom": None}
    sub = node.create_subscription(PoseWithCovarianceStamped, ODOM_TOPIC,
                                   lambda m: state.__setitem__("odom", m), 10)

    def hold(v, length):
        end = time.time() + length
        msg = Twist(); msg.linear.x = v
        while time.time() < end:
            pub.publish(msg)
            rclpy.spin_once(node, timeout_sec=0.02)

    def wait_odom(limit=8.0):
        end = time.time() + limit
        while state["odom"] is None and time.time() < end:
            pub.publish(Twist())
            rclpy.spin_once(node, timeout_sec=0.05)

    def yaw_of(q):
        return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))

    wait_odom()
    hold(0.0, 1.5)
    if state["odom"] is None:
        node.destroy_subscription(sub)
        return {"error": "no odometry; motion not measured"}

    results = {}
    for label, v in (("forward", abs(speed)), ("reverse", -abs(speed))):
        start = state["odom"]
        hold(v, seconds)
        hold(0.0, 2.0)
        end = state["odom"]
        dx = end.pose.pose.position.x - start.pose.pose.position.x
        dy = end.pose.pose.position.y - start.pose.pose.position.y
        dyaw = yaw_of(end.pose.pose.orientation) - yaw_of(start.pose.pose.orientation)
        dyaw = math.atan2(math.sin(dyaw), math.cos(dyaw))
        dist = math.hypot(dx, dy)
        results[label] = {
            "commanded_m": round(abs(v) * seconds, 4),
            "measured_m": round(dist, 4),
            "ratio": round(dist / abs(v * seconds), 4) if v else None,
            "dyaw_rad": round(dyaw, 4),
        }
        hold(0.0, 1.0)
    hold(0.0, 2.0)
    node.destroy_subscription(sub)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--motion", action="store_true",
                    help="also run the bounded motion test (requires the actuation gate open)")
    ap.add_argument("--speed", type=float, default=0.06)
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--out", default="/tmp/ros2_parity_suite.json")
    args = ap.parse_args()

    rclpy.init()
    node = Node("ros2_parity_suite")
    report = {"source": "ros2"}
    try:
        report["sensor"] = sensor_section(node, args.timeout)
        report["odom"] = odom_rate(node, args.timeout)
        report["tf"] = tf_section(node)
        if args.motion:
            report["motion"] = motion_section(node, args.speed, args.seconds)
    finally:
        node.destroy_node()
        rclpy.try_shutdown()

    print(json.dumps(report, indent=2))
    open(args.out, "w").write(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
