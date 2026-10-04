#!/usr/bin/env python3
"""BEHAVIORAL TEST A/B/C (ROS 2 SIDE) — counterpart of the ROS 1 probe.

Inputs are byte-identical to the ROS 1 run so the JSON outputs can be compared
numerically. Emits the same JSON schema as ros1_behavioral.sh.
"""
import json
import math
import sys
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, PoseWithCovarianceStamped, TwistWithCovarianceStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from openmover_msgs.msg import Obstacle
from openmover_msgs.srv import CmdVelModeRequest, StopRequest

rclpy.init()
node = Node("equiv_probe_ros2")

results = {}
got = {}


def mk(topic, typ):
    def cb(m):
        got.setdefault(topic, []).append(m)
    node.create_subscription(typ, topic, cb, 10)


mk("/openmover/control/cmd_vel_sim", Twist)
mk("/openmover/hardware/odom", PoseWithCovarianceStamped)
mk("/openmover/hardware/twist", TwistWithCovarianceStamped)
mk("/openmover/navigation/obstacle", Obstacle)

pub_cmd = node.create_publisher(Twist, "/openmover/control/cmd_vel", 10)
pub_manual = node.create_publisher(Twist, "/openmover/control/cmd_vel_manual", 10)
pub_odom = node.create_publisher(Odometry, "/openmover/hardware/odom_sim", 10)
pub_scan = node.create_publisher(LaserScan, "/openmover/hardware/lidar/scan/obstacle", 2)


def spin(seconds):
    end = time.time() + seconds
    while time.time() < end:
        rclpy.spin_once(node, timeout_sec=0.05)


def twist(vx, vy, vz, wx, wy, wz):
    t = Twist()
    t.linear.x, t.linear.y, t.linear.z = float(vx), float(vy), float(vz)
    t.angular.x, t.angular.y, t.angular.z = float(wx), float(wy), float(wz)
    return t


# ---- service clients -------------------------------------------------------
mode_cli = node.create_client(CmdVelModeRequest, "/openmover/control/cmd_vel_mode/request")
stop_cli = node.create_client(StopRequest, "/openmover/control/stop/request")
ok_mode = mode_cli.wait_for_service(timeout_sec=20.0)
ok_stop = stop_cli.wait_for_service(timeout_sec=20.0)


def call(cli, req):
    fut = cli.call_async(req)
    end = time.time() + 10
    while not fut.done() and time.time() < end:
        rclpy.spin_once(node, timeout_sec=0.05)
    return fut.result() if fut.done() else None


spin(1.0)

# ============ TEST A: cmd_vel response ============
A = {"services_available": {"cmd_vel_mode": bool(ok_mode), "stop": bool(ok_stop)}, "cases": []}


def emit_case(name, chan, msg, expect, manual_mode=None):
    got.pop("/openmover/control/cmd_vel_sim", None)
    (pub_manual if chan == "manual" else pub_cmd).publish(msg)
    spin(0.45)
    recv = got.get("/openmover/control/cmd_vel_sim", [])
    last = recv[-1] if recv else None
    A["cases"].append({
        "name": name,
        "channel": chan,
        "manual_mode": manual_mode,
        "input": {"vx": msg.linear.x, "wz": msg.angular.z},
        "expected": expect,
        "published": last is not None,
        "output": ({"vx": last.linear.x, "wz": last.angular.z} if last else None),
    })


# ROS 2 node also starts with cmd_vel_manual_mode = true (same source logic).
A["initial_manual_mode"] = True
emit_case("manual_mode=True, auto channel", "auto", twist(0.11, 0, 0, 0, 0, 0.22),
          "suppressed (manual mode ignores auto channel)", True)
emit_case("manual_mode=True, manual channel", "manual", twist(0.33, 0, 0, 0, 0, 0.44),
          "forwarded", True)

req = CmdVelModeRequest.Request(); req.manual = False
r1 = call(mode_cli, req)
A["mode_service_response_manual_false"] = (r1.result if r1 else None)

emit_case("manual_mode=False, auto channel", "auto", twist(0.55, 0, 0, 0, 0, 0.66),
          "forwarded", False)
emit_case("manual_mode=False, manual channel", "manual", twist(0.77, 0, 0, 0, 0, 0.88),
          "suppressed", False)

r2 = call(stop_cli, StopRequest.Request(enable=True))
A["stop_service_response_enable_true"] = (r2.result if r2 else None)
emit_case("emergency=True, auto channel", "auto", twist(0.99, 0, 0, 0, 0, 0.99),
          "published but zeroed", False)

r3 = call(stop_cli, StopRequest.Request(enable=False))
A["stop_service_response_enable_false"] = (r3.result if r3 else None)
emit_case("emergency=False, auto channel", "auto", twist(0.12, 0, 0, 0, 0, 0.34),
          "forwarded again", False)

results["test_A_cmd_vel"] = A

# ============ TEST B: odometry / twist transform ============
got.pop("/openmover/hardware/odom", None)
got.pop("/openmover/hardware/twist", None)
od = Odometry()
od.header.frame_id = "odom"
od.child_frame_id = "base_link"
od.pose.pose.position.x = 1.25
od.pose.pose.position.y = -2.5
od.pose.pose.position.z = 0.125
od.pose.pose.orientation.w = 1.0
od.twist.twist.linear.x = 0.4
od.twist.twist.angular.z = -0.15
pub_odom.publish(od)
spin(0.6)

B = {"input": {"x": 1.25, "y": -2.5, "z": 0.125, "lin_x": 0.4, "ang_z": -0.15}}
for topic, key in (("/openmover/hardware/odom", "odom"),
                   ("/openmover/hardware/twist", "twist")):
    recv = got.get(topic, [])
    if recv:
        m = recv[-1]
        if key == "odom":
            B[key] = {"frame_id": m.header.frame_id,
                      "x": m.pose.pose.position.x, "y": m.pose.pose.position.y,
                      "z": m.pose.pose.position.z}
        else:
            B[key] = {"frame_id": m.header.frame_id,
                      "lin_x": m.twist.twist.linear.x,
                      "ang_z": m.twist.twist.angular.z}
    else:
        B[key] = None
results["test_B_odom"] = B

# ============ TEST C: obstacle grid ============
got.pop("/openmover/navigation/obstacle", None)
sc = LaserScan()
sc.header.frame_id = "lidar_link"
sc.angle_min = -math.pi
sc.angle_max = math.pi
sc.angle_increment = 2 * math.pi / 360.0
sc.range_min = 0.05
sc.range_max = 20.0
sc.scan_time = 0.1
sc.time_increment = 0.0
ranges = [float("inf")] * 360
ranges[0] = 1.0
ranges[90] = 0.5
ranges[180] = 2.0
ranges[270] = 0.75
sc.ranges = ranges

C = {"input": {"frame_id": "lidar_link", "num_ranges": 360,
               "obstacles": {"forward_0deg": 1.0, "left_90deg": 0.5,
                             "rear_180deg": 2.0, "right_270deg": 0.75}}}
out = None
# republish for a while: obstacle_handler runs a periodic loop
for _ in range(6):
    pub_scan.publish(sc)
    spin(0.4)
    recv = got.get("/openmover/navigation/obstacle", [])
    if recv:
        out = recv[-1]
        break

if out is not None:

    def clean(seq):
        return [None if math.isinf(float(v)) else float(v) for v in seq]

    C["output"] = {
        "size": int(out.size),
        "obstacle_forward": clean(out.obstacle_forward),
        "obstacle_backward": clean(out.obstacle_backward),
        "obstacle_left": clean(out.obstacle_left),
        "obstacle_right": clean(out.obstacle_right),
    }
else:
    C["output"] = None
results["test_C_obstacle"] = C

results["_meta"] = {"ros_distro": "jazzy", "source": "live ROS 2"}

print("###JSON_START###")
print(json.dumps(results, indent=2, default=str))
print("###JSON_END###")

node.destroy_node()
rclpy.shutdown()
