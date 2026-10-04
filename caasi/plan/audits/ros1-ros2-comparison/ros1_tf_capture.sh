#!/bin/bash
# Capture LIVE ROS 1 TF topology and URDF-derived kinematic facts.
# This is the machine-readable behavioral artifact for the ROS1 <-> ROS2 comparison.
export DISABLE_ROS1_EOL_WARNINGS=1
source /opt/ros/noetic/setup.bash
source /root/openmover_robot/cartographer_ws/install_isolated/setup.bash
source /root/openmover_robot/openmover_ws/devel/setup.bash

python3 - <<'PY'
import rospy, json, math
rospy.init_node('tf_capture', anonymous=True, disable_signals=True)
import tf2_ros
from sensor_msgs.msg import JointState

joint_positions = {}
def js_cb(msg):
    for i, n in enumerate(msg.name):
        joint_positions[n] = msg.position[i] if i < len(msg.position) else None

sub = rospy.Subscriber('/joint_states', JointState, js_cb)

# Publish a joint state so the wheel TFs are actually broadcast.
pub = rospy.Publisher('/joint_states', JointState, queue_size=10)
rospy.sleep(1.0)
msg = JointState()
msg.header.stamp = rospy.Time.now()
msg.name = ['wheel_left_joint', 'wheel_right_joint']
msg.position = [0.0, 0.0]
pub.publish(msg)

buf = tf2_ros.Buffer()
lis = tf2_ros.TransformListener(buf)
rospy.sleep(2.0)

# Read the kinematic tree from the URDF param (authoritative structure).
import xml.etree.ElementTree as ET
urdf = rospy.get_param('/robot_description')
root = ET.fromstring(urdf)
links = [e.get('name') for e in root.findall('link')]
joints = []
for j in root.findall('joint'):
    o = j.find('origin')
    ax = j.find('axis')
    lim = j.find('limit')
    joints.append({
        'name': j.get('name'),
        'type': j.get('type'),
        'parent': j.find('parent').get('link') if j.find('parent') is not None else None,
        'child': j.find('child').get('link') if j.find('child') is not None else None,
        'origin_xyz': o.get('xyz') if o is not None else None,
        'axis': ax.get('xyz') if ax is not None else None,
        'limit': dict(lim.attrib) if lim is not None else None,
    })

out = {
    'source': 'live ROS 1 noetic container, robot_description param',
    'urdf_chars': len(urdf),
    'links': sorted(links),
    'joints': sorted(joints, key=lambda x: x['name']),
}
print(json.dumps(out, indent=2))
PY
