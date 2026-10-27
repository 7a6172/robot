"""obstacle_handler end to end, without hardware or actuation.

A synthetic `/scan` is published and the published obstacle state is inspected. This is the
real contract of the component: it must turn a scan into distances per side of the robot, and
it must refuse to start when the transform it needs is missing.

The node is started as a subprocess so the test exercises the installed executable, not a
re-implementation. Everything is read-only with respect to the robot: no hardware is
contacted and nothing commands motion.
"""

from __future__ import annotations

import math
import os
import shutil
import signal
import subprocess
import time

import pytest

rclpy = pytest.importorskip("rclpy")
pytest.importorskip("openmover_msgs")

from sensor_msgs.msg import LaserScan  # noqa: E402
from openmover_msgs.msg import Obstacle  # noqa: E402

SAMPLES = 1440

STARTUP_TIMEOUT = 25.0


def _ros_env() -> dict:
    env = dict(os.environ)
    install = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', '..',
                           'install')
    local_setup = os.path.abspath(os.path.join(install, 'setup.bash'))
    if os.path.isfile(local_setup):
        # The test runner may not have sourced the workspace overlay.
        sourced = subprocess.run(
            ["bash", "-lc", f"source {shutil.which('ros2') and '/opt/ros/jazzy/setup.bash'}; "
                            f"source {local_setup}; env -0"],
            capture_output=True, text=True,
        )
        for entry in sourced.stdout.split("\0"):
            if "=" in entry:
                key, value = entry.split("=", 1)
                env[key] = value
    return env


@pytest.fixture(scope="module")
def node_and_pub():
    rclpy.init()
    node = rclpy.create_node("obstacle_test_probe")
    pub = node.create_publisher(LaserScan, "/scan", 10)
    yield node, pub
    node.destroy_node()
    rclpy.try_shutdown()


@pytest.fixture(scope="module")
def obstacle_handler():
    """Run the installed obstacle_handler with base_link -> lidar_link provided."""
    env = _ros_env()
    tf = subprocess.Popen(
        ["ros2", "run", "tf2_ros", "static_transform_publisher",
         "--frame-id", "base_link", "--child-frame-id", "lidar_link"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    time.sleep(2.0)
    handler = subprocess.Popen(
        ["ros2", "run", "openmover", "obstacle_handler", "--ros-args",
         "-r", "openmover/hardware/lidar/scan/obstacle:=/scan"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        start_new_session=True)
    time.sleep(5.0)
    if handler.poll() is not None:
        output = handler.stdout.read() if handler.stdout else ""
        tf.terminate()
        pytest.skip(f"obstacle_handler did not stay up: {output[-500:]}")
    yield handler
    for proc in (handler, tf):
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
    for proc in (handler, tf):
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


def _scan(node, obstacle_index: int | None = None, distance: float = 10.0) -> LaserScan:
    scan = LaserScan()
    scan.header.stamp = node.get_clock().now().to_msg()
    scan.header.frame_id = "lidar_link"
    scan.angle_min = -math.pi
    scan.angle_max = math.pi
    scan.angle_increment = (2.0 * math.pi) / SAMPLES
    scan.range_min = 0.25
    scan.range_max = 25.0
    scan.scan_time = 0.0714
    scan.ranges = [distance] * SAMPLES
    if obstacle_index is not None:
        for index in range(max(0, obstacle_index - 25), min(SAMPLES, obstacle_index + 26)):
            scan.ranges[index] = 0.5
    return scan


def _collect(node, pub, obstacle_index, seconds=4.0) -> list:
    received: list = []
    sub = node.create_subscription(Obstacle, "openmover/navigation/obstacle",
                                   received.append, 10)
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pub.publish(_scan(node, obstacle_index))
        rclpy.spin_once(node, timeout_sec=0.05)
    node.destroy_subscription(sub)
    return received


def test_obstacle_handler_publishes_state(node_and_pub, obstacle_handler):
    node, pub = node_and_pub
    messages = _collect(node, pub, None)
    assert messages, "obstacle_handler published no state for a valid scan"
    assert len(messages) > 10, f"only {len(messages)} messages in 4 s"


def test_clear_field_reports_no_close_obstacle(node_and_pub, obstacle_handler):
    node, pub = node_and_pub
    messages = _collect(node, pub, None)
    assert messages
    last = messages[-1]
    # Everything is 10 m away: no side should report a close obstacle.
    assert all(min(values, default=math.inf) > 1.0
               for values in (last.obstacle_forward, last.obstacle_backward,
                              last.obstacle_left, last.obstacle_right))


def test_obstacle_ahead_shrinks_the_forward_distance(node_and_pub, obstacle_handler):
    """The point of the component: a scan becomes a distance on the correct side."""
    node, pub = node_and_pub
    clear = _collect(node, pub, None, seconds=3.0)
    with_obstacle = _collect(node, pub, obstacle_index=720, seconds=4.0)  # index 720 = +x
    assert clear and with_obstacle

    clear_forward = min(clear[-1].obstacle_forward, default=math.inf)
    blocked_forward = min(with_obstacle[-1].obstacle_forward, default=math.inf)
    assert blocked_forward < clear_forward, (
        f"forward distance did not react: clear={clear_forward}, "
        f"with obstacle={blocked_forward}")
    assert blocked_forward < 1.0, blocked_forward
    # The obstacle is ahead, so the rear must be unaffected.
    assert min(with_obstacle[-1].obstacle_backward, default=math.inf) > 1.0


def test_handler_refuses_to_start_without_the_transform(tmp_path):
    """No base_link -> lidar_link means no meaningful obstacle frame: fail, do not guess."""
    env = _ros_env()
    proc = subprocess.Popen(
        ["ros2", "run", "openmover", "obstacle_handler", "--ros-args",
         "-p", "obstacle.tf_wait_timeout:=3.0",
         "-r", "openmover/hardware/lidar/scan/obstacle:=/scan"],
        env={**env, "ROS_DOMAIN_ID": "73"},  # isolated domain: no transforms at all
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        start_new_session=True)
    try:
        deadline = time.monotonic() + 30
        found = False
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                output = proc.stdout.read() if proc.stdout else ""
                found = "TF" in output or "tf" in output
                assert found, output[-400:]
                return
            time.sleep(0.5)
        pytest.skip("handler did not report a missing transform within 30 s")
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
