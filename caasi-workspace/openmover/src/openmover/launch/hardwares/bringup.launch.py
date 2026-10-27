#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 文件描述：hardwares/bringup.launch 的 ROS 2 Jazzy 移植（Stage 8）
# 加载机器人基础硬件系统：
#   公用节点：robot_state_publisher / joint_state_publisher / 静态 TF / 扬声器 / 雷达融合 / 障碍检测
#   仿真模式：Gazebo Harmonic（gz sim）+ ros_gz_bridge + 模型生成 + 仿真控制器
#   真机模式：雷达驱动（bluesea2）/ 电机驱动 / IO 板驱动
#   launch_gazebo:=0（Isaac 等外部仿真器）：仿真模式但不启动 Gazebo ——
#   其余仿真链路（simulation_handler / 定位 / 遥控）原样运行，由外部仿真器
#   在 openmover/control/cmd_vel_sim、openmover/hardware/odom_sim、
#   openmover/hardware/lidar_*/scan、/clock 上对接（见 isaac/scripts/17_bridge_openmover.py）

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, IncludeLaunchDescription,
                            OpaqueFunction, SetEnvironmentVariable,
                            SetLaunchConfiguration, TimerAction)
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node

share_dir = get_package_share_directory('openmover')
launch_dir = os.path.join(share_dir, 'launch')
config_dir = os.path.join(share_dir, 'config_defaults')

# Hardware profile selection. The parameter file is chosen by the `hardware` launch
# argument instead of being hardcoded, so one project can describe more than one real
# hardware fit. Defaults to the lab profile, which is exactly the previous behaviour.
# A profile is named once and everything else follows from it: the parameter file AND the
# drivers, so `hardware:=swjtumover` is enough on its own. Listing the drivers here is what
# makes the launch arguments meaningful -- previously they were validated and then ignored,
# while the node list stayed hardcoded to the lab drivers.
HARDWARE_PROFILES = {
    'openmover_lab': {
        'yaml': 'hardwares.yaml',           # bluesea2 x2 + io_board, 0.162 m track
        'lidar_driver': 'bluesea2',
        'io_driver': 'io_board',
    },
    'swjtumover': {
        'yaml': 'hardware/swjtumover.yaml',  # Vanjee 718H + screen, 0.103 m track
        'lidar_driver': 'vanjee',
        'io_driver': 'screen',
    },
}

# Which components each driver choice means, so a typo can never select nothing silently.
LIDAR_DRIVERS = ('bluesea2', 'vanjee')
IO_DRIVERS = ('io_board', 'screen')

# The parameter file follows the profile. Expressed as a substitution so the choice is
# made at launch time and the same file serves both hardware fits without duplicating
# the launch description.
hardwares_yaml = PythonExpression([
    "'", config_dir, "/' + ",
    repr({name: spec['yaml'] for name, spec in HARDWARE_PROFILES.items()}),
    ".get('", LaunchConfiguration('hardware'), "', 'hardwares.yaml')",
])
modules_yaml = os.path.join(config_dir, 'modules.yaml')

# The model follows the hardware fit. The lab robot has two bluesea2 scanners
# (lidar_forward_link/lidar_rear_link); the physical fit has one Vanjee on lidar_link, mounted
# 0.14114 m above base_link with a 0.02618 rad pitch, taken from the original ROS 1 model.
URDF_BY_PROFILE = {
    'openmover_lab': 'robot_description.urdf',
    'swjtumover': 'robot_description_swjtumover.urdf',
}
urdf_file = os.path.join(share_dir, 'urdf', 'robot_description.urdf')
world_file = os.path.join(share_dir, 'worlds', 'simulation.world')
bridge_yaml = os.path.join(config_dir, 'gz_bridge.yaml')

localization_launch = os.path.join(
    launch_dir, 'modules', 'localization', 'localization.launch.py')

# 机器人初始位姿（与 ROS 1 bringup.launch 一致）
SIM_AREAS = {
    0: ('0', '0', '0.1', '0'),
    1: ('0', '0', '0.1', '3.1415926'),
    2: ('0', '0', '0.1', '0'),
}


def bluesea2_node(name, topic, frame_id, local_port, lidar_ip, use_sim_time,
                  condition=None):
    return Node(
        package='bluesea2', executable='bluesea2_node', name=name,
        output='screen', respawn=True, condition=condition,
        parameters=[{
            'topic': topic,
            'frame_id': frame_id,
            'logPath': '/tmp/log',
            'raw_bytes': 3,
            'min_dist': 0.1,
            'max_dist': 50.0,
            'zero_shift': 0.0,
            'from_zero': False,
            'output_scan': True,
            'output_cloud': False,
            'output_360': True,
            'with_checksum': True,
            'inverted': True,
            'reversed': False,
            'hard_resample': False,
            'soft_resample': False,
            'with_angle_filter': True,
            'min_angle': -1.57,
            'max_angle': 1.57,
            'error_circle': 3,
            'error_scale': 0.9,
            'type': 'udp',
            'lidar_port': 502,
            'local_port': local_port,
            'lidar_ip': lidar_ip,
            'group_listener': False,
            'group_ip': '224.0.0.11',
            'uuid': -1,
            'rpm': 900,
            'resample_res': -1.0,
            'with_smooth': True,
            'with_deshadow': True,
            'alarm_msg': -1,
            'direction': -1,
            'use_sim_time': use_sim_time,
        }])


def teleop_node(use_sim_time, condition=None):
    # No respawn: teleoperation needs an operator and a keyboard backend. Respawning hid that
    # requirement behind a restart loop, so an unusable environment looked like a running
    # component. The handler now exits with a precise message instead.
    return Node(
        package='openmover', executable='teleop_handler.py', name='teleop_handler',
        output='screen', respawn=False, condition=condition,
        parameters=[hardwares_yaml, modules_yaml, {'use_sim_time': use_sim_time}])


def generate_launch_description():
    system_mode = LaunchConfiguration('system_mode')
    sim_area = LaunchConfiguration('sim_area')
    use_sim_time = LaunchConfiguration('use_sim_time')
    launch_gazebo = LaunchConfiguration('launch_gazebo')
    motor_actuation_enabled = LaunchConfiguration('motor_actuation_enabled')
    hardware = LaunchConfiguration('hardware')
    lidar_driver = LaunchConfiguration('lidar_driver')
    io_driver = LaunchConfiguration('io_driver')
    interaction = LaunchConfiguration('interaction')

    # The environment factor for M1 hardening: exactly '1' only when the launch
    # argument is exactly 'true'. A params file cannot set an environment variable,
    # so this is what makes "a YAML cannot grant actuation" a mechanism rather than
    # a convention.
    motor_actuation_env = PythonExpression([
        "'1' if '", motor_actuation_enabled, "' == 'true' else '0'"
    ])

    def _resolve_hardware(context, *args, **kwargs):
        """Resolve the driver set from the hardware profile, before any node is built.

        The profile is authoritative: leaving the driver arguments empty follows it, and
        passing one that contradicts it is an error rather than something to guess at.
        Everything downstream keys off the resolved values, so a driver choice cannot be
        accepted here and then ignored when the nodes are created.
        """
        profile = context.launch_configurations.get('hardware', 'openmover_lab')
        spec = HARDWARE_PROFILES.get(profile)
        if spec is None:
            raise RuntimeError(
                f"unknown hardware profile {profile!r}; known profiles: "
                f"{sorted(HARDWARE_PROFILES)}"
            )

        actions = []
        for arg_name, known in (('lidar_driver', LIDAR_DRIVERS),
                                ('io_driver', IO_DRIVERS)):
            requested = (context.launch_configurations.get(arg_name) or '').strip()
            expected = spec[arg_name]
            if requested and requested != expected:
                raise RuntimeError(
                    f"hardware profile {profile!r} expects {arg_name}:={expected!r}, "
                    f"got {requested!r} -- these drivers are mutually exclusive by "
                    f"profile, so they cannot both run"
                )
            context.launch_configurations[arg_name] = expected
            actions.append(SetLaunchConfiguration(arg_name, expected))

        # A profile whose parameter file is missing must fail here, by name, rather than
        # as an unexplained parameter-file error from whichever node starts first.
        params_file = os.path.join(config_dir, spec['yaml'])
        if not os.path.isfile(params_file):
            raise RuntimeError(
                f"hardware profile {profile!r} needs {params_file}, which is not present "
                f"in the installed package"
            )

        # Only check the driver package when that driver is actually selected, so the lab
        # profile still launches on a host where the Vanjee driver was never built.
        if spec['lidar_driver'] == 'vanjee':
            try:
                get_package_share_directory('openmover_vanjee')
            except Exception:
                raise RuntimeError(
                    f"hardware profile {profile!r} selects the Vanjee LiDAR driver but "
                    f"package 'openmover_vanjee' is not installed; build it or use "
                    f"hardware:=openmover_lab"
                ) from None

        return actions

    def _validate_motor_actuation(context, *args, **kwargs):
        # Reject ambiguous spellings before any node starts. ROS 2 launch parses
        # argument values as YAML, which would otherwise accept 'yes'/'on'/'TRUE' as
        # boolean true and silently authorise actuation.
        raw = context.launch_configurations.get('motor_actuation_enabled', 'false')
        if raw not in ('true', 'false'):
            raise RuntimeError(
                "motor_actuation_enabled must be exactly 'true' or 'false' "
                f"(got {raw!r}); ambiguous spellings are rejected so that an "
                "unintended value can never authorise motor output"
            )
        return []

    sim_cond = IfCondition(PythonExpression([system_mode, ' == 0']))
    real_cond = IfCondition(PythonExpression([system_mode, ' == 1']))

    def real_with(configuration, expected):
        """Real hardware mode AND a specific driver selected.

        Real mode alone is not enough: both LiDAR drivers and both chassis IO drivers are
        mutually exclusive, so each set is gated on its own resolved selection. This is
        what stops one profile's drivers from starting under another profile.
        """
        return IfCondition(PythonExpression(
            ["'", system_mode, "' == '1' and '", configuration,
             "' == '", expected, "'"]))

    vanjee_cond = real_with(lidar_driver, 'vanjee')
    bluesea_cond = real_with(lidar_driver, 'bluesea2')
    io_board_cond = real_with(io_driver, 'io_board')
    # The screen handler writes to the display board over the network, so it belongs to the
    # interaction tier as well as to the io_driver selection.
    screen_cond = IfCondition(PythonExpression(
        ["'", system_mode, "' == '1' and '", io_driver, "' == 'screen' and '",
         interaction, "' == 'true'"]))

    # Components that interact with the outside world (a display, a speaker, an operator's
    # keyboard) are separated from the sensing and control stack. A diagnostic or stationary
    # bringup runs with interaction:=false and touches nothing physical.
    sim_interaction_cond = IfCondition(PythonExpression(
        ["'", system_mode, "' == '0' and '", interaction, "' == 'true'"]))
    real_interaction_cond = IfCondition(PythonExpression(
        ["'", system_mode, "' == '1' and '", interaction, "' == 'true'"]))

    # The two-lidar fusion only makes sense for the two-bluesea fit. A single 360 degree
    # Vanjee publishes /scan directly, so merging two non-existent topics would replace a
    # working scan with an empty one.
    merger_cond = IfCondition(PythonExpression(["'", lidar_driver, "' == 'bluesea2'"]))

    # Consumers subscribe the merged topic by name. It becomes the Vanjee's /scan when
    # there is nothing to merge, so downstream stays wired without a second scan type.
    lidar_scan_topic = PythonExpression([
        "'openmover/hardware/lidar/scan' if '", lidar_driver, "' == 'bluesea2' else '/scan'",
    ])
    # Gazebo 本体（仿真器 + 桥接 + 生成模型）：仅仿真模式且 launch_gazebo:=1。
    # launch_gazebo:=0 时由外部仿真器（Isaac）顶上，其余仿真节点不变。
    gz_cond = IfCondition(PythonExpression(
        [system_mode, ' == 0 and ', launch_gazebo, ' == 1']))

    # 启动机器人状态发布节点（读取 URDF 文件内容作为参数）
    def publish_robot_description(context):
        profile = context.launch_configurations.get('hardware', 'openmover_lab')
        model = URDF_BY_PROFILE.get(profile, 'robot_description.urdf')
        path = os.path.join(share_dir, 'urdf', model)
        if not os.path.isfile(path):
            raise RuntimeError(
                f"hardware profile {profile!r} needs robot model {path}, which is not "
                f"present in the installed package"
            )
        with open(path, 'r') as f:
            robot_description = f.read()
        return [Node(
            package='robot_state_publisher', executable='robot_state_publisher',
            name='robot_state_publisher',
            parameters=[{'robot_description': robot_description,
                         'use_sim_time': use_sim_time.perform(context) == 'true'}])]

    # 仿真区域生成机器人模型 + 启动定位管理系统
    def spawn_area(context, area):
        x, y, z, yaw = SIM_AREAS[area]
        return [
            # gz 生成模型：launch_gazebo:=0（外部仿真器）时跳过；
            # 定位管理系统两种情况都要启动
            Node(package='ros_gz_sim', executable='create', name='spawn_robot',
                 output='screen', condition=gz_cond,
                 arguments=['-file', urdf_file, '-name', 'robot_description',
                            '-x', x, '-y', y, '-z', z, '-Y', yaw]),
            IncludeLaunchDescription(localization_launch, launch_arguments={
                'scan_topic': lidar_scan_topic,
                'init_diff_x': x,
                'init_diff_y': y,
                'init_diff_z': z,
                'init_diff_yaw': yaw,
                'system_mode': system_mode.perform(context),
                'use_sim_time': use_sim_time.perform(context),
            }.items()),
        ]

    # 真机模式启动定位管理系统
    def real_localization(context):
        return [IncludeLaunchDescription(localization_launch, launch_arguments={
            'system_mode': system_mode.perform(context),
            'use_sim_time': use_sim_time.perform(context),
            # The same resolved interface the consumers above use, so the localization
            # processor and the scan source cannot disagree about the topic.
            'scan_topic': lidar_scan_topic,
        }.items())]

    # Gazebo Harmonic 资源路径（package://openmover/... 网格解析）
    gz_resource_path = SetEnvironmentVariable(
        name='GZ_SIM_RESOURCE_PATH',
        value=[os.environ.get('GZ_SIM_RESOURCE_PATH', ''), ':',
               os.path.dirname(share_dir)],
        condition=gz_cond)

    # 启动 Gazebo Harmonic 仿真器
    # NOTE: ros_gz_sim is resolved lazily, inside this function. Resolving it at
    # description-build time made the entire bringup unimportable on any host without
    # Gazebo -- including the physical robot, where simulation is never used.
    def _gz_sim_include():
        return IncludeLaunchDescription(
            os.path.join(get_package_share_directory('ros_gz_sim'),
                         'launch', 'gz_sim.launch.py'),
            launch_arguments={
                'gz_args': ['-r -v 1 ', world_file],
                'on_exit_shutdown': 'false',
            }.items(),
            condition=gz_cond,
        )

    # 启动 Gazebo <-> ROS 2 桥接
    ros_gz_bridge = Node(
        package='ros_gz_bridge', executable='parameter_bridge', name='ros_gz_bridge',
        output='screen', condition=gz_cond,
        # 桥接节点发布 /clock，自身保持墙钟时间避免时钟依赖
        parameters=[{'config_file': bridge_yaml, 'use_sim_time': False}])

    # 启动仿真控制器
    simulation_handler = Node(
        package='openmover', executable='simulation_handler', name='simulation_handler',
        output='screen', respawn=True, condition=sim_cond,
        parameters=[{'use_sim_time': use_sim_time}])

    # The Vanjee driver must bind UDP 7000 *before any other ROS 2 process on this
    # machine*: in this environment every ROS 2 node also binds UDP 7000 (measured across
    # domains 0/1/2/7), and that socket is held without SO_REUSEADDR, so the LiDAR can never
    # bind afterwards. The DDS side tolerates losing the port, so starting the driver first
    # is sufficient. It is therefore launched immediately and everything else is deferred,
    # which makes the ordering deterministic instead of a race.
    lidar_first = Node(
        package='openmover_vanjee', executable='vanjee_scan_node',
        name='vanjee_lidar_node', output='screen', respawn=True,
        condition=vanjee_cond,
        parameters=[hardwares_yaml, {'use_sim_time': use_sim_time}])

    deferred = LaunchDescription([
        DeclareLaunchArgument('system_mode', default_value='1'),
        DeclareLaunchArgument('sim_area', default_value='0'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument(
            'hardware', default_value='openmover_lab',
            description='Hardware profile: which parameter file and which driver set. '
                        'openmover_lab = bluesea2 x2 + io_board + 0.162 m track; '
                        'swjtumover = Vanjee 718H + screen display + 0.103 m track.'),
        DeclareLaunchArgument(
            'lidar_driver', default_value='',
            description='LiDAR driver to start: bluesea2 or vanjee. Leave empty (default) '
                        'to follow the hardware profile, which is what makes '
                        'hardware:=swjtumover sufficient on its own. The two drivers are '
                        'mutually exclusive, so they can never both run.'),
        DeclareLaunchArgument(
            'io_driver', default_value='',
            description='Chassis IO driver: io_board or screen. Leave empty (default) to '
                        'follow the hardware profile.'),
        OpaqueFunction(function=_resolve_hardware),
        OpaqueFunction(function=_validate_motor_actuation),
        DeclareLaunchArgument(
            'motor_actuation_enabled', default_value='false',
            description='Allow physical motor actuation. Default DENY. This is an '
                        'explicit launch decision and is deliberately NOT read from a '
                        'YAML parameter file, so a copied or inherited configuration '
                        'cannot grant motor output on another robot.'),
        DeclareLaunchArgument(
            'lidar_bind_lead', default_value='3.0',
            description='Seconds between starting the LiDAR driver and the rest of the '
                        'stack. The driver must own UDP 7000 first, because every ROS 2 '
                        'process also binds it in this environment.'),
        DeclareLaunchArgument(
            'interaction', default_value='true',
            description='Start the components that interact with the outside world: the '
                        'screen display, the speaker and teleoperation. Set false for a '
                        'diagnostic or stationary bringup, which otherwise runs the sensing, '
                        'localization and control stack only.'),
        DeclareLaunchArgument(
            'launch_gazebo', default_value='1',
            description='仿真模式下是否启动 Gazebo 本体；0 = 外部仿真器'
                        '（Isaac）对接，其余仿真节点照常启动'),

        # 以下为公用节点
        OpaqueFunction(function=publish_robot_description),
        Node(package='joint_state_publisher', executable='joint_state_publisher',
             name='joint_state_publisher',
             parameters=[{'use_sim_time': use_sim_time}]),
        # base_link -> lidar_link comes from the robot model for the physical fit; for the lab
        # fit the two scanner frames are in that model too. No static publisher: a second
        # owner of the same transform is exactly the duplicate-TF defect to avoid.


        # 启动扬声器驱动
        Node(package='openmover', executable='speaker_handler.py',
             name='speaker_handler', respawn=True, condition=real_interaction_cond,
             parameters=[{'sound_filepath': os.path.join(
                 os.environ.get('HOME', ''), 'openmover_robot', 'sounds') + os.sep,
                 'use_sim_time': use_sim_time}]),

        # 启动雷达数据融合（ira_laser_tools，Stage 9 移植）
        Node(package='ira_laser_tools', executable='laserscan_multi_merger',
             name='laserscan_multi_merger', output='screen', condition=merger_cond,
             parameters=[{
                 'destination_frame': 'lidar_link',
                 'cloud_destination_topic': 'openmover/hardware/lidar/pointcloud',
                 'scan_destination_topic': 'openmover/hardware/lidar/scan',
                 'laserscan_topics':
                     '/openmover/hardware/lidar_forward/scan /openmover/hardware/lidar_rear/scan',
                 'angle_min': -3.1415926,
                 'angle_max': 3.1415926,
                 'angle_increment': 0.006962,
                 'scan_time': 0.0,
                 'range_min': 0.33,
                 'range_max': 20.0,
                 'use_sim_time': use_sim_time,
             }]),

        # 以下为仿真环境使用
        gz_resource_path,
        # Deferred: the Gazebo include is only constructed when the condition holds, so
        # a host without ros_gz_sim can still load this file.
        OpaqueFunction(function=lambda ctx: [_gz_sim_include()], condition=gz_cond),
        ros_gz_bridge,
        OpaqueFunction(function=lambda ctx: spawn_area(ctx, 0),
                       condition=IfCondition(PythonExpression(
                           [system_mode, ' == 0 and ', sim_area, ' == 0']))),
        OpaqueFunction(function=lambda ctx: spawn_area(ctx, 1),
                       condition=IfCondition(PythonExpression(
                           [system_mode, ' == 0 and ', sim_area, ' == 1']))),
        OpaqueFunction(function=lambda ctx: spawn_area(ctx, 2),
                       condition=IfCondition(PythonExpression(
                           [system_mode, ' == 0 and ', sim_area, ' == 2']))),
        simulation_handler,
        teleop_node(use_sim_time, condition=sim_interaction_cond),

        # 以下为真机环境使用
        bluesea2_node('bluesea2_node_forward', 'openmover/hardware/lidar_forward/scan',
                      'lidar_forward_link', 6667, '192.168.100.101', use_sim_time,
                      condition=bluesea_cond),
        bluesea2_node('bluesea2_node_rear', 'openmover/hardware/lidar_rear/scan',
                      'lidar_rear_link', 6668, '192.168.100.102', use_sim_time,
                      condition=bluesea_cond),
        OpaqueFunction(function=real_localization, condition=real_cond),
        Node(package='openmover', executable='motor_handler', name='motor_handler',
             output='screen', respawn=True, condition=real_cond,
             parameters=[hardwares_yaml, modules_yaml,
                         # Actuation permission is an explicit launch decision and is
                         # never read from a YAML file: a parameter file may deny
                         # driving but must never grant it, so a copied, inherited or
                         # mistaken YAML cannot enable motor output on another robot.
                         # Declared below with default 'false' (DENY).
                         {'motor.actuation_enabled': motor_actuation_enabled},
                         {'use_sim_time': use_sim_time}],
             additional_env={'CAASI_MOTOR_ACTUATION': motor_actuation_env}),
        Node(package='openmover', executable='io_board_handler', name='io_board_handler',
             output='screen', respawn=True, condition=io_board_cond,
             parameters=[hardwares_yaml, modules_yaml,
                         {'use_sim_time': use_sim_time}]),
        # Chassis IO for the swjtumover fit is the screen/IO board at 192.168.100.100:26.
        # Starting it is selection only: no payload is sent until the stack asks for one.
        Node(package='openmover', executable='screen_handler.py', name='screen_handler',
             output='screen', respawn=True, condition=screen_cond,
             parameters=[hardwares_yaml, modules_yaml,
                         {'use_sim_time': use_sim_time}]),
        teleop_node(use_sim_time, condition=real_interaction_cond),

        # 启动障碍检测
        Node(package='openmover', executable='obstacle_handler', name='obstacle_handler',
             output='screen',
             parameters=[hardwares_yaml, modules_yaml,
                         {'use_sim_time': use_sim_time}],
             remappings=[('openmover/hardware/lidar/scan/obstacle', lidar_scan_topic)]),
    ])

    # Only the argument declarations and the two validators run immediately: they create no
    # DDS participant. Everything that *produces nodes* is deferred -- including the
    # OpaqueFunctions that build the robot_description publisher and the localization
    # include, which is exactly the mistake that once let localization_handler take the port
    # ahead of the LiDAR driver.
    validator_names = {'_resolve_hardware', '_validate_motor_actuation'}
    declaration_actions = []
    node_actions = []
    for action in deferred.entities:
        func_name = getattr(getattr(action, '_OpaqueFunction__function', None), '__name__', '')
        if isinstance(action, DeclareLaunchArgument) or func_name in validator_names:
            declaration_actions.append(action)
        else:
            node_actions.append(action)

    return LaunchDescription(declaration_actions + [
        lidar_first,
        TimerAction(period=LaunchConfiguration('lidar_bind_lead'), actions=node_actions),
    ])
