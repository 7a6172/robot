# 07 — Build System & Tooling

## Build rules (hardware constraint!)

The primary dev machine has **16 GB RAM** and has hard-frozen twice under full-parallel builds /
full-load simulation. Canonical build command:

```bash
cd /home/zar/Documents/phd/robot/openmover_ws
source /opt/ros/jazzy/setup.bash
MAKEFLAGS="-j2" CMAKE_BUILD_PARALLEL_LEVEL=2 colcon build --symlink-install --parallel-workers 2
```

- Selective rebuild: `--packages-select <pkg>` (e.g., after editing one package).
- `--symlink-install` means: package.xml, YAML, launch files, Python scripts are **symlinked**
  (live, no rebuild needed); C++ changes still need rebuild.
- After C++ edits in one package:
  `MAKEFLAGS="-j2" colcon build --symlink-install --parallel-workers 2 --packages-select <pkg>`.
- Comment-only edits to headers/sources need **no** rebuild.
- RAM tiers (used by docs + setup.sh): ≥32 GB → up to 8 jobs; 16–31 GB → 2 jobs;
  8–15 GB → 1 job + headless; <8 GB → not supported.

## Tools (`openmover_ws/tools/`)

| Script | Role | Key facts |
|---|---|---|
| `check_system.sh` | Read-only health check; exit 0 = OK | OS=Ubuntu 24.04, ROS Jazzy, colcon, gz sim 8.x, ~30 apt deps, OSQP in `/usr/local`, GPU, RAM (fail <4 GB free / warn <15 GB total), stale `gz sim`/`ruby` processes, workspace layout |
| `install_deps.sh` | Dependency installer (`sudo bash …`) | Requires Jazzy present; apt base tools → ROS/system packages → `rosdep install --from-paths src` → builds vendored OSQP (`tools/osqp_build`, `-j2`) into `/usr/local` |
| `setup.sh` | Interactive setup wizard | Flags: `--check` (detect only), `--yes`, `--jobs N`. Detects OS/ROS/colcon/gz/OSQP/GPU/disk/RAM (MB thresholds: ≥28672→≤8 jobs, ≥14336→2, ≥7168→1, else INSUFFICIENT). Menu: full setup / deps only / build only / tests only / re-detect |

Vendored OSQP trees: `tools/osqp_build/` (source+build) and `tools/osqp06_install/`
(prebuilt headers + libs). OSQP is required by `auto_mapping_toolbox`'s path smoother and is
intentionally a system-level dep (accepted known minor — not in package.xml).

## Tests

```bash
colcon test --packages-select warehouse_simulation && colcon test-result --verbose
```
6 pytest tests: static YAML validation (nav2_params sections, MPPI plugin name,
`controller_frequency·model_dt == 1` invariant, slam_toolbox mode, gz bridge mappings) and a
functional `trajectory_server` test. Run after any config change in Stack B.

## Sourcing / environment

```bash
source /opt/ros/jazzy/setup.bash          # ROS underlay
source install/setup.bash                 # workspace overlay (in openmover_ws)
```
`use_sim_time` is passed as a launch argument everywhere (no global param-server convention).
Simulation needs `/clock` bridged (done in both gz_bridge.yaml files).

## Troubleshooting table

| Symptom | Cause / fix |
|---|---|
| Machine becomes unresponsive during build/sim | Full parallelism or two sims at once — kill power is the only way out; always use `-j2`, one sim, `headless:=true` for long runs |
| `gz sim` won't start / port busy | Stale process: `pgrep -af 'gz sim\|ruby'`, kill, retry |
| Bridge topics missing | Entity name mismatch (`/model/pioneer3dx/cmd_vel`) or bridge YAML direction/type typo |
| No `map→odom` TF (Stack B) | slam_toolbox lifecycle node inactive — the 12 s activation timer handles it; check `ros2 lifecycle get /slam_toolbox` |
| Cartographer ignores initialpose | ROS 2 cartographer has no initialpose topic; the adapter node translates to trajectory services — ensure it's running |
| LiDAR scan empty (real) | bluesea2 `type`/IP/port params, network route, motor stopped (`start_motor` service) |
| Import errors in HAL scripts | Run installed entry points (`ros2 launch/run openmover …`), not source paths; hal libs install flat into lib/openmover |
| OSQP link errors | `/usr/local/lib/libosqp.so` missing → `sudo bash tools/install_deps.sh` |

## HTML documentation (for humans)

`openmover_ws/docs/`: index, getting_started, build, architecture, packages, usage, hardware,
audit, changelog + `style.css`. Keep them in sync when changing behavior; this knowledge base is
the AI-facing twin of that set.
