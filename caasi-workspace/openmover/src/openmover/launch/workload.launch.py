#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 文件描述：workload.launch 的 ROS 2 Jazzy 移植（Stage 8）
# 加载机器人系统：bootloader + 业务流程节点

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch_ros.actions import Node

share_dir = get_package_share_directory('openmover')
config_dir = os.path.join(share_dir, 'config_defaults')

hardwares_yaml = os.path.join(config_dir, 'hardwares.yaml')
modules_yaml = os.path.join(config_dir, 'modules.yaml')
navigation_yaml = os.path.join(config_dir, 'apps', 'navigation', 'navigation.yaml')


def generate_launch_description():
    return LaunchDescription([
        # 启动机器人
        IncludeLaunchDescription(os.path.join(share_dir, 'launch', 'bootloader.launch.py')),

        # 启动业务流程
        Node(package='openmover', executable='workload.py', name='workload',
             output='screen',
             parameters=[hardwares_yaml, modules_yaml, navigation_yaml]),
    ])
