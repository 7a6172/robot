#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""trajectory_server.py

替代 ROS 1 的 hector_trajectory_server：
监听 TF（map -> base_link），累积机器人历史轨迹，并以固定频率发布
nav_msgs/Path 到 `trajectory` 话题。
"""
import rclpy
from rclpy.node import Node
from tf2_ros import Buffer, TransformListener
from nav_msgs.msg import Path
from geometry_msgs.msg import PoseStamped


class TrajectoryServer(Node):
    def __init__(self):
        super().__init__('trajectory_server')
        self.declare_parameter('frame_id', 'map')
        self.declare_parameter('target_frame', 'base_link')
        self.declare_parameter('rate', 10.0)

        self.frame_id = self.get_parameter('frame_id').value
        self.target_frame = self.get_parameter('target_frame').value

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.path = Path()
        self.path.header.frame_id = self.frame_id

        self.pub = self.create_publisher(Path, 'trajectory', 10)
        rate = self.get_parameter('rate').value
        self.timer = self.create_timer(1.0 / rate, self.timer_cb)

    def timer_cb(self):
        try:
            t = self.tf_buffer.lookup_transform(
                self.frame_id, self.target_frame, rclpy.time.Time())
        except Exception:
            return

        pose = PoseStamped()
        pose.header.stamp = t.header.stamp
        pose.header.frame_id = self.frame_id
        pose.pose.position.x = t.transform.translation.x
        pose.pose.position.y = t.transform.translation.y
        pose.pose.position.z = t.transform.translation.z
        pose.pose.orientation = t.transform.rotation

        # 与 hector_trajectory_server 类似：只在移动时追加点，避免重复点
        if len(self.path.poses) == 0:
            self.path.poses.append(pose)
        else:
            last = self.path.poses[-1].pose.position
            dx = pose.pose.position.x - last.x
            dy = pose.pose.position.y - last.y
            if dx * dx + dy * dy > 1e-6:
                self.path.poses.append(pose)

        self.path.header.stamp = t.header.stamp
        self.pub.publish(self.path)


def main(args=None):
    rclpy.init(args=args)
    node = TrajectoryServer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
