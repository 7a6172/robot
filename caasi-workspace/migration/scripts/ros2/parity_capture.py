#!/usr/bin/env python3
"""ROS 2 stationary parity capture: the same fields the ROS 1 baseline reported.

Read-only: subscribes and looks up transforms, never publishes a command.
"""
import json, math, statistics, sys, time
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.qos import QoSProfile, ReliabilityPolicy

rclpy.init()
node = Node("parity_capture")
result = {"source": "ros2"}

scans = []
node.create_subscription(LaserScan, "/scan", scans.append, QoSProfile(depth=10,
    reliability=ReliabilityPolicy.BEST_EFFORT))
deadline = time.time() + 20
while len(scans) < 8 and time.time() < deadline:
    rclpy.spin_once(node, timeout_sec=0.2)
if scans:
    st = [m.header.stamp.sec + m.header.stamp.nanosec * 1e-9 for m in scans]
    d = [b - a for a, b in zip(st, st[1:]) if b > a]
    s = scans[-1]
    finite = sum(1 for r in s.ranges if math.isfinite(r) and s.range_min <= r <= s.range_max)
    result["scan"] = {
        "rate_hz": round(1.0 / statistics.mean(d), 3) if d else None,
        "samples": len(s.ranges), "frame": s.header.frame_id,
        "angle_min": s.angle_min, "angle_max": s.angle_max,
        "angle_increment": s.angle_increment,
        "range_min": s.range_min, "range_max": s.range_max,
        "scan_time": s.scan_time, "time_increment": s.time_increment,
        "measurements": {"valid": finite,
                         "nan": sum(1 for r in s.ranges if math.isnan(r)),
                         "inf": sum(1 for r in s.ranges if math.isinf(r))},
        "stamp_minus_wallclock_s": round(st[-1] - time.time(), 3),
    }

odoms = []
node.create_subscription(PoseWithCovarianceStamped, "openmover/hardware/odom", odoms.append, 10)
deadline = time.time() + 12
while len(odoms) < 5 and time.time() < deadline:
    rclpy.spin_once(node, timeout_sec=0.2)
if odoms:
    st = [m.header.stamp.sec + m.header.stamp.nanosec * 1e-9 for m in odoms]
    d = [b - a for a, b in zip(st, st[1:]) if b > a]
    q = odoms[-1].pose.pose.orientation
    result["odom"] = {
        "rate_hz": round(1.0 / statistics.mean(d), 3) if d else None,
        "frame": odoms[-1].header.frame_id, "child": "base_link",
        "quaternion_norm": round(math.sqrt(q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w), 9),
        "topic": "openmover/hardware/odom", "type": "PoseWithCovarianceStamped",
    }

from tf2_ros import Buffer, TransformListener

def euler_from_quaternion(q):
    """Roll/pitch/yaw from a quaternion, without needing tf_transformations."""
    x, y, z, w = q
    sinr = 2.0 * (w * x + y * z)
    cosr = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr, cosr)
    sinp = 2.0 * (w * y - z * x)
    pitch = math.copysign(math.pi / 2, sinp) if abs(sinp) >= 1 else math.asin(sinp)
    siny = 2.0 * (w * z + x * y)
    cosy = 1.0 - 2.0 * (y * y + z * z)
    return (roll, pitch, math.atan2(siny, cosy))
buf = Buffer(); _ = TransformListener(buf, node)
result["tf"] = {}
for parent, child in (("base_link", "lidar_link"), ("odom", "base_link")):
    end = time.time() + 10
    while time.time() < end and not buf.can_transform(parent, child, rclpy.time.Time()):
        rclpy.spin_once(node, timeout_sec=0.2)
    try:
        t = buf.lookup_transform(parent, child, rclpy.time.Time())
        tr, rot = t.transform.translation, t.transform.rotation
        rpy = euler_from_quaternion([rot.x, rot.y, rot.z, rot.w])
        result["tf"][f"{parent}->{child}"] = {
            "xyz": [round(tr.x, 6), round(tr.y, 6), round(tr.z, 6)],
            "rpy": [round(v, 6) for v in rpy],
        }
    except Exception as exc:
        result["tf"][f"{parent}->{child}"] = {"error": type(exc).__name__}

print(json.dumps(result, indent=2))
out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ros2_parity.json"
open(out, "w").write(json.dumps(result, indent=2))
node.destroy_node(); rclpy.shutdown()
