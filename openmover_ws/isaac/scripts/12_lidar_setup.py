"""Step 1.2 gate — two RTX 2D LiDARs mounted on pioneer3dx, mirroring the
real bluesea2 chain. See lidar_mirror.py for specs/mounts and probe notes
(incl. the ~0.1 m asset optical-origin bias).

Test: robot static at the origin between two walls; front scan centre beam
should read the front wall distance, rear scan the rear wall distance.

Run: ~/isaacsim/python.sh openmover_ws/isaac/scripts/12_lidar_setup.py
"""

import os
import time

import numpy as np

from common import ASSETS_DIR, preflight
from lidar_mirror import MOUNTS, N_SAMPLES, collect_scan, mount_bluesea2_pair

USD_PATH = os.path.join(ASSETS_DIR, "pioneer3dx", "pioneer3dx", "pioneer3dx.usda")
BASE_LINK = "/World/pioneer3dx/Geometry/base_link"
WALL_X = 3.0                      # walls at +/-3 m (inner faces at +/-2.9 m)

preflight("lidar_setup")
assert os.path.isfile(USD_PATH), f"missing {USD_PATH} — run 10_import_urdf.py first"

T0 = time.time()
from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({"headless": True, "enable_motion_bvh": True})
print(f"[lidar] app up in {time.time() - T0:.1f} s", flush=True)

from isaacsim.core.api import World  # noqa: E402
from isaacsim.core.experimental.objects import Cube  # noqa: E402
from isaacsim.core.prims import Articulation, XFormPrim  # noqa: E402
from isaacsim.core.utils.stage import add_reference_to_stage  # noqa: E402
from isaacsim.sensors.experimental.rtx import (  # noqa: E402
    parse_generic_model_output_data,
)

world = World(stage_units_in_meters=1.0)
world.scene.add_default_ground_plane()
add_reference_to_stage(USD_PATH, "/World/pioneer3dx")
robot = Articulation("/World/pioneer3dx", name="pioneer3dx")

# Walls: front and rear within the 10 m range, side walls for FOV shape
Cube("/World/wall_front", positions=np.array([WALL_X, 0.0, 1.0]),
     scales=np.array([0.2, 8.0, 2.0]))
Cube("/World/wall_rear", positions=np.array([-WALL_X, 0.0, 1.0]),
     scales=np.array([0.2, 8.0, 2.0]))
Cube("/World/wall_left", positions=np.array([0.0, 4.0, 1.0]),
     scales=np.array([8.0, 0.2, 2.0]))
Cube("/World/wall_right", positions=np.array([0.0, -4.0, 1.0]),
     scales=np.array([8.0, 0.2, 2.0]))

world.reset()
robot.initialize()

base = XFormPrim(robot.prim_paths[0], name="base")
pos0, _ = base.get_world_poses()
pos0 = pos0[0]
print(f"[lidar] base pose: x={pos0[0]:.3f} y={pos0[1]:.3f} z={pos0[2]:.3f}",
      flush=True)
assert abs(pos0[0]) < 0.1 and abs(pos0[1]) < 0.1, \
    "robot not at origin; wall math invalid"

SENSORS = mount_bluesea2_pair(BASE_LINK)
for name in SENSORS:
    wp = XFormPrim(f"{BASE_LINK}/bluesea2_{name}").get_world_poses()[0][0]
    print(f"[lidar] {name}: world=({wp[0]:.3f},{wp[1]:.3f},{wp[2]:.3f})",
          flush=True)

# expected centre-beam ranges (walls' inner faces minus lidar x offset)
exp_front = (WALL_X - 0.1) - MOUNTS["front"]["translation"][0]
exp_rear = (-WALL_X + 0.1) - MOUNTS["rear"]["translation"][0]
print(f"[lidar] expected centre ranges: front={exp_front:.3f} "
      f"rear={abs(exp_rear):.3f} m", flush=True)

results = {}
for name in ("front", "rear"):
    res = collect_scan(SENSORS[name], world, 1.0,
                       parse_generic_model_output_data)
    results[name] = res
    if res["frames"] == 0:
        print(f"[lidar] {name}: NO DATA", flush=True)
        continue
    scan = res["scan"]
    filled = int((~np.isnan(scan)).sum())
    res["filled"] = filled
    centre = scan[N_SAMPLES // 2 - 25:N_SAMPLES // 2 + 25]
    centre = centre[~np.isnan(centre)]
    med = float(np.median(centre)) if centre.size else float("nan")
    res["centre"] = med
    print(f"[lidar] {name}: {res['frames']} frames, "
          f"{filled}/{N_SAMPLES} bins filled, centre range {med:.3f} m",
          flush=True)

ok = True
for name, exp in (("front", exp_front), ("rear", abs(exp_rear))):
    res = results[name]
    good = (res.get("frames", 0) > 0 and res.get("filled", 0) > 550
            and abs(res.get("centre", float("nan")) - exp) < 0.15)
    ok = ok and good
    print(f"[lidar] {name}: {'OK' if good else 'FAIL'} "
          f"(centre {res.get('centre', float('nan')):.3f} m vs expected "
          f"{exp:.3f} m)", flush=True)

print(f"[lidar] {'PASSED' if ok else 'FAILED'}: "
      f"{'both bluesea2 mirrors produce valid 600-sample scans' if ok else 'see above'}",
      flush=True)
simulation_app.close()
if not ok:
    raise SystemExit(1)
