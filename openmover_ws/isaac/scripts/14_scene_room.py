"""Step 1.4a gate — simple room scene: robot drives, both bluesea2 mirrors
see the walls and obstacles consistently with geometry.

Scenario: robot spawns at (-3, 0) facing +x inside simple_room.usda.
    1) static scan: front centre beam reads the front wall (inner face x=5),
       rear reads the rear wall; the 1 m box obstacle at (2, 2) shows as a
       nearer return at ~+18..22 deg in the front scan
    2) drive +x at 0.3 m/s for 2 s: front centre range drops and rear centre
       range grows by the distance actually travelled (odom ground truth)

Run: ~/isaacsim/python.sh openmover_ws/isaac/scripts/14_scene_room.py
"""

import math
import os
import time

import numpy as np

from common import ASSETS_DIR, SCENES_DIR, preflight
from lidar_mirror import MOUNTS, N_SAMPLES, collect_scan, mount_bluesea2_pair

USD_PATH = os.path.join(ASSETS_DIR, "pioneer3dx", "pioneer3dx", "pioneer3dx.usda")
ROOM_USD = os.path.join(SCENES_DIR, "simple_room.usda")
BASE_LINK = "/World/pioneer3dx/Geometry/base_link"
WALL_X_INNER = 5.0                # front wall inner face
WALL_REAR_INNER = -5.0            # rear wall inner face
SPAWN = (-3.0, 0.0, 0.01)         # base_link origin is ~ground level (see
                                  # Step 1.1); dropping from higher tips the
                                  # robot onto its folded caster

preflight("scene_room")
assert os.path.isfile(USD_PATH), f"missing {USD_PATH} — run 10_import_urdf.py first"
assert os.path.isfile(ROOM_USD), f"missing {ROOM_USD} — run 14_build_simple_room.py first"

T0 = time.time()
from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({"headless": True, "enable_motion_bvh": True})
print(f"[room] app up in {time.time() - T0:.1f} s", flush=True)

from isaacsim.core.api import World  # noqa: E402
from isaacsim.core.prims import Articulation, XFormPrim  # noqa: E402
from isaacsim.core.utils.stage import add_reference_to_stage  # noqa: E402
from isaacsim.sensors.experimental.rtx import (  # noqa: E402
    parse_generic_model_output_data,
)

from bridge_core import BridgeCore  # noqa: E402

world = World(stage_units_in_meters=1.0)
add_reference_to_stage(ROOM_USD, "/World/room")
add_reference_to_stage(USD_PATH, "/World/pioneer3dx")
robot = Articulation("/World/pioneer3dx", name="pioneer3dx")

XFormPrim("/World/pioneer3dx").set_world_poses(
    np.array([[SPAWN[0], SPAWN[1], SPAWN[2]]]), np.array([[1.0, 0.0, 0.0, 0.0]]))
world.reset()
robot.initialize()
bridge = BridgeCore(world, robot)
SENSORS = mount_bluesea2_pair(BASE_LINK)

# settle
for _ in range(60):
    world.step(render=True)

base = XFormPrim(robot.prim_paths[0], name="base")


def state() -> tuple[float, float, float]:
    """(x, y, yaw_rad) of the robot root."""
    pos, quat = base.get_world_poses()
    q = quat[0]  # w, x, y, z
    yaw = math.atan2(2.0 * (q[0] * q[3] + q[1] * q[2]),
                     1.0 - 2.0 * (q[2] * q[2] + q[3] * q[3]))
    return float(pos[0][0]), float(pos[0][1]), float(yaw)


def centre_range(scan: np.ndarray) -> float:
    # +/-10 deg around the scan centre; wide median keeps this robust to
    # the small yaw drift the robot accumulates while driving
    seg = scan[N_SAMPLES // 2 - 33:N_SAMPLES // 2 + 33]
    seg = seg[~np.isnan(seg)]
    return float(np.median(seg)) if seg.size else float("nan")


x0, y0, yaw0 = state()
pos_s, quat_s = base.get_world_poses()
print(f"[room] settled at x={x0:.3f} y={y0:.3f} z={float(pos_s[0][2]):.3f} "
      f"quat={np.round(quat_s[0], 3)}", flush=True)
# robot must be upright, else scans are garbage
assert (
    float(pos_s[0][2]) > -0.03
    and abs(quat_s[0][1]) < 0.05
    and abs(quat_s[0][2]) < 0.05
), "robot did not settle upright — check spawn"

res0 = {n: collect_scan(s, world, 1.0, parse_generic_model_output_data)
        for n, s in SENSORS.items()}
f0 = res0["front"]["filled"] = int((~np.isnan(res0["front"]["scan"])).sum())
r0 = res0["rear"]["filled"] = int((~np.isnan(res0["rear"]["scan"])).sum())
c_front0 = centre_range(res0["front"]["scan"])
c_rear0 = centre_range(res0["rear"]["scan"])
print(f"[room] static: front fill {f0}/{N_SAMPLES} centre {c_front0:.3f} m | "
      f"rear fill {r0}/{N_SAMPLES} centre {c_rear0:.3f} m", flush=True)

# obstacle check: box at (2,2), nearest corner (1.5,1.5)
d_obs = math.hypot(1.5 - x0, 1.5 - y0)
az_obs = math.degrees(math.atan2(1.5 - y0, 1.5 - x0))
i_lo = int((az_obs - 3 - (-90)) / 180 * N_SAMPLES)
i_hi = int((az_obs + 3 - (-90)) / 180 * N_SAMPLES)
obs_seg = res0["front"]["scan"][max(0, i_lo):min(N_SAMPLES, i_hi)]
obs_seg = obs_seg[~np.isnan(obs_seg)]
c_obs = float(obs_seg.min()) if obs_seg.size else float("nan")
print(f"[room] obstacle at az~{az_obs:.1f} deg: scan min {c_obs:.3f} m "
      f"(geometric nearest corner {d_obs:.3f} m)", flush=True)

exp_front0 = WALL_X_INNER - (x0 + MOUNTS["front"]["translation"][0])
exp_rear0 = (WALL_REAR_INNER * -1) + (x0 + MOUNTS["rear"]["translation"][0])
ok_static = (f0 > 550 and r0 > 550
             and abs(c_front0 - exp_front0) < 0.20
             and abs(c_rear0 - exp_rear0) < 0.20
             and abs(c_obs - d_obs) < 0.25)
print(f"[room] static check: front {c_front0:.3f} vs {exp_front0:.3f}, "
      f"rear {c_rear0:.3f} vs {exp_rear0:.3f} -> "
      f"{'OK' if ok_static else 'FAIL'}", flush=True)

# drive +x for 2 s, then brake to a stop (velocity drive targets persist
# in PhysX — scanning while still creeping would bias the range deltas)
bridge.set_cmd_vel(0.3, 0.0)
dt = world.get_physics_dt()
for _ in range(int(2.0 / dt)):
    bridge.step(render=True)
bridge.set_cmd_vel(0.0, 0.0)
for _ in range(int(0.5 / dt)):
    bridge.step(render=True)
x1, y1, yaw1 = state()
travelled = math.hypot(x1 - x0, y1 - y0)
print(f"[room] after drive: x={x1:.3f} (travelled {travelled:.3f} m, "
      f"yaw drift {math.degrees(yaw1 - yaw0):+.2f} deg)", flush=True)

res1 = {n: collect_scan(s, world, 1.0, parse_generic_model_output_data)
        for n, s in SENSORS.items()}
c_front1 = centre_range(res1["front"]["scan"])
c_rear1 = centre_range(res1["rear"]["scan"])
d_front = c_front0 - c_front1
d_rear = c_rear1 - c_rear0
ok_drive = (abs(d_front - travelled) < 0.15 and abs(d_rear - travelled) < 0.15
            and travelled > 0.4)
print(f"[room] drive check: front range dropped {d_front:.3f} m, rear grew "
      f"{d_rear:.3f} m vs travelled {travelled:.3f} m -> "
      f"{'OK' if ok_drive else 'FAIL'}", flush=True)

ok = ok_static and ok_drive
print(f"[room] {'PASSED' if ok else 'FAILED'}: simple room scene "
      f"(LiDAR sees walls/obstacles, scans track motion)", flush=True)
simulation_app.close()
if not ok:
    raise SystemExit(1)
