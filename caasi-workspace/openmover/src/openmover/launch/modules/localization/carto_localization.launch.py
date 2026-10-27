#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 文件描述：modules/localization/carto_localization.launch 的 ROS 2 Jazzy 移植（Stage 8）
# 启动机器人 Cartographer 定位系统
# ROS 2 差异：cartographer_node 不再订阅 initialpose 话题，
#             由 cartographer_initialpose_adapter 转发为轨迹服务调用。

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

share_dir = get_package_share_directory('openmover')


def generate_launch_description():
    config_filepath = LaunchConfiguration('config_filepath')
    config_basename = LaunchConfiguration('config_basename')
    pbstream_filename = LaunchConfiguration('pbstream_filename')
    use_sim_time = LaunchConfiguration('use_sim_time')

    cartographer_node = Node(
        package='cartographer_ros', executable='cartographer_node',
        name='cartographer_node', output='screen',
        parameters=[{'use_sim_time': use_sim_time}],
        arguments=[
            '-configuration_directory', config_filepath,
            '-configuration_basename', config_basename,
            '-load_state_filename', pbstream_filename,
        ],
        remappings=[
            ('scan', LaunchConfiguration('scan_topic')),
            # odom 必须接 nav_msgs/Odometry 类型的 odom_legacy：
            # localization/odom 是 PoseWithCovarianceStamped，类型不匹配
            ('odom', 'openmover/localization/odom_legacy'),
            ('tracked_pose', 'openmover/localization/pose_aft_mapped'),
            ('write_state', 'openmover/mapping/write_state/request'),
        ])

    cartographer_occupancy_grid_node = Node(
        package='cartographer_ros', executable='cartographer_occupancy_grid_node',
        name='cartographer_occupancy_grid_node', output='screen',
        parameters=[{'localization_mode': True,
                     'resolution': 0.05,
                     'use_sim_time': use_sim_time}],
        remappings=[
            ('map', 'openmover/mapping/map'),
            ('map_metadata', 'openmover/mapping/map_metadata'),
        ])

    # ROS 2 重定位初始位姿适配器（initialpose 话题 -> 轨迹服务）
    initialpose_adapter = Node(
        package='openmover', executable='cartographer_initialpose_adapter.py',
        name='cartographer_initialpose_adapter', output='screen',
        parameters=[{'config_filepath': config_filepath,
                     'config_basename': config_basename,
                     'use_sim_time': use_sim_time}])

    return LaunchDescription([
        DeclareLaunchArgument(
            'config_filepath',
            default_value=os.path.join(share_dir, 'config_defaults',
                                       'apps', 'navigation')),
        DeclareLaunchArgument('config_basename', default_value='navigation.lua'),
        DeclareLaunchArgument(
            'pbstream_filename',
            default_value=os.path.join(share_dir, 'maps_defaults',
                                       'simulation', 'navigation.pbstream')),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        # The scan interface is chosen by the hardware profile: the lab fit merges two
        # bluesea2 scans into the shared topic, while a single 360 degree scanner
        # publishes /scan directly. Default keeps the historical behaviour.
        DeclareLaunchArgument('scan_topic',
                              default_value='openmover/hardware/lidar/scan'),
        cartographer_node,
        cartographer_occupancy_grid_node,
        initialpose_adapter,
    ])
