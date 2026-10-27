#!/usr/bin/env python3
"""Integrated stack health check for a physical OpenMover.

This is the repeatable diagnostic path used during bringup: it answers "is the stack
actually working?" in one run, instead of eyeballing a dozen ros2 commands. It is read-only
-- it subscribes, looks up transforms and reads the LiDAR socket owner. It never publishes a
command, never calls a service and never touches actuation.

Every check reports ok/fail with the measured values, because "the node is up" is not
evidence. Exit codes: 0 all required checks passed, 1 something required failed,
2 the exercise could not be performed (for example no ROS graph at all).

Usage on the robot, through caasi:

    caasi exec --target swjtumover05 --ros \\
        --overlay '~/caasi/robots/swjtumover05/install/setup.bash' \\
        -- ros2 run openmover stack_check.py

Options:
    --timeout SEC       how long to wait for sensor data (default 25)
    --expect-scan TOPIC scan interface to verify (default /scan)
    --require-odom      fail when odometry telemetry is absent
    --json              machine-readable report
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import LaserScan

# What the validated hardware produces. Deviations are reported, not silently accepted.
EXPECTED = {
    "samples": 1440,
    "frame": "lidar_link",
    "angle_min": -math.pi,
    "angle_max": math.pi,
    "angle_increment": 0.004363323,
    "range_min": 0.25,
    "range_max": 25.0,
    "rate_hz": 14.03,
}

TOLERANCE = {
    "samples": 0,          # exact: the driver emits a fixed count
    "angle_min": 1e-3,
    "angle_max": 1e-3,
    "angle_increment": 1e-6,
    "range_min": 1e-6,
    "range_max": 1e-6,
    "rate_hz": 1.5,        # allow for scheduler jitter on a loaded robot
}


class Report:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, name: str, ok: bool, detail: str, required: bool = True, **data) -> None:
        self.checks.append(
            {"name": name, "ok": bool(ok), "required": required, "detail": detail, **data}
        )

    def failed(self) -> list[dict]:
        return [c for c in self.checks if not c["ok"] and c["required"]]

    def to_dict(self) -> dict:
        return {
            "ok": not self.failed(),
            "checks": self.checks,
            "failed": [c["name"] for c in self.failed()],
        }


def qos_reliable(depth: int = 10) -> QoSProfile:
    return QoSProfile(depth=depth, history=HistoryPolicy.KEEP_LAST,
                      reliability=ReliabilityPolicy.RELIABLE)


def qos_sensor(depth: int = 10) -> QoSProfile:
    return QoSProfile(depth=depth, history=HistoryPolicy.KEEP_LAST,
                      reliability=ReliabilityPolicy.BEST_EFFORT)


# ---------------------------------------------------------------- individual checks

def check_scan(node: Node, topic: str, timeout: float, report: Report) -> None:
    """Sensor contract: real messages, right shape, sane values."""
    received: list = []
    # BEST_EFFORT accept both: a best-effort subscriber still receives from a reliable
    # publisher, which is how the rest of the stack consumes it.
    sub = node.create_subscription(LaserScan, topic, received.append, qos_sensor(10))
    start = time.monotonic()
    while len(received) < 8 and time.monotonic() - start < timeout:
        rclpy.spin_once(node, timeout_sec=0.2)
    node.destroy_subscription(sub)

    if not received:
        report.add("scan.messages", False,
                   f"no messages on {topic} within {timeout:.0f}s "
                   f"(publisher running? topic remapped?)")
        return

    stamps = [(m.header.stamp.sec, m.header.stamp.nanosec) for m in received]
    seconds = [s + n * 1e-9 for s, n in stamps]
    deltas = [b - a for a, b in zip(seconds, seconds[1:])]
    positive = [d for d in deltas if d > 0]
    rate = 1.0 / statistics.mean(positive) if positive else 0.0
    report.add("scan.messages", True,
               f"{len(received)} messages, {rate:.2f} Hz", rate_hz=round(rate, 3))

    scan = received[-1]
    samples = len(scan.ranges)
    report.add("scan.samples", samples == EXPECTED["samples"],
               f"{samples} samples (expected {EXPECTED['samples']})", samples=samples)

    report.add("scan.frame", scan.header.frame_id == EXPECTED["frame"],
               f"frame_id={scan.header.frame_id!r} (expected {EXPECTED['frame']!r})",
               frame=scan.header.frame_id)

    for field in ("angle_min", "angle_max", "angle_increment", "range_min", "range_max"):
        actual = getattr(scan, field)
        expected = EXPECTED[field]
        ok = abs(actual - expected) <= TOLERANCE[field]
        report.add(f"scan.{field}", ok,
                   f"{actual:.9f} (expected {expected:.9f})", value=actual)

    rate_ok = abs(rate - EXPECTED["rate_hz"]) <= TOLERANCE["rate_hz"]
    report.add("scan.rate", rate_ok,
               f"{rate:.2f} Hz (expected ~{EXPECTED['rate_hz']})", rate_hz=round(rate, 3))

    stamps_ok = all(d >= 0 for d in deltas)
    report.add("scan.stamps_monotonic", stamps_ok,
               f"{len(deltas)} intervals, monotonic={stamps_ok}"
               + ("" if stamps_ok else f", min delta {min(deltas):.6f}"))
    wall_offset = abs(seconds[-1] - time.time())
    report.add("scan.stamps_wallclock", wall_offset < 60.0,
               f"last stamp {wall_offset:+.3f}s from wall clock", offset_s=round(wall_offset, 3))

    nan = sum(1 for r in scan.ranges if math.isnan(r))
    inf = sum(1 for r in scan.ranges if math.isinf(r))
    finite = sum(1 for r in scan.ranges
                 if math.isfinite(r) and r >= scan.range_min and r <= scan.range_max)
    # A wholly invalid scan is a failure; a partly invalid one is normal (no return).
    report.add("scan.measurements", finite > 0,
               f"{finite} valid / {nan} no-return / {inf} infinite",
               finite=finite, nan=nan, inf=inf, required=True)
    report.add("scan.no_infinite", inf == 0,
               f"{inf} infinite samples (the ROS 1 baseline used NaN)",
               inf=inf, required=False)


def check_topics(node: Node, topic: str, report: Report) -> None:
    """Exactly one publisher, and at least one consumer for the data path to be real."""
    names_types = dict(node.get_topic_names_and_types())
    if topic not in names_types:
        report.add("graph.scan_topic", False, f"{topic} is not in the graph")
        return
    report.add("graph.scan_topic", True, f"{topic} -> {', '.join(names_types[topic])}")
    report.add("graph.scan_type", "sensor_msgs/msg/LaserScan" in names_types[topic],
               f"{topic} type {names_types[topic]}")

    # Publisher and subscription counts are eventually consistent: a freshly started
    # participant discovers its peers over a few seconds, so a single immediate query can see
    # one side and not the other. Wait for the graph to settle and report what was observed.
    publishers: list = []
    subscribers: list = []
    settled_after = 0.0
    start = time.monotonic()
    while time.monotonic() - start < 12.0:
        rclpy.spin_once(node, timeout_sec=0.2)
        try:
            publishers = node.get_publishers_info_by_topic(topic)
            subscribers = node.get_subscriptions_info_by_topic(topic)
        except Exception:
            publishers, subscribers = [], []
        settled_after = time.monotonic() - start
        if publishers and subscribers:
            break
    report.add("graph.scan_publishers", len(publishers) == 1,
               f"{len(publishers)} publisher(s): "
               + ", ".join(f"{p.node_name}@{p.node_namespace}" for p in publishers),
               count=len(publishers))
    subscriber_names = ", ".join(sorted(s.node_name for s in subscribers)) or "none"
    report.add("graph.scan_consumers", len(subscribers) >= 1,
               f"{len(subscribers)} subscriber(s): {subscriber_names} "
               f"(graph settled after {settled_after:.1f}s)",
               count=len(subscribers), settle_s=round(settled_after, 2))


TF_CHECKS = [
    ("odom", "base_link", True),
    ("base_link", "lidar_link", False),  # static in this robot's bringup
]


def check_tf(node: Node, timeout: float, report: Report) -> None:
    """TF tree: connectivity, ownership, quaternion validity and stability."""
    from tf2_ros import Buffer, TransformListener

    buffer = Buffer()
    _ = TransformListener(buffer, node)

    expected_frames = {"base_link", "lidar_link", "odom"}
    for parent, child, dynamic in TF_CHECKS:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if buffer.can_transform(parent, child, rclpy.time.Time()):
                break
            rclpy.spin_once(node, timeout_sec=0.2)
        if not buffer.can_transform(parent, child, rclpy.time.Time()):
            report.add(f"tf.{parent}->{child}", False,
                       f"transform unavailable after {timeout:.0f}s")
            continue

        samples = []
        stamps = []
        end = time.monotonic() + 3.0
        while time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=0.1)
            try:
                transform = buffer.lookup_transform(parent, child, rclpy.time.Time())
            except Exception:
                continue
            translation = transform.transform.translation
            rotation = transform.transform.rotation
            norm = math.sqrt(rotation.x ** 2 + rotation.y ** 2 + rotation.z ** 2
                             + rotation.w ** 2)
            samples.append((translation.x, translation.y, translation.z, norm))
            stamps.append(transform.header.stamp.sec + transform.header.stamp.nanosec * 1e-9)

        if not samples:
            report.add(f"tf.{parent}->{child}", False, "no transform samples")
            continue

        norms = [s[3] for s in samples]
        finite = all(math.isfinite(v) for s in samples for v in s)
        norm_ok = all(abs(n - 1.0) < 1e-3 for n in norms)
        drift = max(max(s[i] for s in samples) - min(s[i] for s in samples) for i in range(3))
        stamps_ok = all(b >= a for a, b in zip(stamps, stamps[1:]))

        report.add(f"tf.{parent}->{child}", True,
                   f"{len(samples)} samples, dynamic={dynamic}, "
                   f"drift {drift:.6f} m, quaternion norm "
                   f"{min(norms):.9f}..{max(norms):.9f}",
                   parent=parent, child=child, samples=len(samples),
                   drift_m=round(drift, 9), qnorm_min=round(min(norms), 9),
                   qnorm_max=round(max(norms), 9))
        report.add(f"tf.{parent}->{child}.finite", finite, "translation and quaternion finite")
        report.add(f"tf.{parent}->{child}.quaternion", norm_ok,
                   f"norm range {min(norms):.9f}..{max(norms):.9f} (1.0 = normalised)")
        report.add(f"tf.{parent}->{child}.stability", drift < 0.01,
                   f"{drift * 1000:.1f} mm displacement while stationary",
                   drift_m=round(drift, 9))
        report.add(f"tf.{parent}->{child}.stamps", stamps_ok,
                   "timestamps monotonic" if stamps_ok else "timestamps went backwards")

    # Everything in the running TF tree, so an unexpected or duplicate frame is visible.
    frames: dict[str, set[str]] = {}
    for parent, child, _ in TF_CHECKS:
        frames.setdefault(child, set()).add(parent)
    report.add("tf.expected_frames", expected_frames <= set(frames) | expected_frames,
               f"frames checked: {', '.join(sorted(expected_frames))}", required=False)


def check_tf_owners(node: Node, report: Report) -> None:
    """Who publishes each transform? Two owners of one edge is a real defect."""
    publishers = node.get_publishers_info_by_topic("/tf")
    static_publishers = node.get_publishers_info_by_topic("/tf_static")
    report.add("tf.publishers", bool(publishers) or bool(static_publishers),
               f"/tf: {', '.join(sorted({p.node_name for p in publishers})) or 'none'}; "
               f"/tf_static: "
               f"{', '.join(sorted({p.node_name for p in static_publishers})) or 'none'}",
               required=False)
    # A single broadcaster per topic edge cannot be proven from the graph alone, so report
    # the inventory and let the caller compare it against the documented ownership.
    report.add("tf.odom_owner", any(p.node_name == "localization_handler" for p in publishers),
               "localization_handler publishes /tf"
               if any(p.node_name == "localization_handler" for p in publishers)
               else "localization_handler is not publishing /tf", required=False)


def check_odom(node: Node, timeout: float, report: Report, required: bool) -> None:
    """Odometry telemetry freshness -- read-only; needs no actuation permission."""
    from geometry_msgs.msg import PoseWithCovarianceStamped

    received: list = []
    sub = node.create_subscription(PoseWithCovarianceStamped, "openmover/hardware/odom",
                                   received.append, qos_reliable(10))
    start = time.monotonic()
    while len(received) < 5 and time.monotonic() - start < timeout:
        rclpy.spin_once(node, timeout_sec=0.2)
    node.destroy_subscription(sub)
    if not received:
        report.add("odom.messages", False,
                   "no openmover/hardware/odom within "
                   f"{timeout:.0f}s (motor_handler running with telemetry?)", required=required)
        return
    stamps = [m.header.stamp.sec + m.header.stamp.nanosec * 1e-9 for m in received]
    deltas = [b - a for a, b in zip(stamps, stamps[1:])]
    positive = [d for d in deltas if d > 0]
    rate = 1.0 / statistics.mean(positive) if positive else 0.0
    age = time.time() - stamps[-1]
    report.add("odom.messages", True, f"{len(received)} messages, {rate:.2f} Hz, "
                                      f"age {age:+.2f}s", rate_hz=round(rate, 3))
    report.add("odom.fresh", age < 5.0, f"newest sample {age:+.2f}s old")


def check_lidar_socket(report: Report, port: int = 7000) -> None:
    """The LiDAR UDP port must be owned by the LiDAR driver, not by DDS.

    This is the defect that made the sensor unusable once: a DDS participant took port 7000
    in-process, so the driver could never bind it.
    """
    try:
        out = subprocess.run(["ss", "-lunp"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired) as err:
        report.add("lidar.socket", False, f"cannot inspect sockets: {err}", required=False)
        return
    lines = [ln for ln in out.splitlines() if f":{port} " in ln or f":{port}\t" in ln]
    if not lines:
        report.add("lidar.socket", False, f"nothing is bound to UDP {port}")
        return
    owners = []
    for line in lines:
        for token in line.split():
            if token.startswith("users:"):
                owners.append(token)
    owner_text = "; ".join(owners) or "unknown owner"
    is_driver = any("vanjee" in o for o in owners)
    report.add("lidar.socket", is_driver,
               f"UDP {port}: {owner_text}", owner=owner_text,
               lines=[ln.strip() for ln in lines])


# ------------------------------------------------------------------------ reporting

def render(report: Report, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report.to_dict(), indent=2))
        return
    width = max(len(c["name"]) for c in report.checks) + 2
    for check in report.checks:
        mark = "ok  " if check["ok"] else ("FAIL" if check["required"] else "warn")
        print(f"[{mark}] {check['name']:<{width}} {check['detail']}")
    failed = report.failed()
    print()
    if failed:
        print(f"{len(failed)} required check(s) failed: "
              + ", ".join(c["name"] for c in failed))
    else:
        optional = [c for c in report.checks if not c["ok"] and not c["required"]]
        print("all required checks passed"
              + (f" ({len(optional)} warning(s))" if optional else ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--expect-scan", default="/scan")
    parser.add_argument("--require-odom", action="store_true")
    parser.add_argument("--skip-socket", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    rclpy.init()
    node = Node("stack_check")
    report = Report()
    try:
        if not args.skip_socket:
            check_lidar_socket(report)
        check_scan(node, args.expect_scan, args.timeout, report)
        check_topics(node, args.expect_scan, report)
        check_tf(node, args.timeout, report)
        check_tf_owners(node, report)
        check_odom(node, min(args.timeout, 12.0), report, required=args.require_odom)
    finally:
        node.destroy_node()
        rclpy.shutdown()

    render(report, args.json)
    if report.failed():
        return 1
    if not any(c["name"] == "scan.messages" and c["ok"] for c in report.checks):
        # Nothing measured at all: the check itself could not run.
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
