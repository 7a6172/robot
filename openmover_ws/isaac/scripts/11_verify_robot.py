"""Step 1.1 gate — verify the imported pioneer3dx USD is drivable.

Loads the imported USD, applies velocity targets to the two wheel joints
(velocity-servo gains set explicitly: the URDF carries no stiffness/damping),
and checks the robot actually translates on the ground plane.

Run: ~/isaacsim/python.sh openmover_ws/isaac/scripts/11_verify_robot.py
"""

import os
import time

from common import ASSETS_DIR, preflight

USD_PATH = os.path.join(ASSETS_DIR, "pioneer3dx", "pioneer3dx", "pioneer3dx.usda")
WHEEL_JOINTS = ["base_left_wheel_joint", "base_right_wheel_joint"]
WHEEL_RADIUS = 0.09            # from URDF
TARGET_LINEAR_V = 0.5          # m/s
WHEEL_OMEGA = TARGET_LINEAR_V / WHEEL_RADIUS  # rad/s
KD = 5.0                       # velocity-servo gain (matches effort limit 5 Nm)
SIM_SECONDS = 4.0

preflight("verify_robot")
assert os.path.isfile(USD_PATH), f"missing {USD_PATH} — run 10_import_urdf.py first"

T0 = time.time()
from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({"headless": True})
print(f"[verify] app up in {time.time() - T0:.1f} s", flush=True)

from isaacsim.core.api import World  # noqa: E402
from isaacsim.core.prims import Articulation, XFormPrim  # noqa: E402
from isaacsim.core.utils.stage import add_reference_to_stage  # noqa: E402

from isaacsim.core.utils.types import ArticulationActions  # noqa: E402

world = World(stage_units_in_meters=1.0)
world.scene.add_default_ground_plane()
add_reference_to_stage(USD_PATH, "/World/pioneer3dx")
robot = Articulation("/World/pioneer3dx", name="pioneer3dx")
world.reset()
robot.initialize()

# Introspect joint order so we address wheels by name safely
dof_names = list(getattr(robot, "dof_names", []) or [])
print(f"[verify] dof_names = {dof_names}", flush=True)
if not dof_names:
    print("[verify] FALLBACK: dumping articulation attributes", flush=True)
    print([a for a in dir(robot) if not a.startswith("_")], flush=True)

# Velocity servo gains on the wheel joints
robot.set_gains(kps=None, kds=[KD] * 2, joint_names=WHEEL_JOINTS)

base = XFormPrim(robot.prim_paths[0], name="base")
pos0, _ = base.get_world_poses()
pos0 = pos0[0]
print(f"[verify] start pose: x={pos0[0]:.3f} y={pos0[1]:.3f} z={pos0[2]:.3f}",
      flush=True)

wheel_idx = [dof_names.index(j) for j in WHEEL_JOINTS]
action = ArticulationActions(joint_velocities=[WHEEL_OMEGA, WHEEL_OMEGA],
                             joint_indices=wheel_idx)
dt = world.get_physics_dt()
n_steps = int(SIM_SECONDS / dt)
T1 = time.time()
for i in range(n_steps):
    robot.apply_action(action)
    world.step(render=False)
print(f"[verify] {n_steps} steps ({SIM_SECONDS:.1f} s sim) in "
      f"{time.time() - T1:.1f} s wall", flush=True)

pos1, _ = base.get_world_poses()
pos1 = pos1[0]
dx = float(pos1[0] - pos0[0])
dz = float(pos1[2])
print(f"[verify] end pose:   x={pos1[0]:.3f} y={pos1[1]:.3f} z={pos1[2]:.3f}",
      flush=True)
print(f"[verify] displacement dx = {dx:.3f} m "
      f"(expected ~ {TARGET_LINEAR_V * SIM_SECONDS:.2f} m)", flush=True)

ok = dx > 0.5 * TARGET_LINEAR_V * SIM_SECONDS and -0.05 < dz < 0.3
if ok:
    print("[verify] PASSED — robot is drivable via wheel velocity targets",
          flush=True)
else:
    print("[verify] FAILED — check gains/contacts (dx or z out of range)",
          flush=True)
simulation_app.close()
if not ok:
    raise SystemExit(1)
