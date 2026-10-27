#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rospy
import cv2
import numpy as np

from cv_bridge import CvBridge, CvBridgeError
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Image


class OmoveFollowing():

    def __init__(self):
        rospy.init_node('omove_following')

        self.cv_bridge = CvBridge()

        self.cmd_pub = rospy.Publisher('/cmd_vel', Twist, queue_size=10)
        self.lane_img_pub = rospy.Publisher('/lane_image', Image, queue_size=5)

        rospy.Subscriber('/d415/color/image_raw', Image, self.color_img_cb)
        rospy.Subscriber('/d415/depth/image_rect_raw', Image, self.depth_img_cb)

        self.yaw = 0.0
        self.flag = 0
        self.blocked = False
        self.reached_goal = False
        self.line_detected = True
        # ========== 新增1：终点停车计数器（仅此一行） ==========
        self.stop_count = 0

        self.image_window_img = None
        self.test_window_img = None

        self.mouse_x = 0
        self.mouse_y = 0
        self.mouse_b = 0
        self.mouse_g = 0
        self.mouse_r = 0
        self.mouse_window_name = ""

        cv2.namedWindow("Image window", cv2.WINDOW_NORMAL)
        cv2.namedWindow("test", cv2.WINDOW_NORMAL)

        
        cv2.setMouseCallback("Image window",self.mouse_callback_image_window)
        cv2.setMouseCallback("test", self.mouse_callback_test_window)

        cv2.startWindowThread()

        rospy.on_shutdown(self.shutdown)


        rate = rospy.Rate(20)

        while not rospy.is_shutdown():
            vel_cmd = Twist()

            if self.flag:
                if not self.reached_goal:
                    rospy.set_param("/reached_goal", True)
                    self.reached_goal = True

            if self.reached_goal:
                vel_cmd.linear.x = 0.0
                vel_cmd.linear.y = 0.0
                vel_cmd.angular.z = 0.0
                # ========== 新增2：停车2.5秒后自动退出节点（仅此4行） ==========
                self.stop_count += 1
                if self.stop_count > 50:  # 20Hz频率，50次 = 2.5秒
                    rospy.signal_shutdown("巡线任务完成，自动退出")

            elif self.blocked:

                vel_cmd.linear.x = 0.0
                vel_cmd.linear.y = 0.0
                vel_cmd.angular.z = 0.0

            else:
                if not self.line_detected:

                    vel_cmd.linear.x = 0.0
                    vel_cmd.linear.y = 0.0
                    vel_cmd.angular.z = 0.0

                else:
                    vel_cmd.linear.x = 0.15
                    vel_cmd.linear.y = 0.0
                    vel_cmd.angular.z = -self.yaw * 0.5

            self.cmd_pub.publish(vel_cmd)
            rate.sleep()

    def mouse_callback_image_window(self, event, x, y, flags, param):
        self.handle_mouse_event(event, x, y, "Image window", self.image_window_img)

    def mouse_callback_test_window(self, event, x, y, flags, param):
        self.handle_mouse_event(event, x, y, "test", self.test_window_img)

    def handle_mouse_event(self, event, x, y, window_name, img):
        if img is None:
            return

        h, w = img.shape[:2]

        if x < 0 or x >= w or y < 0 or y >= h:
            return

        b, g, r = img[y, x]

        self.mouse_x = x
        self.mouse_y = y
        self.mouse_b = int(b)
        self.mouse_g = int(g)
        self.mouse_r = int(r)
        self.mouse_window_name = window_name

        if event == cv2.EVENT_LBUTTONDOWN:
            rospy.loginfo(
                "[%s] 鼠标点击: x=%d, y=%d, BGR=(%d, %d, %d)",
                window_name,
                x,
                y,
                self.mouse_b,
                self.mouse_g,
                self.mouse_r
            )

    def draw_bgr_text(self, img, window_name):
        display_img = img.copy()

        if self.mouse_window_name == window_name:
            text1 = "Window: {}".format(window_name)
            text2 = "x={}, y={}".format(self.mouse_x, self.mouse_y)
            text3 = "BGR=({}, {}, {})".format(
                self.mouse_b,
                self.mouse_g,
                self.mouse_r
            )

            cv2.rectangle(display_img, (10, 10), (430, 115), (0, 0, 0), -1)

            cv2.putText(
                display_img,
                text1,
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2
            )

            cv2.putText(
                display_img,
                text2,
                (20, 75),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2
            )

            cv2.putText(
                display_img,
                text3,
                (20, 110),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2
            )

        return display_img

    def color_img_cb(self, data):
        try:
            cv_img = self.cv_bridge.imgmsg_to_cv2(data, 'bgr8')
        except CvBridgeError as e:
            rospy.logerr("彩色图像转换失败: %s", str(e))
            return

        height, width, channels = cv_img.shape

        crop_img = cv_img[height // 2 + 100:height, 1:width]

        lower = np.array([0, 0, 0], dtype="uint8")
        upper = np.array([60, 60, 60], dtype="uint8")

        mask = cv2.inRange(crop_img, lower, upper)
        extraction = cv2.bitwise_and(crop_img, crop_img, mask=mask)

        m = cv2.moments(mask, False)

        if m['m00'] > 0:
            self.line_detected = True

            x = m['m10'] / m['m00']
            y = m['m01'] / m['m00']

            self.yaw = (x - width / 2) / 320.0

        else:
            self.line_detected = False

            x = width / 2
            y = crop_img.shape[0] / 2

            self.yaw = 0.0

        cv2.circle(extraction, (int(x), int(y)), 2, (0, 255, 0), 3)

        gray = cv2.cvtColor(extraction, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)

        lines = cv2.HoughLinesP(
            edges,
            1,
            np.pi / 180,
            threshold=100,
            minLineLength=100,
            maxLineGap=10
        )

        self.flag = 0

        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]

                slope = abs((y2 - y1) / (x2 - x1 + 1e-6))

                if abs(slope) < 0.2:
                    self.flag = 1
                    cv2.line(extraction, (x1, y1), (x2, y2), (0, 0, 255), 2)


        show_img = np.hstack([crop_img, extraction])


        self.image_window_img = show_img.copy()

        self.test_window_img = cv_img.copy()

        try:
            self.lane_img_pub.publish(
                self.cv_bridge.cv2_to_imgmsg(show_img, "bgr8")
            )
        except CvBridgeError as e:
            rospy.logerr("调试图像发布失败: %s", str(e))

        image_window_display = self.draw_bgr_text(show_img, "Image window")
        test_window_display = self.draw_bgr_text(cv_img, "test")

        cv2.imshow("Image window", image_window_display)
        cv2.imshow("test", test_window_display)
        cv2.waitKey(1)

    def depth_img_cb(self, data):
        try:
            depth_img = self.cv_bridge.imgmsg_to_cv2(data, '16UC1')
        except CvBridgeError as e:
            rospy.logerr("深度图像转换失败: %s", str(e))
            return

        height, width = depth_img.shape

        if height > 400:
            for dis in depth_img[400:401, 0:width][0]:
                if 300 < dis < 350:
                    self.blocked = False
                    break

    def stop_robot(self):
        vel_cmd = Twist()
        vel_cmd.linear.x = 0.0
        vel_cmd.linear.y = 0.0
        vel_cmd.angular.z = 0.0
        self.cmd_pub.publish(vel_cmd)

    def shutdown(self):
        self.stop_robot()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    try:
        OmoveFollowing()
    except rospy.ROSInterruptException:
        pass
