#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 文件描述：apps/mapping.launch 的 ROS 2 Jazzy 移植（Stage 8）
# 启动机器人建图模式

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

share_dir = get_package_share_directory('openmover')
config_dir = os.path.join(share_dir, 'config_defaults')

hardwares_yaml = os.path.join(config_dir, 'hardwares.yaml')
modules_yaml = os.path.join(config_dir, 'modules.yaml')
mapping_yaml = os.path.join(config_dir, 'apps', 'mapping', 'mapping.yaml')

# ROS 2 中代价地图/规划器为进程内独立节点，话题不带父节点名前缀，
# 因此重映射源端去除 ROS 1 的 "<node_name>/" 前缀。
COSTMAP_REMAPS = [
    ('global_costmap/costmap', 'costmap/costmap'),
    ('global_costmap/costmap_updates', 'costmap/costmap_updates'),
    ('global_costmap/footprint', 'costmap/footprint'),
    ('global_planner/plan', 'planner/plan'),
    ('global_planner/potential', 'planner/potential'),
    ('global_planner/polyline_plan', 'planner/polyline_plan'),
]


def generate_launch_description():
    use_sim_time = LaunchConfiguration('use_sim_time')

    # 建图
    carto_mapping = IncludeLaunchDescription(
        os.path.join(share_dir, 'launch', 'modules', 'mapping',
                     'carto_mapping.launch.py'),
        launch_arguments={'use_sim_time': use_sim_time}.items())

    # 最新算法
    auto_mapping_handler = Node(
        package='auto_mapping_toolbox', executable='auto_mapping_handler',
        name='auto_mapping_handler', output='screen',
        parameters=[hardwares_yaml, modules_yaml, mapping_yaml,
                    {'use_sim_time': use_sim_time}],
        remappings=[
            ('path_with_orientation', 'openmover/navigation/path_with_orientation'),
            ('occupancy_grid', 'openmover/mapping/map'),
            ('map', 'openmover/mapping/map'),
            ('scan', 'openmover/hardware/lidar/scan'),
            ('twist', 'openmover/localization/twist'),
            ('auto_mapping/request', 'openmover/mapping/auto_mapping/request'),
            ('auto_mapping/state', 'openmover/mapping/auto_mapping/state'),
            ('cmd_vel_mode/request', 'openmover/control/cmd_vel_mode/request'),
            ('navigation/request', 'openmover/navigation/request'),
            ('navigation/state', 'openmover/navigation/state'),
        ] + [(src, 'openmover/mapping/global_planner/' + dst)
             for src, dst in COSTMAP_REMAPS])

    navigation_handler = Node(
        package='openmover', executable='navigation_handler',
        name='navigation_handler', output='screen',
        parameters=[hardwares_yaml, modules_yaml, mapping_yaml,
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
        ] + [(src, 'openmover/navigation/global_planner/' + dst)
             for src, dst in COSTMAP_REMAPS[:5]])

    # 启动系统重置
    reset_server_handler = Node(
        package='openmover', executable='reset_server_handler.py',
        name='reset_server_handler', output='screen',
        parameters=[hardwares_yaml, modules_yaml, mapping_yaml,
                    {'use_sim_time': use_sim_time}])

    # 启动置信度计算
    localization_confidence_handler = Node(
        package='openmover', executable='localization_confidence_handler',
        name='localization_confidence_handler', output='screen',
        parameters=[hardwares_yaml, modules_yaml, mapping_yaml,
                    {'use_sim_time': use_sim_time}])

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        carto_mapping,
        auto_mapping_handler,
        navigation_handler,
        reset_server_handler,
        localization_confidence_handler,
    ])
