#!/bin/bash
# Capture ROS 1 RAW (non-recursive) message definitions live, so nested types
# are not expanded and the comparison against ROS 2 .msg sources is like-for-like.
export DISABLE_ROS1_EOL_WARNINGS=1
source /opt/ros/noetic/setup.bash
source /root/openmover_robot/cartographer_ws/install_isolated/setup.bash
source /root/openmover_robot/openmover_ws/devel/setup.bash

python3 - <<'PY'
import json, subprocess

reg = [l.strip() for l in subprocess.run(["rosmsg","list"],capture_output=True,text=True).stdout.splitlines()
       if l.strip().startswith("openmover_msgs/")]

defs = {}
for t in reg:
    # -r = raw/non-recursive: top-level field declarations only
    r = subprocess.run(["rosmsg","show","-r",t], capture_output=True, text=True)
    defs[t] = r.stdout.strip()
print("RAW_MSGS=" + json.dumps(defs))
PY
