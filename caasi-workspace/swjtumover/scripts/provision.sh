#!/usr/bin/env bash
# Prepare a robot to run swjtumover: ROS 2, the packages this project uses, the camera, and a shell
# that already knows about all of it.
#
#   # on the robot
#   scripts/provision.sh                 # show what would be installed, change nothing
#   scripts/provision.sh --apply         # do it
#   scripts/provision.sh --apply --stage ros        # one stage only
#
#   # from your machine, as a tracked run
#   caasi run start experiments/provision.yaml -t <target>
#
# Stages, in the order they run:
#   ros      ROS 2 Jazzy itself, and colcon
#   packages the ROS 2 packages this project uses (navigation, mapping, camera, vision, teleop)
#   camera   RealSense udev rules and the video group
#   shell    source ROS 2 and the installed workspace from ~/.bashrc, and set ROS_DOMAIN_ID
#   build    colcon build the project
#
# Every stage is idempotent: running it twice changes nothing the second time. Nothing is installed
# until --apply is given, and every command is printed as it runs.
set -eo pipefail

PREFIX="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # the deployed project
ROS_DISTRO="${ROS_DISTRO:-jazzy}"
ROS_SETUP="/opt/ros/${ROS_DISTRO}/setup.bash"
OVERLAY="${PREFIX}/install/setup.bash"
DOMAIN_ID="${ROS_DOMAIN_ID:-}"

APPLY=0
STAGES=()
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --dry-run) APPLY=0; shift ;;
    --stage) STAGES+=("$2"); shift 2 ;;
    --domain) DOMAIN_ID="$2"; shift 2 ;;
    -h|--help) sed -n '2,24p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ ${#STAGES[@]} -eq 0 ] && STAGES=(ros packages camera shell build)

run() {
  if [ "${APPLY}" -eq 1 ]; then
    echo "+ $*"
    "$@"
  else
    echo "  would run: $*"
  fi
}

apt_install() {
  run sudo apt-get install -y "$@"
}

has_pkg() { dpkg -s "$1" >/dev/null 2>&1; }

stage_ros() {
  echo "== ros =="
  if [ -f "${ROS_SETUP}" ]; then
    echo "   ROS 2 ${ROS_DISTRO} already installed"
  else
    run sudo apt-get update
    run sudo apt-get install -y "ros-${ROS_DISTRO}-desktop"
  fi
  has_pkg "python3-colcon-common-extensions" || \
    apt_install python3-colcon-common-extensions
}

stage_packages() {
  echo "== packages =="
  local packages=(
    "ros-${ROS_DISTRO}-navigation2"
    "ros-${ROS_DISTRO}-nav2-bringup"
    "ros-${ROS_DISTRO}-slam-toolbox"
    "ros-${ROS_DISTRO}-realsense2-camera"
    "ros-${ROS_DISTRO}-cv-bridge"
    python3-opencv
    python3-pynput
  )
  local missing=()
  for pkg in "${packages[@]}"; do
    has_pkg "${pkg}" || missing+=("${pkg}")
  done
  if [ ${#missing[@]} -eq 0 ]; then
    echo "   all ${#packages[@]} packages already installed"
  else
    apt_install "${missing[@]}"
  fi
}

stage_camera() {
  echo "== camera =="
  if dpkg -s librealsense2-utils >/dev/null 2>&1; then
    echo "   librealsense already installed"
  else
    echo "   NOTE: librealsense needs Intel's apt repository; install ros-${ROS_DISTRO}-realsense2-camera"
    echo "         and librealsense2-utils from Intel's instructions for this release."
  fi
  if id -nG "${USER}" | tr ' ' '\n' | grep -qx video; then
    echo "   ${USER} is already in the video group"
  else
    run sudo usermod -aG video "${USER}"
    echo "   log out and back in for the group to apply"
  fi
}

stage_shell() {
  echo "== shell =="
  local bashrc="${HOME}/.bashrc"
  # Guarded, so a shell still opens if the workspace has not been built yet.
  # A machine set up by hand may already source ROS 2 unguarded; that counts as done, and adding a
  # second line would only source it twice.
  #   add_line <line to add> [<text meaning it is already covered>]
  add_line() {
    local line="$1" covered="${2:-$1}"
    if grep -Fq -- "${line}" "${bashrc}" 2>/dev/null; then
      echo "   already present: ${line}"
    elif grep -Fq -- "${covered}" "${bashrc}" 2>/dev/null; then
      echo "   already covered by: ${covered}"
    elif [ "${APPLY}" -eq 1 ]; then
      printf '%s\n' "${line}" >> "${bashrc}"
      echo "+ added to ${bashrc}: ${line}"
    else
      echo "  would add to ${bashrc}: ${line}"
    fi
  }
  add_line "[ -f ${ROS_SETUP} ] && source ${ROS_SETUP}" "source ${ROS_SETUP}"
  add_line "[ -f ${OVERLAY} ] && source ${OVERLAY}"     "source ${OVERLAY}"
  if [ -n "${DOMAIN_ID}" ]; then
    add_line "export ROS_DOMAIN_ID=${DOMAIN_ID}"
  else
    echo "   no --domain given: ROS_DOMAIN_ID is left alone. With several robots on one network a"
    echo "   distinct domain per robot keeps their graphs apart."
  fi
}

stage_build() {
  echo "== build =="
  if [ ! -d "${PREFIX}/src" ]; then
    echo "   no src/ in ${PREFIX}; deploy the project first" >&2
    return 1
  fi
  run bash -c "cd '${PREFIX}' && source '${ROS_SETUP}' && colcon build --symlink-install"
}

for stage in "${STAGES[@]}"; do
  case "${stage}" in
    ros) stage_ros ;;
    packages) stage_packages ;;
    camera) stage_camera ;;
    shell) stage_shell ;;
    build) stage_build ;;
    *) echo "unknown stage: ${stage}" >&2; exit 2 ;;
  esac
done

echo
if [ "${APPLY}" -eq 1 ]; then
  echo "provisioning applied. Verify with:"
else
  echo "nothing was changed (this was a dry run). Apply with --apply. Afterwards verify with:"
fi
echo "  caasi target deps <target> --for bringup"
