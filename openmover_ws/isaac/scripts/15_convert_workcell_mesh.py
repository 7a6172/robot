"""Step 1.4b — convert the warehouse workcell COLLADA mesh to USD (visual only).

trimesh (with pycollada from ~/isaac_pip_extra) reads
src/warehouse_simulation/models/workcell/meshes/mesh.dae and writes
openmover_ws/isaac/scenes/workcell_mesh.usdc: one UsdGeom.Mesh per geometry
node, all bound to a single shared UsdPreviewSurface material.

Geometry-only on purpose: physics collision comes from the baked boxes in
warehouse.usda (the exact collision set of warehouse.sdf). This mesh exists so
RTX LiDAR sees the same wall/rack surfaces Gazebo renders. Textures are
intentionally omitted — bring-up is headless and the gate checks geometry, not
appearance.

Run: PYTHONPATH=$HOME/isaac_pip_extra ~/isaacsim/python.sh \
         openmover_ws/isaac/scripts/15_convert_workcell_mesh.py
"""

import os
import time

import numpy as np

from common import SCENES_DIR, preflight

DAE_PATH = os.path.normpath(os.path.join(
    os.path.dirname(SCENES_DIR),  # openmover_ws/isaac -> openmover_ws
    "..", "src", "warehouse_simulation", "models", "workcell", "meshes", "mesh.dae"))
OUT = os.path.join(SCENES_DIR, "workcell_mesh.usdc")

preflight("convert_workcell_mesh")
assert os.path.isfile(DAE_PATH), f"missing {DAE_PATH}"
if os.path.exists(OUT):
    os.remove(OUT)

T0 = time.time()
import trimesh  # noqa: E402

scene = trimesh.load(DAE_PATH)
# COLLADA stores geometry in mm and scales to metres via per-node scene-graph
# transforms (0.001). scene.geometry holds the RAW (mm) vertices, so baking the
# node transform into the points is mandatory or the mesh is 1000x too large.
geoms = []
if hasattr(scene, "graph") and hasattr(scene.graph, "nodes_geometry"):
    for node in scene.graph.nodes_geometry:
        transform, geom_name = scene.graph.get(node)
        g = scene.geometry[geom_name]
        v = np.asarray(g.vertices, dtype=np.float64)
        v = (transform @ np.hstack([v, np.ones((len(v), 1))]).T).T[:, :3]
        geoms.append((geom_name, v, np.asarray(g.faces, dtype=np.int64)))
else:
    g = scene
    geoms.append(("mesh", np.asarray(g.vertices, dtype=np.float64),
                  np.asarray(g.faces, dtype=np.int64)))
total_v = sum(len(v) for _, v, _ in geoms)
print(f"[convert] {os.path.basename(DAE_PATH)}: {len(geoms)} geometries, "
      f"{total_v} verts", flush=True)

from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({"headless": True})
print(f"[convert] app up in {time.time() - T0:.1f} s", flush=True)

from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade  # noqa: E402

stage = Usd.Stage.CreateNew(OUT)  # .usdc -> binary crate layer
UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
UsdGeom.SetStageMetersPerUnit(stage, 1.0)
root = UsdGeom.Xform.Define(stage, "/WorkcellMesh")
stage.SetDefaultPrim(root.GetPrim())

# one shared material for all geometry
mat = UsdShade.Material.Define(stage, "/WorkcellMesh/_material")
surface = UsdShade.Shader.Define(stage, "/WorkcellMesh/_material/surface")
surface.CreateIdAttr("UsdPreviewSurface")
surface.CreateInput("diffuse", Sdf.ValueTypeNames.Color3f).Set((0.6, 0.6, 0.6))
mat.CreateSurfaceOutput().ConnectToSource(
    surface.CreateOutput("surface", Sdf.ValueTypeNames.Token))

for i, (name, verts, faces) in enumerate(geoms):
    # USD prim names allow only [A-Za-z0-9_] and must not start with a digit
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
    if not safe or safe[0].isdigit():
        safe = f"geom_{i}"
    prim_path = f"/WorkcellMesh/{safe}"
    mesh = UsdGeom.Mesh.Define(stage, prim_path)
    mesh.CreatePointsAttr([Gf.Vec3f(*v) for v in verts])
    mesh.CreateFaceVertexCountsAttr([3] * len(faces))
    mesh.CreateFaceVertexIndicesAttr([int(j) for f in faces for j in f])
    # COLLADA winding is unreliable here; some tris face away from the laser.
    # doubleSided makes RTX hit both windings — neutral for a visual-only mesh
    # (physics collision stays on the baked boxes).
    mesh.CreateDoubleSidedAttr(True)
    UsdShade.MaterialBindingAPI(mesh).Bind(mat)

stage.GetRootLayer().Save()
print(f"[convert] wrote {OUT} ({len(geoms)} meshes, "
      f"{os.path.getsize(OUT)} bytes, {time.time() - T0:.1f} s total)",
      flush=True)
simulation_app.close()
