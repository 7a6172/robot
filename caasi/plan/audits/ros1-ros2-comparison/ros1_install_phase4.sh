#!/bin/bash
# install.sh steps 69-101, with the environment chaining install.sh relies on.
#
# install.sh sources the Cartographer overlay (line 66) and then builds OSQP and
# the OpenMover workspace with that overlay still active, because openmover_msgs
# does find_package(cartographer_ros_msgs). This script reproduces that exact
# environment chaining.
set -x
export DISABLE_ROS1_EOL_WARNINGS=1

source /opt/ros/noetic/setup.bash
source /root/openmover_robot/cartographer_ws/install_isolated/setup.bash

echo "=== cartographer_ros_msgs visible? ==="
python3 -c "import sys; print([p for p in sys.path if 'install_isolated' in p])"
ls /root/openmover_robot/cartographer_ws/install_isolated/share/cartographer_ros_msgs/ >/dev/null && echo "cartographer_ros_msgs present"

# --- [RUN 80-98] OpenMover workspace, install.sh whitelist order ---
cd /root/openmover_robot/openmover_ws || exit 1
rm -rf build devel install

build_pkg () {
  echo "### catkin_make -DCATKIN_WHITELIST_PACKAGES=$1"
  catkin_make -j4 -DCATKIN_WHITELIST_PACKAGES="$1" || { echo "!!! FAILED: $1"; return 1; }
}

build_pkg warehouse_simulation          || exit 1
build_pkg ira_laser_tools               || exit 1
build_pkg relocalization_toolbox_msgs   || exit 1
build_pkg relocalization_toolbox        || exit 1
build_pkg openmover_msgs                || exit 1
source /root/openmover_robot/openmover_ws/devel/setup.bash
build_pkg auto_mapping_toolbox_msgs     || exit 1
build_pkg auto_mapping_toolbox          || exit 1
source /root/openmover_robot/openmover_ws/devel/setup.bash
build_pkg bluesea2                      || exit 1
source /root/openmover_robot/openmover_ws/devel/setup.bash
build_pkg openmover                     || exit 1

echo "=== OPENMOVER WORKSPACE BUILD COMPLETE ==="
ls /root/openmover_robot/openmover_ws/devel/setup.bash
