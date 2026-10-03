#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 2023-6-24 0.0.0.1A

import os
import subprocess
from threading import Lock

import roslaunch
import rospy
import symbols
import yaml
from nav_msgs.msg import OccupancyGrid
from rviz.srv import SendFilePath, SendFilePathRequest
from openmover_msgs.srv import (work_mode_request, work_mode_requestRequest,
                               work_mode_requestResponse)
from std_msgs.msg import String

import config

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


def service_callback(req):
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

    assert isinstance(req, work_mode_requestRequest)

    lock.acquire()

    sleep_duration = config.config_switch_wait_duration

    try:
        if req.mode == symbols.mode_code['create_map']:
            if req.cmd == code_start:
                desired_mode_create_map = code_start
                desired_mode_nav_mode = code_exit
                apply_visualization_config(visualization_config_file_working)
            elif req.cmd == code_exit or req.cmd == code_cancel:
                desired_mode_create_map = code_exit
                apply_visualization_config(visualization_config_file_idle)
            result = code_ok
        elif req.mode == symbols.mode_code['nav_to']:
            if req.cmd == code_start:
                desired_mode_nav_mode = code_start
                desired_mode_create_map = code_exit
                apply_visualization_config(visualization_config_file_working)
            elif req.cmd == code_exit or req.cmd == code_cancel:
                desired_mode_nav_mode = code_exit
                apply_visualization_config(visualization_config_file_idle)
            result = code_ok

        if req.mode == symbols.func_code['load_map']:
            if req.cmd == code_start:
                if req.params != symbols.cmd_code['undef']:
                    current_func_params = req.params
                    desired_func_load_map = code_start
                    apply_visualization_config(
                        visualization_config_file_working)
                else:
                    sleep_duration = 0.0
                    apply_visualization_config(
                        visualization_config_file_working_nomap)
            elif req.cmd == code_exit or req.cmd == code_cancel:
                desired_func_load_map = code_exit
            result = code_ok
        elif req.mode == symbols.func_code['save_map']:
            sleep_duration = 0.0
            if current_mode_create_map == code_start or\
                    current_mode_nav_mode == code_start:
                try:
                    current_func_params = req.params

                    # standard map
                    try:
                        rospy.wait_for_message(
                            'openmover/mapping/map', OccupancyGrid, timeout=1)

                        map_filename = map_save_path + current_func_params
                        mapmeta_filename = map_filename + ".yaml"

                        map_saver_cmd = "rosrun map_server map_saver -f " + \
                            map_filename + " map:=openmover/mapping/map"
                        node = subprocess.Popen(map_saver_cmd, shell=True)
                        node.wait()

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

                    except rospy.exceptions.ROSException:
                        pass

                    # cartographer map
                    try:
                        rospy.wait_for_service(
                            'openmover/localization/cartographer/request', timeout=1)
                        carto_service = rospy.ServiceProxy(
                            'openmover/localization/cartographer/request', work_mode_request)

                        carto_data = carto_service.call(work_mode_requestRequest(
                            symbols.func_code['save_map'], map_save_path, current_func_params))
                        assert isinstance(
                            carto_data, work_mode_requestResponse)

                        result = carto_data.result

                    except rospy.exceptions.ROSException:
                        pass

                    result = code_ok
                except rospy.exceptions.ROSException:
                    result = code_error
            else:
                result = code_error
    except Exception:
        pass

    lock.release()

    try:
        rospy.sleep(sleep_duration)
    except rospy.exceptions.ROSException:
        pass

    return work_mode_requestResponse(result)


def apply_visualization_config(config_file):
    global enable_visualization

    if enable_visualization:
        try:
            rospy.wait_for_service(
                'rviz/load_config_discarding_changes', timeout=2)

            rviz_config_service = rospy.ServiceProxy(
                'rviz/load_config_discarding_changes', SendFilePath)

            rviz_config_service.call(SendFilePathRequest(String(config_file)))
        except rospy.exceptions.ROSException:
            pass


def func_mode_server():
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

    if os.system('sudo renice 10 ' + str(os.getpid())) != 0:
        rospy.logwarn('%s：优先级降低失败。' % TAG)
    else:
        rospy.logout('%s：优先级降低成功。' % TAG)

    rospy.init_node(NODE_NAME, anonymous=True)

    rospy.logout('%s：节点已启动。' % TAG)

    system_mode = rospy.get_param('~system_mode')

    launch_file_create_map = rospy.get_param('~launch_file_create_map')
    launch_file_nav_mode = rospy.get_param('~launch_file_nav_mode')

    launch_file_load_map = rospy.get_param('~launch_file_load_map')

    map_save_path = rospy.get_param('~nav_map_save_path')

    if system_mode == 0:
        map_save_path += 'simulation/'
    elif system_mode == 1:
        map_save_path += 'real-world/'

    enable_visualization = rospy.get_param('~enable_visualization')
    visualization_config_file_idle = rospy.get_param(
        '~visualization_config_file_idle')
    visualization_config_file_working = rospy.get_param(
        '~visualization_config_file_working')
    visualization_config_file_working_nomap = rospy.get_param(
        '~visualization_config_file_working_nomap')

    _ = rospy.Service(
        'openmover/server/set_func_mode', work_mode_request, service_callback)

    uuid = roslaunch.rlutil.get_or_generate_uuid(None, False)
    roslaunch.configure_logging(uuid)

    launch_create_map = roslaunch.parent.ROSLaunchParent(
        uuid, [launch_file_create_map])
    launch_nav_mode = roslaunch.parent.ROSLaunchParent(
        uuid, [launch_file_nav_mode])

    launch_load_map = roslaunch.parent.ROSLaunchParent(
        uuid, [launch_file_load_map])

    rate = rospy.Rate(config.config_server_loop_rate)

    while not rospy.is_shutdown():
        lock.acquire()

        try:
            if current_mode_create_map != desired_mode_create_map:
                if desired_mode_create_map == code_start:
                    launch_create_map = roslaunch.parent.ROSLaunchParent(
                        uuid, [launch_file_create_map])
                    launch_create_map.start()
                elif desired_mode_create_map == code_exit:
                    try:
                        server = launch_create_map.server.server
                        launch_create_map.shutdown()
                        if server:
                            server.shutdown()
                    except Exception:
                        pass
                current_mode_create_map = desired_mode_create_map

            if current_mode_nav_mode != desired_mode_nav_mode:
                if desired_mode_nav_mode == code_start:
                    launch_nav_mode = roslaunch.parent.ROSLaunchParent(
                        uuid, [launch_file_nav_mode])
                    launch_nav_mode.start()
                elif desired_mode_nav_mode == code_exit:
                    try:
                        server = launch_nav_mode.server.server
                        launch_nav_mode.shutdown()
                        if server:
                            server.shutdown()
                    except Exception:
                        pass
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

                    cli_args = [launch_file_load_map,
                                'map_filename:=' + current_map_parsed_filename]
                    roslaunch_args = cli_args[1:]
                    roslaunch_file = [
                        (roslaunch.rlutil.resolve_launch_arguments(cli_args)[0], roslaunch_args)]
                    launch_load_map = roslaunch.parent.ROSLaunchParent(
                        uuid, roslaunch_file)
                    launch_load_map.start()

                    # cartographer map
                    try:
                        rospy.wait_for_service(
                            'openmover/localization/cartographer/request', timeout=2)
                        carto_service = rospy.ServiceProxy(
                            'openmover/localization/cartographer/request', work_mode_request)

                        carto_data = carto_service.call(work_mode_requestRequest(
                            symbols.func_code['load_map'], map_save_path, current_func_params))
                        assert isinstance(
                            carto_data, work_mode_requestResponse)

                        if carto_data.result == code_ok:
                            rospy.logout('%s：Cartographer 地图切换成功。' % TAG)
                    except rospy.exceptions.ROSException:
                        pass
                elif desired_func_load_map == code_exit:
                    # cartographer map
                    try:
                        rospy.wait_for_service(
                            'openmover/localization/cartographer/request', timeout=2)
                        carto_service = rospy.ServiceProxy(
                            'openmover/localization/cartographer/request', work_mode_request)

                        carto_data = carto_service.call(work_mode_requestRequest(
                            symbols.func_code['load_map'], '', code_undef))
                        assert isinstance(
                            carto_data, work_mode_requestResponse)

                        if carto_data.result == code_ok:
                            rospy.logout('%s：Cartographer 已关闭。' % TAG)
                    except rospy.exceptions.ROSException:
                        pass

                    # standard map
                    try:
                        server = launch_load_map.server.server
                        launch_load_map.shutdown()
                        if server:
                            server.shutdown()
                    except Exception:
                        pass

                    try:
                        os.remove(current_map_parsed_filename)
                    except Exception:
                        pass
                current_func_load_map = desired_func_load_map
        except Exception:
            pass

        lock.release()

        if not rospy.is_shutdown():
            try:
                rate.sleep()
            except rospy.exceptions.ROSException:
                rospy.logwarn('%s：节点即将关闭。' % TAG)

                if system_mode == 0:
                    os.system('pkill gzserver')
                    os.system('pkill gzclient')
        else:
            break


if __name__ == "__main__":
    func_mode_server()
