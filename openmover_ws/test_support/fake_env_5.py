#!/usr/bin/env python3
"""Stage 5 fake environment for teleop_handler + obstacle_handler tests.

Provides:
- static TF: map -> odom -> base_link -> lidar_link (lidar at x=0.1, z=0.2)
- LaserScan on openmover/hardware/lidar/scan/obstacle with two known obstacles:
  * forward (angle~0): range 1.0 m
  * left (angle~pi/2): range 0.5 m
- Joy on openmover/control/joy: axes[1]=1.0 (drive forward at max), buttons[1]=0;
  after 8 s a single pressed joy message (buttons[1]=1) to trigger emergency stop
- StopRequest service openmover/control/stop/request logging each call
"""
import math
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from geometry_msgs.msg import TransformStamped, Twist
from sensor_msgs.msg import LaserScan, Joy
from tf2_ros import StaticTransformBroadcaster
from openmover_msgs.srv import StopRequest


class FakeEnv(Node):
    def __init__(self):
        super().__init__('fake_env_5')
        self.start = time.time()
        self.button_pressed = False

        # static TF chain (same pattern as fake_env_nav.py)
        self.tf_broadcaster = StaticTransformBroadcaster(self)
        t_map_odom = TransformStamped()
        t_map_odom.header.frame_id = 'map'
        t_map_odom.child_frame_id = 'odom'
        t_map_odom.transform.rotation.w = 1.0
        t_odom_base = TransformStamped()
        t_odom_base.header.frame_id = 'odom'
        t_odom_base.child_frame_id = 'base_link'
        t_odom_base.transform.rotation.w = 1.0
        t_base_lidar = TransformStamped()
        t_base_lidar.header.frame_id = 'base_link'
        t_base_lidar.child_frame_id = 'lidar_link'
        t_base_lidar.transform.translation.x = 0.1
        t_base_lidar.transform.translation.z = 0.2
        t_base_lidar.transform.rotation.w = 1.0
        self.tf_transforms = [t_map_odom, t_odom_base, t_base_lidar]
        self.tf_broadcaster.sendTransform(self.tf_transforms)
        self.create_timer(1.0, self.send_tf)

        # laser scan (best_effort to match SensorDataQoS subscribers)
        self.scan_pub = self.create_publisher(LaserScan, 'openmover/hardware/lidar/scan/obstacle',
                                              QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT,
                                                         history=HistoryPolicy.KEEP_LAST))
        self.create_timer(0.1, self.pub_scan)

        # joy
        self.joy_pub = self.create_publisher(Joy, 'openmover/control/joy', 10)
        self.create_timer(0.2, self.pub_joy)

        # stop service
        self.create_service(StopRequest, 'openmover/control/stop/request', self.stop_cb)
        self.get_logger().info('fake_env_5 ready')

    def send_tf(self):
        for t in self.tf_transforms:
            t.header.stamp = self.get_clock().now().to_msg()
        self.tf_broadcaster.sendTransform(self.tf_transforms)

    def pub_scan(self):
        scan = LaserScan()
        scan.header.stamp = self.get_clock().now().to_msg()
        scan.header.frame_id = 'lidar_link'
        n = 360
        scan.angle_min = -math.pi
        scan.angle_max = math.pi
        scan.angle_increment = 2.0 * math.pi / n
        scan.range_min = 0.05
        scan.range_max = 25.0
        scan.ranges = [float('inf')] * n
        for i in range(n):
            angle = scan.angle_min + i * scan.angle_increment
            if abs(angle) < math.radians(2):      # obstacle 1.0 m ahead
                scan.ranges[i] = 1.0
            if abs(angle - math.pi / 2.0) < math.radians(2):  # obstacle 0.5 m left
                scan.ranges[i] = 0.5
        self.scan_pub.publish(scan)

    def pub_joy(self):
        joy = Joy()
        joy.axes = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        joy.buttons = [0] * 12
        elapsed = time.time() - self.start
        if elapsed > 8.0 and not self.button_pressed:
            joy.buttons[1] = 1
            self.button_pressed = True
            self.get_logger().info('publishing joy with emergency button pressed')
        self.joy_pub.publish(joy)

    def stop_cb(self, req, resp):
        self.get_logger().info(f'STOP SERVICE CALLED enable={req.enable}')
        resp.result = 'ok'
        return resp


def main():
    rclpy.init()
    node = FakeEnv()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
