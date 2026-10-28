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
# ROS 1 served nav.yaml: the whole building, 99 x 99 m at 0.05 m. As a nav2 global costmap that is
# 3.9M cells and saturates this CPU -- the planner ran at 12.7 Hz and the lifecycle manager's
# configure calls started timing out, aborting bringup. nav_maze.yaml is the same map cropped to
# the maze (world coordinates preserved), 153x less work. Pass map:=.../nav.yaml for the full
# building.
default_map = os.path.join(share_dir, 'map', 'nav_maze.yaml')


def generate_launch_description():
    use_sim_time = LaunchConfiguration('use_sim_time')
    map_yaml = LaunchConfiguration('map')
    cmd_vel_topic = LaunchConfiguration('cmd_vel_topic')

    set_initial_pose = LaunchConfiguration('set_initial_pose')
    initial_pose_x = LaunchConfiguration('initial_pose_x')
    initial_pose_y = LaunchConfiguration('initial_pose_y')
    initial_pose_yaw = LaunchConfiguration('initial_pose_yaw')

    map_server = LifecycleNode(
        package='nav2_map_server', executable='map_server', name='map_server',
        namespace='', output='screen',
        parameters=[nav2_params, {'yaml_filename': map_yaml,
                                  'use_sim_time': use_sim_time}])

    amcl = LifecycleNode(
        package='nav2_amcl', executable='amcl', name='amcl', namespace='', output='screen',
        parameters=[nav2_params,
                    {'use_sim_time': use_sim_time,
                     'set_initial_pose': set_initial_pose,
                     'initial_pose.x': initial_pose_x,
                     'initial_pose.y': initial_pose_y,
                     'initial_pose.z': 0.0,
                     'initial_pose.yaw': initial_pose_yaw}])

    planner = LifecycleNode(
        package='nav2_planner', executable='planner_server', name='planner_server',
        namespace='', output='screen',
        parameters=[nav2_params, {'use_sim_time': use_sim_time}])

    controller = LifecycleNode(
        package='nav2_controller', executable='controller_server', name='controller_server',
        namespace='', output='screen',
        parameters=[nav2_params, {'use_sim_time': use_sim_time}],
        # The controller feeds the velocity smoother, not the final topic: the smoother
        # subscribes `cmd_vel_nav_raw` and publishes `cmd_vel_smoothed`, which becomes
        # `cmd_vel_topic`. Sending the controller straight to the final topic (as this launch
        # originally did) bypassed the smoother entirely, so nothing reached the wheels: nav2
        # logged "Passing new path to controller" then "Failed to make progress" while odometry
        # stayed at zero.
        remappings=[('cmd_vel', 'cmd_vel_nav_raw')])

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
            'set_initial_pose', default_value='false',
            description='Seed amcl with initial_pose_* instead of waiting for a /initialpose '
                        'message (the rviz "2D Pose Estimate" equivalent). Off by default: a '
                        'fabricated pose would let nav2 plan from where the robot is not.'),
        DeclareLaunchArgument('initial_pose_x', default_value='0.0'),
        DeclareLaunchArgument('initial_pose_y', default_value='0.0'),
        DeclareLaunchArgument('initial_pose_yaw', default_value='0.0'),
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
