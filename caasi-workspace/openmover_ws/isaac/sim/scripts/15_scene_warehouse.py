"""Step 1.4b gate — warehouse workcell scene: robot spawns where the Gazebo
stack spawns it (origin), drives, both bluesea2 mirrors see the workcell
consistently with the SDF geometry.

Scenario (warehouse.usda mirrors warehouse.sdf's collision set):
    1) static scan from origin facing +x:
       - front: control panel nearest corner (1.596, 0.914) at ~+33.6 deg,
         rack2 nearest corner (4.906, 0.819) at ~+9.9 deg
       - rear:  wall3 inner face (world x = -8.933) straight behind
    2) drive +x at 0.3 m/s for 2 s: rear wall range grows by the distance
       actually travelled; panel range drops by travelled * cos(az_panel)

Run: ~/isaacsim/python.sh openmover_ws/isaac/scripts/15_scene_warehouse.py
"""

import math
import os
import time

import numpy as np

from common import ASSETS_DIR, SCENES_DIR, preflight
from lidar_mirror import MOUNTS, N_SAMPLES, collect_scan, mount_bluesea2_pair

USD_PATH = os.path.join(ASSETS_DIR, "pioneer3dx", "pioneer3dx", "pioneer3dx.usda")
WH_USD = os.path.join(SCENES_DIR, "warehouse.usda")
WH_MESH_USD = os.path.join(SCENES_DIR, "workcell_mesh.usdc")
BASE_LINK = "/World/pioneer3dx/Geometry/base_link"
SPAWN = (0.0, 0.0, 0.01)          # Gazebo stack spawns at (0,0,0)

# world-frame features (warehouse.sdf boxes + workcell pose offset)
WC_X, WC_Y = -0.040107, 0.052292
PANEL_CORNER = (2.07015 - 0.86733 / 2 + WC_X, 1.16224 - 0.6001 / 2 + WC_Y)
RACK2_CORNER = (5.36795 - 0.84444 / 2 + WC_X, 1.7443 - 1.95581 / 2 + WC_Y)
WALL3_INNER_X = -9.25721 + 0.72902 / 2 + WC_X   # -8.933

preflight("scene_warehouse")
assert os.path.isfile(USD_PATH), f"missing {USD_PATH} — run 10_import_urdf.py first"
assert os.path.isfile(WH_USD), f"missing {WH_USD} — run 15_build_warehouse.py first"
assert os.path.isfile(WH_MESH_USD), (f"missing {WH_MESH_USD} — run "
                                     "15_convert_workcell_mesh.py first")

T0 = time.time()
from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({"headless": True, "enable_motion_bvh": True})
print(f"[wh] app up in {time.time() - T0:.1f} s", flush=True)

from isaacsim.core.api import World  # noqa: E402
from isaacsim.core.prims import Articulation, XFormPrim  # noqa: E402
from isaacsim.core.utils.stage import add_reference_to_stage  # noqa: E402
from isaacsim.sensors.experimental.rtx import (  # noqa: E402
    parse_generic_model_output_data,
)

from bridge_core import BridgeCore  # noqa: E402

world = World(stage_units_in_meters=1.0)
add_reference_to_stage(WH_USD, "/World/warehouse")
# converted workcell visual mesh (render surface the RTX LiDAR traces);
# it is authored in the workcell-local frame, so place it at the workcell
# model pose to align with the baked collision boxes
add_reference_to_stage(WH_MESH_USD, "/World/workcell_mesh")
add_reference_to_stage(USD_PATH, "/World/pioneer3dx")
robot = Articulation("/World/pioneer3dx", name="pioneer3dx")

XFormPrim("/World/pioneer3dx").set_world_poses(
    np.array([[SPAWN[0], SPAWN[1], SPAWN[2]]]), np.array([[1.0, 0.0, 0.0, 0.0]]))
XFormPrim("/World/workcell_mesh").set_world_poses(
    np.array([[WC_X, WC_Y, 0.0]]), np.array([[1.0, 0.0, 0.0, 0.0]]))
world.reset()
robot.initialize()
bridge = BridgeCore(world, robot)
SENSORS = mount_bluesea2_pair(BASE_LINK)

# settle
for _ in range(60):
    world.step(render=True)

base = XFormPrim(robot.prim_paths[0], name="base")
pos_s, quat_s = base.get_world_poses()
print(f"[wh] settled at x={pos_s[0][0]:.3f} y={pos_s[0][1]:.3f} "
      f"z={pos_s[0][2]:.3f} quat={np.round(quat_s[0], 3)}", flush=True)
assert (
    float(pos_s[0][2]) > -0.03
    and abs(quat_s[0][1]) < 0.05
    and abs(quat_s[0][2]) < 0.05
), "robot did not settle upright — check spawn"


def state() -> tuple[float, float]:
    pos, _ = base.get_world_poses()
    return float(pos[0][0]), float(pos[0][1])


def az_window_min(scan: np.ndarray, az_deg: float, half_w: float = 3.0) -> float:
    i_lo = int((az_deg - half_w - (-90)) / 180 * N_SAMPLES)
    i_hi = int((az_deg + half_w - (-90)) / 180 * N_SAMPLES)
    seg = scan[max(0, i_lo):min(N_SAMPLES, i_hi)]
    seg = seg[~np.isnan(seg)]
    return float(seg.min()) if seg.size else float("nan")


def centre_median(scan: np.ndarray, half_w: float = 5.0) -> float:
    seg = scan[N_SAMPLES // 2 - int(half_w / 180 * N_SAMPLES):
               N_SAMPLES // 2 + int(half_w / 180 * N_SAMPLES)]
    seg = seg[~np.isnan(seg)]
    return float(np.median(seg)) if seg.size else float("nan")


# expected geometry from the spawn pose (robot at origin facing +x)
fx = MOUNTS["front"]["translation"][0]
rx = MOUNTS["rear"]["translation"][0]
exp_panel_d = math.hypot(PANEL_CORNER[0] - fx, PANEL_CORNER[1])
exp_panel_az = math.degrees(math.atan2(PANEL_CORNER[1], PANEL_CORNER[0] - fx))
exp_rack_d = math.hypot(RACK2_CORNER[0] - fx, RACK2_CORNER[1])
exp_rack_az = math.degrees(math.atan2(RACK2_CORNER[1], RACK2_CORNER[0] - fx))
exp_rear_d = (rx + SPAWN[0]) - WALL3_INNER_X   # rear sensor x minus wall face x

res0 = {n: collect_scan(s, world, 1.0, parse_generic_model_output_data)
        for n, s in SENSORS.items()}
f0 = int((~np.isnan(res0["front"]["scan"])).sum())
r0 = int((~np.isnan(res0["rear"]["scan"])).sum())
panel0 = az_window_min(res0["front"]["scan"], exp_panel_az)
rack0 = az_window_min(res0["front"]["scan"], exp_rack_az)
rear0 = centre_median(res0["rear"]["scan"])
print(f"[wh] static: front fill {f0}/{N_SAMPLES} rear fill {r0}/{N_SAMPLES}",
      flush=True)
print(f"[wh] panel az~{exp_panel_az:.1f} deg: scan {panel0:.3f} vs geom "
      f"{exp_panel_d:.3f} | rack2 az~{exp_rack_az:.1f} deg: scan {rack0:.3f} "
      f"vs geom {exp_rack_d:.3f} | rear wall scan {rear0:.3f} vs geom "
      f"{exp_rear_d:.3f}", flush=True)

# the LiDAR asset reads ~0.1 m short of geometric truth (Step 1.2 note),
# hence asymmetric tolerances
ok_static = (
    f0 > 50 and r0 > 150
    and abs(panel0 - exp_panel_d) < 0.25
    and abs(rack0 - exp_rack_d) < 0.30
    and abs(rear0 - exp_rear_d) < 0.30
)
print(f"[wh] static check -> {'OK' if ok_static else 'FAIL'}", flush=True)

# drive +x for 2 s, then brake (velocity targets persist in PhysX)
x0, y0 = state()
bridge.set_cmd_vel(0.3, 0.0)
dt = world.get_physics_dt()
for _ in range(int(2.0 / dt)):
    bridge.step(render=True)
bridge.set_cmd_vel(0.0, 0.0)
for _ in range(int(0.5 / dt)):
    bridge.step(render=True)
x1, y1 = state()
travelled = math.hypot(x1 - x0, y1 - y0)
pos_e, quat_e = base.get_world_poses()
print(f"[wh] after drive: x={x1:.3f} (travelled {travelled:.3f} m, "
      f"z={pos_e[0][2]:.3f})", flush=True)
assert float(pos_e[0][2]) > -0.03, "robot tipped during drive"

res1 = {n: collect_scan(s, world, 1.0, parse_generic_model_output_data)
        for n, s in SENSORS.items()}
panel1 = az_window_min(res1["front"]["scan"], exp_panel_az)
rear1 = centre_median(res1["rear"]["scan"])
d_panel = panel0 - panel1
d_rear = rear1 - rear0
exp_panel_drop = travelled * math.cos(math.radians(exp_panel_az))
ok_drive = (
    travelled > 0.4
    and abs(d_rear - travelled) < 0.15
    and abs(d_panel - exp_panel_drop) < 0.12
)
print(f"[wh] drive check: rear wall grew {d_rear:.3f} (expect {travelled:.3f}), "
      f"panel dropped {d_panel:.3f} (expect {exp_panel_drop:.3f}) -> "
      f"{'OK' if ok_drive else 'FAIL'}", flush=True)

ok = ok_static and ok_drive
print(f"[wh] {'PASSED' if ok else 'FAILED'}: warehouse scene "
      f"(LiDAR sees workcell, scans track motion)", flush=True)
simulation_app.close()
if not ok:
    raise SystemExit(1)
