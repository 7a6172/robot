# The `isaac/` Tree

All Isaac-side work lives in `openmover_ws/isaac/`. Numbered scripts are gate artifacts from
Steps 1.0–1.5 (they run standalone and keep their instrumentation); shared modules are
imported by them.

## Scripts (`isaac/scripts/`)

### Shared modules (imported, not run)

| File | Role |
|---|---|
| `common.py` | Paths (`ASSETS_DIR`, `SCENES_DIR`), `preflight()` RAM/stray-sim guard |
| `bridge_core.py` | Simulator-side robot interface: velocity servo on the two drive wheels (`KD = 20.0`), unicycle→diff kinematics (`WHEEL_SEPARATION = 0.32`, `WHEEL_RADIUS = 0.09`), `step(render=...)`, ground-truth `get_odom()` |
| `lidar_mirror.py` | RTX 2D LiDAR mirror of the bluesea2 chain: 600 samples, ±90°, 0.22–10 m, 15 Hz; front/rear mount poses; `mount_bluesea2_pair()` |

### Gate scripts

| Step | Script | What it proves/builds |
|---|---|---|
| 1.0 | `00_smoke_test.py` | Headless SimulationApp boots; peak RSS measured (12.3 GiB) |
| — | `01_introspect_api.py` | Dumps API signatures the bring-up uses |
| 1.1 | `10_import_urdf.py` | pioneer3dx URDF → USD, once (output: `assets/pioneer3dx/`) |
| 1.1 | `11_verify_robot.py` | **Gate:** imported USD is drivable |
| 1.2 | `12_probe_lidar.py`, `12_lidar_setup.py` | RTX 2D LiDAR pipeline characterised; **gate:** two bluesea2 mirrors mounted on the robot see geometry |
| 1.3 | `13_bridge_core.py` | **Gate:** `cmd_vel`-style targets in → odom out; robot drives |
| 1.4a | `14_build_simple_room.py`, `14_scene_room.py` | Simple-room USD built; **gate:** robot drives, both lidars see walls |
| 1.4b | `15_build_warehouse.py`, `15_convert_workcell_mesh.py`, `15_probe_mesh_only.py`, `15_scene_warehouse.py` | Warehouse workcell USD (collision boxes) + converted COLLADA mesh (visual); **gate:** robot spawns at the Gazebo spawn pose, lidars see the workcell |
| 1.5 | `16_probe_rclpy.py` | Preflight: rclpy works inside Isaac's Python |
| 1.5 | `16_bridge_ros.py`, `16_stack_b.launch.py` | **Stack B bridge** (see 03) + its ROS-side launch |
| 1.5 | `17_bridge_openmover.py` | **Stack A bridge** (see 03) |

## Assets (`isaac/assets/`)

- `pioneer3dx/` — USD import of the Pioneer 3DX URDF (Step 1.1). **Note:** this is the
  platform chassis, not the openmover URDF; Isaac uses its kinematics (wheel separation
  0.32 m, wheel radius 0.09 m) while the openmover Gazebo DiffDrive plugin uses
  0.324 / 0.05035. Internally consistent within Isaac; importing the openmover URDF is a
  logged follow-up.

## Scenes (`isaac/scenes/`)

| File | Contents |
|---|---|
| `simple_room.usda` | Step 1.4a demo room |
| `warehouse.usda` | Warehouse workcell: **collision boxes** baked from the Gazebo SDF + spawn layout |
| `workcell_mesh.usdc` + `workcell_mesh_textures/` | Converted COLLADA workcell mesh, **visual-only** (RTX raytracing target); placed at the workcell model pose `(WC_X, WC_Y) = (-0.040107, 0.052292)` to align with the collision boxes |

## ROS-side changes (the only ones)

Approved exception to "zero ROS changes" — two launch files, both symlink-installed:

- `src/openmover/launch/hardwares/bringup.launch.py` — new `launch_gazebo` argument
  (default `'1'`). `gz_sim`, `ros_gz_bridge`, the `ros_gz_sim create` spawn node and the
  gz resource-path setup now require `system_mode == 0 and launch_gazebo == 1`
  (`gz_cond`). Everything else — `simulation_handler`, `teleop_node`, localization,
  merger, obstacle handler, speaker — is unchanged and still gated by `system_mode` alone.
- `src/openmover/launch/bootloader.launch.py` — declares and forwards `launch_gazebo`.
  `use_sim_time` stays `(system_mode == 0)`.

`system_mode` semantics are untouched (no new mode number), so the five Python handlers
that compare `system_mode == 0/1` needed no edits. Known quirk: `workload.launch.py` does
not forward args to bootloader — bring up via `bootloader.launch.py` directly.
