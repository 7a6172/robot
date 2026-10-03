#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 文件描述：apps/navigation/navigation.launch 的 ROS 2 Jazzy 移植（Stage 8）
# 启动机器人导航模式

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

share_dir = get_package_share_directory('openmover')
config_dir = os.path.join(share_dir, 'config_defaults')

hardwares_yaml = os.path.join(config_dir, 'hardwares.yaml')
modules_yaml = os.path.join(config_dir, 'modules.yaml')
navigation_yaml = os.path.join(config_dir, 'apps', 'navigation', 'navigation.yaml')

# ROS 2 中代价地图/规划器为进程内独立节点，话题不带父节点名前缀，
# 因此重映射源端去除 ROS 1 的 "navigation_handler/" 前缀。
COSTMAP_REMAPS = [
    ('global_costmap/costmap',
     'openmover/navigation/global_planner/costmap/costmap'),
    ('global_costmap/costmap_updates',
     'openmover/navigation/global_planner/costmap/costmap_updates'),
    ('global_costmap/footprint',
     'openmover/navigation/global_planner/costmap/footprint'),
    ('global_planner/plan',
     'openmover/navigation/global_planner/planner/plan'),
    ('global_planner/potential',
     'openmover/navigation/global_planner/planner/potential'),
]


def generate_launch_description():
    use_sim_time = LaunchConfiguration('use_sim_time')

    # 启动控制器
    navigation_handler = Node(
        package='openmover', executable='navigation_handler',
        name='navigation_handler', output='screen',
        parameters=[hardwares_yaml, modules_yaml, navigation_yaml,
                    {'use_sim_time': use_sim_time}],
        remappings=[
            ('current_point_in_path', 'openmover/navigation/current_point_in_path'),
            ('point_to_track', 'openmover/navigation/point_to_track'),
            ('best_trajectory', 'openmover/navigation/best_trajectory'),
            ('all_trajectory', 'openmover/navigation/all_trajectory'),
            ('footprint_transformed', 'openmover/navigation/footprint_transformed'),
            ('obstacle_lines', 'openmover/navigation/obstacle_lines'),
            ('visual_marker_array', 'openmover/navigation/visual_marker_array'),
            ('path_with_orientation', 'openmover/navigation/path_with_orientation'),
            ('occupancy_grid', 'openmover/mapping/map'),
            ('map', 'openmover/mapping/map'),
            ('scan', 'openmover/hardware/lidar/scan'),
            ('twist', 'openmover/localization/twist'),
        ] + COSTMAP_REMAPS)

    # 启动系统重置
    reset_server_handler = Node(
        package='openmover', executable='reset_server_handler.py',
        name='reset_server_handler', output='screen',
        parameters=[hardwares_yaml, modules_yaml, navigation_yaml,
                    {'use_sim_time': use_sim_time}])

    # 启动置信度计算
    localization_confidence_handler = Node(
        package='openmover', executable='localization_confidence_handler',
        name='localization_confidence_handler', output='screen',
        parameters=[hardwares_yaml, modules_yaml, navigation_yaml,
                    {'use_sim_time': use_sim_time}])

    # 启动重定位
    relocalization_2d_handler = Node(
        package='relocalization_toolbox', executable='relocalization_2d_handler',
        name='relocalization_2d_handler', output='screen',
        parameters=[hardwares_yaml, modules_yaml, navigation_yaml,
                    {'use_sim_time': use_sim_time}],
        remappings=[
            ('relocalization_request',
             'openmover/localization/relocalization/request'),
            ('relocalization_simple_request',
             'openmover/localization/relocalization/simple_request'),
            ('set_init_pose_request', 'openmover/localization/initialpose/request'),
            ('initialpose', 'openmover/localization/initialpose'),
            ('scan', 'openmover/hardware/lidar/scan'),
            ('map', 'openmover/mapping/map'),
        ])

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        navigation_handler,
        reset_server_handler,
        localization_confidence_handler,
        relocalization_2d_handler,
    ])
