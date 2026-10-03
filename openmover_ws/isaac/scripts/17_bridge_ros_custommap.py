"""Capstone bridge — Isaac-side ROS 2 bridge on a USER-DRAWN custom map.

Same ROS contract as 16_bridge_ros.py (the warehouse rung):
    in : /cmd_vel (geometry_msgs/Twist)
    out: /clock, /odom (nav_msgs/Odometry), /tf (odom->base_link),
         /openmover/hardware/lidar_forward/scan,
         /openmover/hardware/lidar_rear/scan, /tf_static

Difference: the scene is NOT the warehouse. It is built at startup from a
map JSON authored with isaac/lab/27_make_custom_map.py ("draw a PNG, then
go"): a floor slab plus the map's wall boxes, baked as explicit triangle
meshes (the 15_build_warehouse.py pattern — parametric Cube + xformOp:scale
breaks PhysX contact), so the same prims serve collision and RTX-LiDAR
raycasts. The robot spawns at the map's spawn marker.

The map's tile corner sits at world (0,0); the policy node's GeoField is
built from the SAME json (map_file parameter), so both sides of the
embodiment boundary share one map frame.

Additionally records a ground-truth presentation trace at the scan tick
(15 Hz): robot pose + world-frame LiDAR hit points, saved on exit as an npz
consumable by isaac/lab/26_render_topdown_video.py (schema: traj (T,3),
lidar (T,300,2), ep_goal/ep_spawn (1,2), ep_start (1,), occ (gy,gx) bool,
origin (2,), size (2,)).

Run: source /opt/ros/jazzy/setup.bash && \
     ~/isaacsim/python.sh openmover_ws/isaac/scripts/17_bridge_ros_custommap.py \
         --map_file openmover_ws/isaac/lab/maps/demo_spiral.json
"""

import argparse
import json
import math
import os
import time

import numpy as np

from common import ASSETS_DIR, WS_ROOT, preflight
from lidar_mirror import (AZ_MAX, AZ_MIN, FAR, MOUNTS, NEAR, N_SAMPLES,
                          RATE, mount_bluesea2_pair)

parser = argparse.ArgumentParser(description="Custom-map Isaac ROS bridge.")
parser.add_argument("--map_file", type=str, required=True)
parser.add_argument("--duration", type=float, default=130.0,
                    help="bounded sim time [s]; trace is saved on exit")
parser.add_argument("--trace", type=str, default=None,
                    help="output npz (default videos/custommap_demo/trace_<map>.npz)")
parser.add_argument("--seed", type=int, default=None,
                    help="if set, jitter the map spawn by +-0.15 m / +-15 deg "
                         "(N-seed repeat statistic)")
args_cli = parser.parse_args()

USD_PATH = os.path.join(ASSETS_DIR, "pioneer3dx", "pioneer3dx", "pioneer3dx.usda")
BASE_LINK = "/World/pioneer3dx/Geometry/base_link"

with open(args_cli.map_file) as f:
    SPEC = json.load(f)
MAP_SX, MAP_SY = float(SPEC["size"][0]), float(SPEC["size"][1])
MAP_CELL = float(SPEC.get("cell", 0.125))
WALL_H = float(SPEC.get("wall_height", 0.5))
SPAWN = (float(SPEC["spawn"][0]), float(SPEC["spawn"][1]), 0.01)
SPAWN_YAW = 0.0
if args_cli.seed is not None:
    _rng = np.random.default_rng(args_cli.seed)
    SPAWN = (SPAWN[0] + float(_rng.uniform(-0.15, 0.15)),
             SPAWN[1] + float(_rng.uniform(-0.15, 0.15)), SPAWN[2])
    SPAWN_YAW = float(_rng.uniform(-math.radians(15), math.radians(15)))
GOAL = (float(SPEC["goal"][0]), float(SPEC["goal"][1]))

TRACE_PATH = args_cli.trace or os.path.join(
    WS_ROOT, "lab", "videos", "custommap_demo",
    f"trace_{SPEC['name']}.npz")

SCAN_TOPICS = {
    "front": "/openmover/hardware/lidar_forward/scan",
    "rear": "/openmover/hardware/lidar_rear/scan",
}
SCAN_FRAMES = {"front": "lidar_forward_link", "rear": "lidar_rear_link"}
ANGLE_MIN = math.radians(AZ_MIN)
ANGLE_MAX = math.radians(AZ_MAX)
EDGES = np.linspace(AZ_MIN, AZ_MAX, N_SAMPLES + 1)

preflight("bridge_ros_custommap")
for p in (USD_PATH, args_cli.map_file):
    assert os.path.isfile(p), f"missing {p}"

T0 = time.time()
from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({"headless": True, "enable_motion_bvh": True})
print(f"[bridge] app up in {time.time() - T0:.1f} s", flush=True)

from pxr import Gf, UsdGeom, UsdPhysics  # noqa: E402

from isaacsim.core.api import World  # noqa: E402
from isaacsim.core.prims import Articulation, XFormPrim  # noqa: E402
from isaacsim.core.utils.stage import (  # noqa: E402
    add_reference_to_stage,
    get_current_stage,
)
from isaacsim.sensors.experimental.rtx import (  # noqa: E402
    parse_generic_model_output_data,
)

import rclpy  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.qos import DurabilityPolicy, QoSProfile  # noqa: E402
from geometry_msgs.msg import Quaternion, TransformStamped, Twist  # noqa: E402
from nav_msgs.msg import Odometry  # noqa: E402
from rosgraph_msgs.msg import Clock  # noqa: E402
from sensor_msgs.msg import LaserScan  # noqa: E402
from tf2_msgs.msg import TFMessage  # noqa: E402

from bridge_core import BridgeCore  # noqa: E402

world = World(stage_units_in_meters=1.0)
stage = get_current_stage()


def add_box(path: str, pos, size, yaw: float = 0.0) -> None:
    """Static collider box baked as an explicit triangle mesh (see
    15_build_warehouse.py for why parametric cubes are avoided)."""
    px, py, pz = pos
    hx, hy, hz = size[0] / 2, size[1] / 2, size[2] / 2
    c, s = math.cos(yaw), math.sin(yaw)
    local = [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
             (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)]
    verts = [(px + c * lx - s * ly, py + s * lx + c * ly, pz + lz)
             for lx, ly, lz in local]
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


# floor slab (top at z=0) + map wall boxes, tile corner at world (0,0)
add_box("/World/map_floor", (0.5 * MAP_SX, 0.5 * MAP_SY, -0.1),
        (MAP_SX + 4.0, MAP_SY + 4.0, 0.2))
for k, b in enumerate(SPEC["boxes"]):
    cx, cy, yaw, ln, wd, ht = (float(v) for v in b)
    add_box(f"/World/map_wall_{k}", (cx, cy, 0.5 * ht), (ln, wd, ht), yaw)
print(f"[bridge] map '{SPEC['name']}': {len(SPEC['boxes'])} wall boxes, "
      f"spawn=({SPAWN[0]:.2f},{SPAWN[1]:.2f}), goal=({GOAL[0]:.2f},{GOAL[1]:.2f}), "
      f"path_len~{SPEC.get('path_len', float('nan'))} m", flush=True)

add_reference_to_stage(USD_PATH, "/World/pioneer3dx")
robot = Articulation("/World/pioneer3dx", name="pioneer3dx")

XFormPrim("/World/pioneer3dx").set_world_poses(
    np.array([[SPAWN[0], SPAWN[1], SPAWN[2]]]),
    np.array([[0.0, 0.0, math.sin(SPAWN_YAW / 2), math.cos(SPAWN_YAW / 2)]]))
world.reset()
robot.initialize()
bridge = BridgeCore(world, robot)
SENSORS = mount_bluesea2_pair(BASE_LINK)

DT = world.get_physics_dt()
TICK = 1.0 / RATE
QOS = QoSProfile(depth=10)                       # reliable keep-last (rclpy default)
QOS_STATIC = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)


def ros_stamp(sim_t: float):
    from builtin_interfaces.msg import Time
    return Time(sec=int(sim_t), nanosec=int((sim_t % 1.0) * 1e9))


def quat_msg(q_wxyz) -> Quaternion:
    return Quaternion(x=float(q_wxyz[1]), y=float(q_wxyz[2]),
                      z=float(q_wxyz[3]), w=float(q_wxyz[0]))


def yaw_of(q_wxyz) -> float:
    w, x, y, z = (float(v) for v in q_wxyz)
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def rot2d_of_q(q_wxyz) -> np.ndarray:
    w, x, y, z = (float(v) for v in q_wxyz)
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z)]])


def bin_ranges(az: np.ndarray, rng: np.ndarray) -> np.ndarray:
    """Min-per-bin re-bin of one tick's RTX sweep (600 bins); empty bins 0.0
    (the bluesea2 driver convention for invalid returns)."""
    ranges = np.zeros(N_SAMPLES, dtype=np.float32)
    if az.size:
        win = ((az >= AZ_MIN) & (az <= AZ_MAX)
               & (rng >= NEAR) & (rng <= FAR))
        if win.any():
            idx = np.clip(np.digitize(az[win], EDGES) - 1, 0, N_SAMPLES - 1)
            acc = np.full(N_SAMPLES, np.inf)
            np.minimum.at(acc, idx, rng[win])
            valid = ~np.isinf(acc)
            ranges[valid] = acc[valid].astype(np.float32)
    return ranges


def scan_world_hits(ranges: np.ndarray, mount: dict, xy, yaw: float) -> np.ndarray:
    """150 world-frame hit points (stride-4 downsample) for the video fan;
    NaN = missed ray (renderer convention)."""
    idx = np.arange(0, N_SAMPLES, 4)
    ang = ANGLE_MIN + idx * (ANGLE_MAX - ANGLE_MIN) / (N_SAMPLES - 1)
    r = ranges[idx]
    hits = np.full((idx.size, 2), np.nan)
    ok = r > 0.0
    p = np.stack([r[ok] * np.cos(ang[ok]), r[ok] * np.sin(ang[ok])])
    p = rot2d_of_q(mount["orientation"]) @ p + np.asarray(mount["translation"])[:2, None]
    c, s = math.cos(yaw), math.sin(yaw)
    hits[ok, 0] = xy[0] + c * p[0] - s * p[1]
    hits[ok, 1] = xy[1] + s * p[0] + c * p[1]
    return hits


class IsaacBridge(Node):
    def __init__(self):
        super().__init__("isaac_bridge")
        self.cmd = (0.0, 0.0)
        self.create_subscription(Twist, "/cmd_vel", self._on_cmd, QOS)
        self.pub_clock = self.create_publisher(Clock, "/clock", QOS)
        self.pub_odom = self.create_publisher(Odometry, "/odom", QOS)
        self.pub_tf = self.create_publisher(TFMessage, "/tf", QOS)
        self.pub_tf_static = self.create_publisher(TFMessage, "/tf_static",
                                                   QOS_STATIC)
        self.pub_scan = {
            n: self.create_publisher(LaserScan, t, QOS)
            for n, t in SCAN_TOPICS.items()}

    def _on_cmd(self, msg: Twist):
        self.cmd = (msg.linear.x, msg.angular.z)

    def static_tf(self, sim_t: float) -> TFMessage:
        """base_link -> real bluesea2 mount frames (lidar_forward/rear_link)."""
        tfm = TFMessage()
        for name, mount in MOUNTS.items():
            ts = TransformStamped()
            ts.header.stamp = ros_stamp(sim_t)
            ts.header.frame_id = "base_link"
            ts.child_frame_id = SCAN_FRAMES[name]
            t = mount["translation"]
            ts.transform.translation.x, ts.transform.translation.y, \
                ts.transform.translation.z = float(t[0]), float(t[1]), float(t[2])
            ts.transform.rotation = quat_msg(mount["orientation"])
            tfm.transforms.append(ts)
        return tfm

    def odom_and_tf(self, sim_t: float, odom: dict):
        stamp = ros_stamp(sim_t)
        pos = odom["position"]
        msg = Odometry()
        msg.header.stamp = stamp
        msg.header.frame_id = "odom"
        msg.child_frame_id = "base_link"
        msg.pose.pose.position.x, msg.pose.pose.position.y, \
            msg.pose.pose.position.z = (float(pos[0]), float(pos[1]),
                                        float(pos[2]))
        msg.pose.pose.orientation = quat_msg(odom["orientation"])
        msg.twist.twist.linear.x = float(odom["linear"][0])
        msg.twist.twist.angular.z = float(odom["angular"][2])
        self.pub_odom.publish(msg)

        ts = TransformStamped()
        ts.header.stamp = stamp
        ts.header.frame_id = "odom"
        ts.child_frame_id = "base_link"
        ts.transform.translation.x, ts.transform.translation.y, \
            ts.transform.translation.z = (float(pos[0]), float(pos[1]),
                                        float(pos[2]))
        ts.transform.rotation = quat_msg(odom["orientation"])
        self.pub_tf.publish(TFMessage(transforms=[ts]))

    def clock(self, sim_t: float):
        self.pub_clock.publish(Clock(clock=ros_stamp(sim_t)))

    def scan_msg(self, name: str, sim_t: float, ranges: np.ndarray) -> LaserScan:
        msg = LaserScan()
        msg.header.stamp = ros_stamp(sim_t)
        msg.header.frame_id = SCAN_FRAMES[name]
        msg.angle_min = ANGLE_MIN
        msg.angle_max = ANGLE_MAX
        msg.angle_increment = (ANGLE_MAX - ANGLE_MIN) / (N_SAMPLES - 1)
        msg.time_increment = 0.0
        msg.scan_time = TICK
        msg.range_min = NEAR
        msg.range_max = FAR
        msg.ranges = ranges.tolist()
        return msg


def rasterize_occ() -> np.ndarray:
    """(gy, gx) bool wall grid at the map cell resolution, tile corner at
    (0,0) — the occupancy layer for the top-down video."""
    nx = int(round(MAP_SX / MAP_CELL))
    ny = int(round(MAP_SY / MAP_CELL))
    gx = (np.arange(nx) + 0.5) * MAP_CELL
    gy = (np.arange(ny) + 0.5) * MAP_CELL
    gx_m, gy_m = np.meshgrid(gx, gy)          # (ny, nx)
    occ = np.zeros((ny, nx), dtype=bool)
    for b in SPEC["boxes"]:
        cx, cy, yaw, ln, wd, _ht = (float(v) for v in b)
        c, s = math.cos(yaw), math.sin(yaw)
        dx, dy = gx_m - cx, gy_m - cy
        lx = c * dx + s * dy
        ly = -s * dx + c * dy
        occ |= (np.abs(lx) <= 0.5 * ln) & (np.abs(ly) <= 0.5 * wd)
    return occ


def main():
    rclpy.init()
    node = IsaacBridge()

    # settle the robot on the floor before exposing it to the ROS side
    for _ in range(60):
        world.step(render=True)
    base = XFormPrim(robot.prim_paths[0], name="base")
    pos, quat = base.get_world_poses()
    print(f"[bridge] settled at x={pos[0][0]:.3f} y={pos[0][1]:.3f} "
          f"z={pos[0][2]:.3f}", flush=True)

    acc = {n: {"az": [], "rng": []} for n in SENSORS}
    sim_t = 0.0
    next_tick = TICK
    n_scans = 0
    trace_t, trace_pose, trace_lidar = [], [], []
    node.pub_tf_static.publish(node.static_tf(0.0))
    print(f"[bridge] loop conds: is_running={simulation_app.is_running()} "
          f"is_exiting={simulation_app.is_exiting()} rclpy_ok={rclpy.ok()}",
          flush=True)
    print(f"[bridge] live: /cmd_vel in; /clock /odom /tf + 2 bluesea2 scans "
          f"out (dt={DT:.4f} s, scan tick={TICK:.3f} s, duration "
          f"{args_cli.duration:.0f} s)", flush=True)

    try:
        it = 0
        wall_t0 = time.monotonic()
        while (not simulation_app.is_exiting() and rclpy.ok()
               and sim_t < args_cli.duration):
            it += 1
            if it == 1:
                print("[bridge] loop entered", flush=True)
            render = sim_t + DT >= next_tick - 1e-9
            bridge.set_cmd_vel(*node.cmd)
            bridge.step(render=render)
            sim_t += DT

            ranges = {}
            if render:
                for name, sensor in SENSORS.items():
                    data, _ = sensor.get_data("generic-model-output")
                    if data is None:
                        continue
                    gmo = parse_generic_model_output_data(data)
                    if gmo.numElements == 0:
                        continue
                    acc[name]["az"].append(np.asarray(gmo.x))
                    acc[name]["rng"].append(np.asarray(gmo.z))

            node.clock(sim_t)
            node.odom_and_tf(sim_t, bridge.get_odom())

            if sim_t >= next_tick:
                odom = bridge.get_odom()
                xy = (float(odom["position"][0]), float(odom["position"][1]))
                yaw = yaw_of(odom["orientation"])
                row = np.empty((300, 2), dtype=np.float32)
                for k, name in enumerate(("front", "rear")):
                    if acc[name]["az"]:
                        az = np.concatenate(acc[name]["az"])
                        rng = np.concatenate(acc[name]["rng"])
                    else:
                        az = rng = np.array([])
                    ranges[name] = bin_ranges(az, rng)
                    node.pub_scan[name].publish(
                        node.scan_msg(name, sim_t, ranges[name]))
                    acc[name] = {"az": [], "rng": []}
                    n_scans += 1
                    row[k * 150:(k + 1) * 150] = scan_world_hits(
                        ranges[name], MOUNTS[name], xy, yaw)
                trace_t.append(sim_t)
                trace_pose.append((xy[0], xy[1], yaw))
                trace_lidar.append(row)
                next_tick += TICK
                if next_tick < sim_t:      # fell behind — don't burst
                    next_tick = sim_t + TICK

            if int(sim_t / 5.0) != int((sim_t - DT) / 5.0):
                p, _ = base.get_world_poses()
                print(f"[bridge] t={sim_t:6.1f}s cmd={node.cmd[0]:+.2f}/"
                      f"{node.cmd[1]:+.2f} pos=({p[0][0]:+.2f},{p[0][1]:+.2f}) "
                      f"scans={n_scans}", flush=True)

            rclpy.spin_once(node, timeout_sec=0)

            lag = wall_t0 + sim_t - time.monotonic()
            if lag > 0:
                time.sleep(lag)
        print(f"[bridge] loop EXITED: is_exiting={simulation_app.is_exiting()} "
              f"rclpy_ok={rclpy.ok()} iters={it} t={sim_t:.1f}s", flush=True)
    except KeyboardInterrupt:
        pass
    except BaseException:
        import traceback
        traceback.print_exc()
        raise
    finally:
        if trace_pose:
            os.makedirs(os.path.dirname(TRACE_PATH), exist_ok=True)
            np.savez(
                TRACE_PATH,
                traj=np.asarray(trace_pose, dtype=np.float32),
                lidar=np.asarray(trace_lidar, dtype=np.float32),
                ep_goal=np.asarray([GOAL], dtype=np.float32),
                ep_spawn=np.asarray([SPAWN[:2]], dtype=np.float32),
                ep_start=np.asarray([0], dtype=np.int64),
                occ=rasterize_occ(),
                origin=np.asarray([0.5 * MAP_SX, 0.5 * MAP_SY]),
                size=np.asarray([MAP_SX, MAP_SY]))
            print(f"[bridge] trace saved: {TRACE_PATH} "
                  f"({len(trace_pose)} frames @ {RATE:.0f} Hz)", flush=True)
        print(f"[bridge] shutdown at t={sim_t:.1f} s, {n_scans} scans out",
              flush=True)
        node.destroy_node()
        rclpy.shutdown()
        simulation_app.close()


if __name__ == "__main__":
    main()
