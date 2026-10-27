"""ROS 2 replacement for `map_server.launch` + `amcl.launch` + `move_base.launch`.

Same three responsibilities, now nav2:
  * map_server.launch   -> nav2_map_server with the same nav.yaml
  * amcl.launch         -> nav2_amcl with the ROS 1 particle-filter values
  * move_base.launch    -> planner_server (NavFn) + controller_server (DWB) + behaviors +
                           bt_navigator + the two costmaps

One interface detail is preserved deliberately: ROS 1 remapped move_base's output to
`/cmd_vel/nav`, because the mission supervisor selects between `/cmd_vel/nav` and
`/cmd_vel/line`. nav2's velocity smoother therefore publishes `/cmd_vel/nav`, not `/cmd_vel`,
so both systems keep the same arbitration.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode, Node

share_dir = get_package_share_directory('swjtumover_bringup')
nav2_params = os.path.join(share_dir, 'param', 'nav2_params.yaml')
default_map = os.path.join(share_dir, 'map', 'nav.yaml')


def generate_launch_description():
    use_sim_time = LaunchConfiguration('use_sim_time')
    map_yaml = LaunchConfiguration('map')
    cmd_vel_topic = LaunchConfiguration('cmd_vel_topic')

    map_server = LifecycleNode(
        package='nav2_map_server', executable='map_server', name='map_server',
        namespace='', output='screen',
        parameters=[nav2_params, {'yaml_filename': map_yaml,
                                  'use_sim_time': use_sim_time}])

    amcl = LifecycleNode(
        package='nav2_amcl', executable='amcl', name='amcl', namespace='', output='screen',
        parameters=[nav2_params, {'use_sim_time': use_sim_time}])

    planner = LifecycleNode(
        package='nav2_planner', executable='planner_server', name='planner_server',
        namespace='', output='screen',
        parameters=[nav2_params, {'use_sim_time': use_sim_time}])

    controller = LifecycleNode(
        package='nav2_controller', executable='controller_server', name='controller_server',
        namespace='', output='screen',
        parameters=[nav2_params, {'use_sim_time': use_sim_time}],
        remappings=[('cmd_vel', cmd_vel_topic)])

    behaviors = LifecycleNode(
        package='nav2_behaviors', executable='behavior_server', name='behavior_server',
        namespace='', output='screen',
        parameters=[nav2_params, {'use_sim_time': use_sim_time}])

    bt_navigator = LifecycleNode(
        package='nav2_bt_navigator', executable='bt_navigator', name='bt_navigator',
        namespace='', output='screen',
        parameters=[nav2_params, {'use_sim_time': use_sim_time}])

    smoother = LifecycleNode(
        package='nav2_velocity_smoother', executable='velocity_smoother',
        name='velocity_smoother', namespace='', output='screen',
        parameters=[nav2_params, {'use_sim_time': use_sim_time}],
        remappings=[('cmd_vel', 'cmd_vel_nav_raw'),
                    ('cmd_vel_smoothed', cmd_vel_topic)])

    lifecycle_manager = Node(
        package='nav2_lifecycle_manager', executable='lifecycle_manager',
        name='lifecycle_manager_navigation', output='screen',
        parameters=[{'use_sim_time': use_sim_time,
                     'autostart': True,
                     'node_names': ['map_server', 'amcl', 'planner_server',
                                    'controller_server', 'behavior_server',
                                    'bt_navigator', 'velocity_smoother']}])

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument(
            'map', default_value=default_map,
            description='Map YAML to serve, as in map_server.launch.'),
        DeclareLaunchArgument(
            'cmd_vel_topic', default_value='/cmd_vel/nav',
            description='Where nav2 publishes commands. ROS 1 remapped move_base to '
                        '/cmd_vel/nav so the mission supervisor can arbitrate; same here.'),
        map_server, amcl, planner, controller, behaviors, bt_navigator, smoother,
        lifecycle_manager,
    ])
