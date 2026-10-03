"""Clip a bridge trace npz to the driven segment for presentation renders.

The custom-map bridge (17_bridge_ros_custommap.py) records from its own loop
start (robot idle until the policy node boots) and keeps recording after the
goal is reached (the frozen policy has no stop-at-goal behaviour, so the
robot drifts/pins against a wall). For a legible presentation video we trim
to [first motion - pre, first arrival + post].

Usage:
    python3 28_clip_trace.py --trace videos/custommap_demo/trace_demo_crossings.npz
    # -> videos/custommap_demo/trace_demo_crossings_clip.npz
    python3 26_render_topdown_video.py --trace <clip> --fps 15 --title "..."
"""
import argparse
import json
import os

import numpy as np

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--trace", type=str, required=True)
p.add_argument("--out", type=str, default=None,
               help="default: <trace> with .npz replaced by _clip.npz")
p.add_argument("--fps", type=float, default=15.0,
               help="bridge records at 15 Hz")
p.add_argument("--pre", type=float, default=1.0,
               help="seconds of lead before first motion")
p.add_argument("--post", type=float, default=2.5,
               help="seconds kept after first goal arrival")
p.add_argument("--reach", type=float, default=0.30,
               help="arrival radius (policy GOAL_SUCCESS_DIST)")
p.add_argument("--map_file", type=str, default=None,
               help="map JSON; if it carries an ordered 'goals' list the "
                    "clip is split into one pseudo-episode per leg")
p.add_argument("--allow_unreached", action="store_true",
               help="if the goal is never reached, clip [motion-pre, end] "
                    "instead of exiting (failure-case videos)")
args = p.parse_args()

out = args.out or args.trace.replace(".npz", "_clip.npz")
if out == args.trace:
    out = args.trace + "_clip.npz"

d = np.load(args.trace)
traj = d["traj"]
ep_goal = d["ep_goal"]
ep_spawn = d["ep_spawn"]
ep_start = d["ep_start"]

goals = None
if args.map_file:
    with open(args.map_file) as f:
        _spec = json.load(f)
    if _spec.get("goals"):
        goals = [np.array([float(g[0]), float(g[1])])
                 for g in _spec["goals"]]

if goals:
    # serial task: arrival of leg k = first frame inside the reach radius
    # at/after the start of that leg; each leg becomes a pseudo-episode so
    # 26/29 render per-leg START/GOAL markers and HUD counters for free.
    starts, spawns, glist = [0], [traj[0, :2].copy()], []
    for gi, g in enumerate(goals):
        glist.append(g)
        dd = np.linalg.norm(traj[:, :2] - g, axis=1)
        hh = np.nonzero(dd < args.reach)[0]
        hh = hh[hh >= starts[-1]]
        if hh.size == 0:
            raise SystemExit(
                f"[clip] goal {gi} ({g[0]:.2f},{g[1]:.2f}) never reached "
                f"after frame {starts[-1]}; nothing sensible to clip")
        if gi < len(goals) - 1:
            starts.append(int(hh[0]))
            spawns.append(traj[hh[0], :2].copy())
    ep_start = np.asarray(starts)
    ep_spawn = np.asarray(spawns)
    ep_goal = np.asarray(glist)
    print(f"[clip] serial legs: arrivals at frames {starts}")
    dist = np.linalg.norm(traj[:, :2] - goals[-1], axis=1)
    hit = np.nonzero(dist < args.reach)[0]
    hit = hit[hit >= ep_start[-1]]
    spawn = spawns[0]
    ep0_end = len(traj)
else:
    goal = ep_goal[0]
    spawn = ep_spawn[0]
    # With num_envs>1 the env-0 trace can hold a success/timeout reset followed
    # by a second episode; keep the clip inside episode 0 so it never spans the
    # reset (which would teleport the robot back to spawn mid-video).
    ep0_end = int(ep_start[1]) if len(ep_start) > 1 else len(traj)
    dist = np.linalg.norm(traj[:ep0_end, :2] - goal, axis=1)
    hit = np.nonzero(dist < args.reach)[0]

moved = np.linalg.norm(traj[:ep0_end, :2] - spawn, axis=1)
mv = np.nonzero(moved > 0.05)[0]
if mv.size == 0 or (hit.size == 0 and not args.allow_unreached):
    raise SystemExit("[clip] trace never moves or never reaches the goal; "
                     "nothing sensible to clip")
k0 = max(int(mv[0] - args.pre * args.fps), 0)
if hit.size:
    k1 = min(int(hit[0] + args.post * args.fps), ep0_end)
else:
    k1 = ep0_end
    print("[clip] goal never reached: clipping to end of episode 0 "
          "(failure-case video)")

# keep only episode markers that fall inside the clip, re-based to it, so the
# renderers never index a reset that was trimmed away
keep = ep_start < k1
np.savez(out,
         traj=traj[k0:k1],
         lidar=d["lidar"][k0:k1],
         ep_goal=ep_goal[keep],
         ep_spawn=ep_spawn[keep],
         ep_start=np.maximum(ep_start[keep] - k0, 0),
         occ=d["occ"],
         origin=d["origin"],
         size=d["size"])
arr = (f"arrival frame {hit[0]} (t={hit[0] / args.fps:.2f}s)"
       if hit.size else "goal never reached")
print(f"[clip] motion frame {mv[0]} (t={mv[0] / args.fps:.2f}s), {arr}, "
      f"clip [{k0}:{k1}] = {k1 - k0} frames ({(k1 - k0) / args.fps:.1f}s) -> {out}")
