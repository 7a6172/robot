#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 2022-6-2 0.0.0.6A
# ROS 2 Jazzy port (Stage 6): rospy -> rclpy (ros node provided by protocol).

import math
import time

import tf_transformations


# get current system time (ROS 2 builtin_interfaces Time)
def current_ros_time():
    from protocol import node

    return node.get_clock().now().to_msg()


# convert from quaternion to yaw
def yaw_from_quaternion(q):
    yaw = tf_transformations.euler_from_quaternion([q.x, q.y, q.z, q.w])[2]

    return yaw


# convert from yaw to quaternion
def quaternion_from_yaw(yaw):
    from geometry_msgs.msg import Quaternion

    q = tf_transformations.quaternion_from_euler(0, 0, yaw)

    quat = Quaternion()
    quat.x = q[0]
    quat.y = q[1]
    quat.z = q[2]
    quat.w = q[3]

    return quat


# convert from rad to deg
def deg_from_rad(rad):
    return math.degrees(rad)


# convert from deg to rad
def rad_from_deg(deg):
    return math.radians(deg)


# t1 - t2 > secs（builtin_interfaces Time 比较）
def time_diff_gt(t1, t2, secs):
    from rclpy.time import Time, Duration

    return (Time.from_msg(t1) - Time.from_msg(t2)) > Duration(seconds=secs)


# get current system timestamp
def current_sys_timestamp():
    try:
        return round(time.time(), 2)
    except:
        return round(0.000, 2)
