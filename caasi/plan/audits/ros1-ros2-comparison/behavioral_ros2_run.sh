#!/bin/bash
# ============================================================================
# BEHAVIORAL TEST A/B/C (ROS 2 SIDE): start the ROS 2 port's pure nodes with
# the SAME parameter values as the ROS 1 run, then run the identical probe.
#
# NO simulator, NO hardware. Deterministic message-transform comparison only.
# ============================================================================
set -o pipefail
source /opt/ros/jazzy/setup.bash
source /home/zar/Documents/phd/robot/openmover_ws/install/setup.bash

pkill -f simulation_handler >/dev/null 2>&1
pkill -f obstacle_handler   >/dev/null 2>&1
pkill -f static_transform   >/dev/null 2>&1
sleep 2

# Same values the ROS 1 side used, taken from the project's own config files.
CFG=/home/zar/Documents/phd/robot/openmover_ws/src/openmover/config_defaults

# static base->lidar transform, as bringup.launch.py publishes (0 0 0 0 0 0)
ros2 run tf2_ros static_transform_publisher --x 0 --y 0 --z 0 \
  --roll 0 --pitch 0 --yaw 0 --frame-id base_link --child-frame-id lidar_link \
  > /tmp/ros2_static_tf.log 2>&1 &
sleep 3

ros2 run openmover simulation_handler --ros-args \
  -p use_sim_time:=false > /tmp/ros2_sim_handler.log 2>&1 &
# Real params file (process substitution is not readable by the node).
python3 - <<'PY'
import yaml
cfg = yaml.safe_load(open('/home/zar/Documents/phd/robot/openmover_ws/src/openmover/config_defaults/hardwares.yaml'))
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
python3 /tmp/ros2_behavioral.py
