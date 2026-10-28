"""ROS 2 replacement for `line_then_home.launch` / `line_then_home_loop.launch`.

The ROS 1 mission, preserved:
  * optional hardware bringup (`start_hardware`), exactly as before;
  * map server + localisation + navigation;
  * the line follower on `/cmd_vel/line` and nav2 on `/cmd_vel/nav`, with the mission node as
    the single arbiter publishing `/cmd_vel`;
  * `~start`, `~stop`, `~record_waypoints` services on the mission node.

Usage, as recorded in the robot's shell history:

    ros2 launch swjtumover_bringup line_then_home.launch.py
    ros2 service call /line_then_home/start std_srvs/srv/Trigger
    ros2 service call /line_then_home/record_waypoints std_srvs/srv/Trigger
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
navigation_launch = os.path.join(share_dir, 'launch', 'navigation.launch.py')
config_dir = os.path.join(share_dir, 'config')


def generate_launch_description():
    use_sim_time = LaunchConfiguration('use_sim_time')
    start_hardware = LaunchConfiguration('start_hardware')
    map_yaml = LaunchConfiguration('map')
    lidar_bind_lead = LaunchConfiguration('lidar_bind_lead')
    color_topic = LaunchConfiguration('color_topic')
    depth_topic = LaunchConfiguration('depth_topic')

    hardware = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(bringup_launch),
        condition=IfCondition(start_hardware),
        launch_arguments={'enable_teleop': 'false',
                          'enable_visualization': 'false',
                          # Forwarded, not just used for the timer below: without this the bringup
                          # kept its own 3 s default while the timer honoured the argument, so the
                          # two disagreed as soon as anyone changed it.
                          'lidar_bind_lead': lidar_bind_lead,
                          'use_sim_time': use_sim_time}.items())

    navigation = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(navigation_launch),
        launch_arguments={'map': map_yaml, 'use_sim_time': use_sim_time}.items())

    # Line follower: ROS 1 remapped its `/cmd_vel` to `/cmd_vel/line` so it never talks to the
    # wheels directly. Same here. Enabled by the mission node through /line_follow/enable.
    line_follower = Node(
        package='swjtumover_bringup', executable='omove_following_feng.py',
        name='omove_following', output='screen',
        parameters=[{'enabled': False, 'end_confirm_frames': 5, 'image_timeout': 0.5,
                     # ROS 1 published colour/depth on /d415/...; realsense2_camera on Jazzy uses
                     # /camera/camera/.... Left at the ROS 1 defaults the follower would never see
                     # an image and would simply never move, with no error to explain it.
                     'color_topic': color_topic,
                     'depth_topic': depth_topic,
                     'use_sim_time': use_sim_time}],
        remappings=[('/cmd_vel', '/cmd_vel/line')])

    mission = Node(
        package='swjtumover_bringup', executable='line_then_home.py',
        name='line_then_home', output='screen',
        parameters=[os.path.join(config_dir, 'line_then_home.yaml'),
                    {'use_sim_time': use_sim_time}])

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('start_hardware', default_value='true',
                              description='Start bringup too; false if hardware is already up.'),
        DeclareLaunchArgument(
            'map', default_value=os.path.join(share_dir, 'map', 'nav_maze.yaml'),
            description='Cropped maze map by default (world coordinates preserved); pass '
                        'nav.yaml for the whole building.'),
        DeclareLaunchArgument(
            'color_topic', default_value='/camera/camera/color/image_raw',
            description='Colour image for the line follower. ROS 1 used /d415/color/image_raw.'),
        DeclareLaunchArgument(
            'depth_topic', default_value='/camera/camera/depth/image_rect_raw',
            description='Depth image for the line follower.'),
        DeclareLaunchArgument('lidar_bind_lead', default_value='3.0'),
        hardware,
        TimerAction(period=lidar_bind_lead, actions=[navigation, line_follower, mission]),
    ])
