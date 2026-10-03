#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NMTE deploy-time rung: frozen Isaac-Lab policy driven over plain ROS 2 topics.

Paper-1 justification for the ROS 2 part of the pipeline: the SAME frozen
checkpoint used inside Isaac Lab (`bc_init_v3/model_0.pt`, trained in the
source wall-maze world) is deployed here UNCHANGED through the standard
sensor/actuator contract — no Lab env, no simulator internals:

    in : /openmover/hardware/lidar_forward/scan   (sensor_msgs/LaserScan)
         /openmover/hardware/lidar_rear/scan      (sensor_msgs/LaserScan)
         /odom                                    (nav_msgs/Odometry)
    out: /cmd_vel                                 (geometry_msgs/Twist)

The node is the deploy-time interface the paper claims: a simulator-agnostic
process between topics. On a real robot the same node would consume bluesea2
scans and wheel-encoder odometry and publish to the chassis cmd_vel.

Observation fidelity (must match openmover_lab/openmover_nav_env.py exactly —
the policy is frozen, so the observation contract is the whole transfer):
  obs = [front_scan(600), rear_scan(600), goal_robot(2), vx, wz,
         waypoint(3), contact(1)] = 1208 dims
  - scans normalized /10.0, invalid returns -> 1.0 (Lab clamps misses to max)
  - goal in robot frame / 2.55 (0.5*(goal_min_radius+goal_max_radius))
  - vx raw body speed, wz / 5.0
  - waypoint = geodesic-descent pure-pursuit point ~1 m ahead toward the goal
    on an occupancy-inflated distance field (replicates _geo_waypoint; the
    Lab env builds that field from simulator-truth terrain boxes, so here it is built from the SAME warehouse collision boxes 15_build_warehouse.py
    bakes into the Isaac scene — a stand-in for a map_server/SLAM map;
    custom-map mode builds it from the map_file JSON instead)
  - contact force is simulator-internal and has no bridge topic; the rung
    uses a CHASSIS-SPEED STALL proxy instead: commanded speed minus the
    pose-differentiated chassis speed, deadbanded, clipped to [0, 1] (the
    real-robot analog is fused-localization vs commanded velocity; encoder
    twist was rejected because at a corner the wheels keep spinning and mask
    the stall). Two findings from the bring-up (docs/isaac/06_results.md §9):
    * the frozen policy has NO learned stall response — the BC collector
      recorded pre-collision steps only, so the expert's back-up behavior
      was never cloned;
    * therefore the rung adds a deploy-time RECOVERY layer (nav2-style
      backup recovery, bounded and logged), triggered both by the stall
      signal (push-without-motion, absolute + relative shortfall) and by a
      nav2-style PROGRESS CHECKER — the policy can also freeze WITHOUT
      pushing (OOD hesitation: saturated scans + contact=0 -> ~zero
      actions). The policy stays frozen; recovery is the rung component.
    * when the robot sits inside the inflation margin, the waypoint IS the
      nearest free cell — get back to free space first, then re-plan
      (nav2 recovery behavior); field descent from inside the margin either
      collapses onto the robot's own cell or jumps across the pocket.

Action: per-wheel fractions in [-1, 1] (clipped exactly like the Lab wrapper),
converted to a Twist with the TRAINED robot's kinematics (openmover: wheel
radius 0.050353 m, separation 0.324 m, wheel_max_speed 10 rad/s). The Isaac
bridge then re-maps to its pioneer3dx plant (0.32/0.09): linear speed is
preserved exactly by that chain, angular within 1.25% — a deliberate
embodiment mismatch, part of what the rung measures.

Run (ROS side, sourced workspace + Jazzy; torch+rclpy come from isaaclab's
python, which reuses Isaac Sim's bundled interpreter):
  ~/isaaclab/isaaclab.sh -p src/warehouse_simulation/scripts/policy_node.py \
      --ros-args -p goal_x:=6.0 -p goal_y:=8.0

Custom-map mode ("draw, then go"): -p map_file:=<map json> builds the
geodesic field from the SAME spec the Isaac bridge bakes into its scene
(17_bridge_ros_custommap.py) and takes the goal from the map; goal_x/goal_y
are ignored in that mode.
"""

import json
import math

import numpy as np

# --------------------------------------------------------------------- actor
import torch
import torch.nn as nn

OBS_DIM = 1208
ACT_DIM = 2


def load_actor(checkpoint: str) -> nn.Module:
    """Rebuild the rsl_rl MLP actor (128-128, elu, no obs normalization) and
    load the frozen weights. No rsl_rl import needed at deploy time."""
    ckpt = torch.load(checkpoint, map_location="cpu", weights_only=False)
    sd = ckpt["actor_state_dict"]
    mlp = nn.Sequential(
        nn.Linear(OBS_DIM, 128), nn.ELU(),
        nn.Linear(128, 128), nn.ELU(),
        nn.Linear(128, ACT_DIM),
    )
    own = mlp.state_dict()
    mapping = {"0.weight": "mlp.0.weight", "0.bias": "mlp.0.bias",
               "2.weight": "mlp.2.weight", "2.bias": "mlp.2.bias",
               "4.weight": "mlp.4.weight", "4.bias": "mlp.4.bias"}
    for k_dst, k_src in mapping.items():
        own[k_dst] = sd[k_src]
    mlp.load_state_dict(own)
    mlp.eval()
    return mlp


# ------------------------------------------------------- observation contract
N_SAMPLES = 600
LIDAR_MAX = 10.0
GOAL_NORM = 2.55          # 0.5 * (goal_min_radius 1.5 + goal_max_radius 3.6)
WZ_SCALE = 5.0

# contact channel: chassis-speed stall proxy. shortfall = |commanded speed| −
# |pose-differentiated chassis speed|. Deadband absorbs servo lag and
# acceleration transients; anything beyond it saturates toward 1.0 to match
# the Lab channel (force/threshold = 1.0 the instant the hull touches).
STALL_V_TOL = 0.06        # m/s shortfall deadband
STALL_V_SCALE = 0.08      # m/s shortfall beyond deadband mapping to ~1
STALL_MIN_CMD = 0.02      # m/s: below this the robot is not trying to move
STALL_REAL_FRAC = 0.5     # realized < 50% of commanded starts the relative
                          # stall branch (saturates at < 15%); acceleration
                          # transients stay below this and don't register
CONTACT_EMA = 0.8         # fast rise: pose-differentiated speed is noisy at
                          # 20 Hz, and a hard stall must reach the recovery
                          # trigger within ~1 s (slow EMA plateaus ~0.8)

# deploy-time recovery layer (nav2-style backup recovery). BC recorded
# pre-collision steps only, so the frozen policy never learned the expert's
# back-up unstuck behavior; the rung re-adds it here, triggered by the same
# stall signal. Bounded: fixed backup duration + cooldown, alternating turn
# sign so repeated activations change the approach angle.
RECOVERY_CONTACT_TRIG = 0.7   # contact EMA level that counts as pushing
RECOVERY_STALL_TICKS = 20     # 1.0 s at 20 Hz of push-without-motion
RECOVERY_BACKUP_TIME = 1.5    # s of reverse drive per activation
RECOVERY_BACKUP_V = -0.25     # m/s
RECOVERY_BACKUP_W = 0.30      # rad/s, sign alternates per activation
RECOVERY_COOLDOWN = 1.0       # s before another activation is allowed
RECOVERY_PROGRESS_TIME = 6.0  # s of no displacement before progress recovery
RECOVERY_PROGRESS_DIST = 0.10 # m of displacement that resets the checker

# deploy-time SAFETY SHIELD (CBF-lite arm, docs §8): a classical
# curvature-space (DWA-style) velocity filter between the frozen policy and
# the chassis.  Division of labour is the claim: the learned policy provides
# competence (what to do), the shield provides the guarantee (never hit a
# mapped wall).  Every candidate twist is forward-simulated over a horizon
# plus a braking tail; only safe twists are admissible, and (0,0) always is,
# so the filter can always keep the hull outside the walls.
#
# v7 barrier (ledger 17.9). v1-v6 certified candidates against a RASTER of
# persisted lidar hits sampled with 17 sparse hull points, which the exact-box
# audit of 17.8 measured to be 4-9 cm optimistic: hits snap to a 0.08 m
# lattice, the dilation is a 2-cell disk, and the hull samples left
# 0.11-0.22 m gaps along the long edge -- the same order as a 0.125 m wall,
# so a thin box slid BETWEEN samples while the hull rotated (both v3
# negatives are exactly that, both by a hull corner). The primary barrier is
# now an EXACT signed-distance field over the known static map boxes
# (BoxSDF below -- the same boxes the geodesic field and the bridge scene are
# built from, i.e. the map_server/SLAM map of the deployment story) sampled
# on a perimeter-densified hull, so SHIELD_MARGIN is a certified clearance
# floor against the TRUE geometry. The lidar raster is kept as a UNION
# barrier, which is what covers anything not in that map.
#
# Last-seen persistence: obstacle points are buffered in the world frame per
# lidar beam and never forgotten (the map is static).  Without persistence a
# wall closer than the bluesea2 NEAR clip (0.22 m) drops out of the scan and
# the raster barrier goes blind to it (v1/v2-early lesson: 0.22 m margin +
# 0.1 m range bias deadlocked the corner spawn — rotation candidates swept
# the hull corner inside the dilated zone).
SHIELD_MARGIN = 0.10      # m hull-surface clearance enforced on candidates
SHIELD_HORIZON = 0.8      # s of constant-twist arc simulated per candidate
SHIELD_BRAKE_A = 0.6      # m/s^2 braking decel for the stop tail
SHIELD_DT = 0.05          # s arc integration step
SHIELD_GRID_RES = 0.08    # m lidar-raster resolution (robot frame)
SHIELD_GRID_EXT = 2.6     # m lidar-raster half extent
SHIELD_V_SET = (-0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
SHIELD_W_SET = (-0.9, -0.6, -0.3, 0.0, 0.3, 0.6, 0.9)
# --- exact-geometry barrier (v7) ------------------------------------------
SHIELD_ESDF_RES = 0.025   # m signed-distance-field lattice over the map boxes
SHIELD_ESDF_HALO = 1.0    # m: a box only refines the field inside this halo,
                          # outside it the field is clamped at HALO (far above
                          # any margin the shield asks about)
SHIELD_ESDF_PAD = 0.60    # m field extent beyond the drivable bounds
SHIELD_ESDF_SLACK = 0.05  # m certified-floor slack. Bounds the bilinear
                          # sampling error of a 1-Lipschitz field on the
                          # 0.025 m lattice (<= RES*sqrt(2) = 0.035) plus the
                          # hull perimeter discretisation (<= spacing/2 =
                          # 0.015): a candidate accepted at
                          # `margin + SLACK` on the field really does keep the
                          # hull >= `margin` off the TRUE boxes.
SHIELD_HULL_SPACING = 0.03  # m hull perimeter sample spacing (48 pts + centre)
SHIELD_ESCAPE_MARGIN = 0.02  # m certified clearance floor of the escape tier
SHIELD_UNMAPPED_TOL = 0.05  # m: a lidar hit whose exact-field value is at most
                          # this is "explained by the map" and is dropped from
                          # the conservative raster (which would otherwise
                          # double-count it 4-9 cm pessimistically, ledger
                          # 17.8). 0.05 > the bilinear sampling error bound
                          # RES*sqrt(2) = 0.035, so true map surfaces are
                          # always dropped while anything the map does not know
                          # about (moved crate, person) survives.
# Two-tier barrier escape: in a tight pocket the comfort envelope can outrun
# the clearance the hull actually keeps, so NO forward candidate stays outside
# it and the robot livelocks in place rotation (tour goal-3). When the comfort
# tier can only stop/rotate, retry at the escape floor (v7: SHIELD_ESCAPE_MARGIN
# against the exact field, plus the RAW lidar raster with the hull grown by
# SHIELD_RAW_PAD) under a low speed cap, so the robot can creep out. Still
# collision-free -- a certified 2 cm floor is the physical no-touch bar.
SHIELD_ESCAPE_VMAX = 0.20  # m/s cap on escape-tier candidates
SHIELD_LIDAR_X = (0.22015, -0.22015)  # front/rear mount x in hull frame
SHIELD_LIDAR_YAW = (0.0, math.pi)     # front/rear sensor yaw in hull frame
_SHIELD_K = int(math.ceil(SHIELD_MARGIN / SHIELD_GRID_RES))
SHIELD_DISK = [(di, dj)                      # euclidean dilation kernel
               for di in range(-_SHIELD_K, _SHIELD_K + 1)
               for dj in range(-_SHIELD_K, _SHIELD_K + 1)
               if di * di + dj * dj <= _SHIELD_K * _SHIELD_K]
# --- chatter control (v7, ledger 17.8) ------------------------------------
# v6 re-picked the best candidate every tick. Near the barrier two opposite
# twists score within noise of each other, so the published command alternated
# +0.10/-0.10 m/s at 20 Hz while the robot realized ~0.01 m/s: the stall proxy
# oscillated with it and, being gated on |prev_cmd_v|, reported pinned=0 in
# 13/14 fortress escapes, so v6's reverse-preferring escape never engaged and
# the robot dithered ~80 s at +0.05 m clearance. Hysteresis keeps the last
# admissible twist unless a new one clearly beats it; the pin latch detects the
# same livelock GEOMETRICALLY (vetoed command + no motion) instead of through
# the chassis-speed proxy alone.
SHIELD_W_SCALE = 0.25     # m per rad/s: weights an angular deviation against a
                          # linear one in the safe-set projection (a 1 rad/s yaw
                          # rate sweeps the 0.22 m hull corner at ~0.22 m/s)
SHIELD_BACKUP_ALIGN = 0.15  # m-equivalent weight of heading alignment in the
                          # freeze-case backup objective (see _apply_shield)
SHIELD_HYST_BONUS = 0.05  # squared-(m/s) score bonus for repeating the last
                          # published twist (projection units, see _apply_shield)
SHIELD_PIN_TICKS = 10     # vetoed ticks (0.5 s at 20 Hz) without motion -> pin
SHIELD_PIN_MOVE = 0.03    # m of motion per tick that counts as "not stuck"
SHIELD_PIN_RELEASE = 0.20  # m of motion that clears a latched pin


def _hull_perimeter(hx=0.22, hy=0.14, spacing=SHIELD_HULL_SPACING):
    """Hull sample points: the centre plus the rectangle perimeter at
    ~`spacing`.

    v6 used 17 points (corners + edge mid/quarter points), leaving 0.11-0.22 m
    gaps along the 0.44 m edges -- the same order as a 0.125 m wall, so a thin
    box could sit entirely between two samples while the hull rotated into it
    (ledger 17.8). A distance field is only a barrier if it is sampled densely
    enough that no obstacle fits between samples: at 0.03 m spacing the
    discretisation costs at most spacing/2 = 0.015 m, which
    SHIELD_ESDF_SLACK pays for."""
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
# Raster checks still need the grown hull: lidar points land ON the wall face
# while the true box IS that face, so rounding a hull point to a 0.08 m cell
# can place it a cell past a sensed point, i.e. ~6 cm inside the true box (v6
# fix -- the exact field makes it unnecessary for mapped geometry, but the
# raster half of the union barrier still quantises).
SHIELD_RAW_PAD = 0.08     # m hull growth for lidar-RASTER checks
SHIELD_HULL_PTS_RAW = np.array(
    [(math.copysign(abs(x) + SHIELD_RAW_PAD, x) if x else 0.0,
      math.copysign(abs(y) + SHIELD_RAW_PAD, y) if y else 0.0)
     for x, y in SHIELD_HULL_PTS])

# trained-robot kinematics (openmover URDF + openmover_nav_cfg.py)
WHEEL_RADIUS = 0.050353
WHEEL_MAX_SPEED = 10.0    # rad/s
WHEEL_SEPARATION = 0.324  # m (wheel joints at y = +-0.162)
ACTION_CLIP = 1.0         # rsl_rl clip_actions of the frozen deployment
GOAL_SUCCESS_DIST = 0.30  # env goal_success_dist

# geodesic field (openmover_nav_cfg.py: geo_res, geo_inflate, waypoint_lookahead)
GEO_RES = 0.25
# Lab trains with geo_inflate=0.20, but its terrain walls are thick and
# continuous. The warehouse has thin free-standing boxes whose corners a
# 0.327 m hull half-diagonal snags on at 0.20 m inflation. Deploy-time maps
# are inflated by the footprint (the nav2 inflation layer does exactly this),
# so the rung uses a footprint-aware inflation instead.
GEO_INFLATE = 0.35
LOOKAHEAD = 1.0

# warehouse collision set — IDENTICAL to isaac/scripts/15_build_warehouse.py
# (workcell boxes offset by the workcell pose; axis-aligned; floor excluded).
WC_X, WC_Y = -0.040107, 0.052292
WORKCELL_BOXES = [
    # (x, y, sx, sy) — z is irrelevant for the 2D grid; walls/racks/pallets/…
    (4.13686, -10.0212, 12.0768, 0.72902),    # wall1
    (-6.58151, -8.924, 10.5921, 5.00198),     # wall2
    (-9.25721, 0.6135, 0.72902, 15.2908),     # wall3
    (7.35056, 1.7443, 0.84444, 1.95581),      # rack1
    (5.36795, 1.7443, 0.84444, 1.95581),      # rack2
    (7.00142, -7.6467, 0.84444, 3.91162),     # rack3
    (4.97338, -7.6467, 0.84444, 3.91162),     # rack4
    (2.66949, -7.6467, 0.84444, 3.91162),     # rack5
    (-3.33609, 6.31883, 2.14726, 1.79349),    # large_pallet1
    (-5.74492, 6.31883, 2.14726, 1.79349),    # large_pallet2
    (-7.55868, 1.91644, 2.14726, 1.79432),    # large_pallet3
    (-5.29667, 1.91644, 2.14726, 1.79349),    # empty_pallet1
    (-1.09806, 6.31883, 2.14726, 1.79349),    # box_pallet1
    (5.02174, -2.39478, 0.49161, 0.49161),    # pole1
    (0.47071, -2.39478, 0.49161, 0.49161),    # pole2
    (-3.93786, -2.39478, 0.49161, 0.49161),   # pole3
    (2.07015, 1.16224, 0.86733, 0.6001),      # control_panel
]
BIN_FOOTPRINTS = [(0.0, 0.0, 0.66836, 0.66836), (0.0, 0.0, 0.6, 0.6)]
BIN_POSES = [(3, 6), (4, 6), (5, 6), (6, 6), (7, 6), (8, 6)]
FLOOR_HALF = 20.1026 / 2.0


def default_boxes():
    """Warehouse collision set + drivable bounds, shared by the geodesic field
    and the shield's exact-distance barrier (both must see the SAME geometry)."""
    boxes = [(x + WC_X, y + WC_Y, 0.0, sx, sy)
             for x, y, sx, sy in WORKCELL_BOXES]
    for bx, by in BIN_POSES:
        for lx, ly, sx, sy in BIN_FOOTPRINTS:
            boxes.append((bx + lx, by + ly, 0.0, sx, sy))
    bounds = (WC_X - FLOOR_HALF, WC_Y - FLOOR_HALF,
              WC_X + FLOOR_HALF, WC_Y + FLOOR_HALF)
    return boxes, bounds


class GeoField:
    """Occupancy grid + geodesic distance field + waypoint extraction,
    replicating openmover_nav_env._build_occupancy_grid / _update_geo_fields /
    _geo_waypoint on a single static numpy grid (world frame)."""

    def __init__(self, boxes=None, bounds=None):
        """boxes: [(x, y, yaw, sx, sy)] in world frame; bounds: drivable
        extent (x0, y0, x1, y1). Defaults reproduce the warehouse collision
        set (axis-aligned workcell boxes + bins, floor footprint)."""
        if boxes is None:
            boxes, bounds = default_boxes()
        # grid covers the drivable extent + 0.5 m margin
        self.x0 = bounds[0] - 0.5
        self.y0 = bounds[1] - 0.5
        self.nx = int(math.ceil((bounds[2] - bounds[0] + 1.0) / GEO_RES))
        self.ny = int(math.ceil((bounds[3] - bounds[1] + 1.0) / GEO_RES))
        cx = self.x0 + (np.arange(self.nx) + 0.5) * GEO_RES
        cy = self.y0 + (np.arange(self.ny) + 0.5) * GEO_RES
        gx_m, gy_m = np.meshgrid(cx, cy, indexing="ij")  # (nx, ny)
        occ = np.zeros((self.nx, self.ny), dtype=bool)
        pad = GEO_INFLATE
        for bx, by, yaw, sx, sy in boxes:
            c, s = math.cos(yaw), math.sin(yaw)
            dx, dy = gx_m - bx, gy_m - by
            lx = c * dx + s * dy
            ly = -s * dx + c * dy
            occ |= ((np.abs(lx) <= 0.5 * sx + pad)
                    & (np.abs(ly) <= 0.5 * sy + pad))
        # outside the drivable extent is not drivable
        fx0, fy0, fx1, fy1 = bounds
        occ |= ((gx_m < fx0) | (gx_m > fx1) | (gy_m < fy0) | (gy_m > fy1))
        self.occ = occ
        self.field = None

    def cell_idx(self, xy):
        ix = int(np.clip((xy[0] - self.x0) / GEO_RES, 0, self.nx - 1))
        iy = int(np.clip((xy[1] - self.y0) / GEO_RES, 0, self.ny - 1))
        return ix, iy

    def cell_center(self, ix, iy):
        return (self.x0 + (ix + 0.5) * GEO_RES, self.y0 + (iy + 0.5) * GEO_RES)

    def build(self, goal_xy):
        """Bellman 8-connected relaxation from the goal cell (Lab's
        _update_geo_fields), then the 8-pass finite-fill of inf cells."""
        ix, iy = self.cell_idx(goal_xy)
        dist = np.full((self.nx, self.ny), np.inf)
        dist[ix, iy] = 0.0
        diag = GEO_RES * math.sqrt(2.0)
        for _ in range(400):
            d = dist
            nd = d.copy()
            nd[:-1, :] = np.minimum(nd[:-1, :], d[1:, :] + GEO_RES)
            nd[1:, :] = np.minimum(nd[1:, :], d[:-1, :] + GEO_RES)
            nd[:, :-1] = np.minimum(nd[:, :-1], d[:, 1:] + GEO_RES)
            nd[:, 1:] = np.minimum(nd[:, 1:], d[:, :-1] + GEO_RES)
            nd[:-1, :-1] = np.minimum(nd[:-1, :-1], d[1:, 1:] + diag)
            nd[:-1, 1:] = np.minimum(nd[:-1, 1:], d[1:, :-1] + diag)
            nd[1:, :-1] = np.minimum(nd[1:, :-1], d[:-1, 1:] + diag)
            nd[1:, 1:] = np.minimum(nd[1:, 1:], d[:-1, :-1] + diag)
            nd[self.occ] = np.inf
            if np.array_equal(nd, d):
                break
            dist = nd
        for _ in range(8):
            d = dist
            nd = d.copy()
            nd[:-1, :] = np.minimum(nd[:-1, :], d[1:, :])
            nd[1:, :] = np.minimum(nd[1:, :], d[:-1, :])
            nd[:, :-1] = np.minimum(nd[:, :-1], d[:, 1:])
            nd[:, 1:] = np.minimum(nd[:, 1:], d[:, :-1])
            dist = np.where(np.isfinite(d), d, nd)
        self.field = dist
        finite = np.isfinite(dist[~self.occ])
        return finite.any() and finite.all()

    def waypoint(self, xy, yaw):
        """Replica of _geo_waypoint: occupancy-masked 4-connected greedy
        descent ~LOOKAHEAD m toward the goal, chord-checked pure pursuit,
        returned in robot frame / GOAL_NORM (+ remaining geodesic distance)."""
        ix0, iy0 = self.cell_idx(xy)
        d_geo = self.field[ix0, iy0]
        if self.occ[ix0, iy0]:
            # Robot inside the inflation margin (physically possible: the
            # hull reaches further than the inflation). Waypoints through
            # the field would either collapse onto the robot's own cell
            # (chord checks from inside the margin reject everything) or
            # jump to the far side of the pocket, pointing the robot at the
            # wall it already touches. nav2's recovery behavior is simpler
            # and works: get back to free space FIRST. The waypoint is the
            # nearest free cell (ring search); normal planning resumes once
            # the robot is on free ground.
            for r in range(1, 9):
                for dx in range(-r, r + 1):
                    for dy in range(-r, r + 1):
                        if max(abs(dx), abs(dy)) != r:
                            continue
                        nx_, ny_ = ix0 + dx, iy0 + dy
                        if (0 <= nx_ < self.nx and 0 <= ny_ < self.ny
                                and not self.occ[nx_, ny_]):
                            sx, sy = self.cell_center(nx_, ny_)
                            rel = np.array([sx, sy]) - np.asarray(xy)
                            c, s = math.cos(yaw), math.sin(yaw)
                            return ((c * rel[0] + s * rel[1]) / GOAL_NORM,
                                    (-s * rel[0] + c * rel[1]) / GOAL_NORM,
                                    d_geo / GOAL_NORM)
            # no free cell within 8 cells: fall through with own cell
            ix, iy = ix0, iy0
        else:
            ix, iy = ix0, iy0
        moves = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        acc = 0.0
        done = self.field[ix, iy] <= 1e-3
        chain = [(ix, iy)]
        for _ in range(int(math.ceil(LOOKAHEAD / GEO_RES)) + 4):
            if done:
                break
            best_v, best_m = np.inf, None
            for mx, my in moves:
                nx_, ny_ = (min(max(ix + mx, 0), self.nx - 1),
                            min(max(iy + my, 0), self.ny - 1))
                if self.occ[nx_, ny_]:
                    continue
                if self.field[nx_, ny_] < best_v:
                    best_v, best_m = self.field[nx_, ny_], (nx_, ny_)
            if best_m is None:      # dead end: keep last cell
                break
            ix, iy = best_m
            acc += GEO_RES
            chain.append((ix, iy))
            if acc >= LOOKAHEAD or best_v <= 1e-3:
                break
        nodes = np.array([self.cell_center(cix, ciy) for cix, ciy in chain])
        if len(nodes) < 2:
            wp = nodes[0]
        else:
            seg = np.linalg.norm(np.diff(nodes, axis=0), axis=1)
            cum = np.concatenate([[0.0], np.cumsum(seg)])
            s_max = min(np.linalg.norm(nodes[0] - np.asarray(xy)) + LOOKAHEAD,
                        cum[-1])
            S = 24
            s_grid = np.linspace(0.0, 1.0, S) * s_max
            pts = np.empty((S, 2))
            for k, s in enumerate(s_grid):
                j = int(np.clip(np.searchsorted(cum, s, side="right") - 1,
                                0, len(nodes) - 2))
                f = np.clip((s - cum[j]) / max(cum[j + 1] - cum[j], 1e-4),
                            0.0, 1.0)
                pts[k] = nodes[j] + f * (nodes[j + 1] - nodes[j])
            # chord check: farthest sample whose straight segment from the
            # robot crosses no occupied cell (10 samples along the segment).
            # The robot is on a free cell here (inside-margin cases return
            # above). If no chord clears at all, keep the nearest sample.
            fracs = np.linspace(0.1, 1.0, 10)
            sel = 0
            for k in range(S):
                pp = np.asarray(xy)[None, :] + fracs[:, None] * (
                    pts[k] - np.asarray(xy))[None, :]
                clear = True
                for p in pp:
                    cix, ciy = self.cell_idx(p)
                    if self.occ[cix, ciy]:
                        clear = False
                        break
                if clear:
                    sel = k
            wp = pts[sel]
        c, s = math.cos(yaw), math.sin(yaw)
        rel = wp - np.asarray(xy)
        gx = c * rel[0] + s * rel[1]
        gy = -s * rel[0] + c * rel[1]
        return gx / GOAL_NORM, gy / GOAL_NORM, d_geo / GOAL_NORM


class BoxSDF:
    """Exact signed-distance field to a union of boxes: the shield's v7 barrier.

    `d[i, j]` is the TRUE distance from lattice node (x0 + i*res, y0 + j*res) to
    the nearest box surface, negative inside a box, clamped at
    +SHIELD_ESDF_HALO beyond that halo of every box (the shield never asks about
    a margin anywhere near that large, and clamping keeps the build windowed per
    box instead of O(boxes x cells)). Nodes outside the drivable bounds are set
    to -1: the edge of the map is a wall.

    Why exact geometry: the quantity a run is graded on
    (30_clearance_audit.py) is hull-vs-box clearance, so a barrier built from
    lidar hits can only ever approximate what is being certified -- v6's was
    4-9 cm optimistic (ledger 17.8). Sampling this field on a perimeter-densified
    hull turns SHIELD_MARGIN into a floor on the audited quantity itself. The
    boxes are the map the geodesic field is already built from, i.e. the
    map_server/SLAM map of the deployment story; the lidar raster is unioned
    with this barrier at runtime so unmapped obstacles still veto.
    """

    def __init__(self, boxes, bounds, res=SHIELD_ESDF_RES,
                 pad=SHIELD_ESDF_PAD):
        self.res = res
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
            # exact signed distance to a rectangle: face/corner distance
            # outside, -min penetration depth inside
            dw = (np.hypot(np.maximum(ox, 0.0), np.maximum(oy, 0.0))
                  + np.minimum(np.maximum(ox, oy), 0.0)).astype(np.float32)
            sub = d[i0:i1, j0:j1]
            np.minimum(sub, dw, out=sub)
        cx = self.x0 + np.arange(self.nx) * res
        cy = self.y0 + np.arange(self.ny) * res
        outside = (((cx < bounds[0]) | (cx > bounds[2]))[:, None]
                   | ((cy < bounds[1]) | (cy > bounds[3]))[None, :])
        d[outside] = -1.0
        self.d = d

    def sample(self, wx, wy):
        """Bilinear sample at world points (any shape) -> signed distance.
        Out-of-grid points return -1 (treated as wall)."""
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
        return np.where(inside, val, np.float32(-1.0))


# ------------------------------------------------------------------ ROS node
import rclpy  # noqa: E402
from rclpy.node import Node  # noqa: E402
from geometry_msgs.msg import Twist  # noqa: E402
from nav_msgs.msg import Odometry  # noqa: E402
from sensor_msgs.msg import LaserScan  # noqa: E402


def normalize_scan(msg: LaserScan) -> np.ndarray | None:
    """Bridge bins -> Lab scan semantics: /10.0, invalid (0.0) -> 1.0."""
    if len(msg.ranges) != N_SAMPLES:
        return None
    r = np.asarray(msg.ranges, dtype=np.float32)
    out = np.clip(r, 0.0, LIDAR_MAX) / LIDAR_MAX
    out[(r <= 0.0) | (r >= LIDAR_MAX)] = 1.0
    return out


class PolicyNode(Node):
    def __init__(self):
        super().__init__("nmte_policy_node")
        self.declare_parameter("checkpoint",
                               "isaac/lab/logs/rsl_rl/openmover_nav/"
                               "bc_init_v3/model_0.pt")
        self.declare_parameter("goal_x", 6.0)
        self.declare_parameter("goal_y", 8.0)
        self.declare_parameter("rate", 20.0)
        self.declare_parameter("duration", 90.0)
        self.declare_parameter("map_file", "")
        self.declare_parameter("blind_waypoint", False)
        self.blind_wp = self.get_parameter("blind_waypoint").value
        self.declare_parameter("shield", False)
        self.shield_on = self.get_parameter("shield").value
        ckpt = self.get_parameter("checkpoint").value
        self.duration = self.get_parameter("duration").value

        self.actor = load_actor(ckpt)
        map_file = self.get_parameter("map_file").value
        if map_file:
            # custom-map deploy: occupancy from the SAME map JSON the Isaac
            # bridge bakes into its scene (17_bridge_ros_custommap.py), tile
            # corner at world (0,0). Goal comes from the map ("draw, then
            # go"); goal_x/goal_y are ignored in this mode.
            with open(map_file) as f:
                spec = json.load(f)
            boxes = [(float(b[0]), float(b[1]), float(b[2]),
                      float(b[3]), float(b[4])) for b in spec["boxes"]]
            bounds = (0.0, 0.0,
                      float(spec["size"][0]), float(spec["size"][1]))
            self.geo = GeoField(boxes=boxes, bounds=bounds)
            self.goal = np.array([float(spec["goal"][0]),
                                  float(spec["goal"][1])])
            # serial multi-goal task: optional ordered "goals" list in the
            # map JSON; the policy advances on arrival and rebuilds the
            # geodesic field per leg (transfer to task composition).
            glist = spec.get("goals")
            self.goals = ([np.array([float(g[0]), float(g[1])])
                           for g in glist] if glist else [self.goal.copy()])
            self.goal = self.goals[0].copy()
            self.goal_idx = 0
            self.get_logger().info(
                f"[policy] map_file {map_file} ('{spec['name']}'): "
                f"{len(boxes)} boxes, {len(self.goals)} goal(s) from map")
        else:
            boxes, bounds = default_boxes()
            self.geo = GeoField(boxes=boxes, bounds=bounds)
            self.goal = np.array([self.get_parameter("goal_x").value,
                                  self.get_parameter("goal_y").value])
            self.goals = [self.goal.copy()]
            self.goal_idx = 0
        ok = self.geo.build(self.goal)
        self.get_logger().info(
            f"[policy] geodesic field built ({self.geo.nx}x{self.geo.ny} "
            f"cells, res {GEO_RES}); goal cell reachable={ok}")
        # shield v7 barrier: exact signed-distance field over the SAME boxes
        # the geodesic field / bridge scene use, so the certified margin is a
        # floor on the quantity the clearance audit measures
        self.sdf = BoxSDF(boxes, bounds)
        self.get_logger().info(
            f"[shield] v7 exact ESDF {self.sdf.nx}x{self.sdf.ny} @ "
            f"{SHIELD_ESDF_RES} m over {len(boxes)} boxes; margin "
            f"{SHIELD_MARGIN} m + slack {SHIELD_ESDF_SLACK} m, hull "
            f"{len(SHIELD_HULL_PTS)} pts @ {SHIELD_HULL_SPACING} m spacing, "
            f"escape floor {SHIELD_ESCAPE_MARGIN} m")

        self.scan_f = None
        self.scan_r = None
        self.odom = None
        self.contact_ema = 0.0   # chassis-speed stall proxy -> contact channel
        self.prev_cmd_v = 0.0    # linear speed published on the last tick
        self.prev_xy = None      # for pose-differentiated chassis speed
        self.prev_pose_t = None
        self.contact_ticks = 0   # consecutive push-without-motion ticks
        self.recovering = False  # recovery layer state
        self.recover_t0 = 0.0
        self.recover_sign = 1.0
        self.progress_xy = None  # nav2-style progress checker anchor
        self.progress_t = 0.0
        self.last_recover_end = -1e9
        self.n_recoveries = 0
        self.n_shield = 0        # ticks the shield modified the command
        self.n_escape = 0        # ticks the escape tier engaged
        self.n_hyst = 0          # ticks resolved by repeating the last twist
        self.n_pin = 0           # geometric pin latches
        self.last_pub = (0.0, 0.0)   # last published twist (hysteresis anchor)
        self.pinned = False      # geometric pin latch (veto + no motion)
        self.pin_ticks = 0
        self.pin_xy = None       # displacement anchor for the latch
        self.shield_hits = None  # per-beam last-seen world hits (persistence)
        self.create_subscription(LaserScan,
                                 "/openmover/hardware/lidar_forward/scan",
                                 lambda m: setattr(self, "scan_f", m), 10)
        self.create_subscription(LaserScan,
                                 "/openmover/hardware/lidar_rear/scan",
                                 lambda m: setattr(self, "scan_r", m), 10)
        self.create_subscription(Odometry, "/odom",
                                 lambda m: setattr(self, "odom", m), 10)
        self.pub = self.create_publisher(Twist, "/cmd_vel", 10)
        rate = self.get_parameter("rate").value
        self.create_timer(1.0 / rate, self.tick)
        self.t_start = None     # sim time of first command
        self.t_reach = None
        self.last_log = 0.0
        self.get_logger().info(
            f"[policy] frozen checkpoint {ckpt}; goal "
            f"({self.goal[0]:.2f}, {self.goal[1]:.2f}); {rate:.0f} Hz; "
            f"duration {self.duration:.0f} s")

    def _pose(self):
        p = self.odom.pose.pose.position
        q = self.odom.pose.pose.orientation
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                         1.0 - 2.0 * (q.y * q.y + q.z * q.z))
        return np.array([p.x, p.y]), yaw

    def _update_hits(self, xy, yaw):
        """Last-seen persistence: store each valid beam's WORLD hit in a
        per-beam buffer, never clearing it (the map is static).  This keeps
        walls in the grid even after they drop below the NEAR clip, so the
        shield never goes blind at close range."""
        c, s = math.cos(yaw), math.sin(yaw)
        if self.shield_hits is None:
            self.shield_hits = [np.full((len(m.ranges), 2), np.nan)
                                for m in (self.scan_f, self.scan_r)]
        for k, (msg, mx, myaw) in enumerate(
                zip((self.scan_f, self.scan_r),
                    SHIELD_LIDAR_X, SHIELD_LIDAR_YAW)):
            r = np.asarray(msg.ranges, dtype=np.float64)
            ok = (np.isfinite(r) & (r >= msg.range_min)
                  & (r < LIDAR_MAX))
            if not ok.any():
                continue
            a = (msg.angle_min
                 + np.arange(r.size) * msg.angle_increment) + yaw + myaw
            rr = r[ok]
            ox = xy[0] + mx * c          # sensor mount in world
            oy = xy[1] + mx * s
            self.shield_hits[k][ok] = np.stack(
                (ox + rr * np.cos(a[ok]), oy + rr * np.sin(a[ok])), axis=1)

    def _obstacle_grid(self, xy, yaw):
        """Boolean obstacle grids in the robot frame for the UNMAPPED half of
        the barrier.  Cell (i, j) covers x = -EXT + j*RES, y = -EXT + i*RES.
        Returns (raw, dilated): raw marks cells containing a sensed point the
        map does NOT explain; dilated is raw expanded by a disk of
        ceil(SHIELD_MARGIN / RES) cells so a hull point checked against it
        keeps the hull at least SHIELD_MARGIN away from that obstacle.

        v7: hits that land on mapped geometry are dropped here. The exact field
        already certifies those with a real margin, while the raster version of
        the same wall is strictly more conservative (grazing hits scatter, the
        dilation disk is 2 cells, cell rounding adds up to RES/2) -- that
        mismatch is what churned the escape tier 889 times in the 17.8
        warehouse run. Keeping only unexplained hits is also the honest
        deployment split: map_server geometry is certified exactly, anything
        the map does not know about (a moved crate, a person) is treated
        conservatively from the sensor."""
        n = int(round(2.0 * SHIELD_GRID_EXT / SHIELD_GRID_RES)) + 1
        g = np.zeros((n, n), dtype=bool)
        c, s = math.cos(yaw), math.sin(yaw)
        for pts in self.shield_hits:
            m = np.isfinite(pts).all(axis=1)
            if not m.any():
                continue
            q = pts[m]
            if self.sdf is not None:
                q = q[self.sdf.sample(q[:, 0], q[:, 1]) > SHIELD_UNMAPPED_TOL]
                if not q.shape[0]:
                    continue
            dx = q[:, 0] - xy[0]
            dy = q[:, 1] - xy[1]
            x = dx * c + dy * s          # world -> robot frame
            y = -dx * s + dy * c
            jj = np.round((x + SHIELD_GRID_EXT) / SHIELD_GRID_RES).astype(int)
            ii = np.round((y + SHIELD_GRID_EXT) / SHIELD_GRID_RES).astype(int)
            mm = (ii >= 0) & (ii < n) & (jj >= 0) & (jj < n)
            g[ii[mm], jj[mm]] = True
        p = np.pad(g, _SHIELD_K, constant_values=False)
        out = np.zeros_like(g)
        for di, dj in SHIELD_DISK:
            out |= p[_SHIELD_K + di:_SHIELD_K + di + n,
                     _SHIELD_K + dj:_SHIELD_K + dj + n]
        return g, out

    def _arc_poses(self, vs, ws):
        """Constant-twist arcs for a whole candidate set at once.

        vs, ws: (C,) -> (C, K, 3) robot-frame poses (x, y, yaw) along
        SHIELD_HORIZON s of the twist plus a straight braking tail at
        SHIELD_BRAKE_A (the v1-v6 arc model unchanged; v <= 0 has no tail).
        Batched because v7 samples ~50 hull points x ~33 steps, which a
        per-candidate Python loop would not fit in the 20 Hz budget."""
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

    def _arc_hull(self, poses, hull):
        """(C, K, 3) arc poses x (H, 2) hull samples -> (C, K, H, 2) robot-frame
        hull sample positions."""
        c = np.cos(poses[..., 2])[..., None]
        s = np.sin(poses[..., 2])[..., None]
        hx = hull[None, None, :, 0]
        hy = hull[None, None, :, 1]
        px = poses[..., 0][..., None] + hx * c - hy * s
        py = poses[..., 1][..., None] + hx * s + hy * c
        return np.stack((px, py), axis=-1)

    def _arc_clearance(self, vs, ws, xy, yaw, hull):
        """(C, K) minimum exact-field clearance over the hull samples at each
        arc step, in metres (negative = hull inside a box)."""
        pts = self._arc_hull(self._arc_poses(vs, ws), hull)
        c0, s0 = math.cos(yaw), math.sin(yaw)
        wx = xy[0] + pts[..., 0] * c0 - pts[..., 1] * s0
        wy = xy[1] + pts[..., 0] * s0 + pts[..., 1] * c0
        return self.sdf.sample(wx, wy).min(axis=2)

    def _barrier_ok(self, vs, ws, xy, yaw, hull, margin, grid=None):
        """(C,) bool: which candidate arcs keep the hull out of the barrier.

        margin  certified clearance floor against the exact map field. The test
                is `field >= margin + SHIELD_ESDF_SLACK`, and the slack bounds
                the lattice + hull-perimeter discretisation, so an accepted arc
                really does keep the hull >= margin off the TRUE boxes. None
                skips that half of the union.
        grid    optional lidar raster to union with (dilated for the comfort
                tier, raw for the escape tier) -- the half of the barrier that
                sees obstacles which are not in the map. Points beyond the
                raster extent cannot be reached inside the horizon (v1-v6).
        """
        pts = self._arc_hull(self._arc_poses(vs, ws), hull)   # robot frame
        ok = np.ones(pts.shape[0], dtype=bool)
        if margin is not None:
            c0, s0 = math.cos(yaw), math.sin(yaw)
            wx = xy[0] + pts[..., 0] * c0 - pts[..., 1] * s0
            wy = xy[1] + pts[..., 0] * s0 + pts[..., 1] * c0
            cl = self.sdf.sample(wx, wy)                       # (C, K, H)
            ok &= cl.min(axis=(1, 2)) >= margin + SHIELD_ESDF_SLACK
        if grid is not None:
            jj = np.round((pts[..., 0] + SHIELD_GRID_EXT)
                          / SHIELD_GRID_RES).astype(np.intp)
            ii = np.round((pts[..., 1] + SHIELD_GRID_EXT)
                          / SHIELD_GRID_RES).astype(np.intp)
            m = ((ii >= 0) & (ii < grid.shape[0])
                 & (jj >= 0) & (jj < grid.shape[1]))
            hit = np.zeros(ii.shape, dtype=bool)
            hit[m] = grid[ii[m], jj[m]]
            ok &= ~hit.any(axis=(1, 2))
        return ok

    def _apply_shield(self, cmd, xy, yaw, recovering=False):
        """CBF-lite velocity filter (DWA-style), v7 barrier (ledger 17.9).

        Same contract as v1-v6 -- the frozen policy proposes, the shield
        disposes, (0,0) is always admissible -- with three changes, all on the
        shield side (the policy is never touched):

        TIER 1 (comfort): the policy twist passes if its arc + braking tail
        keeps the hull >= SHIELD_MARGIN off the EXACT map boxes (BoxSDF) and
        outside the dilated lidar raster; otherwise the best-scoring admissible
        candidate replaces it.
        TIER 2 (escape): if the comfort tier can only stop/rotate, retry at the
        certified floor SHIELD_ESCAPE_MARGIN (raw raster, hull grown by
        SHIELD_RAW_PAD) under SHIELD_ESCAPE_VMAX, preferring reverse when
        pinned.
        TIER 3 (retreat): if even the escape floor is violated the guarantee is
        already lost (the bridge re-maps the twist onto a pioneer3dx chassis, so
        the plant does not track the simulated arc exactly), and freezing inside
        a wall is the worst response: pick the creep-speed candidate that gains
        the most clearance instead.
        Plus HYSTERESIS (repeat the last published twist unless a new candidate
        beats it by SHIELD_HYST_BONUS) and a geometric PIN LATCH, which together
        kill the 20 Hz sign chatter that defeated v6's stall detector (17.8).
        Selection among admissible candidates is a PROJECTION onto the safe set
        (closest twist to the policy's proposal, CBF-QP form): v7's speed-
        rewarding score livelocked the robot in corners (17.10 -> 17.11). When
        the projection would freeze the robot (its winner cannot translate), a
        goal-directed BACKUP policy re-selects inside the same safe set
        (17.11 -> 17.12). While the pin latch is held the backup REPLACES the
        projection (a faithful projection keeps creeping back into the pocket
        that pinned the robot), and a pure-rotation winner counts as progress
        instead of "locked" -- v7.2 fed rotations to the escape tier, which
        overwrote them with reverses so the robot never re-aimed (17.12 ->
        17.13). While latched, tier-1 passthrough of the policy twist is also
        suspended: safe-but-useless micro-twists otherwise abort the re-aim
        every other tick and the robot loiters (17.13 -> 17.14)."""
        self._update_hits(xy, yaw)
        g0, g = self._obstacle_grid(xy, yaw)
        v, w = cmd.linear.x, cmd.angular.z
        pv, pw = self.last_pub
        hull, hull_raw = SHIELD_HULL_PTS, SHIELD_HULL_PTS_RAW

        if self.pin_xy is None:
            self.pin_xy = xy.copy()
        moved = float(np.linalg.norm(xy - self.pin_xy))
        if self.pinned and moved >= SHIELD_PIN_RELEASE:
            self.pinned = False
            self.pin_ticks = 0
            self.pin_xy = xy.copy()
            moved = 0.0
        pinned = (recovering or self.pinned
                  or self.contact_ema >= RECOVERY_CONTACT_TRIG)

        def publish(cv, cw):
            cmd.linear.x, cmd.angular.z = float(cv), float(cw)
            self.last_pub = (float(cv), float(cw))
            return cmd

        def backup(vs_, ws_, sel):
            """Goal-directed selection over a certified-safe subset: horizon
            progress toward the geodesic waypoint plus heading alignment.

            The projection is degenerate when the nominal twist is small and
            unsafe: STOP is then the closest admissible twist (17.11 measured a
            0.001 score gap over a rotation that would have turned the robot
            into the open corridor), and the robot freezes at the certified
            floor. This is the CBF *backup policy*: it only ever chooses inside
            the safe set, so safety still comes from the barrier alone."""
            P = self._arc_poses(vs_, ws_)
            c0, s0 = math.cos(yaw), math.sin(yaw)
            dx = P[:, -1, 0] * c0 - P[:, -1, 1] * s0
            dy = P[:, -1, 0] * s0 + P[:, -1, 1] * c0
            wpx, wpy, _ = self.geo.waypoint(xy, yaw)
            ux, uy = c0 * wpx - s0 * wpy, s0 * wpx + c0 * wpy
            nrm = math.hypot(ux, uy)
            ux, uy = (ux / nrm, uy / nrm) if nrm > 1e-6 else (1.0, 0.0)
            g = (dx * ux + dy * uy
                 + SHIELD_BACKUP_ALIGN * np.cos(
                     yaw + P[:, -1, 2] - math.atan2(uy, ux)))
            if (float(vs_[-1]), float(ws_[-1])) == self.last_pub:
                g[-1] += SHIELD_HYST_BONUS
            return int(sel[np.argmax(g[sel])])

        def latch(vetoed):
            """Pin latch: a vetoed command without motion is the livelock
            signature the chassis-speed stall proxy missed in 17.8."""
            if not vetoed:
                self.pin_ticks = 0
                if not self.pinned:
                    self.pin_xy = xy.copy()
                return
            if self.pinned:
                return                       # keep the release anchor
            if moved < SHIELD_PIN_MOVE:
                self.pin_ticks += 1
            else:
                self.pin_ticks = 1
                self.pin_xy = xy.copy()
            if self.pin_ticks >= SHIELD_PIN_TICKS:
                self.pinned = True
                self.pin_xy = xy.copy()
                self.n_pin += 1
                self.get_logger().info(
                    f"[shield-pin] latched after {self.pin_ticks} vetoed "
                    f"ticks at ({xy[0]:+.2f},{xy[1]:+.2f}) -> escape prefers "
                    f"reverse", throttle_duration_sec=5.0)

        # a recovery backup escapes un-vetoed when it is safe at the floor
        if recovering and self._barrier_ok(np.array([v]), np.array([w]), xy, yaw,
                                           hull_raw, SHIELD_ESCAPE_MARGIN,
                                           g0)[0]:
            latch(False)
            return publish(v, w)

        # tier 1: policy twist first, then the last published twist -- but
        # NEITHER while the pin latch is held: the pocket trap interleaves
        # certified-safe policy micro-twists that pass tier 1 and abort the
        # backup's re-aim rotation every other tick (17.13 run 5: the robot
        # loitered 180 s, backup rotations published but never followed
        # through). While latched, every tick goes through batch + backup.
        ok = self._barrier_ok(np.array([v, pv]), np.array([w, pw]), xy, yaw,
                              hull, SHIELD_MARGIN, g)
        if ok[0] and not self.pinned:
            latch(False)
            return publish(v, w)
        self.n_shield += 1
        if ok[1] and not self.pinned and (pv != 0.0 or pw != 0.0):
            self.n_hyst += 1
            latch(True)
            return publish(pv, pw)
        latch(True)
        pinned = pinned or self.pinned

        cv, cw = (a.ravel() for a in
                  np.meshgrid(SHIELD_V_SET, SHIELD_W_SET, indexing="ij"))
        cv = np.concatenate([cv, [pv]])
        cw = np.concatenate([cw, [pw]])
        safe = self._barrier_ok(cv, cw, xy, yaw, hull, SHIELD_MARGIN, g)
        # projection onto the safe set (CBF-QP form): of the admissible twists,
        # take the one closest to the policy's proposal. v7's score
        # (cv + 0.25|cw|) paid for full-rate rotation and livelocked the robot
        # in corners with a 20 Hz +-0.9 rad/s chatter (ledger 17.10); a safety
        # filter must not carry an objective of its own.
        score = -((cv - v) ** 2 + (SHIELD_W_SCALE * (cw - w)) ** 2)
        score[-1] += SHIELD_HYST_BONUS       # continuity beats a marginal win
        idx = np.nonzero(safe)[0]
        best = (0.0, 0.0)
        if idx.size:
            i = int(idx[np.argmax(score[idx])])
            if self.pinned or abs(cv[i]) < 0.1:
                i = backup(cv, cw, idx)   # projection would freeze: back up
            best = (float(cv[i]), float(cw[i]))
        escape_ok = False
        if best == (0.0, 0.0):
            # a pure-rotation winner is PROGRESS (it re-aims the robot) and is
            # published as-is; only a full stop means the comfort tier is
            # locked -- v7.2 sent rotations to the escape tier, which replaced
            # them with reverses and never let the robot turn (17.12).
            ev = np.array([x for x in SHIELD_V_SET
                           if abs(x) <= SHIELD_ESCAPE_VMAX])
            ev, ew = (a.ravel() for a in
                      np.meshgrid(ev, SHIELD_W_SET, indexing="ij"))
            have_prev = abs(pv) <= SHIELD_ESCAPE_VMAX
            if have_prev:
                ev = np.concatenate([ev, [pv]])
                ew = np.concatenate([ew, [pw]])
            esafe = self._barrier_ok(ev, ew, xy, yaw, hull_raw,
                                     SHIELD_ESCAPE_MARGIN, g0)
            sgn = -1.0 if pinned else 1.0    # back out when pinned (v6)
            # same projection, but the linear target is reversed when pinned so
            # the creep actually backs out of the pocket instead of re-entering
            tv = (sgn * max(0.10, min(abs(v), SHIELD_ESCAPE_VMAX))
                  if pinned else v)
            escore = -((ev - tv) ** 2 + (SHIELD_W_SCALE * (ew - w)) ** 2)
            if have_prev:
                escore[-1] += SHIELD_HYST_BONUS
            j = np.nonzero(esafe)[0]
            escape_ok = bool(j.size)
            if escape_ok:
                i = int(j[np.argmax(escore[j])])
                if ev[i] == 0.0:
                    i = backup(ev, ew, j)  # same freeze guard at the floor
                if ev[i] != 0.0 or ew[i] != 0.0:
                    self.n_escape += 1
                    self.get_logger().info(
                        f"[shield-escape] ({v:+.2f},{w:+.2f}) comfort tier "
                        f"locked -> ({ev[i]:+.2f},{ew[i]:+.2f}) "
                        f"pinned={int(pinned)}", throttle_duration_sec=5.0)
                    return publish(ev[i], ew[i])
            if not escape_ok:
                # tier 3: already inside the escape floor -- retreat
                clr = self._arc_clearance(ev, ew, xy, yaw, hull_raw)
                obj = (clr[:, -1] + clr.min(axis=1)
                       + 0.05 * sgn * ev + 0.02 * np.abs(ew))
                i = int(np.argmax(obj))
                self.n_escape += 1
                self.get_logger().info(
                    f"[shield-retreat] ({v:+.2f},{w:+.2f}) hull inside the "
                    f"escape floor (min clr {clr[i].min():+.3f} m) -> "
                    f"({ev[i]:+.2f},{ew[i]:+.2f}) gains "
                    f"{clr[i, -1] - clr[i, 0]:+.3f} m pinned={int(pinned)}",
                    throttle_duration_sec=5.0)
                return publish(ev[i], ew[i])
        self.get_logger().info(
            f"[shield] ({v:+.2f},{w:+.2f}) unsafe -> "
            f"({best[0]:+.2f},{best[1]:+.2f}) pinned={int(pinned)}",
            throttle_duration_sec=5.0)
        return publish(best[0], best[1])

    def tick(self):
        now = self.get_clock().now().nanoseconds / 1e9
        if self.t_start is not None and now - self.t_start > self.duration:
            self._summary(now)
            raise SystemExit()  # bounded run, like every other gate script
        if self.scan_f is None or self.scan_r is None or self.odom is None:
            return
        front = normalize_scan(self.scan_f)
        rear = normalize_scan(self.scan_r)
        if front is None or rear is None:
            self.get_logger().warn("[policy] unexpected scan layout",
                                   throttle_duration_sec=5.0)
            return
        xy, yaw = self._pose()
        if self.t_start is None:
            self.t_start = now
            self.get_logger().info(f"[policy] first obs at t={now:.2f}, "
                                   f"pose=({xy[0]:+.2f},{xy[1]:+.2f})")

        if self.t_reach is not None:
            # mission complete: park instead of continuing to command toward
            # the already-reached final goal (post-success grinding was
            # pushing the hull into the goal pocket for minutes; iteration-1
            # shielded demo_open audit: approach 0 penetrations, post-success
            # 206 raster-flagged frames until this fix)
            self.prev_cmd_v = 0.0
            self.pub.publish(Twist())
            return

        # observation, EXACT Lab order/normalization
        rel = self.goal - xy
        c, s = math.cos(yaw), math.sin(yaw)
        gx = (c * rel[0] + s * rel[1]) / GOAL_NORM
        gy = (-s * rel[0] + c * rel[1]) / GOAL_NORM
        vx = float(self.odom.twist.twist.linear.x)
        wz = float(self.odom.twist.twist.angular.z) / WZ_SCALE
        # chassis speed from pose differentiation — encoder twist masks
        # stalls (wheels keep spinning against an obstacle)
        v_chassis = 0.0
        if self.prev_xy is not None and now > self.prev_pose_t:
            v_chassis = float(np.linalg.norm(xy - self.prev_xy)
                              / (now - self.prev_pose_t))
        self.prev_xy, self.prev_pose_t = xy.copy(), now
        # contact channel = chassis-speed stall proxy from the LAST command.
        # Two branches: the absolute shortfall (hard stalls at normal speed,
        # calibrated to Lab's saturated contact channel) and a RELATIVE one:
        # the policy's cornering creep can push at v_cmd ~ 0.05 m/s, below
        # the absolute deadband, so a creep-push against a wall would never
        # register. Realized < STALL_REAL_FRAC of commanded saturates it.
        shortfall = max(abs(self.prev_cmd_v) - v_chassis, 0.0)
        proxy = min(max((shortfall - STALL_V_TOL) / STALL_V_SCALE, 0.0), 1.0)
        if abs(self.prev_cmd_v) > STALL_MIN_CMD:
            rel_short = 1.0 - min(v_chassis / abs(self.prev_cmd_v), 1.0)
            onset = 1.0 - STALL_REAL_FRAC
            rel_proxy = min(max((rel_short - onset) / 0.35, 0.0), 1.0)
            proxy = max(proxy, rel_proxy)
        self.contact_ema = ((1.0 - CONTACT_EMA) * self.contact_ema
                            + CONTACT_EMA * proxy)
        wpx, wpy, d_geo = self.geo.waypoint(xy, yaw)
        if self.blind_wp:
            # ablation: zero the geodesic-waypoint channel (framework arm)
            wpx = wpy = d_geo = 0.0
        obs = np.concatenate([front, rear, [gx, gy, vx, wz],
                              [wpx, wpy, d_geo], [self.contact_ema]]
                             ).astype(np.float32)
        with torch.inference_mode():
            act = self.actor(torch.from_numpy(obs).unsqueeze(0)).numpy()[0]
        act = np.clip(act, -ACTION_CLIP, ACTION_CLIP)

        # trained-robot wheel kinematics -> Twist
        wl = act[0] * WHEEL_MAX_SPEED
        wr = act[1] * WHEEL_MAX_SPEED
        cmd = Twist()
        cmd.linear.x = float(WHEEL_RADIUS * (wl + wr) / 2.0)
        cmd.angular.z = float(WHEEL_RADIUS * (wr - wl) / WHEEL_SEPARATION)

        # ------------------------------------------------- recovery layer
        dist = float(np.linalg.norm(self.goal - xy))
        if self.recovering:
            if now - self.recover_t0 >= RECOVERY_BACKUP_TIME:
                self.recovering = False
                self.last_recover_end = now
                self.get_logger().info(
                    f"[policy] recovery #{self.n_recoveries} done")
            else:
                cmd.linear.x = RECOVERY_BACKUP_V
                cmd.angular.z = self.recover_sign * RECOVERY_BACKUP_W
        else:
            if (self.contact_ema >= RECOVERY_CONTACT_TRIG
                    and abs(self.prev_cmd_v) > STALL_MIN_CMD):
                self.contact_ticks += 1
            else:
                self.contact_ticks = 0
            if (self.contact_ticks >= RECOVERY_STALL_TICKS
                    and now - self.last_recover_end >= RECOVERY_COOLDOWN):
                self.recovering = True
                self.recover_t0 = now
                self.recover_sign *= -1.0
                self.contact_ticks = 0
                self.n_recoveries += 1
                self.get_logger().info(
                    f"[policy] stall (contact={self.contact_ema:.2f}, "
                    f"cmd={self.prev_cmd_v:+.2f}, no motion) -> backup "
                    f"recovery #{self.n_recoveries}")
            else:
                # nav2-style progress checker: the policy can also freeze
                # WITHOUT pushing (OOD hesitation: near-saturated scans +
                # contact=0 -> ~zero actions), which the stall trigger never
                # sees. No displacement for RECOVERY_PROGRESS_TIME while far
                # from the goal and emitting small commands -> backup.
                if self.progress_xy is None:
                    self.progress_xy, self.progress_t = xy.copy(), now
                moved = float(np.linalg.norm(xy - self.progress_xy))
                if moved > RECOVERY_PROGRESS_DIST:
                    self.progress_xy, self.progress_t = xy.copy(), now
                elif (now - self.progress_t >= RECOVERY_PROGRESS_TIME
                        and dist > 2.0 * GOAL_SUCCESS_DIST
                        and abs(cmd.linear.x) < 0.05
                        and abs(cmd.angular.z) < 0.25
                        and now - self.last_recover_end >= RECOVERY_COOLDOWN):
                    self.recovering = True
                    self.recover_t0 = now
                    self.recover_sign *= -1.0
                    self.progress_xy, self.progress_t = xy.copy(), now
                    self.n_recoveries += 1
                    self.get_logger().info(
                        f"[policy] no progress for "
                        f"{RECOVERY_PROGRESS_TIME:.0f} s "
                        f"(dist={dist:.2f}, cmd~0) -> backup recovery "
                        f"#{self.n_recoveries}")
        if self.shield_on:
            # v6: tell the shield when a recovery backup is in flight so it
            # never vetoes the backup into a forward grind (ledger 17.4)
            cmd = self._apply_shield(cmd, xy, yaw,
                                     recovering=self.recovering)
        self.prev_cmd_v = cmd.linear.x
        self.pub.publish(cmd)

        if dist < GOAL_SUCCESS_DIST:
            if self.goal_idx < len(self.goals) - 1:
                self.goal_idx += 1
                self.goal = self.goals[self.goal_idx].copy()
                ok = self.geo.build(self.goal)
                self.progress_xy, self.progress_t = xy.copy(), now
                self.get_logger().info(
                    f"[policy] LEG {self.goal_idx}/{len(self.goals) - 1}: "
                    f"goal reached at t={now - self.t_start:.2f}s -> next "
                    f"({self.goal[0]:.2f},{self.goal[1]:.2f}) field_ok={ok}")
            elif self.t_reach is None:
                self.t_reach = now
                self.get_logger().info(
                    f"[policy] REACHED final goal at t={now:.2f} "
                    f"(time-to-goal {now - self.t_start:.2f} s)")
        if now - self.last_log >= 2.0:
            self.last_log = now
            self.get_logger().info(
                f"[policy] t={now - self.t_start:5.1f}s "
                f"pose=({xy[0]:+.2f},{xy[1]:+.2f}) yaw={math.degrees(yaw):+6.1f} "
                f"dist={dist:.2f} cmd=({cmd.linear.x:+.2f},{cmd.angular.z:+.2f}) "
                f"contact={self.contact_ema:.2f}"
                f"{' RECOVERING' if self.recovering else ''}")
            wxw = xy[0] + (c * wpx - s * wpy) * GOAL_NORM
            wyw = xy[1] + (s * wpx + c * wpy) * GOAL_NORM
            self.get_logger().info(
                f"[policy]   wp=({wxw:+.2f},{wyw:+.2f}) "
                f"d_geo={d_geo * GOAL_NORM:.2f}")

    def _summary(self, now):
        if self.t_reach is not None:
            verdict = (f"SUCCESS, {len(self.goals)} goal(s) in "
                       f"{self.t_reach - self.t_start:.2f} s")
        else:
            xy, _ = self._pose()
            verdict = (f"NOT FINISHED ({self.goal_idx}/{len(self.goals)} "
                       f"goals reached, final dist "
                       f"{np.linalg.norm(self.goal - xy):.2f} m)")
        self.get_logger().info(
            f"[policy] SUMMARY: goals "
            f"{'; '.join(f'({g[0]:.1f},{g[1]:.1f})' for g in self.goals)} "
            f"-> {verdict}; ran {now - self.t_start:.1f} s; "
            f"recoveries={self.n_recoveries}; shield_ticks={self.n_shield}"
            f"; escape={self.n_escape}; hyst={self.n_hyst}; pin={self.n_pin}"
            f"{' (shield ON)' if self.shield_on else ''}")


def main():
    rclpy.init()
    node = PolicyNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
