#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rospy
import cv2
import numpy as np
import actionlib

from cv_bridge import CvBridge, CvBridgeError
from geometry_msgs.msg import Twist, PoseStamped
from sensor_msgs.msg import Image
from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
from tf.transformations import quaternion_from_euler


class FollowThenNavigate:
    def __init__(self):
        rospy.init_node('follow_then_navigate')

        # ---------- 巡线相关 ----------
        self.cv_bridge = CvBridge()
        self.cmd_pub = rospy.Publisher('/cmd_vel', Twist, queue_size=10)
        self.lane_img_pub = rospy.Publisher('/lane_image', Image, queue_size=5)

        rospy.Subscriber('/d415/color/image_raw', Image, self.color_img_cb)
        rospy.Subscriber('/d415/depth/image_rect_raw', Image, self.depth_img_cb)

        self.yaw = 0.0
        self.flag = 0                # 横线检测标志
        self.blocked = False
        self.reached_goal = False
        self.line_detected = True

        # 巡线开始时间：用于启动后前 8 秒禁用终点横线检测
        self.start_time = None

        self.image_window_img = None
        self.test_window_img = None

        # 鼠标回调
        self.mouse_x = 0; self.mouse_y = 0
        self.mouse_b = 0; self.mouse_g = 0; self.mouse_r = 0
        self.mouse_window_name = ""

        cv2.namedWindow("Image window", cv2.WINDOW_NORMAL)
        cv2.namedWindow("test", cv2.WINDOW_NORMAL)
        cv2.setMouseCallback("Image window", self.mouse_callback_image_window)
        cv2.setMouseCallback("test", self.mouse_callback_test_window)
        cv2.startWindowThread()

        # ---------- 导航相关 ----------
        self.move_base_client = actionlib.SimpleActionClient('move_base', MoveBaseAction)
        rospy.loginfo("等待 move_base 服务器...")
        self.move_base_client.wait_for_server()
        rospy.loginfo("move_base 服务器已连接")

    # ================= 巡线逻辑 =================
    def run_line_following(self):
        """执行巡线，直到检测到横线（flag == 1）"""
        rate = rospy.Rate(20)
        self.start_time = rospy.Time.now()
        rospy.loginfo("开始巡线，前 8 秒不检测终点横线...")
        while not rospy.is_shutdown():
            vel_cmd = Twist()

            if self.flag:   # 检测到横线
                if not self.reached_goal:
                    rospy.set_param("/reached_goal", True)
                    self.reached_goal = True
                    rospy.loginfo("检测到横线，巡线完成！")
                    self.cmd_pub.publish(Twist())   # 停车
                    break

            if self.reached_goal:  # 冗余
                vel_cmd.linear.x = 0.0
                vel_cmd.angular.z = 0.0
            elif self.blocked:
                vel_cmd.linear.x = 0.0
                vel_cmd.angular.z = 0.0
            else:
                if not self.line_detected:
                    vel_cmd.linear.x = 0.0
                    vel_cmd.angular.z = 0.0
                else:
                    vel_cmd.linear.x = 0.15
                    vel_cmd.angular.z = -self.yaw * 0.75

            self.cmd_pub.publish(vel_cmd)
            rate.sleep()

    # ================= 导航逻辑 =================
    def send_goal(self, x, y, yaw, timeout=60.0):
        """发送一个导航目标并等待完成，返回是否成功"""
        goal = MoveBaseGoal()
        goal.target_pose.header.frame_id = "map"
        goal.target_pose.header.stamp = rospy.Time.now()
        goal.target_pose.pose.position.x = x
        goal.target_pose.pose.position.y = y
        goal.target_pose.pose.position.z = 0.0

        # 将偏航角转为四元数
        q = quaternion_from_euler(0, 0, yaw)
        goal.target_pose.pose.orientation.x = q[0]
        goal.target_pose.pose.orientation.y = q[1]
        goal.target_pose.pose.orientation.z = q[2]
        goal.target_pose.pose.orientation.w = q[3]

        rospy.loginfo("发送导航目标: (%.2f, %.2f), 朝向 yaw=%.2f rad", x, y, yaw)
        self.move_base_client.send_goal(goal)
        finished = self.move_base_client.wait_for_result(rospy.Duration(timeout))
        if finished:
            state = self.move_base_client.get_state()
            if state == actionlib.GoalStatus.SUCCEEDED:
                rospy.loginfo("目标点到达成功！")
                return True
            else:
                rospy.logwarn("导航失败，状态码: %d", state)
                return False
        else:
            rospy.logwarn("导航超时")
            return False

    def run_navigation_sequence(self):
        """执行两个目标点的顺序导航"""
        rospy.loginfo("开始自主导航序列...")
        # 第一个目标: (0.784, -0.214), 朝向 x 负方向 (yaw=pi)
        success = self.send_goal(0.784, -0.214, yaw=3.14159)
        if not success:
            rospy.logerr("第一个目标失败，终止导航。")
            return
        # 第二个目标: (-0.0666, 3.27), 朝向 x 正方向 (yaw=0)
        success = self.send_goal(-0.0766, 3.3, yaw=0.0)
        if success:
            rospy.loginfo("全部导航目标完成！")

    # ================= 图像回调 =================
    def mouse_callback_image_window(self, event, x, y, flags, param):
        self.handle_mouse_event(event, x, y, "Image window", self.image_window_img)

    def mouse_callback_test_window(self, event, x, y, flags, param):
        self.handle_mouse_event(event, x, y, "test", self.test_window_img)

    def handle_mouse_event(self, event, x, y, window_name, img):
        if img is None: return
        h, w = img.shape[:2]
        if x < 0 or x >= w or y < 0 or y >= h: return
        b, g, r = img[y, x]
        self.mouse_x = x; self.mouse_y = y
        self.mouse_b = int(b); self.mouse_g = int(g); self.mouse_r = int(r)
        self.mouse_window_name = window_name
        if event == cv2.EVENT_LBUTTONDOWN:
            rospy.loginfo("[%s] 鼠标点击: x=%d, y=%d, BGR=(%d,%d,%d)",
                          window_name, x, y, self.mouse_b, self.mouse_g, self.mouse_r)

    def draw_bgr_text(self, img, window_name):
        display_img = img.copy()
        if self.mouse_window_name == window_name:
            text1 = "Window: {}".format(window_name)
            text2 = "x={}, y={}".format(self.mouse_x, self.mouse_y)
            text3 = "BGR=({}, {}, {})".format(self.mouse_b, self.mouse_g, self.mouse_r)
            cv2.rectangle(display_img, (10, 10), (430, 115), (0, 0, 0), -1)
            cv2.putText(display_img, text1, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,0), 2)
            cv2.putText(display_img, text2, (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,0), 2)
            cv2.putText(display_img, text3, (20, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,0), 2)
        return display_img

    def color_img_cb(self, data):
        try:
            cv_img = self.cv_bridge.imgmsg_to_cv2(data, 'bgr8')
        except CvBridgeError as e:
            rospy.logerr("彩色图像转换失败: %s", str(e))
            return

        height, width, _ = cv_img.shape
        crop_img = cv_img[height // 2 + 100:height, 1:width]

        lower = np.array([0, 0, 0], dtype="uint8")
        upper = np.array([140, 80, 100], dtype="uint8")
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
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=100, minLineLength=100, maxLineGap=10)

        self.flag = 0

        # 巡线开始后的前 8 秒不检测终点，防止起点横线被误判
        run_time = 0.0
        if self.start_time is not None:
            run_time = (rospy.Time.now() - self.start_time).to_sec()

        if run_time > 1.0 and lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                slope = abs((y2 - y1) / (x2 - x1 + 1e-6))
                if abs(slope) < 0.2:
                    self.flag = 1
                    cv2.line(extraction, (x1, y1), (x2, y2), (0, 0, 255), 2)
                   

        #show_img = np.hstack([crop_img, extraction])
        mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        show_img = np.hstack([crop_img, mask_bgr])
        self.image_window_img = show_img.copy()
        self.test_window_img = cv_img.copy()

        try:
            self.lane_img_pub.publish(self.cv_bridge.cv2_to_imgmsg(show_img, "bgr8"))
        except CvBridgeError as e:
            rospy.logerr("调试图像发布失败: %s", str(e))

        cv2.imshow("Image window", self.draw_bgr_text(show_img, "Image window"))
        cv2.imshow("test", self.draw_bgr_text(cv_img, "test"))
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

    def shutdown(self):
        self.cmd_pub.publish(Twist())
        cv2.destroyAllWindows()


if __name__ == '__main__':
    try:
        controller = FollowThenNavigate()
        # 先执行巡线
        controller.run_line_following()
        # 巡线完成后执行导航
        controller.run_navigation_sequence()
        rospy.loginfo("任务结束，节点退出")
    except rospy.ROSInterruptException:
        pass

