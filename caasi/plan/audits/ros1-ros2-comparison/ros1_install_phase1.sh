#!/bin/bash
# Faithful execution of openmover_robot/install.sh inside the ros1-ref container.
#
# Steps follow install.sh's order exactly. Adaptations are limited to those
# documented in the step audit; each is marked inline with [ADAPTED] or [SKIP].
set -x

export DEBIAN_FRONTEND=noninteractive
export DISABLE_ROS1_EOL_WARNINGS=1

# [ADAPTED 2-11] sudoers: container runs as root, so passwordless sudo is moot.
# [RUN 12-14] apt refresh
apt-get update -qq
# NOTE: `apt upgrade -y` / `autoremove -y` intentionally omitted; a full dist-upgrade
# inside a pinned ROS base image risks replacing image-managed ROS packages. The
# step audit records this. Package installs below still pull current versions.

# [SKIP 17-21] mainline kernel via tuxinvader PPA - impossible in a container.

# [SKIP 24-29] ROS apt source + key - already configured in the base image.

# [RUN 31] ROS 1 dependency set (install.sh line 31)
apt-get install -y --no-install-recommends \
  ros-noetic-joint-state-controller ros-noetic-position-controllers \
  ros-noetic-navigation ros-noetic-slam-gmapping ros-noetic-robot-pose-ekf \
  ros-noetic-teb-local-planner ros-noetic-joy openssh-server \
  libmodbus-dev libignition-math6-dev

apt-get install -y --no-install-recommends ros-noetic-octomap ros-noetic-octomap-msgs \
  ros-noetic-octomap-ros ros-noetic-octomap-rviz-plugins ros-noetic-octomap-server

apt-get install -y --no-install-recommends \
  ros-noetic-tf2 ros-noetic-tf2-ros ros-noetic-tf2-geometry-msgs \
  ros-noetic-tf2-sensor-msgs ros-noetic-tf2-eigen ros-noetic-tf2-tools

# [SKIP 32] ufw - no firewall in container.

# [RUN 33-34]
source /opt/ros/noetic/setup.bash

# [RUN 35]
apt-get install -y --no-install-recommends \
  python3-rosdep python3-rosinstall python3-rosinstall-generator python3-wstool \
  build-essential

# [RUN 38-42] second dependency block
apt-get install -y --no-install-recommends \
  ros-noetic-joint-state-controller ros-noetic-position-controllers \
  ros-noetic-navigation ros-noetic-slam-gmapping ros-noetic-robot-pose-ekf \
  ros-noetic-teb-local-planner ros-noetic-joy \
  libudev-dev ros-noetic-serial ros-noetic-rosbridge-server libpcap-dev \
  ros-noetic-tf2 ros-noetic-tf2-ros libmodbus-dev

apt-get install -y --no-install-recommends \
  python3-rosdep python3-rosinstall python3-rosinstall-generator python3-wstool \
  build-essential

echo "=== PHASE 1 COMPLETE: ROS 1 base dependencies ==="
