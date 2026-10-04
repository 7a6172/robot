#!/bin/bash
# TEST 4 (TF / forward kinematics) - ROS 2 side
#
# robot_state_publisher with the SAME URDF and joint state as the ROS 1
# reference. The URDF is supplied through a YAML params file because passing XML
# with comment headers through --ros-args CLI parsing is unreliable.
#
# Usage:
#   test_d_ros2.sh [--tree <workspace>]
#
#     --tree  ROS 2 workspace to test (default: openmover_ws)
#
# The harness is tree-agnostic: it only requires <tree>/install/setup.bash and
# <tree>/src/openmover/urdf/robot_description.urdf.
source /opt/ros/jazzy/setup.bash

TREE="openmover_ws"
while [ $# -gt 0 ]; do
  case "$1" in
    --tree) TREE="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

ROOT=/home/zar/Documents/phd/robot
WS="$ROOT/$TREE"
if [ ! -f "$WS/install/setup.bash" ]; then
  echo "ERROR: no ROS 2 install at $WS/install/setup.bash" >&2
  exit 1
fi

echo "=== tree: $TREE ==="
source "$WS/install/setup.bash"

pkill -f robot_state_publisher >/dev/null 2>&1
pkill -f simulation_handler >/dev/null 2>&1
pkill -f obstacle_handler >/dev/null 2>&1
pkill -f static_transform >/dev/null 2>&1
pkill -f tf_probe >/dev/null 2>&1
sleep 2

URDF="$WS/src/openmover/urdf/robot_description.urdf"
URDF="$URDF" python3 - <<'PY'
import os, yaml
urdf = open(os.environ['URDF']).read()
yaml.safe_dump({"robot_state_publisher": {"ros__parameters": {
    "robot_description": urdf, "use_sim_time": False}}},
    open("/tmp/ros2_rsp_params.yaml", "w"))
print("params file written; urdf chars:", len(urdf))
PY

ros2 run robot_state_publisher robot_state_publisher --ros-args \
  --params-file /tmp/ros2_rsp_params.yaml > /tmp/ros2_rsp.log 2>&1 &
sleep 6

echo "=== ros2_rsp log ==="; tail -4 /tmp/ros2_rsp.log
echo "=== /tf present? ==="
timeout 8 ros2 topic list 2>/dev/null | grep -E "^/tf"

echo
echo "=== TEST D kinematics (ROS 2, tree=$TREE) ==="
python3 /home/zar/Documents/phd/robot/caasi/plan/audits/ros1-ros2-comparison/tf_probe.py ros2
