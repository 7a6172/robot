# 2022-5-28 0.0.0.3A

# -*- coding: utf-8 -*-

import math
import time

import rospy
from geometry_msgs.msg import Quaternion
from rosgraph_msgs.msg import Clock
from tf.transformations import euler_from_quaternion, quaternion_from_euler

# variables
try_get_clock_time = True
use_clock_time = False

# functions


def yaw_from_quaternion(quat):
    assert isinstance(quat, Quaternion)
    (_, _, yaw) = euler_from_quaternion([quat.x, quat.y, quat.z, quat.w])
    return yaw


def quaternion_from_yaw(yaw):
    ret = Quaternion()
    (ret.x, ret.y, ret.z, ret.w) = quaternion_from_euler(0, 0, yaw)
    return ret


def rad_from_deg(deg):
    return deg * math.pi / 180.0


def deg_from_rad(rad):
    return rad * 180.0 / math.pi


def current_ros_time():
    global try_get_clock_time
    global use_clock_time

    try:
        if try_get_clock_time or use_clock_time:
            try_get_clock_time = False

            clock_data = rospy.wait_for_message(
                'clock', Clock, timeout=2)
            assert isinstance(clock_data, Clock)

            use_clock_time = True

            return clock_data.clock
        else:
            return rospy.Time.now()
    except rospy.exceptions.ROSException:
        return rospy.Time.now()


def current_sys_timestamp():
    try:
        return round(time.time(), 2)
    except:
        return round(0.000, 2)
