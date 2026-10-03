# 2022-7-3 0.0.0.5A

# -*- coding: utf-8 -*-

from threading import Lock

import rospy
from openmover_msgs.msg import flow_state, bms_data, nav_to_state
from openmover_msgs.srv import (flow_action, flow_actionRequest, flow_actionResponse,
                                flow_cmd, flow_cmdRequest, flow_cmdResponse, nav_to_request)
from relocalization_toolbox_msgs.srv import *
from geometry_msgs.msg import PoseWithCovarianceStamped
from std_msgs.msg import Bool

import logger
import symbols
import utils

# const part
interactive_back = symbols.cmd_code['back']
interactive_pause = symbols.cmd_code['pause']
interactive_continue = symbols.cmd_code['continue']
interactive_wait = symbols.cmd_code['wait']

# action control part
flow_action_updated = False
flow_action_action = symbols.flow_action_code['continue']
flow_action_arg = None

# state part
state_lock = Lock()
flow_state_data = flow_state()

# navigation state part
nav_to_state_data = nav_to_state()
nav_to_state_lock = Lock()

# mutex part
lock = Lock()

# ros proxy init
sdk_initialized = False


def init_cli():
    global flow_state_pub
    global sdk_initialized
    global nav_to_service
    global relocalization_service

    logger.loginfo(handler='init_cli',
                   text='Calling to initialize robot CLI...')

    try:
        rospy.wait_for_message("openmover/flow/state", flow_state, timeout=1)
        logger.logerror(handler='init_cli',
                        text='The robot is not ready or an another session is already running.')
        sdk_initialized = True
        ret = symbols.cmd_code['error']
    except Exception:
        ret = symbols.cmd_code['ok']

    if not sdk_initialized:
        def flow_action_service_callback(req):
            global flow_action_updated
            global flow_action_action
            global flow_action_arg
            global lock

            assert isinstance(req, flow_actionRequest)

            lock.acquire()

            flow_action_updated = True
            flow_action_action = symbols.flow_action_code[req.action]
            flow_action_arg = req.arg

            lock.release()

            return flow_actionResponse(symbols.cmd_code['ok'])

        def send_flow_state(_):
            global flow_state_data

            state_lock.acquire()

            flow_state_data.header.frame_id = 'map'
            flow_state_data.header.stamp = utils.current_ros_time()

            flow_state_pub.publish(flow_state_data)

            state_lock.release()

        def pose_callback(msg):
            assert isinstance(msg, PoseWithCovarianceStamped)

            set_flow_state(x=round(msg.pose.pose.position.x, 3),
                           y=round(msg.pose.pose.position.y, 3),
                           yaw=round(utils.deg_from_rad(utils.yaw_from_quaternion(
                               msg.pose.pose.orientation)), 3))

        def bms_callback(msg):
            assert isinstance(msg, bms_data)

            set_flow_state(voltage=msg.voltage,
                           percent=msg.soc, current=msg.current)

        def nav_to_state_callback(msg):
            global nav_to_state_data

            assert isinstance(msg, nav_to_state)

            set_flow_state(state=symbols.nav_state_ret_code[msg.state])

            nav_to_state_lock.acquire()

            nav_to_state_data = msg

            nav_to_state_lock.release()

        def emergency_callback(msg):
            assert isinstance(msg, Bool)

            set_flow_state(emegergency=msg.data)

        try:
            _ = rospy.Service(
                'openmover/flow/action', flow_action, flow_action_service_callback)

            flow_state_pub = rospy.Publisher("openmover/flow/state", flow_state,
                                             queue_size=10, latch=True)

            _ = rospy.Subscriber("openmover/localization/pose",
                                 PoseWithCovarianceStamped, pose_callback, queue_size=1)

            _ = rospy.Subscriber("openmover/hardware/bms",
                                 bms_data, bms_callback, queue_size=1)

            _ = rospy.Subscriber("openmover/navigation/state",
                                 nav_to_state, nav_to_state_callback, queue_size=1)

            _ = rospy.Subscriber("openmover/hardware/emergency",
                                 Bool, emergency_callback, queue_size=1)

            nav_to_service = rospy.ServiceProxy(
                'openmover/navigation/request', nav_to_request)

            relocalization_service = rospy.ServiceProxy(
                'openmover/localization/relocalization/request', relocalization_request)

            set_flow_state(state=symbols.nav_state_ret_code['reached'])

            rospy.Timer(rospy.Duration(0.2), send_flow_state)

            sdk_initialized = True

            ret = symbols.cmd_code['ok']
        except Exception:
            ret = symbols.cmd_code['error']

    if ret == symbols.cmd_code['ok']:
        logger.logdebug(
            handler='init_cli', text='The result of function is [%s].' % str(ret))
    else:
        logger.logerror(
            handler='init_cli', text='The result of function is [%s].' % str(ret))

    return ret

# setters


def set_flow_state(state=None, x=None, y=None, yaw=None, voltage=None, percent=None, current=None, emegergency=None, on_error=False):
    global flow_state_data

    state_lock.acquire()

    if (state != None):
        flow_state_data.state = symbols.flow_state_code[state]

    if (x != None):
        flow_state_data.pos.x = x

    if (y != None):
        flow_state_data.pos.y = y

    if (yaw != None):
        flow_state_data.pos.yaw = yaw

    if (voltage != None):
        flow_state_data.voltage = voltage

    if (percent != None):
        flow_state_data.percent = percent

    if (current != None):
        flow_state_data.current = current

    if (emegergency != None):
        flow_state_data.emergency = emegergency

    state_lock.release()

# senders


def send_flow_cmd(cmd, arg):
    rospy.wait_for_service(
        'openmover/flow/cmd', timeout=10)

    flow_cmd_service = rospy.ServiceProxy(
        'openmover/flow/cmd', flow_cmd)

    received_data = flow_cmd_service.call(
        flow_cmdRequest(cmd, arg))
    assert isinstance(received_data, flow_cmdResponse)

    return received_data.result

# getters


def get_navigation_state():
    global nav_to_state_data

    nav_to_state_lock.acquire()

    ret = nav_to_state_data

    nav_to_state_lock.release()

    return ret

# receivers


def receive_cmd(latch=False):
    global flow_action_updated

    lock.acquire()

    action = flow_action_action

    if flow_action_updated:
        flow_action_updated = False

        lock.release()

        return symbols.cmd_code[action]
    elif latch:
        lock.release()

        return symbols.cmd_code[action]
    else:
        lock.release()

        return symbols.cmd_code['wait']

# controllers


def if_to_back(cmd):
    return cmd == interactive_back


def if_to_pause(cmd):
    return cmd == interactive_pause


def if_to_continue(cmd):
    return cmd == interactive_continue
