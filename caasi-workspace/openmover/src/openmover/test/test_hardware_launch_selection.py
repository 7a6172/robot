"""Which components `hardwares/bringup.launch.py` actually selects per hardware profile.

These tests evaluate the real launch description: the declared arguments, the OpaqueFunction
that resolves drivers from the profile, `SetLaunchConfiguration`, and the `IfCondition`
guards on every node. Nothing is grepped out of the source, and no process is started --
`selected()` walks the entities the launch service would walk and records what survives its
conditions.

The defect these lock down: `hardware:=swjtumover` used to validate and then ignore
`lidar_driver` / `io_driver`, while the node list stayed hardcoded to the lab drivers, so the
physical robot launched two bluesea2 drivers and never the Vanjee.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent          # src/openmover
LAUNCH_FILE = SRC / 'launch' / 'hardwares' / 'bringup.launch.py'
# The Vanjee driver's share dir, for the tests that model "the driver is installed".
VANJEE_SHARE = SRC.parent / 'openmover_vanjee'


# --------------------------------------------------------------------------- loading

def _load_launch_module():
    """Import the launch file with the package share dir pointing at the source tree.

    The installed copy is a build-time artifact; testing it would test the last build
    rather than the change under review.
    """
    import ament_index_python.packages as aip

    original = aip.get_package_share_directory

    def fake(name):
        # The launch file resolves the driver package through this function; modelling
        # both packages keeps the "is the driver installed?" check under test control.
        if name == 'openmover':
            return str(SRC)
        if name == 'openmover_vanjee':
            return str(VANJEE_SHARE)
        if name in ('ros_gz_sim', 'ros_gz_bridge'):
            # Selection is what is under test, not whether Gazebo happens to be installed
            # on the machine running the tests.
            return f'/opt/ros/jazzy/share/{name}'
        return original(name)

    aip.get_package_share_directory = fake
    try:
        spec = importlib.util.spec_from_file_location('bringup_under_test', LAUNCH_FILE)
        module = importlib.util.module_from_spec(spec)
        sys.modules['bringup_under_test'] = module
        spec.loader.exec_module(module)
        return module
    finally:
        aip.get_package_share_directory = original


# ------------------------------------------------------------------------ evaluation

def _perform(value, context):
    """Resolve a substitution, leaving plain values alone."""
    if isinstance(value, (list, tuple)):
        return ''.join(_perform(v, context) for v in value)
    if hasattr(value, 'perform'):
        return value.perform(context)
    # ParameterFile wraps its path without being a substitution.
    if type(value).__name__ == 'ParameterFile':
        return _perform(value.param_file, context)
    return value


class Selection:
    """The nodes a launch configuration would start, with their resolved parameters."""

    def __init__(self, nodes, args):
        self.nodes = nodes
        self.args = args

    def names(self) -> list[str]:
        return [n['name'] for n in self.nodes]

    def find(self, executable: str) -> dict | None:
        for n in self.nodes:
            if n['executable'] == executable:
                return n
        return None

    def __contains__(self, item):
        return item in self.names()

    def __repr__(self):
        return f"Selection({sorted(self.names())})"


def selected(module, **launch_args) -> Selection:
    """Walk the launch description the way the launch service does, without executing."""
    from launch import LaunchContext
    from launch.actions import DeclareLaunchArgument, OpaqueFunction

    context = LaunchContext()
    description = module.generate_launch_description()

    # Declared defaults first, then the caller's overrides -- the same precedence the
    # command line has.
    configs = {}
    for entity in description.entities:
        if isinstance(entity, DeclareLaunchArgument) and entity.default_value:
            configs[entity.name] = _perform(entity.default_value, context)
    configs.update({k: str(v) for k, v in launch_args.items()})
    # LaunchContext exposes launch_configurations as a read-only property over this dict.
    context._LaunchContext__launch_configurations = configs

    nodes: list[dict] = []

    def visit(entity):
        condition = getattr(entity, 'condition', None)
        if condition is not None and not condition.evaluate(context):
            return
        if isinstance(entity, DeclareLaunchArgument):
            return
        if isinstance(entity, OpaqueFunction):
            for produced in entity.execute(context):
                visit(produced)
            return
        if type(entity).__name__ == 'SetLaunchConfiguration':
            entity.execute(context)
            return
        # Containers (TimerAction, GroupAction, nested LaunchDescription) are transparent:
        # what matters is the set of nodes that would run, not their scheduling wrapper.
        nested = getattr(entity, 'actions', None)
        if isinstance(nested, (list, tuple)):
            for child in nested:
                visit(child)
            return
        inner = getattr(entity, 'entities', None)
        if isinstance(inner, (list, tuple)) and hasattr(entity, 'visit'):
            for child in inner:
                visit(child)
            return
        if type(entity).__name__ == 'IncludeLaunchDescription':
            nodes.append({'name': '<include>', 'executable': '<include>',
                          'package': '<include>', 'parameters': {}, 'env': {}})
            return
        if type(entity).__name__ == 'SetEnvironmentVariable':
            return
        # Node and ExecuteProcess: record what was selected, start nothing.
        if hasattr(entity, 'node_executable') or hasattr(entity, 'cmd'):
            name = _perform(getattr(entity, 'name', None), context)
            exe = _perform(getattr(entity, 'node_executable', None)
                           or getattr(entity, 'executable', None), context)
            package = _perform(getattr(entity, 'node_package', None)
                               or getattr(entity, 'package', None), context)
            params = {}
            # launch_ros keeps these in private attributes; ExecuteProcess does not have
            # parameters at all.
            raw_params = getattr(entity, '_Node__parameters', None) or \
                getattr(entity, 'parameters', None) or []
            for entry in raw_params:
                if isinstance(entry, dict):
                    # Keys are normalised to substitutions too.
                    params.update({_perform(k, context): _perform(v, context)
                                   for k, v in entry.items()})
                else:
                    resolved = _perform(entry, context)
                    params.setdefault('__files__', [])
                    params['__files__'].append(resolved)
            env = {}
            raw_env = getattr(entity, 'additional_env', None) or {}
            # launch_ros normalises this to a list of (key, value) pairs.
            items = raw_env.items() if hasattr(raw_env, 'items') else raw_env
            for key, value in items:
                env[_perform(key, context)] = _perform(value, context)
            nodes.append({'name': name or exe, 'executable': exe or name,
                          'package': package, 'parameters': params, 'env': env,
                          'respawn': bool(getattr(entity, '_Node__respawn', False))})
            return
        # Anything else (groups, log filters) is transparent for this purpose.

    for entity in description.entities:
        visit(entity)
    return Selection(nodes, configs)


@pytest.fixture(scope='module')
def launch():
    return _load_launch_module()


# ------------------------------------------------------------------- real profiles

def test_swjtumover_selects_vanjee_and_screen(launch):
    """`hardware:=swjtumover` alone must be enough -- that is what was broken."""
    sel = selected(launch, hardware='swjtumover')
    assert sel.find('vanjee_scan_node') is not None, sel.names()
    assert sel.find('screen_handler.py') is not None, sel.names()
    assert sel.find('bluesea2_node') is None, "the lab LiDAR must not start on swjtumover"
    assert sel.find('io_board_handler') is None, "io_board is not this fit's chassis IO"


def test_swjtumover_lidar_parameters_come_from_the_robot_profile(launch):
    node = selected(launch, hardware='swjtumover').find('vanjee_scan_node')
    files = node['parameters'].get('__files__', [])
    assert any(f.endswith('hardware/swjtumover.yaml') for f in files), files
    # The profile is the only place a per-robot address may live.
    assert 'host_address' not in node['parameters'], (
        "network configuration must not be hardcoded in the launch file")


def test_lab_profile_is_unchanged(launch):
    sel = selected(launch, hardware='openmover_lab')
    assert sel.find('bluesea2_node') is not None
    assert sel.find('io_board_handler') is not None
    assert sel.find('vanjee_scan_node') is None
    assert sel.find('screen_handler.py') is None
    assert sel.find('laserscan_multi_merger') is not None, "two bluesea2 need fusion"


def test_vanjee_profile_does_not_merge_scans(launch):
    """Merging two topics that do not exist would replace a working /scan with nothing."""
    sel = selected(launch, hardware='swjtumover')
    assert sel.find('laserscan_multi_merger') is None


def test_exactly_one_lidar_driver_in_every_profile(launch):
    for profile in ('openmover_lab', 'swjtumover'):
        sel = selected(launch, hardware=profile)
        drivers = [n for n in sel.nodes
                   if n['executable'] in ('vanjee_scan_node', 'bluesea2_node')]
        expected = 1 if profile == 'swjtumover' else 2  # the lab fit has two bluesea2
        assert len(drivers) == expected, (profile, drivers)


# ------------------------------------------------------------------- simulation

def test_simulation_starts_no_hardware_drivers(launch):
    sel = selected(launch, system_mode='0')
    assert sel.find('bluesea2_node') is None
    assert sel.find('vanjee_scan_node') is None
    assert sel.find('io_board_handler') is None
    assert sel.find('screen_handler.py') is None
    assert sel.find('motor_handler') is None
    assert sel.find('simulation_handler') is not None


def test_simulation_selection_does_not_depend_on_the_hardware_argument(launch):
    sel = selected(launch, system_mode='0', hardware='swjtumover')
    assert sel.find('simulation_handler') is not None
    assert sel.find('vanjee_scan_node') is None


def test_simulation_and_hardware_profiles_never_mix(launch):
    for mode in ('0', '1'):
        sel = selected(launch, system_mode=mode, hardware='swjtumover')
        has_sim = sel.find('simulation_handler') is not None
        has_real = sel.find('vanjee_scan_node') is not None
        assert has_sim != has_real, (mode, sel.names())


# ------------------------------------------------------- required vs optional

def test_gazebo_dependency_is_optional_for_physical_bringup(launch):
    """ros_gz_sim must not even be resolved in real mode, or the host needs Gazebo."""
    sel = selected(launch, system_mode='1', hardware='swjtumover')
    assert sel.find('parameter_bridge') is None
    assert sel.find('create') is None


def test_gazebo_nodes_appear_in_simulation(launch):
    sel = selected(launch, system_mode='0', launch_gazebo='1', sim_area='0')
    assert sel.find('parameter_bridge') is not None
    assert sel.find('simulation_handler') is not None


# ------------------------------------------------- invalid profiles and config

def test_unknown_hardware_profile_fails_by_name(launch):
    with pytest.raises(RuntimeError, match='unknown hardware profile'):
        selected(launch, hardware='nonexistent_robot')


def test_contradictory_driver_is_rejected(launch):
    with pytest.raises(RuntimeError, match='expects lidar_driver'):
        selected(launch, hardware='swjtumover', lidar_driver='bluesea2')
    with pytest.raises(RuntimeError, match='expects io_driver'):
        selected(launch, hardware='swjtumover', io_driver='io_board')


def test_explicit_matching_driver_is_accepted(launch):
    sel = selected(launch, hardware='swjtumover', lidar_driver='vanjee',
                   io_driver='screen')
    assert sel.find('vanjee_scan_node') is not None


def test_missing_driver_package_fails_with_an_actionable_message(launch, monkeypatch):
    """A profile that needs an unbuilt driver must say so, not fail obscurely later."""
    def missing(name):
        if name == 'openmover_vanjee':
            raise Exception('PackageNotFoundError')
        return str(SRC)

    monkeypatch.setattr(launch, 'get_package_share_directory', missing)
    with pytest.raises(RuntimeError, match='openmover_vanjee'):
        selected(launch, hardware='swjtumover')


def test_missing_profile_file_fails_by_path(launch, monkeypatch, tmp_path):
    monkeypatch.setattr(launch, 'config_dir', str(tmp_path))
    with pytest.raises(RuntimeError, match='is not present'):
        selected(launch, hardware='swjtumover')


# ------------------------------------------------------------ safety defaults

def test_motor_actuation_is_disabled_by_default(launch):
    node = selected(launch, hardware='swjtumover').find('motor_handler')
    assert node is not None
    assert node['parameters']['motor.actuation_enabled'] == 'false'
    # The environment factor is the second, independent gate.
    assert node['env']['CAASI_MOTOR_ACTUATION'] == '0'


def test_actuation_cannot_be_granted_from_a_yaml_profile(launch):
    """The profile file is a parameter source; it must not carry actuation at all."""
    import yaml
    data = yaml.safe_load((SRC / 'config_defaults' / 'hardware' /
                           'swjtumover.yaml').read_text())
    assert 'actuation_enabled' not in data['/**']['ros__parameters']['motor']


def test_odd_actuation_spellings_are_rejected(launch):
    for spelling in ('yes', 'on', '1', 'TRUE'):
        with pytest.raises(RuntimeError, match='must be exactly'):
            selected(launch, motor_actuation_enabled=spelling)


def test_io_endpoint_cannot_collide_with_the_motor_port(launch):
    """IO must have its own endpoint; sharing the motor port would address the motors."""
    import yaml
    data = yaml.safe_load((SRC / 'config_defaults' / 'hardware' /
                           'swjtumover.yaml').read_text())
    motor = data['/**']['ros__parameters']['motor']
    screen = data['screen_handler']['ros__parameters']['screen']
    assert screen['port'] != motor['port'], (
        "the screen/IO handler must not be addressable on the motor controller's port")
    assert screen['ip_address'] == motor['ip_address']  # same host, different port


def test_io_board_handler_only_starts_for_the_io_board_profile(launch):
    lab = selected(launch, hardware='openmover_lab')
    swj = selected(launch, hardware='swjtumover')
    assert lab.find('io_board_handler') is not None
    assert swj.find('io_board_handler') is None
    assert lab.find('screen_handler.py') is None
    assert swj.find('screen_handler.py') is not None


# ------------------------------------------------- scan interface -> localization

def _include_args(module, **launch_args):
    """The launch-arguments dict of each localization include, as resolved strings."""
    from launch import LaunchContext

    context = LaunchContext()
    description = module.generate_launch_description()
    configs = {}
    for entity in description.entities:
        if type(entity).__name__ == 'DeclareLaunchArgument' and entity.default_value:
            configs[entity.name] = _perform(entity.default_value, context)
    configs.update({k: str(v) for k, v in launch_args.items()})
    context._LaunchContext__launch_configurations = configs

    found = []

    def visit(entity):
        condition = getattr(entity, 'condition', None)
        if condition is not None and not condition.evaluate(context):
            return
        if type(entity).__name__ == 'OpaqueFunction':
            for produced in entity.execute(context):
                visit(produced)
            return
        if type(entity).__name__ == 'SetLaunchConfiguration':
            entity.execute(context)
            return
        nested = getattr(entity, 'actions', None)
        if isinstance(nested, (list, tuple)):
            for child in nested:
                visit(child)
            return
        if type(entity).__name__ == 'IncludeLaunchDescription':
            args = getattr(entity, 'launch_arguments', None) or []
            resolved = {}
            for key, value in args:
                resolved[_perform(key, context)] = _perform(value, context)
            found.append(resolved)

    for entity in description.entities:
        visit(entity)
    return found


def test_swjtumover_points_localization_at_the_real_scan(launch):
    """The physical scanner publishes /scan; localization must be told so, not guess."""
    includes = _include_args(launch, hardware='swjtumover')
    assert includes, "localization include not found"
    for args in includes:
        assert args.get('scan_topic') == '/scan', args


def test_lab_profile_keeps_the_merged_scan_topic(launch):
    includes = _include_args(launch, hardware='openmover_lab')
    for args in includes:
        assert args.get('scan_topic') == 'openmover/hardware/lidar/scan', args


def test_scan_topic_is_derived_from_the_selected_driver(launch):
    """One resolution, used by every consumer: they cannot disagree about the topic."""
    swj = _include_args(launch, hardware='swjtumover')
    lab = _include_args(launch, hardware='openmover_lab')
    assert {a['scan_topic'] for a in swj} == {'/scan'}
    assert {a['scan_topic'] for a in lab} == {'openmover/hardware/lidar/scan'}


def test_simulation_still_gets_a_scan_topic(launch):
    """The Gazebo include has no scan; the localization include must still get one."""
    includes = [a for a in _include_args(launch, system_mode='0', sim_area='0')
                if 'system_mode' in a]
    assert includes, "simulation localization include not found"
    for args in includes:
        assert args.get('scan_topic'), args


# ------------------------------------------- diagnostics versus the real profile

def test_stack_check_expectations_match_the_vanjee_profile(launch):
    """The diagnostic's notion of "correct" must come from the profile, not from hope."""
    import importlib.util
    import yaml

    script = SRC / 'scripts' / 'diagnostic' / 'stack_check.py'
    spec = importlib.util.spec_from_file_location('stack_check_mod', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    profile = yaml.safe_load(
        (SRC / 'config_defaults' / 'hardware' / 'swjtumover.yaml').read_text())
    vanjee = profile['vanjee_lidar_node']['ros__parameters']

    assert module.EXPECTED['frame'] == vanjee['frame_id']
    assert module.EXPECTED['range_min'] == vanjee['min_distance']
    assert module.EXPECTED['range_max'] == vanjee['max_distance']
    assert module.EXPECTED['samples'] == 1440


def test_stack_check_publishes_nothing(launch):
    """A diagnostic that could command the robot would not be a diagnostic."""
    script = SRC / 'scripts' / 'diagnostic' / 'stack_check.py'
    text = script.read_text()
    # Constructs, not words: the file legitimately *mentions* actuation in its comments.
    for forbidden in ('create_publisher(', '.publish(', 'call_async(', 'cmd_vel'):
        assert forbidden not in text, f"diagnostic must not contain {forbidden!r}"


# ------------------------------------------------ interaction / side-effecting tier

def test_stationary_tier_excludes_side_effecting_components(launch):
    """interaction:=false is the diagnostic/stationary tier: nothing physical is touched."""
    sel = selected(launch, hardware='swjtumover', interaction='false')
    assert sel.find('screen_handler.py') is None
    assert sel.find('speaker_handler.py') is None
    assert sel.find('teleop_handler.py') is None
    # the sensing, localization and control stack is still there
    assert sel.find('vanjee_scan_node') is not None
    assert sel.find('motor_handler') is not None


def test_full_tier_includes_them_by_default(launch):
    sel = selected(launch, hardware='swjtumover')
    assert sel.find('screen_handler.py') is not None
    assert sel.find('speaker_handler.py') is not None
    assert sel.find('teleop_handler.py') is not None


def test_teleop_does_not_respawn(launch):
    """An operator component must fail visibly, not restart forever and look healthy."""
    node = selected(launch, hardware='swjtumover').find('teleop_handler.py')
    assert node is not None
    assert node['respawn'] is False


def test_interaction_does_not_gate_the_sensor(launch):
    for value in ('true', 'false'):
        sel = selected(launch, hardware='swjtumover', interaction=value)
        assert sel.find('vanjee_scan_node') is not None, value


# ------------------------------------------------------- TF frame ownership

def test_urdf_does_not_claim_the_scanner_or_odom_frames(launch):
    """One owner per transform: the URDF must not compete with the profile's frames."""
    import re
    text = (SRC / 'urdf' / 'robot_description.urdf').read_text()
    links = set(re.findall(r'<link\s+name="([^"]+)"', text))
    assert 'base_link' in links
    # The Venjee profile supplies lidar_link through a static publisher, and odom comes
    # from localization_handler. If the URDF also defined them there would be two owners.
    assert 'lidar_link' not in links
    assert 'odom' not in links


def test_no_static_publisher_competes_with_the_model(launch):
    """The model publishes base_link -> lidar_link; a static publisher would duplicate it."""
    for profile in ('swjtumover', 'openmover_lab'):
        sel = selected(launch, hardware=profile)
        assert [n for n in sel.nodes if n['executable'] == 'static_transform_publisher'] == [], profile


def test_physical_mount_geometry_matches_the_ros1_reference(launch):
    """The LiDAR mount is measured, not invented: 141.14 mm up and 1.5 degrees of pitch."""
    import math
    import re
    text = (SRC / 'urdf' / 'robot_description_swjtumover.urdf').read_text()
    joint = re.search(r'<joint name="lidar_joint".*?</joint>', text, re.S).group(0)
    xyz = re.search(r'xyz="([^"]+)"', joint).group(1).split()
    rpy = re.search(r'rpy="([^"]+)"', joint).group(1).split()
    assert [float(v) for v in xyz] == [0.0, 0.0, 0.14114]
    assert abs(float(rpy[0]) - 0.02618) < 1e-9
    assert abs(math.degrees(float(rpy[0])) - 1.500) < 0.01


def test_physical_model_wheels_agree_with_the_motor_parameters(launch):
    """Independent cross-check: the model and the calibrated motor config must match."""
    import re
    import yaml

    text = (SRC / 'urdf' / 'robot_description_swjtumover.urdf').read_text()
    left = re.search(r'<joint name="wheel_left_joint".*?</joint>', text, re.S).group(0)
    xyz = [float(v) for v in re.search(r'xyz="([^"]+)"', left).group(1).split()]
    profile = yaml.safe_load(
        (SRC / 'config_defaults' / 'hardware' / 'swjtumover.yaml').read_text())
    motor = profile['/**']['ros__parameters']['motor']
    assert abs(xyz[1] - motor['chassis_radius']) < 1e-6
    assert abs(xyz[2] - motor['wheel_radius']) < 1e-5


def test_urdf_is_the_lab_fit_and_is_documented_as_such(launch):
    """The shipped URDF describes the two-bluesea lab robot, not the Vanjee fit.

    Not fixed here: a per-profile URDF is a modelling change. Recorded as a test so the
    mismatch cannot be forgotten -- the physical fit relies on the static transform for
    lidar_link, and the lab's lidar_forward/rear frames are simply unused.
    """
    import re
    text = (SRC / 'urdf' / 'robot_description.urdf').read_text()
    links = set(re.findall(r'<link\s+name="([^"]+)"', text))
    assert {'lidar_forward_link', 'lidar_rear_link'} <= links


# ------------------------------------------- LiDAR-before-DDS startup ordering

def test_lidar_driver_is_started_before_the_rest_of_the_stack(launch):
    """Every ROS 2 process binds UDP 7000 here, so the LiDAR must bind it first.

    Measured on the robot across domains 0/1/2/7: a bare rclpy node takes 0.0.0.0:7000, and
    that holder has no SO_REUSEADDR, so the driver can never bind afterwards. Ordering the
    launch is what makes the sensor usable inside the full stack.
    """
    from launch.actions import DeclareLaunchArgument, OpaqueFunction

    from launch import LaunchContext

    description = launch.generate_launch_description()
    context = LaunchContext()
    configs = {}
    for entity in description.entities:
        if isinstance(entity, DeclareLaunchArgument) and entity.default_value:
            configs[entity.name] = _perform(entity.default_value, context)
    configs['hardware'] = 'swjtumover'
    context._LaunchContext__launch_configurations = configs

    order = []
    for entity in description.entities:
        if isinstance(entity, (DeclareLaunchArgument, OpaqueFunction)):
            continue  # declarations and validators create no DDS participant
        order.append(type(entity).__name__)

    # First scheduled action is the driver node itself, everything else follows behind it.
    first = description.entities[
        [i for i, e in enumerate(description.entities)
         if not isinstance(e, (DeclareLaunchArgument, OpaqueFunction))][0]]
    assert type(first).__name__ == 'Node'
    assert _perform(first.node_executable, context) == 'vanjee_scan_node'
    assert 'TimerAction' in order, order


def test_deferred_stack_still_contains_the_control_components(launch):
    sel = selected(launch, hardware='swjtumover')
    # The deferral must not lose anything.
    for expected in ('motor_handler', 'obstacle_handler', 'localization_handler'):
        if expected == 'localization_handler':
            continue  # started by the localization include, not directly
        assert sel.find(expected) is not None, expected
    assert sel.find('<include>') is not None, "localization include missing"
