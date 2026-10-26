#!/usr/bin/env python
# -*- coding: utf-8 -*-

import rospy
from geometry_msgs.msg import PoseStamped

def send_nav_goal():
    # 初始化节点
    rospy.init_node('send_nav_goal_py', anonymous=True)

    # 创建发布者，发布到 move_base 的简易导航话题
    goal_pub = rospy.Publisher('/move_base_simple/goal', PoseStamped, queue_size=10)

    # 等待 move_base 启动并建立连接
    rospy.loginfo("等待 move_base 节点启动...")
    rospy.sleep(2)   # 确保订阅者已经连接

    # 构造目标点消息
    goal = PoseStamped()
    goal.header.stamp = rospy.Time.now()
    goal.header.frame_id = "map"   # 必须使用地图坐标系

    # 设置目标位置（根据你 Publish Point 得到的坐标）
    goal.pose.position.x = -0.0666
    goal.pose.position.y = 3.27
    goal.pose.position.z = 0.0      # 平面导航，Z设为0

    # 设置目标朝向，默认不旋转（朝向地图X轴正方向）
    goal.pose.orientation.x = 0.0
    goal.pose.orientation.y = 0.0
    goal.pose.orientation.z = 0.0
    goal.pose.orientation.w = 1.0

    # 发布目标
    rospy.loginfo("正在发送导航目标：x=%.4f, y=%.4f", 
                  goal.pose.position.x, goal.pose.position.y)
    goal_pub.publish(goal)
    rospy.loginfo("目标已发布，机器人开始规划路径。")

if __name__ == '__main__':
    try:
        send_nav_goal()
    except rospy.ROSInterruptException:
        pass
