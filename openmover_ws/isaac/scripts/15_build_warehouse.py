"""Step 1.4b — build the warehouse workcell scene USD (headless, no physics run).

Produces openmover_ws/isaac/scenes/warehouse.usda, mirroring the collision
set of the world the ROS 2 stack actually runs (warehouse.sdf, inline
workcell copy — which does NOT include the conveyor frames that exist in
models/workcell/model.sdf):

    workcell  pose (-0.040107, 0.052292, 0):
        floor 20.1026 x 20.1026 x 0.2 (top at z=0), 3 walls, 5 racks,
        3 large pallets + 1 empty + 1 box pallet, 3 poles, control panel
    6 x workcell_bin at x=3..8, y=6 (9 boxes each)

Boxes are baked as explicit triangle meshes (parametric Cube + xformOp:scale
breaks PhysX contact — see 14_build_simple_room.py), so the same prims serve
both collision and RTX-LiDAR raycasts.

Run: ~/isaacsim/python.sh openmover_ws/isaac/scripts/15_build_warehouse.py
"""

import os
import time

from common import SCENES_DIR, preflight

OUT = os.path.join(SCENES_DIR, "warehouse.usda")

# workcell model pose in warehouse.sdf
WC_X, WC_Y = -0.040107, 0.052292

# (name, x, y, z, sx, sy, sz) — local workcell coordinates, from
# warehouse.sdf (inline workcell model).
WORKCELL_BOXES = [
    ("floor", 0.0, 0.0, -0.1, 20.1026, 20.1026, 0.2),
    ("wall1", 4.13686, -10.0212, 3.48855, 12.0768, 0.72902, 6.97771),
    ("wall2", -6.58151, -8.924, 3.48855, 10.5921, 5.00198, 6.97771),
    ("wall3", -9.25721, 0.6135, 3.48855, 0.72902, 15.2908, 6.97771),
    ("rack1", 7.35056, 1.7443, 1.41643, 0.84444, 1.95581, 2.83286),
    ("rack2", 5.36795, 1.7443, 1.41643, 0.84444, 1.95581, 2.83286),
    ("rack3", 7.00142, -7.6467, 1.41643, 0.84444, 3.91162, 2.83286),
    ("rack4", 4.97338, -7.6467, 1.41643, 0.84444, 3.91162, 2.83286),
    ("rack5", 2.66949, -7.6467, 1.41643, 0.84444, 3.91162, 2.83286),
    ("large_pallet1", -3.33609, 6.31883, 1.04257, 2.14726, 1.79349, 2.08514),
    ("large_pallet2", -5.74492, 6.31883, 1.04257, 2.14726, 1.79349, 2.08514),
    ("large_pallet3", -7.55868, 1.91644, 1.04257, 2.14726, 1.79432, 2.08514),
    ("empty_pallet1", -5.29667, 1.91644, 0.1636, 2.14726, 1.79349, 0.3272),
    ("box_pallet1", -1.09806, 6.31883, 0.61958, 2.14726, 1.79349, 1.23916),
    ("pole1", 5.02174, -2.39478, 3.02208, 0.49161, 0.49161, 6.04415),
    ("pole2", 0.47071, -2.39478, 3.02208, 0.49161, 0.49161, 6.04415),
    ("pole3", -3.93786, -2.39478, 3.02208, 0.49161, 0.49161, 6.04415),
    ("control_panel", 2.07015, 1.16224, 0.561315, 0.86733, 0.6001, 1.12263),
]

# one workcell_bin (local coords), from models/workcell_bin/model.sdf;
# thin 3 mm walls are dropped — invisible to a 0.22 m min-range 2D LiDAR
BIN_BOXES = [
    ("center", 0.0, 0.0, 0.45, 0.6, 0.6, 0.55),
    ("base", 0.0, 0.0, 0.100245, 0.66836, 0.66836, 0.20049),
]
BIN_POSES = [(3, 6), (4, 6), (5, 6), (6, 6), (7, 6), (8, 6)]

preflight("build_warehouse")
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
root = UsdGeom.Xform.Define(stage, "/Warehouse")
stage.SetDefaultPrim(root.GetPrim())


def add_box(path: str, pos, size) -> None:
    """Static collider box baked as an explicit triangle mesh (see
    14_build_simple_room.py for why parametric cubes are avoided)."""
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
    mesh = UsdGeom.Mesh.Define(stage, path)
    mesh.CreatePointsAttr([Gf.Vec3f(*v) for v in verts])
    mesh.CreateFaceVertexCountsAttr([4] * len(faces))
    mesh.CreateFaceVertexIndicesAttr([i for f in faces for i in f])
    prim = mesh.GetPrim()
    UsdPhysics.CollisionAPI.Apply(prim)
    mesh_col = UsdPhysics.MeshCollisionAPI.Apply(prim)
    mesh_col.CreateApproximationAttr().Set("none")


n = 0
for name, x, y, z, sx, sy, sz in WORKCELL_BOXES:
    add_box(f"/Warehouse/{name}", (x + WC_X, y + WC_Y, z), (sx, sy, sz))
    n += 1
for i, (bx, by) in enumerate(BIN_POSES, 1):
    for name, lx, ly, lz, sx, sy, sz in BIN_BOXES:
        add_box(f"/Warehouse/bin{i}_{name}", (bx + lx, by + ly, lz), (sx, sy, sz))
        n += 1

stage.GetRootLayer().Save()
print(f"[build] wrote {OUT} ({n} boxes, {os.path.getsize(OUT)} bytes, "
      f"{time.time() - T0:.1f} s total)", flush=True)
simulation_app.close()
