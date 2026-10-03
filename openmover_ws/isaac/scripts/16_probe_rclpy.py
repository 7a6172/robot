"""Step 1.5 preflight: can Isaac's python host an rclpy node?

Isaac Sim's bundled interpreter must be able to import rclpy (Jazzy, system
python3.12 site-packages) once /opt/ros/jazzy/setup.bash has been sourced.
Checks version match, import, node create/destroy, and a pub/sub round trip.

Run: source /opt/ros/jazzy/setup.bash && \
         ~/isaacsim/python.sh openmover_ws/isaac/scripts/16_probe_rclpy.py
"""
import sys

print(f"[rclpy-probe] python {sys.version}", flush=True)

import rclpy  # noqa: E402
from rclpy.node import Node  # noqa: E402
from std_msgs.msg import String  # noqa: E402

print(f"[rclpy-probe] rclpy imported from {rclpy.__file__}", flush=True)

rclpy.init()
node = Node("isaac_rclpy_probe")
got = []
node.create_subscription(String, "isaac_probe", lambda m: got.append(m.data), 10)
pub = node.create_publisher(String, "isaac_probe", 10)

import time  # noqa: E402

end = time.time() + 5.0
pub.publish(String(data="hello"))
while time.time() < end and not got:
    rclpy.spin_once(node, timeout_sec=0.1)

print(f"[rclpy-probe] round trip: {'OK got=' + got[0] if got else 'FAILED (no echo)'}",
      flush=True)
node.destroy_node()
rclpy.shutdown()
print("[rclpy-probe] PASSED" if got else "[rclpy-probe] FAILED", flush=True)
