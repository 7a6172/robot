#!/bin/bash
# Build and run the ROS 2 planner algorithm harness against a chosen tree.
#
# The harness links against the OBJECTS the workspace already built
# (libglobal_planner_deps.a, libmath_utils.a) using the EXACT compile flags and
# link line CMake recorded for the shipping nodes. This guarantees the harness
# exercises the same compiled planner as the real build, with no modification to
# any source file.
#
# Usage:
#   build_planner_ros2.sh [--tree <workspace>]
#
#     --tree  ROS 2 workspace to test (default: openmover_ws)
#             openmover_ws                  -> ROS2-reference
#             caasi-workspace/openmover     -> caasi-ROS2
#
# The harness itself is tree-agnostic; only the build directory, the recorded
# CMake flags/link line, and the source include root vary with the tree. Test
# inputs, metrics and tolerances are identical across trees.
source /opt/ros/jazzy/setup.bash

TREE="openmover_ws"
while [ $# -gt 0 ]; do
  case "$1" in
    --tree) TREE="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

ROOT=/home/zar/Documents/phd/robot
WS="$ROOT/$TREE"
if [ ! -f "$WS/install/setup.bash" ]; then
  echo "ERROR: no ROS 2 install at $WS/install/setup.bash" >&2
  exit 1
fi

echo "=== tree: $TREE ==="
source "$WS/install/setup.bash"

B="$WS/build/openmover"
FLAGS_MAKE=$B/CMakeFiles/global_planner_deps.dir/flags.make
if [ ! -f "$FLAGS_MAKE" ]; then
  echo "ERROR: no recorded CMake flags at $FLAGS_MAKE (tree not built?)" >&2
  exit 1
fi

CXX_FLAGS=$(grep -m1 '^CXX_FLAGS = ' "$FLAGS_MAKE" | cut -d= -f2-)
CXX_DEFINES=$(grep -m1 '^CXX_DEFINES = ' "$FLAGS_MAKE" | cut -d= -f2-)
CXX_INCLUDES=$(grep -m1 '^CXX_INCLUDES = ' "$FLAGS_MAKE" | cut -d= -f2-)

HARNESS_CPP=$ROOT/caasi/plan/audits/ros1-ros2-comparison/planner_ab_ros2.cpp
OUT=/tmp/planner_ab_ros2_$(echo "$TREE" | tr '/' '_')

echo "=== compiling harness object ==="
g++ $CXX_FLAGS $CXX_DEFINES $CXX_INCLUDES -c -o "$OUT.o" "$HARNESS_CPP" 2>&1 | tail -8
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
/usr/bin/c++ -O3 -DNDEBUG "$OUT.o" -o "$OUT" $ARGS 2>&1 | tail -10
echo "link rc=$?"

if [ -x "$OUT" ]; then
  echo "=== RUN (tree=$TREE) ==="
  "$OUT" 2>&1 | grep -vE "^\[" | head -30
fi
