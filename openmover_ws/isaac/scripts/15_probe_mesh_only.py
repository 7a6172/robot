"""Regression gate: is the converted workcell mesh itself LiDAR-visible?

Loads workcell_mesh.usdc WITHOUT the baked collision boxes (only a default
ground plane so the robot can stand) and confirms the bluesea2 pair sees the
mesh walls. This is the only test that isolates the mesh: the integrated
warehouse gate also carries the boxes, whose geometry masks any mesh failure
(a 1000x scale bug in the COLLADA->USD converter went undetected there). Keep.
Guard facts: the converter must bake each COLLADA node transform (0.001 scale,
mm -> m) into the points, and sets doubleSided to dodge winding issues.

Run: ~/isaacsim/python.sh openmover_ws/isaac/scripts/15_probe_mesh_only.py
"""

import math
import os

import numpy as np

from common import ASSETS_DIR, SCENES_DIR, preflight
from lidar_mirror import MOUNTS, N_SAMPLES, collect_scan, mount_bluesea2_pair

USD_PATH = os.path.join(ASSETS_DIR, "pioneer3dx", "pioneer3dx", "pioneer3dx.usda")
WH_MESH_USD = os.path.join(SCENES_DIR, "workcell_mesh.usdc")
BASE_LINK = "/World/pioneer3dx/Geometry/base_link"
WC_X, WC_Y = -0.040107, 0.052292
WALL3_INNER_X = -9.25721 + 0.72902 / 2 + WC_X

preflight("probe_mesh_only")

from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({"headless": True, "enable_motion_bvh": True})

from isaacsim.core.api import World  # noqa: E402
from isaacsim.core.prims import Articulation, XFormPrim  # noqa: E402
from isaacsim.core.utils.stage import add_reference_to_stage  # noqa: E402
from isaacsim.sensors.experimental.rtx import (  # noqa: E402
    parse_generic_model_output_data,
)

world = World(stage_units_in_meters=1.0)
world.scene.add_default_ground_plane()          # physics floor only
add_reference_to_stage(WH_MESH_USD, "/World/workcell_mesh")
add_reference_to_stage(USD_PATH, "/World/pioneer3dx")
robot = Articulation("/World/pioneer3dx", name="pioneer3dx")

XFormPrim("/World/pioneer3dx").set_world_poses(
    np.array([[0.0, 0.0, 0.01]]), np.array([[1.0, 0.0, 0.0, 0.0]]))
XFormPrim("/World/workcell_mesh").set_world_poses(
    np.array([[WC_X, WC_Y, 0.0]]), np.array([[1.0, 0.0, 0.0, 0.0]]))
world.reset()
robot.initialize()
SENSORS = mount_bluesea2_pair(BASE_LINK)

for _ in range(60):
    world.step(render=True)

res = {n: collect_scan(s, world, 1.0, parse_generic_model_output_data)
       for n, s in SENSORS.items()}
f0 = int((~np.isnan(res["front"]["scan"])).sum())
r0 = int((~np.isnan(res["rear"]["scan"])).sum())
seg = res["rear"]["scan"][N_SAMPLES // 2 - 16:N_SAMPLES // 2 + 16]
seg = seg[~np.isnan(seg)]
rear_c = float(np.median(seg)) if seg.size else float("nan")
exp_rear = MOUNTS["rear"]["translation"][0] - WALL3_INNER_X
print(f"[mesh_only] front fill {f0}/600 rear fill {r0}/600", flush=True)
print(f"[mesh_only] rear wall scan {rear_c:.3f} m vs geom {exp_rear:.3f} m",
      flush=True)
ok = (f0 > 50 and r0 > 150 and abs(rear_c - exp_rear) < 0.30)
print(f"[mesh_only] {'MESH RENDERS (LiDAR sees it)' if ok else 'MESH NOT SEEN'}",
      flush=True)
simulation_app.close()
if not ok:
    raise SystemExit(1)
