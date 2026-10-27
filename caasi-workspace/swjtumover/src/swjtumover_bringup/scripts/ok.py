#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rospy
import actionlib
import os
import signal
import math
from geometry_msgs.msg import PoseWithCovarianceStamped
from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
from tf.transformations import euler_from_quaternion, quaternion_from_euler


class MultiStageNavigator:
    def __init__(self):
        rospy.init_node("multi_stage_navigator", anonymous=True)

        # ====== 目标点设置 ======
        # 位置 A（仅用坐标，不考虑姿态）
        self.pose_A = (-1.7999369813874384, -2.501408613583877)  # x, y

        # 位置 B、C（含位姿 yaw[弧度]）
        # self.pose_B = (-2.4593043795563525, -1.6577922552925575,0.4824747168913896)
        # self.pose_C = (-1.7226505036226258, 1.881646649501627, 0.9520782356711052)

        self.pose_B = {
            "x": -2.4593043795563525,
            "y": -1.6577922552925575,
            "z":0.0,
            "qx": 0.0,
            "qy": 0.0,
            "qz": 0.8759098969417879,
            "qw": 0.4824747168913896
        }

        self.pose_C = {
            "x": -1.7526505036226258,
            "y": 1.891646649501627,
            "z":0.0,
            "qx": 0.0,
            "qy": 0.0,
            "qz": -0.3058545948018366,
            "qw": 0.9520782356711052
        }

        self.reached_A = False
        self.current_pose = None

        # move_base 动作客户端
        self.client = actionlib.SimpleActionClient("move_base", MoveBaseAction)
        rospy.loginfo("等待 move_base 服务器启动...")
        self.client.wait_for_server()
        rospy.loginfo("move_base 已连接成功")

        # 订阅定位信息
        rospy.Subscriber("/amcl_pose", PoseWithCovarianceStamped, self.pose_callback)

    def pose_callback(self, msg):
        """监听当前位置"""
        pos = msg.pose.pose.position
        ori = msg.pose.pose.orientation
        (_, _, yaw) = euler_from_quaternion([ori.x, ori.y, ori.z, ori.w])
        self.current_pose = (pos.x, pos.y, yaw)

        # 检查是否到达 A（仅位置）
        if not self.reached_A and self.is_reached_A():
            rospy.loginfo("已到达位置 A！准备结束 1.py ...")
            self.stop_process("omove_following000.py")
            self.reached_A = True

            # 接着导航到 B → C
            self.goto_with_pose(**self.pose_B)
            self.goto_with_pose(**self.pose_C)
            rospy.loginfo("已完成所有目标导航任务！")

    
    
    def is_reached_A(self, pos_tol=0.5):
        """判断是否到达位置 A（仅位置，不考虑朝向）"""
        if self.current_pose is None:
            return False
        x, y, _ = self.current_pose
        ax, ay = self.pose_A
        dist = math.hypot(ax - x, ay - y)
        return dist < pos_tol

    def stop_process(self, process_name):
        """结束指定进程"""
        try:
            pids = os.popen(f"pgrep -f {process_name}").read().strip().split('\n')
            for pid in pids:
                if pid:
                    os.kill(int(pid), signal.SIGTERM)
                    rospy.loginfo(f"已结束进程 {process_name} (PID={pid})")
        except Exception as e:
            rospy.logwarn(f"结束进程失败: {e}")

    def goto_with_pose(self, x, y, z, qx, qy, qz, qw):
        goal = MoveBaseGoal()
        goal.target_pose.header.frame_id = "map"
        goal.target_pose.header.stamp = rospy.Time.now()
        goal.target_pose.pose.position.x = float(x)
        goal.target_pose.pose.position.y = float(y)
        goal.target_pose.pose.position.z = float(z)
        goal.target_pose.pose.orientation.x = float(qx)
        goal.target_pose.pose.orientation.y = float(qy)
        goal.target_pose.pose.orientation.z = float(qz)
        goal.target_pose.pose.orientation.w = float(qw)
        self.client.send_goal(goal)
        self.client.wait_for_result()
        result = self.client.get_state()
        return result

    def run(self):
        rospy.loginfo("正在监听小车位置...")
        rospy.spin()


if __name__ == "__main__":
    try:
        node = MultiStageNavigator()
        node.run()
    except rospy.ROSInterruptException:
        pass
