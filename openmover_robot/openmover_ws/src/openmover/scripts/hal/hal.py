# -*- coding: utf-8 -*-
from threading import Lock

import logger
import protocol
import rospy
import utils
from geometry_msgs.msg import (Pose, PoseStamped, PoseWithCovarianceStamped,
                               Twist)
from nav_msgs.msg import Path
from navfn.srv import MakeNavPlan, MakeNavPlanRequest, MakeNavPlanResponse
from std_msgs.msg import Float32
from openmover_msgs.msg import *
from openmover_msgs.srv import *
from relocalization_toolbox_msgs.srv import *
from auto_mapping_toolbox_msgs.srv import *
from auto_mapping_toolbox_msgs.msg import *
from symbols import *

from config import *

# state part
initialized = False
current_mode = mode_code['undef']
current_area = mode_code['undef']

# record part
started_function_dict = dict()
pose_point_dict = dict()
planned_path_dict = dict()
arm_program_before_back = str()

# goto tag const part
desired_back_tag = None
current_back_tag = set()

# initialize uninit lock
uninitialize_lock = Lock()

# back tag part


def back(tag):
    ''' set back tag '''
    global current_back_tag
    global desired_back_tag
    if tag != None:
        logger.logwarn(
            handler='hal', text='System will skip all functions without tag [%s].' % tag)
        desired_back_tag = tag
        current_back_tag.clear()


def set_back_tag(tag):
    ''' set back tag '''
    global current_back_tag
    if tag != None:
        logger.logwarn(
            handler='hal', text='A new back tag [%s] has been setted.' % tag)
        current_back_tag.add(tag)


def __executable__(initialized_required=True):
    ''' check if to execute '''
    if initialized_required and not initialized:
        logger.logwarn(
            handler='hal', text='Please initialize the system.')
        return False

    global current_back_tag
    global desired_back_tag
    return desired_back_tag in current_back_tag or desired_back_tag == None

# logic part


def if_to_continue(result, latch=False, inner=False):
    ''' check if to continue '''

    def check_condition(result, latch):
        try:
            if isinstance(result, tuple):
                result = result[0]

            if result in code_to_exit:
                logger.logerror(
                    handler='hal', text='A fatal error occurred or an exit request received, the system will exit.')
                call_cancel(inner=True)

                try:
                    rospy.sleep(1.0)
                except Exception:
                    pass

                protocol.set_flow_state(state=cmd_code['error'])

                try:
                    rospy.sleep(1.0)
                except Exception:
                    pass

                uninitialize(error=True, inner=False)

            if desired_back_tag != None:
                return cmd_code['continue']

            cmd = protocol.receive_cmd(latch=latch)

            if protocol.if_to_back(cmd):
                logger.logwarn(
                    handler='hal', text='On receiving a back request, the robot will back to the starting point.')
                return cmd_code['back']

            if protocol.if_to_pause(cmd):
                logger.loginfo(
                    handler='hal', text='On receiving a pause request, the system will pause.')
                call_pause(inner=True)

            while not protocol.if_to_continue(cmd):
                cmd = protocol.receive_cmd(latch=latch)

                if protocol.if_to_back(cmd):
                    logger.logwarn(
                        handler='hal', text='On receiving a back request, the robot will back to the starting point.')
                    return cmd_code['back']

                try:
                    rospy.sleep(0.5)
                except Exception:
                    pass

            logger.loginfo(
                handler='hal', text='On receiving a continue request, the system will continue.')

            if (initialized):
                call_continue(inner=True)

            return cmd_code['continue']
        except Exception:
            logger.logerror(
                handler='hal', text='A fatal error occurred or an exit request received, the system will exit.')
            call_cancel(inner=True)

            try:
                rospy.sleep(1.0)
            except Exception:
                pass

            protocol.set_flow_state(state=cmd_code['error'])

            try:
                rospy.sleep(1.0)
            except Exception:
                pass

            uninitialize(error=True, inner=False)

    if __executable__(initialized_required=False):
        logger.loginfo(
            handler='hal', text='The script engine is confirming the execution status...')

        ret = check_condition(result, latch)

        logger.logdebug(
            handler='if_to_continue', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def __wait_for_command__(latch=False, inner=False):
    ''' wait for the command '''

    def check_condition(latch):
        return if_to_continue(result=None, latch=latch, inner=True)

    if __executable__():
        logger.loginfo(
            handler='hal', text='The script engine is waiting for the execution feedback...')

        ret = check_condition(latch)

        logger.logdebug(
            handler='__wait_for_command__', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def join(inner=False):
    logger.loginfo(
        handler='join', text='This session has joined.')

    rate = rospy.Rate(5.0)

    while not rospy.is_shutdown():
        if not rospy.is_shutdown():
            try:
                rate.sleep()
            except Exception:
                pass
        else:
            break

    ret = cmd_code['ok']

    if inner:
        return ret


def param(name, default):
    logger.loginfo(
        handler='param', text='Getting parameter named [%s] with default value [%s].' % (str(name), str(default)))

    ret = default

    try:
        if name != None and default != None:
            ret = rospy.get_param(name, default)
    except Exception:
        pass

    logger.logdebug(
        handler='param', text='The result of function is [%s].' % str(ret))

    return ret

# self test part


def __self_test__(inner=False):
    ''' run self test '''

    def check_condition():
        ret = cmd_code['error']

        if (config_func_enable_self_test):
            try:
                devices = list()
                availables = list()

                available_func_counter = 0

                if (len(config_func_self_test) == len(config_func_self_test_checklist)):
                    for name in func_code:
                        if name in config_func_uninit_keepalive:
                            call_robot_function(
                                name=name, action=cmd_code['finish'])

                    for name in config_func_self_test:
                        logger.loginfo(
                            handler='__self_test__', text='The robot is doing the self-test of device [%s]...' % str(name))

                        devices.append(name)

                        if (name in func_code):
                            call_robot_function(
                                name=name, action=cmd_code['start'])

                        try:
                            if (name in func_code):
                                rospy.wait_for_service(
                                    config_func_self_test_checklist[name], timeout=config_func_self_test_wait_duration)
                            else:
                                rospy.wait_for_message(
                                    config_func_self_test_checklist[name], config_func_self_test_typelist[name], timeout=config_func_self_test_wait_duration)

                            availables.append(True)

                            available_func_counter = available_func_counter + 1

                            logger.loginfo(
                                handler='__self_test__', text='Device [%s] is available.' % str(name))
                        except Exception:
                            availables.append(False)

                            logger.logerror(
                                handler='__self_test__', text='Device [%s] is unavailable.' % str(name))

                        if (name in func_code):
                            call_robot_function(
                                name=name, action=cmd_code['finish'])

                    if (available_func_counter == len(devices)):
                        ret = cmd_code['ok']
            except Exception:
                logger.logerror(
                    handler='__self_test__', text='Robot manager is offline.')

                ret = cmd_code['error']
        else:
            ret = cmd_code['ok']

        return ret

    logger.loginfo(
        handler='__self_test__', text='The robot is doing the self-test...')

    ret = check_condition()

    if ret == cmd_code['ok']:
        logger.logdebug(
            handler='__self_test__', text='The result of function is [%s].' % str(ret))
    else:
        logger.logerror(
            handler='__self_test__', text='The result of function is [%s].' % str(ret))

        protocol.set_flow_state(
            flow_state_code['error'], 0, 0, 0)

        try:
            rospy.sleep(1.0)
        except Exception:
            pass

        logger.log_sys_uninit()

        exit()

    if inner:
        return ret


# initialization part


def initialize(mode=mode_code['nav_to'],
               area=None,
               try_relocalization=False,
               init_pose_name=None,
               init_pose_x=0, init_pose_y=0, init_pose_yaw=0,
               inner=False):
    ''' initialize the robot '''

    # start node
    def start_node(mode, area):
        global initialized

        if not initialized and mode in mode_code and area != None:
            try:
                initialized = True

                # apply init pose for mapping
                if initialized and mode == mode_code['create_map']:
                    logger.loginfo(
                        handler='initialize', text='Applying initial pose for mapping...')
                    switch_result = apply_pose_point(
                        x=0, y=0, yaw=0, inner=True)
                    initialized = switch_result == cmd_code['ok']

                # switch function mode
                logger.loginfo(
                    handler='initialize', text='Switching function mode...')
                switch_result = switch_mode(mode, inner=True)
                initialized = switch_result == cmd_code['ok']

                # switch area
                if initialized and mode == mode_code['nav_to']:
                    logger.loginfo(
                        handler='initialize', text='Switching navigation strategy mode...')
                    switch_result = switch_area_strategy(
                        area, bringup=True, inner=True)
                    initialized = switch_result == cmd_code['ok']

                # apply map
                if initialized and mode == mode_code['nav_to']:
                    logger.loginfo(
                        handler='initialize', text='Applying navigation map...')
                    switch_result = apply_map(area, inner=True)
                    initialized = switch_result == cmd_code['ok']

                # apply init pose for navigation
                if initialized and mode == mode_code['nav_to']:
                    if try_relocalization:
                        logger.loginfo(
                            handler='initialize', text='Finding initial pose for localization...')
                        relocalization_result = call_relocalization(inner=True)
                        initialized = relocalization_result == cmd_code['ok']
                    else:
                        logger.loginfo(
                            handler='initialize', text='Applying initial pose for localization...')
                        switch_result = apply_pose_point(init_pose_name, init_pose_x,
                                                         init_pose_y, init_pose_yaw, inner=True)
                        initialized = switch_result == cmd_code['ok']

                # switch velocity control mode
                if initialized:
                    logger.loginfo(
                        handler='initialize', text='Switching velocity control mode...')
                    switch_result = switch_velocity_mode(True, inner=True)
                    initialized = switch_result == cmd_code['ok']

                if initialized:
                    return cmd_code['ok']
                else:
                    uninitialize(error=True, inner=False)
                    return cmd_code['error']

            except Exception:
                uninitialize(error=True, inner=False)
                return cmd_code['error']
        return cmd_code['ok']

    if __executable__(initialized_required=False):
        __self_test__()

        logger.loginfo(
            handler='initialize', text='Initializing the system...')

        ret = start_node(mode, area)

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='initialize', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='initialize', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def uninitialize(error=False, inner=False):
    ''' uninitialize the robot '''

    def stop_node(error):
        global initialized
        global current_back_tag
        global desired_back_tag

        # stop auto mapping
        current_auto_mapping_state = get_auto_mapping_state(inner=True)
        if current_auto_mapping_state[0] != auto_mapping_state_ret_code['finish']:
            call_cancel_auto_mapping()
            try:
                rospy.sleep(1.0)
            except Exception:
                pass

        # send error state
        if (error):
            protocol.set_flow_state(state=cmd_code['error'])

            try:
                rospy.sleep(1.0)
            except Exception:
                pass

        # stop navigation
        if current_mode == mode_code['nav_to']:
            switch_result = switch_area_strategy(
                mode_code['undef'], inner=True)

        # turn off all devices
        for name in func_code:
            if name in started_function_dict and\
                    started_function_dict[name] == cmd_code['start'] and\
                    not name in config_func_uninit_keepalive:
                switch_result = call_robot_function(
                    name, cmd_code['finish'], inner=True)
                started_function_dict[name] = cmd_code['finish']

        # turn off map server
        if current_mode == mode_code['nav_to']:
            switch_result = apply_map(name=mode_code['undef'], inner=True)

        # switch to idle function mode
        switch_result = switch_mode(mode_code['undef'], inner=True)

        # switch velocity control mode
        switch_result = switch_velocity_mode(True, inner=True)

        # clear back tag
        desired_back_tag = None
        current_back_tag.clear()

        initialized = not switch_result == cmd_code['ok']

        logger.log_sys_uninit()

        return switch_result

    if __executable__(initialized_required=False):
        uninitialize_lock.acquire()

        logger.loginfo(
            handler='uninitialize', text='Uninitializing the system...')

        ret = stop_node(error)

        uninitialize_lock.release()
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner and not error:
        return ret

    try:
        exit()
    except Exception:
        exit()


# switch mode part


def switch_mode(mode, inner=False):
    ''' switch work mode '''

    # switch mode
    def switch_to():
        global current_mode

        if current_mode == mode_code['nav_to']:
            current_state = get_navigation_state(inner=True)

            if current_state[0] != nav_state_ret_code['reached'] and\
                    current_state[0] != cmd_code['error']:
                return cmd_code['busy']

        if initialized and mode in mode_code and current_mode != mode:
            try:
                rospy.wait_for_service(
                    'openmover/server/set_func_mode', timeout=config_service_wait_duration)

                work_mode_service = rospy.ServiceProxy(
                    'openmover/server/set_func_mode', work_mode_request)

                if mode != mode_code['undef']:
                    if current_mode == mode_code['undef']:
                        resp_start_mode = work_mode_service.call(
                            work_mode_requestRequest(mode, cmd_code['start'], ''))
                        assert isinstance(
                            resp_start_mode, work_mode_requestResponse)

                        if cmd_code[resp_start_mode.result] == cmd_code['ok']:
                            current_mode = mode

                            return cmd_code[resp_start_mode.result]
                    else:
                        resp_finish_mode = work_mode_service.call(
                            work_mode_requestRequest(current_mode, cmd_code['finish'], ''))
                        assert isinstance(resp_finish_mode,
                                          work_mode_requestResponse)

                        if cmd_code[resp_finish_mode.result] == cmd_code['ok']:
                            resp_start_mode = work_mode_service.call(
                                work_mode_requestRequest(mode, cmd_code['start'], ''))
                            assert isinstance(
                                resp_start_mode, work_mode_requestResponse)

                            if cmd_code[resp_start_mode.result] == cmd_code['ok']:
                                current_mode = mode

                            return cmd_code[resp_start_mode.result]
                else:
                    resp_finish_mode = work_mode_service.call(
                        work_mode_requestRequest(current_mode, cmd_code['finish'], ''))
                    assert isinstance(resp_finish_mode,
                                      work_mode_requestResponse)

                    if cmd_code[resp_finish_mode.result] == cmd_code['ok']:
                        current_mode = mode

                        return cmd_code[resp_finish_mode.result]
            except Exception:
                return cmd_code['error']
        elif current_mode == mode:
            return cmd_code['ok']

        return cmd_code['error']

    if __executable__():
        logger.loginfo(handler='switch_mode',
                       text='Switching mode to [%s]...' % mode)

        ret = switch_to()

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='switch_mode', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='switch_mode', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def switch_localization_mode(mode, area, inner=False):
    ''' switch localization mode '''

    # switch mode
    def switch_to(mode, area):
        try:
            assert isinstance(mode, str)
            if mode != mode_code['undef'] and mode.find(localization_mode['odom']) == -1:
                return cmd_code['error']

            rospy.wait_for_service(
                'openmover/server/set_localization_mode', timeout=config_service_wait_duration)

            work_mode_service = rospy.ServiceProxy(
                'openmover/server/set_localization_mode', work_mode_request)

            resp_start_mode = work_mode_service.call(
                work_mode_requestRequest(mode, cmd_code['start'], area))
            assert isinstance(resp_start_mode, work_mode_requestResponse)

            return cmd_code[resp_start_mode.result]
        except Exception:
            return cmd_code['error']

    if __executable__():
        logger.loginfo(handler='switch_localization_mode',
                       text='Switching localization mode to [%s] in area [%s]...' % (mode, area))

        ret = switch_to(mode, area)

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='switch_localization_mode', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='switch_localization_mode', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def switch_area_strategy(area=mode_code['undef'], bringup=False, inner=False):
    ''' switch strategy of navigation area '''

    # switch mode
    def switch_to(area, bringup):
        global current_area

        if current_mode == mode_code['nav_to'] and not bringup:
            current_state = get_navigation_state(inner=True)

            if current_state[0] != nav_state_ret_code['reached'] and\
                    current_state[0] != cmd_code['error']:
                return cmd_code['busy']

        if initialized and (current_area != area or bringup):
            try:
                rospy.wait_for_service(
                    'openmover/server/set_nav_area', timeout=config_service_wait_duration)

                area_mode_service = rospy.ServiceProxy(
                    'openmover/server/set_nav_area', work_mode_request)

                if area != mode_code['undef']:
                    if current_area == mode_code['undef']:
                        # switch localization sources
                        if not (area in config_area_localization_sources):
                            result = switch_localization_mode(
                                config_area_localization_sources['default'],
                                area,
                                inner=True
                            )
                        else:
                            result = switch_localization_mode(
                                config_area_localization_sources[area],
                                area,
                                inner=True
                            )

                        # switch navigation mode
                        if result == cmd_code['ok']:
                            resp_start_mode = area_mode_service.call(
                                work_mode_requestRequest(area, cmd_code['start'], ''))
                            assert isinstance(
                                resp_start_mode, work_mode_requestResponse)

                            if cmd_code[resp_start_mode.result] == cmd_code['ok']:
                                current_area = area

                                return cmd_code[resp_start_mode.result]
                        else:
                            return cmd_code['error']
                    else:
                        # switch localization sources
                        result = switch_localization_mode(
                            mode_code['undef'],
                            area,
                            inner=True
                        )

                        if result == cmd_code['ok']:
                            if not (area in config_area_localization_sources):
                                result = switch_localization_mode(
                                    config_area_localization_sources['default'],
                                    area,
                                    inner=True
                                )
                            else:
                                result = switch_localization_mode(
                                    config_area_localization_sources[area],
                                    area,
                                    inner=True
                                )

                        if result == cmd_code['ok']:
                            resp_finish_mode = area_mode_service.call(
                                work_mode_requestRequest(current_area, cmd_code['finish'], ''))
                            assert isinstance(
                                resp_finish_mode, work_mode_requestResponse)

                            if cmd_code[resp_finish_mode.result] == cmd_code['ok']:
                                resp_start_mode = area_mode_service.call(
                                    work_mode_requestRequest(area, cmd_code['start'], ''))
                                assert isinstance(
                                    resp_start_mode, work_mode_requestResponse)

                                if cmd_code[resp_start_mode.result] == cmd_code['ok']:
                                    current_area = area

                                return cmd_code[resp_start_mode.result]
                        else:
                            return cmd_code['error']
                else:
                    # switch localization sources
                    result = switch_localization_mode(
                        mode_code['undef'],
                        area,
                        inner=True
                    )

                    # switch navigation mode
                    if result == cmd_code['ok']:
                        resp_finish_mode = area_mode_service.call(
                            work_mode_requestRequest(current_area, cmd_code['finish'], ''))
                        assert isinstance(resp_finish_mode,
                                          work_mode_requestResponse)

                        if cmd_code[resp_finish_mode.result] == cmd_code['ok']:
                            current_area = area

                            return cmd_code[resp_finish_mode.result]
                    else:
                        return cmd_code['error']
            except Exception:
                return cmd_code['error']
        elif current_area == area:
            return cmd_code['ok']

        return cmd_code['error']

    if __executable__():
        logger.loginfo(handler='switch_area_strategy',
                       text='Switching navigation strategy mode to [%s]...' % area)

        ret = switch_to(area, bringup)

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='switch_area_strategy', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='switch_area_strategy', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def switch_velocity_mode(manual_mode=True, inner=False):
    ''' switch velocity mode '''

    # switch mode
    def switch_to(manual_mode):
        global current_area

        if initialized:
            try:
                rospy.wait_for_service(
                    'openmover/control/cmd_vel_mode/request', timeout=config_service_wait_duration)

                cmd_vel_mode_service = rospy.ServiceProxy(
                    'openmover/control/cmd_vel_mode/request', cmd_vel_mode_request)

                cmd_vel_mode_data = cmd_vel_mode_service.call(
                    cmd_vel_mode_requestRequest(manual_mode))
                assert isinstance(cmd_vel_mode_data,
                                  cmd_vel_mode_requestResponse)

                return cmd_code[cmd_vel_mode_data.result]
            except Exception:
                return cmd_code['error']

        return cmd_code['error']

    if __executable__():
        logger.loginfo(handler='switch_velocity_mode',
                       text='Switching velocity manual control mode to [%s]...' % str(manual_mode))

        ret = switch_to(manual_mode)

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='switch_velocity_mode', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='switch_velocity_mode', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret

# get data part


def get_navigation_state(inner=False):
    ''' get robot state '''
    ''' state, {x:x, y:y, yaw:yaw, vx:vx, vyaw:vyaw, cmd_vx:cmd_vx, cmd_vyaw:cmd_vyaw} '''

    # subscribe the topic
    def get_data():
        if initialized:
            try:
                # get navigation state from buffer
                nav_state_data = protocol.get_navigation_state()
                assert isinstance(nav_state_data, nav_to_state)

                if (utils.current_ros_time() - nav_state_data.header.stamp > rospy.Duration(secs=1)):
                    logger.loginfo(
                        handler='get_navigation_state', text='Buffer data timeout, getting state now...')
                    nav_state_data = rospy.wait_for_message(
                        'openmover/navigation/state', nav_to_state, timeout=2)
                    assert isinstance(nav_state_data, nav_to_state)

                if (utils.current_ros_time() - nav_state_data.header.stamp > rospy.Duration(secs=1) and
                        nav_state_ret_code[nav_state_data.state] != nav_state_ret_code['error']):
                    # switch velocity control mode
                    switch_velocity_mode(True, inner=True)

                    return nav_state_ret_code['reached'], \
                        {'x': round(nav_state_data.pose.pose.position.x, 3),
                         'y': round(nav_state_data.pose.pose.position.y, 3),
                         'yaw': round(utils.deg_from_rad(utils.yaw_from_quaternion(
                             nav_state_data.pose.pose.orientation)), 3),
                         'vx': round(nav_state_data.twist.twist.linear.x, 3),
                         'vyaw': round(utils.deg_from_rad(nav_state_data.twist.twist.angular.z), 3),
                         'cmd_vx': round(nav_state_data.cmd_twist.twist.linear.x, 3),
                         'cmd_vyaw': round(utils.deg_from_rad(nav_state_data.cmd_twist.twist.angular.z), 3)}

                if (nav_state_ret_code[nav_state_data.state] == nav_state_ret_code['reached'] or
                        nav_state_ret_code[nav_state_data.state] == nav_state_ret_code['error']):
                    # wait for stopping
                    try:
                        rospy.sleep(1.0)
                    except Exception:
                        pass
                    # switch velocity control mode
                    switch_velocity_mode(True, inner=True)

                return nav_state_ret_code[nav_state_data.state], \
                    {'x': round(nav_state_data.pose.pose.position.x, 3),
                     'y': round(nav_state_data.pose.pose.position.y, 3),
                     'yaw': round(utils.deg_from_rad(utils.yaw_from_quaternion(
                         nav_state_data.pose.pose.orientation)), 3),
                     'vx': round(nav_state_data.twist.twist.linear.x, 3),
                     'vyaw': round(utils.deg_from_rad(nav_state_data.twist.twist.angular.z), 3),
                     'cmd_vx': round(nav_state_data.cmd_twist.twist.linear.x, 3),
                     'cmd_vyaw': round(utils.deg_from_rad(nav_state_data.cmd_twist.twist.angular.z), 3)}
            except Exception:
                return nav_state_ret_code['reached'], {'x': 0, 'y': 0, 'yaw': 0, 'vx': 0, 'vyaw': 0, 'cmd_vx': 0, 'cmd_vyaw': 0}
        else:
            return cmd_code['error'], {'x': 0, 'y': 0, 'yaw': 0, 'vx': 0, 'vyaw': 0, 'cmd_vx': 0, 'cmd_vyaw': 0}

    if __executable__():
        logger.loginfo(handler='get_navigation_state',
                       text='Getting navigation state...')

        ret = get_data()

        if ret[0] != cmd_code['error']:
            logger.logdebug(
                handler='get_navigation_state', text='The result of function is [%s].' % str(ret[0]))
        else:
            logger.logwarn(
                handler='get_navigation_state', text='The result of function is [%s].' % str(ret[0]))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def get_localization_state(localization_source=localization_mode['map'], inner=False):
    ''' get robot pose '''
    ''' result, {x:x, y:y, yaw:yaw, conf:conf} '''

    # subscribe the topic
    def get_data(localization_source):
        if initialized:
            try:
                pose_data = PoseWithCovarianceStamped()
                conf_data = Float32()
                conf_data.data = 0.0

                if localization_source == localization_mode['odom']:
                    pose_data = rospy.wait_for_message(
                        'openmover/localization/odom', PoseWithCovarianceStamped, timeout=1)
                elif localization_source == localization_mode['map'] or localization_source == localization_mode['lio']:
                    pose_data = rospy.wait_for_message(
                        'openmover/localization/pose', PoseWithCovarianceStamped, timeout=1)
                    conf_data = rospy.wait_for_message(
                        'openmover/localization/confidence', Float32, timeout=2)
                else:
                    pose_data = rospy.wait_for_message(
                        'openmover/localization/pose', PoseWithCovarianceStamped, timeout=1)
                    conf_data = rospy.wait_for_message(
                        'openmover/localization/confidence', Float32, timeout=2)

                assert isinstance(pose_data, PoseWithCovarianceStamped)

                return cmd_code['ok'], \
                    {'x': pose_data.pose.pose.position.x,
                     'y': pose_data.pose.pose.position.y,
                     'yaw': utils.deg_from_rad(utils.yaw_from_quaternion(
                         pose_data.pose.pose.orientation)),
                     'conf': conf_data.data}
            except Exception:
                return cmd_code['error'], {'x': 0, 'y': 0, 'yaw': 0, 'conf': 0}
        else:
            return cmd_code['error'], {'x': 0, 'y': 0, 'yaw': 0, 'conf': 0}

    if __executable__():
        logger.loginfo(handler='get_localization_state',
                       text='Getting localization state...')

        ret = get_data(localization_source)

        if ret[0] == cmd_code['ok']:
            logger.logdebug(
                handler='get_localization_state', text='The result of function is [%s].' % str(ret))
        else:
            logger.logwarn(
                handler='get_localization_state', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def get_auto_mapping_state(inner=False):
    ''' get auto mapping state '''
    ''' result, area '''

    # subscribe the topic
    def get_data():
        if initialized:
            try:
                auto_mapping_state_data = auto_mapping_state()

                auto_mapping_state_data = rospy.wait_for_message(
                    'openmover/mapping/auto_mapping/state', auto_mapping_state, timeout=1)

                assert isinstance(auto_mapping_state_data, auto_mapping_state)

                return auto_mapping_state_ret_code[auto_mapping_state_data.state], auto_mapping_state_data.area
            except rospy.exceptions.ROSException:
                return auto_mapping_state_ret_code['finish'], 0
        else:
            return auto_mapping_state_ret_code['finish'], 0

    if __executable__():
        logger.loginfo(handler='get_auto_mapping_state',
                       text='Getting auto mapping state...')

        ret = get_data()

        logger.logdebug(
            handler='get_auto_mapping_state', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def get_value_from_host(key=None, inner=True):
    ''' get value from host '''
    ''' value '''

    # call the service send_flow_cmd
    def get_data(key):
        try:
            return protocol.send_flow_cmd(cmd=flow_cmd_code['get'], arg=key)
        except Exception:
            return None

    if __executable__():
        logger.loginfo(handler='get_value_from_host',
                       text='Getting value [%s] from host...' % key)

        ret = get_data(key)

        if ret != None:
            logger.logdebug(
                handler='get_value_from_host', text='The result of function is [%s].' % str(ret))
        else:
            logger.logwarn(
                handler='get_value_from_host', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        if ret == cmd_code['pass']:
            return None
        return ret

# create data part


def create_pose_point(name='pose',
                      x=None, y=None, yaw=None,
                      delete=False, inner=False):
    ''' save current pose point or create pose point '''
    ''' result '''

    # subscribe the topic
    def save_data(name, x, y, yaw, delete):
        global pose_point_dict

        if name != cmd_code['undef']:
            try:
                if delete:
                    if name != None and name in pose_point_dict:
                        del pose_point_dict[name]

                    return cmd_code['ok']
                else:
                    pose_data = PoseWithCovarianceStamped()

                    if x == None or y == None or yaw == None:
                        pose_data = rospy.wait_for_message(
                            'openmover/localization/pose', PoseWithCovarianceStamped, timeout=config_service_wait_duration)
                        assert isinstance(pose_data, PoseWithCovarianceStamped)
                    else:
                        pose_data.pose.pose.position.x = x
                        pose_data.pose.pose.position.y = y
                        pose_data.pose.pose.orientation = utils.quaternion_from_yaw(
                            utils.rad_from_deg(yaw))

                    pose_data.header.frame_id = "map"
                    pose_data.header.stamp = utils.current_ros_time()

                    logger.loginfo(handler='create_pose_point',
                                   text='Creating pose point named [%s] at [%s, %s, %s]...'
                                   % (name,
                                      str(round(pose_data.pose.pose.position.x, 3)), str(round(
                                          pose_data.pose.pose.position.y, 3)),
                                      str(round(utils.deg_from_rad(
                                          utils.yaw_from_quaternion(
                                              pose_data.pose.pose.orientation)), 3))))

                    pose_point_dict[name] = pose_data

                    return cmd_code['ok']
            except Exception:
                return cmd_code['error']
        else:
            return cmd_code['error']

    if __executable__(initialized_required=False):
        ret = save_data(name, x, y, yaw, delete)

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='create_pose_point', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='create_pose_point', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def create_map(name=current_area, inner=False):
    ''' create navigaion map '''
    ''' result '''

    # call the service
    def get_data(name):
        if initialized\
                and (current_mode == mode_code['create_map'] or
                     current_mode == mode_code['nav_to']):
            try:
                rospy.wait_for_service(
                    'openmover/server/set_func_mode', timeout=config_service_wait_duration)

                create_map_service = rospy.ServiceProxy(
                    'openmover/server/set_func_mode', work_mode_request)

                create_map_data = create_map_service.call(
                    work_mode_requestRequest(func_code['save_map'], cmd_code['start'], name))
                assert isinstance(create_map_data,
                                  work_mode_requestResponse)

                return cmd_code[create_map_data.result]
            except Exception:
                return cmd_code['error']
        else:
            return cmd_code['error']

    if __executable__():
        logger.loginfo(handler='create_map',
                       text='Creating navigation map named [%s]...' % name)

        ret = get_data(name)

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='create_map', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='create_map', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def create_planned_path(name='pose',
                        planned_path=None,
                        path_frame=localization_mode['map'],
                        delete=False, inner=False):
    ''' create pre-planned path '''
    ''' result '''

    # subscribe the topic
    def save_data(name, planned_path, path_frame, delete):
        global planned_path_dict

        if name != cmd_code['undef']:
            try:
                if delete:
                    if name != None and name in planned_path_dict:
                        del planned_path_dict[name]

                    return cmd_code['ok']
                else:
                    assert isinstance(planned_path, list)

                    planned_path_data = list()

                    for pose_point in planned_path:
                        pose_point_data = PoseStamped()
                        pose_point_data.header.frame_id = path_frame
                        pose_point_data.pose.position.x = pose_point[0]
                        pose_point_data.pose.position.y = pose_point[1]
                        pose_point_data.pose.orientation = utils.quaternion_from_yaw(
                            utils.rad_from_deg(pose_point[2]))
                        planned_path_data.append(pose_point_data)

                    logger.loginfo(handler='create_planned_path',
                                   text='Creating pre-planned path named [%s]...'
                                   % name)

                    planned_path_dict[name] = planned_path_data

                    # publish the path
                    planned_path_pub = rospy.Publisher("openmover/navigation/global_planner/planner/plan", Path,
                                                       queue_size=1, latch=True)

                    planned_path_msg = Path()
                    planned_path_msg.header.stamp = utils.current_ros_time()
                    planned_path_msg.header.frame_id = path_frame
                    planned_path_msg.poses = planned_path_data

                    planned_path_pub.publish(planned_path_msg)

                    rospy.sleep(config_switch_wait_duration)

                    return cmd_code['ok']
            except Exception:
                return cmd_code['error']
        else:
            return cmd_code['error']

    if __executable__(initialized_required=False):
        ret = save_data(name, planned_path, path_frame, delete)

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='create_planned_path', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='create_planned_path', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret

# apply data part


def apply_pose_point(name=None,
                     x=None, y=None, yaw=None,
                     cov_xx=0.25, cov_yy=0.25, cov_aa=0.06853,
                     inner=False):
    ''' apply pose data '''
    ''' result '''

    # publish the topic
    def apply_data(name, x, y, yaw, cov_xx, cov_yy, cov_aa):
        if initialized:
            try:
                rospy.wait_for_service(
                    'openmover/localization/initialpose/request', timeout=config_service_wait_duration)
                init_pose_service = rospy.ServiceProxy(
                    'openmover/localization/initialpose/request', initial_pose_request)

                init_pose = PoseWithCovarianceStamped()

                if name != None and name in pose_point_dict:
                    init_pose = pose_point_dict[name]
                    assert isinstance(init_pose, PoseWithCovarianceStamped)
                elif x != None and y != None and yaw != None:
                    init_pose.pose.pose.position.x = x
                    init_pose.pose.pose.position.y = y
                    init_pose.pose.pose.orientation = utils.quaternion_from_yaw(
                        utils.rad_from_deg(yaw))
                    init_pose.pose.covariance[0] = cov_xx
                    init_pose.pose.covariance[7] = cov_yy
                    init_pose.pose.covariance[35] = cov_aa
                else:
                    return cmd_code['ok']

                init_pose.header.frame_id = 'map'
                init_pose.header.stamp = utils.current_ros_time()

                logger.loginfo(handler='apply_pose_point',
                               text='Applying pose point to [%s, %s, %s]...' %
                               (str(round(init_pose.pose.pose.position.x, 3)), str(round(init_pose.pose.pose.position.y, 3)),
                                str(round(utils.deg_from_rad(utils.yaw_from_quaternion(init_pose.pose.pose.orientation)), 3))))

                init_pose_data = init_pose_service.call(
                    initial_pose_requestRequest(init_pose))
                assert isinstance(init_pose_data, initial_pose_requestResponse)

                try:
                    rospy.sleep(2.0)
                except Exception:
                    pass

                return cmd_code[init_pose_data.result]
            except Exception:
                logger.logerror(
                    handler='apply_pose_point', text='Unable to request service.')
                return cmd_code['error']
        else:
            logger.logerror(
                handler='apply_pose_point', text='Correct mode not started or invalid command.')
            return cmd_code['ok']

    if __executable__():
        ret = apply_data(name, x, y, yaw,
                         cov_xx, cov_yy, cov_aa)

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='apply_pose_point', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='apply_pose_point', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def apply_map(name=current_area, inner=False):
    ''' apply map data '''
    ''' result '''

    # call the service
    def apply_data(name):
        if initialized\
                and current_mode == mode_code['nav_to']:
            try:
                if name in config_area_without_map:
                    rospy.wait_for_service(
                        'openmover/server/set_func_mode', timeout=config_service_wait_duration)
                    apply_map_service = rospy.ServiceProxy(
                        'openmover/server/set_func_mode', work_mode_request)

                    apply_map_data = apply_map_service.call(
                        work_mode_requestRequest(func_code['load_map'], cmd_code['start'], cmd_code['undef']))
                    assert isinstance(apply_map_data,
                                      work_mode_requestResponse)

                    return cmd_code[apply_map_data.result]
                elif name != None and name != cmd_code['undef']:
                    rospy.wait_for_service(
                        'openmover/server/set_func_mode', timeout=config_service_wait_duration)
                    apply_map_service = rospy.ServiceProxy(
                        'openmover/server/set_func_mode', work_mode_request)

                    apply_map_data = apply_map_service.call(
                        work_mode_requestRequest(func_code['load_map'], cmd_code['finish'], ''))
                    assert isinstance(apply_map_data,
                                      work_mode_requestResponse)

                    if cmd_code[apply_map_data.result]:
                        apply_map_data = apply_map_service.call(
                            work_mode_requestRequest(func_code['load_map'], cmd_code['start'], name))
                        assert isinstance(apply_map_data,
                                          work_mode_requestResponse)

                    return cmd_code[apply_map_data.result]
                elif name == mode_code['undef']:
                    rospy.wait_for_service(
                        'openmover/server/set_func_mode', timeout=config_service_wait_duration)
                    apply_map_service = rospy.ServiceProxy(
                        'openmover/server/set_func_mode', work_mode_request)

                    apply_map_data = apply_map_service.call(
                        work_mode_requestRequest(func_code['load_map'], cmd_code['finish'], ''))
                    assert isinstance(apply_map_data,
                                      work_mode_requestResponse)

                    return cmd_code[apply_map_data.result]
                else:
                    logger.logerror(
                        handler='apply_map', text='Invalid arguments.')
                    return cmd_code['ok']
            except Exception:
                logger.logerror(
                    handler='apply_map', text='Unable to request service.')
                return cmd_code['error']
        else:
            logger.logerror(
                handler='apply_map', text='Correct mode not started or invalid command.')
            return cmd_code['ok']

    if __executable__():
        logger.loginfo(handler='apply_map',
                       text='Applying navigation map named [%s]...' % name)

        ret = apply_data(name)

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='apply_map', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='apply_map', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret

# call functions part


def call_robot_function(name, action, inner=False):
    ''' call robot function '''

    def call_function(name, action):
        if name in func_code:
            try:
                rospy.wait_for_service(
                    'openmover/server/set_func_mode', timeout=config_service_wait_duration)
                function_service = rospy.ServiceProxy(
                    'openmover/server/set_func_mode', work_mode_request)

                if name in config_func_uninit_keepalive and action == cmd_code['start']:
                    function_data = function_service.call(
                        work_mode_requestRequest(func_code[name], cmd_code['finish'], ''))
                    assert isinstance(function_data,
                                      work_mode_requestResponse)

                    if function_data.result == cmd_code['ok']:
                        function_data = function_service.call(
                            work_mode_requestRequest(func_code[name], cmd_code['start'], ''))
                        assert isinstance(function_data,
                                          work_mode_requestResponse)
                else:
                    function_data = function_service.call(
                        work_mode_requestRequest(func_code[name], action, ''))
                    assert isinstance(function_data,
                                      work_mode_requestResponse)

                if (cmd_code[function_data.result] == cmd_code['ok']):
                    started_function_dict[func_code[name]] = action

                return cmd_code[function_data.result]
            except Exception:
                logger.logerror(
                    handler='call_robot_function', text='Unable to request service.')
                return cmd_code['error']
        else:
            logger.logerror(
                handler='call_robot_function', text='Invalid device or invalid command.')
            return cmd_code['ok']

    if __executable__(initialized_required=False):
        logger.loginfo(handler='call_robot_function',
                       text='Calling function [%s, %s] of robot...' % (name, action))

        ret = call_function(name, action)

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='call_robot_function', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='call_robot_function', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def call_plan_path(current_pose_name=None, target_pose_name=None,
                   current_pose_x=None, current_pose_y=None, current_pose_yaw=None,
                   target_pose_x=None, target_pose_y=None, target_pose_yaw=None,
                   inner=False):
    ''' call display global plan result '''
    ''' result '''

    # call the function
    def call_function(current_pose_name, target_pose_name,
                      current_pose_x, current_pose_y, current_pose_yaw,
                      target_pose_x, target_pose_y, target_pose_yaw):
        if initialized\
                and current_mode == mode_code['nav_to'] \
                and current_area != mode_code['undef']:
            try:
                rospy.wait_for_service(
                    'openmover/navigation/global_planner/make_plan', timeout=config_service_wait_duration)
                make_plan_service = rospy.ServiceProxy(
                    'openmover/navigation/global_planner/make_plan', MakeNavPlan)

                current_pose = PoseWithCovarianceStamped()
                target_pose = Pose()

                # get current pose
                if current_pose_name != None and current_pose_name in pose_point_dict:
                    pose_in_dict = pose_point_dict[current_pose_name]
                    assert isinstance(
                        pose_in_dict, PoseWithCovarianceStamped)
                    current_pose = pose_in_dict
                elif current_pose_x != None and current_pose_y != None and current_pose_yaw != None:
                    current_pose.pose.pose.position.x = current_pose_x
                    current_pose.pose.pose.position.y = current_pose_y
                    current_pose.pose.pose.orientation = utils.quaternion_from_yaw(
                        utils.rad_from_deg(current_pose_yaw))
                else:
                    try:
                        current_pose = rospy.wait_for_message(
                            'openmover/localization/pose', PoseWithCovarianceStamped, timeout=config_service_wait_duration)
                    except Exception:
                        current_pose.pose.pose.orientation = utils.quaternion_from_yaw(
                            0)

                # get target pose
                if target_pose_name != None and target_pose_name in pose_point_dict:
                    pose_in_dict = pose_point_dict[target_pose_name]
                    assert isinstance(
                        pose_in_dict, PoseWithCovarianceStamped)
                    target_pose = pose_in_dict.pose.pose
                elif target_pose_x != None and target_pose_y != None and target_pose_yaw != None:
                    target_pose.position.x = target_pose_x
                    target_pose.position.y = target_pose_y
                    target_pose.orientation = utils.quaternion_from_yaw(
                        utils.rad_from_deg(target_pose_yaw))
                else:
                    try:
                        pose = rospy.wait_for_message(
                            'openmover/localization/pose', PoseWithCovarianceStamped, timeout=config_service_wait_duration)
                        assert isinstance(pose, PoseWithCovarianceStamped)
                        target_pose = pose.pose.pose
                    except Exception:
                        target_pose.orientation = utils.quaternion_from_yaw(
                            0)

                make_plan_request = MakeNavPlanRequest()

                make_plan_request.start.header.frame_id = 'map'
                make_plan_request.start.header.stamp = utils.current_ros_time()
                make_plan_request.start.pose = current_pose.pose.pose

                make_plan_request.goal.header.frame_id = 'map'
                make_plan_request.goal.header.stamp = utils.current_ros_time()
                make_plan_request.goal.pose = target_pose

                make_plan_data = make_plan_service.call(make_plan_request)
                assert isinstance(make_plan_data,
                                  MakeNavPlanResponse)

                if make_plan_data.plan_found == 1:
                    logger.loginfo(handler='call_plan_path',
                                   text='Path planned.')
                    return cmd_code['ok']
                else:
                    logger.logerror(handler='call_plan_path',
                                    text='Unable to get path.')
                    return cmd_code['ok']
            except Exception:
                logger.logerror(
                    handler='call_plan_path', text='Unable to request service.')
                return cmd_code['ok']
        else:
            logger.logerror(
                handler='call_plan_path', text='Correct mode not started or invalid command.')
            return cmd_code['ok']

    if __executable__():
        logger.loginfo(handler='call_plan_path',
                       text='Calling to plan the global path...')

        ret = call_function(current_pose_name, target_pose_name,
                            current_pose_x, current_pose_y, current_pose_yaw,
                            target_pose_x, target_pose_y, target_pose_yaw)

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='call_plan_path', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='call_plan_path', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def call_nav_to(target_pose_name=None,
                target_pose_x=None, target_pose_y=None, target_pose_yaw=None,
                vx_max=None, vyaw_max=None,
                area=None,
                localization_sources=None,
                ignore_obstacle=False,
                strighting_stop_distance=None, turning_stop_distance=None,
                xy_tolerance=None, yaw_tolerance=None,
                use_global_planner=True,
                use_planned_path=False,
                button_required=False,
                planned_path_name=None,
                planned_path=None,
                init_pose_name=None,
                init_pose_x=None, init_pose_y=None, init_pose_yaw=None,
                execution_mode=execute_mode['sync'],
                timeout=1800,
                publish_freq=2,
                back_tag=None,
                inner=False):
    ''' call nav to '''
    ''' result '''

    # call the function
    def call_function(target_pose_name,
                      target_pose_x, target_pose_y, target_pose_yaw,
                      vx_max, vyaw_max,
                      area,
                      localization_sources,
                      ignore_obstacle,
                      strighting_stop_distance, turning_stop_distance,
                      xy_tolerance, yaw_tolerance,
                      use_global_planner,
                      use_planned_path,
                      button_required,
                      planned_path_name,
                      planned_path,
                      init_pose_name,
                      init_pose_x, init_pose_y, init_pose_yaw,
                      execution_mode,
                      timeout,
                      publish_freq,
                      back_tag):
        global current_area

        # set default area and localization sources
        if area == None:
            area = current_area

        if localization_sources == None:
            if not (area in config_area_localization_sources):
                localization_sources = config_area_localization_sources['default']
            else:
                localization_sources = config_area_localization_sources[area]

        last_area = current_area

        # auto detect the value of use_planned_path
        if (planned_path_name == None and planned_path == None):
            use_planned_path = False

        if initialized\
                and (current_mode == mode_code['nav_to'] or current_mode == mode_code['create_map']):
            try:
                # check params
                if not execution_mode in execute_mode or timeout < 0 or publish_freq < 0 or button_required == None or\
                        (not use_planned_path and target_pose_name == None and target_pose_x == None and target_pose_y == None and target_pose_yaw == None) or\
                        (use_planned_path and planned_path_name == None and (planned_path == None or not isinstance(planned_path, list))):
                    logger.logerror(
                        handler='call_nav_to', text='Invalid arguments.')
                    return cmd_code['ok']

                switch_result = cmd_code['ok']

                if (current_mode == mode_code['nav_to']):
                    # switch area
                    if (area != last_area):
                        if area != None and\
                                area != cmd_code['undef']:
                            switch_result = switch_area_strategy(
                                area, inner=True)
                            if switch_result != cmd_code['ok']:
                                return switch_result

                    # apply map
                    if (area == None) or\
                            (area != last_area and apply_map(area, inner=True) != cmd_code['ok']):
                        return cmd_code['error']

                    # apply init pose
                    if (area != last_area):
                        if (init_pose_name == None and
                                (init_pose_x == None or init_pose_y == None or init_pose_yaw == None)):
                            if (apply_pose_point(None, 0, 0, 0, inner=True) != cmd_code['ok']):
                                return cmd_code['error']
                        elif apply_pose_point(init_pose_name, init_pose_x,
                                              init_pose_y, init_pose_yaw, inner=True) != cmd_code['ok']:
                            return cmd_code['error']
                    else:
                        if init_pose_name != None or\
                                (init_pose_x != None and init_pose_y != None and init_pose_yaw != None):
                            if apply_pose_point(init_pose_name, init_pose_x,
                                                init_pose_y, init_pose_yaw, inner=True) != cmd_code['ok']:
                                return cmd_code['error']

                # get target pose
                current_pose = PoseWithCovarianceStamped()
                target_pose = Pose()

                try:
                    current_pose = rospy.wait_for_message(
                        'openmover/localization/pose', PoseWithCovarianceStamped, timeout=config_service_wait_duration)
                except Exception:
                    current_pose.pose.pose.orientation = utils.quaternion_from_yaw(
                        0)

                target_pose.position.x = current_pose.pose.pose.position.x
                target_pose.position.y = current_pose.pose.pose.position.y
                target_pose.orientation = current_pose.pose.pose.orientation

                if target_pose_name != None and target_pose_name in pose_point_dict:
                    pose_in_dict = pose_point_dict[target_pose_name]
                    assert isinstance(pose_in_dict, PoseWithCovarianceStamped)
                    target_pose = pose_in_dict.pose.pose
                else:
                    if target_pose_x != None:
                        target_pose.position.x = target_pose_x
                    if target_pose_y != None:
                        target_pose.position.y = target_pose_y
                    if target_pose_yaw != None:
                        target_pose.orientation = utils.quaternion_from_yaw(
                            utils.rad_from_deg(target_pose_yaw))

                # get planned path
                if use_planned_path:
                    if planned_path_name != None and planned_path_name in planned_path_dict:
                        planned_path_in_dict = planned_path_dict[planned_path_name]
                        assert isinstance(planned_path_in_dict, list)
                        planned_path = planned_path_in_dict
                    elif planned_path_name != None:
                        logger.logerror(
                            handler='call_nav_to', text='Pre-planned path not exists.')
                        return cmd_code['error']
                    if planned_path == None or len(planned_path) < 1:
                        logger.logerror(
                            handler='call_nav_to', text='Pre-planned path is empty.')
                        return cmd_code['error']

                    first_path_point = planned_path[0]
                    assert isinstance(first_path_point, PoseStamped)
                    assert isinstance(localization_sources, str)

                    # check path frame
                    if localization_sources.find(first_path_point.header.frame_id) == -1:
                        logger.logerror(
                            handler='call_nav_to', text='Wrong pre-planned path frame.')
                        return cmd_code['error']

                    # set traget pose
                    target_pose = planned_path[len(planned_path) - 1].pose

                    # publish the path
                    planned_path_pub = rospy.Publisher("openmover/navigation/global_planner/planner/plan", Path,
                                                       queue_size=10, latch=True)

                    planned_path_msg = Path()
                    planned_path_msg.header.stamp = utils.current_ros_time()
                    planned_path_msg.header.frame_id = first_path_point.header.frame_id
                    planned_path_msg.poses = planned_path

                    planned_path_pub.publish(planned_path_msg)
                else:
                    planned_path = list()

                # set kinematic params
                max_twist = Twist()

                if vx_max != None:
                    max_twist.linear.x = abs(vx_max)

                if vyaw_max != None:
                    max_twist.angular.z = abs(utils.rad_from_deg(vyaw_max))

                # set obstacle stop params
                if strighting_stop_distance == None:
                    strighting_stop_distance = 0
                else:
                    strighting_stop_distance = abs(strighting_stop_distance)

                if turning_stop_distance == None:
                    turning_stop_distance = 0
                else:
                    turning_stop_distance = abs(turning_stop_distance)
                
                # set tolerance params
                if xy_tolerance == None:
                    xy_tolerance = 0
                else:
                    xy_tolerance = abs(xy_tolerance)

                if yaw_tolerance == None:
                    yaw_tolerance = 0
                else:
                    yaw_tolerance = abs(yaw_tolerance)

                # call nav to
                rospy.wait_for_service(
                    'openmover/navigation/request', timeout=config_service_wait_duration)

                # switch velocity control mode
                switch_velocity_mode(False, inner=True)

                nav_to_data = protocol.nav_to_service.call(nav_to_requestRequest(
                    nav_cmd_code['nav_to'],
                    localization_sources,
                    target_pose,
                    max_twist,
                    ignore_obstacle,
                    strighting_stop_distance,
                    turning_stop_distance,
                    use_global_planner,
                    use_planned_path,
                    button_required,
                    planned_path,
                    xy_tolerance,
                    yaw_tolerance
                ))
                assert isinstance(nav_to_data, nav_to_requestResponse)

                if cmd_code[nav_to_data.result] == cmd_code['ok']:
                    if execution_mode == execute_mode['async']:
                        return cmd_code[nav_to_data.result]
                    else:
                        timer = 0
                        rate = rospy.Rate(publish_freq)

                        try:
                            rospy.sleep(1.0)
                        except Exception:
                            pass

                        while True:
                            navigation_state = get_navigation_state(inner=True)

                            if inner:
                                command = __wait_for_command__(
                                    latch=True, inner=True)

                                if command == cmd_code['back']:
                                    call_cancel()
                                    back(back_tag)

                                    try:
                                        rospy.sleep(1.0)
                                    except Exception:
                                        pass

                                    return cmd_code['ok']

                            if navigation_state[0] == nav_state_ret_code['blocked']:
                                logger.logwarn(handler='call_nav_to', text='State: [%s], pose: [%s, %s, %s], velocity: [%s, %s], command: [%s %s].'
                                               % (str(navigation_state[0]), str(navigation_state[1]['x']), str(navigation_state[1]['y']), str(navigation_state[1]['yaw']),
                                                  str(navigation_state[1]['vx']), str(
                                                      navigation_state[1]['vyaw']),
                                                  str(navigation_state[1]['cmd_vx']), str(navigation_state[1]['cmd_vyaw'])))
                            elif navigation_state[0] == nav_state_ret_code['error']:
                                logger.logerror(handler='call_nav_to', text='State: [%s], pose: [%s, %s, %s], velocity: [%s, %s], command: [%s %s].'
                                                % (str(navigation_state[0]), str(navigation_state[1]['x']), str(navigation_state[1]['y']), str(navigation_state[1]['yaw']),
                                                   str(navigation_state[1]['vx']), str(
                                                       navigation_state[1]['vyaw']),
                                                   str(navigation_state[1]['cmd_vx']), str(navigation_state[1]['cmd_vyaw'])))
                            else:
                                logger.loginfo(handler='call_nav_to', text='State: [%s], pose: [%s, %s, %s], velocity: [%s, %s], command: [%s %s].'
                                               % (str(navigation_state[0]), str(navigation_state[1]['x']), str(navigation_state[1]['y']), str(navigation_state[1]['yaw']),
                                                  str(navigation_state[1]['vx']), str(
                                                      navigation_state[1]['vyaw']),
                                                  str(navigation_state[1]['cmd_vx']), str(navigation_state[1]['cmd_vyaw'])))

                            if (navigation_state[0] == nav_state_ret_code['reached'] or
                                    navigation_state[0] == nav_state_ret_code['ready']):
                                return cmd_code['ok']

                            if (navigation_state[0] == nav_state_ret_code['error']):
                                return cmd_code['error']

                            if (timer > timeout):
                                return cmd_code['timeout']

                            timer += 1.0 / publish_freq
                            rate.sleep()
                else:
                    return cmd_code[nav_to_data.result]
            except Exception:
                logger.logerror(
                    handler='call_nav_to', text='Unable to request service.')
                return cmd_code['error']
        else:
            logger.logerror(
                handler='call_nav_to', text='Correct mode not started or invalid command.')
            return cmd_code['ok']

    if __executable__():
        logger.loginfo(handler='call_nav_to',
                       text='Calling to navigate the robot to pose [%s, %s, %s, %s] with speed limit [%s, %s], localization sources [%s]...'
                       % (str(target_pose_name), str(target_pose_x), str(target_pose_y), str(target_pose_yaw),
                          str(vx_max), str(vyaw_max), localization_sources))

        # switch velocity control mode
        switch_result = switch_velocity_mode(False, inner=True)

        if (switch_result == cmd_code['ok']):
            ret = call_function(target_pose_name,
                                target_pose_x, target_pose_y, target_pose_yaw,
                                vx_max, vyaw_max,
                                area,
                                localization_sources,
                                ignore_obstacle,
                                strighting_stop_distance,
                                turning_stop_distance,
                                xy_tolerance,
                                yaw_tolerance,
                                use_global_planner,
                                use_planned_path,
                                button_required,
                                planned_path_name,
                                planned_path,
                                init_pose_name,
                                init_pose_x, init_pose_y, init_pose_yaw,
                                execution_mode,
                                timeout,
                                publish_freq,
                                back_tag)
        else:
            ret = cmd_code['error']

        # switch velocity control mode
        if (execute_mode == execute_mode['sync']):
            # wait for stopping
            try:
                rospy.sleep(0.1)
            except Exception:
                pass
            switch_velocity_mode(True, inner=True)

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='call_nav_to', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='call_nav_to', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def call_move(dist=0, angle=0,
              vx_max=None, vyaw_max=None,
              localization_sources=localization_mode['odom'],
              ignore_obstacle=False,
              strighting_stop_distance=None, turning_stop_distance=None,
              button_required=False,
              execution_mode=execute_mode['sync'],
              timeout=1800,
              publish_freq=2,
              back_tag=None,
              inner=False):
    ''' call move '''
    ''' result '''

    # call the function
    def call_function(dist, angle,
                      vx_max, vyaw_max,
                      localization_sources,
                      ignore_obstacle,
                      strighting_stop_distance, turning_stop_distance,
                      button_required,
                      execution_mode,
                      timeout,
                      publish_freq,
                      back_tag):
        if initialized\
                and current_mode == mode_code['nav_to']\
                and current_area != cmd_code['undef']:
            try:
                # check params
                if not execution_mode in execute_mode or timeout < 0 or publish_freq < 0 or\
                        dist == None or angle == None or button_required == None:
                    logger.logerror(
                        handler='call_move', text='Invalid arguments.')
                    return cmd_code['ok']

                # get target pose
                target_pose = Pose()

                target_pose.position.x = dist
                target_pose.position.z = utils.rad_from_deg(angle)

                # set kinematic params
                max_twist = Twist()

                if vx_max != None:
                    max_twist.linear.x = abs(vx_max)

                if vyaw_max != None:
                    max_twist.angular.z = abs(utils.rad_from_deg(vyaw_max))

                # set obstacle stop params
                if strighting_stop_distance == None:
                    strighting_stop_distance = 0
                else:
                    strighting_stop_distance = abs(strighting_stop_distance)

                if turning_stop_distance == None:
                    turning_stop_distance = 0
                else:
                    turning_stop_distance = abs(turning_stop_distance)

                # call nav to
                rospy.wait_for_service(
                    'openmover/navigation/request', timeout=config_service_wait_duration)

                # switch velocity control mode
                switch_velocity_mode(False, inner=True)

                nav_to_data = protocol.nav_to_service.call(nav_to_requestRequest(
                    nav_cmd_code['move'],
                    localization_sources,
                    target_pose,
                    max_twist,
                    ignore_obstacle,
                    strighting_stop_distance,
                    turning_stop_distance,
                    False,
                    False,
                    button_required,
                    list(),
                    0,
                    0
                ))
                assert isinstance(nav_to_data, nav_to_requestResponse)

                if cmd_code[nav_to_data.result] == cmd_code['ok']:
                    if execution_mode == execute_mode['async']:
                        return cmd_code[nav_to_data.result]
                    else:
                        timer = 0
                        rate = rospy.Rate(publish_freq)

                        try:
                            rospy.sleep(1.0)
                        except Exception:
                            pass

                        while True:
                            navigation_state = get_navigation_state(inner=True)

                            if inner:
                                command = __wait_for_command__(
                                    latch=True, inner=True)

                                if command == cmd_code['back']:
                                    call_cancel()
                                    back(back_tag)

                                    try:
                                        rospy.sleep(1.0)
                                    except Exception:
                                        pass

                                    return cmd_code['ok']

                            if navigation_state[0] == nav_state_ret_code['blocked']:
                                logger.logwarn(handler='call_move', text='State: [%s], pose: [%s, %s, %s] velocity: [%s, %s], command: [%s %s].'
                                               % (str(navigation_state[0]), str(navigation_state[1]['x']), str(navigation_state[1]['y']), str(navigation_state[1]['yaw']),
                                                  str(navigation_state[1]['vx']), str(
                                                      navigation_state[1]['vyaw']),
                                                  str(navigation_state[1]['cmd_vx']), str(navigation_state[1]['cmd_vyaw'])))
                            elif navigation_state[0] == nav_state_ret_code['error']:
                                logger.logerror(handler='call_nav_to', text='State: [%s], pose: [%s, %s, %s], velocity: [%s, %s], command: [%s %s].'
                                                % (str(navigation_state[0]), str(navigation_state[1]['x']), str(navigation_state[1]['y']), str(navigation_state[1]['yaw']),
                                                   str(navigation_state[1]['vx']), str(
                                                       navigation_state[1]['vyaw']),
                                                   str(navigation_state[1]['cmd_vx']), str(navigation_state[1]['cmd_vyaw'])))
                            else:
                                logger.loginfo(handler='call_move', text='State: [%s], pose: [%s, %s, %s] velocity: [%s, %s], command: [%s %s].'
                                               % (str(navigation_state[0]), str(navigation_state[1]['x']), str(navigation_state[1]['y']), str(navigation_state[1]['yaw']),
                                                  str(navigation_state[1]['vx']), str(
                                                      navigation_state[1]['vyaw']),
                                                  str(navigation_state[1]['cmd_vx']), str(navigation_state[1]['cmd_vyaw'])))

                            if (navigation_state[0] == nav_state_ret_code['reached'] or
                                    navigation_state[0] == nav_state_ret_code['ready']):
                                return cmd_code['ok']

                            if (navigation_state[0] == nav_state_ret_code['error']):
                                return cmd_code['error']

                            if (timer > timeout):
                                return cmd_code['timeout']

                            timer += 1.0 / publish_freq
                            rate.sleep()
                else:
                    return cmd_code[nav_to_data.result]
            except Exception:
                logger.logerror(
                    handler='call_move', text='Unable to request service.')
                return cmd_code['error']
        else:
            logger.logerror(
                handler='call_move', text='Correct mode not started or invalid command.')
            return cmd_code['ok']

    if __executable__():
        logger.loginfo(handler='call_move',
                       text='Calling to move the robot of [%s, %s] with speed limit [%s, %s]...'
                       % (str(dist), str(angle), str(vx_max), str(vyaw_max)))

        # switch velocity control mode
        switch_result = switch_velocity_mode(False, inner=True)

        if (switch_result == cmd_code['ok']):
            ret = call_function(dist, angle,
                                vx_max, vyaw_max,
                                localization_sources,
                                ignore_obstacle,
                                strighting_stop_distance,
                                turning_stop_distance,
                                button_required,
                                execution_mode,
                                timeout,
                                publish_freq,
                                back_tag)
        else:
            ret = cmd_code['error']

        # switch velocity control mode
        if (execute_mode == execute_mode['sync']):
            # wait for stopping
            try:
                rospy.sleep(0.1)
            except Exception:
                pass

            switch_velocity_mode(True, inner=True)

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='call_move', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='call_move', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def call_relocalization(inner=False):
    ''' call relocalization in current map '''
    ''' result '''

    # call the function
    def call_function():
        if initialized:
            if current_mode == mode_code['nav_to'] \
                    and current_area != mode_code['undef']:
                try:
                    rospy.wait_for_service(
                        'openmover/localization/relocalization/request', timeout=config_service_wait_duration)

                    relocalization_request_data = relocalization_requestRequest()
                    relocalization_request_data.mode = relocalization_request_data.MODE_MAP_FROM_TOPIC

                    relocalization_data = protocol.relocalization_service.call(
                        relocalization_request_data)
                    assert isinstance(relocalization_data,
                                      relocalization_requestResponse)

                    return cmd_code[relocalization_data.result]
                except Exception:
                    return cmd_code['error']
            else:
                return cmd_code['ok']
        else:
            return cmd_code['error']

    if __executable__():
        logger.loginfo(handler='call_relocalization',
                       text='Calling to relocalize in the map...')

        ret = call_function()

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='call_relocalization', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='call_relocalization', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def call_cancel(inner=False):
    ''' call cancel navigation session '''
    ''' result '''

    # call the function
    def call_function():
        if initialized:
            if current_mode == mode_code['nav_to'] \
                    and current_area != mode_code['undef']:
                try:
                    rospy.wait_for_service(
                        'openmover/navigation/request', timeout=config_service_wait_duration)

                    nav_to_request_data = nav_to_requestRequest()
                    nav_to_request_data.cmd = nav_cmd_code['cancel']

                    nav_to_data = protocol.nav_to_service.call(
                        nav_to_request_data)
                    assert isinstance(nav_to_data,
                                      nav_to_requestResponse)

                    return cmd_code[nav_to_data.result]
                except Exception:
                    return cmd_code['error']
            else:
                return cmd_code['ok']
        else:
            return cmd_code['error']

    if __executable__():
        logger.loginfo(handler='call_cancel',
                       text='Calling to cancel current navigation session...')

        ret = call_function()

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='call_cancel', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='call_cancel', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def call_pause(inner=False):
    ''' call pause navigation session '''
    ''' result '''

    # call the function
    def call_function():
        if initialized:
            if current_mode == mode_code['nav_to'] \
                    and current_area != mode_code['undef']:
                try:
                    nav_to_state_data = get_navigation_state(inner=True)[0]

                    if (nav_to_state_data == nav_state_ret_code['running'] or
                        nav_to_state_data == nav_state_ret_code['blocked'] or
                            nav_to_state_data == nav_state_ret_code['recovery']):
                        rospy.wait_for_service(
                            'openmover/navigation/request', timeout=config_service_wait_duration)

                        nav_to_request_data = nav_to_requestRequest()
                        nav_to_request_data.cmd = nav_cmd_code['pause']

                        nav_to_data = protocol.nav_to_service.call(
                            nav_to_request_data)
                        assert isinstance(nav_to_data,
                                          nav_to_requestResponse)

                        return cmd_code[nav_to_data.result]
                    else:
                        return cmd_code['ok']
                except Exception:
                    return cmd_code['error']
            else:
                return cmd_code['ok']
        else:
            return cmd_code['error']

    if __executable__():
        logger.loginfo(handler='call_pause',
                       text='Calling to pause current navigation session...')

        ret = call_function()

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='call_pause', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='call_pause', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def call_continue(inner=False):
    ''' call continue navigation session '''
    ''' result '''

    # call the function
    def call_function():
        if initialized:
            if current_mode == mode_code['nav_to'] \
                    and current_area != mode_code['undef']:
                try:
                    nav_to_state_data = get_navigation_state(inner=True)[0]

                    if (nav_to_state_data == nav_state_ret_code['pausing']):
                        rospy.wait_for_service(
                            'openmover/navigation/request', timeout=config_service_wait_duration)

                        nav_to_request_data = nav_to_requestRequest()
                        nav_to_request_data.cmd = nav_cmd_code['continue']

                        nav_to_data = protocol.nav_to_service.call(
                            nav_to_request_data)
                        assert isinstance(nav_to_data,
                                          nav_to_requestResponse)

                        return cmd_code[nav_to_data.result]
                    else:
                        return cmd_code['ok']
                except Exception:
                    return cmd_code['error']
            else:
                return cmd_code['ok']
        else:
            return cmd_code['error']

    if __executable__():
        logger.loginfo(handler='call_continue',
                       text='Calling to continue current navigation session...')

        ret = call_function()

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='call_continue', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='call_continue', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def call_auto_mapping(enable_waypoint_retracing=False,
                      execution_mode=execute_mode['sync'],
                      publish_freq=2,
                      back_tag=None,
                      inner=False):
    ''' call auto mapping '''
    ''' result '''

    # call the function
    def call_function(enable_waypoint_retracing,
                      execution_mode,
                      publish_freq,
                      back_tag):
        if initialized:
            if current_mode == mode_code['create_map']:
                try:
                    rospy.wait_for_service(
                        'openmover/mapping/auto_mapping/request', timeout=config_service_wait_duration)
                    auto_mapping_service = rospy.ServiceProxy(
                        'openmover/mapping/auto_mapping/request', auto_mapping_request)

                    auto_mapping_request_data = auto_mapping_requestRequest()
                    auto_mapping_request_data.cmd = auto_mapping_cmd_code['start']
                    auto_mapping_request_data.waypoint_retracing = enable_waypoint_retracing

                    auto_mapping_data = auto_mapping_service.call(
                        auto_mapping_request_data)
                    assert isinstance(auto_mapping_data,
                                      auto_mapping_requestResponse)

                    if cmd_code[auto_mapping_data.result] == cmd_code['ok']:
                        if execution_mode == execute_mode['async']:
                            return cmd_code[auto_mapping_data.result]
                        else:
                            timer = 0
                            rate = rospy.Rate(publish_freq)

                            rospy.sleep(1.0)

                            while True:
                                auto_mapping_state = get_auto_mapping_state(
                                    inner=True)

                                if inner:
                                    command = __wait_for_command__(
                                        latch=True, inner=True)

                                if command == cmd_code['back']:
                                    call_cancel_auto_mapping()
                                    back(back_tag)

                                    try:
                                        rospy.sleep(1.0)
                                    except Exception:
                                        pass

                                    return cmd_code['ok']

                                logger.loginfo(handler='call_auto_mapping',
                                               text='State: [%s], area: [%s].'
                                                    % (str(auto_mapping_state[0]), str(auto_mapping_state[1])))

                                if (auto_mapping_state[0] == auto_mapping_state_ret_code['finish']):
                                    return cmd_code['ok']

                                timer += 1.0 / publish_freq
                                rate.sleep()
                    else:
                        return cmd_code[auto_mapping_data.result]
                except rospy.exceptions.ROSException:
                    return cmd_code['error']
            else:
                return cmd_code['ok']
        else:
            return cmd_code['error']

    if __executable__():
        logger.loginfo(handler='call_auto_mapping',
                       text='Calling to perform auto mapping...')

        ret = call_function(enable_waypoint_retracing,
                            execution_mode,
                            publish_freq,
                            back_tag)

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='call_auto_mapping', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='call_auto_mapping', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def call_cancel_auto_mapping(inner=False):
    ''' call cancel auto mapping '''
    ''' result '''

    # call the function
    def call_function():
        if initialized:
            if current_mode == mode_code['create_map']:
                try:
                    rospy.wait_for_service(
                        'openmover/mapping/auto_mapping/request', timeout=config_service_wait_duration)
                    auto_mapping_service = rospy.ServiceProxy(
                        'openmover/mapping/auto_mapping/request', auto_mapping_request)

                    auto_mapping_request_data = auto_mapping_requestRequest()
                    auto_mapping_request_data.cmd = auto_mapping_cmd_code['cancel']

                    auto_mapping_data = auto_mapping_service.call(
                        auto_mapping_request_data)
                    assert isinstance(auto_mapping_data,
                                      auto_mapping_requestResponse)

                    return cmd_code[auto_mapping_data.result]
                except rospy.exceptions.ROSException:
                    return cmd_code['error']
            else:
                return cmd_code['ok']
        else:
            return cmd_code['error']

    if __executable__():
        logger.loginfo(handler='call_cancel_auto_mapping',
                       text='Calling to cancel auto mapping...')

        ret = call_function()

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='call_cancel_auto_mapping', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='call_cancel_auto_mapping', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


def call_playsound(filename=None, loop_times=1, inner=False):
    ''' call play sound '''
    ''' result '''

    # call the function
    def call_function(filename, loop_times):
        try:
            if filename == None or loop_times < -1:
                logger.logerror(
                    handler='call_playsound', text='Invalid filename.')
                return cmd_code['ok']

            rospy.wait_for_service(
                'openmover/control/playsound/request', timeout=config_service_wait_duration)
            playsound_service = rospy.ServiceProxy(
                'openmover/control/playsound/request', playsound_request)

            playsound_service.call(playsound_requestRequest(
                filename,
                loop_times
            ))

            logger.loginfo(
                handler='call_playsound', text='Play sound command was executed successfully.')

            return cmd_code['ok']
        except Exception:
            logger.logerror(
                handler='call_playsound', text='Unable to request service.')
            return cmd_code['ok']

    if __executable__(initialized_required=False):
        logger.loginfo(handler='call_playsound',
                       text='Calling to play sound [%s] with [%s] loops...' % (filename, str(loop_times)))

        ret = call_function(filename, loop_times)

        if ret == cmd_code['ok']:
            logger.logdebug(
                handler='call_playsound', text='The result of function is [%s].' % str(ret))
        else:
            logger.logerror(
                handler='call_playsound', text='The result of function is [%s].' % str(ret))
    else:
        logger.loginfo(
            handler='hal', text='A function has been skipped.')
        ret = cmd_code['pass']

    if inner:
        return ret


# initialize the ros proxy
rospy.init_node('cli', anonymous=True)

# initialize the time system
_ = utils.current_ros_time()

# initialize logger
logger.initialize()
logger.log_sys_init()

# initialize proxy
if (protocol.init_cli() == cmd_code['error']):
    logger.log_sys_uninit()
    exit()
