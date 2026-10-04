#!/bin/bash
# Capture ROS 1 SERVICE definitions by reading the .srv sources that the ROS 1
# CMakeLists actually declares (rossrv cannot enumerate them because the
# reference declares services in nested subdirectories, which catkin's srv-root
# lookup does not traverse - see audit finding).
export DISABLE_ROS1_EOL_WARNINGS=1
source /opt/ros/noetic/setup.bash
D=/root/openmover_robot/openmover_ws/src/openmover_msgs/srv

python3 - <<'PY'
import json, pathlib
D = pathlib.Path("/root/openmover_robot/openmover_ws/src/openmover_msgs/srv")
out = {}
for f in sorted(D.rglob("*.srv")):
    rel = str(f.relative_to(D))
    out[rel] = f.read_text()
print("SRV_DEFS=" + json.dumps(out))
PY
