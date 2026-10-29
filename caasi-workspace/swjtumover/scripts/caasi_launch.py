#!/usr/bin/env python3
"""Run one swjtumover entry point as a caasi run.

Every command the ROS 1 workflow used from a shell becomes a tracked, monitorable caasi run:

    caasi run start experiments/bringup.yaml       -t swjtumover05
    caasi run start experiments/slam.yaml          -t swjtumover05
    caasi run start experiments/navigation.yaml    -t swjtumover05
    caasi run start experiments/mission.yaml       -t swjtumover05
    caasi run start experiments/line_follower.yaml -t swjtumover05
    caasi run start experiments/obstacle_guard.yaml -t swjtumover05
    caasi run start experiments/teleop.yaml        -t swjtumover05
    caasi run start experiments/rviz.yaml          -t swjtumover05

`caasi run status|logs|attach|stop <run>` then covers the whole lifecycle, which is what the ROS 1
shell history could not do -- those commands were untracked terminal sessions.

The launcher `exec`s, so signals reach ROS 2 directly: `caasi run stop` stops the robot the same
way Ctrl-C would, and the motor node's watchdog zeroes the wheels regardless.

Usage:
    caasi_launch.py launch <launch_file> [ros2 launch args...]
    caasi_launch.py run <executable> [--ros-args ...]
    caasi_launch.py cmd  <any command...>          # e.g. cmd rviz2 -d <config>
"""

from __future__ import annotations

import os
import pathlib
import sys

ROS_SETUP = "/opt/ros/jazzy/setup.bash"
PACKAGE = "swjtumover_bringup"


def build_argv(argv: list[str]) -> list[str]:
    if not argv:
        raise SystemExit(__doc__)
    mode, rest = argv[0], argv[1:]
    if mode == "launch":
        if not rest:
            raise SystemExit("launch needs a launch file name")
        return ["ros2", "launch", PACKAGE, *rest]
    if mode == "run":
        if not rest:
            raise SystemExit("run needs an executable name")
        return ["ros2", "run", PACKAGE, *rest]
    if mode == "cmd":
        if not rest:
            raise SystemExit("cmd needs a command")
        return rest
    raise SystemExit(f"unknown mode {mode!r}: expected launch, run or cmd")


def main(argv: list[str]) -> int:
    command = build_argv(argv)
    mode = argv[0]
    project = pathlib.Path(__file__).resolve().parent.parent
    overlay = project / "install" / "setup.bash"
    # Source the ROS environment here rather than relying on the caller's shell: a caasi run
    # starts from a clean environment, and silently running without ROS would look like a node
    # crash. `set -e` makes a broken setup script fail loudly instead of continuing half-configured.
    #
    # `cmd` is the exception: it runs an arbitrary command, and provisioning is the one command whose
    # job is to install ROS 2 in the first place -- it must be runnable on a machine that has none.
    # For `cmd` the source is therefore best-effort; for `launch` and `run` it stays mandatory.
    lines = ["set -e"]
    if mode == "cmd":
        lines.append(f"if [ -f {ROS_SETUP} ]; then source {ROS_SETUP}; fi")
    else:
        lines.append(f"source {ROS_SETUP}")
    if overlay.is_file():
        lines.append(f"source {overlay}")
    lines.append('exec "$@"')
    os.execvp("bash", ["bash", "-c", "; ".join(lines), "caasi_launch", *command])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
