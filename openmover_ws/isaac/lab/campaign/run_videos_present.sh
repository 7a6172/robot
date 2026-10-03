#!/usr/bin/env bash
# Presentable 3-arm video runs on the two locked presentation maps.
# Sequential (one simulator at a time), fresh process per run, seed 42,
# num_envs 1 so the trace/render shows a single clean robot.
# Traces -> videos/Isaac-Nav-Openmover-v0/trace_<map>_seed42_<arm>.npz
# Results -> campaign/videos_present/results/<arm>_<map>.json
set -u
LAB=/home/zar/Documents/phd/robot/openmover_ws/isaac/lab
PY=/home/zar/isaaclab/_isaac_sim/python.sh
CKPT=$LAB/logs/rsl_rl/openmover_nav/bc_init_v3/model_0.pt
OUT=$LAB/campaign/videos_present
mkdir -p "$OUT/results" "$OUT/logs"

run_arm() {  # $1=map $2=steps $3=arm
  local map=$1 steps=$2 arm=$3
  local extra=()
  case $arm in
    shield)           extra=(--policy trained   --checkpoint "$CKPT" --shield) ;;
    astar_dwa)        extra=(--policy astar_dwa) ;;
    astar_dwa_shield) extra=(--policy astar_dwa --shield) ;;
  esac
  echo "[vid] === $arm $map (steps=$steps) $(date +%T) ==="
  ( cd /home/zar/isaaclab && env -u CONDA_PREFIX -u VIRTUAL_ENV -u PYTHONPATH \
    PYTHONUNBUFFERED=1 "$PY" "$LAB/21_run_openmover_nav.py" \
      --task Isaac-Nav-Openmover-v0 \
      --map_file "$LAB/maps/gen/$map.json" \
      "${extra[@]}" \
      --num_envs 1 --num_steps "$steps" --seed 42 --episode_cap 190.0 \
      --video --video_length "$steps" --tag "$arm" \
      --results_json "$OUT/results/${arm}_${map}.json" \
  ) > "$OUT/logs/${arm}_${map}.log" 2>&1
  echo "[vid] rc=$? $arm $map done $(date +%T)"
}

run_arm f4_b1_m00 1916 shield
run_arm f4_b1_m00 1916 astar_dwa
run_arm f4_b1_m00 1916 astar_dwa_shield
run_arm f6_b2_m00 2732 shield
run_arm f6_b2_m00 2732 astar_dwa
run_arm f6_b2_m00 2732 astar_dwa_shield
echo "[vid] ALL 6 RUNS DONE $(date +%T)"
