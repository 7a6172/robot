#!/usr/bin/env python3
"""TEST E (shared): laserscan_multi_merger on an identical deterministic input.

Two synthetic scans (forward + rear) are published on different frames. The
merger transforms both into `lidar_link` and concatenates them into one 360°
scan. This is a pure geometric transform with no simulator involved.

Deterministic test case: forward scan has a single return at +0.0 rad (1.0 m),
rear scan has a single return at its own 0.0 rad (2.0 m). With the rear sensor
mounted 180° rotated (or 0° with the frame offset), the merged angular positions
are computable and directly comparable.

Arguments: <ros1|ros2>
"""
import json
import math
import sys
import time

SIDE = sys.argv[1] if len(sys.argv) > 1 else "unknown"

# Merger parameters identical to the project's bringup config.
MERGER = {
    "destination_frame": "lidar_link",
    "cloud_destination_topic": "openmover/hardware/lidar/pointcloud",
    "scan_destination_topic": "openmover/hardware/lidar/scan",
    "laserscan_topics": "/openmover/hardware/lidar_forward/scan /openmover/hardware/lidar_rear/scan",
    "angle_min": -3.1415926,
    "angle_max": 3.1415926,
    "angle_increment": 0.006962,
    "scan_time": 0.0,
    "range_min": 0.33,
    "range_max": 20.0,
}

N = 128  # samples per input scan
INC = math.pi / N  # 0..pi forward-ish span


def make_scan(frame_id, near_idx, near_range):
    """Build a scan with `inf` everywhere except one deterministic return."""
    ranges = [float("inf")] * N
    ranges[near_idx] = near_range
    return frame_id, ranges


FWD_FRAME = "lidar_forward_link"
REAR_FRAME = "lidar_rear_link"

out = {"side": SIDE, "params": MERGER, "input": {"num_samples": N, "angle_increment": INC}}

if SIDE == "ros1":
    import rospy
    from sensor_msgs.msg import LaserScan

    rospy.init_node("merger_probe", anonymous=True, disable_signals=True)

    def mk(frame_id, ranges):
        s = LaserScan()
        s.header.frame_id = frame_id
        s.angle_min = -math.pi
        s.angle_max = math.pi - INC
        s.angle_increment = INC
        s.range_min = 0.05
        s.range_max = 20.0
        s.scan_time = 0.1
        s.time_increment = 0.0
        s.ranges = ranges
        return s

    pf = rospy.Publisher("/openmover/hardware/lidar_forward/scan", LaserScan, queue_size=2)
    pr = rospy.Publisher("/openmover/hardware/lidar_rear/scan", LaserScan, queue_size=2)
    got = []

    def cb(m):
        got.append(m)

    rospy.Subscriber(MERGER["scan_destination_topic"], LaserScan, cb)
    rospy.sleep(1.0)

    _id, ranges = make_scan(FWD_FRAME, 0, 1.0)      # forward scan: 1 return at 1.0 m
    fwd = mk(FWD_FRAME, ranges)
    _id2, ranges2 = make_scan(REAR_FRAME, 0, 2.0)   # rear scan: 1 return at 2.0 m
    rear = mk(REAR_FRAME, ranges2)

    for _ in range(30):
        fwd.header.stamp = rospy.Time.now()
        rear.header.stamp = rospy.Time.now()
        pf.publish(fwd)
        pr.publish(rear)
        rospy.sleep(0.15)
        if got:
            break

    if got:
        m = got[-1]
        out["output"] = {
            "frame_id": m.header.frame_id,
            "angle_min": m.angle_min, "angle_max": m.angle_max,
            "angle_increment": m.angle_increment,
            "range_min": m.range_min, "range_max": m.range_max,
            "num_ranges": len(m.ranges),
            "finite_ranges": [
                {"index": i, "angle": m.angle_min + i * m.angle_increment, "range": float(r)}
                for i, r in enumerate(m.ranges)
                if not math.isinf(r) and not math.isnan(r)
            ],
        }
    else:
        out["output"] = None

else:
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import LaserScan

    rclpy.init()
    node = Node("merger_probe")

    def mk(frame_id, ranges):
        s = LaserScan()
        s.header.frame_id = frame_id
        s.angle_min = -math.pi
        s.angle_max = math.pi - INC
        s.angle_increment = INC
        s.range_min = 0.05
        s.range_max = 20.0
        s.scan_time = 0.1
        s.time_increment = 0.0
        s.ranges = ranges
        return s

    pf = node.create_publisher(LaserScan, "/openmover/hardware/lidar_forward/scan", 2)
    pr = node.create_publisher(LaserScan, "/openmover/hardware/lidar_rear/scan", 2)
    got = []
    node.create_subscription(LaserScan, MERGER["scan_destination_topic"],
                             lambda m: got.append(m), 10)

    def spin(sec):
        end = time.time() + sec
        while time.time() < end:
            rclpy.spin_once(node, timeout_sec=0.05)

    spin(1.0)
    _id, ranges = make_scan(FWD_FRAME, 0, 1.0)
    fwd = mk(FWD_FRAME, ranges)
    _id2, ranges2 = make_scan(REAR_FRAME, 0, 2.0)
    rear = mk(REAR_FRAME, ranges2)

    for _ in range(30):
        fwd.header.stamp = node.get_clock().now().to_msg()
        rear.header.stamp = node.get_clock().now().to_msg()
        pf.publish(fwd)
        pr.publish(rear)
        spin(0.15)
        if got:
            break

    if got:
        m = got[-1]
        out["output"] = {
            "frame_id": m.header.frame_id,
            "angle_min": m.angle_min, "angle_max": m.angle_max,
            "angle_increment": m.angle_increment,
            "range_min": m.range_min, "range_max": m.range_max,
            "num_ranges": len(m.ranges),
            "finite_ranges": [
                {"index": i, "angle": m.angle_min + i * m.angle_increment, "range": float(r)}
                for i, r in enumerate(m.ranges)
                if not math.isinf(r) and not math.isnan(r)
            ],
        }
    else:
        out["output"] = None
    node.destroy_node()
    rclpy.shutdown()

print("###JSON_START###")
print(json.dumps(out, indent=2, default=str))
print("###JSON_END###")
