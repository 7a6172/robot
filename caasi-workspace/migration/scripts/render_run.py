#!/usr/bin/env python3
"""Render a run as a visual report: map + trajectory + aligned scans + odometry.

Purpose: give a human something to look at, for both ROS 1 and ROS 2, to judge whether the
robot behaved sensibly. It reads only recorded data, so it needs no display, no robot and no
running stack -- which also makes the two systems directly comparable.

    render_run.py --map map.pgm --map-yaml map.yaml --trace trace.json --out fig.png \
                  --title "ROS 1 gmapping run"

The trace JSON is produced by extract_bag.py (ROS 1) or trace_to_json (ROS 2); it holds
`odom` poses, `map_to_odom` poses and periodic `scans`.
"""
from __future__ import annotations

import argparse
import json
import math

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load_pgm(path):
    data = open(path, "rb").read()
    i, fields = 0, []
    while len(fields) < 4:
        while data[i:i + 1].isspace():
            i += 1
        if data[i:i + 1] == b"#":
            while data[i:i + 1] != b"\n":
                i += 1
            continue
        j = i
        while not data[j:j + 1].isspace():
            j += 1
        fields.append(data[i:j])
        i = j
    w, h = int(fields[1]), int(fields[2])
    return np.frombuffer(data[i + 1:i + 1 + w * h], dtype=np.uint8).reshape(h, w), w, h


def load_map_yaml(path):
    """resolution and origin, from either the inline or the block YAML form."""
    import re
    text = open(path).read()
    res = 0.05
    m = re.search(r"^resolution:\s*([0-9.eE+-]+)", text, re.M)
    if m:
        res = float(m.group(1))
    ox = oy = 0.0
    m = re.search(r"^origin:\s*\[\s*([-0-9.eE+]+)\s*,\s*([-0-9.eE+]+)", text, re.M)
    if m:
        ox, oy = float(m.group(1)), float(m.group(2))
    else:
        m = re.search(r"^origin:\s*\n\s*-\s*([-0-9.eE+]+)\s*\n\s*-\s*([-0-9.eE+]+)",
                      text, re.M)
        if m:
            ox, oy = float(m.group(1)), float(m.group(2))
    return res, ox, oy


def yaw_apply(x, y, yaw, pts):
    c, s = math.cos(yaw), math.sin(yaw)
    return x + pts[:, 0] * c - pts[:, 1] * s, y + pts[:, 0] * s + pts[:, 1] * c


def scan_points(scan):
    r = np.array([v if v is not None and 0.25 <= v <= 25.0 else np.nan
                  for v in scan["ranges"]])
    ang = scan["angle_min"] + np.arange(len(r)) * scan["angle_increment"]
    ok = np.isfinite(r)
    return np.stack([r[ok] * np.cos(ang[ok]), r[ok] * np.sin(ang[ok])], axis=1)


def map_pose_at(trace, t):
    """Pose in the map frame at time t: map->odom composed with odom->base_link."""
    odom = trace["odom"]
    m2o = trace.get("map_to_odom") or []
    pose = min(odom, key=lambda p: abs(p["t"] - t))
    if not m2o:
        return pose["x"], pose["y"], pose["yaw"]
    tf = min(m2o, key=lambda p: abs(p["t"] - t))
    c, s = math.cos(tf["yaw"]), math.sin(tf["yaw"])
    x = tf["x"] + pose["x"] * c - pose["y"] * s
    y = tf["y"] + pose["x"] * s + pose["y"] * c
    return x, y, pose["yaw"] + tf["yaw"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True)
    ap.add_argument("--map-yaml", required=True)
    ap.add_argument("--trace", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="run")
    ap.add_argument("--max-scans", type=int, default=6)
    args = ap.parse_args()

    trace = json.load(open(args.trace))
    occ, w, h = load_pgm(args.map)
    res, ox, oy = load_map_yaml(args.map_yaml)

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.suptitle(args.title, fontsize=14)

    # --- panel 1: map + trajectory in the map frame
    ax = axes[0]
    ax.imshow(occ, cmap="gray", origin="upper",
              extent=[ox, ox + w * res, oy, oy + h * res])
    poses = [map_pose_at(trace, p["t"]) for p in trace["odom"]]
    if poses:
        xs = [p[0] for p in poses]; ys = [p[1] for p in poses]
        ax.plot(xs, ys, "-", color="#1f77b4", lw=1.2, label="trajectory")
        ax.plot(xs[0], ys[0], "o", color="green", ms=8, label="start")
        ax.plot(xs[-1], ys[-1], "s", color="red", ms=8, label="end")
    ax.set_title("map and travelled path")
    ax.set_xlabel("x [m]"); ax.set_ylabel("y [m]"); ax.legend(loc="best", fontsize=8)
    ax.set_aspect("equal")

    # --- panel 2: scan overlay, to see whether hits line up with walls
    ax = axes[1]
    ax.imshow(occ, cmap="gray", origin="upper",
              extent=[ox, ox + w * res, oy, oy + h * res])
    scans = trace["scans"]
    step = max(1, len(scans) // args.max_scans)
    misalignment = []
    for scan in scans[::step]:
        x, y, yaw = map_pose_at(trace, scan["t"])
        pts = scan_points(scan)
        if not len(pts):
            continue
        px, py = yaw_apply(x, y, yaw, pts)
        ax.plot(px, py, ".", ms=1.0, alpha=0.6)
        # distance from each hit to the nearest occupied map cell, for a numeric check
        col = ((px - ox) / res).astype(int); row = (h - 1 - ((py - oy) / res)).astype(int)
        inside = (col >= 0) & (col < w) & (row >= 0) & (row < h)
        if inside.any():
            occmask = occ < 100
            ys_, xs_ = np.nonzero(occmask)
            if len(xs_):
                wx = ox + (xs_ + 0.5) * res; wy = oy + (h - 1 - ys_ + 0.5) * res
                d = np.sqrt((px[inside][:, None] - wx[None, :]) ** 2 +
                            (py[inside][:, None] - wy[None, :]) ** 2).min(axis=1)
                misalignment.append(float(np.median(d)))
    ax.set_title("laser hits in the map frame"
                 + (f"\nmedian offset {np.median(misalignment)*100:.1f} cm" if misalignment else ""))
    ax.set_xlabel("x [m]"); ax.set_ylabel("y [m]"); ax.set_aspect("equal")

    # --- panel 3: odometry over time
    ax = axes[2]
    ts = np.array([p["t"] for p in trace["odom"]])
    if len(ts):
        ts = ts - ts[0]
        ax.plot(ts, [p["x"] for p in trace["odom"]], label="x [m]")
        ax.plot(ts, [p["y"] for p in trace["odom"]], label="y [m]")
        ax.plot(ts, [p["yaw"] for p in trace["odom"]], label="yaw [rad]", alpha=0.7)
        ax.set_xlabel("time [s]"); ax.set_ylabel("value"); ax.legend(fontsize=8)
        ax.set_title("odometry over the run")
        ax.grid(alpha=0.3)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(args.out, dpi=110)
    print(f"wrote {args.out}")
    if misalignment:
        print(f"median scan-to-map offset: {np.median(misalignment)*100:.1f} cm")


if __name__ == "__main__":
    main()
