#!/usr/bin/env bash
# Keyboard teleoperation, from a terminal on the robot's own desktop.
#
#   ~/caasi/robots/swjtumover05/scripts/run_teleop.sh
#
# Arrow keys: up/down drive, left/right turn. Speeds come from config/teleop.yaml
# (0.2 m/s, 0.4 rad/s, accelerating at 0.2 / 0.4 per second).
#
# Two things that are not obvious:
#   * the robot's session is Wayland with X11 applications running through Xwayland, and the X
#     cookie is a mutter file whose name changes every session -- so it is looked up rather than
#     hard-coded;
#   * `pynput` reads X11 events, so an Xwayland window must have focus. Click the rviz window
#     first, then use the arrow keys.
# -u is deliberately not set: the ROS setup scripts reference variables they do not define
set -eo pipefail

export DISPLAY="${DISPLAY:-:0}"
if [ -z "${XAUTHORITY:-}" ] || [ ! -r "${XAUTHORITY:-/nonexistent}" ]; then
  auth="$(ps -eo args | grep -oE '\-auth [^ ]+' | head -1 | cut -d' ' -f2 || true)"
  if [ -n "${auth}" ]; then
    export XAUTHORITY="${auth}"
  fi
fi

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project="$(dirname "${here}")"

# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
if [ -f "${project}/install/setup.bash" ]; then
  # shellcheck disable=SC1091
  source "${project}/install/setup.bash"
fi

echo "teleop: DISPLAY=${DISPLAY} XAUTHORITY=${XAUTHORITY:-<unset>}"
echo "teleop: arrows = drive/turn. Click the rviz window first so Xwayland has focus."
exec ros2 run swjtumover_bringup teleop_node.py --ros-args \
  --params-file "${project}/install/swjtumover_bringup/share/swjtumover_bringup/config/teleop.yaml"
