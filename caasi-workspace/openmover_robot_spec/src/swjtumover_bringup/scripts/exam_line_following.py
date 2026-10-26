#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能自主系统考核项目：阶段1——视觉循线

功能：
1. 等待导航与定位模块准备完成；
2. 订阅 D415 彩色图像并识别黑色寻迹线；
3. 根据黑线质心偏差发布 /cmd_vel；
4. 检测到终点横线后稳定停车，再发布 /exam/line_finished=True；
5. 结束后不再发布速度，避免与 move_base 抢占 /cmd_vel。
"""

import math
import rospy
import cv2
import numpy as np

from cv_bridge import CvBridge, CvBridgeError
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Image
from std_msgs.msg import Bool


class ExamLineFollowing(object):
    def __init__(self):
        rospy.init_node("exam_line_following", anonymous=False)

        self.image_topic = rospy.get_param("~image_topic", "/d415/color/image_raw")
        self.cmd_topic = rospy.get_param("~cmd_topic", "/cmd_vel")
        self.finish_topic = rospy.get_param("~finish_topic", "/exam/line_finished")
        self.debug_image_topic = rospy.get_param("~debug_image_topic", "/exam/lane_debug")

        # 与单独运行时保持一致。现场取色后只修改 launch 中这一组参数即可。
        self.lower_bgr = np.array(
            rospy.get_param("~lower_bgr", [20, 30, 20]), dtype=np.uint8
        )
        self.upper_bgr = np.array(
            rospy.get_param("~upper_bgr", [75, 85, 75]), dtype=np.uint8
        )

        self.roi_y_start_ratio = float(rospy.get_param("~roi_y_start_ratio", 0.55))
        # 摄像头位于机身左侧，因此期望黑线位置向画面右侧偏移。
        self.target_x_ratio = float(rospy.get_param("~target_x_ratio", 0.62))

        self.linear_speed = float(rospy.get_param("~linear_speed", 0.10))
        self.kp_angular = float(rospy.get_param("~kp_angular", 1.00))
        self.max_linear_speed = float(rospy.get_param("~max_linear_speed", 0.50))
        self.max_angular_speed = float(rospy.get_param("~max_angular_speed", 0.30))

        self.lost_stop_frames = int(rospy.get_param("~lost_stop_frames", 3))
        self.lost_count = 0

        self.end_marker_min_width_ratio = float(
            rospy.get_param("~end_marker_min_width_ratio", 0.30)
        )
        self.end_marker_slope_abs_max = float(
            rospy.get_param("~end_marker_slope_abs_max", 0.20)
        )
        self.end_confirm_frames = int(rospy.get_param("~end_confirm_frames", 6))
        self.end_count = 0
        self.finished = False

        # 一键启动时，先等 AMCL 与 move_base 准备完成，避免未定位就开始运动。
        self.wait_localization_ready = bool(
            rospy.get_param("~wait_localization_ready", False)
        )
        self.localization_ready_param = rospy.get_param(
            "~localization_ready_param", "/exam/localization_ready"
        )
        self.localization_wait_timeout = float(
            rospy.get_param("~localization_wait_timeout", 30.0)
        )

        # 检测到终点后保持停车一小段时间，再把控制权交给 move_base。
        self.handoff_stop_time = float(rospy.get_param("~handoff_stop_time", 1.0))
        self.show_window = bool(rospy.get_param("~show_window", False))

        self.bridge = CvBridge()
        self.cmd_pub = rospy.Publisher(self.cmd_topic, Twist, queue_size=5)
        self.finish_pub = rospy.Publisher(
            self.finish_topic, Bool, queue_size=1, latch=True
        )
        self.debug_pub = rospy.Publisher(
            self.debug_image_topic, Image, queue_size=2
        )

        rospy.on_shutdown(self.shutdown)

        if self.show_window:
            cv2.namedWindow("lane_debug", cv2.WINDOW_NORMAL)
            cv2.startWindowThread()

        # 清除上一次运行遗留的完成状态。
        rospy.set_param("/exam/line_finished", False)
        self.finish_pub.publish(Bool(False))

        rospy.loginfo(
            "循线参数: lower=%s upper=%s speed=%.2f kp=%.2f max_wz=%.2f target_x=%.2f",
            self.lower_bgr.tolist(),
            self.upper_bgr.tolist(),
            self.linear_speed,
            self.kp_angular,
            self.max_angular_speed,
            self.target_x_ratio,
        )

        if self.wait_localization_ready:
            self.wait_for_localization()

        if rospy.is_shutdown():
            return

        self.image_sub = rospy.Subscriber(
            self.image_topic, Image, self.image_cb, queue_size=1
        )
        rospy.loginfo("exam_line_following started, image_topic=%s", self.image_topic)
        rospy.spin()

    def wait_for_localization(self):
        rospy.loginfo(
            "等待定位与导航模块准备完成: %s=True",
            self.localization_ready_param,
        )
        start_time = rospy.Time.now()
        rate = rospy.Rate(10)

        while not rospy.is_shutdown():
            ready = bool(rospy.get_param(self.localization_ready_param, False))
            if ready:
                rospy.loginfo("定位与导航模块已准备，开始视觉循线")
                return

            elapsed = (rospy.Time.now() - start_time).to_sec()
            if self.localization_wait_timeout > 0 and elapsed > self.localization_wait_timeout:
                rospy.logerr(
                    "等待定位准备超时 %.1f 秒。为安全起见，循线节点不启动。",
                    self.localization_wait_timeout,
                )
                rospy.signal_shutdown("localization not ready")
                return
            rate.sleep()

    @staticmethod
    def clamp(value, low, high):
        return max(low, min(high, value))

    def publish_stop(self):
        self.cmd_pub.publish(Twist())

    def hold_stop(self, duration):
        end_time = rospy.Time.now() + rospy.Duration(max(0.0, duration))
        rate = rospy.Rate(20)
        while not rospy.is_shutdown() and rospy.Time.now() < end_time:
            self.publish_stop()
            rate.sleep()
        self.publish_stop()

    def image_cb(self, msg):
        if self.finished:
            return

        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except CvBridgeError as exc:
            rospy.logerr_throttle(1.0, "cv_bridge 转换失败: %s", str(exc))
            self.publish_stop()
            return

        h, w = frame.shape[:2]
        y0 = int(h * self.roi_y_start_ratio)
        roi = frame[y0:h, 0:w]
        roi_h, roi_w = roi.shape[:2]

        mask = cv2.inRange(roi, self.lower_bgr, self.upper_bgr)
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        moments = cv2.moments(mask, binaryImage=True)
        line_detected = moments["m00"] > 0

        debug = roi.copy()
        cmd = Twist()
        target_x = int(roi_w * self.target_x_ratio)

        if line_detected:
            self.lost_count = 0
            cx = int(moments["m10"] / moments["m00"])
            cy = int(moments["m01"] / moments["m00"])
            error = (cx - target_x) / (roi_w / 2.0)

            cmd.linear.x = self.clamp(
                self.linear_speed, 0.0, self.max_linear_speed
            )
            cmd.angular.z = self.clamp(
                -self.kp_angular * error,
                -self.max_angular_speed,
                self.max_angular_speed,
            )

            cv2.circle(debug, (cx, cy), 5, (0, 255, 0), -1)
            cv2.line(debug, (target_x, 0), (target_x, roi_h), (255, 0, 0), 2)
            cv2.putText(
                debug,
                "err={:.2f}, wz={:.2f}".format(error, cmd.angular.z),
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
            )
        else:
            self.lost_count += 1
            cv2.putText(
                debug,
                "line lost",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 0, 255),
                2,
            )
            if self.lost_count >= self.lost_stop_frames:
                cmd = Twist()
            else:
                cmd.linear.x = self.clamp(
                    self.linear_speed * 0.5, 0.0, self.max_linear_speed
                )

        end_found = self.detect_end_marker(mask, debug)
        self.end_count = self.end_count + 1 if end_found else 0

        if self.end_count >= self.end_confirm_frames:
            rospy.logwarn("检测到终点横线，稳定停车后切换到导航阶段")
            self.finished = True
            self.hold_stop(self.handoff_stop_time)
            rospy.set_param("/exam/line_finished", True)
            self.finish_pub.publish(Bool(True))
            self.publish_debug(debug, mask)
            rospy.loginfo("已发布 /exam/line_finished=True，停止循线速度输出")
            return

        self.cmd_pub.publish(cmd)
        self.publish_debug(debug, mask)

    def detect_end_marker(self, mask, debug_img):
        roi_h, roi_w = mask.shape[:2]
        min_len = int(roi_w * self.end_marker_min_width_ratio)

        edges = cv2.Canny(mask, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180.0,
            threshold=60,
            minLineLength=min_len,
            maxLineGap=20,
        )
        if lines is None:
            return False

        for item in lines:
            x1, y1, x2, y2 = item[0]
            dx = float(x2 - x1)
            dy = float(y2 - y1)
            length = math.hypot(dx, dy)
            if length < min_len:
                continue

            slope = abs(dy / (dx + 1e-6))
            y_mid = (y1 + y2) / 2.0
            if slope <= self.end_marker_slope_abs_max and y_mid > roi_h * 0.35:
                cv2.line(debug_img, (x1, y1), (x2, y2), (0, 0, 255), 3)
                cv2.putText(
                    debug_img,
                    "END marker",
                    (10, 65),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 0, 255),
                    2,
                )
                return True
        return False

    def publish_debug(self, debug_bgr, mask):
        mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        show = np.hstack([debug_bgr, mask_bgr])
        try:
            self.debug_pub.publish(
                self.bridge.cv2_to_imgmsg(show, encoding="bgr8")
            )
        except CvBridgeError as exc:
            rospy.logerr_throttle(1.0, "调试图像发布失败: %s", str(exc))

        if self.show_window:
            cv2.imshow("lane_debug", show)
            cv2.waitKey(1)

    def shutdown(self):
        self.publish_stop()
        if self.show_window:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        ExamLineFollowing()
    except rospy.ROSInterruptException:
        pass
