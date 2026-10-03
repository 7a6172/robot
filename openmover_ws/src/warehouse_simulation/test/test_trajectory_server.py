#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""trajectory_server.py 的功能测试（rclpy，不需要仿真器）。

流程：
1. 启动 TrajectoryServer 节点；
2. 由测试节点向 /tf 发布 map->base_link 变换（先静止、再移动）；
3. 校验 /trajectory 话题：静止时不重复追加点，移动时路径累积且
   末端点与最新变换一致。
"""
import os
import sys
import threading
import time

import pytest
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Path
from tf2_msgs.msg import TFMessage

SCRIPT_DIR = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
sys.path.insert(0, SCRIPT_DIR)
import trajectory_server  # noqa: E402


class TFPublisher(Node):
    def __init__(self):
        super().__init__('test_tf_publisher')
        self.pub = self.create_publisher(TFMessage, '/tf', 10)

    def send(self, x):
        t = TransformStamped()
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id = 'map'
        t.child_frame_id = 'base_link'
        t.transform.translation.x = float(x)
        t.transform.translation.y = 0.0
        t.transform.translation.z = 0.0
        t.transform.rotation.w = 1.0
        self.pub.publish(TFMessage(transforms=[t]))


@pytest.fixture(scope='module')
def ros():
    rclpy.init()
    yield
    rclpy.shutdown()


def test_trajectory_server(ros):
    server = trajectory_server.TrajectoryServer()
    tf_pub = TFPublisher()

    checker = rclpy.create_node('trajectory_checker')
    received = []
    checker.create_subscription(Path, 'trajectory', received.append, 10)

    executor = MultiThreadedExecutor()
    executor.add_node(server)
    executor.add_node(tf_pub)
    executor.add_node(checker)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    try:
        # ---- 阶段 1：静止，路径只应有一个点 ----
        deadline = time.time() + 10.0
        while time.time() < deadline and not received:
            tf_pub.send(0.0)
            time.sleep(0.1)
        assert received, '10s 内未收到 /trajectory 消息'

        time.sleep(0.8)  # 期间持续发送相同的静止变换
        static_len = len(received[-1].poses)
        assert static_len == 1, f'静止时路径点数应为 1，实际 {static_len}'

        # ---- 阶段 2：移动 0 -> 1.0 m，路径应累积 ----
        for i in range(1, 11):
            tf_pub.send(i * 0.1)
            time.sleep(0.15)

        deadline = time.time() + 5.0
        while time.time() < deadline and len(received[-1].poses) < 8:
            time.sleep(0.1)

        last_path = received[-1]
        assert last_path.header.frame_id == 'map'
        assert len(last_path.poses) >= 8, \
            f'移动后路径点数不足: {len(last_path.poses)}'
        end_x = last_path.poses[-1].pose.position.x
        assert abs(end_x - 1.0) < 1e-3, f'末端点 x={end_x}, 期望 1.0'

        # 路径点应单调递增（没有走回头路）
        xs = [p.pose.position.x for p in last_path.poses]
        assert all(b >= a for a, b in zip(xs, xs[1:]))
    finally:
        executor.shutdown()
        spin_thread.join(timeout=5.0)
        server.destroy_node()
        tf_pub.destroy_node()
        checker.destroy_node()
