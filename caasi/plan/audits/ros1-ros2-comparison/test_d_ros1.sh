#!/bin/bash
# TEST D (ROS 1): robot_state_publisher forward kinematics + TF edge enumeration.
export DISABLE_ROS1_EOL_WARNINGS=1
source /opt/ros/noetic/setup.bash
source /root/openmover_robot/cartographer_ws/install_isolated/setup.bash
source /root/openmover_robot/openmover_ws/devel/setup.bash

pkill -f roscore >/dev/null 2>&1; pkill -f robot_state_publisher >/dev/null 2>&1
pkill -f simulation_handler >/dev/null 2>&1; pkill -f obstacle_handler >/dev/null 2>&1
pkill -f static_transform >/dev/null 2>&1
sleep 2
roscore > /tmp/roscore.log 2>&1 &
sleep 5

# Load the URDF exactly as bringup.launch does.
python3 - <<'PY'
import rospy
rospy.init_node('urdf_loader', anonymous=True, disable_signals=True)
rospy.set_param('/robot_description',
                open('/root/openmover_robot/openmover_ws/src/openmover/urdf/robot_description.urdf').read())
print("robot_description chars:", len(rospy.get_param('/robot_description')))
PY

rosrun robot_state_publisher robot_state_publisher > /tmp/rsp.log 2>&1 &
sleep 5

echo "=== TF edges published (ROS 1) ==="
python3 - <<'PY'
import rospy, json, tf2_ros
rospy.init_node('edge_probe', anonymous=True, disable_signals=True)
buf = tf2_ros.Buffer(); lis = tf2_ros.TransformListener(buf)
rospy.sleep(2.0)
# robot_state_publisher populates the buffer from /tf_static
frames = buf.all_frames_as_yaml()
import yaml
d = yaml.safe_load(frames)
edges = sorted(f"{k}" for k in d.keys())
print("FRAMES=" + json.dumps(edges))
PY

echo
echo "=== TEST D kinematics (ROS 1) ==="
python3 /root/tf_probe.py ros1
