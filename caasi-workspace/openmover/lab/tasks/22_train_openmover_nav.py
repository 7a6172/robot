"""PPO training wrapper for Isaac-Nav-Openmover-v0 (RSL-RL).

External tasks are not auto-imported by the stock trainer (it only sees
`isaaclab_tasks`), so this wrapper registers `openmover_lab` first, then
delegates to Isaac Lab's unified RL trainer. The trainer honors
`--max_iterations`, so runs stay bounded.

Logs land in ./logs/rsl_rl/openmover_nav/<timestamp>[_<run_name>]/
(tensorboard + params/*.yaml + model_<iter>.pt checkpoints).

Usage:
    cd openmover_ws/isaac/lab && ~/isaaclab/isaaclab.sh -p 22_train_openmover_nav.py \
        --rl_library rsl_rl --task Isaac-Nav-Openmover-v0 \
        --num_envs 256 --max_iterations 300 --run_name run1
"""

import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import openmover_lab  # noqa: F401  (registers Isaac-Nav-Openmover-v0)

TRAIN_SCRIPT = Path.home() / "isaaclab" / "scripts" / "reinforcement_learning" / "train.py"

if __name__ == "__main__":
    # train.py imports its sibling module `common`
    sys.path.insert(0, str(TRAIN_SCRIPT.parent))
    runpy.run_path(str(TRAIN_SCRIPT), run_name="__main__")
