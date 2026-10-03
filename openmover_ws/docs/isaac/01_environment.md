# Environment & Runtime

## Machine

| Item | Value |
|---|---|
| OS | Ubuntu 24.04 LTS |
| CPU | i7-12700K (20 logical cores available) |
| RAM | 16 GiB + 24 GiB swap — **workload killer territory; see RAM guard** |
| GPU | NVIDIA RTX 3080, 10 GiB VRAM (driver 580.x, Vulkan) |
| ROS | ROS 2 Jazzy (`/opt/ros/jazzy`) |

The machine has hard-frozen twice before under full simulation load. All Isaac work follows
the RAM guard below.

## Isaac Sim install

- Version **6.0.1-rc.7** at `~/isaacsim` (release candidate; stable 6.0.1 zip is the fallback
  if odd bugs appear — no work would be lost).
- **Headless only.** Scripts create `SimulationApp({"headless": True,
  "enable_motion_bvh": True})`. `enable_motion_bvh` is required: without it the RTX LiDARs do
  not see the robot as it moves.
- Scripts run inside Isaac's **bundled Python 3.12** — never system python:

  ```bash
  source /opt/ros/jazzy/setup.bash          # only needed when the script uses rclpy
  ~/isaacsim/python.sh openmover_ws/isaac/scripts/<script>.py
  ```

- `SimulationApp` startup takes ~10 s (app-up line prints `[bridge] app up in ... s`).
  A full scene bring-up including physics settle is ~30–60 s.

## Isaac Lab install

- **Isaac Lab 3.0** at `~/isaaclab`, installed with `./isaaclab.sh --install` (not pip).
  It bundles **its own Isaac Sim** at `~/isaaclab/_isaac_sim` — separate from `~/isaacsim`;
  the two never run at the same time (RAM guard).
- Scripts run inside the bundled Python via the wrapper:

  ```bash
  cd ~/isaaclab && ./isaaclab.sh -p <script>.py [args]
  ```

- API notes for this version:
  - `AppLauncher`/task registry import clean (`isaacsim` from `_isaac_sim`, `isaaclab`
    editable from `source/`).
  - `--headless` is deprecated: default is headless unless `--viz` is given.
  - The stock `zero_agent.py` / `random_agent.py` loop **forever** without a visualizer;
    bounded runs need a capped loop (`/tmp/isaaclab_smoke.py` pattern:
    `resolve_task_config` + `launch_simulation` + `gym.make(task, cfg=env_cfg)`).
  - `env.step()` observations are a **dict** of tensors (`{'policy': ...}`).
- Verified 2026-09-02: `Isaac-Cartpole-Direct-v0`-style bounded runs, 1 env, 16 zero-action
  steps, headless on `cuda:0`, exit 0 (`[smoke] OK: 16 steps done`).

## Isaac Lab openmover env (training scaffold)

The NMTE training scaffold lives in `openmover_ws/isaac/lab/` (package `openmover_lab`),
built on Isaac Lab's `DirectRLEnv`:

- Task: **`Isaac-Nav-Openmover-v0`** — differential-drive point-goal navigation.
  Obs 1204-d = 600 front + 600 rear ray-cast ranges (normalized; miss = 1.0) + goal xy in
  robot frame + (vx, wz). Actions = 2 wheel velocity targets, ±10 rad/s. Decimation 6 @
  1/120 s → 20 Hz control; 15 s episodes; goal ring 1.5–3.0 m; success < 0.15 m;
  collision = base contact force > 5 N.
- Robot asset: product URDF converted once (`isaac/sim/20_convert_openmover_urdf.py`) to
  `isaac/assets/openmover_lab/robot_description/robot_description.usda` (layered USD).
  Velocity drives are env-level `ImplicitActuatorCfg` (stiffness=0, damping=Kv=2.0 —
  see 05 for why).
- Sensors: two `RayCasterCfg` LiDARs (bluesea2 spec: 600 rays, ±90°, 10 m, 15 Hz) against
  the terrain mesh + one `ContactSensorCfg` on the base.
- Terrain & **environment factory** (2026-09-03): `openmover_lab/openmover_terrains.py`
  defines the worlds as procedural sub-terrain generators (32×32 tiles of 8×8 m, cached
  under `/tmp/isaaclab/terrains`):
  - **Source** — `wall_maze_terrain` (`OPENMOVER_TERRAINS_CFG`, seed=42): flat room,
    boundary walls + 4–12 random interior walls (difficulty-scaled), obstacle-free spawn
    platform at the center.
  - **Rail yard** (Target-1 geometry) — `rail_yard_terrain` (`RAIL_YARD_TERRAINS_CFG`,
    seed=43): boundary fence, one standard-gauge (1.435 m) two-rail track band crossing
    the tile with a level-crossing gap, plus rejection-sampled clutter (cable ducts,
    tool carts, one maintenance vehicle at p=0.6) kept clear of the spawn platform and
    the track band. Per the paper scope the floor is a flat depot — ballast is
    explicitly out.
- **Env factory = one env class, four registered tasks** (same obs/action spaces,
  different cfg subclasses in `openmover_nav_cfg.py`):

  | Task | Geometry | Dynamics |
  |---|---|---|
  | `Isaac-Nav-Openmover-v0` | wall-maze | nominal (µ=1.0, 10 rad/s wheels) |
  | `Isaac-Nav-Openmover-RailYard-v0` | rail yard | nominal |
  | `Isaac-Nav-Openmover-Degraded-v0` | wall-maze | degraded (µ=0.25, 6 rad/s wheels) |
  | `Isaac-Nav-Openmover-Combined-v0` | rail yard | degraded |

  v1 caveats: degraded dynamics are global (no spatial friction patches, latency, or
  sensor noise yet); goal reachability inside cluttered tiles is not enforced. All four
  gym specs CPU-validated 2026-09-03; both terrain meshes valid (256×256 m, 32×32
  origin grids, ~99k verts each).
- Runner: `isaac/lab/21_run_openmover_nav.py` (bounded loop, `--num_envs`, `--task`,
  `--policy zero|random|forward|trained`, `--checkpoint` for trained rollouts via an
  in-script `OnPolicyRunner` load). Validated 2026-09-02 with obstacle terrain: scans
  informative (per-slice min ≈ 0.04–0.12, mean ≈ 0.39, i.e. walls at 0.4–4 m), forward
  policy → wheels track 10 rad/s, collision terminations fire (collision rate 0.77
  forward / ~1.0 random).
- Scaling on the RTX 3080 (headless, random policy), 2026-09-02:

  | num_envs | env-steps/s (flat) | env-steps/s (wall-maze) |
  |---|---|---|
  | 4 | ~160 | — |
  | 64 | ~2,570 | ~2,380 |
  | 256 | ~9,760 | ~6,430 |
  | 1024 | ~27,570 | ~11,420 |

  Obstacle ray-casting costs ~2–2.4×, still near-linear; 1024 envs fit comfortably.
  Plenty for PPO on this obs size.
- Training: RSL-RL PPO via `isaac/lab/22_train_openmover_nav.py` (registers the external
  task, then delegates to the stock unified trainer; agent cfg in
  `openmover_lab/rsl_rl_ppo_cfg.py`: MLP [128,128], adaptive LR 3e-4, clip_actions=1).
  First run 2026-09-02 (256 envs, 300 iters, ~8.5k steps/s, 238 s): mean reward
  −5 → +6.4, episode length 40 → 235/300 steps; success 0 at this budget (expected —
  goal-reaching needs far more iterations). Logs/checkpoints under
  `isaac/lab/logs/rsl_rl/openmover_nav/<timestamp>_<run>/` (runbook in 04).

## RAM guard (common.preflight)

Every Isaac script must call `common.preflight(label)` **before** constructing
`SimulationApp` (see `isaac/scripts/common.py`):

- **Abort** if `MemAvailable < 8 GiB`.
- **Warn** if `MemAvailable < 12.5 GiB` (the empty headless sim peaked at 12.3 GiB RSS in
  Step 1.0; 24 GiB swap is the backstop, not the plan).
- **Warn** on stray simulator processes (`gz sim`, `omni.kit`, `isaac-sim.sh`, `ruby`) —
  one simulator at a time.

Observed memory behavior: the bridge process RSS grows across a run (up to ~6 GiB for the
bridge alone). Restarting the bridge between long sessions recovers the RAM. Check with
`grep MemAvailable /proc/meminfo` before and after heavy runs.

## Operating rules (from the approved plan)

1. Headless Isaac only (for now).
2. No changes to ROS packages without explicit approval. Approved so far: exactly the
   `launch_gazebo` launch argument in `bringup.launch.py` / `bootloader.launch.py`.
3. One heavy process at a time; monitor RAM.
4. ROS configs are read-only specs for the Isaac side (bluesea2 driver config,
   `config_defaults/gz_bridge.yaml`, URDF).

## Workspace layout (relevant parts)

```
openmover_ws/
├── src/                  ROS 2 packages (untouched except the launch_gazebo change)
├── isaac/                Isaac side
│   ├── scripts/          numbered gate scripts + shared modules (Isaac Sim bridges)
│   ├── assets/pioneer3dx/   URDF-imported robot (USDA) for the bridges
│   ├── assets/openmover_lab/  URDF→USD robot for Isaac Lab (converted 2026-09-02)
│   ├── lab/              Isaac Lab env package (openmover_lab) + runner scripts
│   └── scenes/           simple_room.usda, warehouse.usda, workcell_mesh.usdc
├── docs/
│   ├── knowledge/ research/ *.html   existing ROS 2 docs
│   └── isaac/            this set (md) + index.html (humans)
└── install/              colcon, symlink-install (launch edits go live without rebuild)
```
