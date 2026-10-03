"""Bridge core — simulator-side half of the Isaac <-> robot interface.

Mirrors the Gazebo diff_drive plugin contract from pioneer3dx.urdf:
    wheel_separation = 0.32 m, wheel_radius = 0.09 m, velocity servo.

API (ROS-agnostic; the ROS 2 node in Step 1.5 wraps exactly this):
    set_cmd_vel(linear_x, angular_z)   <- cmd_vel in
    step()                             <- advance physics (+ render)
    get_odom()                         -> odom/tf out

Odometry mirrors the Gazebo diff_drive plugin: twist from measured wheel
joint velocities (encoder odometry), pose from the simulator ground truth
(no integration drift — documented deviation from the plugin, strictly
better for bring-up).

Deliberately avoids mixing experimental tensor prims with the legacy
Articulation: creating a tensor physics view invalidates the legacy
simulation view (observed in Step 1.3).
"""

import numpy as np

from isaacsim.core.prims import XFormPrim
from isaacsim.core.utils.types import ArticulationActions

# From the Gazebo diff_drive plugin block in pioneer3dx.urdf
WHEEL_SEPARATION = 0.32
WHEEL_RADIUS = 0.09
WHEEL_JOINTS = ["base_left_wheel_joint", "base_right_wheel_joint"]
# Velocity-servo gain. 5.0 (Step 1.1 value) tracked straight driving at 94%
# but pivot turns only reached ~66% of target wheel speed — the servo was
# torque-starved scrubbing the casters sideways. 20.0 tracks both.
KD = 20.0


class BridgeCore:
    def __init__(self, world, robot):
        self.world = world
        self.robot = robot
        self.base = XFormPrim(robot.prim_paths[0], name="base")
        self.dof_names = list(getattr(robot, "dof_names", []) or [])
        self.wheel_idx = [self.dof_names.index(j) for j in WHEEL_JOINTS]
        robot.set_gains(kps=None, kds=[KD] * 2, joint_names=WHEEL_JOINTS)
        self.linear_x = 0.0
        self.angular_z = 0.0

    def set_cmd_vel(self, linear_x: float, angular_z: float) -> None:
        self.linear_x = float(linear_x)
        self.angular_z = float(angular_z)

    def _wheel_targets(self) -> tuple[float, float]:
        """Unicycle -> wheel kinematics (same as diff_drive plugin)."""
        left = (self.linear_x - self.angular_z * WHEEL_SEPARATION / 2.0) / WHEEL_RADIUS
        right = (self.linear_x + self.angular_z * WHEEL_SEPARATION / 2.0) / WHEEL_RADIUS
        return left, right

    def step(self, render: bool = True) -> None:
        left, right = self._wheel_targets()
        action = ArticulationActions(joint_velocities=[left, right],
                                     joint_indices=self.wheel_idx)
        self.robot.apply_action(action)
        self.world.step(render=render)

    def get_odom(self) -> dict:
        """Pose (sim ground truth) + twist (wheel encoder odometry)."""
        pos, quat = self.base.get_world_poses()
        vel = np.asarray(self.robot.get_joint_velocities(
            joint_indices=self.wheel_idx))[0]  # shape (n_prims, n_dofs)
        wl = float(vel[0])
        wr = float(vel[1])
        vx = WHEEL_RADIUS * (wr + wl) / 2.0
        wz = WHEEL_RADIUS * (wr - wl) / WHEEL_SEPARATION
        return {
            "position": np.asarray(pos[0]),
            "orientation": np.asarray(quat[0]),  # w, x, y, z
            "linear": np.array([vx, 0.0, 0.0]),
            "angular": np.array([0.0, 0.0, wz]),
        }
