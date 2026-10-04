#!/bin/bash
# Build and run the ROS 2 planner A/B harness.
#
# The harness links against the OBJECTS the workspace already built
# (libglobal_planner_deps.a, libmath_utils.a) using the EXACT compile flags and
# link line CMake recorded for the shipping nodes. This guarantees the harness
# exercises the same compiled planner as the real build, with no modification to
# any source file.
source /opt/ros/jazzy/setup.bash
source /home/zar/Documents/phd/robot/openmover_ws/install/setup.bash

B=/home/zar/Documents/phd/robot/openmover_ws/build/openmover
FLAGS_MAKE=$B/CMakeFiles/global_planner_deps.dir/flags.make

CXX_FLAGS=$(grep -m1 '^CXX_FLAGS = ' "$FLAGS_MAKE" | cut -d= -f2-)
CXX_DEFINES=$(grep -m1 '^CXX_DEFINES = ' "$FLAGS_MAKE" | cut -d= -f2-)
CXX_INCLUDES=$(grep -m1 '^CXX_INCLUDES = ' "$FLAGS_MAKE" | cut -d= -f2-)

echo "=== compiling harness object ==="
g++ $CXX_FLAGS $CXX_DEFINES $CXX_INCLUDES -c -o /tmp/planner_ab_ros2.o /tmp/planner_ab_ros2.cpp 2>&1 | tail -8
echo "compile rc=$?"

# Stale absolute path in the recorded link line: the workspace was linked against
# libfastcdr.so.2.2.5 but the installed version is 2.2.8. Provide the old name in
# a local shim directory (no system modification).
mkdir -p /tmp/fastcdr_shim
ln -sf /opt/ros/jazzy/lib/libfastcdr.so.2.2.8 /tmp/fastcdr_shim/libfastcdr.so.2.2.5

LINK=$(cat $B/CMakeFiles/navigation_handler.dir/link.txt | sed 's|/opt/ros/jazzy/lib/libfastcdr.so.2.2.5|/tmp/fastcdr_shim/libfastcdr.so.2.2.5|g')
# strip the compiler, the original object, and the original output name
ARGS=$(echo "$LINK" | sed -E 's|^/usr/bin/c\+\+||; s|[^ ]*/navigation_handler\.cpp\.o||; s|-o navigation_handler||')

echo "=== linking ==="
cd $B || exit 1
/usr/bin/c++ -O3 -DNDEBUG /tmp/planner_ab_ros2.o -o /tmp/planner_ab_ros2 $ARGS 2>&1 | tail -10
echo "link rc=$?"

if [ -x /tmp/planner_ab_ros2 ]; then
  echo "=== RUN ==="
  /tmp/planner_ab_ros2 2>&1 | grep -vE "^\[" | head -30
fi
