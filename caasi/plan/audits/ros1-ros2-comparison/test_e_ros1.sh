#!/bin/bash
# TEST E (ROS 1): laserscan_multi_merger with identical dual-scan input.
export DISABLE_ROS1_EOL_WARNINGS=1
source /opt/ros/noetic/setup.bash
source /root/openmover_robot/cartographer_ws/install_isolated/setup.bash
source /root/openmover_robot/openmover_ws/devel/setup.bash

pkill -f roscore >/dev/null 2>&1; pkill -f laserscan_multi_merger >/dev/null 2>&1
pkill -f static_transform >/dev/null 2>&1
sleep 2
roscore > /tmp/roscore.log 2>&1 &
sleep 5

# Static transforms: base_link -> both lidar frames (same geometry as the URDF).
rosrun tf2_ros static_transform_publisher 0.22015 0 0.07513 0 0 0 base_link lidar_forward_link > /tmp/stf_f.log 2>&1 &
rosrun tf2_ros static_transform_publisher -0.22015 0 0.07513 0 0 0 base_link lidar_rear_link  > /tmp/stf_r.log 2>&1 &
rosrun tf2_ros static_transform_publisher 0 0 0 0 0 0 base_link lidar_link > /tmp/stf_l.log 2>&1 &
sleep 3

rosrun ira_laser_tools laserscan_multi_merger \
  __name:=laserscan_multi_merger \
  _destination_frame:=lidar_link \
  _cloud_destination_topic:=openmover/hardware/lidar/pointcloud \
  _scan_destination_topic:=openmover/hardware/lidar/scan \
  "_laserscan_topics:=/openmover/hardware/lidar_forward/scan /openmover/hardware/lidar_rear/scan" \
  _angle_min:=-3.1415926 _angle_max:=3.1415926 _angle_increment:=0.006962 \
  _scan_time:=0.0 _range_min:=0.33 _range_max:=20.0 \
  > /tmp/ros1_merger.log 2>&1 &
sleep 6

echo "=== merger node up? ==="
rosnode list 2>&1 | grep -i merger || echo "(merger node not found)"
tail -5 /tmp/ros1_merger.log

echo
echo "=== TEST E (ROS 1) ==="
python3 /root/merger_probe.py ros1
