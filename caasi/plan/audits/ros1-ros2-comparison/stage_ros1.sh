#!/bin/bash
# Stage the ROS1 reference into an isolated Noetic container.
#
# Safety: the host tree /home/zar/Documents/phd/robot/openmover_robot is copied
# read-only into the container at ~/openmover_robot. All builds happen inside the
# container's copy. The host tree is never written to.
set -euo pipefail

REF=/home/zar/Documents/phd/robot/openmover_robot
STAGE=/tmp/ros1-ref-staging

rm -rf "$STAGE"
mkdir -p "$STAGE"

# Copy only source content; exclude prior local build artifacts so the container
# builds from a clean source state (install.sh itself rm -rf's these anyway).
rsync -a \
  --exclude 'openmover_ws/build/' \
  --exclude 'openmover_ws/devel/' \
  --exclude 'openmover_ws/install/' \
  --exclude 'cartographer_ws/build_isolated/' \
  --exclude 'cartographer_ws/devel_isolated/' \
  --exclude 'cartographer_ws/install_isolated/' \
  --exclude 'cartographer_ws/abseil-cpp/build/' \
  --exclude 'osqp/build/' \
  "$REF/" "$STAGE/"

echo "staged: $(du -sh "$STAGE" | cut -f1)"
echo "files:  $(find "$STAGE" -type f | wc -l)"
