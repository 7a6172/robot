"""ROS 2 port of swjtumover_bringup/launch/bringup.launch.

Starts what the ROS 1 file started: robot_state_publisher, joint_state_publisher, the LiDAR,
the motor driver, the screen driver and (optionally) teleoperation and rviz.

Two things are deliberate:

* **The LiDAR starts first, on a timer lead.** In this environment every ROS 2 process binds
  UDP 7000, while the Vanjee 718H sends its scans to 192.168.110.10:7000. The driver must
  therefore bind it before any other node exists -- measured on the robot: a bare rclpy node
  takes 0.0.0.0:7000 and holds it without SO_REUSEADDR. `lidar_bind_lead` is a launch argument.
* **Optional components are arguments, not assumptions.** RealSense, rviz and teleoperation are
  all off unless asked for, because a headless robot cannot run rviz and teleoperation needs a
  display. The ROS 1 file hardcoded rviz on, which simply failed on this robot.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, OpaqueFunction, TimerAction)
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node

share_dir = get_package_share_directory('swjtumover_bringup')
config_dir = os.path.join(share_dir, 'config')

# The LiDAR adapter owns its own parameters: it reads a flat ROS 2 file under its node name,
# whereas config/lidar.yaml in this package is the ROS 1 vendor schema (`common:`/`lidar:` with no
# `ros__parameters`) kept for reference. Passing the ROS 1 file to a ROS 2 node fails to parse --
# found by running the launch on the robot, so the adapter's file is resolved from its own package.
vanjee_config_dir = os.path.join(get_package_share_directory('swjtumover_vanjee'), 'config')
urdf_file = os.path.join(share_dir, 'urdf', 'robot_description.urdf')


def generate_launch_description():
    use_sim_time = LaunchConfiguration('use_sim_time')
    enable_teleop = LaunchConfiguration('enable_teleop')
    enable_realsense = LaunchConfiguration('enable_realsense')
    enable_visualization = LaunchConfiguration('enable_visualization')
    lidar_bind_lead = LaunchConfiguration('lidar_bind_lead')

    def publish_robot_description(context):
        if not os.path.isfile(urdf_file):
            raise RuntimeError(f"robot model not found: {urdf_file}")
        with open(urdf_file, 'r') as handle:
            description = handle.read()
        return [Node(
            package='robot_state_publisher', executable='robot_state_publisher',
            name='robot_state_publisher', output='screen',
            parameters=[{'robot_description': description,
                         'use_sim_time': use_sim_time.perform(context) == 'true'}])]

    # The LiDAR driver must own UDP 7000 first; see the module docstring.
    lidar_first = Node(
        package='swjtumover_vanjee', executable='vanjee_scan_node',
        name='vanjee_lidar_node', output='screen', respawn=True,
        parameters=[os.path.join(vanjee_config_dir, 'lidar.yaml'),
                    {'use_sim_time': use_sim_time}])

    deferred = [
        OpaqueFunction(function=publish_robot_description),
        Node(package='joint_state_publisher', executable='joint_state_publisher',
             name='joint_state_publisher', output='screen',
             parameters=[{'use_sim_time': use_sim_time}]),

        # Motor driver: the only actuator path. Actuation gates do not exist in this robot, so
        # this node is exactly as capable as the ROS 1 one -- it has the watchdog the ROS 1
        # variant on swjtumover05 lacked.
        Node(package='swjtumover_bringup', executable='motor_node', name='motor_node',
             output='screen', respawn=True,
             parameters=[os.path.join(config_dir, 'motor.yaml'),
                         {'use_sim_time': use_sim_time}]),

        # Screen driver: writes to the display board over UDP.
        Node(package='swjtumover_bringup', executable='screen_node', name='screen_node',
             output='screen', respawn=True,
             parameters=[os.path.join(config_dir, 'screen.yaml'),
                         {'use_sim_time': use_sim_time}]),

        # Teleoperation: needs an operator session with a display.
        Node(package='swjtumover_bringup', executable='teleop_node.py', name='teleop_node',
             output='screen', respawn=False,
             condition=IfCondition(enable_teleop),
             parameters=[os.path.join(config_dir, 'teleop.yaml'),
                         {'use_sim_time': use_sim_time}]),

        # RealSense D415, as in ROS 1. Off by default: the ROS 2 wrapper must be installed and
        # the ROS 1 launch arguments do not map one-to-one.
        Node(package='realsense2_camera', executable='realsense2_camera_node',
             name='camera', output='screen', respawn=False,
             condition=IfCondition(enable_realsense),
             parameters=[{'align_depth': True, 'pointcloud.enable': True,
                          'clip_distance': 3.0,
                          'rgb_camera.color_profile': '640x480x30',
                          'depth_module.depth_profile': '640x480x30',
                          'use_sim_time': use_sim_time}]),

        Node(package='rviz2', executable='rviz2', name='rviz2', output='screen',
             condition=IfCondition(enable_visualization),
             arguments=['-d', os.path.join(share_dir, 'config', 'bringup.rviz')]),
    ]

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument(
            'enable_teleop', default_value='false',
            description='Start teleoperation. Needs an operator session with DISPLAY.'),
        DeclareLaunchArgument(
            'enable_realsense', default_value='false',
            description='Start the RealSense D415 camera node.'),
        DeclareLaunchArgument(
            'enable_visualization', default_value='false',
            description='Start rviz2. Off by default: the robot is headless.'),
        DeclareLaunchArgument(
            'lidar_bind_lead', default_value='3.0',
            description='Seconds between starting the LiDAR driver and the rest of the stack. '
                        'The driver must own UDP 7000 before any other ROS 2 node binds it.'),
        lidar_first,
        TimerAction(period=lidar_bind_lead, actions=deferred),
    ])
