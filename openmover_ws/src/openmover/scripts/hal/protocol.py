#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 2022-6-2 0.0.0.12A
# ROS 2 Jazzy port (Stage 6): rospy -> rclpy.
# rospy's implicit background spinner is replaced by an explicit executor
# thread spinning the shared CLI node, so synchronous service calls and
# subscriptions behave like they did under ROS 1.

import threading
import time as _time

import rclpy
import rclpy.time
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.executors import MultiThreadedExecutor
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from std_msgs.msg import Bool

from openmover_msgs.msg import BmsData, FlowState, NavToState
from openmover_msgs.srv import FlowAction, FlowCmd, NavToRequest
from relocalization_toolbox_msgs.srv import RelocalizationRequest

from symbols import *
import logger
import utils

# 初始化导航状态缓冲区
navigation_state_buffer_data = None
navigation_state_buffer_data_lock = threading.Lock()

# 共享节点与后台自旋线程（rclpy 需要显式 spin）
node = None
executor = None
spinner_thread = None

# flow_cmd 服务数据
flow_cmd_data_dict = dict()

# 定义导航/重定位服务客户端（保持 ROS 1 全局代理语义）
nav_to_service = None
relocalization_service = None

flow_state_pub = None

# const part
interactive_back = cmd_code['back']
interactive_pause = cmd_code['pause']
interactive_continue = cmd_code['continue']
interactive_wait = cmd_code['wait']

# action control part
flow_action_updated = False
flow_action_action = flow_action_code['continue']
flow_action_arg = None

# state part
state_lock = threading.Lock()
flow_state_data = FlowState()

# mutex part
lock = threading.Lock()

# ros proxy init
sdk_initialized = False


# 等待话题单条消息（替代 rospy.wait_for_message）
def wait_for_message(topic, msg_type, timeout=None, qos=None):
    global node

    if qos is None:
        qos = 10

    event = threading.Event()
    result = dict()

    def callback(msg):
        if 'msg' not in result:
            result['msg'] = msg
            event.set()

    sub = node.create_subscription(msg_type, topic, callback, qos)

    try:
        got = event.wait(timeout)
    finally:
        node.destroy_subscription(sub)

    if not got:
        raise rclpy.exceptions.ROSException(
            'wait_for_message timed out on topic [%s]' % topic)

    return result['msg']


# 同步调用服务（后台自旋线程负责处理响应）
def call_service(client, request, timeout=None):
    if not client.wait_for_service(timeout_sec=timeout):
        raise rclpy.exceptions.ROSException(
            'service [%s] not available' % client.srv_name)

    future = client.call_async(request)

    end = _time.monotonic() + (timeout if timeout is not None else 3600.0)
    while not future.done():
        if _time.monotonic() > end:
            raise rclpy.exceptions.ROSException(
                'service call timeout on [%s]' % client.srv_name)
        if not rclpy.ok():
            raise rclpy.exceptions.ROSException('context is shutdown')
        _time.sleep(0.01)

    return future.result()


# 设置工作流状态
def set_flow_state(state=None, x=None, y=None, yaw=None, voltage=None,
                   percent=None, current=None, emegergency=None, on_error=False):
    global flow_state_data

    state_lock.acquire()

    if (state != None):
        flow_state_data.state = flow_state_code[state]

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


# 获取导航状态
def get_navigation_state(inner=False):
    global navigation_state_buffer_data

    if navigation_state_buffer_data != None:
        navigation_state_buffer_data_lock.acquire()

        if navigation_state_buffer_data == None:
            navigation_state_buffer_data_lock.release()
            return None

        # 返回当前缓冲区数据（与 ROS 1 一致：只读不清空，保留最近一次状态）
        navigation_state_buffer_data_copy = navigation_state_buffer_data

        navigation_state_buffer_data_lock.release()

        return navigation_state_buffer_data_copy

    return None


# 订阅导航状态话题
def navigation_state_callback(msg):
    global navigation_state_buffer_data

    assert isinstance(msg, NavToState)

    set_flow_state(state=nav_state_ret_code[msg.state])

    navigation_state_buffer_data_lock.acquire()

    # 保存导航状态缓冲区数据
    navigation_state_buffer_data = msg

    navigation_state_buffer_data_lock.release()


# flow_cmd 服务处理（ROS 1 中由主机提供该服务；此处本地实现以保持自包含）
def send_flow_cmd(cmd=flow_cmd_code['get'], arg=None, inner=False):
    global flow_cmd_data_dict

    import hal

    def get_data(key):
        if key == 'desired_back_tag':
            if hal.desired_back_tag == None:
                return 'None'
            else:
                return hal.desired_back_tag
        elif key == 'current_back_tag':
            if len(hal.current_back_tag) == 0:
                return 'None'
            else:
                return hal.current_back_tag.pop()
        elif key in flow_cmd_data_dict:
            return flow_cmd_data_dict[key]

        return None

    def set_data(key, value):
        flow_cmd_data_dict[key] = value

        return None

    try:
        if cmd == flow_cmd_code['get']:
            return cmd_code['ok'], get_data(arg)
        elif cmd == 'set':
            assert isinstance(arg, list)
            assert len(arg) > 1

            return cmd_code['ok'], set_data(arg[0], arg[1])
        elif cmd == 'del':
            assert isinstance(arg, str)

            if arg in flow_cmd_data_dict:
                del flow_cmd_data_dict[arg]

                return cmd_code['ok'], None

        return cmd_code['error'], None
    except Exception:
        return cmd_code['error'], None


def flow_cmd_service_callback(request, response):
    ret = send_flow_cmd(cmd=request.cmd, arg=request.arg, inner=True)

    # 服务仅有 result 字段（与 ROS 1 一致，数据不回传）
    response.result = ret[0]

    return response


# 初始化
def init_cli():
    global node
    global executor
    global spinner_thread

    global nav_to_service
    global relocalization_service

    global flow_state_pub
    global sdk_initialized

    logger.loginfo(handler='init_cli',
                   text='Calling to initialize robot CLI...')

    ret = cmd_code['ok']

    # 初始化 ROS 上下文
    if not rclpy.ok():
        rclpy.init()

    # 定义 ROS 节点
    node = rclpy.create_node('cli')

    # 后台自旋线程（等效 rospy 的隐式回调处理）
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    spinner_thread = threading.Thread(target=executor.spin, daemon=True)
    spinner_thread.start()

    try:
        _ = wait_for_message('openmover/flow/state', FlowState, timeout=1)
        logger.logerror(handler='init_cli',
                        text='The robot is not ready or an another session is already running.')
        sdk_initialized = True
        ret = cmd_code['error']
    except Exception:
        ret = cmd_code['ok']

    if not sdk_initialized:
        def flow_action_service_callback(request, response):
            global flow_action_updated
            global flow_action_action
            global flow_action_arg

            assert isinstance(request, FlowAction.Request)

            lock.acquire()

            flow_action_updated = True
            flow_action_action = flow_action_code[request.action]
            flow_action_arg = request.arg

            lock.release()

            response.result = cmd_code['ok']
            return response

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
            assert isinstance(msg, BmsData)

            set_flow_state(voltage=msg.voltage,
                           percent=msg.soc, current=msg.current)

        def emergency_callback(msg):
            assert isinstance(msg, Bool)

            set_flow_state(emegergency=msg.data)

        try:
            _ = node.create_service(
                FlowAction, 'openmover/flow/action', flow_action_service_callback)

            flow_state_pub = node.create_publisher(
                FlowState, 'openmover/flow/state',
                QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                           history=HistoryPolicy.KEEP_LAST,
                           durability=DurabilityPolicy.TRANSIENT_LOCAL))

            # flow_cmd 服务（ROS 1 中由主机提供；此处本地提供以保持自包含）
            _ = node.create_service(FlowCmd, 'openmover/flow/cmd',
                                    flow_cmd_service_callback)

            _ = node.create_subscription(
                PoseWithCovarianceStamped, 'openmover/localization/pose',
                pose_callback, 1)

            _ = node.create_subscription(
                BmsData, 'openmover/hardware/bms',
                bms_callback, 1)

            _ = node.create_subscription(
                NavToState, 'openmover/navigation/state',
                navigation_state_callback, 1)

            _ = node.create_subscription(
                Bool, 'openmover/hardware/emergency',
                emergency_callback, 1)

            nav_to_service = node.create_client(
                NavToRequest, 'openmover/navigation/request')

            relocalization_service = node.create_client(
                RelocalizationRequest, 'openmover/localization/relocalization/request')

            set_flow_state(state=nav_state_ret_code['reached'])

            _ = node.create_timer(0.2, send_flow_state)

            sdk_initialized = True

            ret = cmd_code['ok']
        except Exception:
            ret = cmd_code['error']

    if ret == cmd_code['ok']:
        logger.logdebug(
            handler='init_cli', text='The result of function is [%s].' % str(ret))
    else:
        logger.logerror(
            handler='init_cli', text='The result of function is [%s].' % str(ret))

    return ret


# receivers


def receive_cmd(latch=False):
    global flow_action_updated

    lock.acquire()

    action = flow_action_action

    if flow_action_updated:
        flow_action_updated = False

        lock.release()

        return cmd_code[action]
    elif latch:
        lock.release()

        return cmd_code[action]
    else:
        lock.release()

        return cmd_code['wait']

# controllers


def if_to_back(cmd):
    return cmd == interactive_back


def if_to_pause(cmd):
    return cmd == interactive_pause


def if_to_continue(cmd):
    return cmd == interactive_continue
