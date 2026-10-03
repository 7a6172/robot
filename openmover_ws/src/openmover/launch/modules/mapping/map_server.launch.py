#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 文件描述：modules/mapping/map_server.launch 的 ROS 2 Jazzy 移植（Stage 8）
# 机器人导航地图加载（ROS 1 map_server -> nav2_map_server）

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

share_dir = get_package_share_directory('openmover')


def generate_launch_description():
    map_filename = LaunchConfiguration('map_filename')
    use_sim_time = LaunchConfiguration('use_sim_time')

    # 地图加载（nav2_map_server 是生命周期节点，需 configure+activate 才发布地图；
    # ROS 1 map_server 启动即发布，故此处用 lifecycle_manager autostart 对齐行为）
    map_server = Node(
        package='nav2_map_server', executable='map_server', name='map_server',
        output='screen',
        parameters=[{'yaml_filename': map_filename,
                     'frame_id': 'map',
                     'use_sim_time': use_sim_time}],
        remappings=[
            ('map', 'openmover/mapping/map'),
            ('map_metadata', 'openmover/mapping/map_metadata'),
        ])

    lifecycle_manager = Node(
        package='nav2_lifecycle_manager', executable='lifecycle_manager',
        name='lifecycle_manager_mapping', output='screen',
        parameters=[{'use_sim_time': use_sim_time},
                    {'node_names': ['map_server']},
                    {'autostart': True},
                    {'bond_timeout_ms': 4000}])

    return LaunchDescription([
        DeclareLaunchArgument(
            'map_filename',
            default_value=os.path.join(share_dir, 'maps_defaults',
                                       'simulation', 'navigation.yaml')),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        map_server,
        lifecycle_manager,
    ])
