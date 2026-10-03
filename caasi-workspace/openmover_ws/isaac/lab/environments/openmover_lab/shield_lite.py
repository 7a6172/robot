"""Shield-lite: the adopted deployment shield (policy_node.py v7.4, ledger
17.14) ported to Stack A as a runner-side shim, plus the v7.5 escape-tier
fall-through fix (ledger 17.19). The v7.6 tier-3 hysteresis experiment was
REVERTED after validation (ledger 17.19 item 7); this file is v7.5 behavior.

Same contract as CbfLite: the frozen policy is deployed UNCHANGED, the shim
sits between the policy and ``env.step`` (last in the chain — the shield gets
final authority), and when no env's command is filtered the input tensor is
returned untouched (bit-for-bit baseline reproduction).

Ported semantics (constants IDENTICAL to v7.4; control flow = v7.4 except the
escape-tier fall-through fixed in v7.5, see ``_shield_env``):
  - exact-box ESDF barrier (BoxSDF over the map's wall boxes, 0.025 m lattice,
    bilinear sampling, out-of-bounds = wall) with the certified floor
    SHIELD_MARGIN + SHIELD_ESDF_SLACK over a 51-point hull perimeter,
  - constant-twist candidate arcs (0.8 s + braking tail) for the policy twist,
    the last published twist, the 56-candidate comfort set, the 35-candidate
    escape set,
  - three tiers: comfort (projection onto the safe set, CBF-QP form) ->
    escape (certified 2 cm floor, reverse-preferring when pinned; v7.5 never
    publishes a STOP while a certified mover is admissible) -> retreat
    (max clearance gain when even the floor is violated; deliberately NO
    continuity term — the v7.6 hysteresis experiment was reverted),
  - goal-directed backup policy inside the safe set when the projection would
    freeze (|v| < 0.1 or pinned),
  - hysteresis bonus for repeating the last published twist,
  - geometric pin latch: 10 vetoed ticks without 0.03 m of motion -> pinned
    (escape prefers reverse, tier-1 passthrough SUSPENDED — v7.4, ledger
    17.13/17.14), release after 0.20 m of real motion.

Deliberate deviations from the Stack B deployment node (documented for the
equivalence check, ledger 17.15):
  - NO lidar raster half of the union barrier. In Stack A every obstacle is a
    map box (the raycaster is exact, hits land on box surfaces), so
    policy_node's own unmapped filter (sdf.sample > 0.05) empties the raster
    there too — the union degenerates to the exact-field half. Dropping it
    also removes the last-seen persistence buffer (no near-clip blindness to
    guard against when the barrier never needs the sensor).
  - NO recovery/contact paths: Stack A has no recovery layer, so
    ``recovering`` is always False and the contact-EMA pin trigger does not
    exist; the pin latch is purely geometric, as in v7.4.
  - The backup direction comes from the env's NATIVE geodesic waypoint
    (``_geo_waypoint``, geo_inflate 0.20) instead of the deployment field
    (GEO_INFLATE 0.35): the backup objective only uses the waypoint DIRECTION
    (scale-invariant), and the native field is what the Stack A expert chases.
  - Output wheel fractions are clamped to [-1, 1] per wheel, which is exactly
    the actuator saturation of the velocity-target action space, and the
    candidate sets are filtered to the realizable simplex
    |v|/v_full + |w|/w_full <= 1 so every certified twist is one the plant
    can actually follow (Stack B realized published twists directly).

Frames: the map spec is corner-local (origin at the tile corner); the terrain
origin is the tile CENTER, so robot corner-local xy =
``root_pos_w[:, :2] - env_origins[env, :2] + 0.5 * (size_x, size_y)``.

Cost: N <= 4 envs (custom-map tile limit), per-env numpy. Tier 1 samples
2 x 33 x 51 hull points per env per tick (~3.4k); a vetoed tick adds the
56-candidate batch (~94k) and, at the escape floor, ~59k more. Fine offline;
this is not a real-time node.
"""

import math

import numpy as np
import torch

# --- constants: IDENTICAL to policy_node.py v7.4 (ledger 17.9-17.14) -------
SHIELD_MARGIN = 0.10      # m hull-surface clearance enforced on candidates
SHIELD_HORIZON = 0.8      # s of constant-twist arc simulated per candidate
SHIELD_BRAKE_A = 0.6      # m/s^2 braking decel for the stop tail
SHIELD_DT = 0.05          # s arc integration step
SHIELD_V_SET = (-0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
SHIELD_W_SET = (-0.9, -0.6, -0.3, 0.0, 0.3, 0.6, 0.9)
SHIELD_ESDF_RES = 0.025   # m signed-distance-field lattice over the map boxes
SHIELD_ESDF_HALO = 1.0    # m per-box refinement halo (field clamped outside)
SHIELD_ESDF_PAD = 0.60    # m field extent beyond the drivable bounds
SHIELD_ESDF_SLACK = 0.05  # m certified-floor slack (lattice + hull discretisation)
SHIELD_HULL_SPACING = 0.03  # m hull perimeter sample spacing (51 pts + centre)
SHIELD_ESCAPE_MARGIN = 0.02  # m certified clearance floor of the escape tier
SHIELD_ESCAPE_VMAX = 0.20  # m/s cap on escape-tier candidates
SHIELD_RAW_PAD = 0.08     # m hull growth for escape-tier (raster-era) checks
SHIELD_W_SCALE = 0.25     # m per rad/s in the safe-set projection
SHIELD_BACKUP_ALIGN = 0.15  # heading-alignment weight in the backup objective
SHIELD_HYST_BONUS = 0.05  # score bonus for repeating the last published twist
SHIELD_PIN_TICKS = 10     # vetoed ticks (0.5 s at 20 Hz) without motion -> pin
SHIELD_PIN_MOVE = 0.03    # m of motion per tick that counts as "not stuck"
SHIELD_PIN_RELEASE = 0.20  # m of motion that clears a latched pin

# trained-robot kinematics (openmover URDF + openmover_nav_cfg.py)
WHEEL_SEPARATION = 0.324  # m (wheel joints at y = +-0.162)


def _hull_perimeter(hx=0.22, hy=0.14, spacing=SHIELD_HULL_SPACING):
    """Hull sample points: centre + rectangle perimeter at ~`spacing`
    (verbatim from policy_node; 0.03 m spacing bounds the discretisation at
    spacing/2 = 0.015 m, which SHIELD_ESDF_SLACK pays for)."""
    pts = [(0.0, 0.0)]
    corners = [(hx, hy), (-hx, hy), (-hx, -hy), (hx, -hy)]
    for k, (x0, y0) in enumerate(corners):
        x1, y1 = corners[(k + 1) % 4]
        n = max(1, int(math.ceil(math.hypot(x1 - x0, y1 - y0) / spacing)))
        for j in range(n):
            f = j / n
            pts.append((x0 + f * (x1 - x0), y0 + f * (y1 - y0)))
    return np.array(pts)


SHIELD_HULL_PTS = _hull_perimeter()
SHIELD_HULL_PTS_RAW = np.array(
    [(math.copysign(abs(x) + SHIELD_RAW_PAD, x) if x else 0.0,
      math.copysign(abs(y) + SHIELD_RAW_PAD, y) if y else 0.0)
     for x, y in SHIELD_HULL_PTS])


class BoxSDF:
    """Exact signed-distance field to a union of boxes (verbatim port of the
    policy_node v7 barrier field): true distance on a 0.025 m lattice,
    negative inside, clamped at +HALO beyond each box's halo. Outside the
    drivable bounds the edge of the map is a wall, reported as a RAMP
    ``-(1 + depth)`` instead of policy_node's constant -1 (ledger 17.18): the
    constant leaves every consumer with no gradient once the hull crosses the
    edge -- all candidates tie at -1, so the shield's tier-3 retreat falls back
    to its tie-break terms (reverse + spin) and drives the robot FURTHER out,
    and the planner's pose-relative floor (cur_clr - eps) admits every
    off-map arc. The ramp keeps the same semantics (always <= -1, so no
    certified floor can ever be met outside) while restoring a direction home.
    """

    def __init__(self, boxes, bounds, res=SHIELD_ESDF_RES, pad=SHIELD_ESDF_PAD):
        self.res = res
        self.bounds = tuple(float(b) for b in bounds)
        self.x0 = bounds[0] - pad
        self.y0 = bounds[1] - pad
        self.nx = int(math.ceil((bounds[2] - bounds[0] + 2.0 * pad) / res)) + 1
        self.ny = int(math.ceil((bounds[3] - bounds[1] + 2.0 * pad) / res)) + 1
        d = np.full((self.nx, self.ny), SHIELD_ESDF_HALO, dtype=np.float32)
        halo = SHIELD_ESDF_HALO
        for bx, by, yaw, sx, sy in boxes:
            r = 0.5 * math.hypot(sx, sy) + halo
            i0 = max(0, int(math.floor((bx - r - self.x0) / res)))
            i1 = min(self.nx, int(math.ceil((bx + r - self.x0) / res)) + 1)
            j0 = max(0, int(math.floor((by - r - self.y0) / res)))
            j1 = min(self.ny, int(math.ceil((by + r - self.y0) / res)) + 1)
            if i0 >= i1 or j0 >= j1:
                continue
            gx = self.x0 + np.arange(i0, i1) * res
            gy = self.y0 + np.arange(j0, j1) * res
            gxx, gyy = np.meshgrid(gx, gy, indexing="ij")
            c, s = math.cos(yaw), math.sin(yaw)
            dx, dy = gxx - bx, gyy - by
            lx = c * dx + s * dy            # box frame
            ly = -s * dx + c * dy
            ox = np.abs(lx) - 0.5 * sx      # > 0 outside the box
            oy = np.abs(ly) - 0.5 * sy
            dw = (np.hypot(np.maximum(ox, 0.0), np.maximum(oy, 0.0))
                  + np.minimum(np.maximum(ox, oy), 0.0)).astype(np.float32)
            sub = d[i0:i1, j0:j1]
            np.minimum(sub, dw, out=sub)
        cx = self.x0 + np.arange(self.nx) * res
        cy = self.y0 + np.arange(self.ny) * res
        dxo = np.maximum(bounds[0] - cx, cx - bounds[2])   # > 0 outside in x
        dyo = np.maximum(bounds[1] - cy, cy - bounds[3])
        outside = ((dxo > 0.0)[:, None] | (dyo > 0.0)[None, :])
        depth = np.hypot(np.maximum(dxo, 0.0)[:, None],
                         np.maximum(dyo, 0.0)[None, :])
        d[outside] = -(1.0 + depth[outside])
        self.d = d

    def _outside_val(self, wx, wy):
        """Analytic continuation of the out-of-bounds ramp beyond the lattice
        (the grid only reaches ESDF_PAD past the bounds)."""
        b = self.bounds
        dxo = np.maximum(b[0] - wx, wx - b[2])
        dyo = np.maximum(b[1] - wy, wy - b[3])
        return -(1.0 + np.hypot(np.maximum(dxo, 0.0),
                                np.maximum(dyo, 0.0))).astype(np.float32)

    def sample(self, wx, wy):
        """Bilinear sample at world points (any shape) -> signed distance.
        Out-of-grid points continue the out-of-bounds ramp (wall, and the
        deeper outside the worse)."""
        fx = (np.asarray(wx, dtype=np.float64) - self.x0) / self.res
        fy = (np.asarray(wy, dtype=np.float64) - self.y0) / self.res
        i0 = np.floor(fx).astype(np.intp)
        j0 = np.floor(fy).astype(np.intp)
        tx = (fx - i0).astype(np.float32)
        ty = (fy - j0).astype(np.float32)
        inside = ((i0 >= 0) & (i0 + 1 < self.nx)
                  & (j0 >= 0) & (j0 + 1 < self.ny))
        ic = np.clip(i0, 0, self.nx - 2)
        jc = np.clip(j0, 0, self.ny - 2)
        d00 = self.d[ic, jc]
        d01 = self.d[ic, jc + 1]
        d10 = self.d[ic + 1, jc]
        d11 = self.d[ic + 1, jc + 1]
        val = ((1.0 - tx) * ((1.0 - ty) * d00 + ty * d01)
               + tx * ((1.0 - ty) * d10 + ty * d11))
        return np.where(inside, val, self._outside_val(
            np.asarray(wx, dtype=np.float64), np.asarray(wy, dtype=np.float64)))


def _arc_poses(vs, ws):
    """Constant-twist arcs for a whole candidate set at once (verbatim port):
    vs, ws (C,) -> (C, K, 3) robot-frame poses along SHIELD_HORIZON s plus a
    straight braking tail at SHIELD_BRAKE_A (v <= 0 has no tail)."""
    dt = SHIELD_DT
    n = int(round(SHIELD_HORIZON / dt))
    ntail = int(math.ceil(max(SHIELD_V_SET) / (SHIELD_BRAKE_A * dt)))
    vs = np.asarray(vs, dtype=np.float64)
    ws = np.asarray(ws, dtype=np.float64)
    c = vs.shape[0]
    x = np.zeros(c)
    y = np.zeros(c)
    th = np.zeros(c)
    poses = np.empty((c, n + ntail, 3))
    for k in range(n + ntail):
        if k < n:
            sv, sw = vs, ws
        else:
            sv = np.maximum(vs - SHIELD_BRAKE_A * dt * (k - n + 1), 0.0)
            sw = np.zeros(c)
        th_mid = th + 0.5 * sw * dt
        x = x + sv * np.cos(th_mid) * dt
        y = y + sv * np.sin(th_mid) * dt
        th = th + sw * dt
        poses[:, k, 0] = x
        poses[:, k, 1] = y
        poses[:, k, 2] = th
    return poses


def _arc_hull(poses, hull):
    """(C, K, 3) arc poses x (H, 2) hull samples -> (C, K, H, 2) robot-frame
    hull sample positions (verbatim port)."""
    c = np.cos(poses[..., 2])[..., None]
    s = np.sin(poses[..., 2])[..., None]
    hx = hull[None, None, :, 0]
    hy = hull[None, None, :, 1]
    px = poses[..., 0][..., None] + hx * c - hy * s
    py = poses[..., 1][..., None] + hx * s + hy * c
    return np.stack((px, py), axis=-1)


class ShieldLite:
    """v7.5 shield as a (N,2) wheel-fraction action filter, N <= 4 envs."""

    def __init__(self, wrapped, spec, v_full: float,
                 wheel_separation: float = WHEEL_SEPARATION):
        self.env = wrapped
        self.n = wrapped.num_envs
        self.device = wrapped.device
        self.v_full = float(v_full)                     # m/s at |action| = 1
        self.w_full = 2.0 * self.v_full / float(wheel_separation)  # rad/s
        sx, sy = float(spec["size"][0]), float(spec["size"][1])
        self._half = np.array([0.5 * sx, 0.5 * sy])     # tile centre -> corner
        self._size = np.array([sx, sy])                  # barrier's domain
        # genmaps boxes are (x, y, yaw, sx, sy, z); BoxSDF wants the first five
        boxes = [tuple(float(v) for v in b[:5]) for b in spec["boxes"]]
        self.sdf = BoxSDF(boxes, bounds=(0.0, 0.0, sx, sy))
        if not hasattr(wrapped, "_geo_field"):
            raise ValueError(
                "ShieldLite needs the geodesic waypoint env (use_waypoint_obs / "
                "use_geodesic_progress) for the backup policy direction")
        # precompute the fixed candidate-set arc hulls (robot frame).
        # Realizability filter (Stack A only): wheel fractions saturate at
        # +-1, so a twist is exactly realizable iff |v|/v_full + |w|/w_full
        # <= 1 (va + wa = max(|aL|, |aR|)). policy_node did not need this --
        # the bridge chassis realized the published twist directly -- but
        # here a certified (0.5, 0.9) would be silently shrunk by the
        # actuator to a twist whose arc was never checked. Dropping the
        # unrealizable pairs only removes commands the plant cannot follow.
        cv, cw = (x.ravel() for x in
                  np.meshgrid(SHIELD_V_SET, SHIELD_W_SET, indexing="ij"))
        keep = (np.abs(cv) / self.v_full
                + np.abs(cw) / self.w_full) <= 1.0 + 1e-9
        cv, cw = cv[keep], cw[keep]
        self._cv, self._cw = cv, cw
        p56 = _arc_poses(cv, cw)
        self._pts56 = _arc_hull(p56, SHIELD_HULL_PTS)
        self._end56 = p56[:, -1, :].copy()
        ev = np.array([x for x in SHIELD_V_SET if abs(x) <= SHIELD_ESCAPE_VMAX])
        ev, ew = (x.ravel() for x in
                  np.meshgrid(ev, SHIELD_W_SET, indexing="ij"))
        keepe = (np.abs(ev) / self.v_full
                 + np.abs(ew) / self.w_full) <= 1.0 + 1e-9
        ev, ew = ev[keepe], ew[keepe]
        self._ev, self._ew = ev, ew
        p35 = _arc_poses(ev, ew)
        self._pts35raw = _arc_hull(p35, SHIELD_HULL_PTS_RAW)
        self._end35 = p35[:, -1, :].copy()
        # per-env shield state (reset on dones)
        self.last_pub = [(0.0, 0.0)] * self.n
        self.pinned = [False] * self.n
        self.pin_ticks = [0] * self.n
        self.pin_xy = [None] * self.n
        self._wp = None
        # counters (mirror policy_node's summary)
        self.n_shield = self.n_hyst = self.n_escape = self.n_pin = 0
        self.n_oob = 0        # env-ticks spent outside the barrier's domain
        self.n_retreat = 0    # tier-3 (uncertified retreat) firings, subset of
                              # n_escape -- the tier the leak came from (17.18)
        self._steps = 0

    # ------------------------------------------------------------ geometry
    def _field(self, pts, xy, yaw):
        """(C, K, H, 2) robot-frame hull points -> (C, K) min exact-field
        clearance per arc step (negative = hull inside a box)."""
        c0, s0 = math.cos(yaw), math.sin(yaw)
        wx = xy[0] + pts[..., 0] * c0 - pts[..., 1] * s0
        wy = xy[1] + pts[..., 0] * s0 + pts[..., 1] * c0
        return self.sdf.sample(wx, wy).min(axis=2)

    def _waypoint_u(self, e):
        """Unit robot-frame direction to the env's geodesic waypoint (lazy:
        computed once per tick, only if a backup actually runs)."""
        if self._wp is None:
            pos = self.env._robot.data.root_pos_w.torch
            self._wp = self.env._geo_waypoint(pos[:, :2]).cpu().numpy()
        ux, uy = float(self._wp[e, 0]), float(self._wp[e, 1])
        nrm = math.hypot(ux, uy)
        return (ux / nrm, uy / nrm) if nrm > 1e-6 else (1.0, 0.0)

    # ------------------------------------------------------------ v7.5 flow
    def _shield_env(self, e, v, w, xy, yaw):
        """One env, one tick: port of policy_node._apply_shield (v7.4) with
        the lidar-raster and recovery paths removed (see module docstring) and
        the v7.5 escape-tier fall-through fix (ledger 17.19).
        Returns the published twist (m/s, rad/s)."""
        pv, pw = self.last_pub[e]

        if self.pin_xy[e] is None:
            self.pin_xy[e] = xy.copy()
        moved = float(np.linalg.norm(xy - self.pin_xy[e]))
        if self.pinned[e] and moved >= SHIELD_PIN_RELEASE:
            self.pinned[e] = False
            self.pin_ticks[e] = 0
            self.pin_xy[e] = xy.copy()
            moved = 0.0

        def latch(vetoed):
            """Pin latch: a vetoed command without motion is the livelock
            signature (geometric, v7)."""
            if not vetoed:
                self.pin_ticks[e] = 0
                if not self.pinned[e]:
                    self.pin_xy[e] = xy.copy()
                return
            if self.pinned[e]:
                return                       # keep the release anchor
            if moved < SHIELD_PIN_MOVE:
                self.pin_ticks[e] += 1
            else:
                self.pin_ticks[e] = 1
                self.pin_xy[e] = xy.copy()
            if self.pin_ticks[e] >= SHIELD_PIN_TICKS:
                self.pinned[e] = True
                self.pin_xy[e] = xy.copy()
                self.n_pin += 1
                print(f"[shield-lite] env {e}: pinned at "
                      f"({xy[0]:+.2f},{xy[1]:+.2f}) -> escape prefers reverse")

        def backup(vs_, ws_, ends, sel):
            """Goal-directed selection over a certified-safe subset: horizon
            progress toward the geodesic waypoint plus heading alignment
            (robot-frame form of policy_node's backup; the world-frame
            rotation cancels because the displacement and the waypoint
            direction are rotated by the same yaw)."""
            ux, uy = self._waypoint_u(e)
            g = (ends[:, 0] * ux + ends[:, 1] * uy
                 + SHIELD_BACKUP_ALIGN * np.cos(
                     ends[:, 2] - math.atan2(uy, ux)))
            if (float(vs_[-1]), float(ws_[-1])) == self.last_pub[e]:
                g[-1] += SHIELD_HYST_BONUS
            return int(sel[np.argmax(g[sel])])

        # tier 1: policy twist first, then the last published twist -- but
        # NEITHER while the pin latch is held (v7.4: certified-safe policy
        # micro-twists otherwise abort the backup's re-aim every other tick).
        p1 = _arc_poses(np.array([v, pv]), np.array([w, pw]))
        ok = (self._field(_arc_hull(p1, SHIELD_HULL_PTS), xy, yaw).min(axis=1)
              >= SHIELD_MARGIN + SHIELD_ESDF_SLACK)
        if ok[0] and not self.pinned[e]:
            latch(False)
            return v, w
        self.n_shield += 1
        if ok[1] and not self.pinned[e] and (pv != 0.0 or pw != 0.0):
            self.n_hyst += 1
            latch(True)
            return pv, pw
        latch(True)
        pinned = self.pinned[e]

        # comfort batch: fixed 56-candidate set + the last published twist
        pp = _arc_poses(np.array([pv]), np.array([pw]))
        cv = np.concatenate([self._cv, [pv]])
        cw = np.concatenate([self._cw, [pw]])
        clr = np.concatenate([
            self._field(self._pts56, xy, yaw),
            self._field(_arc_hull(pp, SHIELD_HULL_PTS), xy, yaw)])
        ends = np.concatenate([self._end56, pp[:, -1, :]], axis=0)
        safe = clr.min(axis=1) >= SHIELD_MARGIN + SHIELD_ESDF_SLACK
        # projection onto the safe set (CBF-QP form): closest admissible twist
        score = -((cv - v) ** 2 + (SHIELD_W_SCALE * (cw - w)) ** 2)
        score[-1] += SHIELD_HYST_BONUS       # continuity beats a marginal win
        idx = np.nonzero(safe)[0]
        best = (0.0, 0.0)
        if idx.size:
            i = int(idx[np.argmax(score[idx])])
            if pinned or abs(cv[i]) < 0.1:
                i = backup(cv, cw, ends, idx)  # projection would freeze
            best = (float(cv[i]), float(cw[i]))
        if best == (0.0, 0.0):
            # a pure-rotation winner is PROGRESS and is published as-is (v7.3);
            # only a full stop means the comfort tier is locked -> escape tier
            have_prev = abs(pv) <= SHIELD_ESCAPE_VMAX
            ev, ew = self._ev, self._ew
            clre = self._field(self._pts35raw, xy, yaw)
            ends_e = self._end35
            if have_prev:
                ev = np.concatenate([ev, [pv]])
                ew = np.concatenate([ew, [pw]])
                clre = np.concatenate([
                    clre, self._field(_arc_hull(pp, SHIELD_HULL_PTS_RAW), xy, yaw)])
                ends_e = np.concatenate([ends_e, pp[:, -1, :]], axis=0)
            esafe = clre.min(axis=1) >= SHIELD_ESCAPE_MARGIN + SHIELD_ESDF_SLACK
            sgn = -1.0 if pinned else 1.0    # back out when pinned (v6)
            tv = (sgn * max(0.10, min(abs(v), SHIELD_ESCAPE_VMAX))
                  if pinned else v)
            escore = -((ev - tv) ** 2 + (SHIELD_W_SCALE * (ew - w)) ** 2)
            if have_prev:
                escore[-1] += SHIELD_HYST_BONUS
            j = np.nonzero(esafe)[0]
            if j.size:
                i = int(j[np.argmax(escore[j])])
                if ev[i] == 0.0:
                    i = backup(ev, ew, ends_e, j)  # same freeze guard at floor
                if ev[i] != 0.0 or ew[i] != 0.0:
                    self.n_escape += 1
                    return float(ev[i]), float(ew[i])
                # v7.5: backup() ALSO returned a full STOP. Corridor trap
                # (f1_b0_m01, ledger 17.19): the geodesic waypoint is FORWARD,
                # so every certified reverse mover scores negative progress, and
                # the last_pub STOP carries SHIELD_HYST_BONUS -- together they
                # make the stop win backup() even though certified movers exist.
                # v7.4 fell through to `return best` (==(0,0)) here because tier
                # 3 lived in the `else:` of `if j.size:`; with last_pub=(0,0) the
                # bonus re-selected the stop every tick -> an ABSORBING freeze
                # (the pin latch releases only on 0.20 m of motion that never
                # comes). Restrict to certified MOVERS so the escape tier can
                # never publish (0,0) while one is admissible.
                mover = j[(ev[j] != 0.0) | (ew[j] != 0.0)]
                if mover.size:
                    i = int(mover[np.argmax(escore[mover])])
                    self.n_escape += 1
                    return float(ev[i]), float(ew[i])
            # tier 3: no certified non-stop escape (escape set empty, or only
            # STOPs are certified) -- uncertified retreat. Maximize clearance
            # gain (end-of-horizon + worst-along-arc); the clearance gradient IS
            # the direction signal. The old 0.05*sgn*ev bias pressed the robot
            # INTO walls when unpinned (-> PhysX depenetration ejection through
            # the 0.125 m perimeter, the map exit) and, when pinned, let STOP
            # (ev=0) win the argmax -- an absorbing freeze, since the pin latch
            # releases only on 0.20 m of translation (ledger 17.18).
            gain = clre[:, -1] + clre.min(axis=1) + 0.02 * np.abs(ew)
            # v7.6 EXPERIMENT (REVERTED, ledger 17.19 item 7): adding
            # `if have_prev: gain[-1] += SHIELD_HYST_BONUS` here stopped the
            # 20 Hz tier-3 dither and fixed the trained-arm m01 scrape, but
            # the bonus is a LOCK-IN where nothing is certified -- it created
            # two NEW scrapes (thesis arm m01 env 0, trained arm m00 env 1).
            # Tier 3 keeps no continuity term: dither is net-stationary and
            # empirically safer than committed uncertified motion.
            if pinned:
                # forbid the absorbing STOP: tier 3 MUST translate so the
                # pin latch can release and the BoxSDF ramp can recover.
                move = np.abs(ev) > 0.03
                if move.any():
                    gain = np.where(move, gain, -np.inf)
            i = int(np.argmax(gain))
            self.n_escape += 1
            self.n_retreat += 1
            return float(ev[i]), float(ew[i])
        return best

    # ------------------------------------------------------------- shim API
    def action(self, a: torch.Tensor) -> torch.Tensor:
        """Filter per-wheel actions (N, 2); exact no-op when nothing fires."""
        with torch.inference_mode():
            self._wp = None
            pos = self.env._robot.data.root_pos_w.torch
            q = self.env._robot.data.root_quat_w.torch
            yaw_t = torch.atan2(2.0 * (q[:, 2] * q[:, 3] + q[:, 0] * q[:, 1]),
                                1.0 - 2.0 * (q[:, 1] ** 2 + q[:, 2] ** 2))
            # world -> tile-centre -> corner-local (map spec frame)
            xy = ((pos[:, :2]
                   - self.env._terrain.env_origins[: self.n, :2]).cpu().numpy()
                  + self._half)
            # off-model instrument: the barrier only models the map rectangle,
            # so an excursion outside it is exactly where a guarantee could be
            # lost. Counted per env-tick and reported once (ledger 17.18: the
            # third arm's collision was found from pin coordinates alone).
            oob = ((xy < 0.0) | (xy > self._size)).any(axis=1)
            if oob.any():
                self.n_oob += int(oob.sum())
                if self.n_oob == int(oob.sum()):
                    e0 = int(np.argmax(oob))
                    print(f"[shield-lite] env {e0}: OFF THE MAP at "
                          f"({xy[e0, 0]:+.2f},{xy[e0, 1]:+.2f}) -- barrier "
                          f"out of its modelled domain, ramp recovery engaged")
            yaw = yaw_t.cpu().numpy()
            v = (0.5 * (a[:, 0] + a[:, 1])).cpu().numpy() * self.v_full
            w = (0.5 * (a[:, 1] - a[:, 0])).cpu().numpy() * self.w_full
            out_v = np.empty(self.n)
            out_w = np.empty(self.n)
            changed = False
            for e in range(self.n):
                cv, cw = self._shield_env(e, float(v[e]), float(w[e]),
                                          xy[e], float(yaw[e]))
                out_v[e], out_w[e] = cv, cw
                self.last_pub[e] = (float(cv), float(cw))
                if (cv, cw) != (float(v[e]), float(w[e])):
                    changed = True
            self._steps += self.n
            if not changed:
                return a  # exact no-op: keep the frozen command bit-for-bit
            av = out_v / self.v_full
            aw = out_w / self.w_full
            out = torch.tensor(np.stack([av - aw, av + aw], axis=1),
                               device=a.device, dtype=a.dtype)
            # per-wheel clamp = actuator saturation of the velocity targets
            return out.clamp(-1.0, 1.0)

    def reset(self, dones: torch.Tensor):
        for e in dones.nonzero().squeeze(-1).cpu().tolist():
            self.last_pub[e] = (0.0, 0.0)
            self.pinned[e] = False
            self.pin_ticks[e] = 0
            self.pin_xy[e] = None

    def stats(self) -> dict:
        return {"shield": self.n_shield, "hyst": self.n_hyst,
                "escape": self.n_escape, "retreat": self.n_retreat,
                "pin": self.n_pin,
                "oob": self.n_oob, "steps": self._steps}
