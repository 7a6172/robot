"""Author custom navigation maps for the openmover gallery ("draw, then go").

Produces a JSON map spec consumable by the runner:

    cd ~/isaaclab && ./isaaclab.sh -p .../21_run_openmover_nav.py \
        --map_file .../maps/gap_slalom.json --num_envs 64 --num_steps 2405 \
        --policy trained --checkpoint <model.pt> --fixed_block_prob 1.0

Spec format (tile-local coordinates, tile corner at (0,0), meters):
    {"name", "size": [8, 8], "cell": 0.125,
     "boxes": [[cx, cy, yaw, length, width, height], ...],
     "spawn": [x, y], "goal": [x, y]}

Two ways to make a map:

1) Draw a PNG (square, any resolution, resampled to 64x64 cells):
   - dark pixels  = wall
   - blue pixel   = spawn marker (else tile center)
   - green pixel  = goal marker (else farthest reachable cell)
   Image orientation: as you look at the PNG, left/right = x, top = +y.
       python3 27_make_custom_map.py --png my_drawing.png --name my_map

2) Programmatic gallery generators (this script builds the grid):
       python3 27_make_custom_map.py --gen slalom|ring|rooms|serpentine

Every map is validated by a BFS reachability check (goal must be reachable
from spawn on the 0.125 m grid) and a preview PNG is written next to the spec.
Corridors should stay >= 0.8 m wide (occupancy inflation is 0.2 m), and
spawn/goal should sit >= 0.4 m from any wall (robot hull half-diagonal is
0.33 m; the env snaps marked points that are closer, but centering them by
hand keeps the intended task).
"""

import argparse
import json
from pathlib import Path

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

parser = argparse.ArgumentParser(description="Author a custom navigation map.")
parser.add_argument("--png", type=str, default=None, help="hand-drawn PNG map")
parser.add_argument("--gen", type=str, default=None,
                    choices=["slalom", "ring", "rooms", "serpentine"],
                    help="programmatic gallery generator")
parser.add_argument("--name", type=str, default=None)
parser.add_argument("--cells", type=int, default=64, help="grid cells per axis")
parser.add_argument("--size", type=float, default=8.0, help="tile extent [m]")
parser.add_argument("--wall_height", type=float, default=0.5)
parser.add_argument("--no_boundary", action="store_true",
                    help="skip the outer boundary walls (map keeps robot inside)")
parser.add_argument("--goals", type=str, default=None,
                    help="ordered serial goal cells 'i,j;i,j;...' (BFS-"
                         "validated); the last entry becomes the map goal")
args = parser.parse_args()

if bool(args.png) == bool(args.gen):
    raise SystemExit("pass exactly one of --png / --gen")

N = args.cells
S = args.size
cell = S / N
grid = np.zeros((N, N), dtype=bool)  # grid[j, i]: j = y row (0 = south), i = x col
spawn_cell = goal_cell = None

# ------------------------------------------------------------------ from PNG
if args.png:
    img = plt.imread(args.png)
    if img.ndim == 2:
        img = np.stack([img] * 3, axis=-1)
    img = img[..., :3]
    H, W = img.shape[:2]
    spawn_pts, goal_pts = [], []
    for j in range(N):
        for i in range(N):
            r = int(min((N - 1 - j) * H / N, H - 1))  # PNG row 0 = top = +y
            c = int(min(i * W / N, W - 1))
            pr, pg, pb = img[r, c]
            lum = 0.299 * pr + 0.587 * pg + 0.114 * pb
            if pb > 0.4 and pb > pr + 0.1 and pb > pg + 0.1:
                spawn_pts.append((i, j))
            elif pg > 0.4 and pg > pr + 0.1 and pg > pb + 0.05:
                goal_pts.append((i, j))
            elif lum < 0.45:
                grid[j, i] = True
    if spawn_pts:
        spawn_cell = tuple(np.array(spawn_pts).mean(axis=0).astype(int))
    if goal_pts:
        goal_cell = tuple(np.array(goal_pts).mean(axis=0).astype(int))

# ---------------------------------------------------------------- generators
def hwall(row, i0, i1, th=2):
    grid[row:row + th, i0:i1] = True


def vwall(col, j0, j1, th=2):
    grid[j0:j1, col:col + th] = True


if args.gen == "slalom":
    # full-width walls with alternating gaps: pass right, left, right
    hwall(16, 0, 48)                       # gap on the right (1 m)
    hwall(32, 16, N)                       # gap on the left
    hwall(48, 0, 48)                       # gap on the right
    spawn_cell, goal_cell = (8, 8), (56, 56)
elif args.gen == "ring":
    # ball-maze style: two nested square rings with offset gate gaps
    vwall(12, 12, 54); vwall(52, 12, 28)   # outer ring, east gate rows 28..36
    vwall(52, 36, 54)
    hwall(12, 12, 54); hwall(52, 12, 54)
    vwall(24, 24, 28); vwall(24, 36, 42)   # inner ring, west gate rows 28..36
    hwall(24, 24, 42); hwall(40, 24, 42)
    spawn_cell, goal_cell = (19, 19), (32, 32)   # south passage, corridor center
    # (cell 16 sat only 0.31 m off the west wall < robot hull radius 0.33 m,
    # so the robot spawned intersecting the wall and got crushed at rest)
elif args.gen == "rooms":
    # 2x2 rooms with offset doorways: tour SW -> SE? no: SW -> NE through doors
    vwall(31, 0, 40)                       # vertical divider, door north rows 40..48
    vwall(31, 48, N)
    hwall(31, 0, 12)                       # horizontal divider, doors offset
    hwall(31, 20, 44)
    hwall(31, 52, N)
    spawn_cell, goal_cell = (8, 8), (56, 56)
elif args.gen == "serpentine":
    # six alternating walls -> a long S corridor through the whole tile
    # (10-cell pitch = 1.0 m corridors after the 2-cell walls)
    for k, row in enumerate(range(10, 61, 10)):
        if k % 2 == 0:
            hwall(row, 0, N - 12)          # gap right
        else:
            hwall(row, 12, N)              # gap left
    spawn_cell, goal_cell = (32, 4), (32, 56)
    # (cell 62 sat in a 0.125 m slot between the last wall and the boundary,
    # physically narrower than the robot; cell 56 keeps the long S task)

if not args.no_boundary:
    t = max(1, int(round(0.1 / cell)))     # 0.1 m boundary thickness
    grid[0:t, :] = True
    grid[N - t:, :] = True
    grid[:, 0:t] = True
    grid[:, N - t:] = True

# ------------------------------------------------- default spawn/goal fallback
def nearest_free(ij):
    i0, j0 = ij
    if 0 <= i0 < N and 0 <= j0 < N and not grid[j0, i0]:
        return (i0, j0)
    best = None
    for dj in range(-N, N + 1):
        for di in range(-N, N + 1):
            i, j = i0 + di, j0 + dj
            if 0 <= i < N and 0 <= j < N and not grid[j, i]:
                if best is None or di * di + dj * dj < best[2]:
                    best = (i, j, di * di + dj * dj)
        if best and best[2] <= 4:
            break
    return (best[0], best[1]) if best else ij


if spawn_cell is None:
    spawn_cell = nearest_free((N // 2, N // 2))
    print(f"[map] no blue spawn marker -> using tile center {spawn_cell}")
else:
    spawn_cell = nearest_free(spawn_cell)
if grid[spawn_cell[1], spawn_cell[0]]:
    raise SystemExit("[map] spawn cell is inside a wall")

# BFS distances from spawn (4-connected) for validation + default goal
dist = np.full((N, N), -1, dtype=np.int64)
dist[spawn_cell[1], spawn_cell[0]] = 0
frontier = [spawn_cell]
while frontier:
    nxt = []
    for i, j in frontier:
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ii, jj = i + di, j + dj
            if 0 <= ii < N and 0 <= jj < N and not grid[jj, ii] and dist[jj, ii] < 0:
                dist[jj, ii] = dist[j, i] + 1
                nxt.append((ii, jj))
    frontier = nxt

if goal_cell is None:
    jj, ii = np.unravel_index(np.argmax(dist), dist.shape)
    goal_cell = (int(ii), int(jj))
    print(f"[map] no green goal marker -> farthest reachable cell {goal_cell}")
else:
    goal_cell = nearest_free(goal_cell)
serial_goals = None
if args.goals:
    serial_goals = []
    for tok in args.goals.split(";"):
        i, j = (int(v) for v in tok.split(","))
        i, j = nearest_free((i, j))
        if dist[j, i] < 0:
            raise SystemExit(f"[map] serial goal cell {(i, j)} not reachable")
        serial_goals.append((i, j))
    goal_cell = serial_goals[-1]
g_dist = dist[goal_cell[1], goal_cell[0]]
if g_dist < 0:
    raise SystemExit("[map] ERROR: goal is not reachable from spawn")

# ------------------------------------------------------------------ boxes
boxes = []
wh = args.wall_height
# horizontal runs
for j in range(N):
    i = 0
    while i < N:
        if grid[j, i]:
            k = i
            while k < N and grid[j, k]:
                k += 1
            boxes.append([0.5 * (i + k) * cell, (j + 0.5) * cell, 0.0,
                          (k - i) * cell, cell, wh])
            i = k
        else:
            i += 1
# vertical runs (>= 3 cells) — merges tall walls that row runs stack thinly
for i in range(N):
    j = 0
    while j < N:
        if grid[j, i]:
            k = j
            while k < N and grid[k, i]:
                k += 1
            if k - j >= 3:
                boxes.append([(i + 0.5) * cell, 0.5 * (j + k) * cell, 0.0,
                              cell, (k - j) * cell, wh])
            j = k
        else:
            j += 1

name = args.name or (Path(args.png).stem if args.png else args.gen)
out_dir = Path(__file__).resolve().parent / "maps"
out_dir.mkdir(exist_ok=True)
spec = {
    "name": name,
    "size": [S, S],
    "cell": cell,
    "wall_height": wh,
    "boxes": [[round(v, 4) for v in b] for b in boxes],
    "spawn": [round((spawn_cell[0] + 0.5) * cell, 3), round((spawn_cell[1] + 0.5) * cell, 3)],
    "goal": [round((goal_cell[0] + 0.5) * cell, 3), round((goal_cell[1] + 0.5) * cell, 3)],
    "path_len": round(g_dist * cell, 2),
}
if serial_goals:
    spec["goals"] = [[round((i + 0.5) * cell, 3), round((j + 0.5) * cell, 3)]
                     for i, j in serial_goals]
spec_path = out_dir / f"{name}.json"
with open(spec_path, "w") as f:
    json.dump(spec, f, indent=1)

# ------------------------------------------------------------------ preview
fig, ax = plt.subplots(figsize=(8, 8), dpi=100)
ax.imshow(grid.astype(float), extent=(0, S, 0, S), origin="lower",
          cmap="gray_r", interpolation="nearest")
ax.plot(spec["spawn"][0], spec["spawn"][1], "o", color="#1f6feb",
        markersize=14, mec="white", mew=1.5)
ax.plot(spec["goal"][0], spec["goal"][1], "*", color="#1a9c4b",
        markersize=26, mec="white", mew=1.0)
for k, (i, j) in enumerate(serial_goals or []):
    gx_, gy_ = (i + 0.5) * cell, (j + 0.5) * cell
    ax.plot(gx_, gy_, "*", color="#1a9c4b", markersize=20, mec="white", mew=1.0)
    ax.text(gx_, gy_ + 0.4, f"G{k + 1}", color="#1a9c4b", ha="center",
            fontsize=10, weight="bold")
ax.text(spec["spawn"][0], spec["spawn"][1] - 0.45, "START", color="#1f6feb",
        ha="center", fontsize=10, weight="bold")
ax.text(spec["goal"][0], spec["goal"][1] + 0.4, "GOAL", color="#1a9c4b",
        ha="center", fontsize=10, weight="bold")
ax.set_xlim(0, S)
ax.set_ylim(0, S)
ax.set_aspect("equal")
ax.set_title(f"{name}: {len(boxes)} wall boxes, BFS path {g_dist * cell:.1f} m")
fig.savefig(out_dir / f"{name}.preview.png", dpi=100)
plt.close(fig)

print(f"[map] {name}: {len(boxes)} boxes, spawn={spec['spawn']}, goal={spec['goal']}, "
      f"shortest path ~{g_dist * cell:.1f} m")
print(f"[map] wrote {spec_path}")
print(f"[map] wrote {out_dir / (name + '.preview.png')}")
