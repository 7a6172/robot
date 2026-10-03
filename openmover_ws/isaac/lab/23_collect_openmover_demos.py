"""Collect expert demonstrations for behavior cloning (run13).

run12 showed the policy never discovers the detour motor program from reward
or waypoint information alone, so run13 injects it: an expert controller
follows the geodesic descent chain of the env's distance field and
(policy-obs, expert-action) pairs are recorded for BC.

Expert (validated in /tmp/dbg_expert.py, seed 42, 12 blocked-goal episodes):
  - geodesic descent chain walked downhill from the robot cell with an
    OCCUPANCY mask (the field leaks through walls via fill sweeps, so the
    chain must never enter an inflated wall cell) + dead-end detection;
  - chord-checked pure pursuit along the chain polyline: chase the farthest
    lookahead sample whose straight chord from the robot is occupancy-clear,
    so corners are never cut through walls;
  - close-and-clear goal homing; speed = cos(heading) x lidar-clearance x
    geodesic taper; PD heading control with low-pass smoothing;
  - back-up-on-contact unstuck state machine.

Only pre-collision steps of each episode are recorded (post-collision
behavior must not be imitated). Episode metrics are printed so the expert
itself can be validated (blocked-goal success + video) before BC.

Usage:
    cd openmover_ws/isaac/lab && ~/isaaclab/isaaclab.sh -p \
        23_collect_openmover_demos.py --num_envs 256 --num_steps 800 \
        --fixed_block_prob 1.0 --out logs/bc_demos/demos_p100.pt
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import openmover_lab  # noqa: F401  (registers Isaac-Nav-Openmover-v0)
from openmover_lab.geodesic_expert import GeodesicExpert

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

parser = argparse.ArgumentParser(description="Expert demo collection for BC.")
parser.add_argument("--disable_fabric", action="store_true", default=False)
parser.add_argument("--num_envs", type=int, default=256)
parser.add_argument("--num_steps", type=int, default=800)
parser.add_argument("--task", type=str, default="Isaac-Nav-Openmover-v0")
parser.add_argument("--fixed_block_prob", type=float, default=1.0,
                    help="pin the goal-blocking fraction (1.0 = all blocked)")
parser.add_argument("--out", type=str, default="logs/bc_demos/demos.pt")
parser.add_argument("--seed", type=int, default=42)
parser.add_argument("--video", action="store_true", default=False,
                    help="record an mp4 of the expert (num_envs=1 recommended)")
parser.add_argument("--video_length", type=int, default=300)
add_launcher_args(parser)
args_cli, hydra_args = setup_preset_cli(parser)
sys.argv = [sys.argv[0]] + hydra_args
if args_cli.video:
    args_cli.enable_cameras = True

def main():
    torch.manual_seed(args_cli.seed)
    env_cfg, _ = resolve_task_config(args_cli.task, "")

    with launch_simulation(env_cfg, args_cli):
        env_cfg.scene.num_envs = args_cli.num_envs
        env_cfg.sim.device = args_cli.device if args_cli.device is not None else env_cfg.sim.device
        if args_cli.disable_fabric:
            env_cfg.sim.use_fabric = False
        env_cfg.seed = args_cli.seed
        env_cfg.curriculum_fixed_block_prob = args_cli.fixed_block_prob
        print(f"[nav] goal-blocking fraction pinned to {args_cli.fixed_block_prob}")

        render_mode = None
        if args_cli.video:
            render_mode = "rgb_array"
            env_cfg.terrain.max_init_terrain_level = 0
            env_cfg.terrain.visual_material = sim_utils.PreviewSurfaceCfg(
                diffuse_color=(0.45, 0.45, 0.45)
            )
            tg = env_cfg.terrain.terrain_generator
            tile_x = 0.5 * tg.size[0] - 0.5 * tg.num_rows * tg.size[0]
            tile_y = 0.5 * tg.size[1] - 0.5 * tg.num_cols * tg.size[1]
            env_cfg.viewer.eye = (tile_x, tile_y - 7.0, 9.0)
            env_cfg.viewer.lookat = (tile_x, tile_y, 0.0)

        env = gym.make(args_cli.task, cfg=env_cfg, render_mode=render_mode)
        if args_cli.video:
            video_dir = Path(__file__).resolve().parent / "videos" / args_cli.task
            env = gym.wrappers.RecordVideo(
                env, video_folder=str(video_dir),
                step_trigger=lambda step: step == 0,
                video_length=args_cli.video_length, fps=20,
                disable_logger=True,
            )
        wrapped = env.unwrapped
        print(f"[nav] collecting demos: num_envs={wrapped.num_envs} "
              f"steps={args_cli.num_steps} device={wrapped.device}")

        obs, _ = env.reset()
        expert = GeodesicExpert(wrapped)
        succ_sum = coll_sum = 0.0
        resets = 0
        blk_succ_sum = n_blocked = 0.0
        obs_buf, act_buf, mask_buf = [], [], []
        t0 = time.time()
        for i in range(args_cli.num_steps):
            with torch.inference_mode():
                policy_obs = obs["policy"] if isinstance(obs, dict) else obs
                act = expert.action()
                # record only pre-collision, finite-state steps of each episode
                valid = ~wrapped._penalized & ~wrapped._bad_state
                obs_buf.append(policy_obs.detach().cpu())
                act_buf.append(act.detach().cpu())
                mask_buf.append(valid.detach().cpu())
                obs, rew, term, trunc, info = env.step(act)
                step_dones = term | trunc
                done_ids = step_dones.nonzero().squeeze(-1)
                if done_ids.numel() > 0:
                    expert.episode_reset(done_ids)
                log = info.get("log", {})
                n_reset = int(step_dones.sum().item())
                if n_reset > 0 and "Metrics/success_rate" in log:
                    succ_sum += log["Metrics/success_rate"] * n_reset
                    coll_sum += log.get("Metrics/collision_rate", 0.0) * n_reset
                    resets += n_reset
                    nb = log.get("Metrics/num_blocked_episodes", 0.0)
                    bsr = log.get("Metrics/blocked_success_rate", float("nan"))
                    if nb > 0 and bsr == bsr:
                        blk_succ_sum += bsr * nb
                        n_blocked += nb
                if (i + 1) % 200 == 0:
                    print(f"[nav] step {i + 1}/{args_cli.num_steps} "
                          f"({(i + 1) * wrapped.num_envs / (time.time() - t0):.0f} env-steps/s)")

        obs_all = torch.cat(obs_buf, dim=0)
        act_all = torch.cat(act_buf, dim=0)
        mask_all = torch.cat(mask_buf, dim=0)
        obs_all = obs_all[mask_all]
        act_all = act_all[mask_all]
        out = Path(args_cli.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"obs": obs_all, "act": act_all}, out)
        dt = time.time() - t0
        print(f"[nav] collected {obs_all.shape[0]} valid (obs, act) pairs "
              f"of {args_cli.num_steps * wrapped.num_envs} steps "
              f"({100.0 * obs_all.shape[0] / (args_cli.num_steps * wrapped.num_envs):.1f}%)")
        print(f"[nav] saved to {out} ({out.stat().st_size / 1e6:.0f} MB)")
        n = max(resets, 1)
        print(f"[nav] EXPERT episodes={resets}, success={succ_sum / n:.3f}, "
              f"collision={coll_sum / n:.3f}")
        if n_blocked > 0:
            print(f"[nav] EXPERT blocked episodes={n_blocked:.0f} "
                  f"({100.0 * n_blocked / resets:.1f}%), "
                  f"blocked success={blk_succ_sum / n_blocked:.3f}")
        env.close()


if __name__ == "__main__":
    main()
