"""Step 1.1 — pioneer3dx URDF → USD (run once, reuse forever).

Imports the expanded pioneer3dx URDF (xacro output, kept faithful — no edits)
via isaacsim.asset.importer.urdf, resolving package://warehouse_simulation
mesh paths against the ROS workspace source.

Import choices (see docs/research/04_isaac_sim_strategy.md Phase 1):
- merge_fixed_joints=False  → keep every frame (laser, imu, sonars) for
  sensor placement and TF parity
- collision_from_visuals=False → use the URDF's explicit collisions
  (box chassis, cylinder wheels) — correct wheel contact
- fix_base=False            → floating base (free robot)
- wheel joints get velocity targets (diff-drive), all others no drive

Run: ~/isaacsim/python.sh openmover_ws/isaac/scripts/10_import_urdf.py
"""

import os
import time

from common import ASSETS_DIR, preflight

URDF_PATH = os.path.join(ASSETS_DIR, "pioneer3dx", "pioneer3dx.urdf")
USD_DIR = os.path.join(ASSETS_DIR, "pioneer3dx")
WS_SRC = "/home/zar/Documents/phd/robot/openmover_ws/src"

preflight("import_urdf")

assert os.path.isfile(URDF_PATH), f"missing {URDF_PATH} (run xacro first)"

T0 = time.time()
print("[import] launching SimulationApp (headless)...", flush=True)
from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({"headless": True})
print(f"[import] app up in {time.time() - T0:.1f} s", flush=True)

from isaacsim.asset.importer.urdf import URDFImporter, URDFImporterConfig  # noqa: E402

config = URDFImporterConfig(
    urdf_path=URDF_PATH,
    usd_path=USD_DIR,
    merge_fixed_joints=False,
    merge_mesh=False,
    collision_from_visuals=False,
    collision_type="Convex Hull",
    allow_self_collision=False,
    ros_package_paths=[{"warehouse_simulation":
                        os.path.join(WS_SRC, "warehouse_simulation")}],
    fix_base=False,
    joint_drive_type="force",
    joint_target_type={
        "base_left_wheel_joint": "velocity",
        "base_right_wheel_joint": "velocity",
        ".*": "none",
    },
)

T1 = time.time()
importer = URDFImporter(config)
result = importer.import_urdf()
print(f"[import] done in {time.time() - T1:.1f} s → {result}", flush=True)

simulation_app.close()
print(f"[import] OK — total {time.time() - T0:.1f} s", flush=True)
