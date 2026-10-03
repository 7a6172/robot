"""Direct-RL environment: openmover differential-drive LiDAR point-goal navigation.

Scaffold for the NMTE transfer study (docs/research/03_paper_one_scope.md):
train in a randomized source world, then evaluate the frozen policy in unseen
target worlds (geometry / degraded dynamics).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import torch

from isaaclab.assets import Articulation
from isaaclab.envs import DirectRLEnv
from isaaclab.sensors import ContactSensor, RayCaster

from .openmover_nav_cfg import OpenmoverNavEnvCfg
from .openmover_terrains import (
    TERRAIN_LAYOUT_FNS,
    TERRAIN_LAYOUT_REGISTRY,
    _tile_rng,
    load_custom_map,
)


class OpenmoverNavEnv(DirectRLEnv):
    cfg: OpenmoverNavEnvCfg

    def __init__(self, cfg: OpenmoverNavEnvCfg, render_mode: str | None = None, **kwargs):
        super().__init__(cfg, render_mode, **kwargs)

        self._actions = torch.zeros(self.num_envs, 2, device=self.device)
        self._goal_pos_w = torch.zeros(self.num_envs, 3, device=self.device)
        self._prev_goal_dist = torch.zeros(self.num_envs, device=self.device)
        self._reached = torch.zeros(self.num_envs, dtype=torch.bool, device=self.device)
        self._collided = torch.zeros(self.num_envs, dtype=torch.bool, device=self.device)
        # run5: per-episode flag so the collision penalty fires once (at first
        # contact) instead of every step; also the true "episode had contact"
        # metric (self._collided only reflects the current step)
        self._penalized = torch.zeros(self.num_envs, dtype=torch.bool, device=self.device)

        # wheel joint indices, order preserved: [left, right] == action columns
        self._wheel_idx, _ = self._robot.find_joints(
            ["wheel_left_joint", "wheel_right_joint"], preserve_order=True
        )

        # custom maps: Isaac's default assignment (random row level, grouped
        # column type) can put several envs on the SAME tile; the fixed map
        # spawn then stacks those robots exactly on top of each other (observed:
        # 4.5 kN on base_link at rest, robots climbing each other). Assign
        # round-robin so every tile hosts at most one env.
        if cfg.use_map_spawn_goal:
            to = self._terrain.terrain_origins
            num_tiles = to.shape[0] * to.shape[1]
            if self.num_envs > num_tiles:
                raise ValueError(
                    f"custom map: num_envs={self.num_envs} > {num_tiles} tiles; the "
                    "fixed map spawn would stack robots on shared tiles"
                )
            assign = torch.arange(self.num_envs, device=self.device) % num_tiles
            self._terrain.env_origins[:] = to.reshape(num_tiles, 3)[assign]

        # run6: exact obstacle footprint of every terrain tile, so goal
        # sampling can require the spawn->goal chord to be blocked
        self._build_obstacle_table()

        # custom maps (27_make_custom_map.py): fixed spawn+goal per episode,
        # taken from the map file instead of sampling (tile-center frame)
        if cfg.use_map_spawn_goal:
            sub_cfg = list(cfg.terrain.terrain_generator.sub_terrains.values())[0]
            spec = load_custom_map(sub_cfg.map_file)
            sx, sy = spec["size"]
            self._map_spawn_c = torch.tensor(
                [spec["spawn"][0] - 0.5 * sx, spec["spawn"][1] - 0.5 * sy],
                dtype=torch.float32, device=self.device,
            )
            self._map_goal_c = torch.tensor(
                [spec["goal"][0] - 0.5 * sx, spec["goal"][1] - 0.5 * sy],
                dtype=torch.float32, device=self.device,
            )
            # a marked point closer to a wall than the robot hull half-diagonal
            # spawns the robot INSIDE the wall (PhysX crushes it: ~6.5 kN on
            # base_link at rest, observed on the ring map); snap to a clear spot
            self._map_spawn_c = self._safe_map_point(self._map_spawn_c, "spawn")
            self._map_goal_c = self._safe_map_point(self._map_goal_c, "goal")
            print(f"[nav] custom map spawn/goal fixed from {sub_cfg.map_file}")

        # run10/run12: per-tile occupancy grid + a per-env geodesic distance
        # field from the current goal (recomputed at reset); used for reward
        # shaping (run10) and/or the waypoint observation (run12)
        if cfg.use_geodesic_progress or cfg.use_waypoint_obs:
            self._build_occupancy_grid()
            self._geo_field = torch.full(
                (self.num_envs, self._geo_gx, self._geo_gy),
                math.inf,
                device=self.device,
            )
            self._geo_prev = torch.zeros(self.num_envs, device=self.device)
            self._geo_accum = torch.zeros(self.num_envs, device=self.device)

        # run7: auto-curriculum state on goal blocking (see cfg comments).
        # The EMA starts at the gate (neutral prior) so the first ramp
        # decision is driven by measured blocked-goal success, not by a 0.0
        # prior. curriculum_fixed_block_prob >= 0 pins p (evaluation).
        if cfg.curriculum_fixed_block_prob >= 0.0:
            self._block_prob = float(cfg.curriculum_fixed_block_prob)
        else:
            self._block_prob = float(cfg.block_prob_start)
        self._blocked_success_ema = float(cfg.block_success_gate)
        # per-episode flag: was the goal actually behind a blocked chord?
        self._goal_is_blocked = torch.zeros(self.num_envs, dtype=torch.bool, device=self.device)
        # run12: PhysX blow-up guard state (see _get_dones)
        self._bad_state = torch.zeros(self.num_envs, dtype=torch.bool, device=self.device)

    # ------------------------------------------------------------------ scene
    def _setup_scene(self):
        self._robot = Articulation(self.cfg.robot_cfg)
        self.scene.articulations["robot"] = self._robot
        self._lidar_front = RayCaster(self.cfg.lidar_front)
        self._lidar_rear = RayCaster(self.cfg.lidar_rear)
        self.scene.sensors["lidar_front"] = self._lidar_front
        self.scene.sensors["lidar_rear"] = self._lidar_rear
        self._contact_sensor = ContactSensor(self.cfg.contact_sensor)
        self.scene.sensors["contact_sensor"] = self._contact_sensor
        # terrain (follows the anymal_c pattern)
        self.cfg.terrain.num_envs = self.scene.cfg.num_envs
        self.cfg.terrain.env_spacing = self.scene.cfg.env_spacing
        self._terrain = self.cfg.terrain.class_type(self.cfg.terrain)
        self.scene.clone_environments(copy_from_source=False)
        if self.device == "cpu":
            self.scene.filter_collisions(global_prim_paths=[self.cfg.terrain.prim_path])

    # ---------------------------------------------------------------- actions
    def _pre_physics_step(self, actions: torch.Tensor):
        self._actions = actions

    def _apply_action(self):
        target = self.cfg.wheel_max_speed * self._actions
        self._robot.set_joint_velocity_target_index(target=target, joint_ids=self._wheel_idx)

    # ------------------------------------------------------------ observations
    def _get_observations(self) -> dict:
        ranges_front = self._scan(self._lidar_front)
        ranges_rear = self._scan(self._lidar_rear)
        goal_robot_frame = self._goal_in_robot_frame()
        vx = self._robot.data.root_lin_vel_b.torch[:, 0:1]  # ~[-0.5, 0.5] m/s
        wz = self._robot.data.root_ang_vel_b.torch[:, 2:3] / 5.0
        obs = torch.cat([ranges_front, ranges_rear, goal_robot_frame, vx, wz], dim=-1)
        if self.cfg.use_waypoint_obs:
            wp = self._geo_waypoint(self._robot.data.root_pos_w.torch[:, :2])
            obs = torch.cat([obs, wp], dim=-1)
        if self.cfg.use_contact_obs:
            # run17: normalized net contact force in [0,1]; the expert's backup
            # behavior is conditioned on this, so the clone needs it too
            cf = torch.clamp(self._contact_force(), max=self.cfg.contact_threshold)
            obs = torch.cat([obs, (cf / self.cfg.contact_threshold).unsqueeze(-1)], dim=-1)
        # run12 guard: a solver blow-up leaves lidar/vel/pose non-finite;
        # sanitize so rsl_rl's check_nan aborts never kills a run (the bad
        # env is force-reset by _get_dones)
        obs = torch.nan_to_num(obs, nan=0.0, posinf=1.0, neginf=-1.0)
        return {"policy": obs}

    def _scan(self, lidar: RayCaster) -> torch.Tensor:
        """Normalized ranges in [0, 1]; missed rays clamp to 1.0 (max range)."""
        hits = lidar.data.ray_hits_w.torch  # (N, R, 3), misses are inf
        origin = lidar.data.pos_w.torch.unsqueeze(1)  # (N, 1, 3)
        dist = torch.norm(hits - origin, dim=-1)  # (N, R); inf stays inf
        return torch.clamp(dist, max=self.cfg.lidar_front.max_distance) / self.cfg.lidar_front.max_distance

    def _goal_dist(self) -> torch.Tensor:
        base_xy = self._robot.data.root_pos_w.torch[:, :2]
        return torch.norm(self._goal_pos_w[:, :2] - base_xy, dim=-1)

    def _goal_in_robot_frame(self) -> torch.Tensor:
        base_xy = self._robot.data.root_pos_w.torch[:, :2]
        q = self._robot.data.root_quat_w.torch  # (N, 4), xyzw convention
        yaw = torch.atan2(2.0 * (q[:, 2] * q[:, 3] + q[:, 0] * q[:, 1]), 1.0 - 2.0 * (q[:, 1] ** 2 + q[:, 2] ** 2))
        rel = self._goal_pos_w[:, :2] - base_xy
        cos_y, sin_y = torch.cos(yaw), torch.sin(yaw)
        gx = cos_y * rel[:, 0] + sin_y * rel[:, 1]
        gy = -sin_y * rel[:, 0] + cos_y * rel[:, 1]
        norm = 0.5 * (self.cfg.goal_min_radius + self.cfg.goal_max_radius)
        return torch.stack([gx, gy], dim=-1) / norm

    def _contact_force(self) -> torch.Tensor:
        forces = self._contact_sensor.data.net_forces_w.torch  # (N, B, 3)
        return torch.norm(forces, dim=-1).max(dim=-1).values  # (N,)

    # ------------------------------------------------------------------ dones
    def _get_dones(self) -> tuple[torch.Tensor, torch.Tensor]:
        dist = self._goal_dist()
        self._reached = dist < self.cfg.goal_success_dist
        self._collided = self._contact_force() > self.cfg.contact_threshold
        # run4: collision is a per-step penalty, NOT terminal — terminating on
        # first contact starved the agent of the experience needed to learn
        # wall avoidance (run3 collapsed to spinning, success 0.0)
        terminated = self._reached
        # run12: PhysX blow-up guard — a non-finite root state can never
        # recover; terminate the episode so the env resets instead of
        # poisoning obs/rewards (run12 launch aborted on a NaN obs at iter 0;
        # not reproducible with 4 action regimes x 256 envs x 300 steps, so
        # treat as the known rare solver blow-up, logged for the ledger)
        self._bad_state = ~torch.isfinite(self._robot.data.root_pos_w.torch).all(dim=-1)
        if bool(self._bad_state.any()):
            ids = self._bad_state.nonzero().flatten()[:8].tolist()
            print(f"[nav] guard: {int(self._bad_state.sum())} env(s) non-finite root state "
                  f"-> forced reset (envs {ids})")
        terminated = terminated | self._bad_state
        # DirectRLEnv does NOT apply the episode time-out automatically —
        # _get_dones must return it (as the stock direct envs do)
        time_outs = self.episode_length_buf >= self.max_episode_length - 1
        return terminated, time_outs

    # ---------------------------------------------------------------- rewards
    def _get_rewards(self) -> torch.Tensor:
        if self.cfg.use_geodesic_progress:
            # run10: progress along the geodesic potential (see cfg note) —
            # wall-sliding toward the gap decreases d_geo, so detours earn
            # positive progress instead of sitting in a local minimum
            dist_geo = self._geo_lookup(
                torch.arange(self.num_envs, device=self.device),
                self._robot.data.root_pos_w.torch[:, :2],
            )
            raw = self._geo_prev - dist_geo
            self._geo_prev = dist_geo.clone()
            # residual accumulator: the 0.25 m cell grid lumps ~14 steps of
            # motion into one lookup jump (~5 m/s), and the v_max clamp below
            # would then discard ~85% of the credit (run10 artifact). Drain
            # the residual at the kinematic cap so the AVERAGE credit equals
            # the true geodesic motion.
            cap = 1.5 * self.cfg.wheel_max_speed * self.cfg.wheel_radius * self.step_dt
            self._geo_accum += raw
            progress = torch.clamp(self._geo_accum, -cap, cap)
            self._geo_accum -= progress
        else:
            dist = self._goal_dist()
            progress = self._prev_goal_dist - dist
            self._prev_goal_dist = dist.clone()
        # clamp closing speed to the kinematic limit (1.5x solver margin):
        # rare physics blow-ups eject the robot and otherwise produce
        # -300..-1600 reward spikes through the unclamped progress term
        v_max = 1.5 * self.cfg.wheel_max_speed * self.cfg.wheel_radius
        speed = torch.clamp(progress / self.step_dt, -v_max, v_max)
        rew = self.cfg.reward_progress * speed
        rew += self.cfg.reward_alive * (~self._collided).float()
        rew += self.cfg.reward_reach * self._reached.float()
        # run5: charge the collision penalty once, at first contact of the
        # episode (a per-step charge dominated return variance and pushed the
        # policy away from any goal-directed exploration, runs 3 & 4)
        first_contact = self._collided & ~self._penalized
        rew += self.cfg.reward_collision * first_contact.float()
        self._penalized |= self._collided
        # run8: clearance shaping (see cfg note) — walls repulsive, gaps the
        # only direction with both clearance and progress
        d_min = self.cfg.lidar_front.max_distance * torch.minimum(
            self._scan(self._lidar_front).min(dim=-1).values,
            self._scan(self._lidar_rear).min(dim=-1).values,
        )
        prox = torch.clamp(1.0 - d_min / self.cfg.clearance_thresh, 0.0, 1.0)
        rew += self.cfg.reward_clearance * prox
        # run12 guard: same rationale as the obs sanitize (bounds = reward scale)
        rew = torch.nan_to_num(rew, nan=0.0, posinf=25.0, neginf=-5.0)
        return rew

    # ------------------------------------------------------------------ reset
    def _reset_idx(self, env_ids: Sequence[int] | None):
        if env_ids is None:
            env_ids = self._robot._ALL_INDICES

        log = self.extras.setdefault("log", {})
        reached_mask = self._reached[env_ids]
        log["Metrics/success_rate"] = reached_mask.float().mean().item()
        # run5: episodes that ever had contact (not just the final step)
        log["Metrics/collision_rate"] = self._penalized[env_ids].float().mean().item()

        # run7: update the blocking curriculum from the episodes that just
        # ended (flags belong to those episodes; _sample_goals rewrites them
        # below for the new episodes)
        blocked_flag = self._goal_is_blocked[env_ids]
        blocked_success = float("nan")
        if bool(blocked_flag.any()):
            blocked_success = reached_mask[blocked_flag].float().mean().item()
            a = self.cfg.block_success_ema_alpha
            self._blocked_success_ema = (1.0 - a) * self._blocked_success_ema + a * blocked_success
        if self.cfg.curriculum_fixed_block_prob < 0.0:
            if self.cfg.block_ramp_steps > 0:
                # run9: SCHEDULED ramp — forces gradient onto blocked episodes
                # regardless of current blocked success. The gate controller
                # below stalled in run7/run8 (exposure needs success, success
                # needs exposure), so p follows a fixed time schedule instead.
                frac = (
                    float(self.common_step_counter) - self.cfg.block_ramp_start_steps
                ) / self.cfg.block_ramp_steps
                frac = min(max(frac, 0.0), 1.0)
                self._block_prob = self.cfg.block_prob_start + (
                    self.cfg.block_prob_target - self.cfg.block_prob_start
                ) * frac
            else:
                err = self._blocked_success_ema - self.cfg.block_success_gate
                self._block_prob = min(
                    max(self._block_prob + self.cfg.block_prob_gain * err, self.cfg.block_prob_start),
                    self.cfg.block_prob_target,
                )
        log["Metrics/blocked_success_rate"] = blocked_success
        # blocked-episode count so evaluators can weight blocked_success_rate
        # across batches of different sizes
        log["Metrics/num_blocked_episodes"] = float(blocked_flag.sum().item())
        log["Curriculum/block_prob"] = self._block_prob
        log["Curriculum/blocked_success_ema"] = self._blocked_success_ema
        # time-to-goal over the successes in this reset batch (NaN if none);
        # read before super() resets episode_length_buf
        if reached_mask.any():
            ttg = self.episode_length_buf[env_ids][reached_mask].float() * self.step_dt
            log["Metrics/time_to_goal"] = ttg.mean().item()
        else:
            log["Metrics/time_to_goal"] = float("nan")

        # campaign eval (33_run_campaign.py): per-env outcome arrays so seeds
        # folded into num_envs can be split back out (mean +/- std, and
        # first-episode-only capture). Gated by cfg.log_per_env (default
        # False) because list-valued log keys break RSL-RL scalar logging.
        if self.cfg.log_per_env:
            log["Metrics/per_env_ids"] = env_ids.tolist()
            log["Metrics/per_env_reached"] = reached_mask.tolist()
            log["Metrics/per_env_penalized"] = self._penalized[env_ids].tolist()
            log["Metrics/per_env_ttg"] = (
                self.episode_length_buf[env_ids].float() * self.step_dt
            ).tolist()

        super()._reset_idx(env_ids)

        num = len(env_ids)
        joint_pos = self._robot.data.default_joint_pos.torch[env_ids].clone()
        joint_vel = self._robot.data.default_joint_vel.torch[env_ids].clone()

        root_pose = self._robot.data.default_root_pose.torch[env_ids].clone()  # (num, 7): xyz + quat xyzw
        # NOTE: use terrain origins, not scene.env_origins — in direct envs the
        # terrain is instantiated manually, so the scene falls back to a grid
        if self.cfg.use_map_spawn_goal:
            # custom map: exact spawn cell every episode (yaw stays random so
            # each episode is still a fresh search problem)
            root_pose[:, :2] = self._terrain.env_origins[env_ids, :2] + self._map_spawn_c
        else:
            root_pose[:, :2] += self._terrain.env_origins[env_ids, :2]
            # spawn jitter
            root_pose[:, :2] += (
                2.0 * torch.rand(num, 2, device=self.device) - 1.0
            ) * self.cfg.spawn_pos_jitter
        # random yaw (quat xyzw)
        yaw = 2.0 * math.pi * torch.rand(num, device=self.device)
        root_pose[:, 3:5] = 0.0
        root_pose[:, 5] = torch.sin(yaw / 2.0)
        root_pose[:, 6] = torch.cos(yaw / 2.0)

        root_vel = self._robot.data.default_root_vel.torch[env_ids].clone()

        self._robot.write_root_pose_to_sim_index(root_pose=root_pose, env_ids=env_ids)
        self._robot.write_root_velocity_to_sim_index(root_velocity=root_vel, env_ids=env_ids)
        self._robot.write_joint_position_to_sim_index(position=joint_pos, env_ids=env_ids)
        self._robot.write_joint_velocity_to_sim_index(velocity=joint_vel, env_ids=env_ids)

        self._sample_goals(env_ids, root_pose[:, :2])
        if self.cfg.use_geodesic_progress or self.cfg.use_waypoint_obs:
            self._update_geo_fields(env_ids, root_pose[:, :2])
        self._prev_goal_dist[env_ids] = self._goal_dist()[env_ids]
        self._reached[env_ids] = False
        self._collided[env_ids] = False
        self._penalized[env_ids] = False

    def _sample_goals(self, env_ids: Sequence[int], spawn_xy: torch.Tensor):
        """run6: rejection-sample goals whose straight spawn->goal chord is
        blocked by an obstacle, so EVERY episode requires avoidance.

        run5's plain ring sampling rarely put an obstacle on the chord (clear
        1.0 m spawn platform + 1.5-3.0 m goal ring; measured: only ~13% of
        chords blocked), so the learned policy was turn-and-drive with almost
        no avoidance — exposed by the demo videos. Three stages:
        1. rejection-sample ring candidates until the chord is blocked and the
           goal itself is clear of obstacles (up to ``goal_block_attempts``);
        2. remaining envs get a constructive goal placed behind a reachable
           wall of their tile (handles corner-heavy layouts where rejection
           rarely succeeds — measured on CPU: 87-94% -> ~99% blocked);
        3. last resort (tiles with no reachable blocker at all, ~1%): the
           first unblocked candidate.

        run7: only a fraction ``self._block_prob`` (the curriculum) of the
        episodes get a blocked goal; the rest accept ANY clear ring candidate
        (run5-style). Stage 2 applies only to still-unsatisfied envs that
        wanted a blocked goal. The per-episode flag reflects the ACTUAL
        blocking of the chosen goal (re-checked once at the end), which is
        what the curriculum feedback and the blocked_success metric use.
        """
        num = len(env_ids)
        if self.cfg.use_map_spawn_goal:
            # custom map: the goal is part of the map spec — no sampling
            goal = self._terrain.env_origins[env_ids, :2] + self._map_goal_c
            self._goal_pos_w[env_ids, :2] = goal
            self._goal_pos_w[env_ids, 2] = 0.0
            blocked, _ = self._chord_blocked(spawn_xy, goal, env_ids)
            self._goal_is_blocked[env_ids] = blocked
            return
        origin = self._terrain.env_origins[env_ids, :2]
        satisfied = torch.zeros(num, dtype=torch.bool, device=self.device)
        best = torch.empty(num, 2, device=self.device)
        fallback = torch.empty(num, 2, device=self.device)
        want_blocked = torch.rand(num, device=self.device) < self._block_prob
        for attempt in range(self.cfg.goal_block_attempts):
            radius = self.cfg.goal_min_radius + torch.rand(num, device=self.device) * (
                self.cfg.goal_max_radius - self.cfg.goal_min_radius
            )
            angle = 2.0 * math.pi * torch.rand(num, device=self.device)
            cand = origin + torch.stack([radius * torch.cos(angle), radius * torch.sin(angle)], dim=-1)
            if attempt == 0:
                fallback = cand
            blocked, goal_clear = self._chord_blocked(spawn_xy, cand, env_ids)
            # blocked-goal envs need blocked+clear; the rest take clear only
            take = goal_clear & ~satisfied & (blocked | ~want_blocked)
            best[take] = cand[take]
            satisfied |= take
            if bool(satisfied.all()):
                break
        # stage 2: constructive goal behind a reachable wall for the rest
        if not bool(satisfied.all()):
            miss = ~satisfied & want_blocked
            if bool(miss.any()):
                idx = torch.nonzero(miss, as_tuple=False).squeeze(-1)
                cand = self._constructive_blocked_goal(env_ids[miss])
                blocked, goal_clear = self._chord_blocked(spawn_xy[miss], cand, env_ids[miss])
                take = blocked & goal_clear
                best[idx[take]] = cand[take]
                satisfied[idx[take]] = True
        goal = torch.where(satisfied.unsqueeze(-1), best, fallback)
        self._goal_pos_w[env_ids, :2] = goal
        self._goal_pos_w[env_ids, 2] = 0.0
        # episode flag = actual blocking of the chosen goal (honest metric)
        blocked, _ = self._chord_blocked(spawn_xy, goal, env_ids)
        self._goal_is_blocked[env_ids] = blocked

    def _constructive_blocked_goal(self, env_ids: Sequence[int]) -> torch.Tensor:
        """Goal placed just behind a reachable wall of each env's tile.

        Picks a wall whose center sits inside the goal ring reach, aims the
        goal along the wall direction (jittered within its angular span as
        seen from the tile center), a little past it. The result is still
        validated by ``_chord_blocked`` in the caller.
        """
        n = len(env_ids)
        origin = self._terrain.env_origins[env_ids, :2]
        tiles = self._env_tile[env_ids]
        walls = self._obstacle_table[tiles]
        valid = (
            torch.arange(walls.shape[1], device=self.device).unsqueeze(0)
            < self._obstacle_counts[tiles].unsqueeze(1)
        )
        cx, cy, _yaw, length, _width = walls.unbind(-1)
        dist = torch.norm(walls[..., :2], dim=-1)
        # reachable = interior-ish walls the chord can actually cross
        reach = valid & (dist > 1.2) & (dist < self.cfg.goal_max_radius + 0.5)
        weights = torch.where(reach.any(dim=1, keepdim=True), reach, valid).float()
        pick = torch.multinomial(weights, 1).squeeze(-1)  # (n,)
        wcx = cx.gather(1, pick.unsqueeze(1)).squeeze(1)
        wcy = cy.gather(1, pick.unsqueeze(1)).squeeze(1)
        wdist = dist.gather(1, pick.unsqueeze(1)).squeeze(1)
        wlen = length.gather(1, pick.unsqueeze(1)).squeeze(1)
        half_span = torch.atan2(0.5 * wlen + self.cfg.goal_block_pad, wdist.clamp(min=0.1))
        angle = torch.atan2(wcy, wcx) + (2.0 * torch.rand(n, device=self.device) - 1.0) * 0.8 * half_span
        radius = torch.clamp(
            wdist + 0.3 + 0.5 * torch.rand(n, device=self.device),
            self.cfg.goal_min_radius,
            self.cfg.goal_max_radius,
        )
        return origin + torch.stack([radius * torch.cos(angle), radius * torch.sin(angle)], dim=-1)

    def _chord_blocked(
        self, spawn_xy: torch.Tensor, goal_xy: torch.Tensor, env_ids: Sequence[int]
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """(chord_blocked, goal_clear) per env for the spawn->goal chord.

        The chord is sampled at 32 points; it counts as blocked when a sample
        lies inside an obstacle box inflated by ``goal_block_pad`` (~robot
        half-width). Max sample spacing (~0.11 m at chord <= 3.5 m) stays
        below the thinnest inflated obstacle (rail 0.08 + 2*pad = 0.38 m),
        so no crossing is missed.
        """
        origin = self._terrain.env_origins[env_ids, :2]
        tiles = self._env_tile[env_ids]
        walls = self._obstacle_table[tiles]  # (n, W, 5): cx cy yaw length width, tile-center frame
        valid = (
            torch.arange(walls.shape[1], device=self.device).unsqueeze(0)
            < self._obstacle_counts[tiles].unsqueeze(1)
        )
        p0 = spawn_xy - origin
        p1 = goal_xy - origin
        t = torch.linspace(0.0, 1.0, 32, device=self.device)
        pts = p0.unsqueeze(1) + t.view(1, -1, 1) * (p1 - p0).unsqueeze(1)  # (n, S, 2)
        cx, cy, yaw, length, width = walls.unbind(-1)  # (n, W) each
        cos_y, sin_y = torch.cos(yaw), torch.sin(yaw)
        rx = pts[..., 0].unsqueeze(2) - cx.unsqueeze(1)  # (n, S, W)
        ry = pts[..., 1].unsqueeze(2) - cy.unsqueeze(1)
        lx = cos_y.unsqueeze(1) * rx + sin_y.unsqueeze(1) * ry  # rotate by -yaw
        ly = -sin_y.unsqueeze(1) * rx + cos_y.unsqueeze(1) * ry
        pad = self.cfg.goal_block_pad
        inside = (
            (lx.abs() <= 0.5 * length.unsqueeze(1) + pad)
            & (ly.abs() <= 0.5 * width.unsqueeze(1) + pad)
            & valid.unsqueeze(1)
        )
        blocked = inside[:, 1:-1].any(dim=1).any(dim=1)  # interior samples only
        goal_clear = ~inside[:, -1].any(dim=1)
        return blocked, goal_clear

    # base_link collision mesh (base_link.STL incl. merged LiDAR bumpers) has
    # AABB x +-0.2504, y +-0.2102 -> planar half-diagonal 0.327 m; any marked
    # point nearer than this to a wall intersects geometry at random yaw
    _HULL_CLEAR = 0.36  # 0.327 + small margin

    def _safe_map_point(self, pt, name):
        """Snap a map point (tile-center frame) to >= _HULL_CLEAR wall clearance.

        Distances are computed exactly against the obstacle boxes of the map
        (all tiles share the same layout for custom maps, so tile 0 suffices).
        Falls back to the nearest clear grid point within 2 m; warns if none.
        """
        boxes = self._obstacle_table[0, : self._obstacle_counts[0]].cpu().numpy()

        def clearance(p):
            d = math.inf
            for cx, cy, yaw, length, width in boxes:
                c, s = math.cos(yaw), math.sin(yaw)
                px, py = p[0] - cx, p[1] - cy
                lx, ly = c * px + s * py, -s * px + c * py
                dx = max(abs(lx) - 0.5 * length, 0.0)
                dy = max(abs(ly) - 0.5 * width, 0.0)
                d = min(d, math.hypot(dx, dy))
            return d

        p = pt.cpu().numpy().astype(np.float64)
        if clearance(p) >= self._HULL_CLEAR:
            return pt
        step, max_shift = 0.25, 2.0
        n = int(math.ceil(max_shift / step))
        best, best_d = None, math.inf
        for iy in range(-n, n + 1):
            for ix in range(-n, n + 1):
                shift = math.hypot(ix * step, iy * step)
                if shift == 0.0 or shift > max_shift or shift >= best_d:
                    continue
                q = p + np.array([ix * step, iy * step])
                if clearance(q) >= self._HULL_CLEAR:
                    best, best_d = q, shift
        if best is None:
            print(f"[nav] WARNING: no spot with {self._HULL_CLEAR:.2f} m clearance "
                  f"for {name} within {max_shift:.1f} m; keeping marked point {p}")
            return pt
        print(f"[nav] {name} snapped {best_d:.2f} m for hull clearance: "
              f"({p[0]:.3f},{p[1]:.3f}) -> ({best[0]:.3f},{best[1]:.3f})")
        return torch.tensor(best, dtype=torch.float32, device=self.device)

    def _build_obstacle_table(self):
        """Reconstruct the exact obstacle footprint of every terrain tile.

        The TerrainGenerator draws each tile's difficulty from its seeded
        Generator in a fixed order (replayed below, call-for-call), and each
        layout is drawn from a per-tile RNG keyed by (seed, difficulty) — see
        openmover_terrains.py. Hence this table matches the physical mesh
        with or without the terrain cache.
        """
        tc = self.cfg.terrain.terrain_generator
        sub_cfgs = list(tc.sub_terrains.values())
        proportions = np.array([c.proportion for c in sub_cfgs], dtype=np.float64)
        proportions /= proportions.sum()
        rng = np.random.default_rng(tc.seed)
        num_tiles = tc.num_rows * tc.num_cols
        tables, difficulties = [], []
        for _ in range(num_tiles):
            sub_index = rng.choice(len(proportions), p=proportions)
            difficulty = rng.uniform(*tc.difficulty_range)
            sub_cfg = sub_cfgs[sub_index]
            boxes = TERRAIN_LAYOUT_FNS[sub_cfg.function](difficulty, sub_cfg, _tile_rng(tc.seed, difficulty))
            sx, sy = sub_cfg.size
            arr = np.array(
                [[cx - 0.5 * sx, cy - 0.5 * sy, yaw, length, width] for cx, cy, yaw, length, width, _h in boxes]
            )
            tables.append(arr)
            difficulties.append(difficulty)
        counts = np.array([len(a) for a in tables])
        table = np.zeros((num_tiles, int(counts.max()), 5))
        for k, arr in enumerate(tables):
            table[k, : len(arr)] = arr
        self._obstacle_table = torch.tensor(table, dtype=torch.float32, device=self.device)
        self._obstacle_counts = torch.tensor(counts, dtype=torch.long, device=self.device)
        # env -> tile: tile (row, col) spans [row*sx, (row+1)*sx] x [col*sy, (col+1)*sy];
        # origins sit at tile centers and the full grid is centered on (0, 0)
        size_x, size_y = tc.size
        origins = self._terrain.env_origins
        row = ((origins[:, 0] + 0.5 * tc.num_rows * size_x) / size_x - 0.5).round().long()
        col = ((origins[:, 1] + 0.5 * tc.num_cols * size_y) / size_y - 0.5).round().long()
        self._env_tile = row * tc.num_cols + col
        # cold-cache cross-check: on fresh generation the terrain functions
        # register their layouts keyed by the exact difficulty Isaac passed;
        # a wrong replay would register difficulties the replay never drew.
        # NOTE direction: with use_cache, warm tiles SKIP the layout function
        # (mesh loaded from cache), so their difficulties are legitimately
        # absent from the registry — checking "every replayed difficulty is
        # registered" false-alarms on mixed warm/cold grids (16-tile campaign
        # runs reuse the 4 cached 2x2-era tiles). Check the subset direction
        # instead: everything registered THIS process must match the replay.
        if TERRAIN_LAYOUT_REGISTRY:
            replayed = set(difficulties)
            stale = [d for d in TERRAIN_LAYOUT_REGISTRY if d not in replayed]
            if stale:
                raise RuntimeError(
                    f"obstacle-table difficulty replay mismatch: {len(stale)} registered "
                    "layout(s) not among the replayed difficulties — Isaac's RNG draw "
                    "order changed?"
                )
            n_fresh = sum(1 for d in difficulties if d in TERRAIN_LAYOUT_REGISTRY)
            print(
                f"[nav] obstacle table OK (cold cache, replay cross-checked): {num_tiles} tiles "
                f"({n_fresh} fresh, {num_tiles - n_fresh} from mesh cache), "
                f"obstacles/tile {counts.min()}-{counts.max()}"
            )
        else:
            print(
                f"[nav] obstacle table built (warm cache): {num_tiles} tiles, "
                f"obstacles/tile {counts.min()}-{counts.max()}"
            )

    # ------------------------------------------------- run10 geodesic shaping
    def _build_occupancy_grid(self):
        """run10: boolean occupancy grid (T, gx, gy) of every tile, obstacles
        inflated by ``geo_inflate``. Cell (i, j) center sits at
        ((i+0.5)*res - 0.5*sx, (j+0.5)*res - 0.5*sy) in the tile-center frame.
        """
        tc = self.cfg.terrain.terrain_generator
        sx, sy = tc.size
        res = self.cfg.geo_res
        gx = int(round(sx / res))
        gy = int(round(sy / res))
        self._geo_gx, self._geo_gy = gx, gy
        self._geo_size = (float(sx), float(sy))
        cx = (torch.arange(gx, device=self.device) + 0.5) * res - 0.5 * sx
        cy = (torch.arange(gy, device=self.device) + 0.5) * res - 0.5 * sy
        gy_m, gx_m = torch.meshgrid(cy, cx, indexing="ij")  # (gy, gx)
        cells = torch.stack([gx_m.reshape(-1), gy_m.reshape(-1)], dim=-1)  # (C, 2)
        walls = self._obstacle_table  # (T, W, 5)
        n_w = walls.shape[1]
        valid = torch.arange(n_w, device=self.device).unsqueeze(0) < self._obstacle_counts.unsqueeze(1)
        cos_y, sin_y = torch.cos(walls[..., 2]), torch.sin(walls[..., 2])
        pad = self.cfg.geo_inflate
        occ = torch.zeros(walls.shape[0], gy * gx, dtype=torch.bool, device=self.device)
        for w in range(n_w):
            rx = cells[:, 0].unsqueeze(0) - walls[:, w, 0].unsqueeze(1)  # (T, C)
            ry = cells[:, 1].unsqueeze(0) - walls[:, w, 1].unsqueeze(1)
            lx = cos_y[:, w].unsqueeze(1) * rx + sin_y[:, w].unsqueeze(1) * ry
            ly = -sin_y[:, w].unsqueeze(1) * rx + cos_y[:, w].unsqueeze(1) * ry
            inside = (
                (lx.abs() <= 0.5 * walls[:, w, 3].unsqueeze(1) + pad)
                & (ly.abs() <= 0.5 * walls[:, w, 4].unsqueeze(1) + pad)
                & valid[:, w].unsqueeze(1)
            )
            occ |= inside
        self._geo_occ = occ.reshape(walls.shape[0], gy, gx)
        print(f"[nav] geodesic grid: {walls.shape[0]} tiles x {gy}x{gx} cells "
              f"(res {res} m, inflate {pad} m)")

    def _cell_idx(self, p_tile: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        sx, sy = self._geo_size
        res = self.cfg.geo_res
        ix = torch.clamp(((p_tile[:, 0] + 0.5 * sx) / res).long(), 0, self._geo_gx - 1)
        iy = torch.clamp(((p_tile[:, 1] + 0.5 * sy) / res).long(), 0, self._geo_gy - 1)
        return ix, iy

    def _update_geo_fields(self, env_ids: Sequence[int], spawn_xy: torch.Tensor):
        """run10: per-env geodesic distance field from the new goal (Bellman
        relaxation on the tile grid), plus the lookup at the spawn point."""
        env_ids = torch.as_tensor(env_ids, device=self.device, dtype=torch.long)
        n = env_ids.shape[0]
        if n == 0:
            return
        tiles = self._env_tile[env_ids]
        occ = self._geo_occ[tiles]  # (n, gy, gx)
        origin = self._terrain.env_origins[env_ids, :2]
        ix, iy = self._cell_idx(self._goal_pos_w[env_ids, :2] - origin)
        res = self.cfg.geo_res
        dist = torch.full((n, self._geo_gy, self._geo_gx), math.inf, device=self.device)
        dist[torch.arange(n, device=self.device), iy, ix] = 0.0
        diag = res * math.sqrt(2.0)
        for _ in range(self.cfg.geo_iters):
            d = dist
            nd = d.clone()
            nd[:, :-1, :] = torch.minimum(nd[:, :-1, :], d[:, 1:, :] + res)
            nd[:, 1:, :] = torch.minimum(nd[:, 1:, :], d[:, :-1, :] + res)
            nd[:, :, :-1] = torch.minimum(nd[:, :, :-1], d[:, :, 1:] + res)
            nd[:, :, 1:] = torch.minimum(nd[:, :, 1:], d[:, :, :-1] + res)
            nd[:, :-1, :-1] = torch.minimum(nd[:, :-1, :-1], d[:, 1:, 1:] + diag)
            nd[:, :-1, 1:] = torch.minimum(nd[:, :-1, 1:], d[:, 1:, :-1] + diag)
            nd[:, 1:, :-1] = torch.minimum(nd[:, 1:, :-1], d[:, :-1, 1:] + diag)
            nd[:, 1:, 1:] = torch.minimum(nd[:, 1:, 1:], d[:, :-1, :-1] + diag)
            nd[occ] = math.inf
            if bool(torch.equal(nd, d)):
                break
            dist = nd
        # fill cells that stayed inf (inside inflated obstacles) from their
        # free neighbours so lookups near walls are always finite. ONLY inf
        # cells may receive filled values: an unmasked zero-cost dilation
        # (run10/11 bug) also overwrote free cells whose neighbour was lower,
        # flattening the field to 0 within ~4 cells of the goal and corrupting
        # both the shaping reward and any waypoint extracted from the field.
        for _ in range(8):
            d = dist
            nd = d.clone()
            nd[:, :-1, :] = torch.minimum(nd[:, :-1, :], d[:, 1:, :])
            nd[:, 1:, :] = torch.minimum(nd[:, 1:, :], d[:, :-1, :])
            nd[:, :, :-1] = torch.minimum(nd[:, :, :-1], d[:, :, 1:])
            nd[:, :, 1:] = torch.minimum(nd[:, :, 1:], d[:, :, :-1])
            dist = torch.where(torch.isfinite(d), d, nd)
        self._geo_field[env_ids] = dist
        self._geo_prev[env_ids] = self._geo_lookup(env_ids, spawn_xy)
        self._geo_accum[env_ids] = 0.0

    def _geo_lookup(self, env_ids: torch.Tensor, xy_world: torch.Tensor) -> torch.Tensor:
        """run10: geodesic distance-to-goal at the given world positions."""
        env_ids = torch.as_tensor(env_ids, device=self.device, dtype=torch.long)
        p = xy_world - self._terrain.env_origins[env_ids, :2]
        ix, iy = self._cell_idx(p)
        d = self._geo_field[env_ids, iy, ix]
        big = (self._geo_gx + self._geo_gy) * self.cfg.geo_res
        return torch.minimum(d, torch.full_like(d, big))

    def _geo_waypoint(self, xy_world: torch.Tensor) -> torch.Tensor:
        """run12: next waypoint ~waypoint_lookahead m ahead along the geodesic
        descent path to the goal. Vectorized greedy descent on the per-env
        field; stops at the lookahead distance or at the goal cell.
        run15 fix: descent is OCCUPANCY-MASKED and 4-connected (run12 version
        walked the raw field with 8-neighbour moves, which leaks through walls
        because the fill sweeps copy finite field values into wall cells;
        measured 40% of waypoints pointed through walls at block_prob=1.0),
        and the returned waypoint is chord-checked: the farthest chain point
        whose straight segment from the robot crosses no occupied cell (the
        same construction the validated GeodesicExpert chases; masking alone
        still let the chord cut staircase corners 20% of the time).
        Returns (N, 3): waypoint in robot frame (same normalization as the goal
        bearing) + remaining geodesic distance at the robot."""
        n = xy_world.shape[0]
        ar = torch.arange(n, device=self.device)
        origin = self._terrain.env_origins[:n, :2]
        ix0, iy0 = self._cell_idx(xy_world - origin)
        res = self.cfg.geo_res
        sx, sy = self._geo_size
        moves = torch.tensor([[-1, 0], [1, 0], [0, -1], [0, 1]], device=self.device)
        occ = self._geo_occ[self._env_tile[:n]]  # (N, gy, gx), static per env
        ix, iy = ix0.clone(), iy0.clone()
        acc = torch.zeros(n, device=self.device)
        done = self._geo_field[ar, iy, ix] <= 1e-3
        ix_list, iy_list = [ix.clone()], [iy.clone()]
        max_steps = int(math.ceil(self.cfg.waypoint_lookahead / res)) + 4
        for _ in range(max_steps):
            if bool(done.all()):
                break
            nx = torch.clamp(ix.unsqueeze(1) + moves[:, 0], 0, self._geo_gx - 1)  # (N, 4)
            ny = torch.clamp(iy.unsqueeze(1) + moves[:, 1], 0, self._geo_gy - 1)
            vals = self._geo_field[ar.unsqueeze(1), ny, nx]  # (N, 4)
            # never descend into an inflated wall cell (field leaks through walls)
            vals = vals.masked_fill(occ[ar.unsqueeze(1), ny, nx], float("inf"))
            done = done | torch.isinf(vals).all(dim=-1)  # dead end: keep last cell
            best = torch.argmin(vals, dim=-1)
            ix = torch.where(done, ix, nx[ar, best])
            iy = torch.where(done, iy, ny[ar, best])
            acc = acc + torch.where(done, torch.zeros_like(acc), torch.full_like(acc, res))
            done = done | (acc >= self.cfg.waypoint_lookahead) | (vals[ar, best] <= 1e-3)
            ix_list.append(ix.clone())
            iy_list.append(iy.clone())
        # chain polyline in world frame
        ndx = torch.stack(ix_list, dim=1).float() * res - 0.5 * sx + 0.5 * res
        ndy = torch.stack(iy_list, dim=1).float() * res - 0.5 * sy + 0.5 * res
        nodes = torch.stack([ndx, ndy], dim=-1) + origin.unsqueeze(1)  # (N, M, 2)
        M = nodes.shape[1]
        if M < 2:
            wp_world = nodes[:, 0]
        else:
            # chord-checked pure pursuit: farthest sample with a clear chord
            seg_len = (nodes[:, 1:] - nodes[:, :-1]).norm(dim=-1)
            cum = torch.cat([torch.zeros(n, 1, device=self.device),
                             seg_len.cumsum(dim=1)], dim=1)
            s_max = torch.minimum((nodes[:, 0] - xy_world).norm(dim=-1, keepdim=True)
                                  + self.cfg.waypoint_lookahead, cum[:, -1:])
            S = 24
            s_grid = torch.linspace(0.0, 1.0, S, device=self.device).view(1, S) * s_max
            kk = torch.clamp((cum.unsqueeze(1) < s_grid.unsqueeze(2)).sum(dim=2) - 1,
                             0, M - 2)
            s0 = cum.gather(1, kk)
            s1 = cum.gather(1, kk + 1)
            ff = torch.clamp((s_grid - s0) / torch.clamp(s1 - s0, min=1e-4), 0.0, 1.0)
            pk = nodes.gather(1, kk.unsqueeze(-1).expand(-1, -1, 2))
            pk1 = nodes.gather(1, (kk + 1).unsqueeze(-1).expand(-1, -1, 2))
            pts = pk + ff.unsqueeze(-1) * (pk1 - pk)  # (N, S, 2)
            fracs = torch.linspace(0.1, 1.0, 10, device=self.device)
            rel_c = (pts - xy_world.unsqueeze(1)).unsqueeze(2)
            pp = xy_world.view(n, 1, 1, 2) + fracs.view(1, 1, -1, 1) * rel_c
            ixt, iyt = self._cell_idx((pp - origin.view(n, 1, 1, 2)).reshape(-1, 2))
            ob = occ[ar.repeat_interleave(S * fracs.shape[0]), iyt, ixt]
            ok = ~ob.reshape(n, S, fracs.shape[0]).any(dim=-1)
            iS = torch.arange(S, device=self.device).unsqueeze(0)
            sel = torch.where(ok, iS, torch.zeros_like(iS)).amax(dim=1)
            wp_world = pts[ar, sel]
        q = self._robot.data.root_quat_w.torch  # (N, 4), xyzw convention
        yaw = torch.atan2(2.0 * (q[:, 2] * q[:, 3] + q[:, 0] * q[:, 1]), 1.0 - 2.0 * (q[:, 1] ** 2 + q[:, 2] ** 2))
        rel = wp_world - xy_world
        cos_y, sin_y = torch.cos(yaw), torch.sin(yaw)
        gx = cos_y * rel[:, 0] + sin_y * rel[:, 1]
        gy = -sin_y * rel[:, 0] + cos_y * rel[:, 1]
        norm = 0.5 * (self.cfg.goal_min_radius + self.cfg.goal_max_radius)
        d_geo = self._geo_field[ar, iy0, ix0]
        return torch.stack([gx / norm, gy / norm, d_geo / norm], dim=-1)
