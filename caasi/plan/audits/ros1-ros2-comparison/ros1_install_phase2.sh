#!/bin/bash
# install.sh steps 45-77: Cartographer (abseil + catkin_make_isolated) and OSQP.
# Executed as-is from the authoritative script, inside the container's copy.
set -x
export DEBIAN_FRONTEND=noninteractive
source /opt/ros/noetic/setup.bash

# --- [RUN 47-49] Cartographer build dependencies ---
apt-get install -y ninja-build stow
apt-get install -y clang cmake g++ git google-mock libboost-all-dev \
  libboost-iostreams-dev libcairo2-dev libceres-dev libcurl4-openssl-dev \
  libeigen3-dev libgflags-dev libgoogle-glog-dev liblua5.2-dev \
  libsuitesparse-dev lsb-release ninja-build python3-sphinx stow
apt-get install -y libgmock-dev protobuf-compiler libprotobuf-dev

# --- [RUN 50-58] abseil-cpp into /usr/local/stow/absl ---
cd ~/openmover_robot/cartographer_ws/abseil-cpp || exit 1
rm -rf build
mkdir build
cd build || exit 1
cmake -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
  -DCMAKE_INSTALL_PREFIX=/usr/local/stow/absl .. || exit 1
ninja || exit 1
ninja install || exit 1
cd /usr/local/stow || exit 1
stow absl || exit 1

# --- [RUN 59-66] Cartographer workspace ---
cd ~/openmover_robot/cartographer_ws || exit 1
rm -rf build_isolated devel_isolated install_isolated
source /opt/ros/noetic/setup.bash
catkin_make_isolated --install --use-ninja || exit 1
source ~/openmover_robot/cartographer_ws/install_isolated/setup.bash

# --- [RUN 69-77] OSQP ---
cd ~/openmover_robot/osqp || exit 1
rm -rf build
mkdir build
cd build || exit 1
cmake -G "Unix Makefiles" .. || exit 1
cmake --build . || exit 1
cmake --build . --target install || exit 1

echo "=== CARTOGRAPHER + OSQP COMPLETE ==="
