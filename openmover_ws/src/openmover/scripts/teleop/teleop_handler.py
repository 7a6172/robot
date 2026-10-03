#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 2023-6-24 0.0.0.1A

import os
import sys
import time
import threading

import rclpy
from geometry_msgs.msg import Twist
from pynput import keyboard
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from openmover_msgs.srv import StopRequest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'hal'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 平铺安装布局

import symbols

NODE_NAME = 'teleop_handler'
TAG = '手动控制'

# 初始化数据
emergency_stop_value = False


class TeleopHandler(Node):

    def __init__(self):
        super().__init__(NODE_NAME)

        self.declare_parameter('teleop.velocity_x', 0.4)
        self.declare_parameter('teleop.velocity_yaw', 0.2)
        self.declare_parameter('teleop.max_x_acc', 1.0)
        self.declare_parameter('teleop.max_yaw_acc', 0.3)

        self.velocity_x = self.get_parameter('teleop.velocity_x').value
        self.velocity_yaw = self.get_parameter('teleop.velocity_yaw').value
        self.max_x_acc = self.get_parameter('teleop.max_x_acc').value
        self.max_yaw_acc = self.get_parameter('teleop.max_yaw_acc').value

        self.get_logger().info('%s：节点已启动。' % TAG)

        # 定义发布器
        self.cmd_vel_pub = self.create_publisher(
            Twist, 'openmover/control/cmd_vel_manual', 2)

        # 定义急停客户端
        self.emergency_stop_client = self.create_client(
            StopRequest, 'openmover/control/stop/request')

        # 初始化数据
        self.twist_data = Twist()
        self.twist_target_data = Twist()

        # 注册键盘监听
        self.listener = keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release)
        self.listener.start()

        self.delta_vx = self.max_x_acc / 50.0
        self.delta_vyaw = self.max_yaw_acc / 50.0

    def on_press(self, key):
        global emergency_stop_value

        if key == keyboard.Key.up:
            self.twist_target_data.linear.x = self.velocity_x
        elif key == keyboard.Key.down:
            self.twist_target_data.linear.x = -self.velocity_x

        if key == keyboard.Key.left:
            self.twist_target_data.angular.z = self.velocity_yaw
        elif key == keyboard.Key.right:
            self.twist_target_data.angular.z = -self.velocity_yaw

        if key == keyboard.Key.home:
            self.twist_target_data.linear.x = 0
            self.twist_target_data.angular.z = 0

            try:
                if self.emergency_stop_client.wait_for_service(timeout_sec=1):
                    emergency_stop_value = not emergency_stop_value

                    request = StopRequest.Request()
                    request.enable = emergency_stop_value

                    future = self.emergency_stop_client.call_async(request)

                    # 后台自旋线程处理服务回调，此处轮询结果
                    deadline = time.monotonic() + 3.0
                    while not future.done():
                        if time.monotonic() > deadline:
                            self.get_logger().warn('%s：紧急制动服务未就绪。' % TAG)
                            return
                        time.sleep(0.05)

                    emergency_stop_data = future.result()
                    assert isinstance(emergency_stop_data,
                                      StopRequest.Response)

                    if emergency_stop_data.result == symbols.cmd_code['ok']:
                        if emergency_stop_value:
                            self.get_logger().warn('%s：紧急制动已施加。' % TAG)
                        else:
                            self.get_logger().warn('%s：紧急制动已释放。' % TAG)
                    else:
                        self.get_logger().warn('%s：紧急制动服务未就绪。' % TAG)
                else:
                    self.get_logger().warn('%s：紧急制动服务未就绪。' % TAG)
            except Exception:
                self.get_logger().warn('%s：紧急制动服务未就绪。' % TAG)

    def on_release(self, key):
        if key == keyboard.Key.up or key == keyboard.Key.down:
            self.twist_target_data.linear.x = 0

        if key == keyboard.Key.left or key == keyboard.Key.right:
            self.twist_target_data.angular.z = 0

    def update(self):
        global emergency_stop_value

        if not emergency_stop_value:
            # 线速度加速度控制
            if abs(self.twist_data.linear.x - self.twist_target_data.linear.x) < self.delta_vx:
                self.twist_data.linear.x = self.twist_target_data.linear.x
            elif self.twist_data.linear.x < self.twist_target_data.linear.x:
                self.twist_data.linear.x += self.delta_vx
            elif self.twist_data.linear.x > self.twist_target_data.linear.x:
                self.twist_data.linear.x -= self.delta_vx

            # 角速度加速度控制
            if abs(self.twist_data.angular.z - self.twist_target_data.angular.z) < self.delta_vyaw:
                self.twist_data.angular.z = self.twist_target_data.angular.z
            elif self.twist_data.angular.z < self.twist_target_data.angular.z:
                self.twist_data.angular.z += self.delta_vyaw
            elif self.twist_data.angular.z > self.twist_target_data.angular.z:
                self.twist_data.angular.z -= self.delta_vyaw
        else:
            self.twist_data.linear.x = 0
            self.twist_data.angular.z = 0

        self.cmd_vel_pub.publish(self.twist_data)


def manual_control():
    rclpy.init()

    node = TeleopHandler()

    # 后台自旋线程处理回调（等效 rospy 的隐式回调处理）
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()

    try:
        while rclpy.ok():
            node.update()

            try:
                time.sleep(0.02)
            except KeyboardInterrupt:
                node.get_logger().warn('%s：节点即将关闭。' % TAG)
                break
    finally:
        node.listener.stop()
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    manual_control()
