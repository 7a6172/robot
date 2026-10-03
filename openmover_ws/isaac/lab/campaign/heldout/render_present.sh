#!/usr/bin/env bash
# Held-out PRESENTATION video post-processing (ppt track, not the paper).
# Traces are env-0 of the num_envs=10 --video runs (SAME episode as the reported
# statistics), 20 Hz (2971 steps / 147.5 s horizon). Two phases:
#   light : clip trace -> ep1, clearance-audit, render top-down (no simulator)
#   3d    : render bird's-eye 3D via Isaac Sim (one simulator at a time)
# Sequential, bounded with per-step timeouts. Outputs land in videos_present/videos/.
set -u
LAB=/home/zar/Documents/phd/robot/openmover_ws/isaac/lab
PY=/home/zar/isaaclab/_isaac_sim/python.sh
MAP=$LAB/maps/heldout.json
OUT=$LAB/campaign/heldout/videos_present
VID=$OUT/videos
TR=$LAB/videos/Isaac-Nav-Openmover-v0
FPS=20
PHASE=${1:-light}
# Bird's-eye framing for the 15 m held-out map. Coverage ~= 12.95*height/focal
# (anchored to 29_render_3d_video.py's note that focal 17 @ height 10.5 frames
# the 8 m serial-tour square). height 26 / focal 17 -> ~20 m, frames 15 m with
# margin; offset 6 gives a gentle ~13 deg tilt (near top-down, reads the maze).
BIRD_H=26
BIRD_OFF=6
BIRD_FOCAL=17
mkdir -p "$VID" "$OUT/logs"

declare -A EXTRA TITLE
EXTRA[astar_dwa_shield]=""
EXTRA[astar_dwa]=""
EXTRA[shield]="--allow_unreached"
TITLE[astar_dwa_shield]="Held-out maze - A*+DWA + Shield (thesis): 10/10 goal, 0/10 collision"
TITLE[astar_dwa]="Held-out maze - A*+DWA unprotected: 10/10 goal, 9/10 collision"
TITLE[shield]="Held-out maze - trained policy + Shield (OOD): 0/10 goal, 0/10 collision"

run() { ( cd /home/zar/isaaclab && env -u CONDA_PREFIX -u VIRTUAL_ENV -u PYTHONPATH \
  PYTHONUNBUFFERED=1 "$@" ) ; }

light_arm() {
  local arm=$1
  local tr="$TR/trace_heldout_seed42_${arm}.npz"
  local clip="$VID/heldout_${arm}_clip.npz"
  echo "[render] === light $arm $(date +%T) ==="
  [ -f "$tr" ] || { echo "[render] MISSING trace $tr"; return 1; }
  run timeout 600 "$PY" "$LAB/28_clip_trace.py" --trace "$tr" --out "$clip" \
      --fps $FPS --reach 0.35 --map_file "$MAP" ${EXTRA[$arm]} 2>&1 | tee "$OUT/logs/clip_$arm.log"
  [ -f "$clip" ] || { echo "[render] CLIP FAILED $arm"; return 1; }
  run timeout 600 "$PY" "$LAB/30_clearance_audit.py" --trace "$clip" \
      --map_file "$MAP" 2>&1 | tee "$OUT/logs/audit_$arm.log"
  run timeout 1800 "$PY" "$LAB/26_render_topdown_video.py" --trace "$clip" \
      --fps $FPS --title "${TITLE[$arm]}" --out "$VID/heldout_${arm}.topdown.mp4" \
      2>&1 | tee "$OUT/logs/topdown_$arm.log"
  echo "[render] light $arm done $(date +%T)"
}

d3_arm() {
  local arm=$1
  local clip="$VID/heldout_${arm}_clip.npz"
  echo "[render] === 3d $arm $(date +%T) ==="
  [ -f "$clip" ] || { echo "[render] MISSING clip $clip (run light first)"; return 1; }
  local avail; avail=$(free -m | awk '/^Mem:/{print $7}')
  echo "[render]   avail_RAM=${avail}MiB"
  if [ "${avail:-0}" -lt 4096 ]; then
    echo "[render] ABORT 3d $arm: only ${avail} MiB available (<4096)"; return 3
  fi
  run timeout 1800 "$PY" "$LAB/29_render_3d_video.py" --trace "$clip" \
      --map_file "$MAP" --view bird --fps $FPS \
      --bird_height $BIRD_H --bird_offset $BIRD_OFF --focal $BIRD_FOCAL \
      --headless --enable_cameras \
      --out "$VID/heldout_${arm}.bird3d.mp4" 2>&1 | tee "$OUT/logs/3d_$arm.log"
  echo "[render] 3d $arm done $(date +%T)"
}

echo "[render] PHASE=$PHASE held-out presentation videos $(date +%T)"
for arm in astar_dwa_shield astar_dwa shield; do
  case $PHASE in
    light) light_arm "$arm" ;;
    3d)    d3_arm "$arm" ;;
    all)   light_arm "$arm"; d3_arm "$arm" ;;
    *) echo "[render] unknown phase $PHASE"; exit 2 ;;
  esac
done
echo "[render] PHASE=$PHASE DONE $(date +%T)"
ls -lh "$VID"/*.mp4 2>/dev/null
