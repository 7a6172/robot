#!/bin/bash
# Stop the E2 demo ROS 2 runtime on the target and report what remains.
# Provided so the demonstration environment is reproducible and removable.
DOMAIN=${ROS_DOMAIN_ID:-42}

echo "=== stopping demo runtime on $(hostname) ==="
# `ros2 run` launches a wrapper plus the real binary, so both must be signalled.
# `pkill -f` alone leaves the binaries, as observed during E2 validation.
for pat in "demo_nodes_cpp talker" "demo_nodes_cpp listener" "add_two_ints_server"; do
  pkill -f "$pat" >/dev/null 2>&1 && echo "  signalled wrapper: $pat" || true
done
for exe in talker listener add_two_ints_server; do
  pkill -x "$exe" >/dev/null 2>&1 && echo "  signalled binary:  $exe" || true
done
sleep 3

echo
echo "=== remaining demo processes (expect none) ==="
pgrep -af "demo_nodes_cpp|add_two_ints_server" | grep -v pgrep | sed 's/^/  /' || echo "  (none)"
echo
echo "=== graph now visible on the target (expect empty) ==="
source /opt/ros/jazzy/setup.bash 2>/dev/null
ROS_DOMAIN_ID=$DOMAIN timeout 12 ros2 node list 2>/dev/null | sed 's/^/  /' || true
echo "  (end)"
rm -rf /tmp/caasi_e2_demo
echo
echo "demo logs removed."
