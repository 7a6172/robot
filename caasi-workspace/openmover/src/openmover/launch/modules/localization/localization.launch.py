#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 文件描述：modules/localization/localization.launch 的 ROS 2 Jazzy 移植（Stage 8）
# 启动机器人定位模式选择器 + 定位管理系统

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

share_dir = get_package_share_directory('openmover')

# 定位模块
launch_file_map = os.path.join(
    share_dir, 'launch', 'modules', 'localization',
    'carto_localization_server.launch.py')


def generate_launch_description():
    init_diff_x = LaunchConfiguration('init_diff_x')
    init_diff_y = LaunchConfiguration('init_diff_y')
    init_diff_z = LaunchConfiguration('init_diff_z')
    init_diff_yaw = LaunchConfiguration('init_diff_yaw')
    system_mode = LaunchConfiguration('system_mode')
    use_sim_time = LaunchConfiguration('use_sim_time')
    scan_topic = LaunchConfiguration('scan_topic')

    def build_nodes(context):
        ust = use_sim_time.perform(context) == 'true'

        # 启动 server
        server = Node(
            package='openmover', executable='localization_mode_server_handler.py',
            name='localization_mode_server_handler', output='screen',
            parameters=[{
                'launch_file_map': launch_file_map,
                'system_mode': int(system_mode.perform(context)),
                'use_sim_time': ust,
                # Forwarded to whichever localization launch file this server starts, so
                # the processor subscribes the scan the hardware profile actually provides.
                'scan_topic': scan_topic.perform(context),
            }])

        # 启动机器人定位管理系统
        handler = Node(
            package='openmover', executable='localization_handler',
            name='localization_handler', output='screen',
            parameters=[{
                'init_diff_x': float(init_diff_x.perform(context)),
                'init_diff_y': float(init_diff_y.perform(context)),
                'init_diff_z': float(init_diff_z.perform(context)),
                'init_diff_yaw': float(init_diff_yaw.perform(context)),
                'use_sim_time': ust,
            }])

        return [server, handler]

    return LaunchDescription([
        DeclareLaunchArgument('init_diff_x', default_value='0'),
        DeclareLaunchArgument('init_diff_y', default_value='0'),
        DeclareLaunchArgument('init_diff_z', default_value='0'),
        DeclareLaunchArgument('init_diff_yaw', default_value='0'),
        DeclareLaunchArgument('system_mode', default_value='0'),
        # ROS 1 中 localization_mode_server_handler 会传递 area_name，此处保留声明以兼容
        DeclareLaunchArgument('area_name', default_value='simulation'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument(
            'scan_topic', default_value='openmover/hardware/lidar/scan',
            description='Scan interface passed to the localization processor. The lab '
                        'fit merges two scanners into the shared topic; a single 360 '
                        'degree scanner publishes /scan directly.'),
        OpaqueFunction(function=build_nodes),
    ])
