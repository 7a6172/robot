#!/usr/bin/env python3
# 说明：cartographer 重定位初始位姿适配器。
#       ROS 1 的 cartographer_node 直接订阅 initialpose 话题实现重定位；
#       ROS 2 版本（ros2/cartographer_ros）移除了该话题，改为通过
#       finish_trajectory + start_trajectory(use_initial_pose) 服务实现。
#       本节点订阅 localization_handler 发布的 initialpose 话题，
#       并转发为 cartographer 的轨迹服务调用，保持系统流程一致。
import sys

import rclpy
from rclpy.node import Node

from cartographer_ros_msgs.srv import FinishTrajectory, GetTrajectoryStates, StartTrajectory
from cartographer_ros_msgs.msg import TrajectoryStates
from geometry_msgs.msg import PoseWithCovarianceStamped


class InitialPoseAdapter(Node):

    def __init__(self):
        super().__init__('cartographer_initialpose_adapter')

        self.declare_parameter('config_filepath', '')
        self.declare_parameter('config_basename', 'navigation.lua')
        self.declare_parameter('initialpose_topic', 'openmover/localization/initialpose')

        self.config_filepath = self.get_parameter('config_filepath').get_parameter_value().string_value
        self.config_basename = self.get_parameter('config_basename').get_parameter_value().string_value
        initialpose_topic = self.get_parameter('initialpose_topic').get_parameter_value().string_value

        self.sub = self.create_subscription(
            PoseWithCovarianceStamped, initialpose_topic, self.handle_initial_pose, 10)

        self.get_states_client = self.create_client(GetTrajectoryStates, 'get_trajectory_states')
        self.finish_client = self.create_client(FinishTrajectory, 'finish_trajectory')
        self.start_client = self.create_client(StartTrajectory, 'start_trajectory')

        self.get_logger().info(
            '初始化重定位初始位姿适配器，订阅话题 %s' % initialpose_topic)

    def handle_initial_pose(self, msg):
        try:
            self.process_initial_pose(msg)
        except Exception as e:
            self.get_logger().error('处理初始位姿失败：%s' % str(e))

    def process_initial_pose(self, msg):
        # 查询当前轨迹状态
        if not self.get_states_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error('get_trajectory_states 服务不可用')
            return
        states_resp = self.get_states_client.call(GetTrajectoryStates.Request())

        active_ids = []
        frozen_id = None
        finished_id = None
        for traj_id, state in zip(states_resp.trajectory_states.trajectory_id,
                                  states_resp.trajectory_states.trajectory_state):
            if state == TrajectoryStates.ACTIVE:
                active_ids.append(traj_id)
            elif state == TrajectoryStates.FROZEN:
                frozen_id = traj_id
            elif state == TrajectoryStates.FINISHED:
                finished_id = traj_id

        # 结束当前活动轨迹（ROS 1 的 initialpose 处理也会结束当前轨迹）
        if active_ids:
            if not self.finish_client.wait_for_service(timeout_sec=5.0):
                self.get_logger().error('finish_trajectory 服务不可用')
                return
            for traj_id in active_ids:
                req = FinishTrajectory.Request()
                req.trajectory_id = traj_id
                resp = self.finish_client.call(req)
                self.get_logger().info('结束轨迹 %d: %s' % (traj_id, resp.status.message))

        # 初始位姿相对参考轨迹：优先使用载入的冻结地图轨迹
        reference_id = frozen_id if frozen_id is not None else finished_id
        if reference_id is None:
            self.get_logger().error('无可用参考轨迹，无法重定位')
            return

        if not self.start_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error('start_trajectory 服务不可用')
            return
        req = StartTrajectory.Request()
        req.configuration_directory = self.config_filepath
        req.configuration_basename = self.config_basename
        req.use_initial_pose = True
        req.initial_pose = msg.pose.pose
        req.relative_to_trajectory_id = reference_id
        resp = self.start_client.call(req)
        if resp.status.code == 0:
            self.get_logger().info(
                '重定位成功：新轨迹 %d（参考轨迹 %d）' % (resp.trajectory_id, reference_id))
        else:
            self.get_logger().error('重定位失败：%s' % resp.status.message)


def main(args=None):
    rclpy.init(args=args)
    node = InitialPoseAdapter()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
    sys.exit(0)


if __name__ == '__main__':
    main()
