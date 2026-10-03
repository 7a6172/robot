#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 2022-6-2 0.0.0.10A

import os
from threading import Lock

import config
import roslaunch
import rospy
import symbols

from openmover_msgs.srv import (work_mode_request, work_mode_requestRequest,
                            work_mode_requestResponse)

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


def service_callback(req):
    global desired_mode_map

    global desired_area_name

    global lock

    mode_map_exists = code_exit

    result = code_error

    assert isinstance(req, work_mode_requestRequest)

    lock.acquire()

    desired_area_name = req.params

    try:
        if req.mode.find(mode_map) != -1:
            mode_map_exists = code_start

        if current_mode_map == code_start and mode_map_exists == code_exit:
            mode_map_exists = code_start

        if req.mode == code_undef:
            mode_map_exists = code_exit

        if req.mode != code_undef and\
                current_mode_map == mode_map_exists:
            lock.release()

            result = code_ok
        else:
            desired_mode_map = mode_map_exists

            lock.release()

            result = code_ok

            try:
                rospy.sleep(config.config_switch_wait_duration)
            except rospy.exceptions.ROSException:
                pass
    except Exception:
        lock.release()

    return work_mode_requestResponse(result)


def localization_mode_server():
    global current_mode_map

    global lock

    if os.system('sudo renice 10 ' + str(os.getpid())) != 0:
        rospy.logwarn('%s：优先级降低失败。' % TAG)
    else:
        rospy.logout('%s：优先级降低成功。' % TAG)

    rospy.init_node(NODE_NAME, anonymous=True)

    rospy.logout('%s：节点已启动。' % TAG)

    system_mode = rospy.get_param('~system_mode')

    launch_file_map = rospy.get_param('~launch_file_map')

    _ = rospy.Service(
        'openmover/server/set_localization_mode', work_mode_request, service_callback)

    uuid = roslaunch.rlutil.get_or_generate_uuid(None, False)
    roslaunch.configure_logging(uuid)

    launch_map = roslaunch.scriptapi.ROSLaunch()
    launch_map.parent = roslaunch.parent.ROSLaunchParent(
        uuid, [launch_file_map])

    rate = rospy.Rate(config.config_server_loop_rate)

    while not rospy.is_shutdown():
        lock.acquire()

        try:
            if current_mode_map != desired_mode_map:
                if desired_mode_map == code_start:
                    cli_args = [launch_file_map,
                                'system_mode:=' + str(system_mode),
                                'area_name:=' + str(desired_area_name)]
                    roslaunch_args = cli_args[1:]
                    roslaunch_file = [
                        (roslaunch.rlutil.resolve_launch_arguments(cli_args)[0], roslaunch_args)]
                    launch_map = roslaunch.parent.ROSLaunchParent(
                        uuid, roslaunch_file)
                    launch_map.start()
                elif desired_mode_map == code_exit:
                    try:
                        server = launch_map.server.server
                        launch_map.shutdown()
                        if server:
                            server.shutdown()
                    except Exception:
                        pass
                current_mode_map = desired_mode_map

            # 预留
            last_desired_area_name = desired_area_name
        except Exception:
            pass

        lock.release()

        if not rospy.is_shutdown():
            try:
                rate.sleep()
            except rospy.exceptions.ROSException:
                rospy.logwarn('%s：节点即将关闭。' % TAG)
        else:
            break


if __name__ == "__main__":
    localization_mode_server()
