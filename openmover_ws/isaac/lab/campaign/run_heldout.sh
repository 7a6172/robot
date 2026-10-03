#!/usr/bin/env bash
# Held-out endgame: 3-arm statistics runs on the user-drawn map maps/heldout.json.
# Mirrors the campaign/presentation protocol EXACTLY (num_envs=10, seed 42,
# episode_cap 190.0); num_steps = ceil(horizon/0.05)+20 where
# horizon = min(path_len/0.25 + 10, cap) = min(34.38/0.25+10, 190) = 147.52 s
# -> 2971 steps. Sequential (one simulator at a time), fresh process per arm,
# bounded by a per-arm kill-guard. Results -> heldout/results/<arm>/heldout.json
set -u
LAB=/home/zar/Documents/phd/robot/openmover_ws/isaac/lab
PY=/home/zar/isaaclab/_isaac_sim/python.sh
CKPT=$LAB/logs/rsl_rl/openmover_nav/bc_init_v3/model_0.pt
OUT=$LAB/campaign/heldout
MAP=$LAB/maps/heldout.json
STEPS=2971
ENVIRON=10
CAP=190.0
# per-arm kill-guard: 600 s startup + steps*envs/min_rate(=50 env-steps/s) ~ 1194 s;
# round up to a generous 1800 s (expected wall-time ~2-6 min/arm).
GUARD=1800
mkdir -p "$OUT/results/shield" "$OUT/results/astar_dwa" "$OUT/results/astar_dwa_shield" "$OUT/logs"
: > "$OUT/results.jsonl"

run_arm() {  # $1=arm
  local arm=$1
  local extra=()
  case $arm in
    shield)           extra=(--policy trained   --checkpoint "$CKPT" --shield) ;;
    astar_dwa)        extra=(--policy astar_dwa) ;;
    astar_dwa_shield) extra=(--policy astar_dwa --shield) ;;
    *) echo "[heldout] UNKNOWN ARM $arm"; return 2 ;;
  esac
  # RAM guard: abort if <4 GiB available (RAM+swap) before starting a simulator.
  local avail
  avail=$(free -m | awk '/^Mem:/{print $7}')
  echo "[heldout] === $arm  avail_RAM=${avail}MiB  $(date +%T) ==="
  if [ "${avail:-0}" -lt 4096 ]; then
    echo "[heldout] ABORT $arm: only ${avail} MiB available (<4096)"; return 3
  fi
  ( cd /home/zar/isaaclab && env -u CONDA_PREFIX -u VIRTUAL_ENV -u PYTHONPATH \
    PYTHONUNBUFFERED=1 timeout "$GUARD" "$PY" "$LAB/21_run_openmover_nav.py" \
      --task Isaac-Nav-Openmover-v0 \
      --map_file "$MAP" \
      "${extra[@]}" \
      --num_envs "$ENVIRON" --num_steps "$STEPS" --seed 42 --episode_cap "$CAP" \
      --results_json "$OUT/results/$arm/heldout.json" \
  ) > "$OUT/logs/$arm.log" 2>&1
  local rc=$?
  echo "[heldout] rc=$rc $arm done $(date +%T)"
  if [ -f "$OUT/results/$arm/heldout.json" ]; then
    python3 - "$OUT/results/$arm/heldout.json" "$arm" <<'PYEOF' >> "$OUT/results.jsonl"
import json,sys
d=json.load(open(sys.argv[1])); d["arm"]=sys.argv[2]
print(json.dumps({k:d.get(k) for k in
  ("arm","map","policy","shield","seed","num_envs","num_steps","horizon_s",
   "n_first_episodes","mean_success","mean_collision","mean_ttg_success",
   "baseline_stats","shield_stats")}))
PYEOF
    echo "[heldout]   -> $(tail -1 "$OUT/results.jsonl")"
  else
    echo "[heldout]   -> NO RESULT JSON (see logs/$arm.log)"
  fi
}

echo "[heldout] START 3-arm held-out batch on $(basename "$MAP") $(date +%T)"
run_arm shield
run_arm astar_dwa
run_arm astar_dwa_shield
echo "[heldout] ALL 3 HELD-OUT RUNS DONE $(date +%T)"
