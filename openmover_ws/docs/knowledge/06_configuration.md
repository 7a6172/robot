# 06 — Configuration Reference

## Stack A config layout (`src/openmover/config_defaults/`)

Installed to the package share dir; launch files read them via
`get_package_share_directory('openmover')`.

```
config_defaults/
├── hardwares.yaml      robot geometry + hardware endpoints
├── modules.yaml        teleop & obstacle module params
├── gz_bridge.yaml      Gazebo↔ROS topic map (sim mode)
├── apps/
│   ├── mapping/mapping.{yaml,lua}       mapping-app params + Cartographer lua
│   └── navigation/navigation.{yaml,lua} nav-app params + Cartographer lua
└── rviz/{idle,working,working_nomap}.rviz
```

### hardwares.yaml (namespace `/**`)
- Footprint (used by costmaps / collision checker).
- Motor: IP `192.168.100.100`, port 23, control frequency, wheel radius, chassis radius.
- IO board: port 26, battery-low threshold, localization-confidence threshold.

### modules.yaml
- Teleop: max linear/angular velocities and accelerations.
- Obstacle detection: ranges/grid sizing for `obstacle_handler`.

### apps/navigation/navigation.yaml — sections and what they tune
- `relocalization_2d:` — mirrors `relocalization_toolbox/config/config_2d.yaml`:
  frames (`map_frame`, `base_frame`, `lidar_frame`), delivery flags
  (`publish_init_pose_topic: true`, `call_init_pose_request: false`),
  RRT sampling (`use_reachability_sampling`, expand distances, `min_dist_to_obstacle: 0.21`,
  `reachability_sampling_duration`), scoring (`fit_score_threshold_max: 0.95`,
  `fit_score_threshold_min: 0.85`, `angle_search_step: 0.26`, batch/candidate counts),
  likelihood model (`sigma_hit: 0.2`, `z_hit`, `max_tolerance_dist: 3.0`, map thresholds,
  `sensing_radius: 10.0`), GICP (correspondence distance, iterations).
- Navigation controller + path follower params (speeds, tolerances).
- `global_planner:` and `global_planner_static:` — custom planner settings.
- `global_costmap:` / `global_costmap_static:` — nav2_costmap_2d sections
  (static + obstacle layers; observations from `openmover/hardware/lidar/scan`).
- `localization_confidence:`, `reset_server:` sections.

### apps/mapping/mapping.yaml
Same structure but mapping-tuned: auto_mapping frontier gains
(`info_gain`, `dist_gain`, `dir_gain`, `free_gain`), `exploration_min_dist_to_obs` (0.36),
`planner_min_dist_to_obs` (0.356), costmap ranges. Note: `dist_gain_far`/`dist_gain_near` and
`rrt_sampling_duration`-vs-`reachability_sampling_duration` include **dead keys preserved for
ROS 1 parity** — do not "clean them up".

### Cartographer .lua conventions
`map_frame="map"`, `tracking_frame="base_link"`, `published_frame="odom"`,
`provide_odom_frame=false`, `use_odometry=true`. Mapping config: `mapping.lua`;
localization config: `navigation.lua` (+ `.pbstream` state).

## Maps

| Item | Format | Location |
|---|---|---|
| Shipped sim map | `navigation.yaml` (resolution 0.02, origin) + `.pgm` + `.pbstream` | `src/openmover/maps_defaults/simulation/` |
| Runtime maps | same trio | `~/openmover_robot/maps/{simulation,real-world}/<name>.*` |
| map_server default | yaml path arg | `map_filename` launch arg, defaults to the shipped sim map |

The pgm+yaml pair is the classic ROS map_server format (also what `relocalization_toolbox`
reads in file mode); the pbstream is Cartographer's serialized state, loaded per map name by
`cartographer_server_handler`.

## Toolbox standalone configs (reference defaults; openmover YAML overrides at launch)

- `auto_mapping_toolbox/auto_mapping_toolbox/config/config.yaml` — exploration/planning defaults.
- `relocalization_toolbox/relocalization_toolbox/config/config_2d.yaml` — relocalization defaults
  (bilingual comments).

## Stack B config (`src/warehouse_simulation/config/`)

- `nav2_params.yaml` — full Nav2 stack: **MPPI controller** (`controller_frequency: 20.0`,
  `model_dt: 0.05` — invariant `frequency·model_dt == 1` is enforced by a test;
  `vx_max 1.0`, `vx_min −0.35`, `wz_max 1.9`), goal checker (xy 0.2 m, yaw 0.12 rad),
  costmaps with voxel layer params carried from ROS 1 move_base.
- `slam_toolbox.yaml` — async online mapping (`mode: mapping`, resolution 0.05,
  `max_laser_range: 10.0`, scan topic `/scan`, `minimum_time_interval: 0.2`, `use_sim_time: true`).
- `gz_bridge.yaml` — `/cmd_vel` (ROS→GZ `/model/pioneer3dx/cmd_vel`), `pioneer_odom→/odom`,
  `pioneer_tf→/tf`, `pioneer_joint_states→/joint_states`, `scan→/scan`, `/clock` (GZ→ROS).
- `rviz/navigation.rviz`.

## Runtime directories & environment

```
~/openmover_robot/maps/       map save/load (nav_map_save_path = $HOME/openmover_robot/maps/)
~/openmover_robot/sounds/     speaker assets (sound_filepath in bringup)
~/openmover_robot/logs/       HAL logger output
GZ_SIM_RESOURCE_PATH          set by launch (sim only) so model:// & package:// resolve
```
Env var `OPENMOVER_HOME` is mentioned in `docs/hardware.html` but is **not implemented** —
code consistently uses `$HOME`. Do not rely on it.

## Tuning cheat-sheet (what to change for common goals)

| Goal | Where |
|---|---|
| Slower/faster teleop | `modules.yaml` teleop section |
| Robot keeps hitting obstacles | costmap inflation + `exploration/planner_min_dist_to_obs` in app YAMLs |
| Relocalization too slow | lower `area_batch_proc_number`, raise `fit_score_threshold_max` (fewer refinements) |
| Relocalization fails in open spaces | check `min_dist_to_obstacle`, RRT sampling duration, `sigma_hit` |
| Auto-mapping wanders inefficiently | frontier gains (`info_gain` vs `dist_gain` vs `dir_gain`) in `mapping.yaml` |
| Nav2 too aggressive / too timid (Stack B) | MPPI critics + velocity limits in `nav2_params.yaml` |
| LiDAR blanking sectors (real) | bluesea2 `mask1..8`, `min/max_dist`, `inverted`, `reversed`, `zero_shift` |
