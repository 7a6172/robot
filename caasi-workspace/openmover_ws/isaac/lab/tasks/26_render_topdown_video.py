"""Render a top-down 2D trace video from a trace npz written by 21_run_*.py --video.

Presentation tool (paper figures / readable demos): walls from the env's occupancy
grid, blue START disc, green GOAL star + success ring, crimson trajectory trace,
oriented robot wedge, cyan geodesic-waypoint marker, and the LiDAR fan (world-frame
hit points recorded every step; misses are NaN).

Trace schema (new, 2026-09): traj (T,3) x,y,yaw | wp (T,2) world frame |
lidar (T,300,2) world-frame hit points, first 150 = front scanner, last 150 = rear,
NaN = missed ray | ep_goal/ep_spawn (E,2) | ep_start (E,) | occ (gy,gx) bool |
origin (2,) | size (2,). Old traces without wp/lidar still render (overlays skipped).

Usage:
    python3 26_render_topdown_video.py --trace videos/<task>/trace_seed16.npz \
        [--out videos/<task>/trace_seed16.topdown.mp4] [--fps 20] [--title "..."]
"""

import argparse
import subprocess
import tempfile
from pathlib import Path

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

parser = argparse.ArgumentParser(description="Top-down trace video renderer.")
parser.add_argument("--trace", type=str, required=True)
parser.add_argument("--out", type=str, default=None)
parser.add_argument("--fps", type=int, default=20)
parser.add_argument("--title", type=str, default=None)
parser.add_argument("--stride", type=int, default=1,
                    help="render every Nth trace step (e.g. 4 on a 20 Hz trace "
                         "at --fps 5 = real-time playback, 4x fewer frames)")
args = parser.parse_args()

trace_path = Path(args.trace)
data = np.load(trace_path)
traj = data["traj"]            # (T, 3) x, y, yaw
ep_goal = data["ep_goal"]      # (E, 2)
ep_spawn = data["ep_spawn"]    # (E, 2)
ep_start = data["ep_start"]    # (E,)
occ = data["occ"]              # (gy, gx) bool
origin = data["origin"]        # (2,) tile center in world coords
size = data["size"]            # (2,) tile extent
wp = data["wp"] if "wp" in data.files else None            # (T, 2) or None
lidar = data["lidar"] if "lidar" in data.files else None   # (T, 300, 2) or None

# optional temporal decimation (ep_start is in original-step units; the HUD's
# searchsorted stays consistent because the strided t is also original-step)
if args.stride > 1:
    traj = traj[::args.stride]
    if wp is not None:
        wp = wp[::args.stride]
    if lidar is not None:
        lidar = lidar[::args.stride]

out_path = Path(args.out) if args.out else trace_path.with_suffix(".topdown.mp4")
tile_x0, tile_x1 = origin[0] - size[0] / 2, origin[0] + size[0] / 2
tile_y0, tile_y1 = origin[1] - size[1] / 2, origin[1] + size[1] / 2

# view window in meters, aspect-matched to the 16:9 frame so the static
# occupancy canvas blits 1:1 (no letterbox scaling, no flip)
FIG_W, FIG_H = 10.24, 5.76
x_half, y_half = 0.5 * size[0], 0.5 * size[1]
if x_half / y_half < FIG_W / FIG_H:
    x_half = y_half * FIG_W / FIG_H
else:
    y_half = x_half * FIG_H / FIG_W
x_min, x_max = origin[0] - x_half, origin[0] + x_half
y_min, y_max = origin[1] - y_half, origin[1] + y_half

if args.title:
    title = args.title
else:
    seed_tag = trace_path.stem.replace("trace_", "")
    title = f"{trace_path.parent.name}  ({seed_tag})"

# palette
C_BG = "#f7f3ea"        # free space: warm paper
C_WALL = "#26344d"      # walls: dark navy
C_START = "#1f6feb"     # blue
C_GOAL = "#1a9c4b"      # green
C_TRACE = "#d62728"     # crimson
C_ROBOT = "#ff9f1c"     # orange
C_WP = "#00aecb"        # cyan
C_LIDAR = "#009688"     # teal

# rasterize the static occupancy layer once to an RGBA canvas (row 0 = top),
# then blit it every frame. Direct numpy: no extent/origin/letterbox pitfalls.
def _hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

PX_H = 576
kx = PX_H / (y_max - y_min)                      # pixels per meter
PX_W = int(round((x_max - x_min) * kx))
canvas = np.empty((PX_H, PX_W, 3), np.uint8)
canvas[:] = _hex2rgb(C_BG)
gy, gx = occ.shape
# Nearest-neighbour resample of the occupancy tile to its exact pixel footprint
# in the view. The old integer kron overshot the canvas whenever PX_H/gy was not
# integral (e.g. the 60x60 held-out grid: round(576/60)=10 -> 600 px > 576).
tile_px_h = int(round(size[1] * kx))
tile_px_w = int(round(size[0] * kx))
ri = (np.arange(tile_px_h) * gy / tile_px_h).astype(int).clip(0, gy - 1)
ci = (np.arange(tile_px_w) * gx / tile_px_w).astype(int).clip(0, gx - 1)
up = occ[np.ix_(ri, ci)][::-1]  # row 0 -> top
r0 = int(round((y_max - tile_y1) * kx))
c0 = int(round((tile_x0 - x_min) * kx))
r0 = max(0, min(r0, PX_H - tile_px_h))
c0 = max(0, min(c0, PX_W - tile_px_w))
canvas[r0:r0 + tile_px_h, c0:c0 + tile_px_w] = np.where(
    up[..., None], np.array(_hex2rgb(C_WALL), np.uint8),
    np.array(_hex2rgb(C_BG), np.uint8))
occ_rgba = np.dstack([canvas, np.full((PX_H, PX_W), 255, np.uint8)])

# front/rear scanner offsets along the robot heading (see openmover_nav_cfg.py)
SCAN_OFF = (0.22015, -0.22015)

# cumulative path length per episode for the HUD
seg_len = np.linalg.norm(np.diff(traj[:, :2], axis=0), axis=1)
cum = np.concatenate([[0.0], np.cumsum(seg_len)])

T = traj.shape[0]
tmp = tempfile.mkdtemp(prefix="topdown_")

for t in range(T):
    # original-step index (ep_start/ep boundary bookkeeping is in those units)
    to = t * args.stride
    e = int(np.searchsorted(ep_start, to, side="right")) - 1
    e = max(0, min(e, len(ep_start) - 1))

    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H), dpi=100)
    fig.subplots_adjust(0, 0, 1, 1)
    ax.imshow(occ_rgba, extent=(x_min, x_max, y_min, y_max), origin="upper",
              interpolation="nearest", zorder=0)
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.patch.set_facecolor(C_BG)

    # LiDAR fan: segments from each scanner origin to its world-frame hit points
    x, y, yaw = traj[t]
    c, s = np.cos(yaw), np.sin(yaw)
    if lidar is not None:
        ends = lidar[t]                       # (300, 2), NaN = miss
        origins = np.empty_like(ends)
        for k, off in enumerate(SCAN_OFF):
            sl = slice(k * 150, (k + 1) * 150)
            origins[sl, 0] = x + off * c
            origins[sl, 1] = y + off * s
        ok = np.isfinite(ends).all(axis=1)
        # IsaacLab reports misses as finite hits at max_distance (10 m); drop them
        ok &= np.linalg.norm(ends - origins, axis=1) < 9.9
        if ok.any():
            segs = np.stack([origins[ok], ends[ok]], axis=1)  # (K, 2, 2)
            ax.add_collection(LineCollection(segs, colors=C_LIDAR, alpha=0.20,
                                             linewidths=0.5, zorder=1))

    sx, sy = ep_spawn[e]
    gx, gy = ep_goal[e]
    ax.add_patch(plt.Circle((sx, sy), 0.24, color=C_START, ec="white", lw=1.5, zorder=3))
    ax.text(sx, sy - 0.60, "START", color=C_START, ha="center", fontsize=9,
            weight="bold", zorder=4)
    ax.add_patch(plt.Circle((gx, gy), 0.30, fill=False, ec=C_GOAL, ls=(0, (4, 3)),
                            lw=1.4, zorder=3))
    ax.plot(gx, gy, marker="*", markersize=24, mfc=C_GOAL, mec="white",
            mew=1.0, zorder=3)
    ax.text(gx, gy + 0.52, "GOAL", color=C_GOAL, ha="center", fontsize=9,
            weight="bold", zorder=4)

    # trajectory of the current episode
    s0 = ep_start[e] // args.stride
    seg = traj[s0:t + 1]
    if len(seg) > 1:
        ax.plot(seg[:, 0], seg[:, 1], color=C_TRACE, lw=3.4, alpha=0.22,
                solid_capstyle="round", zorder=4)
        ax.plot(seg[:, 0], seg[:, 1], color=C_TRACE, lw=1.8,
                solid_capstyle="round", zorder=5)

    # waypoint: dashed cyan line + diamond
    if wp is not None and np.isfinite(wp[t]).all():
        x, y, _ = traj[t]
        ax.plot([x, wp[t, 0]], [y, wp[t, 1]], color=C_WP, ls=(0, (4, 3)),
                lw=1.3, alpha=0.9, zorder=5)
        ax.plot(wp[t, 0], wp[t, 1], marker="D", markersize=6, mfc=C_WP,
                mec="white", mew=0.8, zorder=6)

    # robot wedge
    wedge = np.array([[0.30, 0.0], [-0.18, 0.17], [-0.10, 0.0], [-0.18, -0.17]])
    rot = np.array([[c, -s], [s, c]])
    ax.add_patch(plt.Polygon(wedge @ rot.T + np.array([x, y]), closed=True,
                             color=C_ROBOT, ec="#7a4a00", lw=1.0, zorder=7))

    # HUD: episode + path travelled; scale bar
    # cum/seg are built from the (possibly strided) traj: same index space as t/s0
    dist = cum[t] - cum[s0]
    ax.text(x_min + 0.25, y_max - 0.30, f"episode {e}   path {dist:.1f} m",
            color="#333333", fontsize=9, ha="left", va="top", zorder=8,
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#bbbbbb", alpha=0.85))
    bx, by = x_max - 1.4, y_min + 0.35
    ax.plot([bx, bx + 1.0], [by, by], color="#333333", lw=2.5, zorder=8)
    ax.text(bx + 0.5, by + 0.12, "1 m", color="#333333", fontsize=8,
            ha="center", zorder=8)

    ax.text(0.5 * (x_min + x_max), y_max - 0.15, title, fontsize=10,
            color="#333333", ha="center", va="top", zorder=8,
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#bbbbbb",
                      alpha=0.85))
    fig.savefig(f"{tmp}/f{t:04d}.png", dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig)
    if t % 200 == 0:
        print(f"[topdown] frame {t}/{T}")

out_path.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(
    ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(args.fps),
     "-i", f"{tmp}/f%04d.png", "-pix_fmt", "yuv420p", str(out_path)],
    check=True,
)
print(f"[topdown] wrote {out_path}")
