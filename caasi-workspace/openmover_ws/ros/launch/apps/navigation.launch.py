#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 文件描述：apps/navigation.launch 的 ROS 2 Jazzy 移植（Stage 8）
# 启动机器人路点导航模式

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

share_dir = get_package_share_directory('openmover')

launch_file_navigation = os.path.join(
    share_dir, 'launch', 'apps', 'navigation', 'navigation.launch.py')


def generate_launch_description():
    use_sim_time = LaunchConfiguration('use_sim_time')

    def build_nodes(context):
        ust = use_sim_time.perform(context) == 'true'

        # 启动服务器
        return [Node(
            package='openmover', executable='nav_area_server_handler.py',
            name='nav_area_server_handler', output='screen',
            parameters=[{
                'launch_file_default': launch_file_navigation,
                'launch_file_navigation': launch_file_navigation,
                'use_sim_time': ust,
            }])]

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        OpaqueFunction(function=build_nodes),
    ])
