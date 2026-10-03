#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 2023-6-24 0.0.0.2A


from threading import Lock

import config
import roslaunch
import rospy
import symbols
from cartographer_ros_msgs.msg import StatusCode
from cartographer_ros_msgs.srv import (WriteState, WriteStateRequest,
                                       WriteStateResponse)

from openmover_msgs.srv import (work_mode_request, work_mode_requestRequest,
                            work_mode_requestResponse)

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


def service_callback(req):
    global desired_pbstream_filename
    global desired_pbstream_name

    global desired_area_name

    global lock

    result = code_error

    assert isinstance(req, work_mode_requestRequest)

    lock.acquire()

    try:
        if req.mode == symbols.func_code['load_map'] and localization_mode:
            desired_pbstream_name = req.params
            desired_area_name = req.params
            desired_pbstream_filename = req.cmd + req.params + ".pbstream"

            result = code_ok
        elif req.mode == symbols.func_code['save_map'] and not localization_mode:
            try:
                rospy.wait_for_service(
                    'openmover/mapping/write_state/request', timeout=10)
                write_pbstream_service = rospy.ServiceProxy(
                    'openmover/mapping/write_state/request', WriteState)

                pbstream_filename = req.cmd + req.params + ".pbstream"

                write_pbstream_data = write_pbstream_service.call(
                    WriteStateRequest(pbstream_filename, False))
                assert isinstance(write_pbstream_data, WriteStateResponse)

                if write_pbstream_data.status.code == StatusCode.OK:
                    result = code_ok
            except Exception:
                pass
    except Exception:
        pass

    lock.release()

    if req.mode != symbols.func_code['save_map']:
        try:
            rospy.sleep(config.config_switch_wait_duration)
        except rospy.exceptions.ROSException:
            pass

    return work_mode_requestResponse(result)


def cartographer_server():
    global current_pbstream_filename
    global desired_pbstream_filename
    global localization_mode

    global lock

    rospy.init_node(NODE_NAME, anonymous=True)

    rospy.logout('%s：节点已启动。' % TAG)

    localization_mode = rospy.get_param('~localization_mode')
    launch_file_carto_localization = rospy.get_param(
        '~launch_file_cartographer')

    _ = rospy.Service(
        'openmover/localization/cartographer/request', work_mode_request, service_callback)

    if localization_mode:
        uuid = roslaunch.rlutil.get_or_generate_uuid(None, False)
        roslaunch.configure_logging(uuid)
        launch_carto_localization = roslaunch.parent.ROSLaunchParent(
            uuid, [launch_file_carto_localization])

    rate = rospy.Rate(config.config_server_loop_rate)

    while not rospy.is_shutdown():
        lock.acquire()

        try:
            if current_pbstream_filename != desired_pbstream_filename:
                if localization_mode:
                    try:
                        server = launch_carto_localization.server.server
                        launch_carto_localization.shutdown()
                        if server:
                            server.shutdown()
                    except Exception:
                        pass

                    if desired_pbstream_name != code_undef:
                        rospy.logout('%s：加载设置文件：%s。' %
                                     (TAG, str(desired_area_name + ".lua")))

                        rospy.logout('%s：加载地图：%s。' %
                                     (TAG, str(desired_pbstream_filename)))

                        cli_args = [launch_file_carto_localization,
                                    'pbstream_filename:=' + desired_pbstream_filename,
                                    'config_basename:=' + desired_area_name + ".lua"]
                        roslaunch_args = cli_args[1:]
                        roslaunch_file = [
                            (roslaunch.rlutil.resolve_launch_arguments(cli_args)[0], roslaunch_args)]
                        launch_carto_localization = roslaunch.parent.ROSLaunchParent(
                            uuid, roslaunch_file)
                        launch_carto_localization.start()
                    current_pbstream_filename = desired_pbstream_filename
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
    cartographer_server()
