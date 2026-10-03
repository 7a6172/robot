# Runbooks

All commands assume `cwd = /home/zar/Documents/phd/robot`. Every terminal that runs ROS
tooling needs:

```bash
source /opt/ros/jazzy/setup.bash && source openmover_ws/install/setup.bash
```

**Before any Isaac run:** `grep MemAvailable /proc/meminfo` — need ≥ 8 GiB (preflight aborts
below), ideally ≥ 11 GiB. Kill stray simulators (`gz sim`, other Kit instances). One
simulator at a time.

## Stack B — warehouse_simulation against Isaac

Terminal 1 (ROS side; slam_toolbox + merger + teleop, optionally Nav2):

```bash
ros2 launch openmover_ws/isaac/scripts/16_stack_b.launch.py            # nav:=false default
# ros2 launch openmover_ws/isaac/scripts/16_stack_b.launch.py nav:=true rviz:=true
```

Terminal 2 (Isaac side; wait for `[bridge] live:` then heartbeat lines):

```bash
source /opt/ros/jazzy/setup.bash && ~/isaacsim/python.sh openmover_ws/isaac/scripts/16_bridge_ros.py
```

Verification:

```bash
ros2 topic hz /scan                      # merged 360° scan, ~15 Hz
ros2 topic echo /map --once --qos-durability transient_local   # slam_toolbox map
# NOTE: /map is published TRANSIENT_LOCAL — a volatile subscriber sees nothing
ros2 run tf2_ros tf2_echo odom base_link
```

Teleop: keyboard via the launch's teleop node, or scripted (drives forward, stops, turns):

```bash
python3 /tmp/teleop_test.py              # publishes /cmd_vel, reads /odom
```

Nav2 gate: send a goal (e.g. via rviz or `ros2 action send_goal /navigate_to_pose ...`);
expected `SUCCEEDED`, error_code 0.

## Stack A — openmover product stack against Isaac

Terminal 1 (Isaac side first; wait for `[bridge] live:` and the 5 s heartbeats):

```bash
source /opt/ros/jazzy/setup.bash && ~/isaacsim/python.sh openmover_ws/isaac/scripts/17_bridge_openmover.py
```

Terminal 2 (product stack, Gazebo swapped out):

```bash
ros2 launch openmover bootloader.launch.py system_mode:=0 sim_area:=0 launch_gazebo:=0
```

- `system_mode:=0` — simulation mode (unchanged semantics; `use_sim_time` derives true).
- `sim_area:=0` — spawn at origin, yaw 0, matches the Isaac scene.
- `launch_gazebo:=0` — the new arg: skip gz_sim / ros_gz_bridge / spawn only; all other
  sim nodes run as usual. Omit it (or `:=1`) for the normal Gazebo flow.

Known startup race: `obstacle_handler` can FATAL ("base_link ... does not exist") because
it looks up TF before the sim-time TF tree exists, and it is not respawned. Wait ~10 s,
then restart it in a third terminal:

```bash
ros2 run openmover obstacle_handler --ros-args \
  --params-file openmover_ws/install/openmover/share/openmover/config_defaults/hardwares.yaml \
  --params-file openmover_ws/install/openmover/share/openmover/config_defaults/modules.yaml \
  -r openmover/hardware/lidar/scan/obstacle:=openmover/hardware/lidar/scan
```

Verification (teleop gate):

```bash
ros2 topic hz /openmover/hardware/lidar/scan       # merged scan, ~12-15 Hz
ros2 run tf2_ros tf2_echo odom base_link           # from localization_handler
python3 /tmp/teleop_test_a.py                       # publishes cmd_vel_manual, reads openmover/hardware/odom
```

Expected: forward leg ≈ v·t (0.2 m/s × 3 s ≈ +0.47 m after servo losses), pivot leg
≈ w·t yaw; ROS-reported pose matches Isaac's ground-truth heartbeat lines to ~1 cm.

Manual spot checks of the product path:

```bash
ros2 topic echo /openmover/control/cmd_vel_sim      # what the stack sends to the simulator
ros2 topic echo /openmover/hardware/odom_sim --once # what Isaac sends back
ros2 node list                                       # expect isaac_bridge + the product nodes
```

## Stack A — navigation gate (cartographer + product navigation controller)

Same boot as the teleop gate above (Isaac first, then `bootloader.launch.py`, then the
manual `obstacle_handler` restart). Then run the product navigation flow — five service
calls, exact product order (`python3 /tmp/nav_gate_a.py` performs all of them):

1. `/openmover/server/set_localization_mode` (`map`, `start`, `navigation`)
   → starts the cartographer localization launch (`modules/localization/carto_localization.launch.py`).
2. `/openmover/localization/cartographer/request` (`load_map`, `~/openmover_robot/maps/simulation/`,
   `navigation`) → loads `navigation.pbstream` into pure-localization mode.
3. `/openmover/server/set_func_mode` (`load_map`, `start`, `navigation`)
   → `map_server` with `navigation_parsed.yaml` (430×398 @ 0.05 m, nav resolution).
4. `/openmover/server/set_func_mode` (`nav_to`, `start`) → the navigation app.
5. `/openmover/server/set_nav_area` (`navigation`, `start`) → `navigation_handler`
   (custom controller; in-process nav2 costmap + custom dijkstra planner).

Then send a goal and watch the state:

```bash
ros2 topic pub --once /openmover/navigation/simple_goal geometry_msgs/msg/PoseStamped \
  "{header: {frame_id: 'map'}, pose: {position: {x: 1.0, y: 0.0, z: 0.0}, orientation: {w: 1.0}}}"
ros2 topic echo /openmover/navigation/state        # NavToState.state is a STRING:
                                                   # running / reached / blocked / error
```

Expected: cartographer localizes at the spawn (~+0.00, +0.00 in map), the robot drives to
the goal, `state: reached` with `pose` at the goal (xy tolerance 0.02 m), and the Isaac
bridge heartbeat lines show the ground-truth position move by the same amount.

Notes:

- Steps 1–3 each take ~1.5 s of internal config-switch wait; give the map topic (transient
  local) up to a minute to appear after step 3.
- TF chain once localized: `map → odom (cartographer) → base_link (localization_handler)`.
- The `navigation_handler` node name owns its own footprint param — do not move `footprint`
  back into the `/**` wildcard in `hardwares.yaml` (see 05, bugs table).
- Stale processes survive stack restarts; before re-running, kill leftovers with
  `pkill -f "install/openmover/lib"` and `pkill -f "install/relocalization_toolbox/lib"`
  (never `pkill -f openmover` — the Isaac bridge's own cmdline matches that).

## Isaac Lab — openmover navigation env (headless training scaffold)

No ROS needed. Same RAM guard applies (≥ 8 GiB MemAvailable; Isaac Lab uses its own
bundled sim at `~/isaaclab/_isaac_sim`, so `~/isaacsim` must not be running).

```bash
grep MemAvailable /proc/meminfo          # need >= 8 GiB
cd ~/isaaclab && ./isaaclab.sh -p \
  /home/zar/Documents/phd/robot/openmover_ws/isaac/lab/21_run_openmover_nav.py \
  --num_envs 16 --num_steps 100 --policy random
```

- `--policy zero|random|forward` (forward = both wheels +1; physics sanity check).
- Prints env-steps/s and a diagnostics block: scan stats (wall-maze terrain → per-slice
  min ≈ 0.04–0.12, mean ≈ 0.4; all-1.0 scans only on the legacy flat plane), goal/vel
  obs tail, base xy, displacement, wheel joint velocities, contact forces, and mean
  success/collision rates over episode-reset batches.
- Scaling sweep pattern: run the same command with `--num_envs 64 / 256 / 1024` and
  compare env-steps/s (expect near-linear; 2026-09-02 wall-maze: 2.4k / 6.4k / 11.4k).
- Terrain is generated once per config change and cached under `/tmp/isaaclab/terrains`
  (seed=42 in `OPENMOVER_TERRAINS_CFG`); delete that dir to force regeneration.
- Benign warnings at startup: `Failed to find articulation/rigid body at
  .../Robot/Geometry/base_link/base_link` (sensor child-Xform spawn probed by PhysX)
  and URDF-converter warnings about merged lidar links / MuJoCo actuator gains —
  PhysX actuators are re-defined at env level.
- The task registers on `import openmover_lab` (the runner inserts `isaac/lab/` into
  `sys.path`); no `isaaclab_tasks` entry or install step needed.

Target-world smoke test / trained-policy evaluation (env factory, 2026-09-03):

```bash
# smoke a target world with a hand-coded policy (RAM guard first, as above)
cd ~/isaaclab && ./isaaclab.sh -p \
  /home/zar/Documents/phd/robot/openmover_ws/isaac/lab/21_run_openmover_nav.py \
  --task Isaac-Nav-Openmover-RailYard-v0 --num_envs 16 --num_steps 100 --policy forward
# (also -Degraded-v0 and -Combined-v0; note: --policy forward collides by design)

# roll out a trained checkpoint on any world (bounded; prints mean success/collision)
cd ~/isaaclab && ./isaaclab.sh -p \
  /home/zar/Documents/phd/robot/openmover_ws/isaac/lab/21_run_openmover_nav.py \
  --task Isaac-Nav-Openmover-v0 --policy trained \
  --checkpoint openmover_ws/isaac/lab/logs/rsl_rl/openmover_nav/<run_dir>/model_<iter>.pt \
  --num_envs 64 --num_steps 600
```

- The eval pass loads the checkpoint through an in-script `OnPolicyRunner`
  (`rsl_rl_cfg_entry_point` of the task) and rolls out the inference policy; episode
  success/collision rates come from the env's `Metrics/*` extras.
- Transfer table = same checkpoint, `--task` varied over the four worlds, same seed.
- Target worlds generate their own terrain cache on first use (rail yard seed=43);
  delete `/tmp/isaaclab/terrains` to force regeneration.

Recording an environment video (headless, 2026-09-03):

```bash
cd ~/isaaclab && ./isaaclab.sh -p \
  /home/zar/Documents/phd/robot/openmover_ws/isaac/lab/21_run_openmover_nav.py \
  --task Isaac-Nav-Openmover-v0 --num_envs 1 --num_steps 305 \
  --policy forward --video --video_length 300 --video_view bird \
  --headless --enable_cameras
# mp4 lands in isaac/lab/videos/<task>/rl-video-step-0.mp4
```

- `--video` pins env 0 to terrain tile (0,0) and aims a fixed bird/chase camera at it
  in absolute world coords (the Kit capture ignores `viewer.origin_type`); the terrain
  visual material is overridden to gray for the recording only.
- Verify content before trusting the file: `ffmpeg -y -ss 5 -i <mp4> -frames:v 1 f.png`.
- ~12 env-steps/s with RTX capture; one simulator at a time.

### Trace dump + top-down presentation video (2026-09-04)

`--video` also writes a trace npz next to the mp4 (schema v2): `traj (T,3) x,y,yaw |
wp (T,2) world-frame geodesic waypoint | lidar (T,300,2) world-frame hit points
(150 front + 150 rear scanner, NaN = miss) | ep_goal/ep_spawn (E,2) | ep_start (E,) |
occ (32,32) bool | origin (2,) | size (2,)`. Recording semantics: on a done step the
pose buffers are already the POST-reset spawn, so the old episode is closed with the
previous (pre-reset) frame and the new episode starts on the next append (see 05).

Render the presentation top-down video (pure CPU, no sim):

```bash
cd openmover_ws/isaac/lab && python3 26_render_topdown_video.py \
  --trace videos/<task>/trace_seed16.npz [--title "..."] [--fps 20]
# writes videos/<task>/trace_seed16.topdown.mp4
```

Palette: paper background, navy walls, blue START disc, green GOAL star + dashed
success ring, crimson trace, orange robot wedge, cyan waypoint, teal LiDAR fan,
HUD (episode + path length) and a 1 m scale bar. Old pre-schema-v2 traces still
render (overlays skipped).

### Custom maps (27_make_custom_map.py + runner --map_file, 2026-09-04)

Author a map either from a PNG (dark = wall, one blue pixel = spawn, one green
pixel = goal; PNG row 0 = top = +y) or from a built-in gallery generator:

```bash
cd openmover_ws/isaac/lab && python3 27_make_custom_map.py --gen slalom   # or ring|rooms|serpentine|--png x.png
# writes maps/<name>.json + maps/<name>.preview.png (BFS-validated: goal reachable)
```

The JSON spec is `{name, size, cell, wall_height, boxes[[cx,cy,yaw,l,w,h]...], spawn,
goal}` in tile-local corner-origin coords. Run the frozen policy on it:

```bash
cd ~/isaaclab && ./isaaclab.sh -p \
  /home/zar/Documents/phd/robot/openmover_ws/isaac/lab/21_run_openmover_nav.py \
  --task Isaac-Nav-Openmover-v0 --map_file .../isaac/lab/maps/slalom.json \
  --policy trained --checkpoint .../bc_init_v3/model_0.pt \
  --num_envs 64 --num_steps 2405 --fixed_block_prob 1.0
```

`--map_file` swaps the terrain generator for a 2×2-tile custom-map terrain and fixes
spawn+goal from the spec every episode (yaw stays random). Policies: `--policy
trained --checkpoint ...` (frozen), or `--policy expert` (in-engine geodesic expert —
no checkpoint needed; use it to showcase a map before/without a trained policy).
Combine with `--video` for 3D + top-down recordings; the trace npz is named
`trace_<mapstem>_seed<S>.npz`. Corridors should stay ≥ 0.8 m wide (occ inflation
0.20 m at 0.25 m cells).

Custom-map constraints and safeguards (all learned the hard way, see 05):

- `num_envs` must be ≤ 4 (= number of tiles): the fixed map spawn is identical on
  every tile, so two envs on one tile would stack two robots in the same spot. The
  env assigns envs to tiles round-robin and raises if num_envs > tiles. For more
  statistics, run seeds sequentially (`--seed 42/1/7`).
- Terrain cache busting: `CustomMapTerrainCfg.map_hash` = md5 of the map file
  CONTENT. Isaac keys its terrain cache on the cfg dict hash; with only the path in
  the cfg, in-place map edits would silently reload the stale mesh.
- Spawn/goal hull clearance: marked points closer than 0.36 m to any wall (base_link
  collision half-diagonal 0.327 m + margin) are snapped to the nearest clear grid
  point within 2 m (env logs a `[nav] <name> snapped ...` line). Prefer centering
  spawn/goal ≥ 0.4 m from walls by hand so the intended task is preserved.
- Episode horizon auto-scales with the map's BFS `path_len`: `path_len/0.25 + 10`
  (capped at 160 s). Long maps truncated at the old `path_len/0.45 + 5`; a
  truncated episode auto-resets exactly at the horizon, which reads as 0% success
  with the robot back at spawn. Pick `--num_steps` > horizon/0.05 per episode you
  want to observe (e.g. serpentine 138 s → ≥ 2760 steps/episode).
- Geodesic-field sweeps auto-scale too: the runner raises `geo_iters` to
  `path_len/geo_res + 40` so the Bellman field converges over long winding paths
  (serpentine's ~128 cells exceeded the default 72, leaving the spawn cell `inf`
  and the expert spinning in place). Logs `[nav] geo_iters raised to ...`.
- The `blocked-goal episodes: N of N (100%)` line on gallery maps is EXPECTED and
  harmless — it flags the spawn→goal straight CHORD crossing a wall (true of any
  maze), not goal reachability. Judge by success/collision/TTG instead.

Re-converting the URDF (only after URDF changes):

```bash
cd ~/isaaclab && ./isaaclab.sh -p \
  /home/zar/Documents/phd/robot/openmover_ws/isaac/sim/20_convert_openmover_urdf.py
```

## Isaac Lab — PPO training (RSL-RL) for the openmover nav task

No ROS needed; same RAM guard. The stock trainer only auto-imports `isaaclab_tasks`,
so the external task is registered by the wrapper `22_train_openmover_nav.py`, which
then delegates to the unified trainer (honors `--max_iterations`, so runs are bounded).

```bash
grep MemAvailable /proc/meminfo          # need >= 8 GiB
cd openmover_ws/isaac/lab && ~/isaaclab/isaaclab.sh -p 22_train_openmover_nav.py \
  --rl_library rsl_rl --task Isaac-Nav-Openmover-v0 \
  --num_envs 256 --max_iterations 300 --run_name run1
```

- Agent cfg: `openmover_lab/rsl_rl_ppo_cfg.py` (registered as
  `rsl_rl_cfg_entry_point` in `openmover_lab/__init__.py`).
- Output: `isaac/lab/logs/rsl_rl/openmover_nav/<timestamp>_<run_name>/` —
  tensorboard events, `params/env.yaml` + `params/agent.yaml`, `model_<iter>.pt`
  every 50 iters. View curves: `tensorboard --logdir isaac/lab/logs/rsl_rl`.
- Resume: same command + `--resume` (optionally `--load_run <regex>`,
  `--checkpoint <regex>`); continues from the checkpoint's saved iteration.
- Per-iteration log includes our env extras (`Metrics/success_rate`,
  `Metrics/collision_rate`) — biased toward episodes that finish within the
  collection window, so read them as trends, not absolute rates.
- First reference run 2026-09-02 (256 envs, 300 iters): ~8.5k steps/s, 238 s;
  reward −5 → +6.4, episode length 40 → 235/300.

## Transfer-table evaluation (frozen policy on all worlds, 2026-09-03)

Roll a frozen checkpoint out on each registered world — zero gradient steps. Sequential
(one simulator at a time), 256 envs × 2405 steps ≈ 2.1k episodes/world, ~3.5 min/world.

Task v2 protocol (run6+): `--fixed_block_prob 1.0` pins the goal-blocking fraction at
100% and disables the training curriculum (`curriculum_fixed_block_prob`), so eval goals
are frozen/deterministic per seed regardless of the curriculum state the checkpoint was
trained under. The forward baseline must be re-measured with the same flag.

```bash
cd openmover_ws/isaac/lab
CKPT=logs/rsl_rl/openmover_nav/<run7_dir>/model_1499.pt
for T in Isaac-Nav-Openmover-v0 Isaac-Nav-Openmover-RailYard-v0 \
         Isaac-Nav-Openmover-Degraded-v0 Isaac-Nav-Openmover-Combined-v0; do
  ~/isaaclab/isaaclab.sh -p 21_run_openmover_nav.py --task $T \
    --policy trained --checkpoint $CKPT --num_envs 256 --num_steps 2405 \
    --fixed_block_prob 1.0
done
# forward baseline under task v2 (expect ~0: all chords blocked)
~/isaaclab/isaaclab.sh -p 21_run_openmover_nav.py --task Isaac-Nav-Openmover-v0 \
  --policy forward --num_envs 256 --num_steps 2405 --fixed_block_prob 1.0
```

- The runner prints the transfer metrics at the end: `mean success rate`,
  `mean collision rate`, `mean time-to-goal (successes only)`, plus the task-v2
  line `blocked-goal episodes: N of M (%), blocked success=...`.
- Inference is deterministic (mean action); seed fixed → worlds/goals reproducible.
- Record results in `06_results.md` §3 (the transfer ledger).

## Adaptation-budget curve (retrain-from-scratch vs engine zero-shot, 2026-09-04)

Quantifies how much target-world supervision retrain-from-scratch needs to reach the
engine's zero-shot level. See `06_results.md` §6 for numbers. Steps (sequential, one
simulator at a time):

```bash
cd openmover_ws/isaac/lab
# 1) validate the expert teacher solves the target world (expect blocked success >0.5)
~/isaaclab/isaaclab.sh -p 21_run_openmover_nav.py --task Isaac-Nav-Openmover-RailYard-v0 \
  --policy expert --num_envs 16 --num_steps 1200 --fixed_block_prob 1.0 --seed 42
# 2) collect a target demo pool big enough for the largest budget point
~/isaaclab/isaaclab.sh -p 23_collect_openmover_demos.py \
  --task Isaac-Nav-Openmover-RailYard-v0 --num_envs 256 --num_steps 1700 \
  --fixed_block_prob 1.0 --out logs/bc_demos/railyard_demos_p100.pt
# 3) BC a fresh actor at nested budget points (--max_demos subsamples with the fixed seed)
D="logs/bc_demos/railyard_demos_p100.pt ..."   # concatenate pool shards
Y=logs/rsl_rl/openmover_nav/<arch_run>/params/agent.yaml
~/isaaclab/isaaclab.sh -p 24_bc_pretrain_openmover.py --demos $D --agent_yaml $Y \
  --max_demos 40960 --out logs/rsl_rl/openmover_nav/p3_railyard_bc_b41k/model_0.pt
#    (repeat per budget; b0k point = --max_demos 1 --epochs 0 => untrained init)
# 4) eval each checkpoint with the task-v2 protocol (same as transfer ledger)
~/isaaclab/isaaclab.sh -p 21_run_openmover_nav.py --task Isaac-Nav-Openmover-RailYard-v0 \
  --policy trained --checkpoint logs/rsl_rl/openmover_nav/p3_railyard_bc_b41k/model_0.pt \
  --num_envs 256 --num_steps 2405 --fixed_block_prob 1.0 --seed 42
# 5) plot the curve (pure CPU)
python3 28_plot_budget_curve.py   # -> figs/p3_adaptation_budget_curve.png
```

- Budget points must be NESTED subsamples so the curve is comparable across points:
  keep the same `--seed` and the same concatenated pool so `randperm` prefixes nest.
- `--max_demos` is the only addition to `24_bc_pretrain_openmover.py` (2026-09-04);
  default `None` = use all demos (unchanged behavior for prior runs).
- Compare the crossing budget against the engine zero-shot row (§3, same protocol).

## DOB-lite deploy-time interface A/B (dynamics axis, 2026-09-04)

Measures whether the deploy-time disturbance-observer interface repairs the
degraded-dynamics shift WITHOUT touching the frozen policy weights. See
`06_results.md` §7 for numbers. The shim is `openmover_lab/dob_lite.py`; the runner
flag `--dob_lite` enables it and `--const_boost` is an open-loop oracle control arm.
Run each arm separately (one simulator at a time), same task-v2 protocol:

```bash
cd openmover_ws/isaac/lab
CKPT=logs/rsl_rl/openmover_nav/bc_init_v3/model_0.pt
# baseline (regression guard: must reproduce §3 degraded row 0.028 exactly)
~/isaaclab/isaaclab.sh -p 21_run_openmover_nav.py --task Isaac-Nav-Openmover-Degraded-v0 \
  --policy trained --checkpoint $CKPT --num_envs 256 --num_steps 2405 \
  --fixed_block_prob 1.0 --seed 42 > logs/p4_dob_degraded_nodeb.log 2>&1
# + DOB-lite (expect blocked success >> baseline, mean g -> ~0.6)
~/isaaclab/isaaclab.sh -p 21_run_openmover_nav.py --task Isaac-Nav-Openmover-Degraded-v0 \
  --policy trained --checkpoint $CKPT --num_envs 256 --num_steps 2405 \
  --fixed_block_prob 1.0 --seed 42 --dob_lite > logs/p4_dob_degraded_dob.log 2>&1
# source sanity (expect ~no-op: g -> ~1, blocked success ~0.287)
~/isaaclab/isaaclab.sh -p 21_run_openmover_nav.py --task Isaac-Nav-Openmover-v0 \
  --policy trained --checkpoint $CKPT --num_envs 256 --num_steps 2405 \
  --fixed_block_prob 1.0 --seed 42 --dob_lite > logs/p4_dob_source_dob.log 2>&1
# combined (both axes)
~/isaaclab/isaaclab.sh -p 21_run_openmover_nav.py --task Isaac-Nav-Openmover-Combined-v0 \
  --policy trained --checkpoint $CKPT --num_envs 256 --num_steps 2405 \
  --fixed_block_prob 1.0 --seed 42 --dob_lite > logs/p4_dob_combined_dob.log 2>&1
# oracle open-loop control (knows the 10/6 degradation factor in advance)
~/isaaclab/isaaclab.sh -p 21_run_openmover_nav.py --task Isaac-Nav-Openmover-Degraded-v0 \
  --policy trained --checkpoint $CKPT --num_envs 256 --num_steps 2405 \
  --fixed_block_prob 1.0 --seed 42 --const_boost 1.6667 > logs/p4_dob_degraded_oracleboost.log 2>&1
```

- Grep the result lines (isaaclab.sh exits 0 even on traceback):
  `grep -E "episode-reset batches|mean time-to-goal|blocked-goal episodes|DOB-lite mean" logs/p4_dob_*.log`
- The estimator is a plant-gain identifier on the WHEEL-SPEED loop (not body speed);
  body-speed variants v0/v1 were biased by acceleration transients — do not regress to
  them. See the design-history note in `06_results.md` §7 and `dob_lite.py` docstring.
- `--dob_lite`/`--const_boost` disable the wrapper action clip and re-apply the frozen
  clip manually in the runner, so g=1 (or boost=1) stays bit-exact equal to §3 rows.

## CBF-lite deploy-time filter A/B (safety axis, 2026-09-04)

Measures whether the deploy-time safety-filter interface cuts collisions WITHOUT
touching the frozen policy weights. See `06_results.md` §8 for numbers. The shim is
`openmover_lab/cbf_lite.py`; the runner flag `--cbf_lite` enables it (after DOB-lite
when both are set — the filter gets final authority). One simulator at a time:

```bash
cd openmover_ws/isaac/lab
CKPT=logs/rsl_rl/openmover_nav/bc_init_v3/model_0.pt
# custom-map arms: num_envs MUST be <= 4 (env guard raises on tile stacking)
for MAP in ring slalom; do for S in 42 1 7; do
  ~/isaaclab/isaaclab.sh -p 21_run_openmover_nav.py --task Isaac-Nav-Openmover-v0 \
    --map_file maps/$MAP.json --policy trained --checkpoint $CKPT \
    --num_envs 4 --num_steps 2405 --fixed_block_prob 1.0 --seed $S \
    > logs/p4_cbf_${MAP}_frozen_s${S}.log 2>&1
  ~/isaaclab/isaaclab.sh -p 21_run_openmover_nav.py --task Isaac-Nav-Openmover-v0 \
    --map_file maps/$MAP.json --policy trained --checkpoint $CKPT \
    --num_envs 4 --num_steps 2405 --fixed_block_prob 1.0 --seed $S --cbf_lite \
    > logs/p4_cbf_${MAP}_cbf_s${S}.log 2>&1
done; done
# source-world sanity (task-v2 protocol, expect ~0.287 blocked success, collision drop)
~/isaaclab/isaaclab.sh -p 21_run_openmover_nav.py --task Isaac-Nav-Openmover-v0 \
  --policy trained --checkpoint $CKPT --num_envs 256 --num_steps 2405 \
  --fixed_block_prob 1.0 --seed 42 --cbf_lite > logs/p4_cbf_source_taskv2_cbf.log 2>&1
```

- Grep the result lines (isaaclab.sh exits 0 even on traceback):
  `grep -E "episode-reset batches|blocked-goal episodes|CBF-lite interventions" logs/p4_cbf_*.log`
- Clearance is the min over a ±45° cone around the TRAVEL direction (d_margin 0.30 m
  at the LiDAR origin, a_dec 1.0 m/s²). The hemisphere-min variant (v0) never
  triggered anywhere — do not regress to it.
- `--cbf_lite` alone is a bit-exact no-op relative to frozen whenever the clamp never
  fires (the shim returns the input tensor untouched). If intervention rate prints
  0.000 yet metrics drift from frozen, suspect a float round-trip (`(v·x)/x ≠ v`) in
  the shim — the no-op path must return `a` unchanged.
- Slalom collisions are side-contacts the travel cone cannot see; expect ~0
  interventions and no change there (documented negative, §8).

## ROS 2 rung — frozen policy over plain topics (deploy axis, 2026-09-05)

Deploys the frozen checkpoint `bc_init_v3/model_0.pt` UNCHANGED through the
standard contract (scans + odom in, cmd_vel out). Node:
`src/warehouse_simulation/scripts/policy_node.py`. Isaac is the robot/world via
`16_bridge_ros.py`; the rest of Stack B runs unmodified. See ledger §9.

Terminal discipline (this run has THREE long-lived processes; killing the wrong
one loses the sim): terminal A = ROS Stack B launch, terminal B = Isaac bridge,
terminal C = policy node. Do not reuse A/B/C for monitoring — open a 4th.

```bash
# 0) RAM guard (bridge RSS grows to ~6 GiB; restart between sessions)
grep MemAvailable /proc/meminfo   # want > 4 GiB free

# 1) ROS side (terminal A) — sourced jazzy + this workspace
cd /home/zar/Documents/phd/robot
source /opt/ros/jazzy/setup.bash && source openmover_ws/install/setup.bash
ros2 launch openmover_ws/isaac/scripts/16_stack_b.launch.py

# 2) Isaac bridge (terminal B) — the robot + world + topic bridge
cd /home/zar/Documents/phd/robot
source /opt/ros/jazzy/setup.bash && \
  ~/isaacsim/python.sh openmover_ws/isaac/scripts/16_bridge_ros.py \
  > openmover_ws/logs/ros2_rung_bridge.log 2>&1
# wait for heartbeat: tail -f openmover_ws/logs/ros2_rung_bridge.log
#   expect "[bridge] t= ... pos=(+0.01,-0.00)" (spawn) within ~30 s

# 3) frozen policy node (terminal C) — torch+rclpy come from isaaclab.sh
cd /home/zar/Documents/phd/robot/openmover_ws
source /opt/ros/jazzy/setup.bash && \
  timeout 300 ~/isaaclab/isaaclab.sh -p \
    src/warehouse_simulation/scripts/policy_node.py \
    --ros-args -p goal_x:=-7.0 -p goal_y:=4.0 \
  > logs/ros2_rung_policy.log 2>&1
```

- Goal must be a FREE cell (outside the 0.35 m inflation). The replica treats
  inflation as lethal (matches Lab). (-7,4) is the validated in-distribution
  headline; a goal behind the bin row, e.g. (6,8), is a documented negative
  (detour-vs-goal conflict; the frozen policy sides with goal pull).
- Read the outcome (exit code is NOT reliable):
  `grep -E "REACHED|SUMMARY|stall|no progress" logs/ros2_rung_policy.log`
  Headline = `[policy] SUMMARY: ... SUCCESS, time-to-goal NN s`.
- Cross-check the policy telemetry against the bridge ground truth every 5 s:
  `grep '\[bridge\]' logs/ros2_rung_bridge.log | tail`. If the policy "freezes"
  but the bridge pos is moving, trust the bridge (the policy read a stale odom).
- The node auto-stops after its bounded duration and prints one `[policy] SUMMARY`.
  Recovery activations log as `stall (...)` / `no progress (...)`; both are bounded
  (fixed backup + cooldown) and expected near the pallet margins post-success —
  the frozen policy has no stop-at-goal or stall response (§9 findings).
- The contact channel is a chassis-speed stall PROXY (pose-differentiated), not a
  real contact topic. Don't chase contact=1.0 during cruise blips; only sustained
  ≥0.7 for 1 s triggers a recovery.

## Koopman data pipeline v0 (concept arm, 2026-09-05)

Chassis-dynamics transitions + offline lifted-linear fit (ledger §11). No
policy involved; one simulator at a time; the fit itself needs NO simulator.

```bash
# RAM guard first (>= 8 GiB available). Collect per regime (~2 min each,
# 64 envs x 600 steps; same --seed => paired command schedules):
cd ~/isaaclab
./isaaclab.sh -p /home/zar/Documents/phd/robot/openmover_ws/isaac/lab/29_koopman_collect.py \
  --num_envs 64 --num_steps 600 \
  --out /home/zar/Documents/phd/robot/openmover_ws/isaac/lab/logs/koopman_data/source.pt
./isaaclab.sh -p /home/zar/Documents/phd/robot/openmover_ws/isaac/lab/29_koopman_collect.py \
  --task Isaac-Nav-Openmover-Degraded-v0 --num_envs 64 --num_steps 600 \
  --out /home/zar/Documents/phd/robot/openmover_ws/isaac/lab/logs/koopman_data/degraded.pt

# Offline fit + transfer-gap table (CPU seconds; torch via isaaclab.sh):
./isaaclab.sh -p /home/zar/Documents/phd/robot/openmover_ws/isaac/lab/30_koopman_fit.py
```

- Read the TRANSFER GAP block at the end: frozen-source R² on degraded data
  vs refit R². Expected shape: wheel channels collapse under the frozen fit
  (0.88 → ~0.57), body channels stay usable; refit closes the gap (~0.99).
- Sanity gates on the collector output: kept-fraction > 80%, vx range well
  inside ±3 m/s (the plausibility gate). vx beyond that means the gate
  constants need review, not more data.
- The raw quadratic lift DIVERGES without input standardization (R² ~ −1e6).
  If you change the lift, keep the train-statistics standardization.
- Artifacts: `logs/koopman_data/{source,degraded}.pt`, `K_{source,degraded}.pt`,
  `fit_summary.json`; evidence logs `koopman_collect_*.log`, `koopman_fit.log`.

## Capstone "go" demo — custom map bridge (2026-09-05)

User draws a map, says "go", the FROZEN policy drives it over the standard
ROS 2 contract. Ledger §12 holds the results (two honest negatives + one
success). Stack B must be alive (terminal A); the bridge and the policy are
the two bounded processes (terminals B and C). One simulator at a time; RAM
guard >= 8 GiB.

```bash
# 1) author the map (user step): PNG, dark px = wall, blue = spawn, green =
#    goal; corridors >= 0.8 m; spawn/goal >= 0.4 m from walls. Then:
cd /home/zar/Documents/phd/robot/openmover_ws/isaac/lab
python3 27_make_custom_map.py --png maps/<name>.png --name <name>
#    BFS-validates (goal reachable) and writes maps/<name>.json + preview.

# 2) bridge (terminal B): bakes the map into Isaac, publishes the warehouse
#    contract, records the ground-truth trace, exits after --duration.
cd /home/zar/Documents/phd/robot/openmover_ws
source /opt/ros/jazzy/setup.bash && \
  ~/isaaclab/isaaclab.sh -p isaac/scripts/17_bridge_ros_custommap.py \
    --map_file isaac/lab/maps/<name>.json --duration 130 \
    2>&1 | tee isaac/lab/logs/capstone_bridge_<name>.log
#    wait for "[bridge] loop entered" and the t= heartbeat before step 3.

# 3) "go" (terminal C): frozen policy node with the SAME map.
source /opt/ros/jazzy/setup.bash && \
  ~/isaaclab/isaaclab.sh -p src/warehouse_simulation/scripts/policy_node.py \
    --ros-args -p map_file:=$PWD/isaac/lab/maps/<name>.json \
      -p duration:=120.0 \
      -p checkpoint:=$PWD/isaac/lab/logs/rsl_rl/openmover_nav/bc_init_v3/model_0.pt \
    2>&1 | tee isaac/lab/logs/capstone_policy_<name>.log

# 4) verdict + presentation video (any terminal, after both exit):
grep -E "REACHED|SUMMARY" isaac/lab/logs/capstone_policy_<name>.log
cd isaac/lab
python3 28_clip_trace.py --trace videos/custommap_demo/trace_<name>.npz
python3 26_render_topdown_video.py \
  --trace videos/custommap_demo/trace_<name>_clip.npz --fps 15 \
  --title "<title>"
```

Gotchas (all observed, all cost a run to learn):

- `duration:=120.0` MUST be a float — the parameter is declared DOUBLE;
  `120` raises InvalidParameterTypeException at node start.
- `checkpoint` and `map_file` MUST be absolute paths (the checkpoint default
  is relative to the workspace root; isaaclab.sh runs from its own cwd).
- Launch the bridge FIRST and wait for its heartbeat; the policy's 120 s
  clock starts at its own boot and would burn idle if started too early.
- Exit codes are NOT reliable (isaaclab.sh returns 0 on traceback) — grep the
  tee'd logs for `SUMMARY` / `trace saved`.
- Geometry guidance from the three runs: corridors <= 1.25 m and far-end
  detours around long walls are out of distribution for the frozen policy
  (it is goal-bearing dominated, no wall-following). Place gaps >= 2 m ON the
  spawn→goal line (rail-yard level-crossing style) and the zero-shot policy
  succeeds.
- The trace is recorded at 15 Hz → render with `--fps 15` (the renderer
  default is 20). `28_clip_trace.py` trims the idle pre-boot segment and the
  post-success drift (the policy has no stop-at-goal, §9).

## Capstone extensions — orchestrated launch, serial goals, seeds, 3D renders (2026-09-05)

Extensions used by the ladder/serial window (ledger §13). Same one-simulator-
at-a-time and RAM-guard rules as the base capstone runbook.

Orchestrated launch (kills the timing hazard that produced the `_idle`
negative): ONE bash command starts the bridge in background with `tee`, polls
its log for "loop entered" every 2 s, then launches the policy immediately:

```bash
cd /home/zar/Documents/phd/robot/openmover_ws && source /opt/ros/jazzy/setup.bash && \
{ { ~/isaaclab/isaaclab.sh -p isaac/scripts/17_bridge_ros_custommap.py \
      --map_file isaac/lab/maps/<name>.json --duration 130 \
      2>&1 | tee isaac/lab/logs/capstone_bridge_<name>.log ; } & \
  for i in $(seq 1 90); do grep -q "loop entered" \
      isaac/lab/logs/capstone_bridge_<name>.log 2>/dev/null && break; sleep 2; done; \
  ~/isaaclab/isaaclab.sh -p src/warehouse_simulation/scripts/policy_node.py \
    --ros-args -p map_file:=$PWD/isaac/lab/maps/<name>.json -p duration:=120.0 \
      -p checkpoint:=$PWD/isaac/lab/logs/rsl_rl/openmover_nav/bc_init_v3/model_0.pt \
    2>&1 | tee isaac/lab/logs/capstone_policy_<name>.log; wait; }
```

Serial multi-goal: author with `27_make_custom_map.py ... --goals "i,j;i,j;i,j"`
(cell coords, `;`-separated; BFS-validated; last goal becomes the map goal).
`policy_node.py` reads the `goals` list from the JSON, advances on arrival and
rebuilds the GeoField per leg (logs `LEG k/N`). Clip with
`28_clip_trace.py --trace ... --map_file maps/<name>.json` so each leg becomes
a pseudo-episode (per-leg markers in 26/29 for free); add `--allow_unreached`
to clip a FAILURE trace to its end instead of exiting.

Repeat seeds / ablations:
- `17_bridge_ros_custommap.py --seed N` jitters spawn ±0.15 m and yaw ±15°
  (deterministic per seed) for N-seed statistics on a fixed map.
- `policy_node.py ... -p blind_waypoint:=true` zeroes the waypoint+d_geo obs
  dims (waypoint-blinded ablation of the interface arm).

3D presentation renders (`29_render_3d_video.py`): the pioneer3dx usda ships
no meshes reachable by headless Fabric render, so the script builds a proxy
robot from primitives and edits xform ops per frame (`sim.render()` +
`camera.update(dt, force_recompute=True)`); DomeLight 400; `--view bird`
(bird cam at map centre +[3.5,-3.5,10.5]) or `chase`; `--stride k` skips
frames for long failure clips; `--out` to keep old renders (never overwrite).
The default focal 24 clips the map corners (fine when the action stays on the
spawn-goal diagonal); serial tours that visit the far corners need
`--focal 17` to frame the full 8 m square (tour bird3d rendered with it; the
tight-focal variant kept as `.bird3d_tight.mp4`).
It is a second Isaac Sim instance: NEVER run it while a bridge is up.

Ladder/serial map geometry guidance (from §13): full-width staggered
partitions with ~2 m gaps transfer well (mid rung solved faster than easy);
offsetting the gaps ±0.8-0.9 m or using 1.0 m doors re-exposes the corner-wedge
seam (hard rung / rooms negative). Keep doors/openings >= 2 m and aligned to
the approach for successes.

## Shielded presentation runs — zero-contact iteration 2 (2026-09-05)

The deploy-time safety shield (ledger §15) is OFF by default and enabled per
run with one extra policy parameter:

```bash
~/isaaclab/isaaclab.sh -p src/warehouse_simulation/scripts/policy_node.py \
  --ros-args -p map_file:=$PWD/isaac/lab/maps/<name>.json -p duration:=120.0 \
    -p shield:=true \
    -p checkpoint:=$PWD/isaac/lab/logs/rsl_rl/openmover_nav/bc_init_v3/model_0.pt
```

Everything else is the orchestrated launch above, with the bridge given
`--trace isaac/lab/videos/custommap_shield/trace_<name>.npz` so iteration-2
traces never overwrite iteration-1 artifacts in `videos/custommap_demo/`.

Render pipeline for a shielded trace (same as iteration 1):
`28_clip_trace.py --trace videos/custommap_shield/trace_<name>.npz`
(add `--map_file maps/<name>.json` for serial-goal maps), then
`26_render_topdown_video.py --trace <clip> --fps 15 --title "..."`, then
`29_render_3d_video.py --trace <clip> --map_file maps/<name>.json
--headless --enable_cameras` (`--focal 17` for tours). **`--enable_cameras`
is mandatory** — without it the camera spawn raises
`RuntimeError: A camera was spawned without the --enable_cameras flag`
(cost one failed render pass to learn). For maps LARGER than the 8 m
serial-tour squares the default bird camera (height 10.5 / offset 3.5) crops the
corners; raise it via `--bird_height` / `--bird_offset` (coverage ≈
12.95·height/focal): the 15 m held-out maze uses `--bird_height 26
--bird_offset 6 --focal 17` (≈20 m coverage, frames the square with margin).

Verify zero-contact before presenting:
`python3 30_clearance_audit.py --trace <trace> --map_file maps/<name>.json`
(exact-box mode; penetration frames must be 0).

## Shutdown order

1. Stop the ROS launch (Ctrl+C in its terminal) — the stack stops commanding the robot.
2. Stop the Isaac bridge (Ctrl+C). It prints a shutdown summary (`t=…, N scans out`).
3. Confirm RAM recovery: `grep MemAvailable /proc/meminfo` (expect ~11 GiB back).

The bridge RSS grows during long runs (up to ~6 GiB); restart it between sessions rather
than reusing a long-lived instance.
