#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 文件描述：modules/localization/carto_localization_server.launch 的 ROS 2 Jazzy 移植（Stage 8）
# 启动 Cartographer 定位服务器（负责按地图名加载 pbstream 并管理 carto_localization）

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

share_dir = get_package_share_directory('openmover')

launch_file_cartographer = os.path.join(
    share_dir, 'launch', 'modules', 'localization', 'carto_localization.launch.py')


def generate_launch_description():
    use_sim_time = LaunchConfiguration('use_sim_time')

    def build_nodes(context):
        ust = use_sim_time.perform(context) == 'true'

        # 启动 Server
        return [Node(
            package='openmover', executable='cartographer_server_handler.py',
            name='cartographer_localization_server_handler', output='screen',
            parameters=[{
                'localization_mode': True,
                'launch_file_cartographer': launch_file_cartographer,
                'use_sim_time': ust,
            }])]

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        OpaqueFunction(function=build_nodes),
    ])
