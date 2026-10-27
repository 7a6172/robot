"""Task-behaviour migrations: the contracts the ROS 1 scripts promised must still hold.

The ROS 1 originals are in scripts/ros1_reference/ and are read here, so these tests fail if a
future change silently alters a topic name, a service name or a tuning constant that the robot's
behaviour depends on.
"""
from __future__ import annotations

import pathlib
import re

import yaml

PKG = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = PKG / 'scripts'
ROS1 = SCRIPTS / 'ros1_reference'
CONFIG = PKG / 'config'
PARAM = PKG / 'param'
LAUNCH = PKG / 'launch'


def _read(path) -> str:
    return pathlib.Path(path).read_text(encoding='utf-8', errors='replace')


# ------------------------------------------------------- obstacle guard

def test_obstacle_constants_unchanged():
    """These are safety numbers: speed, stop distance, lidar error and sector width."""
    ros1 = _read(ROS1 / 'obstacle_rplidar.py')
    ros2 = _read(SCRIPTS / 'obstacle_rplidar.py')
    for name, value in (('LINEAR_VEL', '0.2'), ('STOP_DISTANCE', '0.8'),
                        ('LIDAR_ERROR', '0.05'), ('FRONT_ANGLE_DEG', '10')):
        assert re.search(rf'{name}\s*=\s*{value}', ros1), f'ROS 1 changed {name}'
        assert re.search(rf'{name}\s*=\s*{value}', ros2), f'ROS 2 changed {name}'
    assert 'SAFE_STOP_DISTANCE = STOP_DISTANCE + LIDAR_ERROR' in ros2


def test_obstacle_topics_unchanged():
    ros1 = _read(ROS1 / 'obstacle_rplidar.py')
    ros2 = _read(SCRIPTS / 'obstacle_rplidar.py')
    for topic in ('/cmd_vel', '/scan'):
        assert topic in ros1 and topic in ros2, topic


# ------------------------------------------------------- line follower

def test_line_follower_vision_constants_unchanged():
    ros1 = _read(ROS1 / 'omove_following_feng.py')
    ros2 = _read(SCRIPTS / 'omove_following_feng.py')
    # forward speed, steering gain and the normalisation width
    assert '0.12' in ros1 and '0.12' in ros2
    assert '-self.yaw * 0.6' in ros1 and '-self.yaw * 0.6' in ros2
    assert '(x - width / 2) / 320.0' in ros1 and '(x - width / 2) / 320.0' in ros2
    # BGR thresholds and the crop offset
    for token in ('[10, 20, 10]', '[40, 50, 40]', 'height // 2 + 100'):
        assert token in ros1 and token in ros2, token
    # end-of-line detection
    for token in ('minLineLength=100', 'maxLineGap=10', 'threshold=100', 'abs(slope) < 0.2'):
        assert token in ros1 and token in ros2, token


def test_line_follower_default_parameters_unchanged():
    ros1 = _read(ROS1 / 'omove_following_feng.py')
    ros2 = _read(SCRIPTS / 'omove_following_feng.py')
    # ROS 1 spells them ~end_confirm_frames / ~image_timeout; the defaults must match.
    assert "end_confirm_frames', 1" in ros1 and "end_confirm_frames', 1" in ros2
    assert "image_timeout', 0.5" in ros1 and "image_timeout', 0.5" in ros2


def test_line_follower_topics_unchanged():
    ros1 = _read(ROS1 / 'omove_following_feng.py')
    ros2 = _read(SCRIPTS / 'omove_following_feng.py')
    for topic in ('/cmd_vel', '/lane_image', '/line_follow/enable', '/line_follow/end',
                  '/d415/color/image_raw', '/d415/depth/image_rect_raw'):
        assert topic in ros1 and topic in ros2, topic


def test_line_follower_gui_is_optional():
    """ROS 1 always created a window; a headless robot cannot. Default must be off."""
    ros2 = _read(SCRIPTS / 'omove_following_feng.py')
    assert "declare_parameter('gui', False)" in ros2


# --------------------------------------------------------- mission node

def test_mission_services_and_topics_unchanged():
    ros1 = _read(ROS1 / 'line_then_home.py')
    ros2 = _read(SCRIPTS / 'line_then_home.py')
    for service in ('~start', '~stop', '~record_waypoints'):
        assert service in ros1 and service in ros2, service
    for topic in ('/cmd_vel', '/cmd_vel/line', '/cmd_vel/nav', '/amcl_pose',
                  '/clicked_point', '/line_follow/end', '/line_follow/enable', '~state'):
        assert topic in ros1 and topic in ros2, topic


def test_mission_parameters_present_and_explicit():
    """ROS 1 relied on code defaults; ROS 2 makes them explicit in YAML with the same values."""
    params = yaml.safe_load(_read(CONFIG / 'line_then_home.yaml'))['line_then_home']['ros__parameters']
    expected = {'cmd_timeout': 0.5, 'stop_duration': 0.7, 'follow_timeout': 300.0,
                'nav_timeout': 180.0, 'tf_timeout': 1.0, 'map_frame': 'map',
                'base_frame': 'base_link'}
    for key, value in expected.items():
        assert params[key] == value, f'{key}: expected {value}, got {params.get(key)}'


def test_mission_uses_nav2_instead_of_move_base():
    ros2 = _read(SCRIPTS / 'line_then_home.py')
    assert 'NavigateToPose' in ros2
    assert 'import actionlib' not in ros2
    assert 'MoveBaseAction' not in ros2


# ------------------------------------------------------- navigation params

def test_nav2_params_carry_the_ros1_values():
    """The kinematics and geometry must survive the move_base -> nav2 conversion."""
    params = yaml.safe_load(_read(PARAM / 'nav2_params.yaml'))
    follow = params['controller_server']['ros__parameters']['FollowPath']
    assert follow['max_vel_x'] == 0.6          # TEB max_vel_x
    assert follow['max_vel_theta'] == 1.0      # TEB max_vel_theta
    assert follow['acc_lim_x'] == 0.5          # TEB acc_lim_x
    assert follow['acc_lim_theta'] == 1.0      # TEB acc_lim_theta
    assert follow['xy_goal_tolerance'] == 0.2  # TEB xy_goal_tolerance
    # nav2 checks the yaw tolerance in the goal checker, not in the controller plugin.
    checker = params['controller_server']['ros__parameters']['general_goal_checker']
    assert checker['xy_goal_tolerance'] == 0.2
    assert checker['yaw_goal_tolerance'] == 0.1  # TEB yaw_goal_tolerance

    local = params['local_costmap']['local_costmap']['ros__parameters']
    assert local['width'] == 4 and local['height'] == 4
    assert local['resolution'] == 0.05
    assert local['global_frame'] == 'odom'
    assert local['rolling_window'] is True
    assert '[[0.16, 0.15], [0.16, -0.15], [-0.16, -0.15], [-0.16, 0.15]]' in local['footprint']

    glob = params['global_costmap']['global_costmap']['ros__parameters']
    assert glob['global_frame'] == 'map'
    assert glob['track_unknown_space'] is True
    assert glob['rolling_window'] is False

    amcl = params['amcl']['ros__parameters']
    assert amcl['min_particles'] == 2000
    assert amcl['max_particles'] == 5000
    assert amcl['laser_max_range'] == 10.0
    assert amcl['update_min_d'] == 0.03
    assert amcl['update_min_a'] == 0.05
    assert amcl['do_beamskip'] is True
    assert amcl['z_hit'] == 0.9 and amcl['z_rand'] == 0.1


def test_nav2_documents_the_planner_difference():
    """TEB has no nav2 default; the substitution must be stated in the file, not hidden."""
    text = _read(PARAM / 'nav2_params.yaml')
    assert 'DWB' in text and 'TEB' in text
    assert 'teb_local_planner' in text


def test_slam_parameters_keep_the_ros1_resolution_and_range():
    params = yaml.safe_load(_read(PARAM / 'slam_toolbox_params.yaml'))['slam_toolbox']['ros__parameters']
    assert params['resolution'] == 0.05        # gmapping delta
    assert params['max_laser_range'] == 16.0   # gmapping maxUrange
    assert params['min_laser_range'] == 0.25
    assert params['scan_topic'] == '/scan'


# --------------------------------------------------------------- launch

def test_line_then_home_arbitrates_the_command_topic():
    """The line follower must not publish /cmd_vel directly, and nav must not either."""
    text = _read(LAUNCH / 'line_then_home.launch.py')
    assert "('/cmd_vel', '/cmd_vel/line')" in text
    nav = _read(LAUNCH / 'navigation.launch.py')
    assert "'cmd_vel_topic', default_value='/cmd_vel/nav'" in nav
