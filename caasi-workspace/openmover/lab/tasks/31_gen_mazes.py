#!/usr/bin/env python3
"""31_gen_mazes.py — procedural presentation-grade maze generator (v3, wide).

Composes structural motifs (serpentine switchback, door gauntlet, ordered gate
chain, roundabout, perimeter tour, flush clutter scatter) and scene archetypes
(fortress rings, competition/micromouse labyrinth, warehouse aisles, highway
lanes with merges) into maps in the same JSON schema as maps/demo_*.json, so
the existing stack (GeoField interface, shield, exact-box audit) runs
unchanged.

CANVAS: 10 x 10 m (N=80 cells of 0.125 m). The deployment bar below cannot be
met on an 8 m canvas with any structural density: 13-cell corridors need a
15-cell wall pitch, and the 62-cell 8 m interior then admits only 3 full-width
walls, a single fortress ring (two concentric 13-cell corridors cost 60 of
those 62 cells, leaving a <= 2-cell keep), a 6-cell roundabout pillar, no
aisle pallets and a labyrinth frozen at 4x4. At 10 m (78-cell interior) the
same bar keeps two fortress rings with a 2.25 m keep, three shelf rows with
1.875 m aisles, a 5x5 labyrinth with 1.625 m corridors and four serpentine
walls. The stack is size-agnostic: the bridge builds floor+walls from
SPEC["size"], rasterize_occ derives nx,ny from size/cell, the top-down renderer
and 30_clearance_audit.py read size/origin from the trace, and policy_node.py
reads spec["size"].

DEPLOYMENT BAR (why these numbers): every accepted map must have a widest-path
corridor of >= MIN_PASS_W = 13 cells = 1.625 m between consecutive waypoints,
and every intentional door must be >= 16 cells = 2.0 m. Two measured failures
set that bar:
  * a generated 8 m fortress wedged the robot in an accidental 0.625 m dog-leg
    (it clipped a wall end cap 1 cm inside the shield's own dilation zone and
    no shield tier could extract it) -> the accidental-pinch gates below;
  * with shield v5, an 0.875 m fortress corridor and a 1.0 m warehouse aisle
    both pinned the robot for ~100 s with ~6 cm hull penetration (docs/isaac/
    06_results.md 17.4). Shield v6 removed the penetration (17.5: 0/1950
    frames, min clearance +0.074 m) but the frozen goal-bearing policy still
    could not TRACK the aisle: GeoField resolves 0.25 m and inflates 0.35 m,
    so a 1.0 m aisle leaves a 0.30 m free band and pure pursuit has no lateral
    slack -> cornering creep pins the hull. 1.625 m corridors leave 0.925 m.
The bar is checked WITHOUT door exemptions: a >= 16-cell door in a 2-cell wall
has a distance-transform funnel of >= 7 cells at its centre, so doors are wide
by geometry, not by fiat. That makes this gate identical to the exemption-free
offline audit (width_audit.py, PASS = bottleneck distance >= 7 cells).

Everything free on an accepted map is at least MIN_PASS_W cells across: walls
are 2 cells thick, bands are 13+ cells, doors are 16+ cells, and scattered
blocks (clutter, pallets, lane incidents) are only kept when every run of free
space they leave is 0 cells (flush against a wall) or >= MIN_PASS_W. Two v2
motifs cannot survive that rule and are gone: the hairpin pocket (needs 17
rows plus a 13-cell band on both sides) and the crossbar (a perpendicular
barrier whose mouth must align with a switchback gap that sits within 16 cells
of the border, so one half ends up 4 cells wide).

Quality gates, all applied before a map is written:
  * footprint-inflated A* must reach every ordered goal (solvability),
  * geodesic/straight-line ratio >= 1.15 (no trivial maps),
  * min wall clearance along the geodesic >= 2 cells (~0.25 m) so narrow spots
    are intentional doors, not accidental pinches,
  * pocket-free: every 8-connected free region contains a cell at distance
    >= WIDE_CLR, so no sealed sub-bar pocket exists anywhere on the map,
  * deployment bar: spawn, every ordered goal and the final goal share one
    8-connected component of the wide mask (which implies every leg's widest
    path is >= MIN_PASS_W),
  * spawn/goal pockets are opened by nudging the point to a cell that already
    has a wide pocket, never by punching a box that clips a 2-cell-thick wall
    (the leftover 1-cell stub is what formed the dog-leg above).

Spawn/goal diversity: layouts are built in a canonical orientation and then
mapped through one of the 8 dihedral transforms of the square, so starts and
goals land on different corners/edges per map (fortress/competition maps use
centre goals by design).

Usage:
  python3 31_gen_mazes.py --per 2 --preview   # sample + previews
                                              # (7 families x 4 bins x per)
  python3 31_gen_mazes.py --per 2             # campaign set, no previews
"""
import argparse
import heapq
import json
import math
import os
from collections import deque

import numpy as np

LAB = os.path.dirname(os.path.abspath(__file__))
MAPS = os.path.join(LAB, "maps")
GEN = os.path.join(MAPS, "gen")

CELL = 0.125
SIZE = 10.0                   # canvas edge in m (see the module docstring)
N = int(round(SIZE / CELL))   # 80
C0, C1 = 1, N - 2             # full-width wall span: flush with the border so
R0, R1 = 1, N - 2             # no 1-cell sliver is left along the boundary
INF_CELLS = 1                 # inflation for the solvability check (0.125 m ~
                              # hull half-width 0.14 m; hull is 0.44 x 0.28 m)
MIN_PATH_CLR = 2              # 8-conn BFS cells from any wall along geodesic
WIDE_CLR = 7                  # BFS cells a keep point / route cell needs
MIN_PASS_W = 2 * WIDE_CLR - 1  # 13 cells = 1.625 m: deployment floor (a
                               # 12-cell corridor only reaches distance 6)
ROW_PITCH = 15                # 2-cell walls at pitch 15 leave a 13-cell band
WR_LO, WR_HI = 14, N - 16     # full-width wall rows: 14..64, so the bands
                              # above the first and below the last are >= 13
MID = N // 2 - 1              # 39: centreline walls (rows/cols 39-40)
RING_A, RING_B = 14, N - 16   # outer ring rectangle rows/cols 14-15 & 64-65
KEEP_A, KEEP_B = 29, N - 31   # fortress inner ring rows/cols 29-30 & 49-50
SPAWN = ((8 + 0.5) * CELL,) * 2               # cell (8,8)
GOAL = ((N - 9 + 0.5) * CELL,) * 2            # cell (71,71)

# Door width in cells per difficulty bin (b0 easy .. b3 extreme). Every entry
# is >= 16 cells (2.0 m): below that the frozen policy's cornering creep pins
# the hull (06_results.md 17.4). Difficulty is therefore carried by door
# width within [2.0, 2.75] m, tour length, ordered-goal count, staggering and
# obstruction -- not by sub-2 m throats.
DOOR = {0: (20, 22), 1: (18, 19), 2: (16, 17), 3: (16, 16)}


def ri(rng, a, b):
    """inclusive-on-both-ends integer draw (numpy Generator has no randint)"""
    return int(rng.integers(a, b + 1))


# --------------------------------------------------------------------------
# grid helpers
# --------------------------------------------------------------------------
def new_grid():
    g = np.zeros((N, N), bool)
    g[0, :] = g[N - 1, :] = True
    g[:, 0] = g[:, N - 1] = True
    return g


def hwall(g, r, c0, c1):
    g[r:r + 2, c0:c1 + 1] = True


def vwall(g, c, r0, r1):
    g[r0:r1 + 1, c:c + 2] = True


def blk(g, r0, r1, c0, c1):
    g[r0:r1 + 1, c0:c1 + 1] = True


def clear(g, r, c, rad):
    g[max(1, r - rad):min(N - 1, r + rad + 1),
      max(1, c - rad):min(N - 1, c + rad + 1)] = False


def erode_thin(g, r, c, rad):
    """Erase wall remnants a clear() punch left only 1 cell thick.

    A 2-cell-thick wall clipped halfway leaves a stub protruding into the
    corridor; the stub plus the border forms an accidental dog-leg the robot
    cannot rotate out of. Any wall cell with free space on both opposite
    sides inside the window is such a stub.
    """
    r0, r1 = max(1, r - rad), min(N - 2, r + rad)
    c0, c1 = max(1, c - rad), min(N - 2, c + rad)
    for _ in range(3):
        sub = g[r0:r1 + 1, c0:c1 + 1]
        up = np.vstack([g[r0 - 1:r0, c0:c1 + 1], sub[:-1]])
        dn = np.vstack([sub[1:], g[r1 + 1:r1 + 2, c0:c1 + 1]])
        lf = np.hstack([g[r0:r1 + 1, c0 - 1:c0], sub[:, :-1]])
        rt = np.hstack([sub[:, 1:], g[r0:r1 + 1, c1 + 1:c1 + 2]])
        thin = sub & (((~up) & (~dn)) | ((~lf) & (~rt)))
        if not thin.any():
            return
        sub &= ~thin


def pick_rows(rng, k, lo, hi, meta, span=ROW_PITCH):
    """k full-width wall rows in [lo, hi], >= span apart from each other and
    from rows other motifs already claimed. Returns None when infeasible.

    The claimed window is (span-2) rows above and span rows below a wall, so a
    second wall can never land inside this wall's 13-cell bands.
    """
    need = (k - 1) * span
    if hi - lo < need:
        return None
    extra = (hi - lo) - need
    for _ in range(60):
        add = sorted(int(rng.integers(0, extra + 1)) for _ in range(k))
        rows = [lo + i * span + add[i] for i in range(k)]
        if any(rr in meta["used_rows"]
               for r in rows for rr in range(r - (span - 2), r + span)):
            continue
        for r in rows:
            meta["used_rows"].update(range(int(r) - (span - 2), int(r) + span))
        return [int(r) for r in rows]
    return None


def ring_rect(g, a, bb):
    """closed 2-cell-thick rectangle on rows/cols a..a+1 and bb..bb+1.

    Every side runs the full a..bb+1 range so the corners are closed: spans
    that stop short leave 3-6 cell strips and open corners, both below the
    deployment bar (this is what wedged the first 8 m fortress test run).
    """
    hwall(g, a, a, bb + 1)
    hwall(g, bb, a, bb + 1)
    vwall(g, a, a, bb + 1)
    vwall(g, bb, a, bb + 1)


def rect_door(rng, g, meta, a, bb, side, w):
    """punch a w-cell door in one side of the rectangle spanning a..bb+1,
    kept >= 3 cells off the corners. Returns the door's centre cell."""
    lo, hi = a + 3, bb - 2 - w
    d = ri(rng, lo, max(lo, hi))
    if side == "N":
        g[a:a + 2, d:d + w] = False
        cells = [(a + k, d + j) for k in (0, 1) for j in range(w)]
        mid = (a, d + w // 2)
    elif side == "S":
        g[bb:bb + 2, d:d + w] = False
        cells = [(bb + k, d + j) for k in (0, 1) for j in range(w)]
        mid = (bb + 1, d + w // 2)
    elif side == "W":
        g[d:d + w, a:a + 2] = False
        cells = [(d + j, a + k) for k in (0, 1) for j in range(w)]
        mid = (d + w // 2, a)
    else:
        g[d:d + w, bb:bb + 2] = False
        cells = [(d + j, bb + k) for k in (0, 1) for j in range(w)]
        mid = (d + w // 2, bb + 1)
    meta["door_cells"].update(cells)
    meta["doors"].append(w)
    return mid


def to_xy(r, c):
    return ((c + 0.5) * CELL, (r + 0.5) * CELL)


def to_rc(x, y):
    return (int(y / CELL), int(x / CELL))


# --------------------------------------------------------------------------
# motifs
# --------------------------------------------------------------------------
def m_serpentine(rng, g, b, meta):
    """full-width walls with alternating end gaps: a corridor switchback.
    Each end gap forces a 180 deg turn, so uturns are credited here (a
    separate hairpin pocket needs 17 rows + 13-row bands on both sides, which
    no 13-cell band can host)."""
    k = 2 + (1 if b >= 1 else 0) + (1 if b >= 3 else 0)
    rows = pick_rows(rng, k, WR_LO, WR_HI, meta)
    if rows is None:
        return
    for i, r in enumerate(rows):
        w = ri(rng, *DOOR[b])
        if i % 2 == 0:                      # gap at the right end
            hwall(g, r, C0, C1 - w)
            d0 = C1 - w + 1
        else:                               # gap at the left end
            hwall(g, r, C0 + w, C1)
            d0 = C0
        for c in range(d0, d0 + w):
            meta["door_cells"].update([(r, c), (r + 1, c)])
        meta["doors"].append(w)
    meta["blockades"] += k
    meta["uturns"] += k
    meta["motifs"].append("serpentine")


def m_gauntlet(rng, g, b, meta):
    """full-width walls whose doors alternate between the two extremes of the
    span, so every wall forces a lateral sweep and the route weaves; higher
    bins add walls rather than doors.

    Doors are >= 2 m wide, so the old mid-span thirds stagger let the
    corner-to-corner diagonal thread them (rho 1.00-1.12) and every gauntlet
    attempt died on the rho >= 1.15 gate. Extremes with a small jitter keep the
    sweeps long. A second door in the same wall would only shortcut the weave,
    so difficulty comes from wall count (k = 2/3/3/4, as in m_serpentine).
    """
    k = 2 + (1 if b >= 1 else 0) + (1 if b >= 3 else 0)
    rows = None
    while k >= 2 and rows is None:          # drop a wall rather than crowd rows
        rows = pick_rows(rng, k, WR_LO, WR_HI, meta)
        if rows is None:
            k -= 1
    if not rows:
        return
    jit = (C1 - C0 + 1) // 8                # 9 cells of mouth jitter
    side = int(rng.integers(0, 2))
    for r in rows:
        w = ri(rng, *DOOR[b])
        j = int(rng.integers(0, jit + 1))
        d0 = C0 + j if side else C1 - w + 1 - j
        hwall(g, r, C0, d0 - 1)
        hwall(g, r, d0 + w, C1)
        for c in range(d0, d0 + w):
            meta["door_cells"].update([(r, c), (r + 1, c)])
        meta["doors"].append(w)
        side ^= 1
    meta["blockades"] += k
    meta["motifs"].append("gauntlet")


def m_gate_chain(rng, g, b, meta, goals):
    """ordered gates: one waypoint in the wide band just past each door, so
    the route must take the doors in sequence."""
    k = 2 + (1 if b >= 1 else 0) + (1 if b >= 3 else 0)
    rows = None
    while k >= 1 and rows is None:      # drop a gate rather than crowd rows
        rows = pick_rows(rng, k, WR_LO, WR_HI, meta)
        if rows is None:
            k -= 1
    if not rows:
        goals.append(list(GOAL))
        meta["motifs"].append("gatechain(none)")
        return
    for r in rows:
        gw = ri(rng, *DOOR[b])
        d0 = ri(rng, C0 + 4, C1 - 4 - gw)
        hwall(g, r, C0, d0 - 1)
        hwall(g, r, d0 + gw, C1)
        for c in range(d0, d0 + gw):
            meta["door_cells"].update([(r, c), (r + 1, c)])
        meta["doors"].append(gw)
        meta["gates"] += 1
        # waypoint on the band centreline (row r+8 of the 13-cell band
        # r+2..r+14) at the door's centre column: distance 7 => wide pocket
        gx, gy = to_xy(r + 8, d0 + gw // 2)
        goals.append([round(gx, 3), round(gy, 3)])
    goals.append(list(GOAL))
    meta["motifs"].append("gatechain")


def m_roundabout(rng, g, b, meta, goals):
    """ring corridor round a central pillar with staggered entry/exit doors;
    higher bins grow the pillar (tighter circuit) and add one radial spoke.

    Exactly one spoke is allowed: two spokes seal a quadrant of the ring, and
    a spoke is only 16-19 cells long, so it cannot carry its own >= 2 m door.
    The spoke's own row (or column) lies inside the pillar's span, so it abuts
    the pillar flush and cannot clip the arms at right angles to it.
    """
    ring_rect(g, RING_A, RING_B)
    I = 10 + 2 * b                          # pillar edge, 1.25 -> 2.0 m
    p0 = (N - I) // 2
    blk(g, p0, p0 + I - 1, p0, p0 + I - 1)
    # ring corridor centreline radii (rows/cols 16..p0-1 and p0+I..63)
    c_in = (RING_A + 2 + p0 - 1) // 2
    c_out = (p0 + I + RING_B - 1) // 2
    if b >= 3:                              # opposite doors: longest circuit
        opts = [("N", "S"), ("E", "W")]
    else:                                   # adjacent doors: one corner cut
        opts = [("N", "E"), ("E", "S"), ("S", "W"), ("W", "N")]
    pair = list(opts[int(rng.integers(0, len(opts)))])
    w = ri(rng, *DOOR[b])
    for side in pair:
        rect_door(rng, g, meta, RING_A, RING_B, side, w)
    if b >= 2:                              # one radial spoke: ring -> pillar
        rest = [s for s in ("N", "S", "E", "W") if s not in pair]
        sd = rest[int(rng.integers(0, len(rest)))]
        r = ri(rng, p0, p0 + I - 2)
        if sd == "W":
            hwall(g, r, RING_A + 2, p0 - 1)
        elif sd == "E":
            hwall(g, r, p0 + I, RING_B - 1)
        elif sd == "N":
            vwall(g, r, RING_A + 2, p0 - 1)
        else:
            vwall(g, r, p0 + I, RING_B - 1)
        meta["blockades"] += 1
    # ordered waypoint: a ring corner touching neither door side, so the
    # circuit round the pillar is compulsory before the exit door
    cs = [((c_in, c_in), ("N", "W")), ((c_in, c_out), ("N", "E")),
          ((c_out, c_in), ("S", "W")), ((c_out, c_out), ("S", "E"))]
    cand = [rc for rc, ss in cs if not (set(ss) & set(pair))]
    wp = cand[int(rng.integers(0, len(cand)))]
    goals.append([round(v, 3) for v in to_xy(*wp)])
    goals.append(list(GOAL))
    meta["blockades"] += 2
    meta["gates"] += 1
    meta["motifs"].append("roundabout")


def m_perimeter(rng, g, b, meta, goals):
    """cross walls splitting the map into four 4.75 m rooms, one door per arm
    half, and an ordered tour of three room centres before the goal.

    The arms cross on rows/cols MID..MID+1 and seal each other, so a door is
    the only way between rooms. The rooms are also the one place on this
    canvas wide enough for clutter to sit legally (see scatter()).
    """
    w = ri(rng, *DOOR[b])
    hwall(g, MID, C0, C1)
    vwall(g, MID, R0, R1)
    for axis, d in (("H", ri(rng, 6, 38 - w)), ("H", ri(rng, 41, C1 - w)),
                    ("V", ri(rng, 6, 38 - w)), ("V", ri(rng, 41, R1 - w))):
        if axis == "H":
            g[MID:MID + 2, d:d + w] = False
            meta["door_cells"].update([(MID + k, d + j) for k in (0, 1)
                                       for j in range(w)])
        else:
            g[d:d + w, MID:MID + 2] = False
            meta["door_cells"].update([(d + j, MID + k) for k in (0, 1)
                                       for j in range(w)])
        meta["doors"].append(w)
    q = {"NW": (20, 20), "NE": (20, 59), "SW": (59, 20), "SE": (59, 59)}
    order = ["NW"] + [str(v) for v in rng.permutation(["NE", "SW"])] + ["SE"]
    for key in order[:-1]:
        goals.append([round(v, 3) for v in to_xy(*q[key])])
    goals.append(list(GOAL))
    meta["blockades"] += 2
    meta["gates"] += 4
    meta["motifs"].append("perimeter")


def gap_ok(g, r, c, s):
    """True when a block on rows r..r+s-1 x cols c..c+s-1 leaves no free run
    narrower than the bar: each of the four runs beside it must be flush
    (0 cells, i.e. the block touches a wall) or >= MIN_PASS_W cells."""
    for d in (-1, 1):
        n, rr = 0, (r - 1 if d < 0 else r + s)
        while 1 <= rr <= N - 2 and not g[rr, c:c + s].any():
            n, rr = n + 1, rr + d
        if 0 < n < MIN_PASS_W:
            return False
    for d in (-1, 1):
        n, cc = 0, (c - 1 if d < 0 else c + s)
        while 1 <= cc <= N - 2 and not g[r:r + s, cc].any():
            n, cc = n + 1, cc + d
        if 0 < n < MIN_PASS_W:
            return False
    return True


def scatter(rng, g, meta, keep_out, n, s_lo, s_hi, region=None):
    """Place up to n square blocks of side s_lo..s_hi cells.

    A candidate is kept only when gap_ok() says it leaves no sub-bar run and
    still_feasible() says the ordered route is still one wide channel. This is
    what lets an obstruction narrow a lane to exactly the bar (a highway
    incident, a pallet against a shelf) without ever creating the accidental
    dog-leg that wedged the first 8 m fortress run. region=(r0,r1,c0,c1)
    restricts the search; waypoints get an s+4 margin and door cells a 2-cell
    margin, so a block never sits on a waypoint or pinches a throat.
    """
    dc = meta["door_cells"]
    got = 0
    for _ in range(30 * max(1, n)):
        if got >= n:
            break
        s = ri(rng, s_lo, s_hi)
        if region is None:
            r0, r1, c0, c1 = 4, N - 5 - s, 4, N - 5 - s
        else:
            r0, r1, c0, c1 = region
            r1, c1 = r1 - s + 1, c1 - s + 1
        if r1 < r0 or c1 < c0:
            continue
        r, c = ri(rng, r0, r1), ri(rng, c0, c1)
        if g[r:r + s, c:c + s].any():
            continue
        if any(abs(r - kr) < s + 4 and abs(c - kc) < s + 4
               for kr, kc in keep_out):
            continue
        if any((rr, cc) in dc for rr in range(r - 2, r + s + 2)
               for cc in range(c - 2, c + s + 2)):
            continue
        g[r:r + s, c:c + s] = True
        if not gap_ok(g, r, c, s) or not still_feasible(g, keep_out):
            g[r:r + s, c:c + s] = False   # undo: below-bar run or sealed route
            continue
        got += 1
    meta["clutter"] += got
    return got


def m_clutter(rng, g, b, meta, keep_out):
    got = scatter(rng, g, meta, keep_out, 2 + b, 4, 8)
    if got:
        meta["motifs"].append("clutter")


# --------------------------------------------------------------------------
# scene archetypes
# --------------------------------------------------------------------------
def m_fortress(rng, g, b, meta, goals):
    """concentric walled rings with staggered doors; goal = the keep.

    Outer ring on rows/cols 14-15 & 64-65, inner ring on 29-30 & 49-50: the
    annulus and the exterior band are both exactly 13 cells (the bar) and the
    keep is 18 cells (2.25 m), so the robot can rotate inside it. At b >= 2
    one arm of the annulus is sealed by a radial wall that abuts both rings,
    which forces the long way round or a trip through the keep.
    """
    sides = ["N", "S", "E", "W"]
    ring_rect(g, RING_A, RING_B)
    side = sides[int(rng.integers(0, 4))]
    rect_door(rng, g, meta, RING_A, RING_B, side, ri(rng, *DOOR[b]))
    ring_rect(g, KEEP_A, KEEP_B)
    rest = [s for s in sides if s != side]
    side2 = rest[int(rng.integers(0, len(rest)))]
    rect_door(rng, g, meta, KEEP_A, KEEP_B, side2, DOOR[3][0])
    meta["blockades"] += 2
    meta["gates"] += 2
    if b >= 2:                              # seal one annulus arm
        rest2 = [s for s in sides if s not in (side, side2)]
        arm = rest2[int(rng.integers(0, len(rest2)))]
        r = ri(rng, KEEP_A, KEEP_B - 1)     # inside the inner ring's span, so
        if arm == "W":                      # the wall abuts it flush
            hwall(g, r, RING_A + 2, KEEP_A - 1)
        elif arm == "E":
            hwall(g, r, KEEP_B + 2, RING_B - 1)
        elif arm == "N":
            vwall(g, r, RING_A + 2, KEEP_A - 1)
        else:
            vwall(g, r, KEEP_B + 2, RING_B - 1)
        meta["blockades"] += 1
    # ordered tour: a point on the annulus centreline (opposite side first, so
    # the ring has to be walked), then the keep centre
    ann = {"N": (RING_A + 8, MID), "S": (RING_B - 7, MID),
           "W": (MID, RING_A + 8), "E": (MID, RING_B - 7)}
    dist = bfs_dist(g)
    opp = {"N": "S", "S": "N", "E": "W", "W": "E"}[side]
    for s in [opp] + [x for x in sides if x not in (opp, side)]:
        rc = ann[s]
        if not g[rc] and dist[rc] >= WIDE_CLR:
            goals.append([round(v, 3) for v in to_xy(*rc)])
            break
    keep = [round(v, 3) for v in to_xy(MID, MID)]
    goals.append(keep)
    meta["goal"] = keep
    meta["motifs"].append("fortress")


def m_micromouse(rng, g, b, meta, goals):
    """competition labyrinth: recursive-backtracker maze on a 5x5 macro grid,
    open centre chamber as the goal, loops knocked in (fewer at higher bins).

    Macro pitch 15 = 13-cell corridors (the bar) + a 2-cell wall, so this is
    the densest labyrinth the bar allows on a 10 m canvas. v2 exempted every
    labyrinth cell from the width gate ("each corridor is an intentional
    narrow passage"); the exemption is gone -- corridors are 1.625 m, so the
    labyrinth is audited like every other family.
    """
    M, s, B = 5, 15, 2
    visited = np.zeros((M, M), bool)
    walls = set()
    for i in range(M):
        for j in range(M):
            if i + 1 < M:
                walls.add(("H", i, j))       # wall below cell (i,j)
            if j + 1 < M:
                walls.add(("V", i, j))       # wall right of cell (i,j)
    stack = [(0, 0)]
    visited[0, 0] = True
    while stack:
        i, j = stack[-1]
        nb = []
        if i > 0 and not visited[i - 1, j]:
            nb.append((i - 1, j, ("H", i - 1, j)))
        if i + 1 < M and not visited[i + 1, j]:
            nb.append((i + 1, j, ("H", i, j)))
        if j > 0 and not visited[i, j - 1]:
            nb.append((i, j - 1, ("V", i, j - 1)))
        if j + 1 < M and not visited[i, j + 1]:
            nb.append((i, j + 1, ("V", i, j)))
        if not nb:
            stack.pop()
            continue
        ni, nj, wd = nb[int(rng.integers(0, len(nb)))]
        walls.discard(wd)
        visited[ni, nj] = True
        stack.append((ni, nj))
    extra = max(1, int(len(walls) * (0.25 - 0.05 * b)))
    # sorted(), not list(): `walls` holds string-tagged tuples ("H"/"V", i, j),
    # and set iteration order over strings is randomised by PYTHONHASHSEED. With
    # list(walls) the seeded rng.permutation indices mapped to a different wall
    # per process, so the knocked-in loops -- and hence the whole labyrinth, its
    # gate outcomes and its retry seed -- varied run to run (family 5 was not
    # reproducible; ledger 17.18). Canonical order makes it hash-seed invariant.
    wl = sorted(walls)
    for wi in rng.permutation(len(wl))[:extra]:
        walls.discard(wl[int(wi)])
    for wd in walls:
        if wd[0] == "H":
            i, j = wd[1], wd[2]
            hwall(g, B + (i + 1) * s - 1, B + j * s, B + (j + 1) * s)
        else:
            i, j = wd[1], wd[2]
            vwall(g, B + (j + 1) * s - 1, B + i * s, B + (i + 1) * s)
    E = B + M * s                            # 77
    g[1:B, 1:N - 1] = True                   # 1-cell seal against the border
    g[E:N - 1, 1:N - 1] = True               # (2 cells with the border ring)
    g[B:E, 1:B] = True
    g[B:E, E:N - 1] = True
    # centre chamber: clear the middle macro cell AND the four wall bands that
    # bound it, so the chamber is 18 cells (2.25 m) across, opens on all four
    # sides and leaves no 1-cell stub behind (v2 cleared to the wall's first
    # row, which left a stub protruding into the corridor)
    ci = cj = M // 2
    lo, hi = B + ci * s - 1, B + (ci + 1) * s + 1     # 31..48
    g[lo:hi + 1, lo:hi + 1] = False
    cc = ((lo + hi) // 2, (lo + hi) // 2)             # (39, 39)
    meta["doors"].append(s - 2)              # 13-cell corridor stands in for
    meta["blockades"] += M * M // 2          # a door in the manifest stats
    if b >= 2:                               # tour a far cell before the goal
        fi, fj = [(M - 1, 0), (0, M - 1)][int(rng.integers(0, 2))]
        goals.append([round(v, 3) for v in
                      to_xy(B + fi * s + s // 2, B + fj * s + s // 2)])
    goals.append([round(v, 3) for v in to_xy(*cc)])
    meta["spawn"] = [round(v, 3) for v in
                     to_xy(B + s // 2, B + s // 2)]
    meta["goal"] = [round(v, 3) for v in to_xy(*cc)]
    meta["motifs"].append("micromouse")


def m_warehouse(rng, g, b, meta, goals):
    """shelf rows with >= 1.875 m aisles, a cross aisle along the dock wall
    and an ordered pick tour that finishes at the dock.

    A 1.0 m aisle pinned the frozen policy for ~100 s even with shield v6
    (06_results.md 17.4/17.5), so aisle width is fixed at >= 15 cells and
    difficulty comes from the number of ordered picks (2 -> 5) and from
    pallets stacked against the shelves.
    """
    SR0, SR1 = 14, 60                        # shelf row span
    shelves = ([(18, 25), (52, 59)] if b == 0
               else [(16, 21), (37, 42), (58, 63)])
    for c0, c1 in shelves:
        blk(g, SR0, SR1, c0, c1)
    meta["blockades"] += len(shelves)
    aisles, lo = [], C0
    for c0, c1 in shelves:
        aisles.append((lo, c0 - 1))
        lo = c1 + 1
    aisles.append((lo, C1))
    ais = [(a + bb) // 2 for a, bb in aisles]
    meta["doors"].append(min(bb - a + 1 for a, bb in aisles))
    n_pick = 2 + (1 if b >= 1 else 0) + (1 if b >= 2 else 0) + (1 if b >= 3
                                                                 else 0)
    rows = [18, 30, 42, 54]
    for p in range(n_pick):
        goals.append([round(v, 3) for v in
                      to_xy(rows[p % len(rows)], ais[(2 * p + 1) % len(ais)])])
    dock = [round(v, 3) for v in to_xy(N - 9, N - 9)]
    goals.append(dock)
    meta["motifs"].append("warehouse")
    # pallets in the dock-side cross aisle (18 cells): flush against a shelf
    # end or the border they leave a >= 13-cell run, anywhere else gap_ok()
    # rejects them
    kp = [to_rc(*SPAWN), to_rc(*dock)] + [to_rc(x, y) for x, y in goals]
    if scatter(rng, g, meta, kp, 1 + (1 if b >= 1 else 0)
               + (1 if b >= 2 else 0), 3, 5, region=(SR1 + 1, R1, C0, C1)):
        meta["motifs"].append("pallets")


def m_highway(rng, g, b, meta, goals):
    """three lanes split by full-span barriers with merge gaps; lane incidents
    close a lane down to exactly the bar so a merge is compulsory; ordered
    exits zig-zag down the map."""
    w = ri(rng, *DOOR[b])
    lanes = [(R0, 25), (28, 51), (54, R1)]
    gaps = []
    for br in (26, 52):
        hwall(g, br, C0, C1)                 # full span: merges are the only
        n_gap = 2 + (1 if b >= 2 else 0)     # way between lanes
        seg = (C1 - C0 + 1) // n_gap
        for q in range(n_gap):
            lo = C0 + 4 + q * seg
            hi = min(C1 - 4 - w, lo + seg - w - 4)
            gc = ri(rng, lo, max(lo, hi))
            g[br:br + 2, gc:gc + w] = False
            for k in range(w):
                meta["door_cells"].update([(br, gc + k), (br + 1, gc + k)])
            meta["doors"].append(w)
            gaps.append((br, gc, w))
    meta["blockades"] += 2
    meta["gates"] += len(gaps)
    goals.append([round(v, 3) for v in to_xy(MID, ri(rng, 46, 64))])
    goals.append([round(v, 3) for v in to_xy(66, ri(rng, 18, 38))])
    goals.append(list(GOAL))
    kp = [to_rc(*SPAWN), to_rc(*GOAL)] + [to_rc(x, y) for x, y in goals]
    # an incident is flush against a barrier and deep enough to leave exactly
    # MIN_PASS_W..MIN_PASS_W+2 cells of lane: a small free-standing block
    # would leave >= 2.5 m and force nothing
    n_inc = 1 + (1 if b >= 2 else 0)
    for _ in range(4):
        if meta["clutter"] >= n_inc:
            break
        r0, r1 = lanes[int(rng.integers(0, 3))]
        s = r1 - r0 + 1 - MIN_PASS_W - ri(rng, 0, 2)
        if scatter(rng, g, meta, kp, 1, s, s,
                   region=(r0, r1, C0 + 13, C1 - 13)):
            meta["blockades"] += 1
    meta["motifs"].append("highway")


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------
def dilate(g, rad):
    out = g.copy()
    for dr in range(-rad, rad + 1):
        for dc in range(-rad, rad + 1):
            out |= np.roll(np.roll(g, dr, 0), dc, 1)
    return out


def astar(free, start, goal):
    if not free[start] or not free[goal]:
        return None
    open_h = [(0.0, start)]
    came = {}
    gscore = {start: 0.0}
    while open_h:
        _, cur = heapq.heappop(open_h)
        if cur == goal:
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            return path[::-1]
        r, c = cur
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if not (0 <= nr < N and 0 <= nc < N) or not free[nr, nc]:
                    continue
                if dr and dc and not (free[r + dr, c] and free[r, c + dc]):
                    continue
                step = 1.4142 if (dr and dc) else 1.0
                ng = gscore[cur] + step
                if ng < gscore.get((nr, nc), 1e9):
                    gscore[(nr, nc)] = ng
                    came[(nr, nc)] = cur
                    h = max(abs(nr - goal[0]), abs(nc - goal[1]))
                    heapq.heappush(open_h, (ng + h, (nr, nc)))
    return None


def bfs_dist(walls):
    """Chebyshev distance from every cell to the nearest wall, UNCAPPED.

    v2 capped this at WIDE_CLR and filled the rest with 99, which turned a
    deep keep into a 197-wide sentinel and made corr_min meaningless. v3 keeps
    the true distance (max ~N/2), so width and bottleneck are real numbers.
    """
    dist = np.full((N, N), 4 * N, int)
    q = list(zip(*np.where(walls)))
    for r, c in q:
        dist[r, c] = 0
    dq = deque(q)                          # multi-source BFS (8-conn, unit)
    while dq:
        r, c = dq.popleft()
        d = dist[r, c]
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                nr, nc = r + dr, c + dc
                if 0 <= nr < N and 0 <= nc < N and dist[nr, nc] > d + 1:
                    dist[nr, nc] = d + 1
                    dq.append((nr, nc))
    return dist


def width_map(g):
    """Usable passage width per cell, in cells: a free cell at Chebyshev
    distance k from the nearest wall sits in a free square of 2k-1 cells.

    NO door exemption (v2 set door cells to 99): a >= 16-cell door in a 2-cell
    wall funnels to distance >= 8 at its centre, so doors are wide by geometry
    and this gate is identical to the exemption-free offline audit.
    """
    return np.where(g, 0, 2 * bfs_dist(g) - 1)


def wide_mask(g):
    w = width_map(g)
    return (w >= MIN_PASS_W) & ~g, w


def connected(mask, pts):
    """True when every point lies in one 8-connected component of mask."""
    if not all(mask[r, c] for r, c in pts):
        return False
    seen = np.zeros_like(mask)
    sr, sc = pts[0]
    seen[sr, sc] = True
    dq = deque([(sr, sc)])
    want = {(r, c) for r, c in pts[1:]}
    while dq and want:
        r, c = dq.popleft()
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                nr, nc = r + dr, c + dc
                if (0 <= nr < N and 0 <= nc < N and mask[nr, nc]
                        and not seen[nr, nc]):
                    seen[nr, nc] = True
                    want.discard((nr, nc))
                    dq.append((nr, nc))
    return not want


def still_feasible(g, pts):
    """Deployment-feasibility gate: spawn, every ordered goal and the goal all
    sit in one >= MIN_PASS_W-wide 8-connected channel."""
    mask, _ = wide_mask(g)
    return connected(mask, pts)


def place_keep(g, r, c, dist, meta, want=WIDE_CLR, reach=10):
    """Give a waypoint a pocket wide enough to rotate in, moving it as little
    as possible.

    Nudge to the nearest free cell within `reach` whose wall distance is
    already >= want. Only if none exists, punch a full wide pocket and erode
    every stub it leaves -- never clip a 2-cell-thick wall halfway, because the
    leftover 1-cell stub is what wedged the first 8 m fortress run in an
    accidental dog-leg 1 cm inside the shield's own dilation.
    """
    if dist[r, c] >= want:
        return r, c
    r0, r1 = max(1, r - reach), min(N - 2, r + reach)
    c0, c1 = max(1, c - reach), min(N - 2, c + reach)
    win = (dist[r0:r1 + 1, c0:c1 + 1] >= want) & ~g[r0:r1 + 1, c0:c1 + 1]
    ys, xs = np.where(win)
    if len(ys):
        d = np.abs(ys - (r - r0)) + np.abs(xs - (c - c0))
        i = int(np.argmin(d))
        return r0 + int(ys[i]), c0 + int(xs[i])
    clear(g, r, c, want)                   # nowhere deep enough: punch a
    erode_thin(g, r, c, want + 2)          # wide pocket and remove the stubs
    meta["punched"] += 1
    return r, c


def bottleneck(w, a, b):
    """max-min (widest) path value between two cells in width map w; -1 if no
    path exists. The accepted-route corridor width, in cells."""
    if w[a] <= 0 or w[b] <= 0:
        return -1
    best = {a: w[a]}
    open_h = [(-w[a], a)]
    while open_h:
        neg, cur = heapq.heappop(open_h)
        cur_w = -neg
        if cur_w < best.get(cur, -1):
            continue
        if cur == b:
            return cur_w
        r, c = cur
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if not (dr or dc):
                    continue
                nr, nc = r + dr, c + dc
                if not (0 <= nr < N and 0 <= nc < N):
                    continue
                nw = min(cur_w, w[nr, nc])
                if nw > best.get((nr, nc), -1):
                    best[(nr, nc)] = nw
                    heapq.heappush(open_h, (-nw, (nr, nc)))
    return -1


def turn_count(path):
    if len(path) < 5:
        return 0
    pts = np.array(path, float)
    head = []
    for i in range(1, len(pts)):
        head.append(math.atan2(pts[i][0] - pts[i - 1][0],
                               pts[i][1] - pts[i - 1][1]))

    def delta(a, bb):
        return abs((a - bb + math.pi) % (2 * math.pi) - math.pi)

    # sharp turns: heading flips within a 3-step window
    hard = sum(1 for i in range(3, len(head))
               if delta(head[i], head[i - 3]) > math.pi / 2)
    # gentle/diagonal-smoothed corners: any single-step heading change > 60 deg
    soft = sum(1 for i in range(1, len(head))
               if delta(head[i], head[i - 1]) > math.pi / 3)
    return max(hard, soft)


def pocket_free(g, dist):
    """True when every 8-connected free region holds a cell at distance >=
    WIDE_CLR. A region that never gets that deep is a sealed sub-bar pocket:
    the robot could be pushed into it with no room to rotate or to be extracted
    by any shield tier, so the whole map is rejected."""
    free = ~g
    seen = np.zeros_like(g)
    for r in range(N):
        for c in range(N):
            if not free[r, c] or seen[r, c]:
                continue
            deep = False
            dq = deque([(r, c)])
            seen[r, c] = True
            while dq:
                cr, cc = dq.popleft()
                if dist[cr, cc] >= WIDE_CLR:
                    deep = True
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        nr, nc = cr + dr, cc + dc
                        if (0 <= nr < N and 0 <= nc < N and free[nr, nc]
                                and not seen[nr, nc]):
                            seen[nr, nc] = True
                            dq.append((nr, nc))
            if not deep:
                return False
    return True


# --------------------------------------------------------------------------
# one map
# --------------------------------------------------------------------------
FAMILIES = {1: "corridor", 2: "gates", 3: "loop", 4: "fortress",
            5: "competition", 6: "warehouse", 7: "highway"}

# The 8 dihedral symmetries of the square, (row, col) -> (row, col).
# Isometries: solvability, clearance, rho and turn counts all carry over, so
# the transform is applied AFTER the quality gates to diversify spawn/goal
# placement (no more always bottom-left -> top-right).
_TF = [
    lambda r, c: (r, c),
    lambda r, c: (N - 1 - c, r),
    lambda r, c: (N - 1 - r, N - 1 - c),
    lambda r, c: (c, N - 1 - r),
    lambda r, c: (r, N - 1 - c),
    lambda r, c: (N - 1 - r, c),
    lambda r, c: (c, r),
    lambda r, c: (N - 1 - c, N - 1 - r),
]


def apply_tf(k, g, path_rc, goals, sp, gl):
    """map grid, geodesic, ordered goals, spawn and goal through symmetry k"""
    f = _TF[k]
    if k:
        rr, cc = np.indices((N, N))
        R, C = f(rr, cc)
        out = np.zeros_like(g)
        out[R, C] = g
        g = out
        path_rc = [f(*rc) for rc in path_rc]
        goals = [[round(v, 3) for v in to_xy(*f(*to_rc(x, y)))]
                 for x, y in goals]
    sp = [round(v, 3) for v in (to_xy(*f(*to_rc(*sp))) if k else sp)]
    gl = [round(v, 3) for v in (to_xy(*f(*to_rc(*gl))) if k else gl)]
    return g, path_rc, goals, sp, gl


def build_map(fam, b, idx):
    base = 97000 * fam + 9700 * b + 97 * idx
    for attempt in range(40):
        seed = base + attempt
        rng = np.random.default_rng(seed)
        g = new_grid()
        meta = {"motifs": [], "doors": [], "blockades": 0, "gates": 0,
                "uturns": 0, "clutter": 0, "door_cells": set(),
                "used_rows": set(), "punched": 0}
        goals = []
        if fam == 1:
            m_serpentine(rng, g, b, meta)
        elif fam == 2:
            # one or the other: a gauntlet already claims up to 4 of the 4 wall
            # rows the pitch allows, so a stacked gate chain would fall through
            # pick_rows and degenerate to a no-op
            if rng.random() < 0.5:
                m_gauntlet(rng, g, b, meta)
            else:
                m_gate_chain(rng, g, b, meta, goals)
        elif fam == 3:
            if rng.random() < 0.5:
                m_roundabout(rng, g, b, meta, goals)
            else:
                m_perimeter(rng, g, b, meta, goals)
        elif fam == 4:
            m_fortress(rng, g, b, meta, goals)
        elif fam == 5:
            m_micromouse(rng, g, b, meta, goals)
        elif fam == 6:
            m_warehouse(rng, g, b, meta, goals)
        else:
            m_highway(rng, g, b, meta, goals)
        sp = meta.get("spawn", list(SPAWN))
        gl = meta.get("goal", list(GOAL))
        # waypoints get a rotation pocket by nudging, never by punching a box
        # that clips a 2-cell-thick wall and leaves a dog-leg stub behind
        dist = bfs_dist(g)
        sr, sc = place_keep(g, *to_rc(*sp), dist, meta)
        gr, gc = place_keep(g, *to_rc(*gl), dist, meta)
        goals = [[round(v, 3) for v in
                  to_xy(*place_keep(g, *to_rc(x, y), dist, meta))]
                 for x, y in goals]
        if meta["punched"]:
            dist = bfs_dist(g)
        sp = [round(v, 3) for v in to_xy(sr, sc)]
        gl = [round(v, 3) for v in to_xy(gr, gc)]
        pts = [(sr, sc)] + [to_rc(x, y) for x, y in goals] + [(gr, gc)]
        if fam <= 3:                    # archetypes carry their own clutter
            m_clutter(rng, g, b, meta, pts)

        dist = bfs_dist(g)              # fresh: clutter/punches moved walls
        free = ~dilate(g, INF_CELLS)
        full, path_len = [], 0.0
        ok = True
        for a, bb in zip(pts[:-1], pts[1:]):
            p = astar(free, a, bb)
            if p is None:
                ok = False
                break
            full += p
            path_len += sum(
                (1.4142 if (abs(p[i + 1][0] - p[i][0]) and
                            abs(p[i + 1][1] - p[i][1])) else 1.0)
                * CELL for i in range(len(p) - 1))
        if not ok or len(full) < 8:
            continue
        # detour ratio against the direct spawn->goal line (tour maps count the
        # full multi-goal route length, so they are inherently longer)
        eucl = math.dist(sp, gl)
        rho = path_len / max(eucl, 1e-6)
        if rho < 1.15:
            continue
        # clearance gate: intentional door gaps are exempt (they hug the wall
        # by construction); everything else on the geodesic must stay >= 2
        # cells from any wall so narrow spots are doors, not accidental pinches
        dc = meta["door_cells"]
        if min((dist[r, c] for r, c in full if (r, c) not in dc),
               default=99) < MIN_PATH_CLR:
            continue
        # pocket-free gate: no sealed sub-bar trap anywhere on the map
        if not pocket_free(g, dist):
            continue
        # deployment bar: spawn, every ordered goal and the goal share one
        # >= MIN_PASS_W-wide channel (no door exemption -- doors are wide by
        # geometry, see width_map). This implies every leg's widest path is
        # >= MIN_PASS_W, checked explicitly next.
        mask, wmap = wide_mask(g)
        if not connected(mask, pts):
            continue
        bneck = [bottleneck(wmap, a, bb) for a, bb in zip(pts[:-1], pts[1:])]
        if min(bneck) < MIN_PASS_W:
            continue
        turns = turn_count(full)
        door_min = min(meta["doors"]) * CELL if meta["doors"] else 2.75
        door_n = min(max((2.75 - door_min) / 0.75, 0), 1)
        struct_n = min((meta["blockades"] + meta["gates"]
                        + 2 * meta["uturns"]) / 12.0, 1)
        rho_n = min(max((rho - 1.15) / 2.5, 0), 1)
        turn_n = min(turns / 10.0, 1)
        clut_n = min(meta["clutter"] / 6.0, 1)
        D = (0.30 * door_n + 0.25 * struct_n + 0.20 * rho_n
             + 0.15 * turn_n + 0.10 * clut_n)
        k = ri(rng, 0, 7)
        g, full, goals, sp, gl = apply_tf(k, g, full, goals, sp, gl)
        path_xy = [[round((c + 0.5) * CELL, 3), round((r + 0.5) * CELL, 3)]
                   for r, c in full[::4]]
        return g, meta, goals, dict(D=round(D, 3), rho=round(rho, 2),
                                    turns=turns, door_min=round(door_min, 2),
                                    corr_min=round(min(bneck) * CELL, 3),
                                    path_len=round(path_len, 2),
                                    path=path_xy, seed=seed,
                                    tf=k, spawn=sp, goal=gl)
    return None, None, None, None


def grid_to_boxes(g):
    boxes = []
    for r in range(N):
        c = 0
        while c < N:
            if g[r, c]:
                c0 = c
                while c + 1 < N and g[r, c + 1]:
                    c += 1
                boxes.append([round((c0 + c + 1) / 2 * CELL, 4),
                              round((r + 0.5) * CELL, 4), 0.0,
                              round((c - c0 + 1) * CELL, 4), CELL, 0.5])
            c += 1
    # Vertical merge (ledger 17.18). The row-wise pass emits one 0.125 m slab
    # per row, so any vertical wall -- including the E/W border columns --
    # becomes a chain of touching cubes. PhysX depenetrates each cube on its
    # own, and a hull/wheel crossing an internal seam takes an ejection spike
    # that flings the robot THROUGH the border: the third arm's off-map leak on
    # f1_b0_m01 (env 0 tumbling at ~5x v_max from spawn, out the east wall at
    # x=10.02). The shield's BoxSDF certifies the smooth union, so the physical
    # seam behaviour diverges from the modelled geometry and the guarantee is
    # lost exactly at the boundary. Merge stacks that share (x-centre, width,
    # yaw) and are contiguous in y into one tall box. The occupied region is
    # identical -- only the decomposition changes -- so clearances, the width
    # audit, spawn and goal are untouched, while the collision geometry now
    # matches the SDF the shield certifies (and the box count drops ~3x).
    def _key(b):
        return (b[0], b[3], b[2])
    boxes.sort(key=lambda b: (_key(b), b[1]))
    merged = []
    for b in boxes:
        if merged and _key(merged[-1]) == _key(b):
            m = merged[-1]
            if abs((b[1] - b[4] / 2.0) - (m[1] + m[4] / 2.0)) < 1e-6:
                y0 = m[1] - m[4] / 2.0
                y1 = b[1] + b[4] / 2.0
                m[1] = round((y0 + y1) / 2.0, 4)
                m[4] = round(y1 - y0, 4)
                continue
        merged.append(list(b))
    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per", type=int, default=2,
                    help="maps per (family, bin) cell")
    ap.add_argument("--preview", action="store_true")
    args = ap.parse_args()
    os.makedirs(GEN, exist_ok=True)
    manifest = {}
    for fam in range(1, 8):
        for b in (0, 1, 2, 3):
            for i in range(args.per):
                name = f"f{fam}_b{b}_m{i:02d}"
                g, meta, goals, info = build_map(fam, b, i)
                if g is None:
                    print(f"  REJECT {name}: no valid layout in 40 tries")
                    continue
                doc = {"name": name, "size": [SIZE, SIZE], "cell": CELL,
                       "wall_height": 0.5, "boxes": grid_to_boxes(g),
                       "spawn": info["spawn"],
                       "goal": goals[-1] if goals else info["goal"],
                       "path_len": info["path_len"]}
                if goals:
                    doc["goals"] = goals
                with open(os.path.join(GEN, name + ".json"), "w") as f:
                    json.dump(doc, f, indent=1)
                manifest[name] = {"family": FAMILIES[fam], "bin": b,
                                  "motifs": meta["motifs"],
                                  "blockades": meta["blockades"],
                                  "gates": meta["gates"],
                                  "uturns": meta["uturns"],
                                  "clutter": meta["clutter"],
                                  **info}
                print(f"  wrote {name}  D={info['D']:.2f} "
                      f"rho={info['rho']:.2f} turns={info['turns']} "
                      f"door={info['door_min']:.2f} "
                      f"corr={info['corr_min']:.3f} tf={info['tf']} "
                      f"seed={info['seed']} "
                      f"sp={info['spawn']} gl={doc['goal']} "
                      f"motifs={meta['motifs']}")
    with open(os.path.join(GEN, "_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    print(f"{len(manifest)} maps in {GEN}")
    if args.preview:
        make_preview(manifest, args.per)


def make_preview(manifest, per):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    groups = [(1, 2, 3, 4), (5, 6, 7)]
    for i in range(per):
        for gi, gf in enumerate(groups):
            fig, axs = plt.subplots(len(gf), 4,
                                    figsize=(13.0, 3.3 * len(gf)))
            for row, fam in enumerate(gf):
                for b in (0, 1, 2, 3):
                    ax = axs[row, b]
                    name = f"f{fam}_b{b}_m{i:02d}"
                    m = manifest.get(name)
                    ax.set_aspect("equal")
                    ax.set_xticks([0, 5, 10])
                    ax.set_yticks([0, 5, 10])
                    ax.tick_params(labelsize=6)
                    if m is None:
                        ax.set_title(f"{name} REJECTED", fontsize=8, color="r")
                        continue
                    doc = json.load(open(os.path.join(GEN, name + ".json")))
                    for bx in doc["boxes"]:
                        ax.add_patch(plt.Rectangle(
                            (bx[0] - bx[3] / 2, bx[1] - bx[4] / 2),
                            bx[3], bx[4], fc="0.35", ec="none"))
                    p = np.array(m["path"])
                    ax.plot(p[:, 0], p[:, 1], "--", lw=0.9, color="C0")
                    ax.plot(doc["spawn"][0], doc["spawn"][1], "o",
                            color="C2", ms=5)
                    gl = doc.get("goals", [doc["goal"]])
                    for j, gg in enumerate(gl):
                        ax.plot(gg[0], gg[1], "*", color="C3", ms=9)
                        ax.annotate(str(j + 1), (gg[0], gg[1]), fontsize=7,
                                    color="C3", xytext=(3, 3),
                                    textcoords="offset points")
                    ax.set_title(
                        f"{name} [{FAMILIES[fam]}]  D={m['D']:.2f} "
                        f"door={m['door_min']:.2f} "
                        f"corr={m['corr_min']:.2f}\n"
                        f"{'+'.join(m['motifs'])}", fontsize=7)
            fig.suptitle(
                f"Procedural maze sample (10 x 10 m), map index {i}, sheet "
                f"{'ab'[gi]} (rows=families "
                f"{'/'.join(FAMILIES[f] for f in gf)}, cols=bins "
                f"easy->extreme; dashed=inflated-A* geodesic, green dot=spawn,"
                f" numbered stars=ordered goals)", fontsize=10)
            fig.tight_layout()
            out = os.path.join(GEN, f"preview_{i}_{'ab'[gi]}.png")
            fig.savefig(out, dpi=130)
            plt.close(fig)
            print("preview:", out)


if __name__ == "__main__":
    main()
