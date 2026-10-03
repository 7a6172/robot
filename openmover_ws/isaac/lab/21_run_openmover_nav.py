"""Bounded runner for the openmover LiDAR point-goal navigation task.

Zero/random actions or a trained RSL-RL checkpoint, capped step count,
headless by default. Used for smoke tests, the parallel-env scaling study,
and per-world evaluation of trained policies (see docs/isaac).

Usage:
    cd ~/isaaclab && ./isaaclab.sh -p \\
        /home/zar/Documents/phd/robot/openmover_ws/isaac/lab/21_run_openmover_nav.py \\
        --num_envs 64 --num_steps 200 --policy random

    # evaluate a trained checkpoint on a target world:
    cd ~/isaaclab && ./isaaclab.sh -p \\
        .../21_run_openmover_nav.py --task Isaac-Nav-Openmover-RailYard-v0 \\
        --policy trained --checkpoint logs/rsl_rl/openmover_nav/<run>/model_1500.pt
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import openmover_lab  # noqa: F401  (registers Isaac-Nav-Openmover-v0)
from openmover_lab.openmover_terrains import custom_map_terrains_cfg, load_custom_map

import gymnasium as gym
import torch

import isaaclab.sim as sim_utils
import isaaclab_tasks  # noqa: F401
from isaaclab_tasks.utils import (
    add_launcher_args,
    launch_simulation,
    resolve_task_config,
    setup_preset_cli,
)

parser = argparse.ArgumentParser(description="Bounded openmover navigation runner.")
parser.add_argument("--disable_fabric", action="store_true", default=False)
parser.add_argument("--num_envs", type=int, default=16)
parser.add_argument("--num_steps", type=int, default=100)
parser.add_argument("--task", type=str, default="Isaac-Nav-Openmover-v0")
parser.add_argument("--policy", type=str, default="zero",
                    choices=["zero", "random", "forward", "trained", "expert",
                             "astar_dwa"])
parser.add_argument("--checkpoint", type=str, default=None,
                    help="RSL-RL model_*.pt path (required for --policy trained)")
parser.add_argument("--seed", type=int, default=42)
parser.add_argument("--video", action="store_true", default=False,
                    help="Record an mp4 (needs --num_steps ~= --video_length)")
parser.add_argument("--video_length", type=int, default=300)
parser.add_argument("--video_view", type=str, default="bird", choices=["bird", "chase"])
parser.add_argument("--tag", type=str, default="",
                    help="provenance tag (e.g. arm name) appended to the trace "
                         "filename so multi-arm video runs don't overwrite each other")
parser.add_argument("--debug_dones", action="store_true", default=False,
                    help="print per-50-step termination/reach/timeout counts")
parser.add_argument("--fixed_block_prob", type=float, default=None,
                    help="pin the goal-blocking fraction (task v2); eval protocol "
                         "uses 1.0; default = env curriculum")
parser.add_argument("--map_file", type=str, default=None,
                    help="custom map JSON (27_make_custom_map.py): swaps the terrain "
                         "for this map and fixes spawn+goal from it")
parser.add_argument("--dob_lite", action="store_true", default=False,
                    help="deploy-time velocity DOB shim on the trained policy "
                         "(degraded-dynamics A/B); implies clip_actions=None")
parser.add_argument("--cbf_lite", action="store_true", default=False,
                    help="deploy-time LiDAR safety filter (CBF-lite) on the trained "
                         "policy; clamps forward speed to the stoppable envelope")
parser.add_argument("--const_boost", type=float, default=1.0,
                    help="open-loop control arm: multiply policy actions by this "
                         "constant before the env (1.0 = off); implies clip_actions=None")
parser.add_argument("--shield", action="store_true", default=False,
                    help="deploy-time shield shim (policy_node v7.4 exact-box ESDF "
                         "barrier port) as final authority on the commanded action; "
                         "requires --map_file; works with --policy trained (learned + "
                         "guarantee) and --policy astar_dwa (planner + guarantee)")
parser.add_argument("--episode_cap", type=float, default=160.0,
                    help="upper bound [s] on the path-length-derived episode horizon "
                         "for custom maps (campaign runs: 190)")
parser.add_argument("--results_json", type=str, default=None,
                    help="write per-env FIRST-episode outcomes (reached/penalized/ttg/"
                         "yaw0) to this JSON path; enables cfg.log_per_env so seeds "
                         "folded into num_envs can be split back out (33_run_campaign)")
add_launcher_args(parser)
args_cli, hydra_args = setup_preset_cli(parser)
sys.argv = [sys.argv[0]] + hydra_args
if args_cli.video:
    args_cli.enable_cameras = True


class VideoMarkers:
    """Visual-only START/GOAL discs so recordings are readable (no collision,
    presentation only — never touches physics or observations)."""

    def __init__(self):
        self._stage = None
        try:
            goal_cfg = sim_utils.CylinderCfg(
                radius=0.18, height=0.06,
                visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.0, 0.85, 0.1)),
            )
            spawn_cfg = sim_utils.CylinderCfg(
                radius=0.24, height=0.02,
                visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.05, 0.3, 0.9)),
            )
            goal_cfg.func("/World/GoalMarker", goal_cfg, translation=(0.0, 0.0, -10.0))
            spawn_cfg.func("/World/SpawnMarker", spawn_cfg, translation=(0.0, 0.0, -10.0))
            import omni.usd
            self._stage = omni.usd.get_context().get_stage()
        except Exception as e:  # presentation-only; never kill the run
            print(f"[nav] marker setup failed (continuing without): {e}")
            self._stage = None

    def place(self, goal_xy, spawn_xy):
        if self._stage is None:
            return
        try:
            from pxr import Gf
            for path, xy, z in (("/World/GoalMarker", goal_xy, 0.03),
                                ("/World/SpawnMarker", spawn_xy, 0.012)):
                prim = self._stage.GetPrimAtPath(path)
                attr = prim.GetAttribute("xformOp:translate")
                if attr:
                    attr.Set(Gf.Vec3d(float(xy[0]), float(xy[1]), z))
        except Exception as e:
            print(f"[nav] marker place failed (continuing without): {e}")


def main():
    torch.manual_seed(args_cli.seed)
    if args_cli.policy == "trained" and not args_cli.checkpoint:
        raise ValueError("--policy trained requires --checkpoint <model_*.pt>")
    if args_cli.policy == "astar_dwa" and not args_cli.map_file:
        raise ValueError("--policy astar_dwa requires --map_file (A* plans on the "
                         "map's occupancy grid, DWA rejects on its exact boxes)")

    env_cfg, _ = resolve_task_config(args_cli.task, "")
    if args_cli.results_json:
        # per-env outcome arrays in extras["log"] (first-episode capture below)
        env_cfg.log_per_env = True

    map_stem = None
    if args_cli.map_file:
        spec = load_custom_map(args_cli.map_file)  # fail early on a bad spec
        env_cfg.terrain.terrain_generator = custom_map_terrains_cfg(
            str(Path(args_cli.map_file).resolve()),
            num_tiles=args_cli.num_envs)  # one tile per env (fixed spawn)
        env_cfg.use_map_spawn_goal = True
        map_stem = Path(args_cli.map_file).stem
        print(f"[nav] custom map '{map_stem}': {len(spec['boxes'])} wall boxes, "
              f"spawn={spec['spawn']} goal={spec['goal']}")
        # long maps need a longer episode horizon. Measured expert effective
        # speed is ~0.31-0.36 m/s on straight legs (V_CRUISE 0.5 degraded by
        # cornering) but drops toward ~0.25 m/s on switchback-heavy maps with
        # backup-unstick cycles, so budget 0.25 m/s + a fixed turn margin.
        # History: pl/0.45+5 truncated slalom (needs ~58 s, had 50 s);
        # pl/0.30+10 capped at 120 s still truncated slow serpentine envs
        # (fastest 105 s, slowest >120 s). Episodes auto-reset exactly at the
        # horizon, which reads as 0% success with the robot back at spawn.
        pl = float(spec.get("path_len", 0.0))
        need = pl / 0.25 + 10.0
        if need > env_cfg.episode_length_s:
            env_cfg.episode_length_s = min(need, args_cli.episode_cap)
            print(f"[nav] episode horizon extended to {env_cfg.episode_length_s:.0f} s "
                  f"(map path {pl:.1f} m)")
        # The geodesic field is Bellman-relaxed for geo_iters sweeps, ~1 cell
        # of progress per sweep along the free path. The default (72) covers the
        # source-task tile (~15 m / 0.25 m = ~60 cells) but NOT long custom maps:
        # serpentine's ~32 m path is ~128 cells, so with 72 sweeps the spawn cell
        # stayed inf (finite frac 0.795) and the expert's descent chain dead-ended
        # at step 0 (robot spun in place the whole episode). Scale the sweep count
        # with path length so the field actually converges; floor at the default.
        need_iters = int(pl / env_cfg.geo_res) + 40
        if need_iters > env_cfg.geo_iters:
            env_cfg.geo_iters = need_iters
            print(f"[nav] geo_iters raised to {env_cfg.geo_iters} for converged field "
                  f"(map path {pl:.1f} m)")

    with launch_simulation(env_cfg, args_cli):
        env_cfg.scene.num_envs = args_cli.num_envs
        env_cfg.sim.device = args_cli.device if args_cli.device is not None else env_cfg.sim.device
        if args_cli.disable_fabric:
            env_cfg.sim.use_fabric = False

        render_mode = None
        env_cfg.seed = args_cli.seed
        if args_cli.fixed_block_prob is not None:
            env_cfg.curriculum_fixed_block_prob = args_cli.fixed_block_prob
            print(f"[nav] goal-blocking fraction pinned to {args_cli.fixed_block_prob}")
        if args_cli.video:
            render_mode = "rgb_array"
            # The video recorder captures a FIXED Kit camera in absolute world
            # coordinates (viewer origin_type/asset_name are ignored), so we
            # pin env 0 to terrain tile (0, 0) and aim the camera at that
            # tile's world position. Tiles are centered on the world origin:
            # tile (0, 0) sits at (0.5 - 0.5*num_rows) * size per axis.
            env_cfg.terrain.max_init_terrain_level = 0
            # default terrain visual material is pure black diffuse; use a
            # visible gray so walls/floor show up in the recording
            env_cfg.terrain.visual_material = sim_utils.PreviewSurfaceCfg(
                diffuse_color=(0.45, 0.45, 0.45)
            )
            tg = env_cfg.terrain.terrain_generator
            tile_x = 0.5 * tg.size[0] - 0.5 * tg.num_rows * tg.size[0]
            tile_y = 0.5 * tg.size[1] - 0.5 * tg.num_cols * tg.size[1]
            if args_cli.video_view == "chase":
                env_cfg.viewer.eye = (tile_x - 2.5, tile_y + 1.8, 1.5)
                env_cfg.viewer.lookat = (tile_x, tile_y, 0.3)
            else:
                env_cfg.viewer.eye = (tile_x, tile_y - 7.0, 9.0)
                env_cfg.viewer.lookat = (tile_x, tile_y, 0.0)
            print(f"[nav] video camera aimed at tile(0,0) = ({tile_x}, {tile_y})")

        env = gym.make(args_cli.task, cfg=env_cfg, render_mode=render_mode)
        if args_cli.video:
            video_dir = Path(__file__).resolve().parent / "videos" / args_cli.task
            env = gym.wrappers.RecordVideo(
                env, video_folder=str(video_dir),
                step_trigger=lambda step: step == 0,
                video_length=args_cli.video_length, fps=20,
                disable_logger=True,
            )
            print(f"[nav] recording video to {video_dir}")
            markers = VideoMarkers()
            trace, ep_goal, ep_spawn, ep_start = [], [], [], []
            wp_trace, lidar_trace = [], []
            prev_frame, prev_wp, prev_lidar = None, None, None
        wrapped = env.unwrapped
        print(f"[nav] obs space: {env.observation_space}")
        print(f"[nav] act space: {env.action_space}")
        print(f"[nav] num_envs={wrapped.num_envs} device={wrapped.device}")

        # optionally load a trained RSL-RL checkpoint for rollout
        inference_policy = None
        env_wrapped = None
        dob = None
        cbf = None
        shield = None
        manual_clip = None
        if args_cli.policy == "trained":
            import importlib.metadata as metadata

            from rsl_rl.runners import OnPolicyRunner

            from isaaclab_rl.rsl_rl import RslRlVecEnvWrapper, handle_deprecated_rsl_rl_cfg
            from isaaclab_tasks.utils.parse_cfg import load_cfg_from_registry

            agent_cfg = load_cfg_from_registry(args_cli.task, "rsl_rl_cfg_entry_point")
            # same cfg migration the stock train/play scripts apply (rsl_rl >= 5:
            # legacy 'stochastic' field must move into distribution_cfg)
            agent_cfg = handle_deprecated_rsl_rl_cfg(agent_cfg, metadata.version("rsl-rl-lib"))
            clip = agent_cfg.clip_actions
            manual_clip = None
            if args_cli.dob_lite or args_cli.const_boost != 1.0 or args_cli.shield:
                # reproduce the frozen deployment EXACTLY (policy output clipped the
                # same way the wrapper would), then let the interface command beyond
                # the clip; so the wrapper itself must not clip
                manual_clip = clip
                clip = None
            env_wrapped = RslRlVecEnvWrapper(env, clip_actions=clip)
            runner = OnPolicyRunner(env_wrapped, agent_cfg.to_dict(), log_dir=None,
                                    device=wrapped.device)
            runner.load(args_cli.checkpoint)
            inference_policy = runner.get_inference_policy(device=wrapped.device)
            print(f"[nav] loaded checkpoint: {args_cli.checkpoint}")
            if args_cli.dob_lite:
                from openmover_lab.dob_lite import DobLite
                from openmover_lab.openmover_nav_cfg import OpenmoverNavEnvCfg
                # configclass strips class-level attrs; instantiate to read the
                # NOMINAL actuator constant regardless of the task variant
                nominal_w = float(OpenmoverNavEnvCfg().wheel_max_speed)
                dob = DobLite(wrapped, nominal_wheel_max=nominal_w)
                print(f"[nav] DOB-lite enabled (nominal wheel_max_speed="
                      f"{nominal_w}, g in [{dob.g_min}, {dob.g_max}])")
            if args_cli.cbf_lite:
                from openmover_lab.cbf_lite import CbfLite
                from openmover_lab.openmover_nav_cfg import OpenmoverNavEnvCfg
                _n = OpenmoverNavEnvCfg()
                v_full = float(_n.wheel_radius) * float(_n.wheel_max_speed)
                cbf = CbfLite(wrapped, v_full=v_full)
                print(f"[nav] CBF-lite enabled (v_full={v_full:.3f} m/s, "
                      f"d_margin={cbf.d_margin} m, a_dec={cbf.a_dec} m/s^2)")
        obs, _ = env.reset()
        yaw0 = None
        first_ep = {}  # env_id -> first-episode outcome (--results_json)
        if args_cli.results_json:
            # initial heading per env = the seed axis on fixed custom maps
            # (spawn xy + goal come from the spec; yaw is random per episode).
            # root_quat_w is xyzw (env convention).
            q = wrapped._robot.data.root_quat_w.torch
            yaw0 = torch.atan2(2.0 * (q[:, 2] * q[:, 3] + q[:, 0] * q[:, 1]),
                               1.0 - 2.0 * (q[:, 1] ** 2 + q[:, 2] ** 2)).cpu().tolist()
        expert = None
        baseline = None
        if args_cli.policy == "expert":
            from openmover_lab.geodesic_expert import GeodesicExpert
            expert = GeodesicExpert(wrapped)
            print("[nav] using in-engine geodesic expert policy")
        if args_cli.policy == "astar_dwa":
            from openmover_lab.astar_dwa import AstarDwa
            from openmover_lab.openmover_nav_cfg import OpenmoverNavEnvCfg
            _n = OpenmoverNavEnvCfg()
            v_full = float(_n.wheel_radius) * float(_n.wheel_max_speed)
            baseline = AstarDwa(wrapped, spec, v_full=v_full)
        # shield is policy-agnostic: it filters whatever command reaches it, so
        # it wraps the trained policy (--policy trained --shield) AND the
        # classical planner (--policy astar_dwa --shield, the paper's thesis arm:
        # planner competence + shield guarantee). Constructed after env.reset()
        # because both it and the baseline read robot state lazily in action().
        if args_cli.shield:
            if not args_cli.map_file:
                raise ValueError(
                    "--shield requires --map_file: the barrier is built from "
                    "the map spec's exact box geometry")
            from openmover_lab.shield_lite import ShieldLite
            from openmover_lab.openmover_nav_cfg import OpenmoverNavEnvCfg
            _n = OpenmoverNavEnvCfg()
            v_full = float(_n.wheel_radius) * float(_n.wheel_max_speed)
            shield = ShieldLite(wrapped, spec, v_full=v_full)
            print(f"[nav] Shield-lite enabled (policy_node v7.4 port; "
                  f"v_full={v_full:.3f} m/s, w_full={shield.w_full:.3f} rad/s, "
                  f"{len(spec['boxes'])} boxes, policy={args_cli.policy})")
        start_xy = wrapped._robot.data.root_pos_w.torch[0, :2].clone()
        if args_cli.video:
            markers.place(wrapped._goal_pos_w[0, :2], start_xy)
            ep_goal.append(wrapped._goal_pos_w[0, :2].cpu().numpy().copy())
            ep_spawn.append(start_xy.cpu().numpy().copy())
            ep_start.append(0)

        succ_sum = 0.0
        coll_sum = 0.0
        resets = 0
        ttg_sum = 0.0  # time-to-goal, weighted by successes per batch
        n_success = 0.0
        blk_succ_sum = 0.0  # blocked-goal successes (weighted)
        n_blocked = 0.0
        dbg_term = dbg_trunc = 0
        t0 = time.time()
        obs_t = env_wrapped.get_observations() if inference_policy is not None else None
        for i in range(args_cli.num_steps):
            with torch.inference_mode():
                if inference_policy is not None:
                    actions = inference_policy(obs_t)
                    if manual_clip is not None:
                        actions = torch.clamp(actions, -manual_clip, manual_clip)
                    if dob is not None:
                        actions = dob.action(actions)
                    if args_cli.const_boost != 1.0:
                        actions = actions * args_cli.const_boost
                    if cbf is not None:
                        actions = cbf.action(actions)
                    if shield is not None:
                        actions = shield.action(actions)
                    obs_t, _, dones, infos = env_wrapped.step(actions)
                    if dob is not None:
                        dob.reset(dones)
                    if shield is not None:
                        shield.reset(dones)
                    inference_policy.reset(dones)
                    log = infos.get("log", {})
                    step_dones = dones
                else:
                    if args_cli.policy == "random":
                        actions = 2.0 * torch.rand(wrapped.num_envs, 2, device=wrapped.device) - 1.0
                    elif args_cli.policy == "forward":
                        actions = torch.ones(wrapped.num_envs, 2, device=wrapped.device)
                    elif args_cli.policy == "expert":
                        actions = expert.action()
                    elif args_cli.policy == "astar_dwa":
                        actions = baseline.action()
                    else:
                        actions = torch.zeros(wrapped.num_envs, 2, device=wrapped.device)
                    if shield is not None:
                        actions = shield.action(actions)
                    obs, rew, term, trunc, info = env.step(actions)
                    log = info.get("log", {})
                    step_dones = term | trunc
                    if shield is not None:
                        shield.reset(step_dones)
                    if expert is not None:
                        done_ids = step_dones.nonzero().squeeze(-1)
                        if done_ids.numel() > 0:
                            expert.episode_reset(done_ids)
                    if baseline is not None:
                        done_ids = step_dones.nonzero().squeeze(-1)
                        if done_ids.numel() > 0:
                            baseline.episode_reset(done_ids)
                    if args_cli.debug_dones:
                        dbg_term += term.sum().item()
                        dbg_trunc += trunc.sum().item()
                        if (i + 1) % 50 == 0:
                            print(f"[dbg] steps {i + 1 - 50}..{i + 1}: "
                                  f"reached={dbg_term} timeout={dbg_trunc} "
                                  f"reward mean={rew.mean():.3f} max={rew.max():.3f} min={rew.min():.3f}")
                            dbg_term = dbg_trunc = 0

                # accumulate episode metrics only on steps where resets happen,
                # weighted by batch size (extras["log"] persists across steps,
                # so summing every step over-counts the last reset batch)
                n_reset = int(step_dones.sum().item())
                if n_reset > 0 and "Metrics/success_rate" in log:
                    succ_sum += log["Metrics/success_rate"] * n_reset
                    coll_sum += log.get("Metrics/collision_rate", 0.0) * n_reset
                    resets += n_reset
                    # time-to-goal: weight the batch mean by its success count
                    ttg = log.get("Metrics/time_to_goal", float("nan"))
                    n_succ_batch = log["Metrics/success_rate"] * n_reset
                    if n_succ_batch > 0 and ttg == ttg:  # skip NaN batches
                        ttg_sum += ttg * n_succ_batch
                        n_success += n_succ_batch
                    # blocked-goal episodes (task v2): weighted by blocked count
                    nb = log.get("Metrics/num_blocked_episodes", 0.0)
                    bsr = log.get("Metrics/blocked_success_rate", float("nan"))
                    if nb > 0 and bsr == bsr:
                        blk_succ_sum += bsr * nb
                        n_blocked += nb
                    # --results_json: FIRST-episode-only outcomes per env index
                    # (a fast env auto-resets into a 2nd episode within the
                    # horizon; recording only the first keeps the batch clean).
                    # The log dict persists across steps, so re-reading the same
                    # batch is idempotent (eid already in first_ep).
                    if args_cli.results_json and "Metrics/per_env_ids" in log:
                        _ids = log["Metrics/per_env_ids"]
                        _rch = log["Metrics/per_env_reached"]
                        _pen = log["Metrics/per_env_penalized"]
                        _ttg = log["Metrics/per_env_ttg"]
                        for k, eid in enumerate(_ids):
                            eid = int(eid)
                            if eid not in first_ep:
                                first_ep[eid] = {
                                    "env": eid,
                                    "reached": bool(_rch[k]),
                                    "penalized": bool(_pen[k]),
                                    "ttg": float(_ttg[k]),
                                    "yaw0": float(yaw0[eid]) if yaw0 else None,
                                }

            if args_cli.video:
                # NOTE: after env.step() returns, env 0's pose buffer is already
                # the POST-RESET spawn if the episode ended on this step
                # (verified: |trace last point - next spawn| == 0.00). So on
                # done steps we close the old episode with the previous
                # (pre-reset) pose; the new episode's first frame is appended
                # on the next step.
                p0 = wrapped._robot.data.root_pos_w.torch[0]
                q0 = wrapped._robot.data.root_quat_w.torch[0]
                # NOT `yaw0`: that name holds the per-env INITIAL headings used
                # by --results_json (the seed axis); shadowing it here made
                # --video + --results_json crash with an IndexError on the
                # first captured episode (ledger 17.18).
                yaw_vid = torch.atan2(2.0 * (q0[2] * q0[3] + q0[0] * q0[1]),
                                      1.0 - 2.0 * (q0[1] ** 2 + q0[2] ** 2))
                # waypoint obs dims [1204:1206]: robot frame, normalized by
                # 0.5*(goal_min+goal_max); denormalize + rotate to world frame
                wp_now = (float("nan"), float("nan"))
                if wrapped.cfg.use_waypoint_obs:
                    pol_obs = obs_t["policy"] if obs_t is not None else obs["policy"]
                    o0 = pol_obs[0]
                    wp_n = 0.5 * (wrapped.cfg.goal_min_radius + wrapped.cfg.goal_max_radius)
                    wx = float(o0[1204]) * wp_n
                    wy = float(o0[1205]) * wp_n
                    c, s = float(torch.cos(yaw_vid)), float(torch.sin(yaw_vid))
                    wp_now = (float(p0[0]) + c * wx - s * wy,
                              float(p0[1]) + s * wx + c * wy)
                # world-frame lidar hit points, every 4th ray -> 150/scanner;
                # misses become NaN; the scan matches the pre-reset pose.
                # NOTE: IsaacLab reports misses as finite hits at max_distance,
                # so mask by range from the scanner origin as well.
                lf = wrapped._lidar_front.data.ray_hits_w.torch[0, ::4, :2]
                lr = wrapped._lidar_rear.data.ray_hits_w.torch[0, ::4, :2]
                lidar_now = torch.cat([lf, lr], dim=0)
                offs = torch.tensor([0.22015, -0.22015], device=lidar_now.device)
                orig = torch.stack([p0[0] + offs * torch.cos(yaw_vid),
                                    p0[1] + offs * torch.sin(yaw_vid)], dim=1)
                orig = orig.repeat_interleave(150, dim=0)
                miss = ~torch.isfinite(lidar_now).all(dim=1)
                miss |= torch.linalg.norm(lidar_now - orig, dim=1) >= 9.9
                lidar_now = lidar_now.clone()
                lidar_now[miss] = float("nan")
                frame = (float(p0[0]), float(p0[1]), float(yaw_vid))
                if bool(step_dones[0]):
                    if prev_frame is not None:
                        trace.append(prev_frame)  # terminal pose of ended episode
                        wp_trace.append(prev_wp)
                        lidar_trace.append(prev_lidar)
                    markers.place(wrapped._goal_pos_w[0, :2], p0[:2])
                    ep_goal.append(wrapped._goal_pos_w[0, :2].cpu().numpy().copy())
                    ep_spawn.append(p0[:2].cpu().numpy().copy())
                    ep_start.append(len(trace))
                else:
                    trace.append(frame)
                    wp_trace.append(wp_now)
                    lidar_trace.append(lidar_now.cpu().numpy())
                prev_frame, prev_wp = frame, wp_now
                prev_lidar = lidar_now.cpu().numpy()

        if args_cli.video:
            import numpy as np
            tag = f"_{args_cli.tag}" if args_cli.tag else ""
            trace_name = (f"trace_{map_stem}_seed{args_cli.seed}{tag}.npz"
                          if map_stem
                          else f"trace_seed{args_cli.seed}{tag}.npz")
            trace_path = video_dir / trace_name
            np.savez(
                trace_path,
                traj=np.asarray(trace, dtype=np.float32),
                wp=np.asarray(wp_trace, dtype=np.float32),        # (T, 2) world frame
                lidar=np.asarray(lidar_trace, dtype=np.float32),  # (T, 300, 2), NaN=miss
                ep_goal=np.asarray(ep_goal, dtype=np.float32),
                ep_spawn=np.asarray(ep_spawn, dtype=np.float32),
                ep_start=np.asarray(ep_start, dtype=np.int64),
                occ=wrapped._geo_occ[wrapped._env_tile[0]].cpu().numpy(),
                origin=np.asarray([tile_x, tile_y], dtype=np.float32),
                size=np.asarray(wrapped._geo_size, dtype=np.float32),
            )
            print(f"[nav] trace written to {trace_path}")

        dt = time.time() - t0
        fps = args_cli.num_steps * wrapped.num_envs / dt
        policy_obs = obs["policy"] if isinstance(obs, dict) else obs
        print(f"[nav] done: {args_cli.num_steps} steps in {dt:.2f} s "
              f"({fps:.0f} env-steps/s)")
        if dob is not None:
            print(f"[nav] DOB-lite mean disturbance gain g={dob.mean_gain():.3f} "
                  f"(1.0 = nominal, lower = more compensated thrust loss)")
        if cbf is not None:
            n_intv, n_tot = cbf.stats()
            print(f"[nav] CBF-lite interventions={n_intv}/{n_tot} env-steps "
                  f"(rate={cbf.intervention_rate():.5f})")
        if shield is not None:
            st = shield.stats()
            print(f"[nav] Shield-lite: shield={st['shield']} hyst={st['hyst']} "
                  f"escape={st['escape']} retreat={st['retreat']} "
                  f"pin={st['pin']} "
                  f"off_map={st['oob']} over {st['steps']} env-steps")
        if baseline is not None:
            st = baseline.stats()
            print(f"[nav] A*+DWA baseline: plans={st['plan']} replans={st['replan']} "
                  f"dwa_reject={st['dwa_reject']} stuck={st['stuck']} "
                  f"over {st['steps']} env-steps")
        print(f"[nav] final obs shape={tuple(policy_obs.shape)} "
              f"norm={policy_obs.float().norm().item():.4f}")
        front = policy_obs[:, :600]
        rear = policy_obs[:, 600:1200]
        print(f"[nav] scan front: min={front.min():.3f} mean={front.mean():.3f} max={front.max():.3f}")
        print(f"[nav] scan rear : min={rear.min():.3f} mean={rear.mean():.3f} max={rear.max():.3f}")
        print(f"[nav] tail (goal_xy, vx, wz) env0: {policy_obs[0, 1200:].tolist()}")
        print(f"[nav] base xy env0: {wrapped._robot.data.root_pos_w.torch[0, :2].tolist()}")
        disp = (wrapped._robot.data.root_pos_w.torch[0, :2] - start_xy).tolist()
        print(f"[nav] displacement env0 over run: [{disp[0]:.3f}, {disp[1]:.3f}] m")
        print(f"[nav] wheel joint vel env0 (L,R): "
              f"{wrapped._robot.data.joint_vel.torch[0].tolist()}")
        print(f"[nav] contact force env0: {wrapped._contact_force().tolist()}")
        n = max(resets, 1)
        print(f"[nav] episode-reset batches observed={resets}, "
              f"mean success rate={succ_sum / n:.3f}, mean collision rate={coll_sum / n:.3f}")
        if n_success > 0:
            print(f"[nav] mean time-to-goal (successes only)={ttg_sum / n_success:.2f} s "
                  f"over {n_success:.0f} successes")
        else:
            print("[nav] no successes -> time-to-goal undefined")
        if n_blocked > 0:
            print(f"[nav] blocked-goal episodes: {n_blocked:.0f} of {resets} "
                  f"({100.0 * n_blocked / resets:.1f}%), blocked success={blk_succ_sum / n_blocked:.3f}")
        else:
            print("[nav] no blocked-goal episodes observed")
        if args_cli.results_json:
            import json
            per_env = [first_ep[e] for e in sorted(first_ep)]
            n_pe = len(per_env)
            succ = sum(1 for r in per_env if r["reached"])
            coll = sum(1 for r in per_env if r["penalized"])
            ttgs = [r["ttg"] for r in per_env if r["reached"]]
            out = {
                "map": map_stem,
                "policy": args_cli.policy,
                "shield": bool(args_cli.shield),
                "seed": args_cli.seed,
                "num_envs": wrapped.num_envs,
                "num_steps": args_cli.num_steps,
                "horizon_s": float(env_cfg.episode_length_s),
                "n_first_episodes": n_pe,
                "mean_success": (succ / n_pe) if n_pe else None,
                "mean_collision": (coll / n_pe) if n_pe else None,
                "mean_ttg_success": (sum(ttgs) / len(ttgs)) if ttgs else None,
                "per_env": per_env,
            }
            if baseline is not None:
                out["baseline_stats"] = baseline.stats()
            if shield is not None:
                out["shield_stats"] = shield.stats()
            out_path = Path(args_cli.results_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w") as f:
                json.dump(out, f, indent=1)
            print(f"[nav] results_json: {n_pe}/{wrapped.num_envs} first episodes "
                  f"-> {out_path}")
        env.close()


if __name__ == "__main__":
    main()
