#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rospy
from std_msgs.msg import Bool
from std_srvs.srv import Empty, EmptyRequest
from openmover_msgs.srv import nav_to_request, nav_to_requestRequest
from auto_mapping_toolbox_msgs.srv import auto_mapping_request, auto_mapping_requestRequest
import symbols

NODE_NAME = 'reset_server_handler'
TAG = '系统重置服务器'

button_pressed_time = None
emergency_state = False
emergency_trigger = False


def button_callback(msg):
    global button_pressed_time

    assert isinstance(msg, Bool)

    if msg.data:
        if button_pressed_time is None:
            button_pressed_time = rospy.get_time()
    else:
        button_pressed_time = None


def emergency_callback(msg):
    global emergency_state
    global emergency_trigger

    assert isinstance(msg, Bool)

    if (msg.data != emergency_state and msg.data):
        emergency_trigger = True

    emergency_state = msg.data


def reset_server():
    global button_pressed_time
    global emergency_state
    global emergency_trigger

    rospy.init_node(NODE_NAME, anonymous=True)
    rospy.loginfo('%s：节点已启动。' % TAG)

    # 0-导航、1-探索
    work_mode = rospy.get_param('~reset_server/work_mode', 0)

    _ = rospy.Subscriber(
        'openmover/hardware/button', Bool, button_callback)

    _ = rospy.Subscriber(
        'openmover/hardware/emergency', Bool, emergency_callback)

    reset_state_pub = rospy.Publisher(
        'openmover/control/reset_state', Bool, queue_size=10)

    if work_mode == 0:
        rospy.wait_for_service('openmover/navigation/request')
        nav_cancel_client = rospy.ServiceProxy(
            'openmover/navigation/request', nav_to_request)
    elif work_mode == 1:
        rospy.wait_for_service('openmover/mapping/auto_mapping/request')
        auto_mapping_cancel_client = rospy.ServiceProxy(
            'openmover/mapping/auto_mapping/request', auto_mapping_request)

    rospy.wait_for_service(
        'openmover/localization/relocalization/simple_request')
    reloc_client = rospy.ServiceProxy(
        'openmover/localization/relocalization/simple_request', Empty)

    # 状态数据
    state_data = Bool()
    state_data.data = False

    while not rospy.is_shutdown():
        if button_pressed_time is not None and (rospy.get_time() - button_pressed_time) > 5 and not emergency_state:
            rospy.logwarn('%s：准备重置系统。' % TAG)

            # 发布状态
            state_data.data = True

            # 发布三次防止丢失
            for _ in range(3):
                reset_state_pub.publish(state_data)
                rospy.sleep(0.02)

            # 取消导航或探索
            if work_mode == 0:
                nav_cancel_request = nav_to_requestRequest()
                nav_cancel_request.cmd = symbols.nav_cmd_code['cancel']
                nav_cancel_client.call(nav_cancel_request)
            elif work_mode == 1:
                auto_mapping_cancel_request = auto_mapping_requestRequest()
                auto_mapping_cancel_request.cmd = symbols.auto_mapping_cmd_code['cancel']
                auto_mapping_cancel_client.call(auto_mapping_cancel_request)

            # 等待取消完毕
            rospy.sleep(0.5)

            # 重置定位
            reloc_request = EmptyRequest()
            reloc_client.call(reloc_request)

            # 等待重置完毕
            rospy.sleep(3)

            rospy.logwarn('%s：系统重置完成。' % TAG)

            button_pressed_time = None
        else:
            # 发布状态
            state_data.data = False
            reset_state_pub.publish(state_data)

        if emergency_trigger:
            rospy.logwarn('%s：紧急制动触发，停止一切任务。' % TAG)

            # 取消导航或探索
            if work_mode == 0:
                nav_cancel_request = nav_to_requestRequest()
                nav_cancel_request.cmd = symbols.nav_cmd_code['cancel']
                nav_cancel_client.call(nav_cancel_request)
            elif work_mode == 1:
                auto_mapping_cancel_request = auto_mapping_requestRequest()
                auto_mapping_cancel_request.cmd = symbols.auto_mapping_cmd_code['cancel']
                auto_mapping_cancel_client.call(auto_mapping_cancel_request)

            # 等待取消完毕
            rospy.sleep(0.5)

            rospy.logwarn('%s：紧急制动已施加。' % TAG)

            emergency_trigger = False

        if not rospy.is_shutdown():
            try:
                rospy.sleep(0.1)
            except rospy.exceptions.ROSException:
                rospy.logwarn('%s：节点即将关闭。' % TAG)
        else:
            break


if __name__ == "__main__":
    reset_server()
