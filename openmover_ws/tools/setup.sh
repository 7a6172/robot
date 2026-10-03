#!/usr/bin/env bash
# ============================================================================
# OpenMover ROS 2 — interactive setup wizard
#
# Detects the system, tells you whether it is sufficient, picks a safe build
# parallelism for your RAM (overridable), and can then install dependencies,
# build the workspace and run the tests — with a confirmation before each
# step.
#
# Usage:
#   bash tools/setup.sh              # interactive wizard
#   bash tools/setup.sh --check      # detect only, then exit (0 = sufficient)
#   bash tools/setup.sh --yes        # non-interactive: accept every default
#   bash tools/setup.sh --jobs N     # override the auto-picked build jobs
#
# Memory safety: compiler jobs are sized to RAM (>=32 GB: up to 8, 16 GB: 2,
# below: 1). Do not raise this on low-memory hosts.
# ============================================================================
set -u

WS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---------------------------------------------------------------- arguments
CHECK_ONLY=0
ASSUME_YES=0
JOBS_OVERRIDE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --check)      CHECK_ONLY=1 ;;
    --yes|-y)     ASSUME_YES=1 ;;
    --jobs)       shift; JOBS_OVERRIDE="${1:-}" ;;
    --jobs=*)     JOBS_OVERRIDE="${1#*=}" ;;
    -h|--help)
      sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown option: $1 (try --help)"; exit 2 ;;
  esac
  shift
done

# ---------------------------------------------------------------- ui helpers
if [ -t 1 ]; then
  RED=$'\e[31m'; GRN=$'\e[32m'; YLW=$'\e[33m'; BLU=$'\e[34m'; BLD=$'\e[1m'; RST=$'\e[0m'
else
  RED=""; GRN=""; YLW=""; BLU=""; BLD=""; RST=""
fi
hr()    { printf '%s\n' "------------------------------------------------------------"; }
title() { printf '\n%s%s%s\n' "$BLD" "$1" "$RST"; }
ok()   { printf '  %s[ ok ]%s %s\n' "$GRN" "$RST" "$1"; }
warn() { printf '  %s[warn]%s %s\n' "$YLW" "$RST" "$1"; }
bad()  { printf '  %s[fail]%s %s\n' "$RED" "$RST" "$1"; }

ask_yn() { # $1 = prompt, $2 = default (y|n); returns 0 for yes
  local prompt="$1" def="${2:-y}" ans
  [ "$ASSUME_YES" -eq 1 ] && return 0
  while true; do
    printf '%s? %s [%s]%s ' "$BLU" "$prompt" "$def" "$RST"
    read -r ans || ans="$def"
    ans="${ans:-$def}"
    case "${ans,,}" in y|yes) return 0 ;; n|no) return 1 ;; esac
  done
}

ask_choice() { # $1 = prompt, $2 = default (1-based), rest = options
  local prompt="$1" def="$2" ans i=1
  shift 2
  local opts=("$@")
  if [ "$ASSUME_YES" -eq 1 ]; then CHOSEN="$def"; return 0; fi
  while true; do
    for o in "${opts[@]}"; do
      printf '  %d) %s\n' "$i" "$o"; i=$((i+1))
    done
    printf '%s? %s [1-%d, default %s]%s ' "$BLU" "$prompt" "${#opts[@]}" "$def" "$RST"
    read -r ans || ans="$def"
    ans="${ans:-$def}"
    if [[ "$ans" =~ ^[0-9]+$ ]] && [ "$ans" -ge 1 ] && [ "$ans" -le "${#opts[@]}" ]; then
      CHOSEN="$ans"; return 0
    fi
  done
}

# ---------------------------------------------------------------- detection
title "OpenMover ROS 2 setup wizard"
echo "Workspace: $WS_DIR"
title "Detecting system ..."

OS_NAME="$(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-unknown}" || echo unknown)"
CORES="$(nproc 2>/dev/null || echo 1)"
# MB-based thresholds: a "16 GB" machine reports ~15.5 GB usable in MemTotal,
# so tiers are keyed on module class (8/16/32 GB), not the raw GB count.
TOTAL_MB=$(( $(awk '/MemTotal/{print $2}' /proc/meminfo) / 1024 ))
AVAIL_GB=$(( $(awk '/MemAvailable/{print $2}' /proc/meminfo) / 1024 / 1024 ))
DISK_GB="$(df -BG --output=avail "$WS_DIR" 2>/dev/null | tail -n 1 | tr -dc '0-9')"

ROS_OK=0; [ -f /opt/ros/jazzy/setup.bash ] && ROS_OK=1
COLCON_OK=0; command -v colcon >/dev/null 2>&1 && COLCON_OK=1
GZ_VER="$(command -v gz >/dev/null 2>&1 && gz sim --versions 2>/dev/null | head -n 1)"
GZ_VER="${GZ_VER:-missing}"

GPU="none detected"
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  GPU="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1)"
elif command -v lspci >/dev/null 2>&1 && lspci 2>/dev/null | grep -iE 'vga|3d|display' | grep -qi nvidia; then
  GPU="NVIDIA present (driver not responding — headless only)"
fi

OSQP_OK=0; [ -f /usr/local/lib/libosqp.so ] && OSQP_OK=1
BUILT_OK=0; [ -f "$WS_DIR/install/setup.bash" ] && BUILT_OK=1

# report
[ "$ROS_OK" -eq 1 ] && ok "ROS 2 Jazzy: /opt/ros/jazzy" || bad "ROS 2 Jazzy not found (install first — see docs/getting_started.html)"
[ "$COLCON_OK" -eq 1 ] && ok "colcon available" || warn "colcon missing (apt install python3-colcon-common-extensions)"
case "$GZ_VER" in 8.*) ok "Gazebo Harmonic: $GZ_VER" ;; *) bad "gz sim: $GZ_VER (expected 8.x — apt install ros-jazzy-ros-gz)" ;; esac
[ "$OSQP_OK" -eq 1 ] && ok "OSQP installed in /usr/local" || warn "OSQP missing (will be built by the dependency step)"
[ "$BUILT_OK" -eq 1 ] && ok "Workspace already built (install/ present)" || warn "Workspace not built yet"
case "$OS_NAME" in *24.04*) ok "OS: $OS_NAME" ;; *) warn "OS: $OS_NAME (Ubuntu 24.04 expected)" ;; esac
if [ "$GPU" = "none detected" ]; then warn "GPU: $GPU (use headless:=true for Gazebo)"; else ok "GPU: $GPU"; fi
echo "  CPU threads : $CORES"
echo "  RAM         : ~$(( TOTAL_MB / 1024 )) GB total ($TOTAL_MB MB), ${AVAIL_GB} GB available"
echo "  Disk free   : ${DISK_GB:-?} GB"

# verdict + job tier (module classes: 32 GB / 16 GB / 8 GB)
PROPOSED=1
if   [ "$TOTAL_MB" -ge 28672 ]; then PROPOSED=$(( CORES > 8 ? 8 : CORES ))
elif [ "$TOTAL_MB" -ge 14336 ]; then PROPOSED=2
fi
VERDICT="PASS"
if [ "$TOTAL_MB" -lt 7168 ]; then
  VERDICT="INSUFFICIENT"
  bad "Less than 8 GB RAM — below the practical minimum (simulation needs ~10 GB with RViz)."
elif [ "$TOTAL_MB" -lt 14336 ]; then
  VERDICT="CAUTION"
  warn "Below the recommended 16 GB — building with 1 job, run Gazebo headless."
else
  ok "System is sufficient (recommended tier: -j$PROPOSED)."
fi
[ "${DISK_GB:-99}" -lt 5 ] && warn "Less than 5 GB free disk — build artifacts need ~3 GB."

if [ "$CHECK_ONLY" -eq 1 ]; then
  hr
  echo "Result: $VERDICT (recommended build jobs: $PROPOSED)"
  [ "$VERDICT" = "INSUFFICIENT" ] && exit 1
  exit 0
fi

# ---------------------------------------------------------------- job selection
JOBS="$PROPOSED"
if [ -n "$JOBS_OVERRIDE" ]; then
  if [[ "$JOBS_OVERRIDE" =~ ^[0-9]+$ ]] && [ "$JOBS_OVERRIDE" -ge 1 ]; then
    JOBS="$JOBS_OVERRIDE"
    warn "Build jobs overridden to $JOBS (auto-picked value was $PROPOSED)."
  else
    bad "Invalid --jobs value '$JOBS_OVERRIDE', using $PROPOSED."
  fi
else
  ask_choice "Build parallelism for ~$(( TOTAL_MB / 1024 )) GB RAM?" "$([ "$PROPOSED" -le 4 ] && echo "$PROPOSED" || echo 4)" \
    "1 job  (safest, <16 GB RAM)" \
    "2 jobs (proven on 16 GB)" \
    "4 jobs" \
    "8 jobs (32 GB+ RAM recommended)"
  case "$CHOSEN" in 1) JOBS=1 ;; 2) JOBS=2 ;; 3) JOBS=4 ;; 4) JOBS=8 ;; esac
fi
echo ""
echo "Selected build jobs: $JOBS"

# ---------------------------------------------------------------- steps
do_deps() {
  title "Installing dependencies (apt + rosdep + OSQP) — needs sudo"
  sudo bash "$WS_DIR/tools/install_deps.sh" || { bad "Dependency installation failed."; return 1; }
  ok "Dependencies installed."
}

do_build() {
  title "Building workspace with -j$JOBS"
  if [ ! -f /opt/ros/jazzy/setup.bash ]; then
    bad "ROS 2 Jazzy is required before building."; return 1
  fi
  set +u; . /opt/ros/jazzy/setup.bash; set -u
  ( cd "$WS_DIR" && \
    MAKEFLAGS="-j$JOBS" CMAKE_BUILD_PARALLEL_LEVEL="$JOBS" \
    colcon build --symlink-install --parallel-workers "$JOBS" ) \
    || { bad "Build failed. Lower the job count and retry."; return 1; }
  ok "Build finished. Activate with: source install/setup.bash"
}

do_test() {
  title "Running warehouse_simulation tests"
  set +u; . /opt/ros/jazzy/setup.bash; set -u
  ( cd "$WS_DIR" && colcon test --packages-select warehouse_simulation \
      && colcon test-result --verbose ) \
    || { bad "Tests failed — see log/ for details."; return 1; }
  ok "Tests passed."
}

# ---------------------------------------------------------------- menu
while true; do
  title "What would you like to do?"
  ask_choice "Choose an action" 1 \
    "Full setup (dependencies + build + tests)" \
    "Install dependencies only" \
    "Build workspace only (-j$JOBS)" \
    "Run tests only" \
    "Re-detect system" \
    "Exit"
  case "$CHOSEN" in
    1)
      if ask_yn "Install dependencies now (sudo apt + rosdep + OSQP)?" y; then do_deps || continue; fi
      if ask_yn "Build the workspace now (-j$JOBS)?" y; then do_build || continue; fi
      if ask_yn "Run the simulation tests now?" y; then do_test; fi
      title "Done"
      echo "Next steps:"
      echo "  source $WS_DIR/install/setup.bash"
      echo "  ros2 launch warehouse_simulation warehouse_simulation.launch.py"
      echo "See docs/usage.html for the full walkthrough."
      exit 0 ;;
    2) ask_yn "Install dependencies now (sudo apt + rosdep + OSQP)?" y && do_deps ;;
    3) ask_yn "Build the workspace now (-j$JOBS)?" y && do_build ;;
    4) ask_yn "Run the simulation tests now?" y && do_test ;;
    5) exec bash "$0" --check ;;
    6) exit 0 ;;
  esac
done
