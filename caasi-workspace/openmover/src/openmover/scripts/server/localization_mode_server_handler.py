#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 2022-6-2 0.0.0.10A
# ROS 2 Jazzy port (Stage 6): roslaunch API -> launch_manager.

import os
import sys
import threading
import time
from threading import Lock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 平铺安装布局

import config
import rclpy
import symbols
import launch_manager

from openmover_msgs.srv import WorkModeRequest
from rclpy.executors import MultiThreadedExecutor

NODE_NAME = 'localization_mode_server_handler'
TAG = '定位数据源服务器'

code_undef = symbols.cmd_code['undef']
code_start = symbols.cmd_code['start']
code_exit = symbols.cmd_code['finish']
code_cancel = symbols.cmd_code['cancel']
code_ok = symbols.cmd_code['ok']
code_error = symbols.cmd_code['error']

mode_map = symbols.localization_mode['map']

current_mode_map = code_undef
desired_mode_map = code_undef

desired_area_name = code_undef
last_desired_area_name = code_undef

lock = Lock()

node = None


def service_callback(request, response):
    global desired_mode_map

    global desired_area_name

    global lock

    mode_map_exists = code_exit

    result = code_error

    assert isinstance(request, WorkModeRequest.Request)

    lock.acquire()

    desired_area_name = request.params

    try:
        if request.mode.find(mode_map) != -1:
            mode_map_exists = code_start

        if current_mode_map == code_start and mode_map_exists == code_exit:
            mode_map_exists = code_start

        if request.mode == code_undef:
            mode_map_exists = code_exit

        if request.mode != code_undef and\
                current_mode_map == mode_map_exists:
            lock.release()

            result = code_ok
        else:
            desired_mode_map = mode_map_exists

            lock.release()

            result = code_ok

            try:
                time.sleep(config.config_switch_wait_duration)
            except Exception:
                pass
    except Exception:
        lock.release()

    response.result = result
    return response


def localization_mode_server():
    global node

    global current_mode_map
    global desired_mode_map
    global desired_area_name
    global last_desired_area_name

    global lock

    # sudo -n：无密码 sudo 时正常执行；否则立即失败而不阻塞节点启动
    if os.system('sudo -n renice 10 ' + str(os.getpid()) + ' >/dev/null 2>&1') != 0:
        print('%s：优先级降低失败。' % TAG)
    else:
        print('%s：优先级降低成功。' % TAG)

    rclpy.init()

    node = rclpy.create_node(NODE_NAME)

    print('%s：节点已启动。' % TAG)

    system_mode = node.declare_parameter('system_mode', 0).value

    launch_file_map = node.declare_parameter('launch_file_map', '').value

    # The scan interface is a hardware-profile decision, not a constant: the lab fit merges
    # two scanners into the shared topic, a single 360 degree scanner publishes /scan. The
    # default keeps the historical topic so existing maps and configs are unaffected.
    scan_topic = node.declare_parameter(
        'scan_topic', 'openmover/hardware/lidar/scan').value

    _ = node.create_service(
        WorkModeRequest, 'openmover/server/set_localization_mode', service_callback)

    # 后台自旋线程处理服务回调
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()

    launch_map = launch_manager.LaunchHandle(
        launch_file_map, args={'scan_topic': scan_topic}, name='localization_map')

    loop_period = 1.0 / config.config_server_loop_rate

    while rclpy.ok():
        lock.acquire()

        try:
            if current_mode_map != desired_mode_map:
                if desired_mode_map == code_start:
                    launch_map.start(args={
                        'system_mode': str(system_mode),
                        'area_name': str(desired_area_name),
                        'use_sim_time': 'true' if system_mode == 0 else 'false'})
                elif desired_mode_map == code_exit:
                    launch_map.stop()
                current_mode_map = desired_mode_map

            # 预留
            last_desired_area_name = desired_area_name
        except Exception:
            pass

        lock.release()

        if rclpy.ok():
            try:
                time.sleep(loop_period)
            except KeyboardInterrupt:
                print('%s：节点即将关闭。' % TAG)
        else:
            break

    launch_map.stop()


if __name__ == "__main__":
    localization_mode_server()
