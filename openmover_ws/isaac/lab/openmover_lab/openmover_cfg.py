"""openmover articulation config for Isaac Lab.

Built from the product URDF (src/openmover/urdf/robot_description.urdf),
converted once by isaac/sim/20_convert_openmover_urdf.py:
- diff-drive: wheel_left/right_joint at y=±0.162 m (track 0.324 m),
  wheel radius 0.050353 m, axis (0,1,0)
- 4 passive caster-ball links (continuous joints, unactuated)
- 2 LiDAR mounts (x=±0.22015, z=0.07513) merged into base_link; the
  ray-cast LiDAR sensors are attached at env level with the same offsets
"""

import isaaclab.sim as sim_utils
from isaaclab.actuators import ImplicitActuatorCfg
from isaaclab.assets import ArticulationCfg

OPENMOVER_USD = (
    "/home/zar/Documents/phd/robot/openmover_ws/isaac/assets/"
    "openmover_lab/robot_description/robot_description.usda"
)

OPENMOVER_CFG = ArticulationCfg(
    spawn=sim_utils.UsdFileCfg(
        usd_path=OPENMOVER_USD,
        activate_contact_sensors=True,
    ),
    actuators={
        # velocity drive: effort = Kv * (target_vel - joint_vel), so the gain
        # lives in `damping` and stiffness must be 0 (else the wheels become a
        # position spring toward q=0 and ignore velocity targets)
        "wheel_drives": ImplicitActuatorCfg(
            joint_names_expr=["wheel_.*_joint"],
            stiffness=0.0,
            damping=2.0,
            effort_limit_sim=5.0,
        ),
        # passive casters: no drive effort
        "caster_balls": ImplicitActuatorCfg(
            joint_names_expr=["ball_.*_joint"],
            stiffness=0.0,
            damping=0.0,
            effort_limit_sim=0.1,
        ),
    },
)
