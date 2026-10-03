"""Koopman data pipeline v0 — chassis-dynamics transition collector (concept arm).

Paper-1 status of the Koopman core is CONCEPT: the program's claim is
"freeze the structure, adapt the interface", and the Koopman lifting is one
candidate mechanism for the dynamics part of that claim (docs/research/
02_nmte_framework.md: methods are candidates, not commitments). This script is
the DATA side of the pipeline: it records (s_t, u_t, s_{t+1}) transitions of
the robot's chassis dynamics in physical units, from any registered openmover
task, so a lifted-linear (EDMD-style) dynamics model can be fit OFFLINE
without a simulator (30_koopman_fit.py).

State s = [vx_b, wz_b, wl, wr]:
    vx_b, wz_b  body-frame chassis twist          [m/s, rad/s]
    wl, wr      realized wheel joint speeds       [rad/s]
Keeping actuator-side and body-side speeds in the SAME state vector is what
lets a lifted model see wheel slip (degraded regime: body lags wheels).

Input u = [a_l, a_r]: the raw commanded actions in [-1, 1] (the applied
wheel-speed target is u * wheel_max_speed; the regime's wheel_max_speed is
stored in the metadata).

Driver: piecewise-constant random commands held HOLD steps each (sysID-style
excitation — covers the full action square including full-forward cruise,
which pure random-per-step driving under-excites). Deterministic per --seed,
so source/degraded collections with the same seed are PAIRED command-wise.

Masks: transitions crossing an episode reset, leaving a collided env, or
non-finite are dropped (post-collision dynamics are contact-dominated and
must not enter the free-driving dynamics fit).

Usage:
    cd ~/isaaclab && ./isaaclab.sh -p \
        /home/zar/Documents/phd/robot/openmover_ws/isaac/lab/29_koopman_collect.py \
        --num_envs 64 --num_steps 600 \
        --out /home/zar/Documents/phd/robot/openmover_ws/isaac/lab/logs/koopman_data/source.pt
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import openmover_lab  # noqa: F401  (registers the openmover tasks)

import gymnasium as gym
import torch

import isaaclab_tasks  # noqa: F401
from isaaclab_tasks.utils import (
    add_launcher_args,
    launch_simulation,
    resolve_task_config,
    setup_preset_cli,
)

parser = argparse.ArgumentParser(description="Koopman chassis-dynamics data collector.")
parser.add_argument("--disable_fabric", action="store_true", default=False)
parser.add_argument("--num_envs", type=int, default=64)
parser.add_argument("--num_steps", type=int, default=600)
parser.add_argument("--task", type=str, default="Isaac-Nav-Openmover-v0")
parser.add_argument("--hold", type=int, default=10,
                    help="control steps each random command is held")
parser.add_argument("--out", type=str,
                    default="logs/koopman_data/source.pt")
parser.add_argument("--seed", type=int, default=42)
add_launcher_args(parser)
args_cli, hydra_args = setup_preset_cli(parser)
sys.argv = [sys.argv[0]] + hydra_args

# Physical-plausibility gate. Free driving on this chassis is bounded by the
# wheel-speed cap (10 rad/s -> ~0.5 m/s, ~3.1 rad/s pivot); the first
# collision impulse step can still pass the _penalized mask and launches the
# body far beyond that (observed: vx up to 39 m/s). Those steps are
# contact-dominated and must not enter a free-driving dynamics fit.
VX_LIM, WZ_LIM, W_LIM = 3.0, 12.0, 25.0


def _body_state(wrapped):
    """s = [vx_b, wz_b, wl, wr] in physical units (N, 4)."""
    vx = wrapped._robot.data.root_lin_vel_b.torch[:, 0]
    wz = wrapped._robot.data.root_ang_vel_b.torch[:, 2]
    w = wrapped._robot.data.joint_vel.torch[:, wrapped._wheel_idx]  # (N, 2)
    return torch.stack([vx, wz, w[:, 0], w[:, 1]], dim=1)


def main():
    torch.manual_seed(args_cli.seed)
    env_cfg, _ = resolve_task_config(args_cli.task, "")

    with launch_simulation(env_cfg, args_cli):
        env_cfg.scene.num_envs = args_cli.num_envs
        env_cfg.sim.device = args_cli.device if args_cli.device is not None else env_cfg.sim.device
        if args_cli.disable_fabric:
            env_cfg.sim.use_fabric = False
        env_cfg.seed = args_cli.seed

        env = gym.make(args_cli.task, cfg=env_cfg)
        wrapped = env.unwrapped
        n = wrapped.num_envs
        dev = wrapped.device
        print(f"[koopman] task={args_cli.task} num_envs={n} steps={args_cli.num_steps} "
              f"hold={args_cli.hold} dt={wrapped.step_dt:.4f} s")

        obs, _ = env.reset()
        # deterministic paired command schedule: re-seed a private generator
        # so source/degraded runs with the same --seed see identical commands
        gen = torch.Generator(device=dev).manual_seed(1000 + args_cli.seed)
        act = 2.0 * torch.rand(n, 2, generator=gen, device=dev) - 1.0

        s_buf, u_buf, sn_buf = [], [], []
        prev_s = _body_state(wrapped)
        prev_clean = torch.ones(n, dtype=torch.bool, device=dev)
        t0 = time.time()
        for i in range(args_cli.num_steps):
            with torch.inference_mode():
                if i % args_cli.hold == 0 and i > 0:
                    act = 2.0 * torch.rand(n, 2, generator=gen, device=dev) - 1.0
                obs, rew, term, trunc, info = env.step(act)
                step_dones = term | trunc
                s_next = _body_state(wrapped)
                # a transition is usable if BOTH endpoints are clean: same episode,
                # no collision accumulated, all values finite, and physically
                # plausible (first collision-impulse step can spike the body
                # speed far beyond the chassis cap before _penalized latches)
                finite_next = torch.isfinite(s_next).all(dim=1)
                plausible = (
                    (s_next[:, 0].abs() < VX_LIM)
                    & (s_next[:, 1].abs() < WZ_LIM)
                    & (s_next[:, 2:].abs().max(dim=1).values < W_LIM)
                )
                clean = ~wrapped._penalized & finite_next & plausible
                usable = prev_clean & clean & ~step_dones
                s_buf.append(prev_s[usable].cpu())
                u_buf.append(act[usable].cpu())
                sn_buf.append(s_next[usable].cpu())
                prev_s = s_next
                prev_clean = clean & ~step_dones
                if (i + 1) % 100 == 0:
                    kept = sum(b.shape[0] for b in s_buf)
                    print(f"[koopman] step {i + 1}/{args_cli.num_steps} "
                          f"kept={kept} ({100.0 * kept / ((i + 1) * n):.1f}%)")

        s_all = torch.cat(s_buf, dim=0)
        u_all = torch.cat(u_buf, dim=0)
        sn_all = torch.cat(sn_buf, dim=0)
        out = Path(args_cli.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        torch.save({
            "s": s_all, "u": u_all, "s_next": sn_all,
            "dt": float(wrapped.step_dt),
            "task": args_cli.task,
            "wheel_max_speed": float(wrapped.cfg.wheel_max_speed),
            "wheel_radius": float(wrapped.cfg.wheel_radius),
            "seed": args_cli.seed,
            "hold": args_cli.hold,
            "state_fields": ["vx_b_mps", "wz_b_radps", "wl_radps", "wr_radps"],
            "action_fields": ["a_l", "a_r"],
        }, out)
        dt = time.time() - t0
        print(f"[koopman] saved {s_all.shape[0]} transitions "
              f"({100.0 * s_all.shape[0] / (args_cli.num_steps * n):.1f}% of steps) "
              f"in {dt:.1f} s -> {out} ({out.stat().st_size / 1e6:.1f} MB)")
        print(f"[koopman] s range: vx [{s_all[:, 0].min():.3f}, {s_all[:, 0].max():.3f}] m/s, "
              f"wz [{s_all[:, 1].min():.3f}, {s_all[:, 1].max():.3f}] rad/s, "
              f"wheels [{s_all[:, 2:].min():.3f}, {s_all[:, 2:].max():.3f}] rad/s")
        env.close()


if __name__ == "__main__":
    main()
