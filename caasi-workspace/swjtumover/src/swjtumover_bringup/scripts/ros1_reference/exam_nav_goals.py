#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能自主系统考核项目：阶段2——AMCL 初始化与自动导航

功能：
1. 启动时向 /initialpose 发布赛道起点位姿，帮助 AMCL 与静态地图对齐；
2. 确认 move_base action server 可用后，通知循线节点系统已准备；
3. 等待 /exam/line_finished=True；
4. 依次向 move_base 发送 exam_goals.yaml 中的目标点。
"""

import math
import rospy
import actionlib

from actionlib_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseWithCovarianceStamped
from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
from std_msgs.msg import Bool
from std_srvs.srv import Empty


def yaw_to_quaternion(yaw):
    qz = math.sin(yaw / 2.0)
    qw = math.cos(yaw / 2.0)
    return 0.0, 0.0, qz, qw


class ExamNavGoals(object):
    def __init__(self):
        rospy.init_node("exam_nav_goals", anonymous=False)

        self.finish_topic = rospy.get_param("~finish_topic", "/exam/line_finished")
        self.wait_line_finished = bool(
            rospy.get_param("~wait_line_finished", True)
        )
        self.goal_timeout = float(rospy.get_param("~goal_timeout", 90.0))
        self.frame_id = rospy.get_param("~frame_id", "map")

        # 注意：launch 把 YAML 加载在节点私有命名空间中，所以必须使用 ~goals。
        self.goals = rospy.get_param("~goals", [])

        self.publish_initial_pose_enabled = bool(
            rospy.get_param("~publish_initial_pose", True)
        )
        self.initial_pose_x = float(rospy.get_param("~initial_pose_x", 0.0))
        self.initial_pose_y = float(rospy.get_param("~initial_pose_y", 0.0))
        self.initial_pose_yaw = float(rospy.get_param("~initial_pose_yaw", 0.0))
        self.initial_pose_topic = rospy.get_param("~initial_pose_topic", "/initialpose")
        self.initial_pose_repeat = int(rospy.get_param("~initial_pose_repeat", 5))
        self.initial_pose_settle_time = float(
            rospy.get_param("~initial_pose_settle_time", 3.0)
        )
        self.amcl_pose_topic = rospy.get_param("~amcl_pose_topic", "/amcl_pose")

        self.clear_costmaps_before_goals = bool(
            rospy.get_param("~clear_costmaps_before_goals", True)
        )
        self.localization_ready_param = rospy.get_param(
            "~localization_ready_param", "/exam/localization_ready"
        )

        if not isinstance(self.goals, list) or len(self.goals) == 0:
            rospy.logerr(
                "未配置导航目标点。应把 exam_goals.yaml 加载到 "
                "/exam_nav_goals/goals，并在代码中用 ~goals 读取。"
            )
            rospy.signal_shutdown("goals not configured")
            return

        rospy.set_param(self.localization_ready_param, False)

        self.line_finished = False
        self.finish_sub = rospy.Subscriber(
            self.finish_topic, Bool, self.finish_cb, queue_size=1
        )
        self.initial_pose_pub = rospy.Publisher(
            self.initial_pose_topic,
            PoseWithCovarianceStamped,
            queue_size=1,
            latch=True,
        )
        self.client = actionlib.SimpleActionClient("move_base", MoveBaseAction)
        rospy.on_shutdown(self.shutdown)

        if self.publish_initial_pose_enabled:
            if not self.publish_initial_pose():
                rospy.logerr("AMCL 初始位姿设置失败，终止一键流程")
                rospy.signal_shutdown("initial pose failed")
                return

        rospy.loginfo("等待 move_base action server...")
        if not self.client.wait_for_server(rospy.Duration(60.0)):
            rospy.logerr("60 秒内未连接到 move_base，请检查 move_base.launch")
            rospy.signal_shutdown("move_base unavailable")
            return
        rospy.loginfo("已连接 move_base，已加载 %d 个导航点", len(self.goals))

        # 只有 AMCL 与 move_base 均可用后，才允许循线节点开始运动。
        rospy.set_param(self.localization_ready_param, True)
        rospy.loginfo("已设置 %s=True", self.localization_ready_param)

        if self.wait_line_finished:
            self.wait_for_line_finished()

        if rospy.is_shutdown():
            return

        if self.clear_costmaps_before_goals:
            self.clear_costmaps()

        self.run_goals()

    def publish_initial_pose(self):
        rospy.loginfo(
            "准备设置 AMCL 初始位姿: x=%.3f y=%.3f yaw=%.3f",
            self.initial_pose_x,
            self.initial_pose_y,
            self.initial_pose_yaw,
        )

        # 等待 AMCL 订阅 /initialpose。
        wait_start = rospy.Time.now()
        rate = rospy.Rate(10)
        while not rospy.is_shutdown() and self.initial_pose_pub.get_num_connections() == 0:
            if (rospy.Time.now() - wait_start).to_sec() > 15.0:
                rospy.logerr("/initialpose 15 秒内没有订阅者，请检查 amcl.launch")
                return False
            rate.sleep()

        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = self.frame_id
        msg.pose.pose.position.x = self.initial_pose_x
        msg.pose.pose.position.y = self.initial_pose_y
        msg.pose.pose.position.z = 0.0
        qx, qy, qz, qw = yaw_to_quaternion(self.initial_pose_yaw)
        msg.pose.pose.orientation.x = qx
        msg.pose.pose.orientation.y = qy
        msg.pose.pose.orientation.z = qz
        msg.pose.pose.orientation.w = qw

        # 给 AMCL 一个合理但不至于过大的初始不确定度。
        msg.pose.covariance[0] = 0.25
        msg.pose.covariance[7] = 0.25
        msg.pose.covariance[35] = 0.0685

        publish_rate = rospy.Rate(5)
        for _ in range(max(1, self.initial_pose_repeat)):
            msg.header.stamp = rospy.Time.now()
            self.initial_pose_pub.publish(msg)
            publish_rate.sleep()

        rospy.loginfo("已发布 AMCL 初始位姿，等待 /amcl_pose")
        try:
            rospy.wait_for_message(
                self.amcl_pose_topic,
                PoseWithCovarianceStamped,
                timeout=10.0,
            )
        except rospy.ROSException:
            rospy.logerr("10 秒内未收到 %s，请检查 AMCL 和 TF", self.amcl_pose_topic)
            return False

        if self.initial_pose_settle_time > 0:
            rospy.sleep(self.initial_pose_settle_time)
        rospy.loginfo("AMCL 已返回定位结果")
        return True

    def wait_for_line_finished(self):
        rospy.loginfo("等待循线结束信号 %s=True ...", self.finish_topic)
        rate = rospy.Rate(10)
        while not rospy.is_shutdown() and not self.line_finished:
            self.line_finished = bool(
                rospy.get_param("/exam/line_finished", False)
            )
            rate.sleep()

        if self.line_finished:
            rospy.loginfo("收到循线结束信号，开始自动导航")

    def finish_cb(self, msg):
        self.line_finished = bool(msg.data)

    def clear_costmaps(self):
        service_name = "/move_base/clear_costmaps"
        try:
            rospy.wait_for_service(service_name, timeout=5.0)
            clear_srv = rospy.ServiceProxy(service_name, Empty)
            clear_srv()
            rospy.loginfo("已清除 move_base 局部与全局代价地图")
        except (rospy.ROSException, rospy.ServiceException) as exc:
            rospy.logwarn("清除代价地图失败，继续导航: %s", str(exc))

    def build_goal(self, item):
        goal = MoveBaseGoal()
        goal.target_pose.header.frame_id = item.get("frame_id", self.frame_id)
        goal.target_pose.header.stamp = rospy.Time.now()
        goal.target_pose.pose.position.x = float(item["x"])
        goal.target_pose.pose.position.y = float(item["y"])
        goal.target_pose.pose.position.z = 0.0

        if "yaw" in item:
            qx, qy, qz, qw = yaw_to_quaternion(float(item["yaw"]))
        else:
            qx = float(item.get("qx", 0.0))
            qy = float(item.get("qy", 0.0))
            qz = float(item.get("qz", 0.0))
            qw = float(item.get("qw", 1.0))

        goal.target_pose.pose.orientation.x = qx
        goal.target_pose.pose.orientation.y = qy
        goal.target_pose.pose.orientation.z = qz
        goal.target_pose.pose.orientation.w = qw
        return goal

    def run_goals(self):
        for index, item in enumerate(self.goals):
            if rospy.is_shutdown():
                return

            name = item.get("name", "goal_{}".format(index + 1))
            goal = self.build_goal(item)

            rospy.loginfo(
                "发送导航目标点 %d/%d: %s, x=%.3f, y=%.3f, frame=%s",
                index + 1,
                len(self.goals),
                name,
                goal.target_pose.pose.position.x,
                goal.target_pose.pose.position.y,
                goal.target_pose.header.frame_id,
            )

            self.client.send_goal(goal)
            finished = self.client.wait_for_result(
                rospy.Duration(self.goal_timeout)
            )

            if not finished:
                rospy.logwarn("目标点 %s 超时，取消当前目标并停止后续导航", name)
                self.client.cancel_goal()
                break

            state = self.client.get_state()
            if state == GoalStatus.SUCCEEDED:
                rospy.loginfo("目标点 %s 到达", name)
                wait_time = float(item.get("wait", 0.0))
                if wait_time > 0:
                    rospy.sleep(wait_time)
            else:
                rospy.logwarn(
                    "目标点 %s 未成功，move_base 状态码=%s，停止后续目标",
                    name,
                    str(state),
                )
                break

        rospy.loginfo("导航流程结束")

    def shutdown(self):
        rospy.set_param(self.localization_ready_param, False)
        try:
            self.client.cancel_all_goals()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        ExamNavGoals()
    except rospy.ROSInterruptException:
        pass
