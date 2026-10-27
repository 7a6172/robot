#!/usr/bin/env python3
"""Render a map alone, large and clean, for a human to inspect the maze layout."""
import argparse, json, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from render_run import load_pgm, load_map_yaml

ap = argparse.ArgumentParser()
ap.add_argument("--map", required=True); ap.add_argument("--map-yaml", required=True)
ap.add_argument("--out", required=True); ap.add_argument("--title", default="map")
ap.add_argument("--trace")
args = ap.parse_args()

occ, w, h = load_pgm(args.map)
res, ox, oy = load_map_yaml(args.map_yaml)
fig, ax = plt.subplots(figsize=(9, 10))
ax.imshow(occ, cmap="gray", origin="upper", extent=[ox, ox + w * res, oy, oy + h * res])
ax.set_title(args.title)
ax.set_xlabel("x [m]"); ax.set_ylabel("y [m]"); ax.set_aspect("equal")
# grid every metre, to read positions off the figure
ax.set_xticks(np.arange(np.floor(ox), ox + w * res + 1, 1.0))
ax.set_yticks(np.arange(np.floor(oy), oy + h * res + 1, 1.0))
ax.grid(alpha=0.25, lw=0.4)
if args.trace:
    trace = json.load(open(args.trace))
    xs = [p["x"] for p in trace["odom"]]; ys = [p["y"] for p in trace["odom"]]
    ax.plot(xs, ys, "-", color="#1f77b4", lw=1.0, alpha=0.8)
fig.tight_layout()
fig.savefig(args.out, dpi=130)
print(f"wrote {args.out}")
