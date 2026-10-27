#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rospy
import cv2
import numpy as np
from cv_bridge import CvBridge, CvBridgeError
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Image

class OmoveFollowing:
    def __init__(self):
        rospy.init_node('omove_following', anonymous=False)
        self.cv_bridge = CvBridge()
        
        # 发布控制命令
        self.cmd_pub = rospy.Publisher('/cmd_vel', Twist, queue_size=10)
        # 发布处理后的掩模图像（用于调试）
        self.lane_img_pub = rospy.Publisher('/lane_image', Image, queue_size=5)
        
        # 订阅彩色图像（循线主数据）
        rospy.Subscriber('/camera/color/image_raw', Image, self.color_img_cb)
        # 订阅深度图像（可选，用于避障，本实验简化）
        rospy.Subscriber('/camera/depth/image_rect_raw', Image, self.depth_img_cb)
        
        # 控制参数
        self.yaw = 0.0          # 角速度系数
        self.blocked = False    # 障碍物标志（本实验未使用深度避障，可保留）
        
        # 图像裁剪参数（只关注图像下半部分，减少干扰）
        self.crop_ratio = 0.5   # 从图像高度的一半开始裁剪到底部
        
        # 颜色阈值（初始值，需根据实际线路RGB值调整）
        # 黑色线路的RGB范围示例（实际需现场调试）
        self.lower_black = np.array([0, 0, 0], dtype="uint8")
        self.upper_black = np.array([80, 80, 80], dtype="uint8")
        
        # 主循环（发布控制指令）
        rate = rospy.Rate(20)   # 20 Hz
        while not rospy.is_shutdown():
            vel_cmd = Twist()
            if self.blocked:
                # 遇到障碍物时的避障动作（本实验循线过程中可忽略）
                for _ in range(20):
                    vel_cmd.linear.y = 0.1
                    self.cmd_pub.publish(vel_cmd)
                    rospy.sleep(0.1)
                for _ in range(30):
                    vel_cmd.linear.x = -0.1
                    self.cmd_pub.publish(vel_cmd)
                    rospy.sleep(0.1)
                for _ in range(20):
                    vel_cmd.linear.y = -0.1
                    self.cmd_pub.publish(vel_cmd)
                    rospy.sleep(0.1)
                self.blocked = False
            else:
                # 正常循线：前进 + 根据线路中心偏差调整角速度
                vel_cmd.linear.x = -0.1          # 前进速度（负值因为机器人坐标定义）
                vel_cmd.angular.z = self.yaw * 0.4   # 比例控制角速度
                self.cmd_pub.publish(vel_cmd)
            rate.sleep()
    
    def color_img_cb(self, data):
        """处理彩色图像，提取线路中心，计算角速度"""
        try:
            cv_img = self.cv_bridge.imgmsg_to_cv2(data, 'bgr8')
        except CvBridgeError as e:
            rospy.logerr(e)
            return
        
        # 1. 裁剪图像（取下半部分，减小无关干扰）
        height, width = cv_img.shape[:2]
        crop_start = int(height * self.crop_ratio)
        crop_img = cv_img[crop_start:height, :]
        crop_h, crop_w = crop_img.shape[:2]
        
        # 2. 颜色掩模：提取黑色线路
        mask = cv2.inRange(crop_img, self.lower_black, self.upper_black)
        
        # 3. 可选：形态学操作去除噪声
        kernel = np.ones((3,3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        
        # 4. 计算掩模的矩（寻找质心）
        m = cv2.moments(mask)
        if m['m00'] != 0:
            cx = int(m['m10'] / m['m00'])
            cy = int(m['m01'] / m['m00'])
        else:
            # 没有检测到线路时，保持上次角度或默认值
            cx, cy = crop_w // 2, crop_h // 2
        
        # 5. 计算偏差并转换为角速度系数（归一化到 [-1, 1]）
        # 偏差 = 质心x坐标 - 图像中心x坐标，然后除以半个宽度得到比例
        self.yaw = (cx - crop_w / 2.0) / (crop_w / 2.0)   # 范围 [-1, 1]
        
        # 6. 在掩模图像上标记质心（用于调试）
        mask_color = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        cv2.circle(mask_color, (cx, cy), 5, (0, 255, 0), -1)
        
        # 7. 发布掩模图像（方便在rqt_image_view中查看）
        try:
            lane_img_msg = self.cv_bridge.cv2_to_imgmsg(mask_color, 'bgr8')
            self.lane_img_pub.publish(lane_img_msg)
        except CvBridgeError as e:
            rospy.logerr(e)
        
        # 8. 本地显示（可选，用于调试）
        cv2.imshow("Mask Image", mask_color)
        cv2.imshow("Original Cropped", crop_img)
        cv2.waitKey(3)
    
    def depth_img_cb(self, data):
        """深度图像回调（本实验不处理，可留空或简单记录）"""
        pass

if __name__ == '__main__':
    try:
        OmoveFollowing()
    except rospy.ROSInterruptException:
        pass
    finally:
        cv2.destroyAllWindows()
