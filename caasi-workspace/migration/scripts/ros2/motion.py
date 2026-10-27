#!/usr/bin/env python3
"""Bounded motion probe for ROS 2: same commands and measurements as the ROS 1 probe.

Publishes one short command to the manual command topic, then zero, and reports the odometry
change. Relies on motor_handler's own watchdog as a second line of defence on top of the
explicit zero, and is bounded by speed and duration before publishing anything.
"""
import math, sys, time
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from geometry_msgs.msg import PoseWithCovarianceStamped

TOPIC = "openmover/control/cmd_vel_manual"

def yaw_of(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))

def main():
    vx = float(sys.argv[1]) if len(sys.argv) > 1 else 0.10
    wz = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    label = sys.argv[4] if len(sys.argv) > 4 else "run"
    vx = max(-0.25, min(0.25, vx)); wz = max(-1.0, min(1.0, wz))
    dur = max(0.0, min(3.0, dur))

    rclpy.init()
    node = Node("ros2_motion_probe")
    pub = node.create_publisher(Twist, TOPIC, 2)
    state = {"odom": None}
    def on_odom(m): state["odom"] = m
    node.create_subscription(PoseWithCovarianceStamped, "openmover/hardware/odom", on_odom, 10)

    def hold(v, w, seconds):
        end = time.time() + seconds
        msg = Twist(); msg.linear.x = v; msg.angular.z = w
        while time.time() < end:
            pub.publish(msg); rclpy.spin_once(node, timeout_sec=0.05)

    deadline = time.time() + 6
    while state["odom"] is None and time.time() < deadline:
        pub.publish(Twist()); rclpy.spin_once(node, timeout_sec=0.05)
    hold(0.0, 0.0, 0.5)
    start = state["odom"]
    if start is None:
        print("FAIL: no odometry"); return 1
    hold(vx, wz, dur)
    hold(0.0, 0.0, 1.0)
    hold(0.0, 0.0, 0.5)
    end = state["odom"]

    p0, p1 = start.pose.pose, end.pose.pose
    dx = p1.position.x - p0.position.x
    dy = p1.position.y - p0.position.y
    dyaw = math.atan2(math.sin(yaw_of(p1.orientation) - yaw_of(p0.orientation)),
                      math.cos(yaw_of(p1.orientation) - yaw_of(p0.orientation)))
    dist = math.hypot(dx, dy)
    print(f"[{label}] cmd vx={vx:+.3f} m/s wz={wz:+.3f} rad/s for {dur:.2f}s")
    print(f"[{label}] odom dx={dx:+.6f} dy={dy:+.6f} dist={dist:.6f} dyaw={dyaw:+.6f} rad")
    if dur > 0 and abs(vx) > 0:
        print(f"[{label}] distance per commanded metre = {dist / abs(vx * dur):.4f}")
    if dur > 0 and abs(wz) > 0:
        print(f"[{label}] rotation per commanded radian = {dyaw / (wz * dur):.4f}")
    node.destroy_node(); rclpy.shutdown()
    return 0

if __name__ == "__main__":
    sys.exit(main())
