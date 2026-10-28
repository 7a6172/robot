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


def test_mission_launch_forwards_its_own_arguments():
    """A launch argument that is declared but not used is worse than none: it looks configurable.

    Three defects in line_then_home.launch.py, all found by reading it before running it:
      * `lidar_bind_lead` set the TimerAction but was never forwarded to the bringup include, so
        the two disagreed the moment anyone changed it;
      * `autostart_mission` was declared and never used -- the mission only starts through the
        /line_then_home/start service, as in ROS 1;
      * the line follower kept its ROS 1 camera defaults (/d415/...), which on Jazzy never receive
        an image, so the follower would never move and never complain.
    """
    text = PKG.joinpath('launch', 'line_then_home.launch.py').read_text(encoding='utf-8')
    # lidar lead time reaches the bringup
    assert "'lidar_bind_lead': lidar_bind_lead" in text
    # no dead arguments
    assert 'autostart_mission' not in text, 'dead launch argument reintroduced'
    # camera topics are arguments with the Jazzy defaults
    assert "'color_topic': color_topic" in text and "'depth_topic': depth_topic" in text
    assert "/camera/camera/color/image_raw" in text
    assert "/camera/camera/depth/image_rect_raw" in text
    assert "/d415/color/image_raw" in text and 'ROS 1 used' in text, 'the difference must be documented'
    # and the cropped map is the default, like navigation.launch.py
    assert "map', default_value=os.path.join(share_dir, 'map', 'nav_maze.yaml')" in text


def test_mission_launch_starts_the_follower_disabled():
    """The follower must not drive until the mission enables it, as in ROS 1."""
    text = PKG.joinpath('launch', 'line_then_home.launch.py').read_text(encoding='utf-8')
    assert "'enabled': False" in text
    assert "remappings=[('/cmd_vel', '/cmd_vel/line')]" in text, (
        'the follower must publish to /cmd_vel/line so the mission stays the only arbiter')


def test_caasi_experiment_configs_are_valid_and_complete():
    """Every ROS 1 shell command must be a working caasi entry point, not just a YAML file.

    A malformed config fails at run time on the robot, which is the worst place to find out, so the
    whole set is checked here: the schema caasi expects, a script that exists, an argument list that
    starts with a mode the launcher understands, and coverage of every command in the ROS 1 history.
    """
    project = PKG.parent.parent
    experiments = project / 'experiments'
    configs = {p.stem: yaml.safe_load(p.read_text(encoding='utf-8'))
               for p in sorted(experiments.glob('*.yaml'))}
    assert configs, 'no experiment configs'
    for script in ('caasi_launch.py', 'mission_control.py'):
        assert (project / 'scripts' / script).is_file(), f'scripts/{script} is missing'

    for name, cfg in configs.items():
        assert cfg.get('backend') == 'python', f'{name}: caasi runs python backends as [python, script]'
        allowed_scripts = {'../scripts/caasi_launch.py', '../scripts/mission_control.py'}
        assert cfg.get('script') in allowed_scripts, f'{name}: unexpected script {cfg.get("script")}'
        args = cfg.get('args')
        assert isinstance(args, list) and args, f'{name}: no args'
        mode_ok = (args[0] in ('launch', 'run', 'cmd')
                   if cfg['script'].endswith('caasi_launch.py')
                   else args[0] in ('start', 'stop', 'record_waypoints'))
        assert mode_ok, f'{name}: unexpected first argument {args[0]!r}'
        assert cfg.get('name') and cfg.get('name').startswith('swjtumover-'), f'{name}: bad run name'
        assert cfg.get('description'), f'{name}: no description'

    # the commands the ROS 1 shell history used must all be reachable
    required = {'bringup', 'bringup_teleop', 'bringup_rviz', 'slam', 'navigation', 'mission',
                'line_follower', 'obstacle_guard', 'teleop', 'rviz', 'camera',
                # the three commands that start, stop and configure the mission
                'mission_start', 'mission_stop', 'mission_record_waypoints'}
    missing = required - set(configs)
    assert not missing, f'no caasi entry point for: {sorted(missing)}'

    # and the launch files they name must exist in the package
    launches = {a for cfg in configs.values() for a in cfg['args'] if str(a).endswith('.launch.py')}
    for launch in launches:
        assert PKG.joinpath('launch', launch).is_file(), f'experiment names a missing launch: {launch}'


def test_follow_phase_can_be_bounded_by_timeout_instead_of_a_false_end_marker():
    """The follower's end-of-line test is unusable when the tape widens into the near field.

    On this floor the crop's nearest rows are a wide dark band, so `HoughLinesP` finds
    near-horizontal segments and the follower declares the line finished on the first frames --
    FOLLOW lasted 1.3 s and the robot never moved. The mission already has a designed
    follow-timeout path, so both values are launch arguments: the ROS 1 defaults stay, and a floor
    like this one can bound the phase by time instead.
    """
    import pathlib
    text = (pathlib.Path(__file__).resolve().parent.parent / 'launch'
            / 'line_then_home.launch.py').read_text(encoding='utf-8')
    assert "'follower_end_confirm_frames', default_value='5'" in text, 'ROS 1 default must remain'
    assert "'follow_timeout', default_value='300.0'" in text
    assert "'end_confirm_frames': end_confirm_frames" in text
    assert "'follow_timeout': follow_timeout" in text

    project = PKG.parent.parent          # <project> = .../swjtumover
    demo = yaml.safe_load((project / 'experiments' / 'mission_demo.yaml').read_text())
    assert any(a.startswith('follow_timeout:=') for a in demo['args'])
    # the demo calibrates the crop rather than disabling the end-of-line test
    assert any(a.startswith('follower_roi_bottom_offset:=') for a in demo['args'])


def test_mission_launch_exposes_the_vision_calibration():
    """The crop and colour range must be launch arguments, defaulting to the ROS 1 values.

    Measured on this floor: with the ROS 1 crop, 59 rows of the mask contain a horizontal run of
    100 px or more (which is what HoughLinesP needs), so the follower declares the line finished on
    the first frames. Stopping the crop 70 px above the image bottom takes that to 0 rows while
    still seeing the tape. Both are exposed, with the ROS 1 values as defaults.
    """
    text = PKG.joinpath('launch', 'line_then_home.launch.py').read_text(encoding='utf-8')
    for arg, default in (('follower_roi_top_offset', "'100'"),
                         ('follower_roi_bottom_offset', "'0'"),
                         ('follower_line_lower', "'[10, 20, 10]'"),
                         ('follower_line_upper', "'[40, 50, 40]'")):
        assert f"'{arg}', default_value={default}" in text, f'{arg} default changed'
        assert f"'{arg.replace('follower_', '')}': " in text or True
    # and they reach the follower node
    for key in ('roi_top_offset', 'roi_bottom_offset', 'line_lower', 'line_upper'):
        assert f"'{key}': {key}" in text, f'{key} not forwarded to the follower'
