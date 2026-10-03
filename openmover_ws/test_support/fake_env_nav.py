#!/usr/bin/env python3
"""Stage 4b 运行期验证用假环境。

发布内容（与 ROS 1 节点接口一致）：
  - TF: map -> odom -> base_link -> lidar_link（静态）
  - openmover/localization/pose   (PoseWithCovarianceStamped, frame=map)
  - openmover/localization/odom   (PoseWithCovarianceStamped, frame=odom)
  - openmover/localization/twist  (TwistWithCovarianceStamped)
  - openmover/navigation/obstacle (openmover_msgs/Obstacle)
  - openmover/mapping/map         (OccupancyGrid, transient_local, 10m x 10m 全空)
  - openmover/hardware/button     (Bool, transient_local, False)
  - openmover/hardware/emergency  (Bool, transient_local, False)
  - 服务 openmover/control/cmd_vel_mode/request -> result="ok"
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy

from geometry_msgs.msg import (PoseWithCovarianceStamped, TwistWithCovarianceStamped,
                               TransformStamped)
from nav_msgs.msg import OccupancyGrid
from std_msgs.msg import Bool
from tf2_ros import StaticTransformBroadcaster

from openmover_msgs.msg import Obstacle
from openmover_msgs.srv import CmdVelModeRequest


class FakeNavEnv(Node):
    def __init__(self):
        super().__init__('fake_nav_env')

        # ---------------- TF ----------------
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
        t_base_lidar.transform.rotation.w = 1.0
        self.tf_transforms = [t_map_odom, t_odom_base, t_base_lidar]
        self.tf_broadcaster.sendTransform(self.tf_transforms)
        self.create_timer(1.0, self.send_tf)

        # ---------------- 发布器 ----------------
        self.pose_pub = self.create_publisher(PoseWithCovarianceStamped,
                                              'openmover/localization/pose', 2)
        self.odom_pub = self.create_publisher(PoseWithCovarianceStamped,
                                              'openmover/localization/odom', 2)
        self.twist_pub = self.create_publisher(TwistWithCovarianceStamped,
                                               'openmover/localization/twist', 2)
        self.obstacle_pub = self.create_publisher(Obstacle,
                                                  'openmover/navigation/obstacle', 1)

        latched = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.map_pub = self.create_publisher(OccupancyGrid, 'openmover/mapping/map',
                                             latched)
        self.button_pub = self.create_publisher(Bool, 'openmover/hardware/button',
                                                latched)
        self.emergency_pub = self.create_publisher(Bool, 'openmover/hardware/emergency',
                                                   latched)

        # ---------------- 服务 ----------------
        self.srv = self.create_service(CmdVelModeRequest,
                                       'openmover/control/cmd_vel_mode/request',
                                       self.cmd_vel_mode_callback)

        # ---------------- 定时器 ----------------
        self.create_timer(0.05, self.pose_timer_callback)
        self.create_timer(0.05, self.odom_timer_callback)
        self.create_timer(0.05, self.twist_timer_callback)
        self.create_timer(0.1, self.obstacle_timer_callback)

        # 发布 latched 数据（地图每 2 秒重发，便于调试订阅时序问题）
        self.publish_map()
        self.create_timer(2.0, self.publish_map)
        self.button_pub.publish(Bool(data=False))
        self.emergency_pub.publish(Bool(data=False))

        self.get_logger().info('fake_nav_env 已启动。')

    def send_tf(self):
        for t in self.tf_transforms:
            t.header.stamp = self.get_clock().now().to_msg()
        self.tf_broadcaster.sendTransform(self.tf_transforms)

    def publish_map(self):
        grid = OccupancyGrid()
        grid.header.frame_id = 'map'
        grid.header.stamp = self.get_clock().now().to_msg()
        grid.info.resolution = 0.05
        grid.info.width = 200
        grid.info.height = 200
        grid.info.origin.position.x = -5.0
        grid.info.origin.position.y = -5.0
        grid.info.origin.orientation.w = 1.0
        grid.data = [0] * (200 * 200)
        self.map_pub.publish(grid)
        self.get_logger().info('已发布 10m x 10m 空白地图。')

    def pose_timer_callback(self):
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = 'map'
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.pose.pose.position.x = 0.0
        msg.pose.pose.position.y = 0.0
        msg.pose.pose.orientation.w = 1.0
        self.pose_pub.publish(msg)

    def odom_timer_callback(self):
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = 'odom'
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.pose.pose.position.x = 0.0
        msg.pose.pose.position.y = 0.0
        msg.pose.pose.orientation.w = 1.0
        self.odom_pub.publish(msg)

    def twist_timer_callback(self):
        msg = TwistWithCovarianceStamped()
        msg.header.frame_id = 'base_link'
        msg.header.stamp = self.get_clock().now().to_msg()
        self.twist_pub.publish(msg)

    def obstacle_timer_callback(self):
        msg = Obstacle()
        msg.header.frame_id = 'base_link'
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.size = 0
        msg.obstacle_forward = []
        msg.obstacle_backward = []
        msg.obstacle_left = []
        msg.obstacle_right = []
        self.obstacle_pub.publish(msg)

    def cmd_vel_mode_callback(self, request, response):
        self.get_logger().info(f'cmd_vel_mode/request: manual={request.manual}')
        response.result = 'ok'
        return response


def main():
    rclpy.init()
    node = FakeNavEnv()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
