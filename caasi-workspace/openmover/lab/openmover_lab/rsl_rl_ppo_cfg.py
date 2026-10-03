"""RSL-RL PPO agent config for Isaac-Nav-Openmover-v0.

First-run settings: small MLP on raw scans (already normalized), adaptive LR.
"""

from isaaclab.utils.configclass import configclass
from isaaclab_rl.rsl_rl import RslRlMLPModelCfg, RslRlOnPolicyRunnerCfg, RslRlPpoAlgorithmCfg


@configclass
class OpenmoverNavPPORunnerCfg(RslRlOnPolicyRunnerCfg):
    num_steps_per_env = 24  # 24 env steps @ 20 Hz = 1.2 s rollout horizon
    max_iterations = 300
    save_interval = 50
    experiment_name = "openmover_nav"
    clip_actions = 1.0  # actions are wheel-speed fractions in [-1, 1]
    # rsl_rl maps role -> list of env observation group names
    obs_groups = {"actor": ["policy"], "critic": ["policy"]}

    actor = RslRlMLPModelCfg(
        hidden_dims=[128, 128],
        activation="elu",
        obs_normalization=False,  # obs already scaled: scans [0,1], goal ~[-2,2], vel ~O(1)
        distribution_cfg=RslRlMLPModelCfg.GaussianDistributionCfg(init_std=1.0),
    )
    critic = RslRlMLPModelCfg(
        hidden_dims=[128, 128],
        activation="elu",
        obs_normalization=False,
    )
    algorithm = RslRlPpoAlgorithmCfg(
        value_loss_coef=1.0,
        use_clipped_value_loss=True,
        clip_param=0.2,
        entropy_coef=0.005,
        num_learning_epochs=5,
        num_mini_batches=4,
        learning_rate=3.0e-4,
        schedule="adaptive",
        gamma=0.99,
        lam=0.95,
        desired_kl=0.01,
        max_grad_norm=1.0,
    )
