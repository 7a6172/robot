#!/usr/bin/env python3
import rospy
import math
from sensor_msgs.msg import LaserScan

pub = None

# 每隔 step 个点取一个，step 越大，点越少
step = 3

# 限制角度范围：前方 120 度
angle_left = math.radians(-60)
angle_right = math.radians(60)

def scan_callback(msg):
    new_scan = LaserScan()
    new_scan.header = msg.header

    ranges = []
    intensities = []

    angles = []
    for i, r in enumerate(msg.ranges):
        angle = msg.angle_min + i * msg.angle_increment

        if angle_left <= angle <= angle_right:
            if i % step == 0:
                ranges.append(r)
                if len(msg.intensities) > i:
                    intensities.append(msg.intensities[i])

    new_scan.angle_min = angle_left
    new_scan.angle_max = angle_right
    new_scan.angle_increment = msg.angle_increment * step
    new_scan.time_increment = msg.time_increment * step
    new_scan.scan_time = msg.scan_time
    new_scan.range_min = msg.range_min
    new_scan.range_max = msg.range_max
    new_scan.ranges = ranges
    new_scan.intensities = intensities

    pub.publish(new_scan)

if __name__ == "__main__":
    rospy.init_node("scan_filter_120deg")
    pub = rospy.Publisher("/scan_filtered", LaserScan, queue_size=10)
    rospy.Subscriber("/scan", LaserScan, scan_callback)
    rospy.spin()
