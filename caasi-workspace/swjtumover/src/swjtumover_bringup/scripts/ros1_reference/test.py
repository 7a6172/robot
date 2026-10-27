#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rospy
import cv2
import numpy as np
from sensor_msgs.msg import Image
from cv_bridge import CvBridge, CvBridgeError


class ColorThresholdTuner:
    def __init__(self):
        rospy.init_node("color_threshold_tuner", anonymous=True)
        self.bridge = CvBridge()
        self.image_sub = rospy.Subscriber("/d415/color/image_raw", Image, self.image_callback)
        self.cv_img = None

        # 创建窗口和滑动条
        cv2.namedWindow("Trackbars", cv2.WINDOW_NORMAL)
        cv2.createTrackbar("LH", "Trackbars", 0, 180, lambda x: None)
        cv2.createTrackbar("LS", "Trackbars", 0, 255, lambda x: None)
        cv2.createTrackbar("LV", "Trackbars", 48, 255, lambda x: None)
        cv2.createTrackbar("UH", "Trackbars", 100, 180, lambda x: None)
        cv2.createTrackbar("US", "Trackbars", 139, 255, lambda x: None)
        cv2.createTrackbar("UV", "Trackbars", 105, 255, lambda x: None)

        rospy.loginfo("颜色阈值调试器已启动，按 ESC 退出。")

        while not rospy.is_shutdown():
            if self.cv_img is not None:
                self.show_threshold_preview()
            if cv2.waitKey(1) & 0xFF == 27:  # ESC退出
                break

        cv2.destroyAllWindows()

    def image_callback(self, msg):
        try:
            self.cv_img = self.bridge.imgmsg_to_cv2(msg, "bgr8")
        except CvBridgeError as e:
            rospy.logerr(f"图像转换失败: {e}")

    def show_threshold_preview(self):
        frame = self.cv_img.copy()
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # 获取当前滑动条参数
        lh = cv2.getTrackbarPos("LH", "Trackbars")
        ls = cv2.getTrackbarPos("LS", "Trackbars")
        lv = cv2.getTrackbarPos("LV", "Trackbars")
        uh = cv2.getTrackbarPos("UH", "Trackbars")
        us = cv2.getTrackbarPos("US", "Trackbars")
        uv = cv2.getTrackbarPos("UV", "Trackbars")

        lower = np.array([lh, ls, lv])
        upper = np.array([uh, us, uv])

        # 二值化处理
        mask = cv2.inRange(hsv, lower, upper)
        result = cv2.bitwise_and(frame, frame, mask=mask)

        # 拼接显示
        hstack = np.hstack((frame, cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR), result))
        cv2.imshow("Threshold Debug (BGR | Mask | Result)", hstack)


if __name__ == "__main__":
    try:
        ColorThresholdTuner()
    except rospy.ROSInterruptException:
        pass
