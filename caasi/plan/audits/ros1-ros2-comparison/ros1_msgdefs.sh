#!/bin/bash
# Capture ROS 1 message/service definitions STRUCTURALLY (field names + types)
# via live ROS 1 introspection, for A/B comparison with the ROS 2 port.
export DISABLE_ROS1_EOL_WARNINGS=1
source /opt/ros/noetic/setup.bash
source /root/openmover_robot/cartographer_ws/install_isolated/setup.bash
source /root/openmover_robot/openmover_ws/devel/setup.bash

python3 - <<'PY'
import json, subprocess

# Use `rosmsg`/`rossrv` text output for definitions (authoritative generated form).
msgs = ["bms_data","flow_state","motor_state","nav_to_simple","nav_to_state",
        "obstacle","pose","twist"]
srvs = ["cmd_vel_mode_request","playsound_request","stop_request","direct_request",
        "flow_action","flow_cmd","self_test_report_request","work_mode_request",
        "nav_to_request","nav_to_simple_request"]

# Discover actual registered type names (ROS 1 nests srv in subdirs).
def list_types(cmd):
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    return [l.strip() for l in out.splitlines() if l.strip().startswith("openmover_msgs/")]

reg_msgs = list_types(["rosmsg", "list"])
reg_srvs = list_types(["rossrv", "list"])
print("REGISTERED_MSGS=" + json.dumps(sorted(reg_msgs)))
print("REGISTERED_SRVS=" + json.dumps(sorted(reg_srvs)))

def show(kind, t):
    r = subprocess.run([kind, "show", t], capture_output=True, text=True)
    return r.stdout.strip()

defs = {}
for t in reg_msgs:
    defs[t] = show("rosmsg", t)
for t in reg_srvs:
    defs[t] = show("rossrv", t)
print("DEFINITIONS=" + json.dumps(defs))
PY
