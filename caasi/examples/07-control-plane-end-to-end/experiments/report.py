#!/usr/bin/env python3
"""The workload the chain runs. It reports where it ran and what it could import.

Small on purpose: what this example teaches is the *chain* around it -- selection,
deployment, a target-native build, remote execution, collection and provenance.
"""
import os
import socket


def main() -> None:
    host = socket.gethostname()
    distro = os.environ.get("ROS_DISTRO", "<unset>")
    try:
        import rclpy  # noqa: F401
        ros = "rclpy available"
    except ImportError:
        ros = "rclpy unavailable"
    with open("report.out", "w") as fh:
        fh.write(f"host={host} distro={distro} {ros}\n")
    print(f"[cp-demo] ran on {host} (ROS_DISTRO={distro}, {ros})", flush=True)


if __name__ == "__main__":
    main()
