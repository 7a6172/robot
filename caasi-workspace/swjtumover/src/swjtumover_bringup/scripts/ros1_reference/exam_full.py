#!/usr/bin/env python3
import rospy
import subprocess
import time
import os
import sys
from geometry_msgs.msg import Twist, PoseStamped, PoseWithCovarianceStamped

class FullExamController:
    def __init__(self):
        rospy.init_node('exam_full_controller')
        self.vel_pub = rospy.Publisher('/cmd_vel', Twist, queue_size=10)
        self.init_pose_pub = rospy.Publisher('/initialpose', PoseWithCovarianceStamped, queue_size=10)
        self.goal_pub = rospy.Publisher('/move_base_simple/goal', PoseStamped, queue_size=10)

        rospy.loginfo("===== 智能自主系统考核 正式开始 =====")
        rospy.sleep(2)

        # 阶段1：视觉巡线
        stage1_result = self.stage1_line_follow()
        if not stage1_result:
            rospy.logerr("【致命错误】巡线阶段异常，终止流程！")
            return

        # 阶段2：分步导航返回（终点→中转点→起点）
        self.stage2_nav_back()

        rospy.loginfo("===== 全部考核任务完成 =====")

    def navigate_to_point(self, x, y, z, w, point_name="目标点", timeout=90):
        """导航到指定坐标点，到达返回True，超时返回False"""
        goal = PoseStamped()
        goal.header.frame_id = "map"
        goal.header.stamp = rospy.Time.now()
        goal.pose.position.x = x
        goal.pose.position.y = y
        goal.pose.orientation.z = z
        goal.pose.orientation.w = w
        self.goal_pub.publish(goal)
        rospy.loginfo(f"[导航] 已发布{point_name}目标: ({x:.2f}, {y:.2f})")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                current = rospy.wait_for_message('/amcl_pose', PoseWithCovarianceStamped, timeout=1)
                dx = current.pose.pose.position.x - x
                dy = current.pose.pose.position.y - y
                dist = (dx**2 + dy**2) ** 0.5
                if dist < 0.3:  # 距离小于30cm判定到达
                    rospy.loginfo(f"[导航] 已到达{point_name}")
                    rospy.sleep(1)
                    return True
            except:
                pass
            rospy.sleep(0.5)

        rospy.logwarn(f"[导航] {point_name}超时未到达")
        return False

    def stage1_line_follow(self):
        rospy.loginfo("[阶段1] 启动视觉巡线节点")
        follow_script = "/home/swjtumover/swjtumover/swjtumover_ws/src/swjtumover_bringup/scripts/omove_following.py"

        if not os.path.exists(follow_script):
            rospy.logerr(f"文件不存在：{follow_script}")
            return False

        # ========== 修复1：启动前强制重置终点参数，清除历史残留 ==========
        rospy.set_param("/reached_goal", False)
        rospy.loginfo("已重置终点检测参数")

        proc = subprocess.Popen(["python3", follow_script], stdout=sys.stdout, stderr=sys.stderr)
        
        time.sleep(2)
        if proc.poll() is not None:
            rospy.logerr(f"巡线脚本启动2秒就退出了，退出码：{proc.returncode}")
            return False
        
        rospy.loginfo("巡线节点运行正常，等待到达终点...")
        
        timeout = 120
        start_time = time.time()
        # ========== 修复2：前30秒为保护期，屏蔽所有终点信号 ==========
        protect_time = 30

        while time.time() - start_time < timeout:
            # 进程正常退出则结束
            if proc.poll() is not None:
                break

            # 保护期内不检测终点参数
            elapsed = time.time() - start_time
            if elapsed > protect_time:
                if rospy.has_param("/reached_goal") and rospy.get_param("/reached_goal"):
                    rospy.loginfo("检测到终点信号，巡线完成")
                    proc.terminate()
                    time.sleep(1)
                    break
            rospy.sleep(0.5)
        
        if time.time() - start_time >= timeout:
            rospy.logerr("巡线超时，强制终止")
            proc.terminate()
            return False

        rospy.loginfo("[阶段1] 巡线完成，已到达跑道尽头")
        
        stop_msg = Twist()
        for _ in range(20):
            self.vel_pub.publish(stop_msg)
            rospy.sleep(0.1)
        rospy.sleep(2)
        return True

    def stage2_nav_back(self):
        rospy.loginfo("[阶段2] 启动自主导航系统")
        map_path = "/home/swjtumover/swjtumover/swjtumover_ws/src/swjtumover_bringup/maps/track_map.yaml"
        
        # 启动地图与AMCL定位
        subprocess.Popen(['roslaunch', 'swjtumover_bringup', 'map_server.launch', f'map_file:={map_path}'])
        rospy.sleep(3)
        subprocess.Popen(['roslaunch', 'swjtumover_bringup', 'amcl.launch'])
        rospy.sleep(3)

        # 终点初始位姿（你的实测坐标）
        init_pose = PoseWithCovarianceStamped()
        init_pose.header.frame_id = "map"
        init_pose.header.stamp = rospy.Time.now()
        init_pose.pose.pose.position.x = -2.1510479068483774
        init_pose.pose.pose.position.y = -0.8844062976264153
        init_pose.pose.pose.orientation.z = 0.3799262465625216
        init_pose.pose.pose.orientation.w = 0.9250167821033919
        for _ in range(3):
            self.init_pose_pub.publish(init_pose)
            rospy.sleep(0.5)
        rospy.sleep(2)

        # 启动move_base导航
        subprocess.Popen(['roslaunch', 'swjtumover_bringup', 'move_base.launch'])
        rospy.sleep(5)

        # 中转点坐标（你的实测值）
        mid_x = 0.4180457592010498
        mid_y = -0.23368358612060547
        mid_z = -0.08144476073724118
        mid_w = 0.9966778571576944

        # 第一步：导航到中转点
        self.navigate_to_point(mid_x, mid_y, mid_z, mid_w, point_name="中转点")

        # 第二步：从中转点导航回起点
        start_x = 2.37558172940533
        start_y = -1.6277725120721014
        start_z = -0.9283964063848115
        start_w = 0.3715913247261943
        self.navigate_to_point(start_x, start_y, start_z, start_w, point_name="起点")

        rospy.loginfo("[阶段2] 导航返回完成")

if __name__ == '__main__':
    try:
        FullExamController()
        rospy.spin()
    except rospy.ROSInterruptException:
        rospy.logerr("考核流程被手动中断")
