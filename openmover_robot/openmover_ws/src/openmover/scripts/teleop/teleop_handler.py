#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 2023-6-24 0.0.0.1A

import rospy
import symbols
from geometry_msgs.msg import Twist
from pynput import keyboard
from openmover_msgs.srv import (stop_request, stop_requestRequest,
                            stop_requestResponse)

NODE_NAME = 'teleop_handler'
TAG = '手动控制'

# 初始化数据
emergency_stop_value = False


def manual_control():
    # 初始化节点
    rospy.init_node(NODE_NAME, anonymous=True)

    # 打印调试信息
    rospy.logout("%s：节点已启动。" % TAG)

    # 获取参数
    velocity_x = rospy.get_param('~teleop/velocity_x', 0.4)
    velocity_yaw = rospy.get_param('~teleop/velocity_yaw', 0.2)
    max_x_acc = rospy.get_param('~teleop/max_x_acc', 1)
    max_yaw_acc = rospy.get_param('~teleop/max_yaw_acc', 0.3)

    # 定义发布器
    cmd_vel_pub = rospy.Publisher(
        'openmover/control/cmd_vel_manual', Twist, queue_size=2)

    # 定义急停客户端
    emergency_stop_client = rospy.ServiceProxy(
        'openmover/control/stop/request', stop_request)

    # 初始化数据
    twist_data = Twist()
    twist_target_data = Twist()

    # 注册键盘监听
    def on_press(key):
        global emergency_stop_value

        if key == keyboard.Key.up:
            twist_target_data.linear.x = velocity_x
        elif key == keyboard.Key.down:
            twist_target_data.linear.x = -velocity_x

        if key == keyboard.Key.left:
            twist_target_data.angular.z = velocity_yaw
        elif key == keyboard.Key.right:
            twist_target_data.angular.z = -velocity_yaw

        if key == keyboard.Key.home:
            twist_target_data.linear.x = 0
            twist_target_data.angular.z = 0

            try:
                rospy.wait_for_service(
                    'openmover/control/stop/request', timeout=1)

                emergency_stop_value = not emergency_stop_value

                emergency_stop_data = emergency_stop_client.call(
                    stop_requestRequest(emergency_stop_value))
                assert isinstance(emergency_stop_data,
                                  stop_requestResponse)

                if emergency_stop_data.result == symbols.cmd_code['ok']:
                    if emergency_stop_value:
                        rospy.logwarn('%s：紧急制动已施加。' % TAG)
                    else:
                        rospy.logwarn('%s：紧急制动已释放。' % TAG)
                else:
                    rospy.logwarn('%s：紧急制动服务未就绪。' % TAG)
            except rospy.exceptions.ROSException:
                rospy.logwarn('%s：紧急制动服务未就绪。' % TAG)

    def on_release(key):
        if key == keyboard.Key.up or key == keyboard.Key.down:
            twist_target_data.linear.x = 0

        if key == keyboard.Key.left or key == keyboard.Key.right:
            twist_target_data.angular.z = 0

    listener = keyboard.Listener(
        on_press=on_press,
        on_release=on_release)
    listener.start()

    delta_vx = max_x_acc / 50.0
    delta_vyaw = max_yaw_acc / 50.0

    # 循环频率
    rate = rospy.Rate(50.0)

    while not rospy.is_shutdown():
        if not emergency_stop_value:
            # 线速度加速度控制
            if abs(twist_data.linear.x - twist_target_data.linear.x) < delta_vx:
                twist_data.linear.x = twist_target_data.linear.x
            elif twist_data.linear.x < twist_target_data.linear.x:
                twist_data.linear.x += delta_vx
            elif twist_data.linear.x > twist_target_data.linear.x:
                twist_data.linear.x -= delta_vx

            # 角速度加速度控制
            if abs(twist_data.angular.z - twist_target_data.angular.z) < delta_vyaw:
                twist_data.angular.z = twist_target_data.angular.z
            elif twist_data.angular.z < twist_target_data.angular.z:
                twist_data.angular.z += delta_vyaw
            elif twist_data.angular.z > twist_target_data.angular.z:
                twist_data.angular.z -= delta_vyaw
        else:
            twist_data.linear.x = 0
            twist_data.angular.z = 0

        cmd_vel_pub.publish(twist_data)

        if not rospy.is_shutdown():
            try:
                rate.sleep()
            except rospy.exceptions.ROSException:
                rospy.logwarn('%s：节点即将关闭。' % TAG)
        else:
            break


if __name__ == "__main__":
    manual_control()
