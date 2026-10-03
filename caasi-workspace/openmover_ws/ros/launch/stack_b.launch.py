"""Stack B (warehouse_simulation) ROS side against Isaac — Step 1.5.

Replicates warehouse_simulation.launch.py minus the Gazebo parts (gz_sim,
ros_gz_bridge, gz_spawn_model): Isaac plays those roles via
scripts/16_bridge_ros.py (/clock /odom /tf /cmd_vel + the two bluesea2 scans).

Additions vs the original, all Isaac-side only (no ROS package modified):
  - laserscan_multi_merger (ira_laser_tools, runs unmodified; launch params
    mirror openmover's bringup) merges Isaac's front/rear bluesea2 scans and
    publishes the 360 deg result on /scan. destination_frame is base_link
    because Stack B's URDF has no lidar_link.
  - nav:=false by default: the Step 1.5 gate is teleop + mapping; pass
    nav:=true to also bring up Nav2. rviz:=true re-enables visualization.

Run (in a terminal sourced for ROS 2 Jazzy + this workspace):
  ros2 launch openmover_ws/isaac/scripts/16_stack_b.launch.py

Then start the Isaac side:
  source /opt/ros/jazzy/setup.bash && \
  ~/isaacsim/python.sh openmover_ws/isaac/scripts/16_bridge_ros.py
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, ExecuteProcess,
                            IncludeLaunchDescription, TimerAction)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    wh_share = get_package_share_directory('warehouse_simulation')
    xacro_file = os.path.join(wh_share, 'urdf', 'pioneer3dx.urdf.xacro')
    nav2_params = os.path.join(wh_share, 'config', 'nav2_params.yaml')
    slam_params = os.path.join(wh_share, 'config', 'slam_toolbox.yaml')
    rviz_config = os.path.join(wh_share, 'rviz', 'navigation.rviz')

    use_sim_time = True  # Isaac publishes /clock
    nav = LaunchConfiguration('nav')
    rviz = LaunchConfiguration('rviz')

    robot_description = ParameterValue(
        Command(['xacro ', xacro_file]), value_type=str)

    return LaunchDescription([
        DeclareLaunchArgument('nav', default_value='false',
                              description='Also bring up Nav2 (default: '
                                          'teleop + mapping only)'),
        DeclareLaunchArgument('rviz', default_value='false'),

        # 1. robot_state_publisher (unchanged from warehouse_simulation)
        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            name='robot_state_publisher',
            output='screen',
            parameters=[{'use_sim_time': use_sim_time,
                         'robot_description': robot_description}],
        ),

        # 2. scan merger (unmodified node; Isaac-side launch params mirror
        #    openmover's bringup except destination_frame=base_link and
        #    scan_destination_topic=/scan for the Stack B contract)
        Node(
            package='ira_laser_tools',
            executable='laserscan_multi_merger',
            name='laserscan_multi_merger',
            output='screen',
            parameters=[{
                'destination_frame': 'base_link',
                'cloud_destination_topic': '/openmover/hardware/lidar/pointcloud',
                'scan_destination_topic': '/scan',
                'laserscan_topics':
                    '/openmover/hardware/lidar_forward/scan '
                    '/openmover/hardware/lidar_rear/scan',
                'angle_min': -3.1415926,
                'angle_max': 3.1415926,
                'angle_increment': 0.006962,
                'scan_time': 0.0,
                'range_min': 0.33,
                'range_max': 20.0,
                'use_sim_time': use_sim_time,
            }],
        ),

        # 3. slam_toolbox (unchanged include + activation timer)
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(get_package_share_directory('slam_toolbox'),
                             'launch', 'online_async_launch.py')),
            launch_arguments={
                'use_sim_time': 'true',
                'slam_params_file': slam_params,
            }.items(),
        ),
        TimerAction(
            period=12.0,
            actions=[ExecuteProcess(
                cmd=['bash', '-c',
                     'state=$(ros2 lifecycle get /slam_toolbox 2>/dev/null); '
                     'case "$state" in *inactive*) '
                     'ros2 lifecycle set /slam_toolbox activate;; esac'],
                output='screen')],
        ),

        # 4. Nav2 (optional for the teleop gate)
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(get_package_share_directory('nav2_bringup'),
                             'launch', 'navigation_launch.py')),
            launch_arguments={
                'use_sim_time': 'true',
                'params_file': nav2_params,
                'autostart': 'True',
            }.items(),
            condition=IfCondition(nav),
        ),

        # 5. trajectory + cmd_vel watchdog (unchanged)
        Node(
            package='warehouse_simulation',
            executable='trajectory_server.py',
            name='trajectory_server',
            output='screen',
            parameters=[{'use_sim_time': use_sim_time,
                         'frame_id': 'map',
                         'target_frame': 'base_link'}],
        ),
        Node(
            package='warehouse_simulation',
            executable='cmd_vel_watchdog.py',
            name='cmd_vel_watchdog',
            output='screen',
            parameters=[{'use_sim_time': use_sim_time, 'timeout': 0.4}],
        ),

        # 6. rviz2 (optional; off by default to save RAM during gates)
        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            arguments=['-d', rviz_config],
            parameters=[{'use_sim_time': use_sim_time}],
            condition=IfCondition(rviz),
        ),
    ])
