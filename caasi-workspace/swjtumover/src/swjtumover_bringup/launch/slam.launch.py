"""ROS 2 replacement for `bringup_gmapping.launch`: bringup + SLAM.

ROS 1 ran `gmapping` (a particle filter). gmapping has no ROS 2 port, so this uses
slam_toolbox -- nav2's default graph SLAM -- which keeps the same `map -> odom` contract that
amcl, nav2 and the task scripts expect. Parameters live in param/slam_toolbox_params.yaml,
where the mapping from the old gmapping settings is documented.

It is **not** a like-for-like algorithm: map texture and loop closure will differ. The ROS 1
map remains the reference for comparison.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

share_dir = get_package_share_directory('swjtumover_bringup')
bringup_launch = os.path.join(share_dir, 'launch', 'bringup.launch.py')
slam_params = os.path.join(share_dir, 'param', 'slam_toolbox_params.yaml')


def generate_launch_description():
    use_sim_time = LaunchConfiguration('use_sim_time')
    start_hardware = LaunchConfiguration('start_hardware')
    lidar_bind_lead = LaunchConfiguration('lidar_bind_lead')

    hardware = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(bringup_launch),
        condition=IfCondition(start_hardware),
        launch_arguments={'enable_teleop': 'false',
                          'enable_visualization': 'false',
                          'use_sim_time': use_sim_time}.items())

    # SLAM needs /scan, odom and the TF tree to exist first.
    slam = Node(
        package='slam_toolbox', executable='sync_slam_toolbox_node', name='slam_toolbox',
        output='screen',
        parameters=[slam_params, {'use_sim_time': use_sim_time}])

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument(
            'start_hardware', default_value='true',
            description='Also start bringup.launch.py; set false if hardware is already up.'),
        DeclareLaunchArgument(
            'lidar_bind_lead', default_value='3.0',
            description='Passed to bringup: the LiDAR must own UDP 7000 before other nodes.'),
        hardware,
        TimerAction(period=lidar_bind_lead, actions=[slam]),
    ])
