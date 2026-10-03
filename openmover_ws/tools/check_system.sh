#!/usr/bin/env bash
# OpenMover ROS 2 workspace — system health check (strictly read-only)
#
# Usage:  bash tools/check_system.sh
# Exit code 0 = machine can build/run the workspace, non-zero otherwise.
#
# Mind the 16 GB memory constraint: this script only reads state, it never
# compiles or launches anything.

set -u

PASS=0; WARN=0; FAIL=0
pass() { printf '  [PASS] %s\n' "$1"; PASS=$((PASS+1)); }
warn() { printf '  [WARN] %s\n' "$1"; WARN=$((WARN+1)); }
fail() { printf '  [FAIL] %s\n' "$1"; FAIL=$((FAIL+1)); }
section() { printf '\n== %s ==\n' "$1"; }

WS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---------------------------------------------------------------- OS
section "Operating system"
if [ -r /etc/os-release ]; then
  . /etc/os-release
  if [ "${ID:-}" = "ubuntu" ] && [ "${VERSION_ID:-}" = "24.04" ]; then
    pass "Ubuntu ${VERSION_ID} (${VERSION_CODENAME:-noble})"
  else
    warn "Detected ${PRETTY_NAME:-unknown OS} — expected Ubuntu 24.04"
  fi
else
  fail "Cannot read /etc/os-release"
fi

# ---------------------------------------------------------------- ROS 2
section "ROS 2"
if [ -f /opt/ros/jazzy/setup.bash ]; then
  pass "ROS 2 Jazzy installed (/opt/ros/jazzy)"
else
  fail "ROS 2 Jazzy not found — /opt/ros/jazzy/setup.bash missing"
fi
if command -v colcon >/dev/null 2>&1; then
  pass "colcon on PATH"
else
  warn "colcon not on PATH (apt install python3-colcon-common-extensions)"
fi

# ---------------------------------------------------------------- Gazebo
section "Gazebo Harmonic"
if command -v gz >/dev/null 2>&1; then
  gz_ver="$(gz sim --versions 2>/dev/null | head -n 1)"
  if [ -n "$gz_ver" ]; then
    case "$gz_ver" in
      8.*) pass "gz sim Harmonic detected: $gz_ver" ;;
      *)   warn "gz sim found but unexpected version: $gz_ver (expected 8.x)" ;;
    esac
  else
    warn "gz binary found but 'gz sim --versions' produced no output"
  fi
else
  fail "gz command not found (apt install ros-jazzy-ros-gz)"
fi

# ---------------------------------------------------------------- Dependencies
section "ROS / system dependency packages"
DEPS="
ros-jazzy-cartographer-ros ros-jazzy-cartographer-ros-msgs
ros-jazzy-nav2-costmap-2d ros-jazzy-nav2-map-server
ros-jazzy-nav2-lifecycle-manager ros-jazzy-nav2-msgs
ros-jazzy-nav2-bringup ros-jazzy-navigation2
ros-jazzy-slam-toolbox
ros-jazzy-laser-geometry ros-jazzy-pcl-ros ros-jazzy-pointcloud-to-laserscan
ros-jazzy-robot-state-publisher ros-jazzy-xacro
ros-jazzy-joint-state-publisher ros-jazzy-teleop-twist-keyboard
ros-jazzy-rosbridge-server ros-jazzy-joy ros-jazzy-tf-transformations
ros-jazzy-ros-gz-sim ros-jazzy-ros-gz-bridge
ros-jazzy-rviz2
libpcl-dev libeigen3-dev libopencv-dev libyaml-cpp-dev libboost-dev
python3-pynput python3-pygame
"
missing=""; total=0
for p in $DEPS; do
  total=$((total+1))
  dpkg -s "$p" >/dev/null 2>&1 || missing="$missing $p"
done
if [ -z "$missing" ]; then
  pass "All $total dependency packages installed"
else
  fail "Missing packages:$missing"
fi

# ---------------------------------------------------------------- OSQP
section "OSQP (QP solver, built into /usr/local)"
if [ -f /usr/local/lib/libosqp.so ] && [ -d /usr/local/include/osqp ]; then
  pass "OSQP library + headers installed in /usr/local"
else
  fail "OSQP missing — run 'sudo bash tools/install_deps.sh'"
fi

# ---------------------------------------------------------------- GPU
section "GPU"
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  gpu_name="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1)"
  pass "NVIDIA driver responding: ${gpu_name:-NVIDIA GPU}"
elif command -v lspci >/dev/null 2>&1; then
  if lspci 2>/dev/null | grep -iE 'vga|3d|display' | grep -qi nvidia; then
    warn "NVIDIA GPU present but nvidia-smi not responding (driver issue? Gazebo GUI may fail, headless still works)"
  elif lspci 2>/dev/null | grep -qiE 'vga|3d|display'; then
    warn "No NVIDIA GPU detected — Gazebo GUI needs one; use headless:=true"
  else
    warn "No display adapter found via lspci — GPU check inconclusive"
  fi
else
  warn "Could not query PCI devices (lspci missing?) — GPU check skipped"
fi

# ---------------------------------------------------------------- Memory
section "Memory (hard constraint: 16 GB)"
avail_kb="$(awk '/MemAvailable/ {print $2}' /proc/meminfo)"
total_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
avail_gb=$((avail_kb / 1024 / 1024))
total_gb=$((total_kb / 1024 / 1024))
if [ "$total_gb" -lt 15 ]; then
  warn "Total RAM is ${total_gb} GB — builds must stay at -j2 and Gazebo runs headless"
fi
if [ "$avail_gb" -lt 4 ]; then
  fail "Only ${avail_gb} GB RAM available — close other applications before building or running Gazebo"
else
  pass "${avail_gb} GB available (of ${total_gb} GB total)"
fi

# ---------------------------------------------------------------- Stale processes
section "Stale simulator processes"
stale="$(pgrep -fc 'gz sim|ruby' 2>/dev/null || true)"
if [ "${stale:-0}" -gt 0 ]; then
  warn "$stale stale 'gz sim'/'ruby' process(es) running — kill them before launching (pkill -f 'gz sim'; pkill -f ruby)"
else
  pass "No stale gz/ruby processes"
fi

# ---------------------------------------------------------------- Workspace
section "Workspace layout ($WS_DIR)"
[ -d "$WS_DIR/src/openmover" ] && pass "src/openmover present" || fail "src/openmover missing"
[ -d "$WS_DIR/src/openmover_msgs" ] && pass "src/openmover_msgs present" || fail "src/openmover_msgs missing"
[ -d "$WS_DIR/src/warehouse_simulation" ] && pass "src/warehouse_simulation present" || fail "src/warehouse_simulation missing"
[ -f "$WS_DIR/install/setup.bash" ] \
  && pass "workspace already built (install/setup.bash present)" \
  || warn "workspace not built yet — run the -j2 colcon build from the docs"

# ---------------------------------------------------------------- Summary
printf '\n==========================================\n'
printf 'Summary: %d passed, %d warning(s), %d failed\n' "$PASS" "$WARN" "$FAIL"
if [ "$FAIL" -gt 0 ]; then
  echo "RESULT: FAIL — fix the [FAIL] items above and re-run."
  exit 1
fi
if [ "$WARN" -gt 0 ]; then
  echo "RESULT: PASS with warnings."
else
  echo "RESULT: PASS — system is ready."
fi
exit 0
