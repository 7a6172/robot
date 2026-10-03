# Lessons Learned, Gate Evidence, Follow-ups

## Gate results (Step 1.5)

### Stack B (warehouse_simulation) — PASSED

- **Teleop gate:** Isaac scans → unmodified `laserscan_multi_merger` → `/scan` (903 ranges)
  → slam_toolbox → `/map` with real occupancy. Scripted drive (forward 3 s, stop, turn)
  moved the robot; `/odom` matched Isaac ground truth.
- **Nav2 gate:** goal (1.0, 0.0) → `SUCCEEDED`, error_code 0, 0 recoveries; robot arrived
  at x ≈ +0.90 (goal tolerance 0.2 m). MPPI controller, NavfnPlanner, collision_monitor
  relaying `cmd_vel_smoothed` → `/cmd_vel`.

### Stack A (openmover product stack) — PASSED

- Teleop through the **product path**: `cmd_vel_manual` → `simulation_handler` →
  `cmd_vel_sim` → Isaac → `odom_sim` → `simulation_handler` → `openmover/hardware/odom` →
  `localization_handler` (TF + localization topics).
- Forward leg: commanded 0.2 m/s × 3 s → ROS pose +0.467 m (Isaac ground truth +0.48) —
  servo tracking loss only, consistent with the KD=20 characterization.
- Pivot leg: 0.5 rad/s × 2 s → ~40° yaw. Merged scan `openmover/hardware/lidar/scan`
  at ~12.4 Hz; `odom→base_link` TF live; sim time from Isaac `/clock` across the stack.
- **Navigation gate** (product flow, not Nav2): the five-service product sequence
  (localization mode → cartographer `load_map` pbstream → `func_mode load_map` →
  `func_mode nav_to` → `set_nav_area`) came up clean against Isaac; cartographer localized
  at the spawn (≈ +0.00, +0.00 in map), goal (1.0, 0.0) on
  `/openmover/navigation/simple_goal` → `NavToState.state: reached` with pose
  (1.026, −0.008), Isaac ground truth (+1.03, +0.00). Custom `navigation_handler`
  (in-process nav2 costmaps + custom dijkstra planner) ran the whole drive.
  Getting there required fixing four ROS 2 port bugs below (all latent in the product
  stack, not Isaac-specific).

### Isaac Lab openmover env scaffold — PASSED (2026-09-02)

Training scaffold for the NMTE transfer study (`docs/research/03_paper_one_scope.md`):

- Product URDF → layered USD (`isaac/sim/20_convert_openmover_urdf.py` →
  `isaac/assets/openmover_lab/`); direct-RL task `Isaac-Nav-Openmover-v0`
  (`isaac/lab/openmover_lab/`): dual 600-ray ray-cast LiDARs + goal-in-robot-frame obs
  (1204-d), wheel-velocity actions, contact-based collision, progress/alive/reach rewards.
- Physics validated: zero actions → robot stationary, contact force 0; forward command →
  wheels track ~9.97 rad/s of the 10 rad/s target, robot drives at vx ≈ 0.35 m/s
  (0.66 m in 2 s from rest), no spurious contacts.
- Parallel scaling on the RTX 3080 (headless): 64 envs ≈ 2.6k, 256 ≈ 9.8k,
  1024 ≈ 27.6k env-steps/s — near-linear, 1024 envs fit (see 01 for the table).
- Flat terrain by design: all scan values = 1.0 (rays never hit the ground plane).
- Obstacle terrain added 2026-09-02 (`openmover_lab/openmover_terrains.py`): wall-maze
  source world, one 8×8 m room per env tile (boundary + 4–12 random interior walls,
  difficulty-scaled). Re-validated: scans informative (per-slice min ≈ 0.04–0.12, mean
  ≈ 0.39), forward policy → collision rate 0.77 (rest = wall-sliding timeouts), random
  policy → ≈ 1.0. Wall-maze throughput ≈ 2.4k / 6.4k / 11.4k at 64 / 256 / 1024 envs
  (~2–2.4× cost of real ray hits; still near-linear).
- **Environment factory** added 2026-09-03 (Phase 2, per
  `docs/research/04_isaac_sim_strategy.md`): same `OpenmoverNavEnv` registered under
  four task IDs — source (`-v0`, wall-maze), Target 1 (`-RailYard-v0`, rail-yard
  geometry incl. standard-gauge track band + level crossing + depot clutter),
  Target 2 (`-Degraded-v0`, wall-maze + µ=0.25 floor + 6 rad/s wheel cap),
  Target 3 (`-Combined-v0`, both axes). Rail-yard generator CPU-validated without the
  simulator (mesh bounds + 32×32 origin grid + all four gym specs resolve); GPU
  smoke tests follow once the training run frees the GPU.

## Bugs found and fixed (keep these in mind before re-tuning anything)

| Symptom | Root cause | Fix |
|---|---|---|
| Bridge loop exited at t=0.0 | `AttributeError: module 'rclpy' has no attribute 'spin_some'` — spin_some is rclcpp-only | `rclpy.spin_once(node, timeout_sec=0)` each loop iteration |
| Teleop moved too little (Δx 0.25 vs 0.6 m) | Sim ran at RTF 0.57 (rendering every physics step) | Render-gate to the 15 Hz scan tick |
| After gating, RTF ≈ 12× | Unpaced gated loop runs ~10× faster than real time | Real-time pacing sleep (`wall_t0 + sim_t - now`) |
| Pivot turns tracked only ~66% of target wheel speed | Velocity servo torque-starved scrubbing casters sideways at KD=5 | `bridge_core.KD = 20.0` → ~92% tracking (straight driving was 94% already at KD=5) |
| `/map` invisible to a probe | slam_toolbox publishes `/map` TRANSIENT_LOCAL; probe subscribed volatile | Subscribe with `DurabilityPolicy.TRANSIENT_LOCAL` |
| `obstacle_handler` FATAL at Stack A boot | Looks up TF before the sim-time TF tree exists; launch does not respawn it | Restart manually after boot (runbook in 04) |
| Launch failed: `PackageNotFoundError: warehouse_simulation` | Terminal missing the workspace overlay | `source openmover_ws/install/setup.bash` before `ros2 launch` |
| Carto launch abort: `executable cartographer_initialpose_adapter.py not found` | Symlink in libexec existed but source file lacked the exec bit; launch checks `X_OK` on the resolved path | `chmod +x` the source file (`scripts/server/cartographer_initialpose_adapter.py`) — symlink install, instant |
| `navigation_handler` SIGABRT at costmap init: `parameter {footprint} is of type {string}, setting it to {double_array}` | `/**` wildcard in `hardwares.yaml` also feeds the in-process nav2 costmap sub-nodes, which declare `footprint` as **string** | Moved `footprint` out of `/**`, scoped it under `navigation_handler:` and `obstacle_handler:` node names |
| Cartographer stuck `Queue waiting for data: (1, odom)` | Launch remapped carto's odom to `openmover/localization/odom`, which is `PoseWithCovarianceStamped`; carto needs `nav_msgs/Odometry` | Remap to `openmover/localization/odom_legacy` (both carto launch files: localization + mapping) |
| `navigation_handler` SIGABRT: `parameter 'navigation.control_freq' … {double}, setting it to {integer}` | ROS 2 is strict about yaml-vs-declared param types (ROS 1 was lenient) | `control_freq: 100` → `100.0` in `apps/navigation/navigation.yaml`; `collision_trajectory_sampling_ratio` stays int `3` (code declares int) |
| Nav state compared as enum, never matched | `NavToState.state` is a **string** (`running`/`reached`/`blocked`/`error`), not an enum constant | String compares in gate scripts |
| Isaac Lab env: `ImportError: cannot import name 'sim_utils' from 'isaaclab.sim'` | `sim_utils` is not an exportable name; it is the module alias itself | `import isaaclab.sim as sim_utils` (the stock-task idiom), then `sim_utils.RigidBodyMaterialCfg(...)` |
| RayCaster init: `No sensor prims matched: .../Robot/base_link` | The URDF-converted USD nests bodies: rigid bodies live at `Robot/Geometry/<link>` (verified with a pure `pxr.Usd.Stage.Open` traversal checking `RigidBodyAPI` — no sim needed); `Robot/base_link` simply does not exist | Sensor `prim_path` = `/World/envs/env_.*/Robot/Geometry/base_link` (the actual body prim); offsets are relative to that frame |
| ContactSensor init: `could not find any bodies with contact reporter API` | PhysX contact reporting is off by default on spawned bodies | `spawn = UsdFileCfg(usd_path=..., activate_contact_sensors=True)` in the ArticulationCfg (applied at spawn; no re-conversion needed) |
| Robot ignores wheel velocity targets (silent) | `ImplicitActuator.compute` = `stiffness*(pos_target−q) + damping*(vel_target−q̇)` — with stiffness>0, damping=0 the wheels are position-sprung toward q=0 | Velocity drive = `stiffness=0.0, damping=Kv`. Validate actuation with a forward-command run (wheels should track target, robot should translate) — "env runs" does not prove drives work |
| With `terrain_type="generator"`, robots/goals land on a different grid than the tiles | In direct envs the terrain is instantiated manually, so `scene._terrain` is None and `scene.env_origins` silently falls back to an `env_spacing` grid | Use `self._terrain.env_origins` for spawns and goals (identical to the grid in `plane` mode) |
| Custom walls came out at random yaw despite passing an angle | `trimesh.utils.make_box` always starts from `Rotation.random()` and only caps y/x tilt — yaw is uncontrollable | Build boxes with `trimesh.creation.box(extents, transform)` and an explicit z-yaw rotation |
| Episodes never timed out (mean ep-len grew past the 300-step cap during training, reward inflated by unbounded alive bonus) | `DirectRLEnv` does NOT apply the episode time-out automatically — unlike manager-based envs (where `termination_manager` provides `mdp.time_out`), the direct env's `_get_dones()` must return it | `_get_dones` returns `time_outs = episode_length_buf >= max_episode_length - 1` (same as stock direct envs, e.g. anymal_c). Detection clue: logged `Mean episode length` exceeding `episode_length_s / step_dt` |
| Runner reported ~0.6 success for a naive forward policy (true rate 0.125) | `extras["log"]` persists across steps: summing the logged reset-batch metric every step re-counts the last batch until the next reset, so a tiny all-success batch (1.0) dominated the time average | Accumulate metrics only on steps where resets occur, weighted by the batch size (`n_reset = step_dones.sum()`). Detection clue: `episode-reset batches observed` equal to the step count |
| `--video` recordings were pure black | Three stacked causes: (1) the Kit video backend captures a FIXED camera at absolute world-coord `viewer.eye/lookat` — `origin_type`/`asset_name`/`env_index` are ignored; (2) env 0's tile sits far from the world origin (32×32 grid of 8 m tiles centered on origin → tile (0,0) at (−124,−124), and the initial terrain *level* is `torch.randint`, so even x varies per run); (3) the default terrain `visual_material` is `PreviewSurfaceCfg(diffuse_color=(0,0,0))` — pure black diffuse | In the runner under `--video`: set `terrain.max_init_terrain_level=0` (pins env 0 to tile (0,0)), compute the tile origin from the generator cfg (`(0.5−0.5·num_rows)·size` per axis), aim `viewer.eye/lookat` at those absolute coords, and override the terrain visual material to a gray `PreviewSurfaceCfg`. Verify frames with ffmpeg → PNG before trusting the mp4 |
| run3 & run4: success rate pinned at 0.0000 for the whole run (~27M env-steps combined) | Sparse/hard-to-discover reach signal: +reach bonus only inside a 0.15 m radius, while a per-step −5 collision charge dominated return variance and the clamped progress term couldn't overcome it — the policy never got a usable gradient toward "go to the goal" | run5 reward redesign: make the collision penalty **one-shot** (charged once, at first contact of the episode), raise the reach bonus (10→25), and relax the success radius (0.15→0.30 m) so reaching is discoverable. Detection clue: success 0.0 while mean reward is flat and strongly negative, episode length always at max (never terminates via reach) |
| run5 demo videos show NO obstacle avoidance (turn-and-drive only), despite success 0.62 | **Task-validity flaw**: clear 1.0 m spawn platform + 1.5–3.0 m goal ring ⇒ most spawn→goal chords are unobstructed — measured on CPU: only 12.9% (wall-maze) / 11.5% (rail yard) of run5-style chords blocked. Avoidance was neither required nor shaped; metrics looked healthy, only the videos exposed it | Blocked-goal sampling (PointNav geodesic-filter analog): reconstructable terrain layouts (per-tile RNG keyed by (seed, difficulty) only, pure layout functions, bit-exact replay inside the env → obstacle table; `layout_version` field busts the terrain cache), then rejection-sample goals whose chord is blocked+clear (ring widened 3.0→3.6 m, 64 attempts; measured acceptance 87–94%), constructive behind-a-wall fallback (~99%), honest final `_chord_blocked` recheck. Detection clue: success/collision metrics fine but rollouts ignore the LiDAR — always verify behavior on video, not just scalars |
| run6 (100% blocked goals): success discovery flat ~1.8% of logged iterations over 2.4M steps (~500 iters); reward plateaus positive (~85), collision 0.5–1.0, reach bonus almost never fires | **Potential-field local minimum**: with pure distance shaping, a detour temporarily INCREASES goal distance ⇒ negative progress reward ⇒ going around a wall is locally unrewarded, so blocked-goal reach is practically undiscoverable by exploration. run5's 87% unblocked goals were exactly its bootstrap | run7 auto-curriculum on the blocking fraction: start at `block_prob_start=0.2` (bootstrappable, run5-like mix), ramp p toward 1.0 when the EMA of *blocked-goal* success exceeds the gate (0.2), decay p when below (self-stabilizing); log `Curriculum/block_prob` and `Metrics/blocked_success_rate`; `curriculum_fixed_block_prob ≥ 0` pins p for evaluation. Detection clue: flat low-rate success discovery DESPITE positive plateaued reward in a task where every goal requires a non-monotone path |
| run7–run8: the auto-curriculum pinned p at 0.20–0.22 for the entire run; blocked success oscillated 0.03–0.18, never sustained above the 0.2 gate; run8 added clearance shaping (−0.3·proximity from LiDAR min-range) — overall success slightly better (~0.43–0.56) but blocked success still flat, no trend | **Chicken-and-egg gate stall**: the closed-loop gate raises p only after blocked success crosses 0.2, but blocked success can only rise with EXPOSURE to blocked episodes — meanwhile the 80% easy episodes keep reinforcing straight-line driving. Shaping (clearance) changed the reward landscape but exposure, not landscape, was the binding constraint | run9 **scheduled blocking ramp**: after bootstrap (~iter 200), p follows a fixed open-loop time schedule 0.2 → 1.0 (steps 4800 → 19200) regardless of current blocked success; the gate controller stays as the fallback branch (`block_ramp_steps > 0` selects the ramp). General lesson: when a curriculum variable gates its own exposure, prefer an open-loop schedule over a closed-loop gate. Detection clue: curriculum variable pinned at its lower bound while the gating metric oscillates just below threshold |

| run10 (geodesic shaping) bootstrapped ~2× slower than run9 despite a better potential: reward 14–25 vs 52–86 at the same iterations | **Quantization × clamp artifact**: the 0.25 m grid lumps ~14 control steps of motion into one lookup jump; `progress/step_dt` at the jump step is ~5 m/s, so the kinematic v_max clamp (0.755 m/s, added in run4 to kill blow-up spikes) discards ~85% of the credit. A clamp that is invisible on a smooth signal silently eats a quantized one | Residual accumulator: add each raw jump to `self._geo_accum`, emit `clamp(accum, ±v_max·dt)` per step, subtract the emit — average credit equals true motion, spikes still capped. General lesson: whenever a per-step clamp meets a lumped/quantized signal, audit the credit budget (sum emitted vs sum raw) before trusting a negative result |
| run9 died at iter 1371/1500: log ends mid-run, isaaclab.sh printed "There was an error running python" but the log contains NO Python traceback | Native (non-Python) process death inside Kit/PhysX — matches the accepted caveat "Isaac Sim can crash outright". Not RAM (9 GiB free), no concurrent jobs, metrics healthy right up to the crash | Treat the last saved checkpoint as the run's artifact (`model_1350.pt` here, save interval 50); resume only if metrics were still moving (here blocked success had been flat for ~570 iters at p=1.0 → recorded as final, no resume). Detection clue: "There was an error running python" + abrupt log end with zero traceback lines ⇒ do NOT grep for Traceback only |
| run11 (geodesic shaping, quantization fixed): p=1.0 blocked success 0.058/990 eps vs run9's 0.095/796 — WORSE, and even unblocked learning slowed (0.18 vs 0.39 at iters 200–399) | **Reward-space shaping ≠ policy learning**: the detour credit exists in the reward (geodesic potential is monotone along the true path), but a policy that only sees LiDAR + goal bearing cannot DISCOVER or ACT on the detour from shaped reward alone — the gradient is there, the information and exploration trajectory to exploit it are not. Also the 0.25 m-quantized field injects noise that slowed even unblocked learning | Three negative run families now bound the search: exposure (run9 ramp), reward direction (run8 clearance, run10/11 geodesic) — both fail ⇒ the binding constraint is INFORMATION, not sampling or reward shape. Next rung must hand the policy the solution's structure: geodesic descent direction / next-waypoint as an OBSERVATION (turn shaping into a tracking task), or subgoal waypoints. Detection clue: reward landscape provably improved (unit-tested field) yet blocked success does not move ⇒ stop optimizing the reward, optimize what the policy is told. **SUPERSEDED in part by the next row: the run10/11 field was corrupted, so "reward direction fails" is confounded** |
| run10/11 geodesic field was silently wrong: d_geo at spawn measured 0.6–0.8× the Euclidean distance (a distance field can never be below Euclidean); the corruption cost run10/11 their validity | **Unmasked zero-cost dilation bug**: the "fill inf cells inside obstacles" pass ran `nd = min(nd, shifted d)` over ALL cells, not just inf ones — 4 passes of zero-cost erosion flattened the field to 0 within ~4 cells of every goal (and eroded it near walls). The offline unit test missed it because its probe points were >4 cells from the goal | Mask the fill write with `torch.where(isfinite(d), d, nd)` and re-verify with an INVARIANT test at build time of any distance field: d(field) ≥ euclid − cell-diagonal at random free points, d ≈ octile in free space. General lesson: cleanup passes are code too — assert their invariants (here: "fill must never modify finite cells") instead of eyeballing far-field probes |
| run12 (waypoint observation, correct field): p=1.0 blocked success 0.072/1029 vs run9's 0.095/796; video shows the robot wiggling/rotating in place near spawn — no detour, no wall-pressing | **Information ≠ behavior**: handing the policy the detour as an observation (next geodesic waypoint in robot frame) did not create detour behavior. With goal bearing, waypoint bearing, LiDAR and the alive reward all active, standing still is a local optimum (alive bonus, no collision) and PPO collapsed into it — the policy never had the detour MOTOR PROGRAM in its repertoire to begin with, and no observation can be tracked by a network that has never produced the motion. Four negative families now bound the search: exposure (run9), reward direction (run8, run10/11-confounded), information (run12) | Next rung must put the behavior into the policy before RL: **BC/DAgger warm-start from an expert that tracks the geodesic field** (the expert itself is already available as `_geo_waypoint` + a pure-pursuit controller), or make the detour discoverable by shrinking the problem (subgoal / wall-length curriculum). Detection clue: bootstrap healthy + reward plateau positive but blocked success flat AND video shows a NEW passive failure mode (in-place wiggle) instead of the old active one (wall-pressing) ⇒ the added signal is being used to justify inaction, not to act. **SUPERSEDED in part by the run15 row below: the run12 waypoint obs was corrupted (40% of waypoints pointed through walls), so "information ≠ behavior" is confounded — the policy was handed a steering signal that pointed through walls, and the information hypothesis remains UNTESTED with a correct signal** |
| run13 (BC warm-start + PPO): early blocked success 0.10–0.16 (~2× run9/run12 at the same stage) DECAYS to 0.05–0.10 by iters 500–1500; overall 0.089/1103 ≈ run9's 0.095, vs the expert's own 0.636 | **BC injection works, PPO erosion wins**: the warm-start provably puts the detour motor program into the policy (the 2× early advantage), but with no mechanism to persist the cloning prior, the on-policy gradient drifts back to the alive-reward standing-still attractor — the same attractor that swallowed run12's waypoint policy. A one-shot BC init is not a behavior anchor; imitation must either stay in the loop (DAgger / expert-mixed rollouts) or be enforced as a regularizer (KL to the BC policy), or the task must shrink until RL can self-sustain the detour. Detection clue: healthy instant bootstrap + early advantage that monotonically decays over hundreds of iterations ⇒ the prior is being unlearned, not refined |
| run13 prep — BC expert validated on 12 blocked-goal episodes (seed 42, 300-step budget, `/tmp/dbg_expert.py`): success 0.58 → **0.75** (LOOKAHEAD 0.60 → 0.85 m, one change), all successes collision-free in 195–274 steps; the 3 failures stall at min_gd 0.66–0.77 m in tight goal pockets. Ported as `GeodesicExpert` into `23_collect_openmover_demos.py` | Three expert-design lessons: (1) **the field leaks through walls** — the fill sweeps copy finite values into inflated wall cells, so EVERY wall decision (descent chain, pursuit chords, goal-direct check) must consult `_geo_occ` occupancy, never `_geo_field` values; (2) **grid-corner cutting is invisible to floor-based cell tests** — a chord to a diagonal neighbor passes exactly through the shared corner; probe points along the segment (10 samples) against occupancy are the only reliable oracle; (3) **evaluate the expert over MANY random layouts before single-seed tuning** — the same controller that "fails" a hand-picked hard pocket scores 0.75 overall. Also a metric bug found here: reading `env._reached` AFTER `env.step()` always returns False because `_reset_idx` already cleared it inside the same step — read `info["log"]["Metrics/success_rate"]` instead. General lesson: never trust a per-episode flag read after an auto-reset; use the metric logged inside `_reset_idx` before the clear |
| run14 follow-up (long BC): retrained the clone on the same 738k DAgger aggregate with 60 epochs / batch 1024 / lr 1e-3 (≈43k optimizer steps vs 1–2.7k before): val act-MAE improved 0.23 → 0.148, yet closed-loop blocked success DROPPED 0.096 → 0.044 | **Open-loop sharpness ≠ closed-loop skill**: a sharper fit on the demo distribution is not a better driver; once undertraining is ruled out (MAE kept improving while closed-loop got worse), the remaining suspect is the signal itself, not the learner. Detection clue: clone far below expert AND DAgger (distribution shift) AND long training (capacity/underfitting) both fail to move the ceiling ⇒ audit the observations, not the training recipe |
| run15 diagnosis: the student's waypoint obs was corrupted — measured during an expert rollout at block_prob=1.0, **40% of obs waypoints pointed through walls** (straight chord from the robot crosses occupied cells) and 30% of waypoints sat INSIDE wall cells | **`_geo_waypoint` forgot the occupancy lesson**: it walked `_geo_field` with an UNMASKED 8-connected greedy descent. The fill sweeps copy finite field values into wall cells (known since run13-prep), so the descent leaked straight through walls; the diagonal moves additionally cut grid corners; and the returned cell was never chord-checked. The clone was being trained to steer at points on the far side of walls — this, not imitation difficulty, explains the 0.05–0.12 cloning ceiling vs the expert's 0.64, and retroactively confounds run12 (its "information ≠ behavior" verdict trained on the same corrupted signal) | Fix (run15, one env change): `_geo_waypoint` now does occupancy-masked 4-connected descent with dead-end detection and returns the farthest CHORD-CLEAR point of the descent chain — the exact construction the validated expert chases. Verified with the same probe: 0.000 blocked chords and 0.000 in-wall waypoints whenever the robot's own cell is clear (the residual 7.5% are exactly the samples where the robot itself is inside an inflated wall cell, where every chord fails and the waypoint correctly collapses to the robot). General lesson: **before concluding imitation is hard, audit observation geometry against the oracle** — replay the expert, reconstruct each derived observation in world frame, and test it with the same occupancy oracle the expert uses. Corrupted inputs make perfect learners look capped |
| run16 (DAgger v2, clean obs): 4 rounds of on-policy relabeling oscillate around 0.25 blocked success (full-protocol 0.224/2090 eps) — same ceiling as the plain clone, still 2.8× below the expert | **Distribution shift definitively NOT the binding constraint** — now proven twice (run14 under corrupted obs, run16 under clean obs). The clone fails at states BOTH datasets cover, so the missing piece must be a signal the policy lacks at decision time, not better state coverage. Suspicion fell on the expert's unstuck/backup state machine, which is gated on CONTACT FORCE — a quantity absent from the policy obs, making those labels effectively stochastic for the clone and collapsed by MSE averaging | run17 (one bounded change): add normalized net contact force as 1 obs dim (1208-d), re-collect demos, re-clone. Blocked success 0.234 → **0.287** (+23% relative) ⇒ the contact obs was a real second binding constraint: the clone can now condition recovery behavior on the same signal that gates the expert's. General lesson: **when imitation stalls despite clean obs and on-policy data, check which internal signals the expert conditions on that the student cannot observe** — every hidden state of the teacher's controller is a candidate observation. Detection clue: residual gap concentrates near contact/stuck events and DAgger does not move the ceiling |
| User review of the recordings: "the robot always shows up in center, the center is always empty, there is no marking of start and end, 10–30 s of moving around a little — even my 2D pathfinder animations present better; what does this achieve?" | **Scalars and unmarked 3D video do not communicate the task**: the spawn sits on a deliberately clear 1 m platform at the tile center (reset physics), the camera is fixed there, and the goal existed only as numbers inside the observation — so recordings showed a small robot in a mostly empty room where success and failure look identical, and early-failing episodes read as "wiggling". The eval numbers were real but the artifact was illegible, which fairly reads as "nothing was done" | Presentation layer (2026-09-04, video mode only, zero physics/obs impact): visual-only START (blue) / GOAL (green) discs via `VideoMarkers` in `21_run_openmover_nav.py`; per-step trace npz dump (pose+yaw, episode boundaries, tile occupancy grid); `26_render_topdown_video.py` renders a 2D top-down trace animation (walls, START, GOAL star, red path, heading wedge) — the classical pathfinder-style view, but driven by the learned policy. General lesson: qualitative artifacts need the same engineering as metrics; a demo that requires verbal explanation is a bad demo |

General lesson from the nav gate: **ROS 2 parameter typing is strict** — every wildcard
(`/**`) yaml entry reaches every node it matches, including in-process sub-nodes (nav2
costmaps), and a type mismatch is a hard `InvalidParameterTypeException` abort. When a
product node crashes at startup, check `declare_parameter` types in the source against the
yaml before blaming the sim.

General Isaac Lab (3.0) lessons from the env scaffold:

- **Obs/quat conventions:** data tensors are accessed via `.torch` (e.g.
  `robot.data.root_pos_w.torch`); `root_quat_w` is **xyzw**, not wxyz — yaw extraction
  and reset quaternions must follow that order.
- **RayCaster:** exactly one mesh prim (`mesh_prim_paths=["/World/ground"]`), missed
  rays = `inf` (clamp to max range before normalizing); ray count for a ±90° FOV is
  `ceil(fov/res)+1` → `horizontal_res=0.3006` gives exactly 600 rays; `update_period`
  must be an integer multiple of sim dt (15 Hz = 8/120).
- **Reset/write API:** `write_root_pose_to_sim_index` / `write_root_velocity_to_sim_index`
  / `write_joint_position_to_sim_index` / `write_joint_velocity_to_sim_index` with
  `default_root_pose.torch[env_ids]` + `scene.env_origins[env_ids]` (plain tensor).
- **Benign noise at startup:** `Failed to find articulation/rigid body at
  .../base_link/base_link` warnings (sensor child-Xform probing) and URDF-converter
  warnings (merged lidar links, MuJoCo actuator gains) — neither affects PhysX.
- **Observation norm over a batch is misleading**: `obs.norm()` spans all envs; check
  per-slice min/mean/max instead (a "2× too high" norm was just 4 envs in one tensor).
- **Terrain generators:** custom sub-terrains = `SubTerrainBaseCfg` subclass with
  `function(difficulty, cfg) -> (list[trimesh.Trimesh], origin)` returning meshes in
  `[0,size]²` with origin at the tile center (`make_plane(size, 0.0, center_zero=False)`
  for the floor). Set `seed=` whenever `use_cache=True` (else a reproducibility warning
  and non-reproducible cache). RayCaster keeps working unchanged — it resolves the first
  `Mesh` child under `prim_path` (`/World/ground/terrain`). Real ray hits cost
  throughput (~2.4× at 1024 envs here).
- **RSL-RL training:** the unified trainer (`isaaclab.sh train --rl_library rsl_rl` /
  `scripts/reinforcement_learning/train.py`) only auto-imports `isaaclab_tasks` — an
  external task package must be imported *before* config resolution (wrapper script), and
  the trainer script needs its own directory on `sys.path` (it does `from common import
  ...`). Set `obs_groups = {"actor": ["policy"], "critic": ["policy"]}` (role -> env
  observation group names; the reverse mapping crashes with "Observation 'actor' in
  observation set 'policy' not found"). Training shows recurrent rare reward-collapse
  spikes (run1 @256 envs: ~−430/iter for a few iters; run3 @1024 envs: −288 and
  −1598 single-iteration mean returns) that self-recover — suspected cause is a
  physics blow-up (robot ejected by the solver) hitting the **unclamped** progress
  reward `progress / step_dt`. Follow-up: clamp per-step progress to the kinematic
  limit before the next serious training campaign.

## Tuning values that matter

- Physics dt ≈ 0.0167 s (60 Hz); scan tick 1/15 s.
- RTF: 0.57 (render every step) → ~12 (gated unpaced) → ~0.87 (paced alone), ~0.6 (paced
  with full stack).
- `bridge_core.KD = 20.0`; `WHEEL_SEPARATION = 0.32`, `WHEEL_RADIUS = 0.09` (pioneer3dx).
- QoS: all bridge publishers reliable depth 10; `/tf_static` transient-local (Stack B);
  slam `/map` transient-local (Stack B).
- RAM: preflight abort < 8 GiB, warn < 12.5 GiB; bridge RSS grows to ~6 GiB over a run.

## Accepted caveats

- **Kinematics mismatch:** Isaac drives the pioneer3dx asset (0.32/0.09) while the openmover
  Gazebo DiffDrive plugin uses 0.324/0.05035. Bring-up only needs Isaac to be internally
  consistent (it is: ROS-reported pose == Isaac ground truth), so this was accepted.
- RTX LiDAR ranges read ~0.1 m short of geometric truth (asset/optical offset of the
  Example_Rotary_2D config).
- `speaker_handler` may warn if `~/openmover_robot/sounds` is missing — harmless.
- `teleop_handler` dies (exit −6) when the stack runs headless — harmless for
  simulation; the product teleop path is not needed by the gates.
- `relocalization_2d_handler` segfaults (exit −11) ~1.8 s after launch — observed
  reproducibly, not yet root-caused; non-blocking (relocalization is not needed when
  the spawn pose is already in-map, which cartographer handles).
- Isaac Sim can crash outright (SIGSEGV in `libcarb.tasking`) while another process is
  pip-installing into its bundled Python or under RAM pressure — finish installer jobs
  before launching the bridge; the crash reporter auto-uploads the minidump.
- Stopping the stack with SIGINT orphans some child-launched product nodes
  (`localization_handler`, cartographer nodes, `relocalization_2d_handler`); kill
  leftovers before the next boot (see 04, navigation gate notes). Stale DDS discovery
  can also show duplicate node names in `ros2 node list` briefly after a restart.
- Isaac Sim is 6.0.1-**rc.7**; if odd Kit bugs appear, re-fetch stable 6.0.1 (no work lost —
  everything is scripts + USD).

## Trace & renderer bugs (2026-09-04, presentation pipeline)

- **Phantom trace jump (post-reset pose buffers).** In `ManagerBasedRLEnv.step()`,
  resets happen BEFORE observations are recomputed, so after `env.step()` returns on a
  done step the robot pose buffers already hold the POST-reset spawn while the LiDAR
  `ray_hits_w` still belongs to the pre-reset (terminal) pose (verified empirically:
  every old episode trace ended exactly at the next spawn, |last−spawn| = 0.00). The old
  showcase traces therefore reported contaminated path lengths (source "6.0 m", rail
  "4.6 m"); corrected under the prev-frame scheme (close the old episode with the
  pre-reset frame, start the new one on the next append): **2.87 m / 2.49 m**. Numbers in
  06 §3 updated accordingly.
- **LiDAR misses are finite hits at max_distance.** IsaacLab's RayCaster reports a
  missed ray as `origin + dir·max_distance` (finite!), so an `isfinite` mask does not
  catch it. Mask by range from the scanner origin (≥ 9.9 m ⇒ NaN) both when recording
  (21_run) and when drawing (26_render).
- **Matplotlib canvas-blit pitfalls.** Rendering the static occupancy layer via a
  figure buffer and re-`imshow`-ing it per frame silently (a) letterboxes the square
  map inside the 16:9 buffer and re-stretches it (walls drawn at ~56% scale while
  overlays stay true-scale ⇒ LiDAR fans appear to pass through walls), (b) flips
  vertically if `origin` mismatches the buffer's top-row convention, (c) shifts if one
  figure has a title and the other does not. Fix: rasterize the occ layer with plain
  numpy into a canvas whose meter-window has exactly the frame aspect (16:9), and make
  both figures full-bleed (`subplots_adjust(0,0,1,1)`, title as data-coord text).

## Custom-map spawn crush (2026-09-04, ring gallery map)

The expert scored 0.046 success / 1.000 collision on the ring map while the same
expert scored 0.629 on the source task. Zero-action debugging (no policy in the
loop: reset, step zeros, read the contact sensor) showed the robot physically
crushed at spawn: 4.5–8.4 kN on base_link at rest, tipping by t=0.1 s, dragged
0.28 m with zero commands. Two independent defects:

- **Env→tile stacking (the main one).** Isaac's `_compute_env_origins_curriculum`
  assigns `terrain_types = arange(num_envs)//(num_envs/num_cols)` (grouped by
  column) and `terrain_levels = randint(...)` (random row), so with 4 envs on a 2×2
  tile grid env0+env1 (and env2+env3) can land on the SAME tile. The source task
  never showed this (1024 tiles, spawn jitter ±0.3 m), but a custom map fixes the
  spawn identically on every tile — so the two robots spawn stacked exactly on top
  of each other (chaotic +z forces = one robot climbing the other). Fix: round-robin
  env→tile assignment in the env when `use_map_spawn_goal`, plus a hard error if
  `num_envs > num_tiles`.
- **Hull clearance at the marked spawn.** base_link's collision mesh (base_link.STL
  incl. merged LiDAR bumpers) has AABB x ±0.250, y ±0.210 → planar half-diagonal
  0.327 m. The ring spawn sat 0.312 m from the west wall, so at most random yaws
  the hull intersected the wall at reset (persistent ~6.5 kN). Fix: `_safe_map_point`
  snaps any marked spawn/goal closer than 0.36 m to a wall onto the nearest clear
  0.25 m grid point within 2 m (logs `[nav] <name> snapped ...`), and the ring
  generator now places the spawn at the corridor center. Same class of bug caught on
  the serpentine goal (0.125 m slot between last wall and boundary — physically
  narrower than the robot; moved to cell 56).

Debugging notes for the next time: zero-action rest force on the contact sensor is
the fastest discriminator (source baseline: exactly 0.0 N at rest); the force VECTOR
direction identifies the offender. Terrain placement was verified correct along the
way (cached mesh.obj is stored center-frame, Isaac translates by tile centers; the
env's obstacle table matches the mesh — proven again by the source task), and
`TerrainImporter.meshes` is deprecated and returns `{}` (cannot probe the live mesh
through it). Rule of thumb for authored maps: spawn/goal ≥ 0.4 m from any wall,
corridors ≥ 0.8 m.

## Long-map expert failures: horizon truncation + geodesic-field convergence (2026-09-04, slalom/serpentine gallery maps)

Expert scored 0.000 on slalom and serpentine while ring/rooms worked. Two
independent causes, both invisible in the runner's summary line alone:

- **Horizon truncation reads as "robot never moved".** The runner extended the
  episode horizon by `path_len/0.45 + 5`, too optimistic (measured expert
  effective speed ~0.31–0.36 m/s straight, ~0.25 m/s switchback-heavy). Episodes
  auto-reset EXACTLY at the horizon, and the end-of-run diagnostics print the
  POST-RESET pose — so `displacement env0: [0.002, 0.000] m` looked like "the
  robot never moved" when it had actually driven ~18 m and been truncated.
  Debug discriminator: `episode-reset batches observed=N` equal to num_envs with
  zero mid-run resets means every episode hit the horizon. Fix: horizon =
  `path_len/0.25 + 10`, cap 160 s (slalom 91 s, serpentine 138 s).
- **Geodesic field did not converge on long maps.** `_update_geo_fields` relaxes
  the distance field for `geo_iters=72` sweeps (~1 cell of progress per sweep),
  tuned for the ~60-cell source tile. Serpentine's 32 m path is ~128 cells, so
  the spawn cell stayed `inf` (finite frac 0.795, spawn field=inf); the expert's
  descent chain dead-ends in an all-inf neighbourhood and the robot spins in
  place for the whole episode (`d_geo` pinned at the 16.0 lookup clamp).
  Discriminator: dbg prints `FIELD finite frac` and per-env `field=<val>` at the
  spawn cell — 1.0/finite means converged. Fix (runner, custom-map path only):
  `geo_iters = max(default, path_len/geo_res + 40)`; source training untouched.
  After both fixes the expert threads all six serpentine lanes (dbg: corner trace
  visits each corridor in order, d_geo 32.7→0.25, goal reached ~105 s).

Note for evaluators: `blocked-goal episodes: 4 of 4 (100%)` on gallery maps is
expected and harmless — the metric flags the spawn→goal CHORD as intersecting a
wall (true for every maze), not goal reachability.

## Follow-ups (not blocking)

1. Import the **openmover URDF** into Isaac so geometry/kinematics match the product stack
   exactly (replaces the pioneer3dx asset; re-derive the servo gains).
2. Add `respawn=True` (or a TF-ready startup delay) for `obstacle_handler` in bringup —
   needs a ROS-side change, ask first.
3. ~~Nav2 / cartographer against Stack A~~ — DONE: navigation gate passed (see gate
   results above). Remaining: multi-goal/longer routes, recovery (`blocked` state) and
   relocalization-from-wrong-pose exercises.
4. Characterise/compensate the ~0.1 m LiDAR bias if map accuracy becomes an issue.
5. Longer-soak RAM profiling of the bridge before unattended runs.
6. Root-cause the `relocalization_2d_handler` segfault (exit −11 ~1.8 s after launch).
7. **Env factory v1 gaps** (before the paper experiments): clamp per-step progress
   reward to the kinematic limit (kills the −300..−1600 spikes); source-world dynamics
   randomization (required by `docs/research/03_paper_one_scope.md`); Target-2/3
   degraded dynamics are global only — add spatial friction patches, action latency,
   sensor noise; enforce goal reachability in cluttered tiles.
