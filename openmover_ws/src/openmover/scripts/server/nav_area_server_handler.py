#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 2022-6-2 0.0.0.7A
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

NODE_NAME = 'nav_area_server_handler'
TAG = '导航策略服务器'

code_undef = symbols.cmd_code['undef']
code_start = symbols.cmd_code['start']
code_exit = symbols.cmd_code['finish']
code_cancel = symbols.cmd_code['cancel']
code_ok = symbols.cmd_code['ok']
code_error = symbols.cmd_code['error']

current_launch = None
current_command = code_undef

launch_files = dict()
launch_file_default = None

lock = Lock()

node = None


def service_callback(request, response):
    global current_launch
    global current_command

    global lock

    result = code_error

    assert isinstance(request, WorkModeRequest.Request)

    lock.acquire()

    try:
        if request.cmd == code_start:
            if not request.mode in launch_files:
                launch_file = launch_file_default
            else:
                launch_file = launch_files[request.mode]
            current_launch = launch_manager.LaunchHandle(
                launch_file, name='nav_area')
            current_command = code_start

            print("%s：选择启动的导航策略启动文件：%s。" % (TAG, str(launch_file)))
        elif request.cmd == code_exit or request.cmd == code_cancel:
            current_command = code_exit
        result = code_ok
    except Exception:
        pass

    lock.release()

    try:
        time.sleep(config.config_switch_wait_duration)
    except Exception:
        pass

    response.result = result
    return response


def nav_area_server():
    global node

    global current_command
    global launch_files
    global launch_file_default

    global lock

    rclpy.init()

    node = rclpy.create_node(NODE_NAME)

    print('%s：节点已启动。' % TAG)

    # ROS 2：无全局参数服务器，将本节点 use_sim_time（由启动文件设置）转发给子启动
    use_sim_time = node.get_parameter('use_sim_time').value

    launch_file_default = node.declare_parameter(
        'launch_file_default', '').value

    for nav_mode_name in config.config_area_list:
        area_launch_file = node.declare_parameter(
            'launch_file_' + nav_mode_name, '').value
        if area_launch_file != '':
            launch_files[nav_mode_name] = area_launch_file
        else:
            launch_files[nav_mode_name] = launch_file_default

    _ = node.create_service(
        WorkModeRequest, 'openmover/server/set_nav_area', service_callback)

    # 后台自旋线程处理服务回调
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()

    loop_period = 1.0 / config.config_server_loop_rate

    while rclpy.ok():
        lock.acquire()

        try:
            if current_command == code_start:
                try:
                    if current_launch != None:
                        current_launch.start(args={
                            'use_sim_time': 'true' if use_sim_time else 'false'})
                except Exception:
                    pass
                current_command = code_undef
            elif current_command == code_exit:
                try:
                    if current_launch != None:
                        current_launch.stop()
                except Exception:
                    pass
                current_command = code_undef
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
    nav_area_server()
