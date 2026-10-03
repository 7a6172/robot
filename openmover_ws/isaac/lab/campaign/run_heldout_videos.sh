#!/usr/bin/env bash
# Held-out PRESENTATION videos (ppt track, not the paper). Records env-0 traces
# at num_envs=10 --video so each clip is the SAME episode as the reported
# statistics (env-0 of the 10-env run), sidestepping the §17.21 num_envs=1
# livelock. Traces land in videos/Isaac-Nav-Openmover-v0/trace_heldout_seed42_<arm>.npz
# (hardcoded video_dir). Sequential, one simulator at a time, bounded kill-guard.
# Clip -> audit -> render (26 topdown / 29 3d) are done AFTER, separately.
set -u
LAB=/home/zar/Documents/phd/robot/openmover_ws/isaac/lab
PY=/home/zar/isaaclab/_isaac_sim/python.sh
CKPT=$LAB/logs/rsl_rl/openmover_nav/bc_init_v3/model_0.pt
OUT=$LAB/campaign/heldout/videos_present
MAP=$LAB/maps/heldout.json
STEPS=2971
ENVIRON=10
CAP=190.0
GUARD=2400   # 10-env + video render is heavier; generous 40-min/arm kill-guard
mkdir -p "$OUT/logs" "$OUT/results" "$OUT/videos"

run_arm() {  # $1=arm
  local arm=$1
  local extra=()
  case $arm in
    shield)           extra=(--policy trained   --checkpoint "$CKPT" --shield) ;;
    astar_dwa)        extra=(--policy astar_dwa) ;;
    astar_dwa_shield) extra=(--policy astar_dwa --shield) ;;
    *) echo "[heldout-vid] UNKNOWN ARM $arm"; return 2 ;;
  esac
  local avail
  avail=$(free -m | awk '/^Mem:/{print $7}')
  echo "[heldout-vid] === $arm  avail_RAM=${avail}MiB  $(date +%T) ==="
  if [ "${avail:-0}" -lt 4096 ]; then
    echo "[heldout-vid] ABORT $arm: only ${avail} MiB available (<4096)"; return 3
  fi
  ( cd /home/zar/isaaclab && env -u CONDA_PREFIX -u VIRTUAL_ENV -u PYTHONPATH \
    PYTHONUNBUFFERED=1 timeout "$GUARD" "$PY" "$LAB/21_run_openmover_nav.py" \
      --task Isaac-Nav-Openmover-v0 \
      --map_file "$MAP" \
      "${extra[@]}" \
      --num_envs "$ENVIRON" --num_steps "$STEPS" --seed 42 --episode_cap "$CAP" \
      --video --video_length "$STEPS" --video_view bird --tag "$arm" \
      --results_json "$OUT/results/${arm}.json" \
  ) > "$OUT/logs/$arm.log" 2>&1
  local rc=$?
  echo "[heldout-vid] rc=$rc $arm done $(date +%T)"
  local tr="$LAB/videos/Isaac-Nav-Openmover-v0/trace_heldout_seed42_${arm}.npz"
  if [ -f "$tr" ]; then
    echo "[heldout-vid]   trace OK: $(du -h "$tr" | cut -f1) $tr"
    grep -E "\[nav\] done|mean success|\[nav\] trace written" "$OUT/logs/$arm.log" | tail -3
  else
    echo "[heldout-vid]   NO TRACE (see logs/$arm.log)"; tail -5 "$OUT/logs/$arm.log"
  fi
}

echo "[heldout-vid] START 3-arm held-out VIDEO batch (num_envs=$ENVIRON) $(date +%T)"
run_arm astar_dwa_shield   # hero clip first (thesis: clean success)
run_arm astar_dwa          # negative comparison (success + collision)
run_arm shield             # OOD failure (timeout wander)
echo "[heldout-vid] ALL 3 HELD-OUT VIDEO RUNS DONE $(date +%T)"
