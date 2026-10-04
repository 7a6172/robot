#!/bin/bash
# Start a MINIMAL ROS 2 demo runtime on the remote target.
#
# Deliberately NOT OpenMover: E2 proves remote observability of a ROS 2 runtime,
# and the standard demo nodes provide valid evidence with far less complexity.
# (OpenMover can be used afterwards as an additional integration validation, but
# it is not required to prove the capability.)
#
# Runs, detached, in a dedicated ROS_DOMAIN_ID:
#   - demo_nodes_cpp talker   -> /chatter publisher
#   - demo_nodes_cpp listener -> /chatter subscriber
#   - add_two_ints_server     -> a service
set +u   # ROS setup.bash reads unset vars; do not use set -u
DOMAIN=42
LOG=/tmp/caasi_e2_demo
mkdir -p "$LOG"

# Clean any previous instance so repeated runs are deterministic.
pkill -f "demo_nodes_cpp talker"   >/dev/null 2>&1
pkill -f "demo_nodes_cpp listener" >/dev/null 2>&1
pkill -f add_two_ints_server       >/dev/null 2>&1
sleep 1

start() {
  local name="$1"; shift
  ROS_DOMAIN_ID=$DOMAIN setsid nohup "$@" > "$LOG/$name.log" 2>&1 < /dev/null &
  echo "  started $name (pid $!)"
}

source /opt/ros/jazzy/setup.bash
start talker   ros2 run demo_nodes_cpp talker
start listener ros2 run demo_nodes_cpp listener
start adder    ros2 run demo_nodes_cpp add_two_ints_server

sleep 5
echo
echo "=== running demo processes (PID PPID CMD) ==="
ps -o pid,ppid,cmd -C talker,listener,add_two_ints_server 2>/dev/null | sed 's/^/  /' || \
  pgrep -af "demo_nodes_cpp|add_two_ints_server" | sed 's/^/  /'

echo
echo "=== nodes visible on the target (ROS_DOMAIN_ID=$DOMAIN) ==="
ROS_DOMAIN_ID=$DOMAIN timeout 15 ros2 node list 2>/dev/null | sed 's/^/  /'
echo "=== topics visible on the target ==="
ROS_DOMAIN_ID=$DOMAIN timeout 15 ros2 topic list 2>/dev/null | sed 's/^/  /'
echo "=== services visible on the target ==="
ROS_DOMAIN_ID=$DOMAIN timeout 15 ros2 service list 2>/dev/null | sed 's/^/  /'
