"""34_aggregate_campaign.py -- aggregate the 3-arm campaign results for paper_v2.

Reads campaign/results/{arm}/{map}.json (produced by 33_run_campaign.py) plus
maps/gen/_manifest.json and pools EPISODE-LEVEL statistics (not mean-of-means:
presentation maps carry 10 seeds vs 4 elsewhere, so episode weighting is the
honest aggregate).

Outputs:
  campaign/aggregate.json   machine-readable, every table below
  stdout                    markdown tables (overall, per-bin, per-family,
                            presentation maps, shield/baseline instrument sums)

Usage:
  python3 34_aggregate_campaign.py [--campaign_dir campaign] [--markdown]
Runs while the campaign is still going: incomplete (map, arm) cells are
reported as missing, everything present is aggregated.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

LAB = Path(__file__).resolve().parent
ARMS = ("shield", "astar_dwa", "astar_dwa_shield")
ARM_LABEL = {
    "shield": "trained+shield",
    "astar_dwa": "A*+DWA",
    "astar_dwa_shield": "A*+DWA+shield",
}
PRESENTATION = ("f4_b1_m00", "f6_b2_m00")
EXPECTED_MAPS = 56


def load_runs(results_dir: Path):
    """arm -> map_stem -> result dict (complete runs only)."""
    runs = defaultdict(dict)
    incomplete = []
    for arm in ARMS:
        d = results_dir / arm
        if not d.exists():
            continue
        for p in sorted(d.glob("*.json")):
            try:
                r = json.loads(p.read_text())
            except Exception as e:
                incomplete.append((arm, p.stem, f"unreadable: {e}"))
                continue
            per_env = r.get("per_env")
            n = r.get("n_first_episodes")
            if not per_env or n != len(per_env):
                incomplete.append((arm, p.stem, f"n_first_episodes={n} "
                                   f"per_env={len(per_env) if per_env else 0}"))
                continue
            runs[arm][p.stem] = r
    return runs, incomplete


def pool(rows):
    """Episode-pooled success/collision/ttg over a list of result dicts."""
    reached = penalized = episodes = 0
    ttg_ok = []
    for r in rows:
        for e in r["per_env"]:
            episodes += 1
            reached += bool(e["reached"])
            penalized += bool(e["penalized"])
            if e["reached"] and e.get("ttg") is not None:
                ttg_ok.append(e["ttg"])
    if not episodes:
        return None
    return {
        "n_maps": len(rows),
        "episodes": episodes,
        "success": reached / episodes,
        "collision": penalized / episodes,
        "reached": reached,
        "penalized": penalized,
        "ttg_success_mean": (sum(ttg_ok) / len(ttg_ok)) if ttg_ok else None,
        "ttg_success_n": len(ttg_ok),
    }


def key_sum(rows, section, keys):
    out = defaultdict(int)
    for r in rows:
        s = r.get(section) or {}
        for k in keys:
            out[k] += s.get(k, 0) or 0
    return dict(out)


def group(runs_arm, manifest, keyfn):
    g = defaultdict(list)
    for stem, r in runs_arm.items():
        g[keyfn(stem, r)].append(r)
    return {k: pool(v) for k, v in sorted(g.items())}


def fmt(x, nd=3):
    return "  --  " if x is None else f"{x:.{nd}f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--campaign_dir", type=str, default=str(LAB / "campaign"))
    ap.add_argument("--markdown", action="store_true", default=True)
    args = ap.parse_args()
    cdir = Path(args.campaign_dir).resolve()
    manifest = json.loads((LAB / "maps" / "gen" / "_manifest.json").read_text())

    runs, incomplete = load_runs(cdir / "results")

    agg = {"campaign_dir": str(cdir), "arms": {}}
    for arm in ARMS:
        runs_arm = runs.get(arm, {})
        rows = list(runs_arm.values())
        entry = {
            "overall": pool(rows),
            "per_bin": group(runs_arm, manifest,
                             lambda s, r: manifest[s]["bin"]),
            "per_family": group(runs_arm, manifest,
                                lambda s, r: manifest[s]["family"]),
            "presentation": {m: pool([runs_arm[m]])
                             for m in PRESENTATION if m in runs_arm},
            "shield_totals": key_sum(
                rows, "shield_stats",
                ("shield", "hyst", "escape", "retreat", "pin", "oob", "steps")),
            "baseline_totals": key_sum(
                rows, "baseline_stats",
                ("plan", "replan", "dwa_reject", "stuck", "steps")),
            "maps_done": sorted(runs_arm.keys()),
        }
        agg["arms"][arm] = entry
    agg["incomplete"] = [{"arm": a, "map": m, "why": w}
                         for a, m, w in incomplete]

    out = cdir / "aggregate.json"
    out.write_text(json.dumps(agg, indent=1))
    print(f"wrote {out}")
    n_done = {a: len(agg["arms"][a]["maps_done"]) for a in ARMS}
    print(f"maps complete per arm: {n_done} (of {EXPECTED_MAPS})")
    for a, m, w in incomplete:
        print(f"  INCOMPLETE {a}/{m}: {w}")

    # ---- markdown tables ----
    print("\n## Overall (episode-pooled)\n")
    print("| arm | maps | episodes | success | collision | TTG succ (s) |")
    print("|---|---|---|---|---|---|")
    for arm in ARMS:
        o = agg["arms"][arm]["overall"]
        if o is None:
            print(f"| {ARM_LABEL[arm]} | 0 | 0 | -- | -- | -- |")
            continue
        print(f"| {ARM_LABEL[arm]} | {o['n_maps']} | {o['episodes']} | "
              f"{fmt(o['success'])} | {fmt(o['collision'])} | "
              f"{fmt(o['ttg_success_mean'], 1)} |")

    print("\n## By difficulty bin (success / collision)\n")
    bins = sorted({manifest[s]["bin"] for s in manifest})
    header = "| arm | " + " | ".join(f"b{b}" for b in bins) + " |"
    print(header)
    print("|---" * (len(bins) + 1) + "|")
    for arm in ARMS:
        cells = []
        for b in bins:
            e = agg["arms"][arm]["per_bin"].get(str(b)) or \
                agg["arms"][arm]["per_bin"].get(b)
            cells.append("--" if e is None
                         else f"{e['success']:.2f} / {e['collision']:.2f}")
        print(f"| {ARM_LABEL[arm]} | " + " | ".join(cells) + " |")

    print("\n## By family (success / collision)\n")
    fams = sorted({manifest[s]["family"] for s in manifest})
    print("| arm | " + " | ".join(fams) + " |")
    print("|---" * (len(fams) + 1) + "|")
    for arm in ARMS:
        cells = []
        for f in fams:
            e = agg["arms"][arm]["per_family"].get(f)
            cells.append("--" if e is None
                         else f"{e['success']:.2f} / {e['collision']:.2f}")
        print(f"| {ARM_LABEL[arm]} | " + " | ".join(cells) + " |")

    print("\n## Presentation maps (10 seeds)\n")
    print("| map | arm | success | collision | TTG succ (s) |")
    print("|---|---|---|---|---|")
    for m in PRESENTATION:
        for arm in ARMS:
            e = agg["arms"][arm]["presentation"].get(m)
            if e is None:
                print(f"| {m} | {ARM_LABEL[arm]} | -- | -- | -- |")
            else:
                print(f"| {m} | {ARM_LABEL[arm]} | {fmt(e['success'])} | "
                      f"{fmt(e['collision'])} | "
                      f"{fmt(e['ttg_success_mean'], 1)} |")

    print("\n## Shield instrument (totals over completed shielded runs)\n")
    print("| arm | shield ticks | hyst | escape | retreat | pin | oob | steps |")
    print("|---|---|---|---|---|---|---|---|")
    for arm in ("shield", "astar_dwa_shield"):
        t = agg["arms"][arm]["shield_totals"]
        print(f"| {ARM_LABEL[arm]} | {t.get('shield', 0)} | {t.get('hyst', 0)} "
              f"| {t.get('escape', 0)} | {t.get('retreat', 0)} | "
              f"{t.get('pin', 0)} | {t.get('oob', 0)} | {t.get('steps', 0)} |")


if __name__ == "__main__":
    main()
