"""Convert the openmover URDF to a USD asset for Isaac Lab (one-off).

Outputs: openmover_ws/isaac/assets/openmover_lab/robot_description/...

Usage (Isaac Lab 3.0, headless by default):
    cd ~/isaaclab && ./isaaclab.sh -p openmover_ws/isaac/sim/20_convert_openmover_urdf.py

Facts baked in (from the product URDF, src/openmover/urdf/robot_description.urdf):
- diff-drive: wheel_left/right_joint, y=±0.162 m (track 0.324 m), wheel radius 0.050353 m
- 4 passive caster-ball links (continuous joints, unactuated)
- 2 fixed LiDAR mounts at x=±0.22015, z=0.07513 (merged into base_link here;
  the Isaac Lab ray-cast sensors are attached with the same offsets at env level)
"""

import argparse

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description="openmover URDF -> USD for Isaac Lab")
AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()
app_launcher = AppLauncher(args_cli)

from isaaclab.sim.converters import UrdfConverter, UrdfConverterCfg  # noqa: E402

WS = "/home/zar/Documents/phd/robot/openmover_ws"
URDF_PATH = f"{WS}/src/openmover/urdf/robot_description.urdf"
USD_DIR = f"{WS}/isaac/assets/openmover_lab"

cfg = UrdfConverterCfg(
    asset_path=URDF_PATH,
    usd_dir=USD_DIR,
    force_usd_conversion=True,
    fix_base=False,
    merge_fixed_joints=True,  # LiDAR links merge into base_link (sensors added at env level)
    robot_type="Wheeled",
    collision_type="Convex Hull",
    # velocity-controlled drives: for target_type="velocity" the importer zeroes
    # damping and `stiffness` acts as the velocity gain Kv (Nm per rad/s slip)
    joint_drive=UrdfConverterCfg.JointDriveCfg(
        drive_type="force",
        target_type="velocity",
        gains=UrdfConverterCfg.JointDriveCfg.PDGainsCfg(stiffness=2.0, damping=0.0),
    ),
    ros_package_paths=[{"name": "openmover", "path": f"{WS}/src/openmover"}],
)

converter = UrdfConverter(cfg)
print(f"[convert] USD written to: {converter.usd_path}")
