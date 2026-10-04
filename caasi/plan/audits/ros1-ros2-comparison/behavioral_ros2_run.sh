#!/bin/bash
# ============================================================================
# TEST 1 (cmd_vel gating / odometry / obstacle grid) - ROS 2 side
#
# Starts the ROS 2 implementation's pure nodes with the SAME parameter values
# as the ROS 1 reference run, then runs the identical probe.
#
# NO simulator, NO hardware. Deterministic message-transform comparison only.
#
# Usage:
#   behavioral_ros2_run.sh [--tree <workspace>]
#
#     --tree  ROS 2 workspace to test (default: openmover_ws)
#             openmover_ws                  -> ROS2-reference
#             caasi-workspace/openmover     -> caasi-ROS2
#
# The harness is tree-agnostic: it only requires <tree>/install/setup.bash and
# <tree>/src/openmover/config_defaults/. No test input, metric or tolerance
# depends on which tree is selected.
# ============================================================================
set -o pipefail
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

# The behavior name depends only on the workspace basename, keeping run/diagnostic
# names stable across trees (openmover_ws and caasi-workspace/openmover share the
# same package names).
echo "=== tree: $TREE ==="
source "$WS/install/setup.bash"

# The ROS 2 domain must differ between the B and C runs if they are ever active
# concurrently; callers may set ROS_DOMAIN_ID. Default keeps prior behavior.
: "${ROS_DOMAIN_ID:=0}"
export ROS_DOMAIN_ID

pkill -f simulation_handler >/dev/null 2>&1
pkill -f obstacle_handler   >/dev/null 2>&1
pkill -f static_transform   >/dev/null 2>&1
sleep 2

# Same values the ROS 1 side used, taken from the selected tree's own config.
CFG="$WS/src/openmover/config_defaults"

# static base->lidar transform, as bringup.launch.py publishes (0 0 0 0 0 0)
ros2 run tf2_ros static_transform_publisher --x 0 --y 0 --z 0 \
  --roll 0 --pitch 0 --yaw 0 --frame-id base_link --child-frame-id lidar_link \
  > /tmp/ros2_static_tf.log 2>&1 &
sleep 3

ros2 run openmover simulation_handler --ros-args \
  -p use_sim_time:=false > /tmp/ros2_sim_handler.log 2>&1 &
# Real params file (process substitution is not readable by the node).
TREE="$TREE" CFG="$CFG" python3 - <<'PY'
import os, yaml
cfg = yaml.safe_load(open(os.path.join(os.environ['CFG'], 'hardwares.yaml')))
fp = cfg['navigation_handler']['ros__parameters']['footprint']
yaml.safe_dump({'obstacle_handler': {'ros__parameters': {'footprint': fp}}},
               open('/tmp/ros2_obstacle_params.yaml', 'w'))
print('footprint written:', fp)
PY
ros2 run openmover obstacle_handler --ros-args \
  -p use_sim_time:=false \
  -p obstacle.laser_min_dist:=0.23 \
  -p obstacle.laser_max_dist:=10.0 \
  -p obstacle.obs_min_dist:=0.02 \
  -p obstacle.obstacle_grid_number:=5 \
  -p obstacle.ray_reversed:=false \
  --params-file /tmp/ros2_obstacle_params.yaml > /tmp/ros2_obs_handler.log 2>&1 &
sleep 8

echo "=== ROS 2 nodes up ==="
ros2 node list 2>/dev/null | sort

echo
echo "=== running behavioral probe ==="
python3 /home/zar/Documents/phd/robot/caasi/plan/audits/ros1-ros2-comparison/behavioral_ros2.py
