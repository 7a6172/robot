# OpenMover: Full ROS 1 Noetic → ROS 2 Jazzy + Gazebo Harmonic Migration Plan

## 1. Summary

Migrate the entire `openmover_robot` ROS 1 project (9 custom C++ nodes, 8 Python nodes, 3 custom interface packages, 2 algorithm toolboxes, cartographer SLAM/localization, dual-LiDAR hardware drivers, laser merging, Gazebo simulation, RViz, rosbridge, and the warehouse demo) into a new colcon workspace at `/home/zar/Documents/phd/robot/openmover_ws`, targeting **ROS 2 Jazzy + Gazebo Harmonic (gz-sim 8.10)**. The ROS 1 repo stays untouched as reference. Nothing is dropped; every ROS 1 artifact gets a ROS 2 equivalent.

### Verified environment (checked on this machine)
- ROS 2 Jazzy installed and active (`ROS_DISTRO=jazzy`), Gazebo Harmonic `gz sim 8.10.0` confirmed.
- Already installed: `cartographer_ros` (ROS 2 port, **with `tracked_pose` support confirmed in headers**), `cartographer_ros_msgs` (incl. `WriteState.srv`), `ros_gz_sim`, `ros_gz_bridge`, `nav2_costmap_2d`, `nav2_map_server`, `nav2_lifecycle_manager`, `nav2_msgs`, `slam_toolbox`, `laser_geometry`, `pcl_ros`, `tf2_ros`, `robot_state_publisher`, `xacro`, `teleop_twist_keyboard`, `pointcloud_to_laserscan` (not installed but in apt), `colcon`.
- Installable via apt (missing now): `ros-jazzy-rosbridge-server`, `ros-jazzy-pointcloud-to-laserscan`, `ros-jazzy-joy`, `python3-pynput`, `python3-pygame`.
- NOT in apt: `libosqp-dev` → build OSQP from the vendored source `openmover_robot/osqp/` (same as ROS 1 `install.sh` did).

### Key architectural decisions (confirmed with user)
1. **SLAM: Cartographer ROS 2 port** (binary `ros-jazzy-cartographer-ros`) — keeps `mapping.lua`/`navigation.lua` and `.pbstream` workflow; `tracked_pose` exists in the ROS 2 port, so `localization_handler` keeps its exact ROS 1 data path.
2. **warehouse_simulation_toolkit: migrate** (Pioneer3DX + Gazebo Harmonic + Nav2 + slam_toolbox + rviz2 + ported `key_control`).
3. **Testing: all three** — golden-value unit tests, sim integration test, ROS1-vs-ROS2 comparison guide.
4. **Workspace**: use the provided empty `/home/zar/Documents/phd/robot/openmover_ws`.
5. **Identity preservation**: all topic names, service names, TF frames, and parameter names stay identical to ROS 1 wherever technically possible, so behavior and results are directly comparable.

---

## 2. Current State Analysis (ROS 1)

Source: `/home/zar/Documents/phd/robot/openmover_robot` (built for Noetic).

### 2.1 Packages
| Package | Content | Migration approach |
|---|---|---|
| `openmover` | 9 C++ nodes, 9 libs, 8 Python nodes, URDF + meshes, Gazebo world, 11 launch files | Full port (biggest work item) |
| `openmover_msgs` | 8 msg + 10 srv (in subfolders) | → rosidl package, flatten srv folders |
| `auto_mapping_toolbox(_msgs)` | frontier exploration + custom costmap/Dijkstra/OSQP planner | Full port |
| `relocalization_toolbox(_msgs)` | global 2D relocalization (likelihood field + PCL GICP) | Full port |
| `bluesea2` | Lanhai UDP LiDAR driver | Replace with official `BlueSeaLidar/bluesea-ros2` driver + our config overlay |
| `ira_laser_tools` | `laserscan_multi_merger` (used) + `laserscan_virtualizer` (unused by robot) | Port merger to rclcpp; port virtualizer too for completeness |
| `warehouse_simulation_toolkit` | Pioneer3DX demo: gmapping + move_base + Gazebo classic | Migrate to Nav2 + slam_toolbox + Gazebo Harmonic |
| `cartographer_ws` | cartographer + cartographer_ros built from source | Replaced by apt `ros-jazzy-cartographer-ros` (not rebuilt) |
| repo-root `config/`, `maps/`, `osqp/`, `install.sh` | runtime lua/yaml configs, saved maps+pbstreams, vendored OSQP, provisioning | `config/`+`maps/` shipped as package defaults + runtime dir seeding; OSQP built from vendored source |

### 2.2 System architecture (must be preserved)
- Entry: `workload.launch` → `bootloader.launch` (mode servers + rosbridge:8080 + rviz) + `bringup.launch` (robot_state_publisher, static TF `base_link→lidar_link`, speaker, laser merger, obstacle_handler; sim branch: Gazebo + `simulation_handler` + teleop; real branch: 2× bluesea2 UDP drivers @192.168.100.101/.102, `motor_handler` @192.168.100.100:23, `io_board_handler` @192.168.100.100:26).
- 5 Python "server" nodes dynamically start/stop launch subtrees at runtime via the **ROS 1 `roslaunch` Python API** (`func_mode_server_handler`, `nav_area_server_handler`, `localization_mode_server_handler`, `cartographer_server_handler`, `reset_server_handler`). No ROS 2 equivalent API exists → replaced with a subprocess-based `ros2 launch` process manager (see §4.1).
- HAL layer: `workload.py` → `cli.py`/`hal.py`/`protocol.py` orchestrates everything via services (`openmover/server/set_func_mode`, `set_localization_mode`, `set_nav_area`, `openmover/navigation/request`, `auto_mapping/request`, `relocalization/request`, `initialpose/request`, `playsound/request`, `cmd_vel_mode/request`, `flow/action`+`flow/state`).
- Localization chain: `motor_handler`/`simulation_handler` → `localization_handler` (odom→base TF, pose fusion) ← cartographer `tracked_pose` (remapped `pose_aft_mapped`) + `map→odom` TF from cartographer; `localization_confidence_handler` scores scan-vs-map; `relocalization_2d_handler` provides global relocalization.
- Mapping chain: cartographer (mapping.lua) + `auto_mapping_handler` (frontiers, own `costmap_2d`, Dijkstra+OSQP planner) + `navigation_handler` (executes paths) → map saved via cartographer `WriteState` srv (`.pbstream`) + `map_server map_saver` (pgm/yaml).
- Navigation chain: `navigation_handler` (custom local planner + `costmap_2d` as library, ~50 params) consumes pose/twist/obstacle/map, publishes `cmd_vel`, `nav_to_state` (latched), serves `navigation/request` + `simple_request`.
- Custom nav stack (no move_base in the robot itself): costmap_2d used directly as a C++ library by `navigation_handler` and `auto_mapping_handler`.
- Runtime dirs outside packages: `$(env HOME)/openmover_robot/{config,maps,sounds,logs}`.

### 2.3 ROS 1-isms to replace everywhere
`roscpp/rospy` → `rclcpp/rclpy`; `tf` (tf1) → `tf2*`; `ros::topic::waitForMessage` → helper (spin-until-message); latched publishers → `TRANSIENT_LOCAL` QoS; `XmlRpc` footprint param → double-array param; `dynamic_reconfigure` → declared parameters; `ros::master::getTopics()` → rclcpp graph API; `sensor_msgs/PointCloud` → `PointCloud2`; `navfn/MakeNavPlan` srv → `nav_msgs/GetPlan`; `roslaunch` Python API → subprocess launch manager; catkin → ament/colcon + install rules (ROS 1 CMake has **zero install rules**); classic Gazebo plugins → gz-sim8 systems + `ros_gz_bridge`; `map_server/map_saver` → `nav2_map_server`; RViz → RViz2.

---

## 3. Target Workspace Layout

`/home/zar/Documents/phd/robot/openmover_ws/` (colcon):

```
openmover_ws/
├── src/
│   ├── openmover_msgs/                    # rosidl interfaces
│   ├── auto_mapping_toolbox/
│   │   ├── auto_mapping_toolbox_msgs/
│   │   └── auto_mapping_toolbox/
│   ├── relocalization_toolbox/
│   │   ├── relocalization_toolbox_msgs/
│   │   └── relocalization_toolbox/
│   ├── openmover/                         # robot core (C++/py/launch/urdf/worlds/meshes/rviz/config defaults/maps defaults/tests)
│   ├── ira_laser_tools/                   # rclcpp port (merger + virtualizer)
│   ├── bluesea2/                          # vendored official BlueSeaLidar/bluesea-ros2 driver (git clone)
│   └── warehouse_simulation/              # migrated demo (Nav2 + slam_toolbox + gz harmonic)
├── tools/
│   ├── setup.sh                           # apt deps + OSQP install (replaces ROS 1 install.sh)
│   ├── golden/                            # ROS 1 Docker golden-data generator script
│   └── comparison/                        # ROS1-vs-ROS2 trajectory/map comparison scripts
└── docs/                                  # migration notes + comparison guide (user-requested)
```

Runtime compatibility: a `ros2 run openmover init_runtime_dirs` script seeds `$OPENMOVER_HOME` (default `~/openmover_robot`) with `config/`, `maps/`, `sounds/` from package defaults **only if missing**, preserving the user's existing maps. All launch files read `OPENMOVER_HOME` env (fallback `~/openmover_robot`) instead of hard `$(env HOME)` paths.

---

## 4. Cross-Cutting Migration Patterns

### 4.1 Dynamic launch management (the roslaunch-API replacement)
New module `openmover/scripts/openmover_py/launch_manager.py`:
- `LaunchHandle = subprocess.Popen(["ros2","launch",...], start_new_session=True)`
- `start(launch_pkg, launch_file, args: dict)` / `stop()` (terminate process group, then SIGKILL after 5 s grace) / `restart()` / `is_alive()`.
- The 4 mode servers (`func_mode`, `nav_area`, `localization_mode`, `cartographer`) keep their exact ROS 1 service interfaces (`work_mode_request`) and parameter names (`launch_file_create_map`, `launch_file_nav_mode`, `launch_file_load_map`, `nav_map_save_path`, `enable_visualization`, `visualization_config_file_*`, `system_mode`, `localization_mode`, ...); only the launch mechanism changes.
- `pkill gzserver/gzclient` shutdown hooks and `sudo renice` calls are preserved (guarded, non-fatal).
- Python nodes import this module via `sys.path` injection of the installed `scripts/` dir (installed to `share/openmover/scripts`).

### 4.2 QoS mapping
| ROS 1 | ROS 2 |
|---|---|
| latched (`button`, `emergency`, `bms`, `navigation/state`, `auto_mapping/state`, `flow/state`, `planner/plan`) | `DurabilityPolicy.TRANSIENT_LOCAL`, depth 1 |
| scan/odom sensor streams | `rclcpp::SensorDataQoS` |
| services | default |

### 4.3 costmap_2d as a library
`costmap_2d::Costmap2DROS` → `nav2_costmap_2d::Costmap2DROS` (it is a LifecycleNode in Nav2). Usage pattern in `navigation_handler`/`auto_mapping_handler`:
```cpp
costmap_ros_ = std::make_shared<nav2_costmap_2d::Costmap2DROS>("global_costmap", tf_buffer_, "global_costmap");
// run in own executor thread; drive lifecycle manually:
costmap_ros_->configure(); costmap_ros_->activate();   // on start; deactivate/cleanup on stop
```
Costmap YAML params keep the ROS 1 names (plugins `static_layer`/`obstacle_layer`/`inflation_layer`, topics remapped exactly as today under `openmover/navigation/global_planner/costmap/*` / `openmover/mapping/global_planner/costmap/*`). Nav2 differences handled: `Costmap2DROS` name/namespace split, lifecycle transitions, `robot_radius`/footprint param formats.

### 4.4 `ros::topic::waitForMessage` replacement
Small shared helper `openmover/include/openmover/topic_utils.hpp` (+ twin for rclpy): `template<class T> T::SharedPtr wait_for_message(node, topic, qos, timeout)` using a one-shot subscription + spin loop — used by `localization_handler` (initialpose), `navigation_handler` (map), `relocalization_2d_handler` (scan/map).

### 4.5 Map save/load
- Save occupancy grid: `ros2 run nav2_map_server map_saver_cli -f <path> --ros-args -r map:=openmover/mapping/map` (replaces `rosrun map_server map_saver`); `$HOME_PATH` yaml rewriting logic kept as-is.
- Load map: `nav2_map_server` `map_server` node with `autostart: true` + `frame_id: map`, remapped to `openmover/mapping/map` / `map_metadata` (replaces ROS1 `map_server`).
- pbstream save: cartographer `WriteState` srv (same name `openmover/mapping/write_state/request`, type `cartographer_ros_msgs/srv/WriteState`).

### 4.6 Gazebo Harmonic patterns
- World: new SDF for gz-sim8 with required system plugins:
  ```xml
  <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
  <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
  <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
  <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors"><render_engine>ogre2</render_engine></plugin>
  ```
- Diff drive: `gz-sim-diff-drive-system-plugin` with gz topics `cmd_vel` / `odom`; `ros_gz_bridge` maps them to `openmover/control/cmd_vel_sim` (`geometry_msgs/Twist`) and `openmover/hardware/odom_sim` (`nav_msgs/Odometry`) so `simulation_handler` ports 1:1 unchanged.
- LiDARs: two `<sensor type="gpu_lidar">` (600 samples, ±1.57 rad, 0.22–10 m, 15 Hz, gaussian noise) → bridged to `openmover/hardware/lidar_forward/scan` / `openmover/hardware/lidar_rear/scan` (`sensor_msgs/LaserScan`), with per-topic `frame_id` overrides (`lidar_forward_link`/`lidar_rear_link`) in the bridge YAML.
- Clock bridge (`/clock`) + `use_sim_time:=true` everywhere in sim.
- Spawning: `ros2 run ros_gz_sim create -topic robot_description -x/-y/-z/-Y` per `sim_area` (same three start poses as ROS 1).

### 4.7 Build system
ament_cmake everywhere (pure-interface packages: ament_cmake + rosidl). All packages get proper `install()` rules (executables, libs, launch, config, meshes, urdf, worlds, rviz, scripts). C++17, `-O3` retained for algorithm libs (`-flto -ffast-math` for relocalization as in ROS 1).

---

## 5. Package-by-Package Changes

### 5.1 `openmover_msgs` → `openmover_msgs` (rosidl)
- Move `msg/*.msg` unchanged (all field types ROS 2-compatible incl. `bool[4]`).
- Flatten `srv/{driver,localization,manager,mode,navigation}/*.srv` → `srv/*.srv` (ROS 2 requires flat dirs); contents unchanged.
- Trim package.xml to pure interface deps (`rosidl_default_generators`, `std_msgs`, `geometry_msgs`); drop the wrong ROS 1 deps (cartographer_ros_msgs, costmap_2d, serial, actionlib...).

### 5.2 `auto_mapping_toolbox_msgs` / `relocalization_toolbox_msgs`
- Same conversion. Fix the ROS 1 anomaly: rename `RelocalizationRequest.srv` → `srv/relocalization_request.srv` (content unchanged), so `relocalization_toolbox_msgs/srv/RelocalizationRequest` is generated consistently.

### 5.3 `openmover` (core robot package)
**C++ nodes (all keep names, topics, services, params; ports are mechanical):**

| Node | Specific conversion notes |
|---|---|
| `io_board_handler` | UDP sockets stay (raw POSIX). `boost::thread` → `std::thread`. Latched pubs → transient_local. `tf::getYaw`/`createQuaternionMsgFromYaw` → `tf2::getYaw`/`tf2::toMsg(tf2::Quaternion)`. Drop vestigial `serial` include. Params `robot.*` declared. |
| `motor_handler` | Same socket code; `ros::Rate` → `rclcpp::Rate`; keep zero-speed-on-shutdown hook via `rclcpp::shutdown` callback. |
| `simulation_handler` | 1:1 port; subscribes `openmover/hardware/odom_sim` (nav_msgs/Odometry from gz bridge). |
| `teleop_handler` (C++) | `sensor_msgs/Joy` unchanged; service client `stop_request`. |
| `localization_handler` | tf2 broadcaster/listener; keeps `initialpose/request` + `direct/request` services; `pose_aft_mapped` still fed from cartographer **`tracked_pose`** (confirmed present in ROS 2 port); `waitForMessage` → helper; init pose params `init_diff_*`. |
| `localization_confidence_handler` | Straight port (likelihood_field lib). |
| `obstacle_handler` | PCL + `tf2::transformToEigen` already ROS2-style; straight port. |
| `navigation_handler` | Biggest node: ~50 params declared; costmap via §4.3 (two `Costmap2DROS`: `global_costmap`, `global_costmap_static`); keep all internal libs unchanged (controllers/mover/path_follower/path_checker/collision_checker); `MakeNavPlan`-style make_plan exposed as **`nav_msgs/srv/GetPlan`** at `openmover/navigation/global_planner/make_plan` (so `hal.py plan()` keeps working; ROS 1's orphan `global_planner_handler` is merged here and dropped as separate binary). |
| `global_planner_handler` | Dropped as standalone binary (never launched in ROS 1); its `make_plan` capability moves into `navigation_handler` (above). |
| Libraries | `crc8_maxim`, `math_utils`, `likelihood_field`, `controllers`, `mover`, `path_follower`, `collision_checker`, `path_checker`, `global_planner_deps` (11 files + `osqp::osqp` link) — code unchanged except includes (`tf` → `tf2`, msg headers `openmover_msgs/xxx.h` → `openmover_msgs/msg/xxx.hpp`). |

**Python nodes (rospy → rclpy, same node names/params):**
- `speaker_handler.py` (pygame), `teleop_handler.py` (pynput), `workload.py` + `hal/` (`cli.py`, `hal.py`, `protocol.py`, `config.py`, `symbols.py`, `logger.py`, `utils.py`) — mechanical conversion: `rospy.ServiceProxy` → `create_client`, `wait_for_message` → helper, `rospy.get_param` → declared params / config files, sim-time detection via `/clock`, `tf.transformations` → `tf_transformations` (pip) or local quaternion funcs.
- `server/func_mode_server_handler.py`, `nav_area_server_handler.py`, `localization_mode_server_handler.py`, `cartographer_server_handler.py`, `reset_server_handler.py` — keep logic; use §4.1 launch manager; rviz config hot-swap: RViz2 has no load-config service → implement via `rviz2` restart with `-d <config>` (documented tradeoff; configs swapped by relaunching rviz2 process managed by the server).

**Launch (XML → Python launch in `openmover/launch/`):** 1:1 mapping of all 11 ROS 1 files: `bootloader.launch.py`, `workload.launch.py`, `hardwares/bringup.launch.py`, `apps/mapping.launch.py`, `apps/navigation.launch.py`, `apps/navigation/navigation.launch.py`, `modules/localization/{localization,carto_localization,carto_localization_server}.launch.py`, `modules/mapping/{carto_mapping,map_server}.launch.py`. Args (`system_mode`, `sim_area`, `init_diff_*`, `pbstream_filename`, `config_basename`, `map_filename`, ...) preserved. `use_sim_time` propagated. Sim branch additionally starts: `ros_gz_sim` world launch, `ros_gz_bridge` (config YAML), spawner, clock bridge. Real branch: `bluesea2` driver launches (§5.6).
- `tf/static_transform_publisher base_link→lidar_link` kept (ROS 2 static_transform_publisher args: `x y z yaw pitch roll frame_id child_frame_id`).

**URDF → xacro (`urdf/robot_description.urdf.xacro`):**
- Links/joints/inertials/meshes unchanged (mesh URIs → `package://openmover/meshes/...` still valid in ROS 2; also provide `file://` fallback via xacro arg).
- Replace `<gazebo>` blocks:
  - Diff drive → `gz-sim-diff-drive-system-plugin` (wheel_separation 0.324, wheel_radius 0.05035, topics per §4.6, odom frame `odom`, tf publish on).
  - `libgazebo_ros_laser.so` → `<sensor type="gpu_lidar">` blocks per §4.6.
  - Wheel/ball friction `<gazebo reference>` blocks kept (understood by gz-sim).
- `environment_description.urdf`: fix stale `package://ssir2/...` mesh URI → `package://openmover/meshes/environment_description/base_link.STL`; converted to a static SDF model included by the world (same as ROS 1 world did).

**Worlds:** `worlds/simulation.world` → `worlds/simulation.sdf` (gz-sim8 form per §4.6: physics 0.01 step / RTF 1, sun, 100×100 ground plane, static environment mesh model, spherical coords kept).

**Meshes:** copied unchanged.

**RViz:** new `rviz/openmover.rviz` for RViz2 (map, merged scan, TF, pose, path, markers) + 3 runtime configs seeded to `$OPENMOVER_HOME/config/rviz/` (idle, working, working_nomap). Topic remaps for RViz tools: `initialpose → openmover/localization/initialpose`, `goal → openmover/navigation/simple_goal` (configured in the rviz config file itself).

**Config/maps defaults:** `openmover/config_defaults/` (converted `hardwares.yaml`, `modules.yaml`, `navigation.yaml`, `mapping.yaml`, `apps/mapping/mapping.lua`, `apps/navigation/navigation.lua`) and `openmover/maps_defaults/simulation/*` copied from the ROS 1 repo root `config/` and `maps/`; seeded by `init_runtime_dirs`. Lua files are cartographer-core config → **unchanged** (ROS 2 port uses the same lua schema).

**package.xml deps (ROS 2):** `rclcpp, rclpy, std_msgs, geometry_msgs, nav_msgs, sensor_msgs, visualization_msgs, std_srvs, tf2, tf2_ros, tf2_geometry_msgs, tf2_sensor_msgs, tf2_eigen, laser_geometry, pcl_conversions, pcl_ros, nav2_costmap_2d, nav2_map_server (exec), cartographer_ros_msgs, cartographer_ros (exec), openmover_msgs, relocalization_toolbox_msgs, auto_mapping_toolbox_msgs, ira_laser_tools (exec), bluesea2 (exec), rosbridge_server (exec), ros_gz_sim/ros_gz_bridge (exec), xacro, robot_state_publisher, joint_state_publisher,Eigen3, PCL, OpenCV, OpenMP, osqp (system), yaml-cpp`.

### 5.4 `auto_mapping_toolbox`
- `auto_mapping_handler` port: same 7-state machine; `ros::AsyncSpinner`/callback queues → rclcpp `CallbackGroup` (Reentrant) + dedicated executor thread; boost R-tree code unchanged; tf1 helpers → tf2; costmap per §4.3; all `~/auto_mapping/*` params from `config.yaml` declared (convert `dist_gain`→`dist_gain_far/near` mapping to match code expectations — keep code behavior: declare both, yaml provides both).
- Keep all remap conventions (launch-side remaps identical to ROS 1 `apps/mapping.launch`).
- `nav_functions` service clients: `navigation/request`, `cmd_vel_mode/request` unchanged.

### 5.5 `relocalization_toolbox`
- `relocalization_2d_handler` port: services `relocalization_request`, `relocalization_simple_request` (`std_srvs/Empty` exists in ROS 2), client `set_init_pose_request`; `waitForMessage` → helper (§4.4); PCL GICP/yaml-cpp/Eigen code unchanged; OpenMP flags kept; all `~/relocalization_2d/*` params declared.

### 5.6 `bluesea2` (hardware driver)
- Vendor the official ROS 2 driver: `git clone https://github.com/BlueSeaLidar/bluesea-ros2` → `src/bluesea2` (package `bluesea2`, supports UDP, angle filter, inverted, from_zero, scan_topic/frame_id params — matches all params used in ROS 1 bringup).
- Add `openmover/launch/hardwares/bluesea2_forward.launch.py` / `..._rear.launch.py` replicating ROS 1 bringup config: UDP, lidar IPs 192.168.100.101/.102, lidar_port 502, local ports 6667/6668, 900 rpm, `with_angle_filter` ±1.57, `inverted`, topics `openmover/hardware/lidar_forward/scan` / `openmover/hardware/lidar_rear/scan`, frames `lidar_forward_link` / `lidar_rear_link`, respawn. (Parameter names adapt to the ROS 2 driver's schema — verified against its template at implementation time.)
- The old ROS 1 driver code is not ported (vendor replacement covers it; documented in comparison guide).

### 5.7 `ira_laser_tools` (rclcpp port)
- `laserscan_multi_merger`: replace `ros::master::getTopics()` with `node->get_topic_names_and_types()`; tf1 listener → `tf2_ros::Buffer`; `dynamic_reconfigure` → declared params (`angle_min/max`, `angle_increment`, `range_min/max`, `scan_time`, `destination_frame`, `laserscan_topics`, `scan_destination_topic`, `cloud_destination_topic`) applied on set-parameter callback. Same merge semantics (laser_geometry → PCL transform → single scan + cloud, frame `lidar_link`, 360°, 0.33–20 m).
- `laserscan_virtualizer`: ported similarly (kept for completeness, unused by robot).

### 5.8 `warehouse_simulation` (demo migration)
- New `warehouse_simulation` ament_cmake package:
  - `worlds/warehouse.sdf`: gz-sim8 world including the existing `models/workcell` + `models/workcell_bin` (convert model.config/model.sdf to gz format; meshes/textures copied). Note: the ROS 1 launch referenced a missing `warehouse.world` — we recreate a proper world from the shipped models.
  - Pioneer3DX: self-contained `urdf/pioneer3dx.urdf.xacro` (chassis, 2 driven wheels, caster, hokuyo-style lidar) with gz diff-drive + gpu_lidar plugins; ros_gz bridge for `cmd_vel`/`odom`/scan.
  - SLAM: `slam_toolbox` async node (replaces gmapping) with params matching ROS 1 (map 24×24 m @0.05, max range 10).
  - Nav stack: **Nav2** (replaces move_base): `nav2_bringup`-style param file derived from the 6 ROS 1 yaml files (NavfnROS → `nav2_navfn_planner/NavfnPlanner`, TrajectoryPlannerROS → DWB with equivalent limits, costmap layers mapped 1:1 incl. voxel layer, robot_radius 0.25, inflation 1.0/2.58).
  - `key_control` ported to rclcpp (same key semantics, `cmd_vel` @ Twist).
  - `trajectory_server.py` (small rclpy node) replaces `hector_trajectory_server` (map→base path @10 Hz).
  - `rviz/navigation.rviz` recreated for RViz2.
  - `warehouse_simulation.launch.py` orchestrates all of the above (with `use_sim_time`).

### 5.9 Provisioning (`tools/setup.sh`)
Replaces ROS 1 `install.sh`: apt installs (`ros-jazzy-rosbridge-server`, `ros-jazzy-pointcloud-to-laserscan`, `ros-jazzy-joy`, `python3-pynput`, `python3-pygame`, `python3-colcon-common-extensions`, `libpcl-dev`, `libeigen3-dev`, `libopencv-dev`, `libyaml-cpp-dev`, `libboost-dev`, `cmake`, `ninja-build`), builds+installs OSQP from `openmover_robot/osqp/` (cmake/ninja → /usr/local), `rosdep install` for the workspace, then `colcon build`.

---

## 6. Testing & Verification (user-requested, all three)

### 6.1 Golden-value unit tests (GTest, `colcon test`)
Location: `*/test/` per package. Goldens committed as CSV under `test/golden/`.
- `openmover`: `math_utils` (pose ops, angle wrap), `crc8_maxim` (known vectors), global planner (dijkstra expansion + gradient/grid traceback on a synthetic 50×50 costmap, fixed start/goal → golden path), OSQP smoother (fixed waypoints → golden smoothed polyline), `controllers` (fixed inputs → golden cmd outputs).
- `relocalization_toolbox`: likelihood-field scoring on synthetic map+scan (golden scores), sector_query/sampling determinism.
- `auto_mapping_toolbox`: frontier scoring `info_gain/dist_gain/dir_gain/free_gain` (golden scores), TSP ordering on fixed node set.
- `openmover_msgs`: roundtrip serialization sanity.
- **ROS 1 golden generator**: `tools/golden/gen_golden_ros1.sh` — Dockerfile (ros:noetic) that mounts `openmover_robot`, builds the same pure-algorithm test binaries against ROS 1 code, and dumps the same golden CSVs (user runs this on their Docker-capable PC to cross-validate goldens).

### 6.2 Sim integration test (`openmover/test/sim_integration/`)
Python `launch_test` (runs headless, `gz sim` headless render):
1. Launch sim stack (`system_mode:=0`, `use_sim_time:=true`).
2. Wait-for-topics assertions: merged scan, odom, TF tree completeness (`map→odom→base_link→lidar_*` once cartographer up).
3. Drive test: enable manual mode (`cmd_vel_mode/request manual:=true`), publish scripted `cmd_vel_manual` square; assert `openmover/hardware/odom` displacement vs ground truth from gz (`/model/openmover/odometry`), tolerance-based.
4. Mapping smoke: start mapping mode via `set_func_mode`; wait for `openmover/mapping/map` non-empty; call auto_mapping start/cancel; assert `auto_mapping/state` transitions.
5. Localization smoke: stop mapping, save state (WriteState), switch to localization mode, assert `openmover/localization/pose` within tolerance of gz ground truth after `initialpose`.

### 6.3 ROS1-vs-ROS2 comparison guide (`docs/comparison.md` + `tools/comparison/`)
User-requested deliverable (docs allowed):
- `record_run.sh` (ROS 2): scripted teleop square run; records rosbag2 + exports `openmover/localization/pose`, `openmover/hardware/odom`, `openmover/control/cmd_vel` to CSV via a recorder node.
- `record_run_ros1.sh` + Dockerfile (ros:noetic, X11/`--network host` for Gazebo classic): same scripted run in the original repo; `rostopic echo -b` export to CSV.
- `compare.py`: time-aligned interpolation, RMSE/max-error tables for pose & odom, map similarity (IoU on occupancy) when both maps saved; prints PASS/FAIL vs configurable thresholds.

---

## 7. Implementation Order (execution phases)

1. **Phase 0 – Provisioning**: `tools/setup.sh`; run apt installs + OSQP build; create workspace skeleton.
2. **Phase 1 – Interfaces**: `openmover_msgs`, `auto_mapping_toolbox_msgs`, `relocalization_toolbox_msgs`; build + verify generated headers.
3. **Phase 2 – Core libs + golden unit tests**: port ROS-independent libs first (math_utils, crc8, planner stack, likelihood fields, controllers...), add GTests + goldens; `colcon test`.
4. **Phase 3 – openmover C++ nodes**: driver trio → teleop → localization pair → obstacle → navigation_handler (+GetPlan) → wiring; build incrementally.
5. **Phase 4 – Python layer**: `openmover_py` (launch_manager, topic utils) → hal/cli/protocol → 5 servers → teleop/speaker/workload; `init_runtime_dirs` seeder.
6. **Phase 5 – Toolboxes**: `auto_mapping_toolbox`, `relocalization_toolbox` ports + their unit tests.
7. **Phase 6 – `ira_laser_tools`** port (merger + virtualizer).
8. **Phase 7 – `bluesea2`** vendor clone + openmover bringup overlays (real-robot branch).
9. **Phase 8 – Simulation stack**: xacro + gz world + ros_gz bridge YAML + spawn; cartographer mapping/localization launches (lua unchanged); map server/saver; rosbridge; rviz2 configs; **full launch-file set**.
10. **Phase 9 – `warehouse_simulation`** migration.
11. **Phase 10 – Tests**: sim integration test, comparison tooling + docs.
12. **Phase 11 – End-to-end verification**: `colcon build && colcon test`; run sim workload; manual scripted flow (teleop → mapping → save → localize → nav_to goal); fix until green.

---

## 8. Assumptions & Decisions Log

1. Cartographer ROS 2 binary port is the SLAM choice (user-confirmed); lua configs and existing `.pbstream` files (`maps/simulation/navigation.pbstream`) reused as-is (pbstream format is version-stable across cartographer 2.0; verified at runtime in Phase 11 — fallback: regenerate the sim pbstream by re-mapping in ROS 2 if an edge-case incompatibility appears).
2. All ROS 1 topic/service/frame/param names preserved (parity-first). Exceptions forced by ROS 2: srv files flattened, `navfn/MakeNavPlan` → `nav_msgs/GetPlan`, `sensor_msgs/PointCloud` → `PointCloud2`, dynamic_reconfigure → parameters.
3. `openmover_ws` = `/home/zar/Documents/phd/robot/openmover_ws`; ROS 1 repo untouched (reference + golden generator + comparison runs).
4. Runtime dirs stay at `~/openmover_robot/{config,maps,sounds,logs}` (overridable via `OPENMOVER_HOME`), seeded from in-repo defaults without overwriting existing user data.
5. bluesea2: official vendor ROS 2 driver (not a manual port) — lower risk, actively maintained; hardware not testable here (launch config mirrors ROS 1 params exactly).
6. RViz config hot-swap → managed rviz2 relaunch (RViz2 has no ROS 1-style load-config service).
7. Orphan `global_planner_handler` merged into `navigation_handler` as `GetPlan` service (hal.py behavior preserved).
8. `use_sim_time` is a launch-level argument threaded through all sim components; real-robot mode unaffected.
9. OSQP built from vendored source (not in Ubuntu 24.04 apt).
10. `warehouse_simulation` rebuilt around its shipped workcell models (original `warehouse.world` was missing from the repo).

## 9. Risks & Mitigations
| Risk | Mitigation |
|---|---|
| Nav2 `Costmap2DROS` lifecycle complexity in custom nodes | Pattern fixed in §4.3; dedicated executor thread; validated by sim integration test |
| gz bridge topic/frame mismatches | Central bridge YAML with explicit types + `frame_id` overrides; integration test asserts scan frames |
| pbstream incompatibility across cartographer builds | Test loading early (Phase 9); fallback re-mapping run; slam_toolbox available as documented alternative |
| Dynamic `ros2 launch` subprocess management edge cases (zombies, restart races) | Process-group kill + grace period + `is_alive` guards; servers unit-tested with dummy launch files |
| ROS 2 driver param schema differences (bluesea2) | Verify against vendor template during Phase 8; keep ROS 1 topic names via remaps |
| Performance of 2× gpu_lidar + bridge in sim | gz `update_rate` matching ROS 1 (15 Hz); headless test uses `--headless-rendering` |

## 10. Verification Checklist (final)
- [ ] `colcon build` clean, zero ROS 1 dependencies in any package.xml (`colcon list` + grep for roscpp/catkin).
- [ ] `colcon test` green (all golden unit tests).
- [ ] `ros2 launch openmover workload.launch.py system_mode:=0` → sim drives, maps, saves pbstream+pgm, localizes on saved map, nav_to reaches goal.
- [ ] Real-robot branch launch files start without hardware errors only where testable; config parity table in docs.
- [ ] Sim integration launch-test passes headless.
- [ ] `warehouse_simulation.launch.py` runs Nav2 + slam_toolbox in Gazebo Harmonic with key_control.
- [ ] Comparison tooling runs and produces the RMSE/IoU report template.
