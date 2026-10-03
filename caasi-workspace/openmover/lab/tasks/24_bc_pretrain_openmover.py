"""Behavior-cloning pretrain for run13 (no simulator needed).

Trains a fresh rsl_rl MLPModel actor (architecture taken verbatim from a
training run's params/agent.yaml, so state-dict keys match exactly) to imitate
the expert demos collected by 23_collect_openmover_demos.py, then synthesizes
an rsl_rl OnPolicyRunner checkpoint (actor = BC weights, critic = fresh,
optimizer = fresh Adam, iter = 0) that train.py can --resume from.

Usage:
    cd openmover_ws/isaac/lab && ~/isaaclab/isaaclab.sh -p \
        24_bc_pretrain_openmover.py \
        --demos logs/bc_demos/demos_p100.pt logs/bc_demos/demos_p0.pt \
        --agent_yaml logs/rsl_rl/openmover_nav/<run12_dir>/params/agent.yaml \
        --out logs/rsl_rl/openmover_nav/bc_init/model_0.pt
"""

import argparse
import copy
import itertools

import torch
import yaml
from tensordict import TensorDict

from rsl_rl.models import MLPModel

parser = argparse.ArgumentParser(description="BC pretrain of the rsl_rl actor.")
parser.add_argument("--demos", nargs="+", required=True,
                    help="demo .pt files from 23_collect_openmover_demos.py")
parser.add_argument("--agent_yaml", type=str, required=True,
                    help="params/agent.yaml of the run whose architecture to clone")
parser.add_argument("--out", type=str,
                    default="logs/rsl_rl/openmover_nav/bc_init/model_0.pt")
parser.add_argument("--epochs", type=int, default=15)
parser.add_argument("--batch", type=int, default=4096)
parser.add_argument("--lr", type=float, default=3e-4)
parser.add_argument("--seed", type=int, default=42)
parser.add_argument("--max_demos", type=int, default=None,
                    help="adaptation-budget knob: keep only this many (obs,act) pairs, "
                         "sampled with the fixed --seed RNG so budget points are nested-"
                         "comparable across runs")
args = parser.parse_args()

torch.manual_seed(args.seed)

obs = torch.cat([torch.load(p, weights_only=True)["obs"] for p in args.demos], dim=0)
act = torch.cat([torch.load(p, weights_only=True)["act"] for p in args.demos], dim=0)
if args.max_demos is not None and args.max_demos < obs.shape[0]:
    idx = torch.randperm(obs.shape[0])[:args.max_demos]
    obs, act = obs[idx], act[idx]
    print(f"[bc] budget capped to {args.max_demos} demos (seed {args.seed})")
n, obs_dim = obs.shape
print(f"[bc] {n} demos, obs dim {obs_dim}, act dim {act.shape[1]}")

with open(args.agent_yaml) as f:
    agent = yaml.safe_load(f)

obs_td = TensorDict({"policy": torch.zeros(2, obs_dim)}, batch_size=[2])
actor = MLPModel(
    obs_td, agent["obs_groups"], "actor", output_dim=act.shape[1],
    **{k: copy.deepcopy(v) for k, v in agent["actor"].items() if k != "class_name"},
)
critic = MLPModel(
    obs_td, agent["obs_groups"], "critic", output_dim=1,
    **{k: copy.deepcopy(v) for k, v in agent["critic"].items() if k != "class_name"},
)
print(f"[bc] actor params={sum(p.numel() for p in actor.parameters())}, "
      f"critic params={sum(p.numel() for p in critic.parameters())}")

opt = torch.optim.Adam(actor.parameters(), lr=args.lr)
loss_fn = torch.nn.MSELoss()
perm0 = torch.randperm(n)
for ep in range(args.epochs):
    tot, cnt = 0.0, 0
    for b0 in range(0, n, args.batch):
        idx = perm0[b0:b0 + args.batch]
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
        err = (actor(td, stochastic_output=False) - act[:8192]).abs()
    print(f"[bc] epoch {ep + 1}/{args.epochs}: loss={tot / cnt:.5f} "
          f"val mae=({err.mean(dim=0)[0]:.3f}, {err.mean(dim=0)[1]:.3f})")

# synthesize a runner checkpoint: BC actor + fresh critic + fresh optimizer.
# PPO builds ONE Adam group over chain(actor, critic) params, so mirror that;
# a pre-step state_dict has empty state but matching param groups.
fresh_opt = torch.optim.Adam(
    itertools.chain(actor.parameters(), critic.parameters()), lr=args.lr
)
import os

os.makedirs(os.path.dirname(args.out), exist_ok=True)
torch.save(
    {
        "actor_state_dict": actor.state_dict(),
        "critic_state_dict": critic.state_dict(),
        "optimizer_state_dict": fresh_opt.state_dict(),
        "iter": 0,
        "infos": None,
    },
    args.out,
)
print(f"[bc] wrote {args.out}")
