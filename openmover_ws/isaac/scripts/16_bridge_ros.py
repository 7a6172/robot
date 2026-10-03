"""Step 1.5 — Isaac-side ROS 2 bridge: drive Stack B against Isaac.

Wraps bridge_core.BridgeCore in an rclpy node and mirrors the gz half of
warehouse_simulation's gz_bridge.yaml contract:
    in : /cmd_vel (geometry_msgs/Twist)
    out: /clock, /odom (nav_msgs/Odometry), /tf (odom->base_link),
         /openmover/hardware/lidar_forward/scan,
         /openmover/hardware/lidar_rear/scan
The two scan topics carry the real-robot names so the existing
laserscan_multi_merger (ira_laser_tools) runs unmodified Isaac-side and
remaps its output to /scan (plan doc, Step 1.2 decision). /tf_static carries
base_link->lidar_forward_link / lidar_rear_link at the real mount poses.

All publishers are reliable-QoS: the merger subscribes reliable (depth 1)
and Stack B's gz bridge published reliable too.

Scene = warehouse (boxes for physics + converted workcell mesh for RTX).

Run: source /opt/ros/jazzy/setup.bash && \
     ~/isaacsim/python.sh openmover_ws/isaac/scripts/16_bridge_ros.py
"""

import math
import os
import time

import numpy as np

from common import ASSETS_DIR, SCENES_DIR, preflight
from lidar_mirror import (AZ_MAX, AZ_MIN, FAR, MOUNTS, NEAR, N_SAMPLES,
                          RATE, mount_bluesea2_pair)

USD_PATH = os.path.join(ASSETS_DIR, "pioneer3dx", "pioneer3dx", "pioneer3dx.usda")
WH_USD = os.path.join(SCENES_DIR, "warehouse.usda")
WH_MESH_USD = os.path.join(SCENES_DIR, "workcell_mesh.usdc")
BASE_LINK = "/World/pioneer3dx/Geometry/base_link"
SPAWN = (0.0, 0.0, 0.01)          # Gazebo stack spawns at (0,0,0)
WC_X, WC_Y = -0.040107, 0.052292  # workcell model pose in warehouse.sdf

SCAN_TOPICS = {
    "front": "/openmover/hardware/lidar_forward/scan",
    "rear": "/openmover/hardware/lidar_rear/scan",
}
SCAN_FRAMES = {"front": "lidar_forward_link", "rear": "lidar_rear_link"}
ANGLE_MIN = math.radians(AZ_MIN)
ANGLE_MAX = math.radians(AZ_MAX)
EDGES = np.linspace(AZ_MIN, AZ_MAX, N_SAMPLES + 1)

preflight("bridge_ros")
for p in (USD_PATH, WH_USD, WH_MESH_USD):
    assert os.path.isfile(p), f"missing {p}"

T0 = time.time()
from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({"headless": True, "enable_motion_bvh": True})
print(f"[bridge] app up in {time.time() - T0:.1f} s", flush=True)

from isaacsim.core.api import World  # noqa: E402
from isaacsim.core.prims import Articulation, XFormPrim  # noqa: E402
from isaacsim.core.utils.stage import add_reference_to_stage  # noqa: E402
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
add_reference_to_stage(WH_USD, "/World/warehouse")
# visual mesh authored in the workcell-local frame -> place at the workcell
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

    def scan(self, name: str, sim_t: float, az: np.ndarray,
             rng: np.ndarray) -> LaserScan:
        """Re-bin one tick's RTX sweep into a 600-bin bluesea2-style scan.

        Same min-per-bin rule as lidar_mirror.collect_scan; empty bins -> 0.0
        (the bluesea2 driver convention for invalid returns).
        """
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
        ranges = np.zeros(N_SAMPLES, dtype=np.float32)
        if az.size:
            win = ((az >= AZ_MIN) & (az <= AZ_MAX)
                   & (rng >= NEAR) & (rng <= FAR))
            if win.any():
                idx = np.clip(np.digitize(az[win], EDGES) - 1,
                              0, N_SAMPLES - 1)
                acc = np.full(N_SAMPLES, np.inf)
                np.minimum.at(acc, idx, rng[win])
                valid = ~np.isinf(acc)
                ranges[valid] = acc[valid].astype(np.float32)
        msg.ranges = ranges.tolist()
        return msg


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
    node.pub_tf_static.publish(node.static_tf(0.0))
    # NOTE: simulation_app.is_running() is False in headless script mode (the
    # script itself is the main loop); is_exiting() flips only after close().
    print(f"[bridge] loop conds: is_running={simulation_app.is_running()} "
          f"is_exiting={simulation_app.is_exiting()} rclpy_ok={rclpy.ok()}",
          flush=True)
    print(f"[bridge] live: /cmd_vel in; /clock /odom /tf + 2 bluesea2 scans "
          f"out (dt={DT:.4f} s, scan tick={TICK:.3f} s)", flush=True)

    try:
        it = 0
        wall_t0 = time.monotonic()
        while not simulation_app.is_exiting() and rclpy.ok():
            it += 1
            if it == 1:
                print("[bridge] loop entered", flush=True)
            # RTX scans are only needed at TICK rate; rendering is the
            # dominant cost, so physics-only steps between ticks skip it
            # (RTF jumps from ~0.57 to >1). Sensor data is only valid after
            # a rendered step, so reads are gated the same way.
            render = sim_t + DT >= next_tick - 1e-9
            bridge.set_cmd_vel(*node.cmd)
            bridge.step(render=render)
            sim_t += DT

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
                for name in SENSORS:
                    if acc[name]["az"]:
                        az = np.concatenate(acc[name]["az"])
                        rng = np.concatenate(acc[name]["rng"])
                    else:
                        az = rng = np.array([])
                    node.pub_scan[name].publish(
                        node.scan(name, sim_t, az, rng))
                    acc[name] = {"az": [], "rng": []}
                    n_scans += 1
                next_tick += TICK
                if next_tick < sim_t:      # fell behind — don't burst
                    next_tick = sim_t + TICK

            if int(sim_t / 5.0) != int((sim_t - DT) / 5.0):
                p, _ = base.get_world_poses()
                print(f"[bridge] t={sim_t:6.1f}s cmd={node.cmd[0]:+.2f}/"
                      f"{node.cmd[1]:+.2f} pos=({p[0][0]:+.2f},{p[0][1]:+.2f}) "
                      f"scans={n_scans}", flush=True)

            # rclpy has no spin_some (rclcpp-only); spin_once with a zero
            # timeout pumps pending callbacks without blocking the sim loop.
            rclpy.spin_once(node, timeout_sec=0)

            # Pace to real time: with rendering gated to the scan tick the
            # loop runs ~10x faster than real time, which is unusable for
            # teleop and wrong for a stack that expects real-time sensors.
            lag = wall_t0 + sim_t - time.monotonic()
            if lag > 0:
                time.sleep(lag)
        print(f"[bridge] loop EXITED: is_exiting={simulation_app.is_exiting()} "
              f"rclpy_ok={rclpy.ok()} iters={it}", flush=True)
    except KeyboardInterrupt:
        pass
    except BaseException:
        import traceback
        traceback.print_exc()
        raise
    finally:
        print(f"[bridge] shutdown at t={sim_t:.1f} s, {n_scans} scans out",
              flush=True)
        node.destroy_node()
        rclpy.shutdown()
        simulation_app.close()


if __name__ == "__main__":
    main()
