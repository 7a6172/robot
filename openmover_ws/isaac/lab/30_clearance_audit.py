#!/usr/bin/env python3
"""30_clearance_audit.py — offline hull-vs-wall clearance audit of a trace.

Reads a bridge trace npz (traj, occ, origin, size) and reports the minimum
distance between the robot hull footprint (rotated rectangle, default half-
extents 0.22 x 0.14 m = the pioneer3dx proxy of 29_render_3d_video.py) and
the map walls over the whole run.  Negative = penetration (contact).  This
is the ground truth behind the zero-contact claim of the shielded runs
(docs/isaac/06_results.md §15); iteration-1 traces audit negative.

Two geometry modes:
  default            raster occ distance field (0.125 m cells).  Conservative
                     for clearance, but flags hull points that lie INSIDE an
                     occupied cell even when the baked wall surface is on the
                     far side of that cell (up to one cell of over-flag).
  --map_file <json>  EXACT mode: point-vs-box distance against the map JSON
                     wall boxes (the same boxes the bridge bakes into
                     colliders).  This is the true ground truth.

Optional --t_reach <s> splits the report into approach (t <= t_reach) and
post-success phases (multi-goal tours: pass the FINAL reach time).

Usage: python3 30_clearance_audit.py --trace <npz> [--map_file <json>]
           [--t_reach 23.05] [--hx 0.22] [--hy 0.14]
"""
import argparse
import json
import math

import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("--trace", required=True)
parser.add_argument("--map_file", default=None, help="map JSON -> exact boxes")
parser.add_argument("--t_reach", type=float, default=None)
parser.add_argument("--hx", type=float, default=0.22)
parser.add_argument("--hy", type=float, default=0.14)
args = parser.parse_args()

d = np.load(args.trace)
traj = d["traj"]                      # (T,3) x,y,yaw at 15 Hz
origin = np.asarray(d["origin"], dtype=float)
size = np.asarray(d["size"], dtype=float)

# hull sample points in body frame (corners + edge midpoints + centre)
pts = [(0.0, 0.0), (args.hx, 0.0), (-args.hx, 0.0),
       (0.0, args.hy), (0.0, -args.hy)]
for sx in (1, -1):
    for sy in (1, -1):
        pts.append((sx * args.hx, sy * args.hy))
for sx in (args.hx, -args.hx):        # short-edge quarter points
    for sy in (args.hy / 2, -args.hy / 2):
        pts.append((sx, sy))


def report(cl_arr):
    """cl_arr: per-frame min hull clearance.  Prints min + penetration."""
    idx = np.arange(len(cl_arr))
    if args.t_reach is not None:
        t_arr = idx / 15.0
        for label, m in (("APPROACH (t<=reach)", t_arr <= args.t_reach),
                         ("POST-SUCCESS       ", t_arr > args.t_reach)):
            sel = cl_arr[m]
            if len(sel) == 0:
                continue
            i = int(np.argmin(sel))
            ti = idx[m][i] / 15.0
            print(f"  {label}: min clearance {sel[i]:+.4f} m at t={ti:.1f}s; "
                  f"penetration frames {int((sel < 0).sum())}/{len(sel)}")
    else:
        i = int(np.argmin(cl_arr))
        print(f"  min clearance {cl_arr[i]:+.4f} m at t={idx[i] / 15.0:.1f}s; "
              f"penetration frames {int((cl_arr < 0).sum())}/{len(cl_arr)}")


if args.map_file is not None:
    # ---------------- EXACT mode: point vs JSON wall boxes ----------------
    boxes = []
    for b in json.load(open(args.map_file))["boxes"]:
        boxes.append((b[0] - b[3] / 2, b[0] + b[3] / 2,
                      b[1] - b[4] / 2, b[1] + b[4] / 2))

    def pt_box(px, py, x0, x1, y0, y1):
        dx = max(x0 - px, px - x1, 0.0)
        dy = max(y0 - py, py - y1, 0.0)
        if dx == 0.0 and dy == 0.0:          # inside: depth to nearest face
            return -min(px - x0, x1 - px, py - y0, y1 - py)
        return math.hypot(dx, dy)

    cl_arr = np.empty(traj.shape[0])
    # world -> corner-local: the JSON boxes are corner-local and the trace
    # origin is the map CENTRE (same convention as the raster mode below).
    # For bridge traces (world == corner-local, origin = centre) the shift is
    # a no-op; Stack A runner traces are world-frame on a tile centred at
    # origin, so traj - (origin - size/2) puts them in the map frame.
    corner = origin - 0.5 * size
    for i in range(traj.shape[0]):
        x, y, yaw = traj[i]
        x, y = x - corner[0], y - corner[1]
        c, s = math.cos(yaw), math.sin(yaw)
        cl = np.inf
        for bx, by in pts:
            wx = x + c * bx - s * by
            wy = y + s * bx + c * by
            cl = min(cl, min(pt_box(wx, wy, *b) for b in boxes))
        cl_arr[i] = cl
    print(f"{args.trace} (EXACT boxes, {len(boxes)} walls):")
    report(cl_arr)
else:
    # ---------------- raster mode: occ distance field ---------------------
    occ = d["occ"]                    # (gy,gx) bool, raw walls
    ny, nx = occ.shape
    res = float(size[0]) / nx
    og = occ.T                        # (nx, ny)
    dist = np.full((nx, ny), np.inf)
    dist[og] = 0.0
    diag = res * math.sqrt(2.0)
    for _ in range(300):
        dd = dist
        nd = dd.copy()
        nd[:-1, :] = np.minimum(nd[:-1, :], dd[1:, :] + res)
        nd[1:, :] = np.minimum(nd[1:, :], dd[:-1, :] + res)
        nd[:, :-1] = np.minimum(nd[:, :-1], dd[:, 1:] + res)
        nd[:, 1:] = np.minimum(nd[:, 1:], dd[:, :-1] + res)
        nd[:-1, :-1] = np.minimum(nd[:-1, :-1], dd[1:, 1:] + diag)
        nd[:-1, 1:] = np.minimum(nd[:-1, 1:], dd[1:, :-1] + diag)
        nd[1:, :-1] = np.minimum(nd[1:, :-1], dd[:-1, 1:] + diag)
        nd[1:, 1:] = np.minimum(nd[1:, 1:], dd[:-1, :-1] + diag)
        if np.array_equal(nd, dd):
            break
        dist = nd

    corner = origin - 0.5 * size      # trace origin is the map CENTRE

    def cell_ix(p):
        return int(np.clip((p[0] - corner[0]) / res, 0, nx - 1))

    def cell_iy(p):
        return int(np.clip((p[1] - corner[1]) / res, 0, ny - 1))

    cl_arr = np.empty(traj.shape[0])
    for i in range(traj.shape[0]):
        x, y, yaw = traj[i]
        c, s = math.cos(yaw), math.sin(yaw)
        cl = np.inf
        for bx, by in pts:
            wx, wy = x + c * bx - s * by, y + s * bx + c * by
            ix, iy = cell_ix((wx, wy)), cell_iy((wx, wy))
            if og[ix, iy]:
                cl = -1.0             # hull point inside a wall cell
                break
            cl = min(cl, dist[ix, iy] - 0.5 * res)  # centre -> surface
        cl_arr[i] = cl
    print(f"{args.trace} (raster occ, res {res:.3f} m):")
    report(cl_arr)
