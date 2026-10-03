"""Environment config for openmover LiDAR point-goal navigation (direct RL).

Observation layout (1204-dim):
    - 600 front LiDAR ranges + 600 rear LiDAR ranges, normalized by max range
      (a missed ray = max range = 1.0)
    - goal position in robot frame (x, y), normalized by the goal ring radius
    - forward velocity vx and yaw rate wz, normalized

Action: 2 wheel velocity targets in [-1, 1], scaled by wheel_max_speed [rad/s].
"""

from __future__ import annotations

import isaaclab.sim as sim_utils
from isaaclab.assets import ArticulationCfg
from isaaclab.envs import DirectRLEnvCfg
from isaaclab.scene import InteractiveSceneCfg
from isaaclab.sensors import ContactSensorCfg, RayCasterCfg
from isaaclab.sensors.ray_caster import patterns
from isaaclab.sim import SimulationCfg
from isaaclab.terrains import TerrainImporterCfg
from isaaclab.utils.configclass import configclass

from .openmover_cfg import OPENMOVER_CFG
from .openmover_terrains import OPENMOVER_TERRAINS_CFG, RAIL_YARD_TERRAINS_CFG

# bluesea2 spec: 600 samples over +/-90 deg => resolution 0.3006 deg gives
# exactly ceil(180 / 0.3006) + 1 = 600 rays
LIDAR_NUM_RAYS = 600
LIDAR_PATTERN = patterns.LidarPatternCfg(
    channels=1,
    vertical_fov_range=(0.0, 0.0),
    horizontal_fov_range=(-90.0, 90.0),
    horizontal_res=0.3006,
)


@configclass
class OpenmoverNavEnvCfg(DirectRLEnvCfg):
    # env
    decimation = 6  # 6 sim steps @ 1/120 s => 20 Hz control
    episode_length_s = 15.0
    action_space = 2
    observation_space = 2 * LIDAR_NUM_RAYS + 4  # scans + goal(2) + (vx, wz)
    state_space = 0

    def __post_init__(self):
        # run12: waypoint observation appends 3 dims (see use_waypoint_obs)
        if self.use_waypoint_obs:
            self.observation_space = 2 * LIDAR_NUM_RAYS + 4 + 3
        # run17: contact-force observation appends 1 dim (see use_contact_obs)
        if self.use_contact_obs:
            self.observation_space += 1

    # simulation
    sim: SimulationCfg = SimulationCfg(dt=1 / 120, render_interval=6)

    # scene
    scene: InteractiveSceneCfg = InteractiveSceneCfg(num_envs=16, env_spacing=6.0)

    # terrain: source world = wall-maze tiles (one room per env); the
    # environment factory (Phase 2) will swap in the target worlds via
    # terrain_type="generator" / "usd"
    terrain: TerrainImporterCfg = TerrainImporterCfg(
        prim_path="/World/ground",
        terrain_type="generator",
        terrain_generator=OPENMOVER_TERRAINS_CFG,
        collision_group=-1,
        physics_material=sim_utils.RigidBodyMaterialCfg(
            static_friction=1.0,
            dynamic_friction=1.0,
            restitution=0.0,
        ),
        debug_vis=False,
    )

    # robot
    # Spawn lifted 5 mm: at z=0 the four caster balls sit EXACTLY tangent to the
    # ground mesh (ball-centre height == ball radius), i.e. zero separation. On
    # the first physics substep after reset PhysX resolves that degenerate
    # contact by ejecting a fraction of the envs (measured on f1_b0_m01, 16 envs,
    # fresh process: 3/16 and 5/16 launches over seeds 42/43, worst |v_xy|
    # 12.1 m/s and +0.93 m in z within 0.05 s of zero action). With CCD off, the
    # airborne robot then tunnels the 0.125 m border walls and leaves the map --
    # the "collision leak" of ledger §17.18. A 5 mm lift removes it completely
    # (0/32 launches, 0/32 pops, worst |v_xy| 0.006 m/s); the drop impact
    # (~0.31 m/s) stays under bounce_threshold_velocity=0.5 so nothing bounces.
    # enable_stabilization and enable_ccd were both tested and do NOT fix it.
    robot_cfg: ArticulationCfg = OPENMOVER_CFG.replace(
        prim_path="/World/envs/env_.*/Robot",
        init_state=ArticulationCfg.InitialStateCfg(pos=(0.0, 0.0, 0.005)),
    )
    wheel_max_speed: float = 10.0  # rad/s -> ~0.5 m/s linear at wheel radius 0.050353
    wheel_radius: float = 0.050353  # m (URDF); used to clamp the progress reward

    # LiDARs (mounts merged into base_link by the URDF converter; offsets match
    # src/openmover/urdf/robot_description.urdf)
    lidar_front: RayCasterCfg = RayCasterCfg(
        prim_path="/World/envs/env_.*/Robot/Geometry/base_link",
        mesh_prim_paths=["/World/ground"],
        offset=RayCasterCfg.OffsetCfg(pos=(0.22015, 0.0, 0.07513), rot=(0.0, 0.0, 0.0, 1.0)),
        pattern_cfg=LIDAR_PATTERN,
        ray_alignment="yaw",
        max_distance=10.0,
        update_period=8 / 120,  # 15 Hz, integer multiple of sim dt
        debug_vis=False,
    )
    lidar_rear: RayCasterCfg = RayCasterCfg(
        prim_path="/World/envs/env_.*/Robot/Geometry/base_link",
        mesh_prim_paths=["/World/ground"],
        offset=RayCasterCfg.OffsetCfg(pos=(-0.22015, 0.0, 0.07513), rot=(0.0, 0.0, 1.0, 0.0)),
        pattern_cfg=LIDAR_PATTERN,
        ray_alignment="yaw",
        max_distance=10.0,
        update_period=8 / 120,
        debug_vis=False,
    )

    # collision detection on the body
    contact_sensor: ContactSensorCfg = ContactSensorCfg(
        prim_path="/World/envs/env_.*/Robot/Geometry/base_link",
        history_length=0,
    )
    contact_threshold: float = 5.0  # N

    # goal sampling (ring around the spawn point, in the env origin frame)
    # goal ring must stay inside the 8 m tiles (boundary walls at +/-4 m)
    # run6: ring widened 3.0 -> 3.6 so chords reach more walls (measured on
    # CPU: blocked-goal acceptance 53% -> 87-94% across the two worlds)
    goal_min_radius: float = 1.5
    goal_max_radius: float = 3.6
    # run5: 0.15 m was too tight to ever be discovered by exploration
    # (run3/run4: success 0.0 across ~27M env-steps); 0.30 m keeps the task
    # honest (still requires deliberate docking) while being reachable
    goal_success_dist: float = 0.30
    spawn_pos_jitter: float = 0.3  # +/- m, xy
    # run6: rejection-sample goals until the straight spawn->goal chord is
    # blocked by an obstacle — run5's ring sampling rarely blocked the chord
    # (measured: only ~13% of goals were blocked), so the policy learned
    # turn-and-drive, not avoidance (exposed by the demo videos). Remaining
    # envs get a constructive goal behind a reachable wall; the last resort
    # is the first (unblocked) candidate.
    goal_block_attempts: int = 64
    goal_block_pad: float = 0.15  # m; inflate obstacles by ~robot half-width
    # run7: auto-curriculum on goal blocking. run6 (100% blocked goals) failed
    # to bootstrap: success discovery stayed flat at ~1.8% of logged iterations
    # over 2.4M steps (no upward trend) — with pure distance shaping a detour
    # temporarily INCREASES goal distance (negative progress reward), so the
    # reach bonus almost never fired (potential-field local minimum). The env
    # now starts with ``block_prob_start`` blocked goals (bootstrappable like
    # run5's mostly-clear chords) and ramps the fraction toward
    # ``block_prob_target`` whenever the EMA of *blocked-goal* success exceeds
    # ``block_success_gate``; it decays back when blocked success falls below
    # the gate (self-stabilizing loop). Set ``curriculum_fixed_block_prob >= 0``
    # to pin the fraction (evaluation protocol).
    block_prob_start: float = 0.2
    block_prob_target: float = 1.0
    block_success_gate: float = 0.20
    block_prob_gain: float = 0.01  # p adjustment per reset batch per unit gate error
    block_success_ema_alpha: float = 0.1
    curriculum_fixed_block_prob: float = -1.0  # <0: curriculum active; else fixed p
    # run9: SCHEDULED blocking ramp (used instead of the gate controller when
    # block_ramp_steps > 0). The gate controller (run7/8) is chicken-and-egg:
    # blocked success cannot rise without exposure, but exposure only rises
    # once blocked success crosses the gate — meanwhile the 80% easy episodes
    # reinforce straight-line driving. A fixed schedule (in per-env control
    # steps; 24 steps = 1 training iteration) forces the gradient onto blocked
    # episodes after the reach bootstrap (~iter 200).
    block_ramp_start_steps: int = 4800   # ~iteration 200
    block_ramp_steps: int = 14400        # ramp iters ~200-800

    # reward scales
    reward_progress: float = 2.0
    reward_alive: float = 0.05
    reward_reach: float = 25.0
    # run5: ONE-SHOT penalty, charged once per episode at first contact
    # (a per-step -5 dominated return variance and starved the goal signal)
    reward_collision: float = -5.0
    # run8: dense obstacle-clearance shaping. run7 reached goals (~0.5 on the
    # easy mix) but on blocked goals it pressed into the nearest wall and
    # stopped (video-verified): straight-line progress is a potential field
    # whose local minimum sits AT the blocking wall, so nothing rewarded
    # sliding along it toward the gap. A small smooth penalty for being close
    # to any obstacle makes walls repulsive and the gap the only direction
    # with both clearance and progress. Weight kept small vs the run3/run4
    # per-step -5 that collapsed training (this one is bounded in [0, 0.3]).
    reward_clearance: float = -0.3
    clearance_thresh: float = 0.5  # m; penalty support radius
    # run10: GEODESIC potential shaping. Runs 6-9 established that the binding
    # constraint is the reward landscape, not exposure: Euclidean progress
    # makes wall-sliding zero/negative reward, so a detour is a potential-field
    # local minimum (video-verified: robot noses into the wall end and stops
    # while the gap stands wide open). Replace the progress potential with the
    # geodesic distance to the goal on a coarse occupancy grid of the exact
    # tile layout (obstacle table), computed per episode at reset by Bellman
    # relaxation. Along any shortest path the geodesic potential decreases
    # monotonically, so sliding along a wall toward the gap IS progress.
    # Phi = -d_geo is potential-based shaping, so optimal policies are
    # preserved. On unblocked goals d_geo ~ Euclidean, so easy episodes are
    # unaffected.
    use_geodesic_progress: bool = False
    geo_res: float = 0.25     # m per cell (8 m tile -> 32x32 grid)
    geo_inflate: float = 0.20  # obstacle inflation for the grid (robot half-width + margin)
    geo_iters: int = 72       # Bellman sweeps (>= longest free path in cells, ~62)
    # run12: waypoint observation. Runs 6-11 showed the binding constraint is
    # INFORMATION, not exposure or reward direction: the policy is never told
    # the path bends around the wall. Each step, append to the observation the
    # next waypoint ~waypoint_lookahead m ahead along the geodesic descent
    # path (robot-frame x/y, same normalization as the goal bearing) plus the
    # remaining geodesic distance. Steering to a bearing is already in the
    # policy's repertoire (that is how it solves unblocked goals), so
    # avoidance becomes a tracking task. Reward stays run9's Euclidean
    # shaping => one change per run.
    use_waypoint_obs: bool = True
    waypoint_lookahead: float = 1.0  # m ahead along the geodesic path
    # run17: net contact-force magnitude (normalized by contact_threshold) as
    # one extra obs dim. The expert's unstuck/backup state machine is gated on
    # contact, so its labels on contact states are unconditioned for a clone
    # that cannot see the force — cloning stalls exactly where the expert
    # recovers. Giving the student the same input makes labels deterministic.
    use_contact_obs: bool = True

    # gallery/custom maps (27_make_custom_map.py + runner --map_file): the
    # runner swaps terrain.terrain_generator for custom_map_terrains_cfg(map)
    # and sets this flag; spawn+goal then come from the map file each episode
    # instead of ring sampling
    use_map_spawn_goal: bool = False

    # campaign eval (33_run_campaign.py): when True, _reset_idx ALSO emits
    # per-env outcome arrays (ids/reached/penalized/ttg) in extras["log"] so
    # seeds folded into num_envs=N can be split back out for mean +/- std and
    # first-episode-only capture (a fast env otherwise auto-resets into a 2nd
    # episode within the horizon, biasing the batch mean). Default False:
    # list-valued log keys would break RSL-RL's scalar tensorboard logging.
    log_per_env: bool = False


# ---------------------------------------------------------------------------
# Environment factory: target worlds for the transfer study
# (docs/research/03_paper_one_scope.md experiment design). Same env class,
# same obs/action spaces — only geometry and dynamics differ.
# ---------------------------------------------------------------------------

# Target 2/3 degraded regime (docs/research/06_validation_plan.md step 4:
# low-friction floor materials; battery/motor sag emulated by a lower wheel
# speed cap). v1 = global; spatial friction patches / latency / sensor noise
# are v2 refinements.
DEGRADED_FRICTION = 0.25
DEGRADED_WHEEL_MAX_SPEED = 6.0


def _terrain_cfg(generator, static_friction: float, dynamic_friction: float) -> TerrainImporterCfg:
    return TerrainImporterCfg(
        prim_path="/World/ground",
        terrain_type="generator",
        terrain_generator=generator,
        collision_group=-1,
        physics_material=sim_utils.RigidBodyMaterialCfg(
            static_friction=static_friction,
            dynamic_friction=dynamic_friction,
            restitution=0.0,
        ),
        debug_vis=False,
    )


@configclass
class OpenmoverNavRailYardEnvCfg(OpenmoverNavEnvCfg):
    """Target 1: railway-yard geometry, nominal dynamics."""

    terrain: TerrainImporterCfg = _terrain_cfg(RAIL_YARD_TERRAINS_CFG, 1.0, 1.0)


@configclass
class OpenmoverNavDegradedEnvCfg(OpenmoverNavEnvCfg):
    """Target 2: source-like geometry, degraded dynamics regime."""

    terrain: TerrainImporterCfg = _terrain_cfg(OPENMOVER_TERRAINS_CFG, DEGRADED_FRICTION, DEGRADED_FRICTION)
    wheel_max_speed: float = DEGRADED_WHEEL_MAX_SPEED


@configclass
class OpenmoverNavCombinedEnvCfg(OpenmoverNavRailYardEnvCfg):
    """Target 3: railway-yard geometry AND degraded dynamics."""

    terrain: TerrainImporterCfg = _terrain_cfg(RAIL_YARD_TERRAINS_CFG, DEGRADED_FRICTION, DEGRADED_FRICTION)
    wheel_max_speed: float = DEGRADED_WHEEL_MAX_SPEED
