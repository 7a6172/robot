"""Offline 3D playback renderer for custom-map traces.

Replays a ground-truth trace npz (from 17_bridge_ros_custommap.py) in a fresh
Isaac scene built from the SAME map JSON, kinematically posing a stylized
proxy robot (primitives; the pioneer3dx usda ships no visual meshes and
referenced subtrees do not reach the headless render scene) per frame
(no physics, no ROS), and records a bird or chase camera to mp4 via an
ffmpeg rawvideo pipe. The live science runs stay untouched; this is pure
presentation post-processing (companion of 26_render_topdown_video.py).

Usage (headless):
    ~/isaaclab/isaaclab.sh -p 29_render_3d_video.py --headless --enable_cameras \
        --trace videos/custommap_demo/trace_demo_crossings_clip.npz \
        --map_file maps/demo_crossings.json --view bird
"""
import argparse
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from isaaclab.app import AppLauncher  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--trace", type=str, required=True)
parser.add_argument("--map_file", type=str, required=True)
parser.add_argument("--view", type=str, default="bird",
                    choices=["bird", "chase"])
parser.add_argument("--fps", type=float, default=15.0)
parser.add_argument("--stride", type=int, default=1,
                    help="frame decimation of the trace")
parser.add_argument("--width", type=int, default=960)
parser.add_argument("--height", type=int, default=540)
parser.add_argument("--out", type=str, default=None,
                    help="default: <trace stem>.<view>3d.mp4")
parser.add_argument("--focal", type=float, default=24.0,
                    help="pinhole focal length; lower = wider FOV (default "
                         "24 clips the map corners, ~17 frames the full 8 m "
                         "square for serial tours)")
parser.add_argument("--bird_height", type=float, default=10.5,
                    help="bird's-eye camera height above ground (m); raise to "
                         "frame larger maps (default 10.5 frames the ~8 m "
                         "serial-tour squares)")
parser.add_argument("--bird_offset", type=float, default=3.5,
                    help="bird's-eye horizontal camera offset from map centre "
                         "(m); sets the view tilt (default 3.5)")
AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()

simulation_app = AppLauncher(args_cli).app

import json  # noqa: E402

import numpy as np  # noqa: E402
from pxr import Gf, UsdGeom, UsdPhysics  # noqa: E402

import isaaclab.sim as sim_utils  # noqa: E402
from isaaclab.sensors.camera import Camera, CameraCfg  # noqa: E402
import omni.usd  # noqa: E402

with open(args_cli.map_file) as f:
    SPEC = json.load(f)
MAP_SX, MAP_SY = (float(v) for v in SPEC["size"])
TRACE = np.load(args_cli.trace)
# Trajectories are recorded in WORLD frame, but the walls/floor below are placed
# in TILE-LOCAL coords (straight from the map JSON). Shift world -> tile-local so
# the robot, spawn and goal discs align with the geometry. For traces whose
# origin == size/2 (e.g. the custommap_demo tours) this is the identity; when
# origin/size are absent it is a no-op (back-compat with pre-schema-v2 traces).
if "origin" in TRACE.files and "size" in TRACE.files:
    _shift = -np.asarray(TRACE["origin"]) + np.asarray(TRACE["size"]) / 2.0
else:
    _shift = np.zeros(2)
traj = TRACE["traj"][::args_cli.stride].copy()
traj[:, :2] += _shift
ep_goal = TRACE["ep_goal"] + _shift
ep_spawn = TRACE["ep_spawn"] + _shift
CX, CY = 0.5 * MAP_SX, 0.5 * MAP_SY

OUT = args_cli.out or str(Path(args_cli.trace).with_name(
    Path(args_cli.trace).stem + f".{args_cli.view}3d.mp4"))

sim_cfg = sim_utils.SimulationCfg()
sim = sim_utils.SimulationContext(sim_cfg)
sim.set_camera_view([2.5, 2.5, 2.5], [0.0, 0.0, 0.0])
stage = omni.usd.get_context().get_stage()


def add_box(path: str, pos, size, yaw: float = 0.0, color=None) -> None:
    """Static visual+collision box as explicit triangle mesh (bridge 17)."""
    px, py, pz = pos
    hx, hy, hz = size[0] / 2, size[1] / 2, size[2] / 2
    c, s = math.cos(yaw), math.sin(yaw)
    local = [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
             (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)]
    verts = [(px + c * lx - s * ly, py + s * lx + c * ly, pz + lz)
             for lx, ly, lz in local]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (2, 3, 7, 6), (1, 2, 6, 5), (0, 4, 7, 3)]
    mesh = UsdGeom.Mesh.Define(stage, path)
    mesh.CreatePointsAttr([Gf.Vec3f(*v) for v in verts])
    mesh.CreateFaceVertexCountsAttr([4] * len(faces))
    mesh.CreateFaceVertexIndicesAttr([i for f in faces for i in f])
    prim = mesh.GetPrim()
    UsdPhysics.CollisionAPI.Apply(prim)
    mesh_col = UsdPhysics.MeshCollisionAPI.Apply(prim)
    mesh_col.CreateApproximationAttr().Set("none")
    if color is not None:
        mesh.CreateDisplayColorAttr([Gf.Vec3f(*color)])


add_box("/World/map_floor", (CX, CY, -0.1), (MAP_SX + 4, MAP_SY + 4, 0.2),
        0.0, color=(0.82, 0.80, 0.75))
for k, b in enumerate(SPEC["boxes"]):
    cx, cy, yaw, ln, wd, ht = (float(v) for v in b)
    add_box(f"/World/map_wall_{k}", (cx, cy, 0.5 * ht), (ln, wd, ht), yaw,
            color=(0.16, 0.22, 0.35))


def add_disc(path: str, xy, color) -> None:
    cyl = UsdGeom.Cylinder.Define(stage, path)
    cyl.CreateRadiusAttr(0.24)
    cyl.CreateHeightAttr(0.03)
    cyl.CreateAxisAttr("Z")
    cyl.AddTranslateOp().Set(Gf.Vec3d(float(xy[0]), float(xy[1]), 0.015))
    cyl.CreateDisplayColorAttr([Gf.Vec3f(*color)])


add_disc("/World/mark_start", ep_spawn[0], (0.10, 0.45, 0.90))
for g, goal_xy in enumerate(ep_goal):
    add_disc(f"/World/mark_goal_{g}", goal_xy, (0.10, 0.65, 0.25))

sim_utils.DomeLightCfg(intensity=400.0).func(
    "/World/dome_light", sim_utils.DomeLightCfg(intensity=400.0))

# Stylized proxy robot (primitives render reliably in headless Fabric).
_proxy = UsdGeom.Xform.Define(stage, "/World/proxy_robot")
_trans_op = _proxy.AddTranslateOp()
_rotz_op = _proxy.AddRotateZOp()


def _child_matrix(prim, mat) -> None:
    UsdGeom.Xformable(prim).AddTransformOp().Set(mat)


_body = UsdGeom.Cube.Define(stage, "/World/proxy_robot/body")
_body.CreateSizeAttr(1.0)
_body.CreateDisplayColorAttr([Gf.Vec3f(0.92, 0.92, 0.90)])
_child_matrix(_body, Gf.Matrix4d().SetScale(
    Gf.Vec3d(0.44, 0.28, 0.14)).SetTranslateOnly(Gf.Vec3d(0, 0, 0.15)))

_top = UsdGeom.Cube.Define(stage, "/World/proxy_robot/top_plate")
_top.CreateSizeAttr(1.0)
_top.CreateDisplayColorAttr([Gf.Vec3f(0.16, 0.22, 0.35)])
_child_matrix(_top, Gf.Matrix4d().SetScale(
    Gf.Vec3d(0.38, 0.24, 0.02)).SetTranslateOnly(Gf.Vec3d(0, 0, 0.23)))

for _side, _sy in (("l", 0.155), ("r", -0.155)):
    _w = UsdGeom.Cylinder.Define(stage, f"/World/proxy_robot/wheel_{_side}")
    _w.CreateRadiusAttr(0.065)
    _w.CreateHeightAttr(0.03)
    _w.CreateAxisAttr("Y")
    _w.CreateDisplayColorAttr([Gf.Vec3f(0.10, 0.10, 0.12)])
    _child_matrix(_w, Gf.Matrix4d().SetTranslateOnly(
        Gf.Vec3d(0.0, _sy, 0.065)))

_lidar = UsdGeom.Cylinder.Define(stage, "/World/proxy_robot/lidar")
_lidar.CreateRadiusAttr(0.035)
_lidar.CreateHeightAttr(0.05)
_lidar.CreateAxisAttr("Z")
_lidar.CreateDisplayColorAttr([Gf.Vec3f(0.15, 0.20, 0.35)])
_child_matrix(_lidar, Gf.Matrix4d().SetTranslateOnly(
    Gf.Vec3d(0.12, 0, 0.27)))


def set_robot_pose(x: float, y: float, yaw: float) -> None:
    _trans_op.Set(Gf.Vec3d(float(x), float(y), 0.0))
    _rotz_op.Set(float(math.degrees(yaw)))


set_robot_pose(*traj[0][:2], float(traj[0][2]))

cam_cfg = CameraCfg(
    prim_path="/World/cam3d",
    update_period=0,
    height=args_cli.height,
    width=args_cli.width,
    data_types=["rgb"],
    spawn=sim_utils.PinholeCameraCfg(
        focal_length=args_cli.focal, focus_distance=400.0,
        horizontal_aperture=20.955, clipping_range=(0.1, 1.0e5)),
)
camera = Camera(cfg=cam_cfg)
sim.reset()

if args_cli.view == "bird":
    pos = np.array([[CX + args_cli.bird_offset, CY - args_cli.bird_offset,
                     args_cli.bird_height]], dtype=np.float32)
    tgt = np.array([[CX, CY, 0.2]], dtype=np.float32)
    camera.set_world_poses_from_view(pos, tgt)

ffmpeg = subprocess.Popen(
    ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo",
     "-pix_fmt", "rgb24", "-s", f"{args_cli.width}x{args_cli.height}",
     "-r", str(args_cli.fps), "-i", "pipe:", "-c:v", "libx264",
     "-pix_fmt", "yuv420p", OUT],
    stdin=subprocess.PIPE)

dt = sim.get_physics_dt()
for t in range(traj.shape[0]):
    x, y, yaw = (float(v) for v in traj[t])
    set_robot_pose(x, y, yaw)
    if args_cli.view == "chase":
        c, s = math.cos(yaw), math.sin(yaw)
        pos = np.array([[x - 1.9 * c, y - 1.9 * s, 1.25]], dtype=np.float32)
        tgt = np.array([[x + 1.4 * c, y + 1.4 * s, 0.25]], dtype=np.float32)
        camera.set_world_poses_from_view(pos, tgt)
    sim.render()
    camera.update(dt=dt, force_recompute=True)
    rgb = camera.data.output["rgb"]
    if rgb is None or rgb.numel() == 0:
        print(f"[3d] frame {t}: no rgb yet, skipping", flush=True)
        continue
    frame = np.asarray(rgb[0].detach().cpu())[:, :, :3].astype(np.uint8)
    ffmpeg.stdin.write(np.ascontiguousarray(frame).tobytes())
    if t % 100 == 0:
        print(f"[3d] frame {t}/{traj.shape[0]}", flush=True)

ffmpeg.stdin.close()
ffmpeg.wait()
print(f"[3d] wrote {OUT} ({traj.shape[0]} frames @ {args_cli.fps} Hz, "
      f"view={args_cli.view})", flush=True)
simulation_app.close()
