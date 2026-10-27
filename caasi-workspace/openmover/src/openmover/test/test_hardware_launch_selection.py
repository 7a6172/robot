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
                          'package': package, 'parameters': params, 'env': env})
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
