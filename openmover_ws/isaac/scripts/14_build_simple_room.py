"""Step 1.4a — build the simple-room scene USD (headless, no physics run).

Produces openmover_ws/isaac/scenes/simple_room.usda:
    10 x 8 m interior (walls' inner faces at x=+/-5, y=+/-4, height 2 m),
    ground slab, one 1 m box obstacle and one pillar. All static colliders.

Run: ~/isaacsim/python.sh openmover_ws/isaac/scripts/14_build_simple_room.py
"""

import os
import time

from common import SCENES_DIR, preflight

OUT = os.path.join(SCENES_DIR, "simple_room.usda")

preflight("build_simple_room")
os.makedirs(SCENES_DIR, exist_ok=True)
if os.path.exists(OUT):
    os.remove(OUT)

T0 = time.time()
from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({"headless": True})
print(f"[build] app up in {time.time() - T0:.1f} s", flush=True)

from pxr import Gf, Usd, UsdGeom, UsdPhysics  # noqa: E402

stage = Usd.Stage.CreateNew(OUT)
UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
UsdGeom.SetStageMetersPerUnit(stage, 1.0)
room = UsdGeom.Xform.Define(stage, "/Room")
stage.SetDefaultPrim(room.GetPrim())


def add_box(name: str, pos, size) -> None:
    """Static collider box baked as an explicit triangle mesh.

    Parametric Cube + xformOp:scale made PhysX mis-handle the collision
    (robot sank ~2 cm and tipped on such a floor; probe 14_probe_floor.py).
    Baking real vertices keeps the robot upright and the LiDAR raycasts
    exact. Boxes are axis-aligned: pos = centre, size = (dx, dy, dz).
    """
    px, py, pz = pos
    hx, hy, hz = size[0] / 2, size[1] / 2, size[2] / 2
    verts = [
        (px - hx, py - hy, pz - hz), (px + hx, py - hy, pz - hz),
        (px + hx, py + hy, pz - hz), (px - hx, py + hy, pz - hz),
        (px - hx, py - hy, pz + hz), (px + hx, py - hy, pz + hz),
        (px + hx, py + hy, pz + hz), (px - hx, py + hy, pz + hz),
    ]
    faces = [
        (0, 3, 2, 1),  # bottom (-z)
        (4, 5, 6, 7),  # top (+z)
        (0, 1, 5, 4),  # -y
        (2, 3, 7, 6),  # +y
        (1, 2, 6, 5),  # +x
        (0, 4, 7, 3),  # -x
    ]
    mesh = UsdGeom.Mesh.Define(stage, f"/Room/{name}")
    mesh.CreatePointsAttr([Gf.Vec3f(*v) for v in verts])
    mesh.CreateFaceVertexCountsAttr([4] * len(faces))
    mesh.CreateFaceVertexIndicesAttr([i for f in faces for i in f])
    prim = mesh.GetPrim()
    UsdPhysics.CollisionAPI.Apply(prim)
    mesh_col = UsdPhysics.MeshCollisionAPI.Apply(prim)
    # exact triangle mesh — fine for static geometry (cube = exact box)
    mesh_col.CreateApproximationAttr().Set("none")


WALL_H, WALL_T = 2.0, 0.2
add_box("Floor", (0, 0, -0.05), (30, 30, 0.1))          # top face at z=0
add_box("WallFront", (5.0 + WALL_T / 2, 0, WALL_H / 2), (WALL_T, 8.0 + 2 * WALL_T, WALL_H))
add_box("WallRear", (-5.0 - WALL_T / 2, 0, WALL_H / 2), (WALL_T, 8.0 + 2 * WALL_T, WALL_H))
add_box("WallLeft", (0, 4.0 + WALL_T / 2, WALL_H / 2), (10.0, WALL_T, WALL_H))
add_box("WallRight", (0, -4.0 - WALL_T / 2, WALL_H / 2), (10.0, WALL_T, WALL_H))
add_box("ObstacleBox", (2.0, 2.0, 0.5), (1.0, 1.0, 1.0))
add_box("ObstaclePillar", (-2.0, -1.0, 0.75), (0.5, 0.5, 1.5))

stage.GetRootLayer().Save()
print(f"[build] wrote {OUT} "
      f"({os.path.getsize(OUT)} bytes, {time.time() - T0:.1f} s total)",
      flush=True)
simulation_app.close()
