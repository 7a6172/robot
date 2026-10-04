#!/bin/bash
# Build and run the ROS 1 planner A/B harness.
#
# The ROS 1 `openmover` package exposes no shared library, so the planner
# translation units are compiled directly into the harness. Planner sources are
# used EXACTLY as they are in the workspace - nothing is modified.
export DISABLE_ROS1_EOL_WARNINGS=1
source /opt/ros/noetic/setup.bash
source /root/openmover_robot/cartographer_ws/install_isolated/setup.bash
source /root/openmover_robot/openmover_ws/devel/setup.bash

W=/root/openmover_robot/openmover_ws/src/openmover
GP=$W/src/navigation/utils/global_planner

SRCS="
$GP/planner.cpp
$GP/quadratic_calculator.cpp
$GP/dijkstra.cpp
$GP/gradient_path.cpp
$GP/grid_path.cpp
$GP/orientation_filter.cpp
$GP/backend_optimization.cpp
$GP/polyline_generation.cpp
$GP/osqp_smoother.cpp
$GP/osqp_utils.cpp
$W/src/navigation/utils/math_utils.cpp
"

g++ -std=c++17 -O2 -fopenmp -o /tmp/planner_ab_ros1 \
  /root/planner_ab_ros1.cpp $SRCS \
  -I"$W/include" \
  -I/root/openmover_robot/openmover_ws/devel/include \
  -I/opt/ros/noetic/include \
  -I/usr/include/eigen3 \
  -I/usr/include/pcl-1.10 \
  -I/usr/include/opencv4 \
  -L/opt/ros/noetic/lib \
  -L/usr/local/lib \
  -lroscpp -lrostime -lrosconsole -lcostmap_2d -ltf2 -ltf2_ros \
  -lroscpp_serialization -lcpp_common -lrosconsole_log4cxx -lrosconsole_backend_interface \
  -lxmlrpcpp -lroslib -lboost_system -lboost_thread -lpthread \
  -losqp -lpcl_common -lpcl_filters -lpcl_io -lpcl_search -lpcl_kdtree -lflann -lflann_cpp -lopencv_core -lopencv_imgproc -lceres -lglog 2>&1 | tail -25

echo "build rc=$?"
if [ -x /tmp/planner_ab_ros1 ]; then
  pkill -f roscore >/dev/null 2>&1; sleep 1
  roscore > /tmp/roscore.log 2>&1 &
  sleep 4
  echo "=== RUN ==="
  export LC_ALL=C.UTF-8 LANG=C.UTF-8 LANGUAGE=C.UTF-8
  export PYTHONIOENCODING=utf-8
  export ROSCONSOLE_FORMAT='[${severity}] ${message}'
  LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH /tmp/planner_ab_ros1
fi
