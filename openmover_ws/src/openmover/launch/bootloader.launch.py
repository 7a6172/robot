#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 文件描述：bootloader.launch 的 ROS 2 Jazzy 移植（Stage 8）
# 加载机器人服务：功能模式服务器、rosbridge、可视化（rviz2）、机器人驱动（bringup）

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

share_dir = get_package_share_directory('openmover')
launch_dir = os.path.join(share_dir, 'launch')
rviz_dir = os.path.join(share_dir, 'config_defaults', 'rviz')


def generate_launch_description():
    system_mode = LaunchConfiguration('system_mode')
    sim_area = LaunchConfiguration('sim_area')
    enable_visualization = LaunchConfiguration('enable_visualization')
    launch_gazebo = LaunchConfiguration('launch_gazebo')

    def build_nodes(context):
        # 系统模式，0 - 仿真模式；1 - 真机模式
        mode = int(system_mode.perform(context))
        use_sim_time = (mode == 0)
        home = os.environ.get('HOME', '')

        # 启动 Server
        func_mode_server = Node(
            package='openmover', executable='func_mode_server_handler.py',
            name='func_mode_server_handler', output='screen', respawn=True,
            parameters=[{
                'system_mode': mode,
                'launch_file_create_map': os.path.join(
                    launch_dir, 'apps', 'mapping.launch.py'),
                'launch_file_nav_mode': os.path.join(
                    launch_dir, 'apps', 'navigation.launch.py'),
                'launch_file_load_map': os.path.join(
                    launch_dir, 'modules', 'mapping', 'map_server.launch.py'),
                'nav_map_save_path': os.path.join(
                    home, 'openmover_robot', 'maps') + os.sep,
                'enable_visualization':
                    enable_visualization.perform(context) == 'true',
                'visualization_config_file_idle': os.path.join(
                    rviz_dir, 'idle.rviz'),
                'visualization_config_file_working': os.path.join(
                    rviz_dir, 'working.rviz'),
                'visualization_config_file_working_nomap': os.path.join(
                    rviz_dir, 'working_nomap.rviz'),
                'use_sim_time': use_sim_time,
            }])

        # 启动可视化
        rviz = Node(
            package='rviz2', executable='rviz2', name='rviz',
            arguments=['-d', os.path.join(rviz_dir, 'idle.rviz')],
            parameters=[{'use_sim_time': use_sim_time}],
            remappings=[
                ('initialpose', 'openmover/localization/initialpose'),
                ('goal', 'openmover/navigation/simple_goal'),
            ],
            condition=IfCondition(enable_visualization))

        # 机器人驱动
        bringup = IncludeLaunchDescription(
            os.path.join(launch_dir, 'hardwares', 'bringup.launch.py'),
            launch_arguments={
                'system_mode': str(mode),
                'sim_area': sim_area.perform(context),
                'use_sim_time': 'true' if use_sim_time else 'false',
                'launch_gazebo': launch_gazebo.perform(context),
            }.items())

        return [func_mode_server, rviz, bringup]

    # 启动 Bridge
    rosbridge = IncludeLaunchDescription(
        os.path.join(get_package_share_directory('rosbridge_server'),
                     'launch', 'rosbridge_websocket_launch.xml'),
        launch_arguments={'port': '8080'}.items())

    return LaunchDescription([
        DeclareLaunchArgument('system_mode', default_value='0'),
        DeclareLaunchArgument('sim_area', default_value='1'),
        DeclareLaunchArgument('enable_visualization', default_value='true'),
        DeclareLaunchArgument(
            'launch_gazebo', default_value='1',
            description='仿真模式下是否启动 Gazebo 本体；0 = 外部仿真器（Isaac）'),
        OpaqueFunction(function=build_nodes),
        rosbridge,
    ])
