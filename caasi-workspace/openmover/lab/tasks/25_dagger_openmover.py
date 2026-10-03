"""DAgger for the openmover nav policy (run14).

run13 showed a one-shot BC clone is weak in closed loop (0.10-0.16 blocked
success vs the expert's 0.64: compounding error on states the clone itself
visits) and that PPO then erodes even that. DAgger attacks the cloning gap:
each round the CURRENT policy drives, the expert labels every state the
policy visits, the labels are aggregated into the dataset, and the actor is
re-cloned from scratch on the aggregate. No RL in the loop, so there is
nothing to erode the behavior.

Round r:
  1. roll out current actor for --rollout_steps (256 envs); env steps with the
     ACTOR action while the expert computes its label at the same state;
  2. aggregate (obs, expert_act) into the dataset (starts from run13's demos);
  3. re-clone a fresh actor on the aggregate;
  4. eval the new actor for --eval_steps (blocked-goal success).

Outputs: per-round dataset logs/bc_demos/dagger/roundR.pt, final synthesized
rsl_rl checkpoint logs/rsl_rl/openmover_nav/dagger_init/model_0.pt.

Usage:
    cd openmover_ws/isaac/lab && ~/isaaclab/isaaclab.sh -p \
        25_dagger_openmover.py --num_envs 256 --rounds 4 --headless
"""

import argparse
import copy
import itertools
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import openmover_lab  # noqa: F401  (registers Isaac-Nav-Openmover-v0)
from openmover_lab.geodesic_expert import GeodesicExpert

import gymnasium as gym
import torch
import yaml
from tensordict import TensorDict

from rsl_rl.models import MLPModel

import isaaclab_tasks  # noqa: F401
from isaaclab_tasks.utils import (
    add_launcher_args,
    launch_simulation,
    resolve_task_config,
    setup_preset_cli,
)

parser = argparse.ArgumentParser(description="DAgger cloning for run14.")
parser.add_argument("--num_envs", type=int, default=256)
parser.add_argument("--rounds", type=int, default=4)
parser.add_argument("--rollout_steps", type=int, default=400)
parser.add_argument("--eval_steps", type=int, default=300)
parser.add_argument("--task", type=str, default="Isaac-Nav-Openmover-v0")
parser.add_argument("--fixed_block_prob", type=float, default=1.0)
parser.add_argument("--seed", type=int, default=42)
parser.add_argument("--epochs", type=int, default=8)
parser.add_argument("--batch", type=int, default=4096)
parser.add_argument("--lr", type=float, default=3e-4)
parser.add_argument("--agent_yaml", type=str,
                    default="logs/rsl_rl/openmover_nav/2026-09-03_21-36-57_run12/params/agent.yaml")
parser.add_argument("--init_ckpt", type=str,
                    default="logs/rsl_rl/openmover_nav/bc_init/model_0.pt")
parser.add_argument("--init_demos", nargs="+",
                    default=["logs/bc_demos/demos_p100.pt", "logs/bc_demos/demos_p0.pt"])
parser.add_argument("--out_dir", type=str, default="logs/bc_demos/dagger")
parser.add_argument("--out_ckpt", type=str,
                    default="logs/rsl_rl/openmover_nav/dagger_init/model_0.pt")
add_launcher_args(parser)
args_cli, hydra_args = setup_preset_cli(parser)
sys.argv = [sys.argv[0]] + hydra_args


def build_actor(agent, obs_dim, act_dim):
    obs_td = TensorDict({"policy": torch.zeros(2, obs_dim)}, batch_size=[2])
    return MLPModel(
        obs_td, agent["obs_groups"], "actor", output_dim=act_dim,
        **{k: copy.deepcopy(v) for k, v in agent["actor"].items() if k != "class_name"},
    )


def train_actor(actor, obs, act, epochs, batch, lr, tag):
    n = obs.shape[0]
    opt = torch.optim.Adam(actor.parameters(), lr=lr)
    loss_fn = torch.nn.MSELoss()
    for ep in range(epochs):
        perm = torch.randperm(n)
        tot, cnt = 0.0, 0
        for b0 in range(0, n, batch):
            idx = perm[b0:b0 + batch]
            td = TensorDict({"policy": obs[idx]}, batch_size=[idx.shape[0]])
            pred = actor(td, stochastic_output=False)
            loss = loss_fn(pred, act[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += loss.item() * idx.shape[0]
            cnt += idx.shape[0]
    with torch.inference_mode():
        td = TensorDict({"policy": obs[:8192]}, batch_size=[min(8192, n)])
        err = (actor(td, stochastic_output=False) - act[:8192]).abs().mean(dim=0)
    print(f"[dagger] {tag}: {n} demos, final loss={tot / cnt:.5f}, "
          f"val mae=({err[0]:.3f}, {err[1]:.3f})")


def main():
    torch.manual_seed(args_cli.seed)
    env_cfg, _ = resolve_task_config(args_cli.task, "")
    with launch_simulation(env_cfg, args_cli):
        env_cfg.scene.num_envs = args_cli.num_envs
        env_cfg.sim.device = args_cli.device if args_cli.device is not None else env_cfg.sim.device
        env_cfg.seed = args_cli.seed
        env_cfg.curriculum_fixed_block_prob = args_cli.fixed_block_prob
        env = gym.make(args_cli.task, cfg=env_cfg)
        wrapped = env.unwrapped
        dev = wrapped.device
        n_env = wrapped.num_envs
        print(f"[dagger] num_envs={n_env} rounds={args_cli.rounds} "
              f"rollout={args_cli.rollout_steps} eval={args_cli.eval_steps}")

        # initial dataset + actor
        obs = torch.cat([torch.load(p, weights_only=True)["obs"] for p in args_cli.init_demos], dim=0)
        act = torch.cat([torch.load(p, weights_only=True)["act"] for p in args_cli.init_demos], dim=0)
        with open(args_cli.agent_yaml) as f:
            agent = yaml.safe_load(f)
        actor = build_actor(agent, obs.shape[1], act.shape[1])
        actor.load_state_dict(torch.load(args_cli.init_ckpt, weights_only=True)["actor_state_dict"])
        actor.to(dev).train()
        print(f"[dagger] seed dataset {obs.shape[0]} pairs; actor loaded from {args_cli.init_ckpt}")

        out_dir = Path(args_cli.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        def roll_metrics(info, acc, n_reset):
            log = info.get("log", {})
            if n_reset > 0 and "Metrics/success_rate" in log:
                acc[0] += log["Metrics/success_rate"] * n_reset
                acc[1] += log.get("Metrics/collision_rate", 0.0) * n_reset
                acc[2] += n_reset
                nb = log.get("Metrics/num_blocked_episodes", 0.0)
                bsr = log.get("Metrics/blocked_success_rate", float("nan"))
                if nb > 0 and bsr == bsr:
                    acc[3] += bsr * nb
                    acc[4] += nb

        def eval_policy(steps, tag):
            obs_e, _ = env.reset()
            acc = [0.0, 0.0, 0, 0.0, 0.0]
            # no_grad (not inference_mode): env buffers must stay updatable
            # outside this block (auto-resets write into them)
            with torch.no_grad():
                for _ in range(steps):
                    p_obs = obs_e["policy"] if isinstance(obs_e, dict) else obs_e
                    a = actor(TensorDict({"policy": p_obs}, batch_size=[p_obs.shape[0]]),
                              stochastic_output=False)
                    obs_e, _, term, trunc, info = env.step(a)
                    roll_metrics(info, acc, int((term | trunc).sum().item()))
            n = max(acc[2], 1)
            bs = acc[3] / acc[4] if acc[4] > 0 else float("nan")
            print(f"[dagger] {tag}: episodes={acc[2]} success={acc[0] / n:.3f} "
                  f"collision={acc[1] / n:.3f} blocked_eps={acc[4]:.0f} blocked_success={bs:.3f}")
            return bs

        expert = GeodesicExpert(wrapped)
        obs_all, act_all = obs, act
        obs_r, _ = env.reset()
        expert.episode_reset(torch.arange(n_env))
        t0 = time.time()
        for r in range(args_cli.rounds):
            actor.eval()
            buf_o, buf_a = [], []
            acc = [0.0, 0.0, 0, 0.0, 0.0]
            # no_grad (not inference_mode): env buffers must stay updatable
            # outside this block (eval resets write into them)
            with torch.no_grad():
                for i in range(args_cli.rollout_steps):
                    p_obs = obs_r["policy"] if isinstance(obs_r, dict) else obs_r
                    a_pol = actor(TensorDict({"policy": p_obs}, batch_size=[p_obs.shape[0]]),
                                  stochastic_output=False)
                    a_exp = expert.action()  # label at the policy-visited state
                    buf_o.append(p_obs.detach().cpu())
                    buf_a.append(a_exp.detach().cpu())
                    obs_r, _, term, trunc, info = env.step(a_pol)
                    dones = term | trunc
                    ids = dones.nonzero().squeeze(-1)
                    if ids.numel() > 0:
                        expert.episode_reset(ids)
                    roll_metrics(info, acc, int(dones.sum().item()))
            n = max(acc[2], 1)
            bs = acc[3] / acc[4] if acc[4] > 0 else float("nan")
            print(f"[dagger] round {r} rollout: episodes={acc[2]} "
                  f"success={acc[0] / n:.3f} blocked_eps={acc[4]:.0f} blocked_success={bs:.3f}")
            obs_all = torch.cat([obs_all, torch.cat(buf_o, dim=0)], dim=0)
            act_all = torch.cat([act_all, torch.cat(buf_a, dim=0)], dim=0)
            torch.save({"obs": torch.cat(buf_o, dim=0), "act": torch.cat(buf_a, dim=0)},
                       out_dir / f"round{r}.pt")
            # re-clone from scratch on the aggregate (CPU), then back to device
            torch.manual_seed(args_cli.seed + r + 1)
            actor = build_actor(agent, obs_all.shape[1], act_all.shape[1])
            actor.train()
            train_actor(actor, obs_all, act_all, args_cli.epochs, args_cli.batch,
                        args_cli.lr, f"round {r} reclone")
            actor.to(dev)
            eval_policy(args_cli.eval_steps, f"round {r} eval")

        # final artifact: synthesized rsl_rl checkpoint for downstream runs
        critic = MLPModel(
            TensorDict({"policy": torch.zeros(2, obs_all.shape[1])}, batch_size=[2]),
            agent["obs_groups"], "critic", output_dim=1,
            **{k: copy.deepcopy(v) for k, v in agent["critic"].items() if k != "class_name"},
        )
        fresh_opt = torch.optim.Adam(
            itertools.chain(actor.parameters(), critic.parameters()), lr=args_cli.lr
        )
        ckpt = Path(args_cli.out_ckpt)
        ckpt.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "actor_state_dict": actor.state_dict(),
                "critic_state_dict": critic.state_dict(),
                "optimizer_state_dict": fresh_opt.state_dict(),
                "iter": 0,
                "infos": None,
            },
            ckpt,
        )
        print(f"[dagger] wrote {ckpt}; total demos {obs_all.shape[0]}; "
              f"elapsed {(time.time() - t0) / 60:.1f} min")
        env.close()


if __name__ == "__main__":
    main()
