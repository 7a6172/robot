#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 文件描述：modules/mapping/carto_mapping.launch 的 ROS 2 Jazzy 移植（Stage 8）
# 启动机器人 Cartographer 建图系统

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node

share_dir = get_package_share_directory('openmover')

# 建图模式下服务器管理的启动文件即本文件自身（与 ROS 1 保持一致）
launch_file_cartographer = os.path.join(
    share_dir, 'launch', 'modules', 'mapping', 'carto_mapping.launch.py')


def generate_launch_description():
    use_sim_time = LaunchConfiguration('use_sim_time')

    cartographer_node = Node(
        package='cartographer_ros', executable='cartographer_node',
        name='cartographer_node', output='screen',
        parameters=[{'use_sim_time': use_sim_time}],
        arguments=[
            '-configuration_directory', os.path.join(
                share_dir, 'config_defaults', 'apps', 'mapping'),
            '-configuration_basename', 'mapping.lua',
        ],
        remappings=[
            ('scan', 'openmover/hardware/lidar/scan'),
            # odom 必须接 nav_msgs/Odometry 类型的 odom_legacy：
            # localization/odom 是 PoseWithCovarianceStamped，类型不匹配
            ('odom', 'openmover/localization/odom_legacy'),
            ('write_state', 'openmover/mapping/write_state/request'),
        ])

    cartographer_occupancy_grid_node = Node(
        package='cartographer_ros', executable='cartographer_occupancy_grid_node',
        name='cartographer_occupancy_grid_node', output='screen',
        parameters=[{'localization_mode': False,
                     'resolution': 0.05,
                     'use_sim_time': use_sim_time}],
        remappings=[
            ('map', 'openmover/mapping/map'),
            ('map_metadata', 'openmover/mapping/map_metadata'),
        ])

    def build_server(context):
        ust = use_sim_time.perform(context) == 'true'

        # 启动 Cartographer Server
        return [Node(
            package='openmover', executable='cartographer_server_handler.py',
            name='cartographer_mapping_server_handler', output='screen',
            parameters=[{
                'localization_mode': False,
                'launch_file_cartographer': launch_file_cartographer,
                'nav_map_save_path':
                    EnvironmentVariable(name='HOME').perform(context) +
                    '/openmover_robot/maps/',
                'use_sim_time': ust,
            }])]

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        cartographer_node,
        cartographer_occupancy_grid_node,
        OpaqueFunction(function=build_server),
    ])
