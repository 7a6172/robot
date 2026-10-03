"""openmover tasks for Isaac Lab (direct RL).

Registered here so that `import openmover_lab` makes the tasks available to
gym.make / the Isaac Lab runner scripts.
"""

import gymnasium as gym

gym.register(
    id="Isaac-Nav-Openmover-v0",
    entry_point="openmover_lab.openmover_nav_env:OpenmoverNavEnv",
    disable_env_checker=True,
    kwargs={
        "env_cfg_entry_point": "openmover_lab.openmover_nav_cfg:OpenmoverNavEnvCfg",
        "rsl_rl_cfg_entry_point": "openmover_lab.rsl_rl_ppo_cfg:OpenmoverNavPPORunnerCfg",
    },
)

# Target worlds of the transfer study (same env class, different worlds):
#   -RailYard-v0  : yard geometry, nominal dynamics      (Target 1)
#   -Degraded-v0  : maze geometry, degraded dynamics     (Target 2)
#   -Combined-v0  : yard geometry AND degraded dynamics  (Target 3)
for _task, _cfg in (
    ("Isaac-Nav-Openmover-RailYard-v0", "openmover_lab.openmover_nav_cfg:OpenmoverNavRailYardEnvCfg"),
    ("Isaac-Nav-Openmover-Degraded-v0", "openmover_lab.openmover_nav_cfg:OpenmoverNavDegradedEnvCfg"),
    ("Isaac-Nav-Openmover-Combined-v0", "openmover_lab.openmover_nav_cfg:OpenmoverNavCombinedEnvCfg"),
):
    gym.register(
        id=_task,
        entry_point="openmover_lab.openmover_nav_env:OpenmoverNavEnv",
        disable_env_checker=True,
        kwargs={
            "env_cfg_entry_point": _cfg,
            "rsl_rl_cfg_entry_point": "openmover_lab.rsl_rl_ppo_cfg:OpenmoverNavPPORunnerCfg",
        },
    )
