#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rospy
import math
from sensor_msgs.msg import LaserScan
from geometry_msgs.msg import Twist


LINEAR_VEL = 0.2          
STOP_DISTANCE = 0.8    
LIDAR_ERROR = 0.05       
SAFE_STOP_DISTANCE = STOP_DISTANCE + LIDAR_ERROR

FRONT_ANGLE_DEG = 10     


class ObstacleAvoidance:
    def __init__(self):
        rospy.init_node('omove_obstacle', anonymous=False)

        self.cmd_pub = rospy.Publisher('/cmd_vel', Twist, queue_size=1)

        self.scan_msg = None
        self.moving = False

        rospy.Subscriber('/scan', LaserScan, self.scan_callback)

        rospy.on_shutdown(self.shutdown)

        rospy.loginfo("避障节点已启动")
        rospy.loginfo("检测范围：正前方 ±%.1f 度", FRONT_ANGLE_DEG)
        rospy.loginfo("安全停止距离：%.3f m", SAFE_STOP_DISTANCE)

    def scan_callback(self, msg):
        self.scan_msg = msg

    def get_front_distances(self):
        """
        获取小车正前方一定角度范围内的有效雷达距离
        """

        if self.scan_msg is None:
            return []

        scan = self.scan_msg

        front_angle = 0.0
        half_angle = math.radians(FRONT_ANGLE_DEG)

        start_angle = front_angle - half_angle
        end_angle = front_angle + half_angle

        start_index = int((start_angle - scan.angle_min) / scan.angle_increment)
        end_index = int((end_angle - scan.angle_min) / scan.angle_increment)

        start_index = max(0, start_index)
        end_index = min(len(scan.ranges) - 1, end_index)

        front_ranges_raw = scan.ranges[start_index:end_index + 1]

        valid_ranges = []

        nan_count = 0
        zero_count = 0
        inf_count = 0
        invalid_count = 0

        for distance in front_ranges_raw:
            if math.isnan(distance):
                nan_count += 1
                continue

            if math.isinf(distance):
                inf_count += 1
                valid_ranges.append(scan.range_max)
                continue

            if distance <= 0.0:
                zero_count += 1
                continue

            if distance < scan.range_min or distance > scan.range_max:
                invalid_count += 1
                continue

            valid_ranges.append(distance)

        rospy.loginfo_throttle(
            1.0,
            "front_index=[%d:%d], raw=%d, valid=%d, nan=%d, zero=%d, inf=%d, invalid=%d",
            start_index,
            end_index,
            len(front_ranges_raw),
            len(valid_ranges),
            nan_count,
            zero_count,
            inf_count,
            invalid_count
        )

        return valid_ranges

    def stop_robot(self):
        twist = Twist()
        twist.linear.x = 0.0
        twist.angular.z = 0.0
        self.cmd_pub.publish(twist)
        self.moving = False

    def move_forward(self):
        twist = Twist()
        twist.linear.x = LINEAR_VEL
        twist.angular.z = 0.0
        self.cmd_pub.publish(twist)
        self.moving = True

    def run(self):
        rate = rospy.Rate(10)

        while not rospy.is_shutdown():
            front_distances = self.get_front_distances()

            if not front_distances:
                rospy.logwarn_throttle(
                    1.0,
                    "前方没有有效雷达数据，出于安全考虑停车"
                )
                self.stop_robot()
                rate.sleep()
                continue

            min_distance = min(front_distances)

            rospy.loginfo_throttle(
                1.0,
                "前方最小距离 min_distance = %.3f m, SAFE_STOP_DISTANCE = %.3f m",
                min_distance,
                SAFE_STOP_DISTANCE
            )

            if min_distance < SAFE_STOP_DISTANCE:
                if self.moving:
                    rospy.logwarn(
                        "Stop! 前方障碍物距离 %.3f m 小于安全距离 %.3f m",
                        min_distance,
                        SAFE_STOP_DISTANCE
                    )
                self.stop_robot()
            else:
                self.move_forward()
                rospy.loginfo_throttle(
                    1.0,
                    "Go! 前方安全，距离 %.3f m",
                    min_distance
                )

            rate.sleep()

    def shutdown(self):
        rospy.loginfo("节点关闭，停止小车")
        self.stop_robot()


if __name__ == '__main__':
    try:
        node = ObstacleAvoidance()
        node.run()
    except rospy.ROSInterruptException:
        pass
