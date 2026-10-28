#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rospy
import threading
from geometry_msgs.msg import Twist
from pynput import keyboard

NODE_NAME = 'teleop_node'
TAG = '键盘手动控制'


def manual_control():
    rospy.init_node(NODE_NAME, anonymous=True)
    rospy.loginfo("%s：节点已启动。" % TAG)

    velocity_x = rospy.get_param('~teleop/velocity_x', 0.4)
    velocity_yaw = rospy.get_param('~teleop/velocity_yaw', 0.8)
    max_x_acc = rospy.get_param('~teleop/max_x_acc', 0.5)
    max_yaw_acc = rospy.get_param('~teleop/max_yaw_acc', 1.57)
    zero_flush_sec = rospy.get_param(
        '~teleop/zero_flush_sec', 0.15)
    release_debounce_sec = rospy.get_param(
        '~teleop/release_debounce_sec', 0.08)
    brake_on_flip = rospy.get_param(
        '~teleop/brake_on_flip', True)
    brake_on_flip_yaw = rospy.get_param('~teleop/brake_on_flip_yaw', True)

    cmd_vel_pub = rospy.Publisher('cmd_vel', Twist, queue_size=2)

    twist_data = Twist()
    twist_target_data = Twist()
    last_nonzero_cmd = Twist()

    pressed = set()
    lock = threading.Lock()

    KEY_UP = keyboard.Key.up
    KEY_DOWN = keyboard.Key.down
    KEY_LEFT = keyboard.Key.left
    KEY_RIGHT = keyboard.Key.right

    hz = 50.0
    rate = rospy.Rate(hz)
    delta_vx = max_x_acc / hz
    delta_vyaw = max_yaw_acc / hz

    zero_flush_ticks_total = max(1, int(zero_flush_sec * hz))
    zero_flush_ticks = 0

    waiting_debounce = False
    last_all_release_stamp = rospy.Time(0)

    def recompute_target():
        vx = 0.0
        wz = 0.0
        if KEY_UP in pressed and KEY_DOWN not in pressed:
            vx += velocity_x
        if KEY_DOWN in pressed and KEY_UP not in pressed:
            vx -= velocity_x
        if KEY_LEFT in pressed and KEY_RIGHT not in pressed:
            wz += velocity_yaw
        if KEY_RIGHT in pressed and KEY_LEFT not in pressed:
            wz -= velocity_yaw
        twist_target_data.linear.x = vx
        twist_target_data.angular.z = wz

    def on_press(key):
        nonlocal zero_flush_ticks, waiting_debounce
        with lock:
            if key == KEY_UP:
                pressed.add(KEY_UP)
            elif key == KEY_DOWN:
                pressed.add(KEY_DOWN)
            elif key == KEY_LEFT:
                pressed.add(KEY_LEFT)
            elif key == KEY_RIGHT:
                pressed.add(KEY_RIGHT)

            recompute_target()
            zero_flush_ticks = 0
            waiting_debounce = False

    def on_release(key):
        nonlocal last_all_release_stamp, waiting_debounce
        with lock:
            if key in (KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT):
                pressed.discard(key)
                recompute_target()
                if not pressed:
                    last_all_release_stamp = rospy.Time.now()
                    waiting_debounce = True

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    while not rospy.is_shutdown():
        now = rospy.Time.now()

        with lock:
            has_pressed = len(pressed) > 0
            in_waiting = waiting_debounce
            target_vx = twist_target_data.linear.x
            target_wz = twist_target_data.angular.z
            local_zero_flush = zero_flush_ticks
            last_release = last_all_release_stamp

        if has_pressed:
            if brake_on_flip and (twist_data.linear.x * target_vx < 0):
                twist_data.linear.x = 0.0
            if brake_on_flip_yaw and (twist_data.angular.z * target_wz < 0):
                twist_data.angular.z = 0.0

            if abs(twist_data.linear.x - target_vx) < delta_vx:
                twist_data.linear.x = target_vx
            elif twist_data.linear.x < target_vx:
                twist_data.linear.x += delta_vx
            else:
                twist_data.linear.x -= delta_vx

            if abs(twist_data.angular.z - target_wz) < delta_vyaw:
                twist_data.angular.z = target_wz
            elif twist_data.angular.z < target_wz:
                twist_data.angular.z += delta_vyaw
            else:
                twist_data.angular.z -= delta_vyaw

            cmd_vel_pub.publish(twist_data)

            if abs(twist_data.linear.x) > 1e-6 or abs(twist_data.angular.z) > 1e-6:
                last_nonzero_cmd = Twist()
                last_nonzero_cmd.linear.x = twist_data.linear.x
                last_nonzero_cmd.angular.z = twist_data.angular.z

            with lock:
                zero_flush_ticks = 0
                waiting_debounce = False

        else:
            if in_waiting:
                cmd_vel_pub.publish(last_nonzero_cmd)
                if (now - last_release).to_sec() >= release_debounce_sec:
                    with lock:
                        waiting_debounce = False
                        zero_flush_ticks = zero_flush_ticks_total
            else:
                if local_zero_flush > 0:
                    with lock:
                        zero_flush_ticks -= 1
                    cmd_vel_pub.publish(Twist())

        try:
            rate.sleep()
        except rospy.exceptions.ROSException:
            rospy.logwarn('%s：节点即将关闭。' % TAG)
            break

    try:
        listener.stop()
    except Exception:
        pass


if __name__ == "__main__":
    manual_control()
