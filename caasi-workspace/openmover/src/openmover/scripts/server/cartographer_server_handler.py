#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 2023-6-24 0.0.0.2A
# ROS 2 Jazzy port (Stage 6): roslaunch API -> launch_manager.
# cartographer ROS 2 binaries are available (user-confirmed); uses
# cartographer_ros_msgs WriteState as in ROS 1.

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

from cartographer_ros_msgs.msg import StatusCode
from cartographer_ros_msgs.srv import WriteState
from openmover_msgs.srv import WorkModeRequest
from rclpy.executors import MultiThreadedExecutor

NODE_NAME = 'cartographer_server_handler'
TAG = 'Cartographer 功能服务器'

code_undef = symbols.cmd_code['undef']
code_start = symbols.cmd_code['start']
code_exit = symbols.cmd_code['finish']
code_cancel = symbols.cmd_code['cancel']
code_ok = symbols.cmd_code['ok']
code_error = symbols.cmd_code['error']

current_pbstream_filename = code_undef
desired_pbstream_filename = code_undef

desired_area_name = code_undef

lock = Lock()

node = None


def service_callback(request, response):
    global desired_pbstream_filename
    global desired_pbstream_name

    global desired_area_name

    global lock

    result = code_error

    assert isinstance(request, WorkModeRequest.Request)

    lock.acquire()

    try:
        if request.mode == symbols.func_code['load_map'] and localization_mode:
            desired_pbstream_name = request.params
            desired_area_name = request.params
            desired_pbstream_filename = request.cmd + request.params + ".pbstream"

            result = code_ok
        elif request.mode == symbols.func_code['save_map'] and not localization_mode:
            try:
                write_pbstream_service = node.create_client(
                    WriteState, 'openmover/mapping/write_state/request')

                if write_pbstream_service.wait_for_service(timeout_sec=10):
                    pbstream_filename = request.cmd + request.params + ".pbstream"

                    write_pbstream_data = write_pbstream_service.call(
                        WriteState.Request(filename=pbstream_filename,
                                           include_unfinished_submaps=False))
                    assert isinstance(write_pbstream_data, WriteState.Response)

                    if write_pbstream_data.status.code == StatusCode.OK:
                        result = code_ok

                node.destroy_client(write_pbstream_service)
            except Exception:
                pass
    except Exception:
        pass

    lock.release()

    if request.mode != symbols.func_code['save_map']:
        try:
            time.sleep(config.config_switch_wait_duration)
        except Exception:
            pass

    response.result = result
    return response


def cartographer_server():
    global node

    global current_pbstream_filename
    global desired_pbstream_filename
    global desired_pbstream_name
    global localization_mode

    global lock

    rclpy.init()

    node = rclpy.create_node(NODE_NAME)

    print('%s：节点已启动。' % TAG)

    localization_mode = node.declare_parameter('localization_mode', False).value
    launch_file_carto_localization = node.declare_parameter(
        'launch_file_cartographer', '').value

    # ROS 2：无全局参数服务器，将本节点 use_sim_time（由启动文件设置）转发给子启动
    use_sim_time = node.get_parameter('use_sim_time').value

    _ = node.create_service(
        WorkModeRequest, 'openmover/localization/cartographer/request', service_callback)

    # 后台自旋线程处理服务回调
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()

    if localization_mode:
        launch_carto_localization = launch_manager.LaunchHandle(
            launch_file_carto_localization, name='cartographer_localization')

    loop_period = 1.0 / config.config_server_loop_rate

    while rclpy.ok():
        lock.acquire()

        try:
            if current_pbstream_filename != desired_pbstream_filename:
                if localization_mode:
                    launch_carto_localization.stop()

                    if desired_pbstream_name != code_undef:
                        print('%s：加载设置文件：%s。' %
                              (TAG, str(desired_area_name + ".lua")))

                        print('%s：加载地图：%s。' %
                              (TAG, str(desired_pbstream_filename)))

                        launch_carto_localization.start(args={
                            'pbstream_filename': desired_pbstream_filename,
                            'config_basename': desired_area_name + ".lua",
                            'use_sim_time': 'true' if use_sim_time else 'false'})
                    current_pbstream_filename = desired_pbstream_filename
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


if __name__ == "__main__":
    cartographer_server()
