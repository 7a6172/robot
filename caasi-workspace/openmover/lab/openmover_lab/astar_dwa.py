"""In-house classical baseline: A* global plan + DWA local controller.

The campaign baseline arm (ledger 17.x, submission-readiness campaign). A
textbook classical stack, implemented from scratch (no nav2):

  - **A*** on the env's boolean occupancy grid (``_geo_occ``, 0.25 m cells,
    obstacles inflated by ``geo_inflate`` = 0.20 m), 8-connected with
    diagonal-corner rules, octile heuristic. Replanned from the robot's
    current cell every ``PLAN_EVERY`` steps and whenever tracking error to
    the path exceeds ``REPLAN_ERR`` (static map, so this only heals drift).
  - **DWA** over the same constant-twist candidate set the deployment shield
    uses (``SHIELD_V_SET`` x ``SHIELD_W_SET``, filtered for Stack A wheel
    realizability |v|/v_full + |w|/w_full <= 1), arcs simulated with the
    shield's ``_arc_poses`` (0.8 s horizon + braking tail). A candidate is
    admissible when the 51-point hull stays at least
    ``max(DWA_MARGIN, current_clearance - DWA_EPS)`` from the TRUE box
    geometry (the shield's exact ``BoxSDF`` — the baseline gets the same map
    knowledge, so the comparison is control architecture, not oracle access).
    The pose-relative floor lets the robot turn when it already hugs a wall
    but never lets clearance DECREASE. Score = goal progress (true geodesic
    distance at the arc end) + heading to the local waypoint + speed +
    clearance. All candidates rejected -> zero twist (the classical stack has
    NO escape tier, retreat, backup policy, pin latch, or hysteresis — that
    gap is the point of the comparison).

Information parity with the learning arm: static map + goal (both know it);
no lidar used by either at decision time. Difference: policy+shield selects
twists by a certified safe-set projection with escape/retreat tiers; A*+DWA
follows a global plan with a scored local window.

Interface mirrors ``GeodesicExpert``: ``action()`` -> (N, 2) wheel fractions,
``episode_reset(env_ids)``, ``stats()``. N <= 4 envs (one tile each).
"""

import heapq
import math

import numpy as np
import torch

from .shield_lite import (
    SHIELD_HULL_PTS,
    SHIELD_V_SET,
    SHIELD_W_SET,
    WHEEL_SEPARATION,
    BoxSDF,
    _arc_hull,
    _arc_poses,
)

PLAN_EVERY = 20      # steps between scheduled replans (1 s at 20 Hz)
REPLAN_ERR = 0.75    # m tracking error to the path that forces a replan
WP_LOOKAHEAD = 0.50  # m: first path point at least this far ahead is the target
DWA_MARGIN = 0.03    # m hull clearance required of a DWA candidate (true boxes)
DWA_EPS = 0.02       # m: pose-relative admissibility slack (see _score)
W_PROGRESS = 1.0     # score weight: -geodesic distance at arc end (per m)
W_HEADING = 0.8      # score weight: cos(heading to local waypoint)
W_SPEED = 0.3        # score weight: forward speed (per m/s)
W_CLEAR = 0.10       # score weight: min hull clearance along the arc (per m)


class AstarDwa:
    """A* + DWA baseline controller, vectorized over N <= 4 envs."""

    def __init__(self, wrapped, spec, v_full: float,
                 wheel_separation: float = WHEEL_SEPARATION):
        self.env = wrapped
        self.n = wrapped.num_envs
        self.device = wrapped.device
        self.v_full = float(v_full)
        self.w_full = 2.0 * self.v_full / float(wheel_separation)
        if not hasattr(wrapped, "_geo_occ"):
            raise ValueError(
                "AstarDwa needs the occupancy-grid env (use_geodesic_progress / "
                "use_waypoint_obs)")
        # --- static grid (identical on every tile for a custom map) ---
        self.gx, self.gy = int(wrapped._geo_gx), int(wrapped._geo_gy)
        self.res = float(wrapped.cfg.geo_res)
        sx, sy = wrapped._geo_size
        self.sx, self.sy = float(sx), float(sy)
        occ = wrapped._geo_occ[wrapped._env_tile[: self.n]]  # (N, gy, gx)
        self.occ = [occ[e].cpu().numpy() for e in range(self.n)]
        # --- true box geometry for DWA rejection (same field as the shield) ---
        # genmaps boxes are (x, y, yaw, sx, sy, z); BoxSDF wants the first five
        boxes = [tuple(float(v) for v in b[:5]) for b in spec["boxes"]]
        self.sdf = BoxSDF(boxes, bounds=(0.0, 0.0, sx, sy))
        self._half = np.array([0.5 * sx, 0.5 * sy])  # tile centre -> corner
        # --- candidate arcs (realizability-filtered, shield kinematics) ---
        cv, cw = (x.ravel() for x in
                  np.meshgrid(SHIELD_V_SET, SHIELD_W_SET, indexing="ij"))
        keep = (np.abs(cv) / self.v_full
                + np.abs(cw) / self.w_full) <= 1.0 + 1e-9
        cv, cw = cv[keep], cw[keep]
        self._cv, self._cw = cv, cw
        p = _arc_poses(cv, cw)
        self._pts = _arc_hull(p, SHIELD_HULL_PTS)   # (C, K, H, 2) robot frame
        self._end = p[:, -1, :].copy()              # (C, 3) end pose
        # --- per-env state ---
        self.paths = [None] * self.n       # list of (i, j) cells or None
        self._tick = 0
        self.n_plan = self.n_replan = self.n_reject = self.n_stuck = 0
        print(f"[baseline] A*+DWA ready (grid {self.gy}x{self.gx} @ {self.res} m, "
              f"{len(spec['boxes'])} boxes, dwa={cv.shape[0]} candidates)")

    # ------------------------------------------------------------------ A*
    def _cell_of(self, x_tile, y_tile):
        i = min(max(int((x_tile + 0.5 * self.sx) // self.res), 0), self.gx - 1)
        j = min(max(int((y_tile + 0.5 * self.sy) // self.res), 0), self.gy - 1)
        return i, j

    def _xy_of(self, i, j):
        return ((i + 0.5) * self.res - 0.5 * self.sx,
                (j + 0.5) * self.res - 0.5 * self.sy)

    def _plan(self, e, start, goal):
        """8-connected A* on the inflated grid, tile frame. Returns a list of
        cell centres [(x, y), ...] from start to goal, or None."""
        occ = self.occ[e]          # NOTE: indexed [j(y), i(x)] — shape (gy, gx)
        si, sj = self._cell_of(*start)
        gi, gj = self._cell_of(*goal)
        if occ[gj, gi]:  # goal cell inflated shut: retreat toward the goal
            best, bd = None, 1e9
            for di in range(-8, 9):
                for dj in range(-8, 9):
                    ii, jj = gi + di, gj + dj
                    if 0 <= ii < self.gx and 0 <= jj < self.gy and not occ[jj, ii]:
                        d = math.hypot(di * self.res, dj * self.res)
                        if d < bd:
                            best, bd = (ii, jj), d
            if best is None:
                return None
            gi, gj = best
        if occ[sj, si]:  # robot cell inflated shut (hugging a wall): allow it
            pass
        NB = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
              (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)),
              (-1, 1, math.sqrt(2)), (-1, -1, math.sqrt(2))]

        def h(i, j):
            dx, dy = abs(i - gi), abs(j - gj)
            return self.res * (max(dx, dy) + (math.sqrt(2) - 1) * min(dx, dy))

        open_heap = [(h(si, sj), 0.0, si, sj)]
        gscore = {(si, sj): 0.0}
        came = {}
        closed = set()
        while open_heap:
            _, g, i, j = heapq.heappop(open_heap)
            if (i, j) in closed:
                continue
            if (i, j) == (gi, gj):
                # reconstruct
                cells = [(gi, gj)]
                while cells[-1] in came:
                    cells.append(came[cells[-1]])
                cells.reverse()
                return [self._xy_of(ci, cj) for ci, cj in cells]
            closed.add((i, j))
            for di, dj, cost in NB:
                ni, nj = i + di, j + dj
                if not (0 <= ni < self.gx and 0 <= nj < self.gy):
                    continue
                if occ[nj, ni] and (ni, nj) != (si, sj):
                    continue
                if di and dj and (occ[j, i + di] or occ[j + dj, i]):
                    continue  # no corner cutting
                ng = g + cost * self.res
                if ng < gscore.get((ni, nj), 1e18) - 1e-9:
                    gscore[(ni, nj)] = ng
                    came[(ni, nj)] = (i, j)
                    heapq.heappush(open_heap, (ng + h(ni, nj), ng, ni, nj))
        return None

    # ----------------------------------------------------------------- DWA
    def _gdist_cells(self, e, xs_tile, ys_tile):
        """Geodesic distance-to-goal at tile-frame points (CPU replica of
        env._geo_lookup's clamped nearest-cell indexing; the field is copied
        to host once per tick in action())."""
        ix = np.clip(((xs_tile + 0.5 * self.sx) / self.res).astype(np.int64),
                     0, self.gx - 1)
        iy = np.clip(((ys_tile + 0.5 * self.sy) / self.res).astype(np.int64),
                     0, self.gy - 1)
        d = self._geo_cpu[e, iy, ix]
        big = (self.gx + self.gy) * self.res
        return np.minimum(d, big)

    def _score(self, e, cv, pts, end, xy, yaw, tgt_local, gdist_now, cur_clr):
        """(C,) DWA score and admissibility mask, robot frame."""
        c0, s0 = math.cos(yaw), math.sin(yaw)
        # tile frame -> corner-local (the SDF's frame): + half the map size
        wx = xy[0] + pts[..., 0] * c0 - pts[..., 1] * s0 + self._half[0]
        wy = xy[1] + pts[..., 0] * s0 + pts[..., 1] * c0 + self._half[1]
        clr = self.sdf.sample(wx, wy).min(axis=2)          # (C, K)
        # Admissible = the hull never gets closer to the true geometry than
        # floor = DWA_MARGIN, except when the robot ALREADY sits tighter than
        # that (spawns can hug corners): then the floor relaxes to
        # cur_clr - DWA_EPS so rotations that do not decrease clearance stay
        # admissible. With plentiful clearance the absolute margin governs, so
        # arcs may trade clearance down to DWA_MARGIN (otherwise the robot
        # could never leave an open pocket — every exit temporarily decreases
        # clearance). A stopped arc is always admissible: the baseline freezes
        # instead of fighting the wall — no escape tier, no retreat, no backup.
        floor = DWA_MARGIN
        if cur_clr < floor:
            floor = cur_clr - DWA_EPS
        ok = (clr.min(axis=1) >= floor)
        # true geodesic progress at the arc end (tile frame)
        ex = xy[0] + end[:, 0] * c0 - end[:, 1] * s0
        ey = xy[1] + end[:, 0] * s0 + end[:, 1] * c0
        d_end = self._gdist_cells(e, ex, ey)
        d_end = np.where(np.isfinite(d_end), d_end, 1e3)
        # heading to the local waypoint at the arc end
        dxe = tgt_local[0] - end[:, 0]
        dye = tgt_local[1] - end[:, 1]
        head = np.cos(np.arctan2(dye, dxe) - end[:, 2])
        score = (W_PROGRESS * (gdist_now - d_end)
                 + W_HEADING * head
                 + W_SPEED * cv
                 + W_CLEAR * np.minimum(clr.min(axis=1), 1.0))
        return score, ok

    def _dwa(self, e, xy, yaw, tgt_local, gdist_now):
        """One env, one tick: returns (aL, aR) wheel fractions in [-1, 1]."""
        # clearance of the CURRENT pose (hull at rest) — admissibility floor
        c0, s0 = math.cos(yaw), math.sin(yaw)
        hx = xy[0] + SHIELD_HULL_PTS[:, 0] * c0 - SHIELD_HULL_PTS[:, 1] * s0
        hy = xy[1] + SHIELD_HULL_PTS[:, 0] * s0 + SHIELD_HULL_PTS[:, 1] * c0
        cur_clr = float(self.sdf.sample(hx + self._half[0], hy + self._half[1]).min())
        score, ok = self._score(e, self._cv, self._pts, self._end, xy, yaw,
                                tgt_local, gdist_now, cur_clr)
        if ok.any():
            b = int(np.argmax(np.where(ok, score, -1e18)))
            va, wa = float(self._cv[b]), float(self._cw[b])
            return ((va - 0.5 * wa * WHEEL_SEPARATION) / self.v_full,
                    (va + 0.5 * wa * WHEEL_SEPARATION) / self.v_full)
        # every candidate rejected: the classical stack stops (no escape tier,
        # no retreat, no backup policy — this is the architecture gap the
        # campaign measures)
        self.n_reject += 1
        self.n_stuck += 1
        return 0.0, 0.0

    # ---------------------------------------------------------------- main
    def action(self) -> torch.Tensor:
        pos = self.env._robot.data.root_pos_w.torch[: self.n]
        q = self.env._robot.data.root_quat_w.torch[: self.n]
        yaw = torch.atan2(2.0 * (q[:, 2] * q[:, 3] + q[:, 0] * q[:, 1]),
                          1.0 - 2.0 * (q[:, 1] ** 2 + q[:, 2] ** 2))
        origins = self.env._terrain.env_origins[: self.n, :2]
        xy_t = (pos[:, :2] - origins).cpu().numpy()        # tile frame
        yaw_np = yaw.cpu().numpy()
        goal_t = (self.env._goal_pos_w[: self.n, :2] - origins).cpu().numpy()
        # one host copy of the geodesic field per tick (it only changes at
        # episode resets); all per-candidate lookups then run in numpy
        self._geo_cpu = self.env._geo_field[: self.n].cpu().numpy()
        replan = (self._tick % PLAN_EVERY == 0)
        self._tick += 1
        out = np.zeros((self.n, 2), dtype=np.float32)
        for e in range(self.n):
            xy, yaw_e, goal = xy_t[e], float(yaw_np[e]), goal_t[e]
            path = self.paths[e]
            need = replan or path is None
            if not need and path is not None:
                d = min(math.hypot(xy[0] - px, xy[1] - py) for px, py in path)
                need = d > REPLAN_ERR
            if need:
                path = self._plan(e, tuple(xy), tuple(goal))
                if path is not None:
                    self.paths[e] = path
                    self.n_plan += 1
                    if self._tick > 1:
                        self.n_replan += 1
                else:
                    self.paths[e] = None
            path = self.paths[e]
            # local waypoint: first path point >= WP_LOOKAHEAD ahead, else goal
            tgt = goal
            if path is not None:
                for px, py in path:
                    if math.hypot(px - xy[0], py - xy[1]) >= WP_LOOKAHEAD:
                        tgt = (px, py)
                        break
            c0, s0 = math.cos(yaw_e), math.sin(yaw_e)
            dx, dy = tgt[0] - xy[0], tgt[1] - xy[1]
            tgt_local = (dx * c0 + dy * s0, -dx * s0 + dy * c0)
            gd = float(self._gdist_cells(e, np.array([xy[0]]), np.array([xy[1]]))[0])
            gnow = gd if np.isfinite(gd) else 1e3
            aL, aR = self._dwa(e, xy, yaw_e, tgt_local, gnow)
            out[e] = (aL, aR)
        act = torch.tensor(out, dtype=torch.float32, device=self.device)
        return act.clamp(-1.0, 1.0)

    def episode_reset(self, env_ids):
        for e in env_ids.tolist() if hasattr(env_ids, "tolist") else env_ids:
            self.paths[int(e)] = None

    def stats(self) -> dict:
        return {"plan": self.n_plan, "replan": self.n_replan,
                "dwa_reject": self.n_reject, "stuck": self.n_stuck,
                "steps": self._tick * self.n}
