#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ROS 2 Jazzy port (Stage 6): rospy -> rclpy.

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 平铺安装布局

import rclpy
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from std_msgs.msg import Bool
from std_srvs.srv import Empty
from openmover_msgs.srv import NavToRequest
from auto_mapping_toolbox_msgs.srv import AutoMappingRequest
import symbols

NODE_NAME = 'reset_server_handler'
TAG = '系统重置服务器'

button_pressed_time = None
emergency_state = False
emergency_trigger = False

node = None


def button_callback(msg):
    global button_pressed_time

    assert isinstance(msg, Bool)

    if msg.data:
        if button_pressed_time is None:
            button_pressed_time = node.get_clock().now().nanoseconds / 1e9
    else:
        button_pressed_time = None


def emergency_callback(msg):
    global emergency_state
    global emergency_trigger

    assert isinstance(msg, Bool)

    if (msg.data != emergency_state and msg.data):
        emergency_trigger = True

    emergency_state = msg.data


def call_service_blocking(client, request):
    future = client.call_async(request)
    end = time.monotonic() + 5.0
    while not future.done() and time.monotonic() < end:
        time.sleep(0.01)
    return future.result()


def reset_server():
    global node

    global button_pressed_time
    global emergency_state
    global emergency_trigger

    rclpy.init()

    node = rclpy.create_node(NODE_NAME)

    print('%s：节点已启动。' % TAG)

    # 0-导航、1-探索
    work_mode = node.declare_parameter('reset_server/work_mode', 0).value

    # 与 ROS 1 latched 话题兼容（transient_local）
    latched_qos = QoSProfile(depth=1,
                             reliability=ReliabilityPolicy.RELIABLE,
                             history=HistoryPolicy.KEEP_LAST,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)

    _ = node.create_subscription(
        Bool, 'openmover/hardware/button', button_callback, latched_qos)

    _ = node.create_subscription(
        Bool, 'openmover/hardware/emergency', emergency_callback, latched_qos)

    reset_state_pub = node.create_publisher(
        Bool, 'openmover/control/reset_state', 10)

    if work_mode == 0:
        nav_cancel_client = node.create_client(
            NavToRequest, 'openmover/navigation/request')
        nav_cancel_client.wait_for_service()
    elif work_mode == 1:
        auto_mapping_cancel_client = node.create_client(
            AutoMappingRequest, 'openmover/mapping/auto_mapping/request')
        auto_mapping_cancel_client.wait_for_service()

    reloc_client = node.create_client(
        Empty, 'openmover/localization/relocalization/simple_request')
    reloc_client.wait_for_service()

    # 状态数据
    state_data = Bool()
    state_data.data = False

    while rclpy.ok():
        rclpy.spin_some(node)

        now = node.get_clock().now().nanoseconds / 1e9

        if button_pressed_time is not None and (now - button_pressed_time) > 5 and not emergency_state:
            print('%s：准备重置系统。' % TAG)

            # 发布状态
            state_data.data = True

            # 发布三次防止丢失
            for _ in range(3):
                reset_state_pub.publish(state_data)
                time.sleep(0.02)

            # 取消导航或探索
            if work_mode == 0:
                nav_cancel_request = NavToRequest.Request()
                nav_cancel_request.cmd = symbols.nav_cmd_code['cancel']
                call_service_blocking(nav_cancel_client, nav_cancel_request)
            elif work_mode == 1:
                auto_mapping_cancel_request = AutoMappingRequest.Request()
                auto_mapping_cancel_request.cmd = symbols.auto_mapping_cmd_code['cancel']
                call_service_blocking(
                    auto_mapping_cancel_client, auto_mapping_cancel_request)

            # 等待取消完毕
            time.sleep(0.5)

            # 重置定位
            reloc_request = Empty.Request()
            call_service_blocking(reloc_client, reloc_request)

            # 等待重置完毕
            time.sleep(3)

            print('%s：系统重置完成。' % TAG)

            button_pressed_time = None
        else:
            # 发布状态
            state_data.data = False
            reset_state_pub.publish(state_data)

        if emergency_trigger:
            print('%s：紧急制动触发，停止一切任务。' % TAG)

            # 取消导航或探索
            if work_mode == 0:
                nav_cancel_request = NavToRequest.Request()
                nav_cancel_request.cmd = symbols.nav_cmd_code['cancel']
                call_service_blocking(nav_cancel_client, nav_cancel_request)
            elif work_mode == 1:
                auto_mapping_cancel_request = AutoMappingRequest.Request()
                auto_mapping_cancel_request.cmd = symbols.auto_mapping_cmd_code['cancel']
                call_service_blocking(
                    auto_mapping_cancel_client, auto_mapping_cancel_request)

            # 等待取消完毕
            time.sleep(0.5)

            print('%s：紧急制动已施加。' % TAG)

            emergency_trigger = False

        if rclpy.ok():
            try:
                time.sleep(0.1)
            except KeyboardInterrupt:
                print('%s：节点即将关闭。' % TAG)
        else:
            break


if __name__ == "__main__":
    reset_server()
