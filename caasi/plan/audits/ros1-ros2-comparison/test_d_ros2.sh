#!/bin/bash
# TEST D (ROS 2): robot_state_publisher with the SAME URDF and joint state as ROS 1.
# The URDF is supplied through a YAML params file because passing XML with
# comment headers through --ros-args CLI parsing is unreliable.
source /opt/ros/jazzy/setup.bash
source /home/zar/Documents/phd/robot/openmover_ws/install/setup.bash

pkill -f robot_state_publisher >/dev/null 2>&1
pkill -f simulation_handler >/dev/null 2>&1
pkill -f obstacle_handler >/dev/null 2>&1
pkill -f static_transform >/dev/null 2>&1
pkill -f tf_probe >/dev/null 2>&1
sleep 2

URDF=/home/zar/Documents/phd/robot/openmover_ws/src/openmover/urdf/robot_description.urdf
python3 - <<PY
import yaml
urdf = open("$URDF").read()
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
echo "=== TEST D kinematics (ROS 2) ==="
python3 /tmp/tf_probe.py ros2
