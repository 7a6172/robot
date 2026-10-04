#!/usr/bin/env python3
"""install.sh step-by-step executability audit for an isolated Noetic container.

Every step of the authoritative install.sh is classified:
  RUN      - executed as-is inside the container
  ADAPTED  - same intent, adjusted only for container reality (documented)
  SKIP     - cannot be meaningfully executed; reason recorded

The goal is a working ROS 1 OpenMover reference, not merely a Noetic install.
"""
import json

# (line_range, step, classification, reason)
STEPS = [
    ("2-11",   "Configure passwordless sudo for the build user", "ADAPTED",
     "Container runs as root; the sudoers entry is meaningless but harmless. "
     "Executed in adapted form (no-op) so later `sudo` calls succeed trivially."),
    ("12-14",  "apt update / upgrade / autoremove", "RUN",
     "Executed. Baseline package refresh inside the container."),
    ("17-21",  "Install mainline kernel linux-generic-6.01 via tuxinvader PPA", "SKIP",
     "A container shares the host kernel; installing a kernel package inside it "
     "cannot change the running kernel and would only add unusable files. Also "
     "the PPA targets a bare-metal Ubuntu host, not the Noetic base image. "
     "IMPACT ON EQUIVALENCE: none. No OpenMover ROS functionality, message "
     "definition, planning algorithm, or sensor model depends on the kernel "
     "version. This step is host provisioning, not part of the ROS 1 system."),
    ("24-29",  "Add ROS apt source + ros.asc key", "SKIP",
     "The osrf/ros:noetic-desktop-full base image already ships ROS Noetic with "
     "its apt source and keys configured. Re-adding a mirror source (ustc.edu.cn) "
     "and importing ros.asc would be redundant and could conflict with the "
     "image's working configuration. IMPACT: none; ROS Noetic is present and "
     "functional, which is the step's actual intent."),
    ("30",     "apt install ros-noetic-desktop-full", "ADAPTED",
     "Satisfied by the base image rather than installed from scratch. "
     "Verified present and functional."),
    ("31",     "Install ROS Noetic navigation/SLAM/TF/joy/octomap/ignition deps", "RUN",
     "Executed as-is. This is the substantive ROS 1 dependency set the project "
     "needs (navigation, slam-gmapping, robot-pose-ekf, teb-local-planner, "
     "octomap, tf2, ignition, libmodbus)."),
    ("32",     "ufw allow ssh", "SKIP",
     "No ufw/firewall inside the container and no SSH service is being exposed. "
     "IMPACT: none on OpenMover functional behavior; host firewall provisioning."),
    ("33-34",  "source /opt/ros/noetic/setup.bash; append to ~/.bashrc", "RUN",
     "Executed; environment bootstrap for subsequent steps."),
    ("35",     "apt install rosdep/rosinstall/wstool/build-essential", "RUN",
     "Executed as-is."),
    ("38-42",  "Second ROS dependency block (adds serial, rosbridge-server, "
               "libpcap, libudev)", "RUN",
     "Executed as-is. Adds serial/USB, rosbridge, and packet-capture support "
     "used by OpenMover hardware layers."),
    ("45-49",  "Cartographer build dependencies", "RUN",
     "Executed as-is (ninja, stow, ceres, protobuf, boost, eigen, lua, suitesparse)."),
    ("50-58",  "Build and install abseil-cpp into /usr/local/stow/absl", "RUN",
     "Executed as-is inside the container."),
    ("59-66",  "catkin_make_isolated Cartographer workspace", "RUN",
     "Executed as-is. This produces the ROS 1 Cartographer SLAM stack."),
    ("69-77",  "Build and install OSQP", "RUN",
     "Executed as-is. OSQP backs the ROS 1 global-planner trajectory smoother."),
    ("80-98",  "catkin_make the OpenMover workspace in install.sh's whitelist "
               "order", "RUN",
     "Executed as-is, preserving the exact package order and whitelisting from "
     "the authoritative script: warehouse_simulation, ira_laser_tools, "
     "relocalization_toolbox_msgs, relocalization_toolbox, openmover_msgs, "
     "auto_mapping_toolbox_msgs, auto_mapping_toolbox, bluesea2, openmover."),
    ("99-101", "Export PYTHONPATH for the HAL; disable ROS 1 EOL warnings", "RUN",
     "Executed as-is."),
    ("104-109", "pip install pygame, pynput; set pip index", "ADAPTED",
     "pygame and pynput are installed. The Tsinghua mirror index is not applied "
     "(unreachable/slow from this environment); the default PyPI index is used "
     "instead. IMPACT: none on functional equivalence - identical packages, "
     "different download source."),
    ("112-113", "Source Cartographer and OpenMover overlays", "RUN",
     "Executed as-is."),
]

print(json.dumps(STEPS, indent=2, ensure_ascii=False))
