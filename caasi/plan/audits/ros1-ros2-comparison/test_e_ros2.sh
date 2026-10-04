#!/bin/bash
# TEST 5 (laserscan_multi_merger) - ROS 2 side
#
# Identical dual-scan input and the same static transforms and parameters as the
# ROS 1 reference run.
#
# Usage:
#   test_e_ros2.sh [--tree <workspace>]
#
#     --tree  ROS 2 workspace to test (default: openmover_ws)
#
# The harness is tree-agnostic: it only requires <tree>/install/setup.bash.
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

pkill -f laserscan_multi_merger >/dev/null 2>&1
pkill -f static_transform >/dev/null 2>&1
pkill -f robot_state_publisher >/dev/null 2>&1
pkill -f merger_probe >/dev/null 2>&1
sleep 2

ros2 run tf2_ros static_transform_publisher --x 0.22015 --y 0 --z 0.07513 \
  --roll 0 --pitch 0 --yaw 0 --frame-id base_link --child-frame-id lidar_forward_link > /tmp/r2_stf_f.log 2>&1 &
ros2 run tf2_ros static_transform_publisher --x -0.22015 --y 0 --z 0.07513 \
  --roll 0 --pitch 0 --yaw 0 --frame-id base_link --child-frame-id lidar_rear_link > /tmp/r2_stf_r.log 2>&1 &
ros2 run tf2_ros static_transform_publisher --x 0 --y 0 --z 0 \
  --roll 0 --pitch 0 --yaw 0 --frame-id base_link --child-frame-id lidar_link > /tmp/r2_stf_l.log 2>&1 &
sleep 4

ros2 run ira_laser_tools laserscan_multi_merger --ros-args \
  -r __node:=laserscan_multi_merger \
  -p destination_frame:=lidar_link \
  -p cloud_destination_topic:=openmover/hardware/lidar/pointcloud \
  -p scan_destination_topic:=openmover/hardware/lidar/scan \
  -p "laserscan_topics:=/openmover/hardware/lidar_forward/scan /openmover/hardware/lidar_rear/scan" \
  -p angle_min:=-3.1415926 -p angle_max:=3.1415926 -p angle_increment:=0.006962 \
  -p scan_time:=0.0 -p range_min:=0.33 -p range_max:=20.0 \
  > /tmp/ros2_merger.log 2>&1 &
sleep 6

echo "=== merger node up? ==="
timeout 10 ros2 node list 2>/dev/null | grep -i merger || echo "(not found)"
tail -8 /tmp/ros2_merger.log

echo
echo "=== TEST E (ROS 2, tree=$TREE) ==="
python3 /home/zar/Documents/phd/robot/caasi/plan/audits/ros1-ros2-comparison/merger_probe.py ros2
