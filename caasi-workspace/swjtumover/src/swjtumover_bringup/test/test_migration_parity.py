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
