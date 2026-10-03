"""Campaign runner: three arms over the 56-map procedural pool.

Arms (locked by user decision after the corridor-family diagnosis, ledger
§17.17):
  shield           = frozen BC policy + ShieldLite   (learned + guarantee)
  astar_dwa        = A*+DWA, unprotected             (classical competence)
  astar_dwa_shield = A*+DWA + ShieldLite             (thesis arm: planner
                     competence + shield guarantee -> expect high success AND
                     zero collisions)

One Isaac subprocess per (map, arm); the seed axis (initial yaw — the only
per-episode randomness on fixed custom maps) is folded into num_envs=N and
split back out via --results_json first-episode capture, giving per-map
mean +/- std for success / collision / time-to-goal.

Rules enforced here (standing project rules):
  - ONE simulator at a time (strictly sequential subprocesses).
  - RAM guard: wait until >= 8 GiB available before each launch.
  - Bounded: per-run wall timeout kills runaway processes.
  - Resume: (map, arm) pairs with a complete results JSON are skipped.
  - Everything kept: per-run JSONs, subprocess logs, results.jsonl ledger.

Usage (system python3 — no torch needed here):
    python3 33_run_campaign.py --dry_run                 # plan + cost estimate
    python3 33_run_campaign.py --maps f6_b2_m00 --seeds 4   # validate on one map
    python3 33_run_campaign.py                           # full core campaign

Presentation maps (f4_b1_m00, f6_b2_m00) use --presentation_seeds (10) so the
locked 10-seed repeats come out of the same pass.
"""

import argparse
import json
import math
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

LAB = Path(__file__).resolve().parent
ISAACLAB = Path.home() / "isaaclab"
RUNNER = LAB / "21_run_openmover_nav.py"
MAPS = LAB / "maps" / "gen"
PRESENTATION = ("f4_b1_m00", "f6_b2_m00")
ARMS = ("shield", "astar_dwa", "astar_dwa_shield")
# camp6b frozen BC checkpoint (absolute: subprocess cwd is ~/isaaclab)
CHECKPOINT = str(LAB / "logs/rsl_rl/openmover_nav/bc_init_v3/model_0.pt")
STEP_DT = 0.05  # 20 Hz (decimation 6)


def mem_available_gib() -> float:
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / (1024 * 1024)
    raise RuntimeError("MemAvailable not found in /proc/meminfo")


def wait_for_ram(min_gib: float):
    while True:
        avail = mem_available_gib()
        if avail >= min_gib:
            return
        print(f"[camp] RAM guard: {avail:.1f} GiB available < {min_gib}, "
              f"waiting 30 s ...", flush=True)
        time.sleep(30)


def plan_run(map_stem: str, arm: str, seeds: int, pl: float, args) -> dict:
    """Build the subprocess command + expectations for one (map, arm)."""
    horizon = min(pl / 0.25 + 10.0, args.episode_cap)  # same formula as runner
    steps = int(math.ceil(horizon / STEP_DT)) + 20     # first episodes all end
    policy = "trained" if arm == "shield" else "astar_dwa"
    cmd = [
        str(ISAACLAB / "_isaac_sim" / "python.sh"), str(RUNNER),
        "--task", "Isaac-Nav-Openmover-v0",
        "--map_file", str(MAPS / f"{map_stem}.json"),
        "--policy", policy,
        "--num_envs", str(seeds),
        "--num_steps", str(steps),
        "--seed", str(args.seed),
        "--episode_cap", str(args.episode_cap),
        "--results_json", str(args.out / "results" / arm / f"{map_stem}.json"),
    ]
    if policy == "trained":
        cmd += ["--checkpoint", args.checkpoint]
    if arm in ("shield", "astar_dwa_shield"):
        cmd += ["--shield"]
    # kill guard: assume the worst observed throughput (~9 env-steps/s with
    # video+shield) plus generous Isaac startup
    timeout = 600 + steps * seeds / max(args.min_rate, 1.0)
    return {"map": map_stem, "arm": arm, "seeds": seeds, "path_len": pl,
            "horizon": horizon, "steps": steps, "cmd": cmd, "timeout": timeout}


def run_one(run: dict, args) -> dict:
    log_path = args.out / "logs" / f"{run['arm']}_{run['map']}.log"
    json_path = args.out / "results" / run["arm"] / f"{run['map']}.json"
    print(f"[camp] === {run['arm']:16s} {run['map']} "
          f"(seeds={run['seeds']}, horizon={run['horizon']:.0f} s, "
          f"steps={run['steps']}) ===", flush=True)
    print(f"[camp] cmd: {' '.join(shlex.quote(c) for c in run['cmd'])}", flush=True)
    t0 = time.time()
    # python.sh directly (not `isaaclab.sh -p`): the isaaclab.cli dispatcher
    # exits immediately (rc=0) on this install, orphaning the real sim process
    # — wait()/timeout/RAM guard would watch nothing. Strip conda/venv vars so
    # the Kit interpreter runs with its own environment.
    env = {k: v for k, v in os.environ.items()
           if k not in ("CONDA_PREFIX", "VIRTUAL_ENV", "PYTHONPATH")}
    env["PYTHONUNBUFFERED"] = "1"
    with open(log_path, "w") as logf:
        proc = subprocess.Popen(
            run["cmd"], cwd=str(ISAACLAB), stdout=logf,
            stderr=subprocess.STDOUT, env=env)
        try:
            rc = proc.wait(timeout=run["timeout"])
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            rc = -999
            print(f"[camp] TIMEOUT after {run['timeout']:.0f} s — killed",
                  flush=True)
    wall = time.time() - t0
    rec = {"map": run["map"], "arm": run["arm"], "seeds": run["seeds"],
           "returncode": rc, "wall_s": round(wall, 1),
           "log": str(log_path), "json": str(json_path)}
    if json_path.exists():
        res = json.loads(json_path.read_text())
        rec.update({
            "n_first_episodes": res.get("n_first_episodes"),
            "mean_success": res.get("mean_success"),
            "mean_collision": res.get("mean_collision"),
            "mean_ttg_success": res.get("mean_ttg_success"),
            # off-model instrument: env-ticks the shield saw the robot outside
            # the map rectangle (the barrier's domain) -- the guarantee audit
            "shield_oob": (res.get("shield_stats") or {}).get("oob"),
        })
        if res.get("n_first_episodes") != run["seeds"]:
            print(f"[camp] WARNING: captured {res.get('n_first_episodes')}/"
                  f"{run['seeds']} first episodes", flush=True)
    else:
        print(f"[camp] FAILED: no results JSON (rc={rc}); see {log_path}",
              flush=True)
    print(f"[camp] done in {wall:.0f} s: success={rec.get('mean_success')} "
          f"collision={rec.get('mean_collision')} "
          f"ttg={rec.get('mean_ttg_success')}", flush=True)
    with open(args.out / "results.jsonl", "a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def complete(json_path: Path, seeds: int) -> bool:
    if not json_path.exists():
        return False
    try:
        res = json.loads(json_path.read_text())
    except Exception:
        return False
    return res.get("n_first_episodes") == seeds


def summarize(args, records):
    """Per-arm aggregate over completed runs -> summary.json + printed table."""
    summary = {}
    for arm in args.arms:
        rows = [json.loads(p.read_text())
                for p in (args.out / "results" / arm).glob("*.json")
                if p.exists()] if (args.out / "results" / arm).exists() else []
        rows = [r for r in rows if r.get("mean_success") is not None]
        if not rows:
            summary[arm] = {"n_maps": 0}
            continue
        succ = [r["mean_success"] for r in rows]
        coll = [r["mean_collision"] for r in rows]
        ttg = [r["mean_ttg_success"] for r in rows
               if r.get("mean_ttg_success") is not None]
        fams = {}
        manifest = json.loads((MAPS / "_manifest.json").read_text())
        for r in rows:
            fam = manifest.get(r["map"], {}).get("family", "?")
            fams.setdefault(fam, []).append(r)
        summary[arm] = {
            "n_maps": len(rows),
            "success_mean_of_means": sum(succ) / len(succ),
            "collision_mean_of_means": sum(coll) / len(coll),
            "ttg_mean": (sum(ttg) / len(ttg)) if ttg else None,
            "per_family": {
                f: {"n": len(v),
                    "success": sum(x["mean_success"] for x in v) / len(v),
                    "collision": sum(x["mean_collision"] for x in v) / len(v)}
                for f, v in sorted(fams.items())},
        }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1))
    print("\n[camp] ===== summary =====")
    for arm, s in summary.items():
        if not s.get("n_maps"):
            print(f"[camp] {arm}: no completed runs")
            continue
        print(f"[camp] {arm}: {s['n_maps']} maps | success="
              f"{s['success_mean_of_means']:.3f} | collision="
              f"{s['collision_mean_of_means']:.3f} | ttg="
              f"{s['ttg_mean'] if s['ttg_mean'] is None else round(s['ttg_mean'], 1)} s")
        for f, v in s["per_family"].items():
            print(f"[camp]   {f:12s} n={v['n']:2d} success={v['success']:.3f} "
                  f"collision={v['collision']:.3f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arms", type=str, default=",".join(ARMS))
    ap.add_argument("--maps", type=str, default="all",
                    help="'all' | 'presentation' | comma-separated stems")
    ap.add_argument("--seeds", type=int, default=4,
                    help="seeds folded into num_envs per (map, arm)")
    ap.add_argument("--presentation_seeds", type=int, default=10,
                    help="seeds for f4_b1_m00 / f6_b2_m00 (locked 10-seed repeats)")
    ap.add_argument("--seed", type=int, default=42, help="torch seed for runs")
    ap.add_argument("--episode_cap", type=float, default=190.0)
    ap.add_argument("--checkpoint", type=str, default=CHECKPOINT)
    ap.add_argument("--min_rate", type=float, default=9.0,
                    help="worst-case env-steps/s used for the kill-guard timeout")
    ap.add_argument("--min_ram_gib", type=float, default=8.0)
    ap.add_argument("--out", type=str, default=str(LAB / "campaign"))
    ap.add_argument("--force", action="store_true",
                    help="re-run (map, arm) pairs that already have results")
    ap.add_argument("--dry_run", action="store_true",
                    help="print the plan + wall-clock estimate, launch nothing")
    args = ap.parse_args()
    args.arms = [a.strip() for a in args.arms.split(",")]
    for a in args.arms:
        if a not in ARMS:
            sys.exit(f"unknown arm '{a}' (choices: {ARMS})")
    args.out = Path(args.out).resolve()  # subprocess cwd is ~/isaaclab: a
    # relative --out would send --results_json there instead of here
    for arm in ARMS:
        (args.out / "results" / arm).mkdir(parents=True, exist_ok=True)
    (args.out / "logs").mkdir(parents=True, exist_ok=True)

    manifest = json.loads((MAPS / "_manifest.json").read_text())
    if args.maps == "all":
        map_stems = sorted(manifest.keys())
    elif args.maps == "presentation":
        map_stems = list(PRESENTATION)
    else:
        map_stems = [m.strip() for m in args.maps.split(",")]
        for m in map_stems:
            if m not in manifest:
                sys.exit(f"map '{m}' not in manifest")

    plan = []
    for stem in map_stems:
        seeds = args.presentation_seeds if stem in PRESENTATION else args.seeds
        for arm in args.arms:
            run = plan_run(stem, arm, seeds,
                           float(manifest[stem]["path_len"]), args)
            jp = args.out / "results" / arm / f"{stem}.json"
            if complete(jp, seeds) and not args.force:
                continue
            plan.append(run)

    # dry-run cost estimate from MEASURED walls (results.jsonl): f1_b0_m00 4-seed
    # runs 71-100 s, f6_b2_m00 10-seed runs 138-158 s => ~40 s Isaac startup +
    # ~150 env-steps/s for every arm (shield/baseline host-side cost is small
    # next to the sim). Earlier 20/40 env-steps/s guesses overestimated the
    # 3-arm campaign at 20 h; measured rate puts it near 4-5 h.
    est = 0.0
    print(f"[camp] plan: {len(plan)} runs "
          f"({len(map_stems)} maps x arms {args.arms})")
    for run in plan:
        w = 40 + run["steps"] * run["seeds"] / 150.0  # startup + sim
        est += w
        print(f"[camp]   {run['arm']:16s} {run['map']} seeds={run['seeds']} "
              f"horizon={run['horizon']:.0f}s steps={run['steps']} "
              f"est~{w / 60:.1f} min")
    print(f"[camp] estimated total wall clock: {est / 3600:.2f} h")
    if args.dry_run or not plan:
        if not plan:
            summarize(args, [])
        return

    records = []
    for k, run in enumerate(plan, 1):
        print(f"\n[camp] [{k}/{len(plan)}] ", end="", flush=True)
        wait_for_ram(args.min_ram_gib)
        records.append(run_one(run, args))
    n_fail = sum(1 for r in records if r.get("mean_success") is None)
    print(f"\n[camp] campaign pass complete: {len(records) - n_fail}/"
          f"{len(records)} runs produced results ({n_fail} failed)")
    summarize(args, records)


if __name__ == "__main__":
    main()
