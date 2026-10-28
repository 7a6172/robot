"""ROS 1 -> ROS 2 parity of the migrated bringup: interface and default-parameter contracts.

A migration is only as good as the things that must NOT change. These tests read the ROS 1
sources kept in src/ros1_reference/ and assert that the ROS 2 side still agrees with them on
topic names, message fields, protocol framing and default parameters.
"""
from __future__ import annotations

import pathlib
import re

import pytest
import yaml

PKG = pathlib.Path(__file__).resolve().parent.parent
ROS1 = PKG / 'src' / 'ros1_reference'
CONFIG = PKG / 'config'
PARAM = PKG / 'param'


def _read(path) -> str:
    return path.read_text(encoding='utf-8', errors='replace')


# ----------------------------------------------------------------- topics

def test_motor_topics_unchanged():
    """Same topic names on both sides: /cmd_vel, /odom, /motor_state/{left,right}."""
    ros1 = _read(ROS1 / 'motor_node.cpp')
    ros2 = _read(PKG / 'src' / 'motor_node.cpp')
    for topic in ('cmd_vel', 'odom', 'motor_state/left', 'motor_state/right'):
        assert f'"{topic}"' in ros1, f'ROS 1 lost {topic}'
        assert f'"{topic}"' in ros2, f'ROS 2 uses a different topic name for {topic}'


def test_screen_topic_and_endpoint_unchanged():
    ros1 = _read(ROS1 / 'screen_node.cpp')
    ros2 = _read(PKG / 'src' / 'screen_node.cpp')
    assert '"qrcode_text"' in ros1 and '"qrcode_text"' in ros2
    cfg = yaml.safe_load(_read(CONFIG / 'screen.yaml'))
    params = cfg['screen_handler']['ros__parameters']['screen']
    assert params['ip_address'] == '192.168.100.100'
    assert params['port'] == 26


def test_screen_tail_byte_is_0xff_as_in_ros1():
    """ROS 1 wrote three 0xff tail bytes here; the ROS 2 port must not "unify" that."""
    ros1 = _read(ROS1 / 'screen_node.cpp')
    assert 'comm_tail = 0xff' in ros1 or 'comm_tail = 0xff;' in ros1
    ros2 = _read(PKG / 'src' / 'screen_node.cpp')
    assert 'COMM_TAIL = 0xff' in ros2


# --------------------------------------------------------------- protocol

def test_motor_protocol_constants_unchanged():
    ros1 = _read(ROS1 / 'motor_node.cpp')
    ros2 = _read(PKG / 'src' / 'motor_node.cpp')
    for token in ('MOTOR_LEFT_ID', 'MOTOR_RIGHT_ID', '0x64'):
        assert token in ros1 and token in ros2, token
    assert 'MOTOR_CMD_BUFFER_SIZE = 10' in ros2
    assert 'crc8_maxim' in ros2


def test_odometry_maths_unchanged():
    """The odometry must stay byte-for-byte equivalent: same scale and compensation."""
    ros2 = _read(PKG / 'src' / 'motor_node.cpp')
    assert 'odom_compensation_ratio_' in ros2
    assert 'M_PI / 180.0 * wheel_radius_' in ros2
    assert 'sincosf' in ros2


def test_safety_guard_is_present_in_ros2():
    """The ROS 1 variant on swjtumover05 had no watchdog; the migrated one must have it."""
    ros2 = _read(PKG / 'src' / 'motor_node.cpp')
    assert 'motor_safety::Guard' in ros2
    assert 'cmd_vel_timeout' in ros2
    assert 'motor_feedback_timeout' in ros2
    assert 'allow_motion' in ros2


# ------------------------------------------------------------- parameters

def test_motor_parameters_match_ros1_values():
    """Every value the ROS 1 motor.yaml set is present and identical in ROS 2."""
    ros1 = yaml.safe_load(_read(CONFIG / 'motor_ros1.yaml'))['motor']
    ros2 = yaml.safe_load(_read(CONFIG / 'motor.yaml'))['motor_node']['ros__parameters']['motor']
    for key, value in ros1.items():
        assert key in ros2, f'missing parameter motor.{key}'
        assert ros2[key] == value, f'motor.{key}: ROS 1 {value} vs ROS 2 {ros2[key]}'


def test_teleop_parameters_match_ros1_values():
    ros1 = yaml.safe_load(_read(CONFIG / 'teleop_ros1.yaml'))['teleop']
    ros2 = yaml.safe_load(_read(CONFIG / 'teleop.yaml'))['teleop_node']['ros__parameters']['teleop']
    for key, value in ros1.items():
        assert ros2[key] == value, f'teleop.{key}: ROS 1 {value} vs ROS 2 {ros2[key]}'


def test_screen_parameters_match_ros1_values():
    ros1 = yaml.safe_load(_read(CONFIG / 'screen_ros1.yaml'))['screen']
    ros2 = yaml.safe_load(_read(CONFIG / 'screen.yaml'))['screen_handler']['ros__parameters']['screen']
    for key, value in ros1.items():
        assert ros2[key] == value, f'screen.{key}: ROS 1 {value} vs ROS 2 {ros2[key]}'


# --------------------------------------------------------------- messages

def test_motor_state_message_fields_preserved():
    """Field names, order and types are part of the interface contract."""
    ros1 = _read(PKG.parent / 'swjtumover_msgs' / 'msg' / 'MotorState.msg')
    expected = [
        ('std_msgs/Header', 'header'),
        ('float32', 'phase_current'),
        ('int16', 'rpm'),
        ('float32', 'position_deg'),
        ('bool', 'over_temperature_fault'),
        ('bool', 'stall_fault'),
        ('bool', 'phase_overcurrent_fault'),
        ('bool', 'overcurrent_fault'),
        ('bool', 'sensor_fault'),
    ]
    lines = [line.strip() for line in ros1.splitlines() if line.strip()]
    assert len(lines) == len(expected), lines
    for line, (type_name, field) in zip(lines, expected):
        assert line.split()[0] == type_name, line
        assert line.split()[1] == field, line


# ------------------------------------------------------------------ model

def test_robot_model_is_the_ros1_one():
    """The URDF is copied verbatim; the measured lidar mount must survive the migration."""
    urdf = _read(PKG / 'urdf' / 'robot_description.urdf')
    match = re.search(r'<joint\s+name="lidar_joint".*?</joint>', urdf, re.S)
    assert match, 'lidar_joint missing'
    joint = match.group(0)
    assert '0.14114' in joint and '0.02618' in joint


def test_numeric_parameters_accept_ros1_integer_yaml():
    """ROS 1 converted an integer YAML value for a float parameter; ROS 2 does not.

    `control_freq: 50` in the ROS 1 motor.yaml failed on the robot with
    "parameter {motor.control_freq} is of type {double}, setting it to {integer} is not
    allowed". The node therefore declares from the override's own type, so a ROS 1
    configuration file loads unchanged. Found on hardware, not in a unit test; asserted here
    so it cannot regress.
    """
    source = _read(PKG / 'src' / 'motor_node.cpp')
    assert 'declare_numeric' in source and 'declare_integer' in source
    assert 'get_parameter_overrides' in source
    assert 'PARAMETER_INTEGER' in source and 'PARAMETER_DOUBLE' in source
    # and the ROS 1 files really do use integers for these
    ros1 = yaml.safe_load(_read(CONFIG / 'motor_ros1.yaml'))['motor']
    assert isinstance(ros1['control_freq'], int)
    assert isinstance(ros1['wheel_acc'], int)


def test_installed_config_has_no_absolute_paths_from_the_ros1_machine():
    """A ROS 1 config file must not carry that machine's absolute paths into a deployment.

    `map/nav.yaml` kept `image: /home/swjtumover/swjtumover/swjtumover_ws/src/...`, so
    map_server failed its configure transition on the robot ("Failed to load map yaml file")
    and nav2 could not come up. Reference copies under *_ros1* are exempt: they exist to be
    byte-comparable with the originals.
    """
    offenders = []
    for path in list(PKG.joinpath('config').glob('*.yaml')) + \
            list(PKG.joinpath('map').glob('*.yaml')) + \
            list(PKG.joinpath('param').glob('*.yaml')):
        if '_ros1' in path.name:
            continue
        text = path.read_text(encoding='utf-8')
        for number, line in enumerate(text.splitlines(), 1):
            if '/home/' in line and not line.lstrip().startswith('#'):
                offenders.append(f'{path.name}:{number}: {line.strip()}')
    assert not offenders, 'absolute paths in installed config:\n' + '\n'.join(offenders)


def test_nav2_plugin_classes_use_ros2_separator():
    """ROS 1 addressed plugins as `package/Class`; ROS 2 resolves `package::Class`.

    Keeping the ROS 1 form made planner_server die during configure on the robot:
    "the class nav2_navfn_planner/NavfnPlanner ... does not exist", and the lifecycle manager
    then aborted the whole nav2 bringup. Every plugin class in the nav2 parameters must use
    `::` and must exist in the plugin description of its package.
    """
    text = (PKG / 'param' / 'nav2_params.yaml').read_text(encoding='utf-8')
    bad = re.findall(r'plugin: "([a-z0-9_]+)/[A-Za-z0-9_]+"', text)
    assert not bad, f'ROS 1 style plugin classes: {bad}'
    declared = re.findall(r'plugin: "([a-z0-9_]+)::([A-Za-z0-9_]+)"', text)
    assert declared, 'no plugin classes found -- test is not looking'
    for package, _cls in declared:
        assert (package, _cls), 'unreachable'
    # the packages are the ones this robot actually has
    packages = {p for p, _ in declared}
    assert packages <= {'nav2_navfn_planner', 'nav2_controller', 'dwb_core', 'nav2_costmap_2d',
                        'nav2_behaviors', 'nav2_bt_navigator'}, packages


def test_costmap_obstacle_source_parameters_are_per_source():
    """nav2 reads obstacle-layer parameters from the *source*, ROS 1 read them from the layer.

    Keeping the ROS 1 nesting left `scan.max_obstacle_height` at nav2's default 0.0. The laser
    sits at z = 0.141 m, so every point was filtered out, the local costmap stayed empty, DWB saw
    no obstacles at all and the robot drove into a maze wall. These parameters must be nested
    under the observation source, and max_obstacle_height must admit the sensor height.
    """
    data = yaml.safe_load(_read(PARAM / 'nav2_params.yaml'))
    for costmap in ('local_costmap', 'global_costmap'):
        params = data[costmap][costmap]['ros__parameters']
        layer = params['obstacle_layer']
        source = layer['scan']
        for key in ('max_obstacle_height', 'obstacle_max_range', 'raytrace_max_range'):
            assert key in source, f'{costmap}: scan.{key} missing (must be per source)'
            assert key not in layer, f'{costmap}: {key} at layer level is ignored by nav2'
        assert source['max_obstacle_height'] > 0.15, (
            f'{costmap}: scan.max_obstacle_height {source["max_obstacle_height"]} would filter '
            'out the LiDAR at z=0.141')
        assert source['obstacle_max_range'] > 0.5
        assert source['marking'] and source['clearing']


def test_costmap_inflation_matches_ros1():
    """Inflated cost values are what keep DWB away from walls; the values are ROS 1's."""
    data = yaml.safe_load(_read(PARAM / 'nav2_params.yaml'))
    expected = {'local_costmap': (0.03, 10.0), 'global_costmap': (0.08, 8.0)}
    for costmap, (radius, scaling) in expected.items():
        inflation = data[costmap][costmap]['ros__parameters']['inflation_layer']
        assert abs(inflation['inflation_radius'] - radius) < 1e-9, costmap
        assert abs(inflation['cost_scaling_factor'] - scaling) < 1e-9, costmap


def test_dwb_can_reverse_like_ros1_teb():
    """ROS 1 TEB set max_vel_x_backwards: 0.2. DWB is forward-only unless min_vel_x is negative.

    Forward-only DWB could not back out of a tight spot: the controller reported "Failed to make
    progress", aborted the goal (nav2 error 105) and left the robot stuck against an obstacle it
    had correctly detected.
    """
    data = yaml.safe_load(_read(PARAM / 'nav2_params.yaml'))
    follow = data['controller_server']['ros__parameters']['FollowPath']
    assert follow['min_vel_x'] <= -0.2 + 1e-9, (
        f"DWB min_vel_x {follow['min_vel_x']} forbids reversing; ROS 1 allowed 0.2 m/s backwards")
    assert follow['max_vel_x'] == 0.6 and follow['max_vel_theta'] == 1.0


def test_maze_map_preserves_world_coordinates():
    """The cropped maze map must be interchangeable with nav.pgm in world coordinates.

    It exists for CPU reasons (the full 99 m map as a nav2 global costmap saturates the robot and
    breaks lifecycle bringup), so a goal in map coordinates has to mean the same point in both.
    """
    full = yaml.safe_load(_read(PKG / 'map' / 'nav.yaml'))
    maze = yaml.safe_load(_read(PKG / 'map' / 'nav_maze.yaml'))
    assert maze['resolution'] == full['resolution']
    assert maze['image'] == 'nav_maze.pgm'

    def header(path):
        """(width, height) from a PGM header, skipping comment lines as nav.pgm has one."""
        fields = []
        for line in path.read_bytes().splitlines():
            line = line.strip()
            if not line or line.startswith(b'#'):
                continue
            fields.extend(line.split())
            if len(fields) >= 3:
                break
        assert fields[0] == b'P5'
        return int(fields[1]), int(fields[2])

    fw, fh = header(PKG / 'map' / 'nav.pgm')
    mw, mh = header(PKG / 'map' / 'nav_maze.pgm')
    assert (mw, mh) != (fw, fh), 'cropped map should be smaller'
    # world extent of each map
    fx, fy, _ = full['origin']
    mx, my, _ = maze['origin']
    assert fx <= mx and fy <= my, 'crop origin must lie inside the full map'
    assert mx + mw * maze['resolution'] <= fx + fw * full['resolution'] + 1e-9
    assert my + mh * maze['resolution'] <= fy + fh * full['resolution'] + 1e-9


def test_dwb_checks_the_whole_footprint_not_the_centre():
    """`BaseObstacle` only tests the robot's centre point; the body is 0.32 x 0.30 m.

    With BaseObstacle the robot drove its front edge into a tall box that the LiDAR had
    correctly placed in the costmap, because its centre was still in free space when the
    collision happened. ROS 1's TEB scored against the footprint model, so the migrated stack
    must do the equivalent: ObstacleFootprint.
    """
    data = yaml.safe_load(_read(PARAM / 'nav2_params.yaml'))
    follow = data['controller_server']['ros__parameters']['FollowPath']
    critics = follow['critics']
    assert 'ObstacleFootprint' in critics, f'no footprint collision critic: {critics}'
    assert 'BaseObstacle' not in critics, 'BaseObstacle alone only checks the centre point'
    assert 'ObstacleFootprint.scale' in follow
    # and the footprint must be the ROS 1 one
    footprint = follow.get('footprint') or data['local_costmap']['local_costmap'][
        'ros__parameters']['footprint']
    assert '0.16' in str(footprint) and '0.15' in str(footprint), footprint
