#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""warehouse_simulation.launch.py

ROS 2 移植版 warehouse_simulation 一键启动（对应 ROS 1 warehouse_simulation.launch）：
  1. Gazebo Harmonic 加载 warehouse.sdf
  2. robot_state_publisher 发布 pioneer3dx 模型
  3. ros_gz_bridge 桥接 cmd_vel / odom / tf / joint_states / scan / clock
  4. 生成机器人（z=0.0，与 ROS 1 一致）
  5. slam_toolbox 异步在线建图（替代 gmapping）
  6. Nav2 导航栈（替代 move_base）
  7. rviz2 可视化
  8. trajectory_server 发布历史轨迹（替代 hector_trajectory_server）
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, ExecuteProcess,
                            IncludeLaunchDescription, OpaqueFunction,
                            SetEnvironmentVariable, TimerAction)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = get_package_share_directory('warehouse_simulation')

    world_file = os.path.join(pkg_share, 'worlds', 'warehouse.sdf')
    bridge_config = os.path.join(pkg_share, 'config', 'gz_bridge.yaml')
    nav2_params = os.path.join(pkg_share, 'config', 'nav2_params.yaml')
    slam_params = os.path.join(pkg_share, 'config', 'slam_toolbox.yaml')
    rviz_config = os.path.join(pkg_share, 'rviz', 'navigation.rviz')
    xacro_file = os.path.join(pkg_share, 'urdf', 'pioneer3dx.urdf.xacro')

    use_sim_time = LaunchConfiguration('use_sim_time')
    rviz = LaunchConfiguration('rviz')
    headless = LaunchConfiguration('headless')

    # xacro -> robot_description（必须声明为 str，否则 launch 会尝试按 yaml 解析）
    from launch_ros.parameter_descriptions import ParameterValue
    robot_description = ParameterValue(
        Command(['xacro ', xacro_file]), value_type=str)

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='true'),
        DeclareLaunchArgument('rviz', default_value='true'),
        DeclareLaunchArgument('headless', default_value='false',
                              description='Run gz sim server only (no GUI)'),
        # 机器人生成位置（与 ROS 1 warehouse_simulation.launch 的 x_pos/y_pos/z_pos 一致）
        DeclareLaunchArgument('x_pos', default_value='0.0'),
        DeclareLaunchArgument('y_pos', default_value='0.0'),
        DeclareLaunchArgument('z_pos', default_value='0.0'),

        # workcell / workcell_bin 模型按 model:// URI 引用，需加入资源路径；
        # URDF 中 package://warehouse_simulation/... 会被 gz 转为
        # model://warehouse_simulation/...，因此把 pkg_share 的上级目录也加入
        SetEnvironmentVariable(
            'GZ_SIM_RESOURCE_PATH',
            [os.path.join(pkg_share, 'models'), os.pathsep,
             os.path.dirname(pkg_share)]),

        # 1. Gazebo Harmonic（服务端 + GUI；headless:=true 时仅服务端）
        OpaqueFunction(function=lambda context: [IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(get_package_share_directory('ros_gz_sim'),
                             'launch', 'gz_sim.launch.py')),
            launch_arguments={'gz_args': (
                '-r -v 1 -s ' if context.launch_configurations['headless'] == 'true'
                else '-r -v 1 ') + world_file}.items(),
        )]),

        # 2. robot_state_publisher
        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            name='robot_state_publisher',
            output='screen',
            parameters=[{'use_sim_time': use_sim_time,
                         'robot_description': robot_description}],
        ),

        # 3. ros_gz_bridge（按 yaml 配置）
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(get_package_share_directory('ros_gz_bridge'),
                             'launch', 'ros_gz_bridge.launch.py')),
            launch_arguments={
                'bridge_name': 'ros_gz_bridge',
                'config_file': bridge_config,
            }.items(),
        ),

        # 4. 生成 pioneer3dx（z=0.0 与 ROS 1 一致；entity_name 显式固定，
        #    bridge 话题 /model/pioneer3dx/cmd_vel 依赖该名称）
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(get_package_share_directory('ros_gz_sim'),
                             'launch', 'gz_spawn_model.launch.py')),
            launch_arguments={
                'topic': '/robot_description',
                'entity_name': 'pioneer3dx',
                'x': LaunchConfiguration('x_pos'),
                'y': LaunchConfiguration('y_pos'),
                'z': LaunchConfiguration('z_pos'),
            }.items(),
        ),

        # 5. slam_toolbox 异步在线建图（替代 gmapping）
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(get_package_share_directory('slam_toolbox'),
                             'launch', 'online_async_launch.py')),
            launch_arguments={
                'use_sim_time': use_sim_time,
                'slam_params_file': slam_params,
            }.items(),
        ),

        # 5b. slam_toolbox 是 lifecycle 节点，其自带的 autostart 事件有时不会触发，
        #     这里延时检查并显式激活（已激活则跳过），确保 map->odom TF 一定发布
        TimerAction(
            period=12.0,
            actions=[ExecuteProcess(
                cmd=['bash', '-c',
                     'state=$(ros2 lifecycle get /slam_toolbox 2>/dev/null); '
                     'case "$state" in *inactive*) '
                     'ros2 lifecycle set /slam_toolbox activate;; esac'],
                output='screen')],
        ),

        # 6. Nav2 导航栈（替代 move_base）
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(get_package_share_directory('nav2_bringup'),
                             'launch', 'navigation_launch.py')),
            launch_arguments={
                'use_sim_time': use_sim_time,
                'params_file': nav2_params,
                'autostart': 'True',
            }.items(),
        ),

        # 7. 历史轨迹服务（替代 hector_trajectory_server）
        Node(
            package='warehouse_simulation',
            executable='trajectory_server.py',
            name='trajectory_server',
            output='screen',
            parameters=[{'use_sim_time': use_sim_time,
                         'frame_id': 'map',
                         'target_frame': 'base_link'}],
        ),

        # 7b. cmd_vel 看门狗：遥控松键后 0.4s 无指令自动发零速，防止机器人继续跑
        Node(
            package='warehouse_simulation',
            executable='cmd_vel_watchdog.py',
            name='cmd_vel_watchdog',
            output='screen',
            parameters=[{'use_sim_time': use_sim_time, 'timeout': 0.4}],
        ),

        # 8. rviz2
        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            arguments=['-d', rviz_config],
            parameters=[{'use_sim_time': use_sim_time}],
            condition=IfCondition(rviz),
        ),
    ])
