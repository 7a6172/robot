#!/usr/bin/env bash
# OpenMover ROS 2 workspace — dependency installer
#
# Usage:  sudo bash tools/install_deps.sh      (re-execs itself with sudo if needed)
#
# Installs, in order:
#   1. base build tools
#   2. the ROS 2 / system packages required by the workspace (see docs/getting_started.html)
#   3. rosdep-resolved package.xml dependencies
#   4. OSQP from tools/osqp_build (skipped if already installed)
#
# MEMORY CONSTRAINT: builds here use -j2. Do not raise this on 16 GB hosts.

set -e
export DEBIAN_FRONTEND=noninteractive

# -- re-exec with sudo when needed -----------------------------------------
if [ "$(id -u)" -ne 0 ]; then
  echo "This script installs system packages — re-running with sudo..."
  exec sudo bash "$0" "$@"
fi

WS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REAL_USER="${SUDO_USER:-root}"

echo "== [1/4] Base build tools =="
apt-get update
apt-get install -y curl gnupg lsb-release software-properties-common \
  git build-essential cmake ninja-build python3-colcon-common-extensions

# -- ROS 2 Jazzy must already exist (see docs/getting_started.html) --------
if [ ! -f /opt/ros/jazzy/setup.bash ]; then
  echo "ERROR: ROS 2 Jazzy not found (/opt/ros/jazzy/setup.bash missing)."
  echo "Install it first as described in docs/getting_started.html, then re-run this script."
  exit 1
fi

echo "== [2/4] ROS / system dependency packages =="
apt-get install -y \
  ros-jazzy-cartographer-ros ros-jazzy-cartographer-ros-msgs \
  ros-jazzy-nav2-costmap-2d ros-jazzy-nav2-map-server \
  ros-jazzy-nav2-lifecycle-manager ros-jazzy-nav2-msgs \
  ros-jazzy-nav2-bringup ros-jazzy-navigation2 \
  ros-jazzy-slam-toolbox \
  ros-jazzy-laser-geometry ros-jazzy-pcl-ros ros-jazzy-pointcloud-to-laserscan \
  ros-jazzy-robot-state-publisher ros-jazzy-xacro \
  ros-jazzy-joint-state-publisher ros-jazzy-teleop-twist-keyboard \
  ros-jazzy-rosbridge-server ros-jazzy-joy ros-jazzy-tf-transformations \
  ros-jazzy-ros-gz-sim ros-jazzy-ros-gz-bridge \
  ros-jazzy-rviz2 \
  libpcl-dev libeigen3-dev libopencv-dev libyaml-cpp-dev libboost-dev \
  python3-pynput python3-pygame

echo "== [3/4] rosdep (package.xml dependencies) =="
rosdep init >/dev/null 2>&1 || true
if [ "$REAL_USER" != "root" ]; then
  # update the invoking user's rosdep cache, not root's
  su "$REAL_USER" -c "rosdep update"
else
  rosdep update
fi
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths "$WS_DIR/src" --ignore-src -r -y --rosdistro jazzy

echo "== [4/4] OSQP =="
if [ -f /usr/local/lib/libosqp.so ] && [ -d /usr/local/include/osqp ]; then
  echo "OSQP already installed in /usr/local — skipping."
else
  OSQP_SRC="$WS_DIR/tools/osqp_build"
  if [ ! -d "$OSQP_SRC" ]; then
    echo "ERROR: $OSQP_SRC not found. Copy the vendored OSQP tree into tools/ first."
    exit 1
  fi
  if [ -f "$OSQP_SRC/Makefile" ] && [ -f "$OSQP_SRC/CMakeCache.txt" ]; then
    # vendored tree is already configured in-place — just build and install
    make -C "$OSQP_SRC" -j2
    make -C "$OSQP_SRC" install
  else
    cmake -S "$OSQP_SRC" -B "$OSQP_SRC/build" -DCMAKE_BUILD_TYPE=Release
    cmake --build "$OSQP_SRC/build" -j2        # -j2: 16 GB memory constraint
    cmake --install "$OSQP_SRC/build"
  fi
fi

echo ""
echo "Done. Verify with:  bash tools/check_system.sh"
