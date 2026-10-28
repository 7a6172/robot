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
    # BGR thresholds and the crop offset: the ROS 1 literals in ROS 1, and in ROS 2 the same values
    # as parameter defaults -- they became parameters so a floor where the tape widens into the near
    # field can be calibrated without editing code (see test_line_follower_vision_is_calibratable).
    for token in ('[10, 20, 10]', '[40, 50, 40]', 'height // 2 + 100'):
        assert token in ros1, token
    assert "'line_lower', [10, 20, 10]" in ros2
    assert "'line_upper', [40, 50, 40]" in ros2
    assert "height // 2 + self.roi_top_offset" in ros2
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


def test_no_ros1_private_name_syntax():
    """ROS 2 rejects `~name` (ROS 1's private namespace). Relative names give the same result.

    `self.create_publisher(String, '~state', ...)` raised InvalidTopicNameException on the robot
    and the mission node exited immediately, so the whole supervisor was dead on arrival.
    """
    import pathlib
    here = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in sorted((here / 'scripts').glob('*.py')):
        if 'ros1_reference' in str(path):
            continue
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            if re.search(r"[\"']~[A-Za-z_]", line):
                offenders.append(f'{path.name}:{number}: {stripped}')
    assert not offenders, 'ROS 1 private names in ROS 2 code:\n' + '\n'.join(offenders)


def test_mission_interface_names_match_ros1_when_qualified():
    """The relative names must resolve to the ROS 1 fully-qualified ones."""
    import pathlib
    here = pathlib.Path(__file__).resolve().parent.parent
    text = (here / 'scripts' / 'line_then_home.py').read_text(encoding='utf-8')
    code = '\n'.join(l for l in text.splitlines() if not l.strip().startswith('#'))
    for name in ('state', 'start', 'stop', 'record_waypoints'):
        assert f"self.prefix + '/{name}'" in code, (
            f'{name} must be named from the node name so it expands to /line_then_home/{name} '
            'as in ROS 1 (a plain relative name would become /' + name + ')')
    assert "self.prefix = '/' + self.get_name()" in code
    assert "'~" not in code, 'a private-name topic/service survived in code (comments may mention it)'


def test_line_follower_has_an_obstacle_stop_from_the_body_edge():
    """The follower must stop on obstacles, measured from the BODY, not from the sensor.

    ROS 1's follower had no obstacle check at all -- only "line lost" and "end of line". The
    LiDAR sits at the robot's centre (x=0, y=0), so a raw range is the distance to the centre
    while the body still reaches 0.16 m ahead. A guard that stopped at a raw 0.22 m left 6 cm,
    and the robot crept into a wall boundary during verification.
    """
    text = (pathlib.Path(__file__).resolve().parent.parent / 'scripts'
            / 'omove_following_feng.py').read_text(encoding='utf-8')
    assert 'BODY_HALF_LENGTH = 0.16' in text, 'body half-length must come from the URDF value'
    assert 'OBSTACLE_STOP_DISTANCE = BODY_HALF_LENGTH + OBSTACLE_MARGIN' in text, (
        'the stop distance must include the body offset, not just the sensor range')
    assert 'OBSTACLE_MARGIN' in text and '0.1' in text.split('OBSTACLE_MARGIN')[1][:20]
    assert 'self.obstacle_stop' in text
    assert "'/scan'" in text, 'the follower needs the scan to detect obstacles'


def test_mission_can_start_from_tf_when_amcl_pose_is_absent():
    """ROS 1's amcl published /amcl_pose continuously; nav2's publishes only on filter updates.

    The mission requires a home pose before it will enable the line follower, and the follower is
    what moves the robot -- so on a stationary robot the `/amcl_pose` precondition could never be
    satisfied, and the task was unstartable. Setting an initial pose produced `map -> base_link`
    but no `/amcl_pose`. The transform carries the same information, so it is used as a fallback;
    the ROS 1 precondition stays as the primary path.
    """
    import pathlib
    text = (pathlib.Path(__file__).resolve().parent.parent / 'scripts'
            / 'line_then_home.py').read_text(encoding='utf-8')
    assert 'def pose_from_tf' in text
    assert 'pose = self.pose_from_tf()' in text
    # the lookup must be in the map frame with a timeout, not a bare call
    assert 'self.map_frame, self.base_frame' in text
    assert 'timeout=rclpy.duration.Duration(seconds=self.tf_timeout)' in text
    # the primary /amcl_pose path is still there
    assert "'/amcl_pose'" in text
    # and the failure message still tells the operator what to do
    assert 'set an initial' in text
def test_pose_from_tf_builds_a_pose_and_survives_a_missing_chain():
    """The TF fallback is the only reason the mission can start on ROS 2.

    It could not be exercised on the robot before the battery ran out, so its logic is checked
    here directly: a successful lookup becomes a PoseWithCovarianceStamped in the map frame, and
    any lookup failure yields None instead of raising -- so `start` still answers with a helpful
    message rather than dying.
    """
    import importlib.util
    import pathlib
    import types

    root = pathlib.Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('lth', root / 'scripts' / 'line_then_home.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Logger:
        def warn(self, *_a, **_k): pass
        def info(self, *_a, **_k): pass

    translation = types.SimpleNamespace(x=1.5, y=-2.5, z=0.0)
    rotation = types.SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0)

    class GoodBuffer:
        def lookup_transform(self, target, source, _time, timeout=None):
            assert target == 'map' and source == 'base_link'
            assert timeout is not None, 'the lookup must bound its wait'
            return types.SimpleNamespace(transform=types.SimpleNamespace(
                translation=translation, rotation=rotation))

    class BadBuffer:
        def lookup_transform(self, *_a, **_k):
            raise RuntimeError('chain not there yet')

    # a fake self is enough: the method only touches these attributes
    fake = types.SimpleNamespace(tf_buffer=GoodBuffer(), map_frame='map',
                                 base_frame='base_link', tf_timeout=1.0,
                                 get_logger=lambda: Logger())
    pose = module.LineThenHome.pose_from_tf(fake)
    assert pose is not None
    assert pose.header.frame_id == 'map'
    assert abs(pose.pose.pose.position.x - 1.5) < 1e-9
    assert abs(pose.pose.pose.position.y + 2.5) < 1e-9
    assert abs(pose.pose.pose.orientation.w - 1.0) < 1e-9

    fake.tf_buffer = BadBuffer()
    assert module.LineThenHome.pose_from_tf(fake) is None, 'a missing chain must not raise'


def test_line_follower_vision_is_calibratable_with_ros1_defaults():
    """The crop and the colour range must be parameters, defaulting to the ROS 1 values.

    On this floor the tape widens into the near field, so the crop's nearest rows are a wide dark
    band and the end-of-line test fires on the first frames. The ROS 1 author calibrated this
    interactively (the click-to-print-BGR callback); headless, the same calibration has to be
    expressible as parameters. The defaults stay exactly as ported.
    """
    import pathlib
    text = (pathlib.Path(__file__).resolve().parent.parent / 'scripts'
            / 'omove_following_feng.py').read_text(encoding='utf-8')
    assert "'roi_top_offset', 100" in text, 'ROS 1 crop offset must remain the default'
    assert "'roi_bottom_offset', 0" in text
    assert "'line_lower', [10, 20, 10]" in text, 'ROS 1 thresholds must remain the defaults'
    assert "'line_upper', [40, 50, 40]" in text
    # and they must actually be used
    assert 'cv2.inRange(crop_img, self.line_lower, self.line_upper)' in text
    assert 'self.roi_top_offset' in text and 'self.roi_bottom_offset' in text
    # the hard-coded values must be gone
    assert "np.array([10, 20, 10], dtype='uint8')" not in text
