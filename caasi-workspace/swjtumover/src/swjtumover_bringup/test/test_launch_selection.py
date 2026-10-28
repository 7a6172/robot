"""What the migrated bringup actually launches, evaluated from the real launch description.

The ROS 1 file hardcoded rviz on; this one makes the optional components arguments. These
tests walk the launch description the way the launch service does (conditions, OpaqueFunctions,
TimerAction) and assert the resulting node set, without starting any process.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re

import yaml

import pytest

PROJECT = pathlib.Path(__file__).resolve().parents[3]
PKG = pathlib.Path(__file__).resolve().parent.parent
LAUNCH_FILE = PKG / 'launch' / 'bringup.launch.py'


def _load():
    import ament_index_python.packages as aip
    original = aip.get_package_share_directory
    aip.get_package_share_directory = lambda name: str(PKG) if name == 'swjtumover_bringup' else original(name)
    try:
        spec = importlib.util.spec_from_file_location('swjtumover_bringup_launch', LAUNCH_FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        aip.get_package_share_directory = original


def _perform(value, context):
    if isinstance(value, (list, tuple)):
        return ''.join(_perform(v, context) for v in value)
    if hasattr(value, 'perform'):
        return value.perform(context)
    if type(value).__name__ == 'ParameterFile':
        return _perform(value.param_file, context)
    return value


def selected(**launch_args):
    from launch import LaunchContext
    from launch.actions import DeclareLaunchArgument, OpaqueFunction

    module = _load()
    context = LaunchContext()
    description = module.generate_launch_description()
    configs = {}
    for entity in description.entities:
        if isinstance(entity, DeclareLaunchArgument) and entity.default_value:
            configs[entity.name] = _perform(entity.default_value, context)
    configs.update({k: str(v) for k, v in launch_args.items()})
    context._LaunchContext__launch_configurations = configs

    found = []

    def visit(entity):
        condition = getattr(entity, 'condition', None)
        if condition is not None and not condition.evaluate(context):
            return
        if isinstance(entity, OpaqueFunction):
            for produced in entity.execute(context):
                visit(produced)
            return
        nested = getattr(entity, 'actions', None)
        if isinstance(nested, (list, tuple)):
            for child in nested:
                visit(child)
            return
        inner = getattr(entity, 'entities', None)
        if isinstance(inner, list) and hasattr(entity, 'visit'):
            for child in inner:
                visit(child)
            return
        if hasattr(entity, 'node_executable'):
            found.append(_perform(entity.node_executable, context))

    for entity in description.entities:
        visit(entity)
    return found


def test_default_launch_is_headless_and_safe():
    """Nothing optional runs by default: no rviz, no teleop, no camera."""
    names = selected()
    assert 'vanjee_scan_node' in names
    assert 'motor_node' in names
    assert 'screen_node' in names
    assert 'rviz2' not in names
    assert 'teleop_node.py' not in names
    assert 'realsense2_camera_node' not in names


def test_optional_components_start_only_when_asked():
    names = selected(enable_teleop='true', enable_visualization='true', enable_realsense='true')
    assert 'teleop_node.py' in names
    assert 'rviz2' in names
    assert 'realsense2_camera_node' in names


def test_lidar_starts_before_everything_else():
    """The driver must own UDP 7000 before any other ROS 2 node binds it."""
    from launch import LaunchContext
    from launch.actions import DeclareLaunchArgument, OpaqueFunction

    module = _load()
    context = LaunchContext()
    description = module.generate_launch_description()
    configs = {}
    for entity in description.entities:
        if isinstance(entity, DeclareLaunchArgument) and entity.default_value:
            configs[entity.name] = _perform(entity.default_value, context)
    context._LaunchContext__launch_configurations = configs

    first_node = None
    for entity in description.entities:
        if isinstance(entity, (DeclareLaunchArgument, OpaqueFunction)):
            continue
        first_node = entity
        break
    assert first_node is not None
    assert _perform(first_node.node_executable, context) == 'vanjee_scan_node'


def test_actuation_relevant_nodes_are_respawned_not_silently_dropped():
    """motor_node and screen_node were respawn="true" in ROS 1; that must not change."""
    module = _load()
    from launch import LaunchContext
    from launch.actions import DeclareLaunchArgument

    context = LaunchContext()
    description = module.generate_launch_description()
    configs = {}
    for entity in description.entities:
        if isinstance(entity, DeclareLaunchArgument) and entity.default_value:
            configs[entity.name] = _perform(entity.default_value, context)
    context._LaunchContext__launch_configurations = configs

    respawn = {}

    def visit(entity):
        condition = getattr(entity, 'condition', None)
        if condition is not None and not condition.evaluate(context):
            return
        from launch.actions import OpaqueFunction
        if isinstance(entity, OpaqueFunction):
            for produced in entity.execute(context):
                visit(produced)
            return
        nested = getattr(entity, 'actions', None)
        if isinstance(nested, (list, tuple)):
            for child in nested:
                visit(child)
            return
        if hasattr(entity, 'node_executable'):
            # launch_ros stores this on ExecuteLocal in this distribution, so resolve it by
            # name rather than assuming one private attribute spelling.
            respawn[_perform(entity.node_executable, context)] = bool(
                getattr(entity, '_ExecuteLocal__respawn',
                        getattr(entity, '_Node__respawn', False)))

    for entity in description.entities:
        visit(entity)
    assert respawn.get('motor_node') is True
    assert respawn.get('screen_node') is True


# Every YAML a launch passes as `parameters=` must be a ROS 2 parameter file. The ROS 1 vendor
# schema (`common:` / `lidar:` with no `ros__parameters`) is NOT one, and feeding it to a node
# fails at startup with "Cannot have a value before ros__parameters". That happened on the robot
# with bringup.launch.py handing config/lidar.yaml to the LiDAR adapter, which crashed, respawned,
# and left the UDP 7000 port to whoever started next. Static checks missed it; this does not.

_LAUNCH_PARAM_DIRS = {
    'config_dir': 'swjtumover_bringup/config',          # this package
    'vanjee_config_dir': 'swjtumover_vanjee/config',    # the LiDAR adapter's own file
}


def _launch_parameter_files():
    """(launch file, referenced path, yaml file) for every YAML a launch passes as parameters."""
    found = []
    for launch in sorted(PKG.joinpath('launch').glob('*.launch.py')):
        text = launch.read_text(encoding='utf-8')
        for block in re.findall(r'parameters=\[(.*?)\]', text, re.S):
            for var, name in re.findall(r"os\.path\.join\((\w+),\s*'([^']+\.yaml)'\)", block):
                assert var in _LAUNCH_PARAM_DIRS, (
                    f'{launch.name}: unknown parameter directory variable {var!r}; '
                    'add it to _LAUNCH_PARAM_DIRS so this test can check the file')
                found.append((launch.name, var, name))
    return found


def test_launch_parameter_files_are_ros2_parameter_files():
    referenced = _launch_parameter_files()
    assert referenced, 'no YAML parameters found in any launch file -- test is not looking'
    problems = []
    for launch_name, var, name in referenced:
        relative = _LAUNCH_PARAM_DIRS[var]
        package, _, _ = relative.partition('/')
        path = PROJECT / 'src' / package / 'config' / name
        assert path.is_file(), f'{launch_name} references a missing file: {path}'
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or not data:
            problems.append(f'{launch_name} -> {path.name}: not a mapping')
            continue
        if not any(isinstance(v, dict) and 'ros__parameters' in v for v in data.values()):
            problems.append(
                f'{launch_name} -> {path.name}: no ros__parameters (ROS 1 schema cannot be '
                'passed to a ROS 2 node)')
    assert not problems, '\n'.join(problems)


def test_lifecycle_nodes_are_managed():
    """A lifecycle node left unconfigured publishes nothing, and the launch looks healthy.

    `sync_slam_toolbox_node` is a lifecycle node while ROS 1's gmapping was not, so the launch
    has to configure and activate it. Found on the robot: slam_toolbox was running, but
    `ros2 node info /slam_toolbox` showed no `/scan` subscription and no `/map` publisher until
    `ros2 lifecycle set ... configure/activate` was issued by hand.
    """
    lifecycle_managed = {
        'slam.launch.py': ['slam_toolbox'],
    }
    for name, required in lifecycle_managed.items():
        text = PKG.joinpath('launch', name).read_text(encoding='utf-8')
        assert 'nav2_lifecycle_manager' in text, f'{name}: no lifecycle manager'
        assert 'autostart' in text, f'{name}: lifecycle manager does not autostart'
        for node in required:
            assert f"'{node}'" in text, f'{name}: {node} not in the manager\'s node_names'
        # the manager must be started, not merely constructed
        assert 'lifecycle_manager' in text.split('return LaunchDescription')[-1], (
            f'{name}: the lifecycle manager is constructed but never added to the description')


def test_cmd_vel_chain_reaches_the_final_topic():
    """controller_server -> velocity_smoother -> cmd_vel_topic must be a connected chain.

    The controller originally published straight to the final topic, so the smoother (which
    subscribes `cmd_vel_nav_raw`) never received anything and no command reached the wheels.
    nav2 logged normal path handoffs while odometry stayed at zero -- a silent standstill.
    """
    text = PKG.joinpath('launch', 'navigation.launch.py').read_text(encoding='utf-8')
    # controller output topic
    assert "remappings=[('cmd_vel', 'cmd_vel_nav_raw')]" in text, \
        'controller_server must publish to cmd_vel_nav_raw'
    # smoother input and output
    assert "('cmd_vel', 'cmd_vel_nav_raw')" in text, 'velocity_smoother must consume cmd_vel_nav_raw'
    assert "('cmd_vel_smoothed', cmd_vel_topic)" in text, \
        'velocity_smoother must publish to the configured cmd_vel_topic'
    # and the arbitration contract with the task scripts
    mission = PKG.joinpath('scripts', 'line_then_home.py').read_text(encoding='utf-8')
    assert "'/cmd_vel/nav'" in mission, 'the mission node must forward /cmd_vel/nav'
    assert "default_value='/cmd_vel/nav'" in text, 'default cmd_vel_topic must stay /cmd_vel/nav'
