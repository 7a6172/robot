#!/usr/bin/env python3
"""TEST D (shared): TF topology + forward kinematics from robot_state_publisher.

Given an identical URDF and an identical joint state, robot_state_publisher must
produce identical transforms. This is pure forward kinematics and is directly
comparable across ROS 1 / ROS 2. Run on either side; output is JSON so both can
be diffed numerically.
"""
import json
import math
import sys
import time

# Deterministic, non-zero joint configuration so the FK result is non-trivial.
JOINT_STATE = {
    "wheel_left_joint": 0.75,
    "wheel_right_joint": -0.25,
    "ball_front_left_joint": 0.1,
    "ball_rear_right_joint": -0.1,
}
FRAMES = ["wheel_left_link", "wheel_right_link", "ball_front_left_link",
          "ball_rear_right_link", "lidar_forward_link", "lidar_rear_link"]
PARENT = "base_link"

SIDE = sys.argv[1] if len(sys.argv) > 1 else "unknown"

out = {"side": SIDE, "joint_state": JOINT_STATE, "transforms": {}, "tf_edges": []}

if SIDE == "ros1":
    import rospy
    import tf2_ros
    from sensor_msgs.msg import JointState

    rospy.init_node("tf_probe", anonymous=True, disable_signals=True)
    js = JointState()
    js.name = list(JOINT_STATE.keys())
    js.position = [JOINT_STATE[k] for k in js.name]
    pub = rospy.Publisher("/joint_states", JointState, queue_size=10)
    rospy.sleep(1.0)
    out["joint_state_used"] = js.name
    pub.publish(js)

    buf = tf2_ros.Buffer()
    lis = tf2_ros.TransformListener(buf)
    rospy.sleep(2.5)
    for _ in range(20):
        js.header.stamp = rospy.Time.now()
        pub.publish(js)
        rospy.sleep(0.1)
    for f in FRAMES:
        try:
            t = buf.lookup_transform(PARENT, f, rospy.Time(0), rospy.Duration(1.0))
            out["transforms"][f] = {
                "t": [t.transform.translation.x, t.transform.translation.y,
                      t.transform.translation.z],
                "q": [t.transform.rotation.x, t.transform.rotation.y,
                      t.transform.rotation.z, t.transform.rotation.w],
            }
        except Exception as e:
            out["transforms"][f] = {"error": str(e)}

else:
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import JointState
    import tf2_ros

    rclpy.init()
    node = Node("tf_probe")
    buf = tf2_ros.Buffer()
    lis = tf2_ros.TransformListener(buf, node)
    pub = node.create_publisher(JointState, "/joint_states", 10)

    def spin(sec):
        end = time.time() + sec
        while time.time() < end:
            rclpy.spin_once(node, timeout_sec=0.05)

    js = JointState()
    js.name = list(JOINT_STATE.keys())
    js.position = [float(JOINT_STATE[k]) for k in js.name]
    spin(1.0)
    out["joint_state_used"] = js.name
    for _ in range(20):
        js.header.stamp = node.get_clock().now().to_msg()
        pub.publish(js)
        spin(0.1)
    for f in FRAMES:
        try:
            t = buf.lookup_transform(PARENT, f, rclpy.time.Time(),
                                     timeout=rclpy.duration.Duration(seconds=1.0))
            out["transforms"][f] = {
                "t": [t.transform.translation.x, t.transform.translation.y,
                      t.transform.translation.z],
                "q": [t.transform.rotation.x, t.transform.rotation.y,
                      t.transform.rotation.z, t.transform.rotation.w],
            }
        except Exception as e:
            out["transforms"][f] = {"error": str(e)}
    node.destroy_node()
    rclpy.shutdown()

out["frames_requested"] = FRAMES
out["parent_frame"] = PARENT
print("###JSON_START###")
print(json.dumps(out, indent=2, default=str))
print("###JSON_END###")
