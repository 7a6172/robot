#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rospy
import cv2
import numpy as np
import actionlib

from cv_bridge import CvBridge, CvBridgeError
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Image
from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal


class ExamRun:

    def __init__(self):
        
        rospy.init_node("exam_run")

        self.bridge = CvBridge()

        self.cmd_pub = rospy.Publisher("/cmd_vel", Twist, queue_size=10)
        self.lane_img_pub = rospy.Publisher("/lane_image", Image, queue_size=5)

        # 同时订阅两种常见彩色相机话题，哪个有图像就用哪个
        self.mode = "FOLLOW_LINE"
        self.nav_started = False
        self.yaw = 0.0
        self.line_detected = False
        self.end_count = 0
        self.end_detected = False
        rospy.Subscriber("/d415/color/image_raw", Image, self.color_img_cb)
        rospy.Subscriber("/camera/color/image_raw", Image, self.color_img_cb)

        # move_base action 客户端
        self.client = actionlib.SimpleActionClient("move_base", MoveBaseAction)
        rospy.loginfo("正在等待 move_base...")
        self.move_base_ready = self.client.wait_for_server(rospy.Duration(10.0))

        if self.move_base_ready:
            rospy.loginfo("move_base 已连接")
        else:
            rospy.logwarn("move_base 暂未连接，到终点后会再次等待")

        # 状态：FOLLOW_LINE 巡线，NAVIGATING 导航返回，PARK 停车
        
        

        # 启动时间，用于防止起点停车线被误判为终点横线
        self.start_time = rospy.Time.now()

        # 巡线变量
        

        # 终点横线检测
        

        # 图像窗口和鼠标取色
        self.image_window_img = None
        self.mouse_x = 0
        self.mouse_y = 0
        self.mouse_b = 0
        self.mouse_g = 0
        self.mouse_r = 0
        self.mouse_window_name = ""

        cv2.namedWindow("Image window", cv2.WINDOW_NORMAL)
        cv2.setMouseCallback("Image window", self.mouse_callback_image_window)
        cv2.startWindowThread()

        rospy.on_shutdown(self.shutdown)

        # 最新设置的 4 个导航点
        # 顺序：巡线终点附近 -> 返回通道 -> 起点附近 -> 最终停车点
        

        self.main_loop()

    def main_loop(self):
        rate = rospy.Rate(20)

        while not rospy.is_shutdown():

            if self.mode == "FOLLOW_LINE":

                if self.end_detected and not self.nav_started:
                    rospy.loginfo("检测到终点横线，停车，切换到导航返回")
                    self.stop_robot()
                    rospy.sleep(1.0)

                    self.mode = "NAVIGATING"
                    self.nav_started = True

                    # 进入导航后，不再持续发布 /cmd_vel，避免和 move_base 抢速度
                    self.navigate_back()

                else:
                    cmd = Twist()

                    if not self.line_detected:
                        # 丢线时慢速找线，防止起点不动
                        cmd.linear.x = 0.04
                        cmd.linear.y = 0.0
                        cmd.angular.z = 0.12

                    else:
                        cmd.linear.x = 0.15
                        cmd.linear.y = 0.0
                        cmd.angular.z = -self.yaw * 1.18

                        # 限制角速度，避免转向过猛
                        if cmd.angular.z > 0.35:
                            cmd.angular.z = 0.35
                        if cmd.angular.z < -0.35:
                            cmd.angular.z = -0.35

                    self.cmd_pub.publish(cmd)

            elif self.mode == "PARK":
                self.stop_robot()

            rate.sleep()

    def color_img_cb(self, data):
        if self.mode != "FOLLOW_LINE":
            return

        try:
            cv_img = self.bridge.imgmsg_to_cv2(data, "bgr8")
        except CvBridgeError as e:
            rospy.logerr("彩色图像转换失败: %s", str(e))
            return

        height, width = cv_img.shape[:2]

        # 取图像下半部分，主要识别地面黑线
        crop_img = cv_img[height // 2:height, 1:width]
        crop_h, crop_w = crop_img.shape[:2]

        # 黑色阈值，OpenCV 是 BGR 顺序
        # 如果黑线识别不到，可以把 upper 改成 [120, 120, 120]
        lower = np.array([0, 0, 0], dtype="uint8")
        upper = np.array([100, 100, 100], dtype="uint8")

        mask = cv2.inRange(crop_img, lower, upper)

        # 去噪处理
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        extraction = cv2.bitwise_and(crop_img, crop_img, mask=mask)

        # 计算黑线中心
        m = cv2.moments(mask, False)

        if m["m00"] > 300:
            self.line_detected = True

            cx = m["m10"] / m["m00"]
            cy = m["m01"] / m["m00"]

            self.yaw = (cx - crop_w / 2.0) / 320.0

        else:
            self.line_detected = False
            cx = crop_w / 2.0
            cy = crop_h / 2.0
            self.yaw = 0.0

        cv2.circle(extraction, (int(cx), int(cy)), 5, (0, 255, 0), 3)

        # 终点横线检测：寻找较长的水平黑线
        gray = cv2.cvtColor(extraction, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)

        lines = cv2.HoughLinesP(
            edges,
            1,
            np.pi / 180,
            threshold=80,
            minLineLength=100,
            maxLineGap=20
        )

        horizontal_found = False

        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]

                dx = x2 - x1
                dy = y2 - y1

                if abs(dx) < 1:
                    continue

                slope = abs(dy / float(dx))

                # slope 越小越接近水平线，并且长度要够长
                if slope < 0.2 and abs(dx) > crop_w * 0.35:
                    horizontal_found = True
                    cv2.line(extraction, (x1, y1), (x2, y2), (0, 0, 255), 3)

        # 启动前 8 秒不检测终点，防止起点停车线误判
        run_time = (rospy.Time.now() - self.start_time).to_sec()

        if run_time > 8.0:
            if horizontal_found:
                self.end_count += 1
            else:
                self.end_count = 0
        else:
            self.end_count = 0

        # 连续 5 帧识别到横线，才认为到达终点
        if self.end_count >= 5:
            self.end_detected = True

        # 显示调试画面：左边原图，右边识别结果
        show_img = np.hstack([crop_img, extraction])
        self.image_window_img = show_img.copy()

        info1 = "mode: {}".format(self.mode)
        info2 = "line: {}, yaw: {:.3f}".format(self.line_detected, self.yaw)
        info3 = "end_count: {}, time: {:.1f}s".format(self.end_count, run_time)

        cv2.putText(show_img, info1, (20, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.putText(show_img, info2, (20, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.putText(show_img, info3, (20, 105),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        display_img = self.draw_bgr_text(show_img, "Image window")

        try:
            self.lane_img_pub.publish(
                self.bridge.cv2_to_imgmsg(show_img, "bgr8")
            )
        except CvBridgeError:
            pass

        cv2.imshow("Image window", display_img)
        cv2.waitKey(1)

    def make_goal(self, x, y, z, w):
        goal = MoveBaseGoal()

        goal.target_pose.header.frame_id = "map"
        goal.target_pose.header.stamp = rospy.Time.now()

        goal.target_pose.pose.position.x = x
        goal.target_pose.pose.position.y = y
        goal.target_pose.pose.position.z = 0.0

        goal.target_pose.pose.orientation.x = 0.0
        goal.target_pose.pose.orientation.y = 0.0
        goal.target_pose.pose.orientation.z = z
        goal.target_pose.pose.orientation.w = w

        return goal

    def navigate_back(self):
        rospy.loginfo("开始自主导航返回起点...")

        if not self.move_base_ready:
            rospy.loginfo("再次等待 move_base，最多等待 15 秒...")
            self.move_base_ready = self.client.wait_for_server(rospy.Duration(15.0))

        if not self.move_base_ready:
            rospy.logerr("move_base 未启动，无法导航返回，停车")
            self.mode = "PARK"
            self.stop_robot()
            return

        # 核心修改：不再人为切分航点！只给系统下达唯一的“最终目标”
        # TODO: 请将这里的 0.0, 0.0, 0.0, 1.0 替换为你实际在 RViz 中标定的起点精准坐标和姿态
        final_x = 2.46
        final_y = -1.60
        final_z = -0.95
        final_w = 0.33

        rospy.loginfo(f"发送最终停车点: x={final_x}, y={final_y}, z={final_z}, w={final_w}")
        goal = self.make_goal(final_x, final_y, final_z, final_w)
        self.client.send_goal(goal)

        # 把等待时间拉长，给它留足在复杂障碍物间绕路思考的时间
        finished = self.client.wait_for_result(rospy.Duration(120.0))

        if not finished:
            rospy.logwarn("避障超时或完全被纸箱堵死，取消目标并停车")
            self.client.cancel_goal()
            self.stop_robot()
            self.mode = "PARK"
            return

        rospy.loginfo("完美！4 个字：自主规划。已避开所有障碍物回到起点，停车")
        self.mode = "PARK"
        self.stop_robot()

    def stop_robot(self):
        cmd = Twist()
        cmd.linear.x = 0.0
        cmd.linear.y = 0.0
        cmd.angular.z = 0.0
        self.cmd_pub.publish(cmd)

    def mouse_callback_image_window(self, event, x, y, flags, param):
        self.handle_mouse_event(event, x, y, "Image window", self.image_window_img)

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

            cv2.rectangle(display_img, (10, 120), (440, 225), (0, 0, 0), -1)

            cv2.putText(display_img, text1, (20, 150),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.putText(display_img, text2, (20, 185),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.putText(display_img, text3, (20, 220),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        return display_img

    def shutdown(self):
        self.stop_robot()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        ExamRun()
    except rospy.ROSInterruptException:
        pass
