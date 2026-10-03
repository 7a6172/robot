#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 2022-6-2 0.0.0.7A

from threading import Lock

import config
import roslaunch
import rospy
import symbols
from openmover_msgs.srv import work_mode_request, work_mode_requestRequest, work_mode_requestResponse

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


def service_callback(req):
    global current_launch
    global current_command

    global lock

    result = code_error

    assert isinstance(req, work_mode_requestRequest)

    lock.acquire()

    try:
        if req.cmd == code_start:
            if not req.mode in launch_files:
                launch_file = launch_file_default
            else:
                launch_file = launch_files[req.mode]
            current_launch = roslaunch.parent.ROSLaunchParent(
                uuid, [launch_file])
            current_command = code_start

            rospy.loginfo("%s：选择启动的导航策略启动文件：%s。" % (TAG, str(launch_file)))
        elif req.cmd == code_exit or req.cmd == code_cancel:
            current_command = code_exit
        result = code_ok
    except Exception:
        pass

    lock.release()

    try:
        rospy.sleep(config.config_switch_wait_duration)
    except rospy.exceptions.ROSException:
        pass

    return work_mode_requestResponse(result)


def nav_area_server():
    global uuid

    global current_command
    global launch_files
    global launch_file_default

    global lock

    rospy.init_node(NODE_NAME, anonymous=True)

    rospy.logout('%s：节点已启动。' % TAG)

    launch_file_default = rospy.get_param('~launch_file_default')

    for nav_mode_name in config.config_area_list:
        if rospy.has_param('~launch_file_' + nav_mode_name):
            launch_files[nav_mode_name] = rospy.get_param(
                '~launch_file_' + nav_mode_name)
        else:
            launch_files[nav_mode_name] = launch_file_default

    _ = rospy.Service(
        'openmover/server/set_nav_area', work_mode_request, service_callback)

    uuid = roslaunch.rlutil.get_or_generate_uuid(None, False)
    roslaunch.configure_logging(uuid)

    rate = rospy.Rate(config.config_server_loop_rate)

    while not rospy.is_shutdown():
        lock.acquire()

        try:
            if current_command == code_start:
                try:
                    if current_launch != None:
                        current_launch.start()
                except Exception:
                    pass
                current_command = code_undef
            elif current_command == code_exit:
                try:
                    if current_launch != None:
                        server = current_launch.server.server
                        current_launch.shutdown()
                        if server:
                            server.shutdown()
                except Exception:
                    pass
                current_command = code_undef
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
    nav_area_server()
