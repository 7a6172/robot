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
  local env_file="${HOME}/.caasi_env.sh"
  local bashrc="${HOME}/.bashrc"
  local profile="${HOME}/.profile"

  # Ubuntu's ~/.bashrc returns early when the shell is not interactive:
  #
  #     case $- in *i*) ;; *) return;; esac
  #
  # Anything appended after that guard works in a terminal and nowhere else -- so a desktop
  # shortcut, a cron job, or `ssh robot 'ros2 topic list'` gets no ROS at all, which looks like
  # "the shortcut opens the wrong terminal". The environment therefore lives in one file that is
  # sourced from *above* the guard, and from ~/.profile for login shells.
  if [ "${APPLY}" -eq 1 ]; then
    cat > "${env_file}" <<ENVFILE
# caasi: ROS 2 and this robot's own packages, for every shell -- interactive or not.
# Sourced from ~/.bashrc (above the interactive-only guard) and from ~/.profile.
if [ -f ${ROS_SETUP} ]; then
  . ${ROS_SETUP}
fi
if [ -f ${OVERLAY} ]; then
  . ${OVERLAY}
fi
case ":\$PATH:" in
  *":\$HOME/.local/bin:"*) ;;
  *) PATH="\$PATH:\$HOME/.local/bin"; export PATH ;;
esac
ENVFILE
    echo "+ wrote ${env_file}"
  else
    echo "  would write ${env_file} (ROS 2 + overlay + ~/.local/bin)"
  fi

  local source_line='[ -f "$HOME/.caasi_env.sh" ] && . "$HOME/.caasi_env.sh"'
  if grep -Fq -- '.caasi_env.sh' "${bashrc}" 2>/dev/null; then
    echo "   already sourced from ${bashrc}"
  elif [ "${APPLY}" -eq 1 ]; then
    python3 - "${bashrc}" <<'PYFILE'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text() if path.exists() else ""
block = ('# caasi: environment for every shell, placed above the interactive-only guard below\n'
         '[ -f "$HOME/.caasi_env.sh" ] && . "$HOME/.caasi_env.sh"\n\n')
marker = "# If not running interactively, don't do anything"
if block.splitlines()[1] not in text:
    text = text.replace(marker, block + marker, 1) if marker in text else block + text
    path.write_text(text)
    print("+ added the caasi block to", path)
PYFILE
  else
    echo "  would source .caasi_env.sh from ${bashrc} (before the interactive guard)"
  fi

  if grep -Fq -- '.caasi_env.sh' "${profile}" 2>/dev/null; then
    echo "   already sourced from ${profile}"
  elif [ "${APPLY}" -eq 1 ]; then
    printf '\n# caasi: ROS 2 + this robot, for login shells and the desktop session\n%s\n' \
      "${source_line}" >> "${profile}"
    echo "+ added the caasi block to ${profile}"
  else
    echo "  would source .caasi_env.sh from ${profile}"
  fi

  if [ -n "${DOMAIN_ID}" ]; then
    echo "   ROS_DOMAIN_ID=${DOMAIN_ID} (add it to ${env_file} to make it permanent)"
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
