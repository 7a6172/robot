#!/usr/bin/env python
# -*- coding: utf-8 -*-

import rospy
from geometry_msgs.msg import PoseStamped

def send_goal():
    # 初始化节点
    rospy.init_node('send_goal_demo', anonymous=True)

    # 创建一个发布者，发布到 /move_base_simple/goal
    goal_pub = rospy.Publisher('/move_base_simple/goal', PoseStamped, queue_size=10)

    # 等待话题有订阅者（move_base 节点在运行）
    rospy.loginfo("等待 move_base 启动...")
    rospy.sleep(2)  # 先等一下确保连接

    # 构造目标点
    goal = PoseStamped()
    goal.header.stamp = rospy.Time.now()
    goal.header.frame_id = "map"   # 一定要用地图坐标系

    # ------ 在这里修改你的目标坐标和姿态 ------
    goal.pose.position.x = 2.0   # 目标 x 坐标 (米)
    goal.pose.position.y = 1.0   # 目标 y 坐标 (米)
    goal.pose.position.z = 0.0

    # 朝向用四元数，这里表示朝向正东（0弧度，即沿x轴正方向）
    goal.pose.orientation.x = 0.0
    goal.pose.orientation.y = 0.0
    goal.pose.orientation.z = 0.0
    goal.pose.orientation.w = 1.0   # w=1 表示无旋转，即朝向x轴
    # 如果想要朝向某个角度，例如朝北（90度），可以用：
    # from tf.transformations import quaternion_from_euler
    # quat = quaternion_from_euler(0, 0, 1.57)  # 偏航角1.57弧度
    # goal.pose.orientation.x = quat[0]
    # goal.pose.orientation.y = quat[1]
    # goal.pose.orientation.z = quat[2]
    # goal.pose.orientation.w = quat[3]

    rospy.loginfo("正在发布导航目标：x=%.2f, y=%.2f", goal.pose.position.x, goal.pose.position.y)
    goal_pub.publish(goal)
    rospy.loginfo("目标已发布！")

if __name__ == '__main__':
    try:
        send_goal()
    except rospy.ROSInterruptException:
        pass
