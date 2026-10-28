#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ROS 2 port of swjtumover_bringup/scripts/obstacle_rplidar.py.

A front-facing guard: drive forward while the corridor ahead is clear, stop otherwise. The
constants, the front sector, the NaN filtering and the go/stop decision are unchanged from
ROS 1 -- this is a safety behaviour, so its numbers are not mine to tune.

Two deliberate differences:
  * it is a wall-timer loop rather than `while not rospy.is_shutdown()`;
  * a zero command is published on shutdown, because the controller keeps whatever command it
    last received.
"""

from __future__ import annotations

import math

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import LaserScan

LINEAR_VEL = 0.2          # m/s, unchanged from ROS 1
STOP_DISTANCE = 0.8       # m
LIDAR_ERROR = 0.05
SAFE_STOP_DISTANCE = STOP_DISTANCE + LIDAR_ERROR
FRONT_ANGLE_DEG = 10      # half-width of the front sector


class ObstacleAvoidance(Node):
    def __init__(self) -> None:
        super().__init__('omove_obstacle')
        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel', 1)
        self.scan_msg = None
        self.moving = False

        scan_qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.create_subscription(LaserScan, '/scan', self.scan_callback, scan_qos)
        self.create_timer(0.1, self.step)

        self.get_logger().info('obstacle guard started')
        self.get_logger().info('detection sector: +-%.1f degrees ahead' % FRONT_ANGLE_DEG)
        self.get_logger().info('stop distance: %.3f m' % SAFE_STOP_DISTANCE)

    def scan_callback(self, msg: LaserScan) -> None:
        self.scan_msg = msg

    def get_front_distances(self) -> list:
        """Valid ranges inside the front sector, with the ROS 1 NaN/inf filtering."""
        if self.scan_msg is None:
            return []
        scan = self.scan_msg
        half_angle = math.radians(FRONT_ANGLE_DEG)
        start_index = int((-half_angle - scan.angle_min) / scan.angle_increment)
        end_index = int((half_angle - scan.angle_min) / scan.angle_increment)
        start_index = max(0, start_index)
        end_index = min(len(scan.ranges) - 1, end_index)
        if end_index < start_index:
            return []
        valid = []
        for value in scan.ranges[start_index:end_index + 1]:
            if math.isnan(value) or math.isinf(value):
                continue
            if value < max(scan.range_min, 0.05) or value > scan.range_max:
                continue
            valid.append(value)
        return valid

    def stop_robot(self) -> None:
        self.cmd_pub.publish(Twist())
        self.moving = False

    def move_forward(self) -> None:
        twist = Twist()
        twist.linear.x = LINEAR_VEL
        twist.angular.z = 0.0
        self.cmd_pub.publish(twist)
        self.moving = True

    def step(self) -> None:
        front = self.get_front_distances()
        if not front:
            self.get_logger().warn(
                'no valid scan data ahead, stopping for safety', throttle_duration_sec=1.0)
            self.stop_robot()
            return
        min_distance = min(front)
        if min_distance < SAFE_STOP_DISTANCE:
            if self.moving:
                self.get_logger().warn(
                    'Stop! obstacle at %.3f m, inside the %.3f m stop distance'
                    % (min_distance, SAFE_STOP_DISTANCE))
            self.stop_robot()
        else:
            self.move_forward()
            self.get_logger().info(
                'Go! path clear, %.3f m' % min_distance, throttle_duration_sec=1.0)

    def shutdown(self) -> None:
        self.get_logger().info('shutting down, stopping the robot')
        self.stop_robot()


def main() -> int:
    rclpy.init()
    node = ObstacleAvoidance()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.shutdown()
        node.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
