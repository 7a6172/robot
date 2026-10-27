"""What the migrated bringup actually launches, evaluated from the real launch description.

The ROS 1 file hardcoded rviz on; this one makes the optional components arguments. These
tests walk the launch description the way the launch service does (conditions, OpaqueFunctions,
TimerAction) and assert the resulting node set, without starting any process.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

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
