#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 2023-6-24 0.0.0.1A
# ROS 2 Jazzy port (Stage 6):
# - roslaunch API      -> launch_manager (ros2 launch subprocess manager)
# - rviz SendFilePath  -> restart rviz2 with `-d <config>` (rviz2 has no such service)
# - map_server saver   -> nav2_map_server map_saver_cli
# - rospy background spin -> background executor thread

import os
import subprocess
import sys
import threading
import time
from threading import Lock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 平铺安装布局

import rclpy
import symbols
import yaml
from nav_msgs.msg import OccupancyGrid
from openmover_msgs.srv import WorkModeRequest
from rclpy.executors import MultiThreadedExecutor
from std_msgs.msg import String

import config
import launch_manager

NODE_NAME = 'func_mode_server_handler'
TAG = '功能模式服务器'

code_undef = symbols.cmd_code['undef']
code_start = symbols.cmd_code['start']
code_exit = symbols.cmd_code['finish']
code_cancel = symbols.cmd_code['cancel']
code_ok = symbols.cmd_code['ok']
code_error = symbols.cmd_code['error']

current_mode_create_map = code_undef
desired_mode_create_map = code_undef
current_mode_nav_mode = code_undef
desired_mode_nav_mode = code_undef

current_func_load_map = code_exit
desired_func_load_map = code_exit

lock = Lock()

node = None


def service_callback(request, response):
    global desired_mode_create_map
    global desired_mode_nav_mode

    global desired_func_load_map
    global desired_func_arm
    global desired_func_charger

    global current_func_params

    global map_save_path
    global map_saver_cmd

    global lock

    result = code_error

    assert isinstance(request, WorkModeRequest.Request)

    lock.acquire()

    sleep_duration = config.config_switch_wait_duration

    try:
        if request.mode == symbols.mode_code['create_map']:
            if request.cmd == code_start:
                desired_mode_create_map = code_start
                desired_mode_nav_mode = code_exit
                apply_visualization_config(visualization_config_file_working)
            elif request.cmd == code_exit or request.cmd == code_cancel:
                desired_mode_create_map = code_exit
                apply_visualization_config(visualization_config_file_idle)
            result = code_ok
        elif request.mode == symbols.mode_code['nav_to']:
            if request.cmd == code_start:
                desired_mode_nav_mode = code_start
                desired_mode_create_map = code_exit
                apply_visualization_config(visualization_config_file_working)
            elif request.cmd == code_exit or request.cmd == code_cancel:
                desired_mode_nav_mode = code_exit
                apply_visualization_config(visualization_config_file_idle)
            result = code_ok

        if request.mode == symbols.func_code['load_map']:
            if request.cmd == code_start:
                if request.params != symbols.cmd_code['undef']:
                    current_func_params = request.params
                    desired_func_load_map = code_start
                    apply_visualization_config(
                        visualization_config_file_working)
                else:
                    sleep_duration = 0.0
                    apply_visualization_config(
                        visualization_config_file_working_nomap)
            elif request.cmd == code_exit or request.cmd == code_cancel:
                desired_func_load_map = code_exit
            result = code_ok
        elif request.mode == symbols.func_code['save_map']:
            sleep_duration = 0.0
            if current_mode_create_map == code_start or\
                    current_mode_nav_mode == code_start:
                try:
                    current_func_params = request.params

                    # standard map
                    try:
                        _ = protocol_wait_for_message(
                            'openmover/mapping/map', OccupancyGrid, timeout=1)

                        map_filename = map_save_path + current_func_params
                        mapmeta_filename = map_filename + ".yaml"

                        # ROS 2: nav2_map_server map_saver_cli
                        map_saver_cmd = ("ros2 run nav2_map_server map_saver_cli -f " +
                                         map_filename +
                                         " --ros-args -r map:=openmover/mapping/map")
                        saver_node = subprocess.Popen(map_saver_cmd, shell=True)
                        saver_node.wait()

                        # get current home path name
                        current_home_path = os.environ['HOME']

                        with open(mapmeta_filename, 'r') as stream:
                            mapmeta_yaml = yaml.safe_load(stream)

                        if mapmeta_yaml['origin'][2] == float('nan'):
                            mapmeta_yaml['origin'][2] = 0

                        mapmeta_yaml['image'] = str(mapmeta_yaml['image']).replace(
                            current_home_path, '$HOME_PATH')

                        with open(mapmeta_filename, 'w') as outfile:
                            yaml.dump(mapmeta_yaml, outfile,
                                      default_flow_style=False, allow_unicode=True)

                        result = code_ok

                    except Exception:
                        pass

                    # cartographer map
                    try:
                        carto_service = node.create_client(
                            WorkModeRequest, 'openmover/localization/cartographer/request')

                        if carto_service.wait_for_service(timeout_sec=1):
                            carto_future = carto_service.call_async(WorkModeRequest.Request(
                                symbols.func_code['save_map'], map_save_path, current_func_params))

                            end = time.monotonic() + 5.0
                            while not carto_future.done() and time.monotonic() < end:
                                time.sleep(0.01)

                            carto_data = carto_future.result()
                            assert isinstance(
                                carto_data, WorkModeRequest.Response)

                            result = carto_data.result

                        node.destroy_client(carto_service)

                    except Exception:
                        pass

                    result = code_ok
                except Exception:
                    result = code_error
            else:
                result = code_error
    except Exception:
        pass

    lock.release()

    try:
        time.sleep(sleep_duration)
    except Exception:
        pass

    response.result = result
    return response


def protocol_wait_for_message(topic, msg_type, timeout=None):
    event = threading.Event()
    result = dict()

    def callback(msg):
        if 'msg' not in result:
            result['msg'] = msg
            event.set()

    sub = node.create_subscription(msg_type, topic, callback, 10)

    try:
        got = event.wait(timeout)
    finally:
        node.destroy_subscription(sub)

    if not got:
        raise RuntimeError('wait_for_message timed out on topic [%s]' % topic)

    return result['msg']


def apply_visualization_config(config_file):
    global enable_visualization

    if enable_visualization:
        # ROS 2: rviz2 无配置热切换服务，重启 rviz2 并加载新配置
        try:
            subprocess.call(['ros2', 'node', 'kill', '/rviz'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.Popen(['ros2', 'run', 'rviz2', 'rviz2', '-d', config_file],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except Exception:
            pass


def func_mode_server():
    global node

    global system_mode

    global current_mode_create_map
    global current_mode_nav_mode

    global current_func_load_map
    global current_func_arm
    global current_func_charger

    global map_save_path
    global map_saver_cmd
    global current_map_parsed_filename

    global enable_visualization
    global visualization_config_file_idle
    global visualization_config_file_working
    global visualization_config_file_working_nomap

    # sudo -n：无密码 sudo 时正常执行；否则立即失败而不阻塞节点启动
    if os.system('sudo -n renice 10 ' + str(os.getpid()) + ' >/dev/null 2>&1') != 0:
        print('%s：优先级降低失败。' % TAG)
    else:
        print('%s：优先级降低成功。' % TAG)

    rclpy.init()

    node = rclpy.create_node(NODE_NAME)

    print('%s：节点已启动。' % TAG)

    system_mode = node.declare_parameter('system_mode', 0).value

    # ROS 2：无全局参数服务器，将 use_sim_time 以启动参数转发给子启动文件
    use_sim_time_arg = 'true' if system_mode == 0 else 'false'

    launch_file_create_map = node.declare_parameter(
        'launch_file_create_map', '').value
    launch_file_nav_mode = node.declare_parameter(
        'launch_file_nav_mode', '').value

    launch_file_load_map = node.declare_parameter(
        'launch_file_load_map', '').value

    map_save_path = node.declare_parameter('nav_map_save_path', '').value

    if system_mode == 0:
        map_save_path += 'simulation/'
    elif system_mode == 1:
        map_save_path += 'real-world/'

    enable_visualization = node.declare_parameter(
        'enable_visualization', False).value
    visualization_config_file_idle = node.declare_parameter(
        'visualization_config_file_idle', '').value
    visualization_config_file_working = node.declare_parameter(
        'visualization_config_file_working', '').value
    visualization_config_file_working_nomap = node.declare_parameter(
        'visualization_config_file_working_nomap', '').value

    _ = node.create_service(
        WorkModeRequest, 'openmover/server/set_func_mode', service_callback)

    # 后台自旋线程处理服务回调
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()

    launch_create_map = launch_manager.LaunchHandle(
        launch_file_create_map, name='create_map')
    launch_nav_mode = launch_manager.LaunchHandle(
        launch_file_nav_mode, name='nav_mode')
    launch_load_map = launch_manager.LaunchHandle(
        launch_file_load_map, name='load_map')

    loop_period = 1.0 / config.config_server_loop_rate

    while rclpy.ok():
        lock.acquire()

        try:
            if current_mode_create_map != desired_mode_create_map:
                if desired_mode_create_map == code_start:
                    launch_create_map.start(args={'use_sim_time': use_sim_time_arg})
                elif desired_mode_create_map == code_exit:
                    launch_create_map.stop()
                current_mode_create_map = desired_mode_create_map

            if current_mode_nav_mode != desired_mode_nav_mode:
                if desired_mode_nav_mode == code_start:
                    launch_nav_mode.start(args={'use_sim_time': use_sim_time_arg})
                elif desired_mode_nav_mode == code_exit:
                    launch_nav_mode.stop()
                current_mode_nav_mode = desired_mode_nav_mode

            if current_func_load_map != desired_func_load_map:
                if desired_func_load_map == code_start:
                    # standard map
                    # get current home path name
                    current_home_path = os.environ['HOME']

                    # open yaml file
                    with open(map_save_path + current_func_params + ".yaml", 'r') as stream:
                        mapmeta_yaml = yaml.safe_load(stream)

                    mapmeta_yaml['image'] = str(mapmeta_yaml['image']).replace(
                        '$HOME_PATH', current_home_path)

                    current_map_parsed_filename = map_save_path + \
                        current_func_params + "_parsed.yaml"

                    with open(current_map_parsed_filename, 'w') as outfile:
                        yaml.dump(mapmeta_yaml, outfile,
                                  default_flow_style=False, allow_unicode=True)

                    launch_load_map.start(
                        args={'map_filename': current_map_parsed_filename,
                              'use_sim_time': use_sim_time_arg})

                    # cartographer map
                    try:
                        carto_service = node.create_client(
                            WorkModeRequest, 'openmover/localization/cartographer/request')

                        if carto_service.wait_for_service(timeout_sec=2):
                            carto_future = carto_service.call_async(WorkModeRequest.Request(
                                symbols.func_code['load_map'], map_save_path, current_func_params))

                            end = time.monotonic() + 5.0
                            while not carto_future.done() and time.monotonic() < end:
                                time.sleep(0.01)

                            carto_data = carto_future.result()
                            assert isinstance(
                                carto_data, WorkModeRequest.Response)

                            if carto_data.result == code_ok:
                                print('%s：Cartographer 地图切换成功。' % TAG)

                        node.destroy_client(carto_service)
                    except Exception:
                        pass
                elif desired_func_load_map == code_exit:
                    # cartographer map
                    try:
                        carto_service = node.create_client(
                            WorkModeRequest, 'openmover/localization/cartographer/request')

                        if carto_service.wait_for_service(timeout_sec=2):
                            carto_future = carto_service.call_async(WorkModeRequest.Request(
                                symbols.func_code['load_map'], '', code_undef))

                            end = time.monotonic() + 5.0
                            while not carto_future.done() and time.monotonic() < end:
                                time.sleep(0.01)

                            carto_data = carto_future.result()
                            assert isinstance(
                                carto_data, WorkModeRequest.Response)

                            if carto_data.result == code_ok:
                                print('%s：Cartographer 已关闭。' % TAG)

                        node.destroy_client(carto_service)
                    except Exception:
                        pass

                    # standard map
                    launch_load_map.stop()

                    try:
                        os.remove(current_map_parsed_filename)
                    except Exception:
                        pass
                current_func_load_map = desired_func_load_map
        except Exception:
            pass

        lock.release()

        if rclpy.ok():
            try:
                time.sleep(loop_period)
            except KeyboardInterrupt:
                print('%s：节点即将关闭。' % TAG)

                if system_mode == 0:
                    os.system('pkill gzserver')
                    os.system('pkill gzclient')
        else:
            break

    launch_create_map.stop()
    launch_nav_mode.stop()
    launch_load_map.stop()


if __name__ == "__main__":
    func_mode_server()
